"""
FMP (Financial Modeling Prep) analyst ratings scraper.
Pulls upgrades/downgrades from the FMP stable API and inserts as predictions.

Env: FMP_KEY
Runs: every 4 hours via APScheduler (offset from Benzinga's 2-hour cycle)
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Prediction, Forecaster, Config
from jobs.prediction_validator import (
    validate_prediction,
    resolve_forecaster_alias,
    prediction_exists_cross_scraper,
)
from jobs.news_scraper import find_forecaster
from jobs.upgrade_scrapers import _is_self_analysis
from jobs.massive_benzinga import _get_sector_safe

FMP_KEY = os.getenv("FMP_KEY", "").strip()
FMP_API = "https://financialmodelingprep.com/stable/upgrades-downgrades"

# ── Direction classification ─────────────────────────────────────────────────

_BULLISH_GRADES = {"buy", "strong buy", "strong-buy", "outperform", "overweight", "positive",
                   "accumulate", "top pick", "conviction buy"}
_BEARISH_GRADES = {"sell", "strong sell", "strong-sell", "underperform", "underweight",
                   "negative", "reduce"}
_NEUTRAL_GRADES = {"hold", "neutral", "equal-weight", "equal weight", "market perform",
                   "market-perform", "sector perform", "sector-perform", "in-line",
                   "in line", "peer perform", "sector weight", "market weight"}

_SKIP_ACTIONS = {"removes", "suspends", "terminates", "firm_dissolved"}


def _classify_direction(action: str, new_grade: str, prev_grade: str) -> str | None:
    """Classify into bullish/bearish/neutral.
    The destination grade always determines direction.
    'Downgrades to Hold' = neutral, not bearish."""
    action_l = (action or "").lower().strip()
    grade_l = (new_grade or "").lower().strip()

    if any(s in action_l for s in _SKIP_ACTIONS):
        return None

    # Destination grade always wins
    if grade_l in _NEUTRAL_GRADES:
        return "neutral"
    if grade_l in _BULLISH_GRADES:
        return "bullish"
    if grade_l in _BEARISH_GRADES:
        return "bearish"

    # Grade not recognized — use action as hint
    if action_l in ("upgrade", "init"):
        return "bullish"
    if action_l in ("downgrade",):
        return "bearish"

    return None


def _get_call_type(action: str) -> str:
    action_l = (action or "").lower()
    if "upgrade" in action_l:
        return "upgrade"
    if "downgrade" in action_l:
        return "downgrade"
    if "init" in action_l:
        return "new_coverage"
    return "rating"


# ── Process a single FMP rating ──────────────────────────────────────────────


def _process_fmp_rating(item: dict, db: Session) -> bool:
    """Process one FMP rating item. Returns True if inserted."""
    ticker = (item.get("symbol") or "").strip().upper()
    firm = (item.get("gradingCompany") or "").strip()
    action = (item.get("action") or "").strip()
    new_grade = (item.get("newGrade") or "").strip()
    prev_grade = (item.get("previousGrade") or "").strip()
    date_str = (item.get("publishedDate") or "")[:10]
    news_url = (item.get("newsURL") or item.get("newsUrl") or "").strip()

    if not ticker or not firm or not date_str or len(date_str) < 8:
        return False
    if len(firm) > 50 or len(firm) < 2:
        return False

    direction = _classify_direction(action, new_grade, prev_grade)
    if not direction:
        return False

    call_type = _get_call_type(action)

    # Resolve firm alias
    canonical = resolve_forecaster_alias(firm)
    if _is_self_analysis(canonical, ticker):
        return False

    # Parse date
    try:
        pred_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return False

    # Source dedup
    source_id = f"fmp_{ticker}_{canonical}_{date_str}"
    if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
                  {"sid": source_id}).first():
        return False

    # Cross-scraper dedup (catches overlap with Benzinga)
    forecaster = find_forecaster(canonical, db)
    if not forecaster:
        return False

    if prediction_exists_cross_scraper(ticker, forecaster.id, direction, pred_date, db):
        return False

    # Source URL
    source_url = news_url or f"https://financialmodelingprep.com/quote/{ticker}"

    # Build context
    grade_text = f"{prev_grade} → {new_grade}" if prev_grade and new_grade else new_grade
    context = f"{canonical}: {action} {ticker} to {grade_text}" if grade_text else f"{canonical}: {action} on {ticker}"

    # Window: 90 days for rating changes
    window_days = 90

    # Validate
    is_valid, _ = validate_prediction(
        ticker=ticker, direction=direction, source_url=source_url,
        archive_url=source_url, context=context, forecaster_id=forecaster.id,
    )
    if not is_valid:
        return False

    db.add(Prediction(
        forecaster_id=forecaster.id, ticker=ticker, direction=direction,
        prediction_date=pred_date,
        evaluation_date=pred_date + timedelta(days=window_days),
        window_days=window_days, source_url=source_url, archive_url=source_url,
        source_type="article", source_platform_id=source_id,
        sector=_get_sector_safe(ticker, db),
        context=context[:500], exact_quote=context,
        outcome="pending", verified_by="fmp_ratings",
        call_type=call_type,
    ))
    return True


# ── Incremental scraper (runs every 4 hours) ────────────────────────────────

_last_fmp_date = None


def scrape_fmp_ratings(db: Session):
    """Fetch recent FMP ratings and insert new predictions.
    Does NOT use SCRAPER_LOCK — FMP writes to its own source_platform_id
    prefix (fmp_) so there's no conflict with Benzinga scrapers."""
    _fmp_incremental(db)


