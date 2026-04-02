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
from jobs.news_scraper import find_forecaster
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
    """Fetch analyst ratings from Massive API and insert as predictions.
    No SCRAPER_LOCK needed — _guarded_job provides per-job locking,
    and source_platform_id dedup prevents duplicate inserts."""
    _massive_inner(db)


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
            if _LAST_UPDATED:
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
            # Log URL field availability for first 5 ratings
            url_stats = {"has_url_news": 0, "has_url_calendar": 0, "neither": 0}
            for _r in ratings[:20]:
                un = _r.get("url_news") or _r.get("benzinga_news_url") or ""
                uc = _r.get("url_calendar") or _r.get("benzinga_calendar_url") or ""
                if un and "://" in un:
                    url_stats["has_url_news"] += 1
                elif uc and "://" in uc:
                    url_stats["has_url_calendar"] += 1
                else:
                    url_stats["neither"] += 1
            print(f"[MassiveBZ] URL fields in first 20: {url_stats}")

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

    # Derive call_type
    call_type = _get_call_type(action_lower, rating_current.lower(), pt_current)

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

    # Source URL — prefer real article URLs from the API
    source_url = ""
    for candidate in [url_news, url_calendar]:
        if candidate and candidate.strip() and "://" in candidate and "/quote/" not in candidate:
            source_url = candidate.strip()
            break
    if not source_url:
        source_url = f"https://www.benzinga.com/stock/{ticker.lower()}/ratings"

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
    from jobs.context_formatter import format_context
    context = format_context(canonical, action, rating_current, ticker, target_price)

    # Cross-scraper dedup
    if prediction_exists_cross_scraper(ticker, forecaster.id, direction, pred_date, db):
        return False

    # Validate (may fix source_url)
    is_valid, result = validate_prediction(
        ticker=ticker, direction=direction, source_url=source_url,
        archive_url=source_url, context=context, forecaster_id=forecaster.id,
    )
    if not is_valid:
        return False
    if isinstance(result, dict):
        source_url = result.get("source_url", source_url)

    # Insert
    pred = Prediction(
        forecaster_id=forecaster.id, ticker=ticker, direction=direction,
        prediction_date=pred_date,
        evaluation_date=pred_date + timedelta(days=window_days),
        window_days=window_days, source_url=source_url, archive_url=source_url,
        source_type="article", source_platform_id=source_id,
        external_id=f"bz_{benzinga_id}" if benzinga_id else None,
        target_price=target_price, entry_price=entry_price,
        sector=_get_sector_safe(ticker, db),
        context=context[:500], exact_quote=context,
        outcome="pending", verified_by="massive_benzinga",
        call_type=call_type,
    )
    db.add(pred)
    db.flush()  # Get the prediction ID

    # Notify watchlist users (only for recent predictions, not backfill)
    try:
        from jobs.watchlist_alerts import notify_watchlist_users
        notify_watchlist_users(ticker, pred.id, canonical, direction, target_price, pred_date, db)
    except Exception:
        pass

    return True


def _get_call_type(action_lower: str, rating_lower: str, pt_current) -> str:
    """Derive call_type from action and rating."""
    if "upgrade" in action_lower:
        return "upgrade"
    if "downgrade" in action_lower:
        return "downgrade"
    if "initiate" in action_lower:
        return "new_coverage"
    if pt_current and str(pt_current).strip():
        return "price_target"
    return "rating"


def _get_sector_safe(ticker: str, db) -> str:
    try:
        from jobs.sector_lookup import get_sector
        return get_sector(ticker, db)
    except Exception:
        return "Other"


_NEUTRAL_RATINGS = ["hold", "neutral", "market perform", "market_perform", "equal weight",
                     "equal_weight", "sector perform", "sector_perform", "in line", "in_line",
                     "peer perform", "peer_perform", "sector weight", "sector_weight",
                     "market weight", "market_weight"]


def _get_direction(action_lower: str, rating_lower: str, pt_current, pt_prior) -> str | None:
    """Determine bullish/bearish/neutral from action + rating + price target change.

    CRITICAL: The destination rating (rating_current) determines the direction,
    NOT the action verb. "Downgrades to Hold" = neutral (not bearish).
    "Upgrades to Hold" = neutral (not bullish).
    """
    _BULL = ["buy", "outperform", "overweight", "strong buy", "positive", "accumulate", "add", "top pick"]
    _BEAR = ["sell", "underperform", "underweight", "strong sell", "negative", "reduce", "avoid"]

    # STEP 1: The destination rating always wins.
    # "Downgrades to Hold" → neutral. "Upgrades to Buy" → bullish.
    if any(w in rating_lower for w in _NEUTRAL_RATINGS):
        return "neutral"
    if any(w in rating_lower for w in _BULL):
        # For maintains/reiterates with no PT change, skip (no new information)
        if ("maintains" in action_lower or "reiterates" in action_lower):
            if not pt_current or str(pt_current) == str(pt_prior):
                return None
        return "bullish"
    if any(w in rating_lower for w in _BEAR):
        if ("maintains" in action_lower or "reiterates" in action_lower):
            if not pt_current or str(pt_current) == str(pt_prior):
                return None
        return "bearish"

    # STEP 2: Rating not recognized. Use action as hint.
    if any(w in action_lower for w in ["upgrade", "initiates"]):
        return "bullish"
    if "downgrade" in action_lower:
        return "bearish"

    return None
