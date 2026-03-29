"""
Massive API — Benzinga Analyst Ratings ingestion.
Pulls structured analyst upgrades/downgrades/price targets from the Massive API
and inserts them as predictions into the Eidolum database.

Env: MASSIVE_API_KEY (set in Railway)
Runs: every 2 hours via APScheduler
"""
import os
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Prediction, Forecaster
from jobs.prediction_validator import (
    validate_prediction,
    resolve_forecaster_alias,
    prediction_exists_cross_scraper,
)
from jobs.news_scraper import find_forecaster, SCRAPER_LOCK
from jobs.upgrade_scrapers import _is_self_analysis

MASSIVE_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
API_URL = "https://api.massive.com/benzinga/v1/ratings"
_LAST_UPDATED = None

# Actions to skip entirely — not predictions
SKIP_ACTIONS = {
    "terminates_coverage_on", "removes", "suspends", "firm_dissolved",
    "terminates coverage on", "removes coverage", "suspends coverage",
}


def scrape_massive_ratings(db: Session):
    """Fetch analyst ratings from Massive API and insert as predictions."""
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[MassiveBZ] Another scraper running, skipping")
        return
    try:
        _massive_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _massive_inner(db: Session):
    global _LAST_UPDATED
    if not MASSIVE_KEY:
        print("[MassiveBZ] No MASSIVE_API_KEY set, skipping")
        return

    # Always incremental — backfill is done separately
    if not _LAST_UPDATED:
        _LAST_UPDATED = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"[MassiveBZ] Incremental fetch since {_LAST_UPDATED}")
    max_pages = 5

    added = 0
    skipped = 0
    page = 0
    next_url = None

    while True:
        page += 1

        # Build request
        if next_url:
            url = next_url
            params = {}
        else:
            url = API_URL
            params = {
                "apiKey": MASSIVE_KEY,
                "sort": "last_updated.desc",
                "limit": 500,
            }
            if is_backfill:
                params["date.gte"] = backfill_date
            elif _LAST_UPDATED:
                params["last_updated.gte"] = _LAST_UPDATED

        try:
            r = httpx.get(url, params=params, headers={"Accept": "application/json"}, timeout=30)
            if r.status_code != 200:
                print(f"[MassiveBZ] HTTP {r.status_code}: {r.text[:300]}")
                break

            data = r.json()
        except Exception as e:
            print(f"[MassiveBZ] Request error: {e}")
            break

        # Extract ratings list
        if isinstance(data, list):
            ratings = data
            next_url = None
        elif isinstance(data, dict):
            ratings = data.get("ratings", data.get("results", data.get("data", [])))
            next_url_raw = data.get("next_url") or data.get("next")
            # Append API key to next_url if needed
            if next_url_raw:
                sep = "&" if "?" in next_url_raw else "?"
                next_url = f"{next_url_raw}{sep}apiKey={MASSIVE_KEY}" if "apiKey" not in next_url_raw else next_url_raw
            else:
                next_url = None
        else:
            ratings = []
            next_url = None

        if not ratings:
            if page == 1:
                print(f"[MassiveBZ] No ratings returned. Response: {str(data)[:300]}")
            break

        if page == 1:
            print(f"[MassiveBZ] Page 1: {len(ratings)} ratings. Fields: {list(ratings[0].keys())}")

        for rating in ratings:
            result = _process_rating(rating, db)
            if result:
                added += 1
            else:
                skipped += 1

        # Stop at max pages to avoid runaway pagination
        if not next_url or page >= max_pages:
            break

    if added > 0:
        db.commit()

    _LAST_UPDATED = datetime.utcnow().strftime("%Y-%m-%d")
    print(f"[MassiveBZ] Done: {added} added, {skipped} skipped (pages: {page})")