def _fmp_incremental(db: Session):
    global _last_fmp_date
    if not FMP_KEY:
        print(f"[FMP] FMP_KEY not set (env value: '{os.getenv('FMP_KEY', '')[:3]}...'), skipping")
        return
    print(f"[FMP] FMP_KEY present: {FMP_KEY[:5]}...")

    if not _last_fmp_date:
        _last_fmp_date = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d")

    today = datetime.utcnow().strftime("%Y-%m-%d")
    print(f"[FMP] Incremental fetch: {_last_fmp_date} to {today}")

    added = 0
    skipped = 0

    try:
        r = httpx.get(FMP_API, params={
            "from": _last_fmp_date,
            "to": today,
            "apikey": FMP_KEY,
        }, timeout=30)

        if r.status_code != 200:
            print(f"[FMP] HTTP {r.status_code}: {r.text[:300]}")
            return

        data = r.json()
        if not isinstance(data, list):
            print(f"[FMP] Unexpected response type: {type(data)}")
            return

        print(f"[FMP] Got {len(data)} ratings")

        for item in data:
            if _process_fmp_rating(item, db):
                added += 1
            else:
                skipped += 1

        if added > 0:
            db.commit()

    except Exception as e:
        print(f"[FMP] Error: {e}")

    _last_fmp_date = today
    print(f"[FMP] Done: {added} added, {skipped} skipped")


# ── Backfill (2020-01-01 → today, month by month) ───────────────────────────


def backfill_fmp_ratings(db: Session, start_date: str = None):
    """Pull FMP historical data month by month from 2018-01-01."""
    return _fmp_backfill_inner(db, start_date)


def _fmp_backfill_inner(db: Session, start_date: str = None) -> dict:
    if not FMP_KEY:
        print("[FMP-Backfill] FMP_KEY not set")
        return {"status": "no_key"}

    # Resume from last position or start from beginning
    if not start_date:
        try:
            row = db.execute(text("SELECT value FROM config WHERE key = 'fmp_backfill_last_date'")).scalar()
            if row:
                start_date = row
        except Exception:
            pass
    if not start_date:
        start_date = "2018-01-01"

    start = datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.utcnow()
    total_added = 0
    total_skipped = 0
    months_processed = 0

    print(f"[FMP-Backfill] Starting from {start_date}")

    current = start
    while current < today:
        month_end = min(current + timedelta(days=30), today)
        from_str = current.strftime("%Y-%m-%d")
        to_str = month_end.strftime("%Y-%m-%d")

        try:
            r = httpx.get(FMP_API, params={
                "from": from_str,
                "to": to_str,
                "apikey": FMP_KEY,
            }, timeout=30)

            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    added = 0
                    for item in data:
                        if _process_fmp_rating(item, db):
                            added += 1
                        else:
                            total_skipped += 1
                    total_added += added
                    if added > 0:
                        db.commit()
                    print(f"[FMP-Backfill] {from_str} to {to_str}: {added} added / {len(data)} total")
            else:
                print(f"[FMP-Backfill] HTTP {r.status_code} for {from_str}")

        except Exception as e:
            print(f"[FMP-Backfill] Error for {from_str}: {e}")

        # Save progress
        try:
            existing = db.execute(text("SELECT 1 FROM config WHERE key = 'fmp_backfill_last_date'")).first()
            if existing:
                db.execute(text("UPDATE config SET value = :v WHERE key = 'fmp_backfill_last_date'"), {"v": to_str})
            else:
                db.execute(text("INSERT INTO config (key, value) VALUES ('fmp_backfill_last_date', :v)"), {"v": to_str})
            db.commit()
        except Exception:
            pass

        months_processed += 1
        current = month_end + timedelta(days=1)

        # Rate limit: 300ms between requests
        time.sleep(0.3)

    print(f"[FMP-Backfill] Complete: {total_added} added, {total_skipped} skipped, {months_processed} months")
    return {"status": "done", "added": total_added, "skipped": total_skipped, "months": months_processed}
