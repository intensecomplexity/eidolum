"""
Benzinga Direct API scraper — structured analyst ratings.
Uses BENZINGA_KEY env var. Returns individual analyst actions with firm name, rating, and price target.
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Prediction, Forecaster
from jobs.prediction_validator import (
    validate_prediction,
    resolve_forecaster_alias,
    TICKER_COMPANY_NAMES,
)
from jobs.news_scraper import find_forecaster, SCRAPER_LOCK
from jobs.upgrade_scrapers import _is_self_analysis

BENZINGA_KEY = os.getenv("BENZINGA_KEY", "")
_LAST_DATE = None


def scrape_benzinga_ratings(db: Session):
    """Scrape analyst ratings from Benzinga's direct API."""
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[Benzinga] Another scraper running, skipping")
        return
    try:
        _benzinga_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _benzinga_inner(db: Session):
    global _LAST_DATE
    if not BENZINGA_KEY:
        print("[Benzinga] No BENZINGA_KEY, skipping")
        return

    params = {
        "token": BENZINGA_KEY,
        "limit": 100,
        "sort": "date.desc",
    }
    if _LAST_DATE:
        params["date_from"] = _LAST_DATE

    try:
        r = httpx.get(
            "https://api.benzinga.com/api/v1/ratings",
            params=params,
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[Benzinga] HTTP {r.status_code}: {r.text[:200]}")
            return

        data = r.json()

        # Handle both list and dict responses
        if isinstance(data, list):
            ratings = data
        elif isinstance(data, dict):
            ratings = data.get("ratings", data.get("results", data.get("data", [])))
        else:
            ratings = []

        if not ratings:
            print(f"[Benzinga] No ratings. Response type: {type(data).__name__}, preview: {str(data)[:300]}")
            return

        # Debug: print first item's fields
        if ratings:
            print(f"[Benzinga] Got {len(ratings)} ratings. Fields: {list(ratings[0].keys())}")

        added = 0
        for rating in ratings:
            ticker = rating.get("ticker", "")
            firm = rating.get("analyst", "") or rating.get("firm", "") or rating.get("analyst_firm", "")
            action = rating.get("action_company", "") or rating.get("rating_action", "") or rating.get("action", "")
            rating_current = rating.get("rating_current", "") or rating.get("rating", "")
            rating_prior = rating.get("rating_prior", "") or rating.get("previous_rating", "")
            pt_current = rating.get("pt_current", "") or rating.get("price_target", "")
            pt_prior = rating.get("pt_prior", "") or rating.get("previous_price_target", "")
            date_str = rating.get("date", "")
            url_news = rating.get("url_news", "") or rating.get("benzinga_news_url", "")
            url_calendar = rating.get("url_calendar", "") or rating.get("benzinga_calendar_url", "")

            if not ticker or not firm:
                continue

            # Direction from action + rating
            direction = None
            action_lower = (action or "").lower()
            rating_lower = (rating_current or "").lower()

            if any(w in action_lower for w in ["upgrades", "upgrade", "initiates"]):
                direction = "bullish"
            elif any(w in action_lower for w in ["downgrades", "downgrade"]):
                direction = "bearish"
            elif "maintains" in action_lower or "reiterates" in action_lower:
                # Maintains only valid if price target changed
                if not pt_current or str(pt_current) == str(pt_prior):
                    continue  # No PT change = noise, skip
                if any(w in rating_lower for w in ["buy", "outperform", "overweight", "strong buy"]):
                    direction = "bullish"
                elif any(w in rating_lower for w in ["sell", "underperform", "underweight", "reduce"]):
                    direction = "bearish"
                else:
                    continue  # Skip neutral maintains
            elif any(w in rating_lower for w in ["buy", "outperform", "overweight", "strong buy", "positive"]):
                direction = "bullish"
            elif any(w in rating_lower for w in ["sell", "underperform", "underweight", "strong sell", "negative", "reduce"]):
                direction = "bearish"

            if not direction:
                continue

            # Resolve firm name
            canonical = resolve_forecaster_alias(firm)
            if _is_self_analysis(canonical, ticker):
                continue

            # Build context
            pt_str = f", PT ${pt_current}" if pt_current else ""
            context = f"{canonical} {action} {rating_current} on {ticker}{pt_str}"

            # Source URL
            source_url = url_news or url_calendar or f"https://www.benzinga.com/quote/{ticker}/analyst-ratings"

            # Deduplicate
            date_clean = (date_str or "")[:10]
            if not date_clean or len(date_clean) < 8:
                continue

            source_id = f"bz_{ticker}_{canonical}_{date_clean}"
            if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
                continue
            if db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": source_url}).first():
                continue

            forecaster = find_forecaster(canonical, db)
            if not forecaster:
                continue

            try:
                pred_date = datetime.strptime(date_clean, "%Y-%m-%d")
            except Exception:
                continue

            # Parse price target
            target_price = None
            if pt_current:
                try:
                    target_price = float(str(pt_current).replace("$", "").replace(",", ""))
                except (ValueError, TypeError):
                    pass

            window_days = 365 if target_price else 90

            is_valid, _ = validate_prediction(
                ticker=ticker.upper(), direction=direction, source_url=source_url,
                archive_url=source_url, context=context, forecaster_id=forecaster.id,
            )
            if not is_valid:
                continue

            db.add(Prediction(
                forecaster_id=forecaster.id, ticker=ticker.upper(), direction=direction,
                prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=window_days),
                window_days=window_days, source_url=source_url, archive_url=source_url,
                source_type="article", source_platform_id=source_id,
                target_price=target_price,
                context=context[:500], exact_quote=context,
                outcome="pending", verified_by="benzinga_api",
            ))
            added += 1

        db.commit()
        _LAST_DATE = datetime.utcnow().strftime("%Y-%m-%d")
        print(f"[Benzinga] Done: {added} predictions added")

    except Exception as e:
        print(f"[Benzinga] Error: {e}")