def _process_rating(rating: dict, db: Session) -> bool:
    """Process a single rating. Returns True if a prediction was inserted."""

    # Extract fields — try multiple key variations
    ticker = (rating.get("ticker") or "").strip().upper()
    firm = (
        rating.get("analyst") or rating.get("firm") or
        rating.get("analyst_firm") or rating.get("analyst_name") or ""
    ).strip()
    action = (
        rating.get("action_company") or rating.get("rating_action") or
        rating.get("action") or ""
    ).strip()
    rating_current = (rating.get("rating_current") or rating.get("rating") or "").strip()
    rating_prior = (rating.get("rating_prior") or rating.get("previous_rating") or "").strip()
    pt_current = rating.get("pt_current") or rating.get("price_target") or ""
    pt_prior = rating.get("pt_prior") or rating.get("previous_price_target") or ""
    date_str = (rating.get("date") or rating.get("last_updated") or "")[:10]
    url_news = rating.get("url_news") or rating.get("benzinga_news_url") or ""
    url_calendar = rating.get("url_calendar") or rating.get("benzinga_calendar_url") or ""
    benzinga_id = rating.get("id") or rating.get("benzinga_id") or ""

    # Must have ticker and firm
    if not ticker or not firm:
        return False

    # Must have a date
    if not date_str or len(date_str) < 8:
        return False

    # Reject garbage firm names
    if len(firm) > 50 or len(firm) < 2:
        return False

    # Layer 1: external_id dedup (benzinga_id is globally unique)
    if benzinga_id:
        ext_id = f"bz_{benzinga_id}"
        if db.execute(text("SELECT 1 FROM predictions WHERE external_id = :eid LIMIT 1"), {"eid": ext_id}).first():
            return False

    # Skip non-prediction actions
    action_lower = action.lower()
    if any(skip in action_lower for skip in SKIP_ACTIONS):
        return False

    # Determine direction
    direction = _get_direction(action_lower, rating_current.lower(), pt_current, pt_prior)
    if not direction:
        return False

    # Resolve firm name
    canonical = resolve_forecaster_alias(firm)
    if _is_self_analysis(canonical, ticker):
        return False

    # Dedup by source_platform_id
    source_id = f"mbz_{ticker}_{canonical}_{date_str}"
    if benzinga_id:
        source_id = f"mbz_{benzinga_id}"

    if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
        return False

    # Source URL
    source_url = url_news or url_calendar or f"https://www.benzinga.com/quote/{ticker}/analyst-ratings"
    if db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": source_url}).first():
        return False

    # Find or create forecaster
    forecaster = find_forecaster(canonical, db)
    if not forecaster:
        return False

    # Parse date
    try:
        pred_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return False

    # Parse price target
    target_price = None
    if pt_current:
        try:
            target_price = float(str(pt_current).replace("$", "").replace(",", ""))
        except (ValueError, TypeError):
            pass

    # Entry price (previous PT)
    entry_price = None
    if pt_prior:
        try:
            entry_price = float(str(pt_prior).replace("$", "").replace(",", ""))
        except (ValueError, TypeError):
            pass

    # Window: 365 days for price targets, 90 for rating changes
    window_days = 365 if target_price else 90

    # Build context
    pt_str = f", PT ${pt_current}" if pt_current else ""
    context = f"{canonical} {action} {rating_current} on {ticker}{pt_str}"

    # Cross-scraper dedup
    if prediction_exists_cross_scraper(ticker, forecaster.id, direction, pred_date, db):
        return False

    # Validate
    is_valid, _ = validate_prediction(
        ticker=ticker, direction=direction, source_url=source_url,
        archive_url=source_url, context=context, forecaster_id=forecaster.id,
    )
    if not is_valid:
        return False

    # Insert
    db.add(Prediction(
        forecaster_id=forecaster.id, ticker=ticker, direction=direction,
        prediction_date=pred_date,
        evaluation_date=pred_date + timedelta(days=window_days),
        window_days=window_days, source_url=source_url, archive_url=source_url,
        source_type="article", source_platform_id=source_id,
        external_id=f"bz_{benzinga_id}" if benzinga_id else None,
        target_price=target_price, entry_price=entry_price,
        context=context[:500], exact_quote=context,
        outcome="pending", verified_by="massive_benzinga",
    ))
    return True


def _get_direction(action_lower: str, rating_lower: str, pt_current, pt_prior) -> str | None:
    """Determine bullish/bearish from action + rating + price target change."""

    # Explicit upgrade/initiate = bullish
    if any(w in action_lower for w in ["upgrade", "initiates"]):
        return "bullish"

    # Explicit downgrade = bearish
    if "downgrade" in action_lower:
        return "bearish"

    # Maintains/reiterates — only valid if PT changed
    if "maintains" in action_lower or "reiterates" in action_lower:
        if not pt_current or str(pt_current) == str(pt_prior):
            return None  # No change = skip
        if any(w in rating_lower for w in ["buy", "outperform", "overweight", "strong buy"]):
            return "bullish"
        if any(w in rating_lower for w in ["sell", "underperform", "underweight", "reduce"]):
            return "bearish"
        return None

    # Fallback: derive from rating name
    if any(w in rating_lower for w in ["buy", "outperform", "overweight", "strong buy", "positive"]):
        return "bullish"
    if any(w in rating_lower for w in ["sell", "underperform", "underweight", "strong sell", "negative", "reduce"]):
        return "bearish"

    return None
