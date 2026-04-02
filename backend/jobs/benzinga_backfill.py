"""
Benzinga historical backfill: forward only.

Forward backfill: 2020-01-01 -> today, day by day, chronologically.
Progress stored in Config table so it survives restarts.
Processes 30 days per batch, sleeps 10 seconds between batches.

Connection-safe: opens/closes DB per day, never holds connections during API calls.
"""
import os
import time
import httpx
from datetime import datetime, timedelta, date
from sqlalchemy import text as sql_text
from models import Prediction, Forecaster, Config
from jobs.prediction_validator import (
    validate_prediction,
    resolve_forecaster_alias,
    prediction_exists_cross_scraper,
)
from jobs.news_scraper import find_forecaster
from jobs.upgrade_scrapers import _is_self_analysis

MASSIVE_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
API_URL = "https://api.massive.com/benzinga/v1/ratings"

SKIP_ACTIONS = {
    "terminates_coverage_on", "removes", "suspends", "firm_dissolved",
    "terminates coverage on", "removes coverage", "suspends coverage",
}

FORWARD_START = date(2020, 1, 1)

# ── Global state ─────────────────────────────────────────────────────────────
_backfill_running = False
_backfill_stop = False
_backfill_status = {
    "running": False,
    "phase": None,         # "forward" | None
    "current_date": None,
    "days_completed": 0,
    "predictions_inserted": 0,
    "last_error": None,
    "forward_done": False,
}


def get_backfill_status() -> dict:
    return dict(_backfill_status)


def stop_backfill():
    global _backfill_stop
    _backfill_stop = True


# ── Config helpers ───────────────────────────────────────────────────────────
def _get_config(db, key: str) -> str | None:
    row = db.query(Config).filter(Config.key == key).first()
    return row.value if row else None


def _set_config(db, key: str, value: str):
    row = db.query(Config).filter(Config.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Config(key=key, value=value))
    db.commit()


# ── Main entry point ────────────────────────────────────────────────────────
# No hardcoded stop year. Reverse backfill runs until the API returns nothing.
EMPTY_DAYS_TO_STOP = 30  # Stop after 30 consecutive days with 0 results = end of API data


def run_backfill():
    """Run forward backfill to today, then reverse backfill until API data runs out."""
    global _backfill_running, _backfill_stop, _backfill_status

    if _backfill_running:
        print("[Backfill] Already running")
        return
    if not MASSIVE_KEY:
        print("[Backfill] No MASSIVE_API_KEY")
        return

    _backfill_running = True
    _backfill_stop = False

    try:
        forward_done = _run_forward()
        if forward_done and not _backfill_stop:
            _run_reverse()
    finally:
        _backfill_running = False
        _backfill_status["running"] = False
        _backfill_status["phase"] = None
        print("[Backfill] All backfill phases complete")


def _run_forward() -> bool:
    """Phase 1: Forward backfill from FORWARD_START to today. Returns True if caught up."""
    from database import BgSessionLocal

    db = BgSessionLocal()
    try:
        # Check if already done
        if _get_config(db, "backfill_forward_done") == "true":
            last = _get_config(db, "backfill_last_date")
            print(f"[Forward] Already complete (last={last})")
            _backfill_status["forward_done"] = True
            return True

        # Resume point
        start = FORWARD_START
        resume = _get_config(db, "backfill_last_date")
        if resume:
            try:
                resumed = datetime.strptime(resume, "%Y-%m-%d").date()
                if resumed >= start:
                    start = resumed + timedelta(days=1)
            except Exception:
                pass
    finally:
        db.close()

    end = date.today()
    if start > end:
        # Mark forward as done
        db = BgSessionLocal()
        try:
            _set_config(db, "backfill_forward_done", "true")
        finally:
            db.close()
        _backfill_status["forward_done"] = True
        print(f"[Forward] Already caught up to {end}")
        return True

    total_days = (end - start).days + 1
    _backfill_status.update({
        "running": True, "phase": "forward", "current_date": str(start),
        "days_completed": 0, "predictions_inserted": 0, "last_error": None,
        "forward_done": False,
    })

    print(f"[Forward] {start} -> {end} ({total_days} days)")
    total_inserted = 0
    days_done = 0
    batch_days = 0
    current = start

    while current <= end:
        if _backfill_stop:
            print(f"[Forward] Stopped at {current}")
            return False

        # Storage guard: stop if DB approaching volume limit
        try:
            from circuit_breaker import db_storage_ok
            if not db_storage_ok("forward_backfill"):
                print(f"[Forward] Paused at {current}: storage limit approaching")
                return False
        except Exception:
            pass

        inserted = _process_one_day(current, "backfill_last_date", "Forward")
        total_inserted += inserted
        days_done += 1
        batch_days += 1
        _backfill_status["days_completed"] = days_done
        _backfill_status["predictions_inserted"] = total_inserted
        _backfill_status["current_date"] = str(current)

        current += timedelta(days=1)
        time.sleep(0.2)

        if batch_days >= 90:
            _refresh_stats_if_needed()
            print(f"[Forward] Batch done. {days_done}/{total_days} days, {total_inserted} inserted. Pausing 5s.")
            time.sleep(5)
            batch_days = 0

    # Mark forward complete
    db = BgSessionLocal()
    try:
        _set_config(db, "backfill_forward_done", "true")
    finally:
        db.close()

    _backfill_status["forward_done"] = True
    _refresh_stats_if_needed()
    print(f"[Forward] Complete: {days_done} days, {total_inserted} predictions")
    return True


def _run_reverse() -> bool:
    """Phase 2: Reverse backfill from 2019-12-31 backwards. Stops when API
    returns empty results for EMPTY_DAYS_TO_STOP consecutive days."""
    from database import BgSessionLocal

    db = BgSessionLocal()
    try:
        # Check if already done
        if _get_config(db, "backfill_reverse_done") == "true":
            print("[Reverse] Already complete")
            return True

        # Resume point (going backwards)
        start = date(2019, 12, 31)
        resume = _get_config(db, "benzinga_reverse_backfill_last_date")
        if resume:
            try:
                resumed = datetime.strptime(resume, "%Y-%m-%d").date()
                if resumed < start:
                    start = resumed - timedelta(days=1)
            except Exception:
                pass
    finally:
        db.close()

    _backfill_status.update({
        "running": True, "phase": "reverse", "current_date": str(start),
        "days_completed": 0, "predictions_inserted": 0,
    })

    print(f"[Reverse] Starting from {start} backwards (stops after {EMPTY_DAYS_TO_STOP} consecutive empty days with 0 results)")
    total_inserted = 0
    days_done = 0
    batch_days = 0
    consecutive_empty = 0
    current = start

    while True:
        if _backfill_stop:
            print(f"[Reverse] Stopped at {current}")
            return False

        # Storage guard
        try:
            from circuit_breaker import db_storage_ok
            if not db_storage_ok("reverse_backfill"):
                print(f"[Reverse] Paused at {current}: storage limit approaching")
                return False
        except Exception:
            pass

        inserted = _process_one_day(current, "benzinga_reverse_backfill_last_date", "Reverse")
        total_inserted += inserted
        days_done += 1
        batch_days += 1
        _backfill_status["days_completed"] = days_done
        _backfill_status["predictions_inserted"] = total_inserted
        _backfill_status["current_date"] = str(current)

        # Track consecutive empty days to detect end of API data
        if inserted == 0:
            consecutive_empty += 1
        else:
            consecutive_empty = 0

        if consecutive_empty >= EMPTY_DAYS_TO_STOP:
            print(f"[Reverse] {EMPTY_DAYS_TO_STOP} consecutive empty days at {current} — API has no more data. Marking complete.")
            break

        current -= timedelta(days=1)
        time.sleep(0.2)

        if batch_days >= 90:
            _refresh_stats_if_needed()
            print(f"[Reverse] Batch done. {days_done} days, {total_inserted} inserted. At {current}. Pausing 5s.")
            time.sleep(5)
            batch_days = 0

    db = BgSessionLocal()
    try:
        _set_config(db, "backfill_reverse_done", "true")
    finally:
        db.close()

    _refresh_stats_if_needed()
    print(f"[Reverse] Complete: {days_done} days, {total_inserted} predictions")
    return True


# ── Process a single day ─────────────────────────────────────────────────────
def _process_one_day(day: date, config_key: str, label: str) -> int:
    """Fetch and insert all ratings for one day. Returns number inserted."""
    from database import BgSessionLocal

    day_str = day.strftime("%Y-%m-%d")
    db = BgSessionLocal()
    try:
        inserted, fetched = _fetch_and_insert_day(day_str, db)
        _set_config(db, config_key, day_str)
        if inserted > 0 or fetched > 0:
            print(f"[{label}] {day_str}: fetched={fetched} inserted={inserted}")
        return inserted
    except Exception as e:
        _backfill_status["last_error"] = f"{day_str}: {e}"
        print(f"[{label}] Error on {day_str}: {e}")
        return 0
    finally:
        db.close()


def _refresh_stats_if_needed():
    """Refresh forecaster stats after a batch."""
    try:
        from jobs.historical_evaluator import refresh_all_forecaster_stats
        refresh_all_forecaster_stats()
    except Exception as e:
        print(f"[Backfill] Stats refresh error: {e}")


# ── Auto-resume on startup ──────────────────────────────────────────────────
def auto_resume_backfill():
    """Called on startup. Resumes forward backfill, then reverse until API data runs out."""
    import threading
    if not MASSIVE_KEY:
        print("[Backfill] MASSIVE_API_KEY not set — backfill cannot run")
        return

    from database import BgSessionLocal
    db = BgSessionLocal()
    try:
        forward_done = _get_config(db, "backfill_forward_done") == "true"
        fwd_last = _get_config(db, "backfill_last_date")

        if forward_done and fwd_last:
            last_fwd = datetime.strptime(fwd_last, "%Y-%m-%d").date()
            if last_fwd >= date.today() - timedelta(days=1):
                print(f"[Backfill] Forward already caught up to {fwd_last}. Checking reverse backfill.")
            # Need to catch up new days
            _set_config(db, "backfill_forward_done", "false")
            print(f"[Backfill] Forward needs catch-up from {last_fwd} to today")
        elif fwd_last:
            print(f"[Backfill] Resuming forward from {fwd_last}")
        else:
            print(f"[Backfill] Starting fresh forward from {FORWARD_START}")
    finally:
        db.close()

    threading.Thread(target=run_backfill, daemon=True).start()


# ── API fetch + insert ───────────────────────────────────────────────────────
def _fetch_and_insert_day(day_str: str, db) -> tuple:
    """Fetch all ratings for a single day from the API. Returns (inserted, fetched)."""
    inserted = 0
    fetched = 0
    next_url = None
    page = 0

    while True:
        page += 1
        if next_url:
            url = next_url
            params = {}
        else:
            url = API_URL
            params = {
                "apiKey": MASSIVE_KEY,
                "date.gte": day_str,
                "date.lte": day_str,
                "limit": 500,
                "sort": "last_updated.asc",
            }

        try:
            r = httpx.get(url, params=params, timeout=20)
            if r.status_code != 200:
                break
            data = r.json()
        except Exception as e:
            print(f"[Backfill] API error for {day_str} page {page}: {e}")
            break

        if isinstance(data, list):
            ratings = data
            next_url = None
        elif isinstance(data, dict):
            ratings = data.get("ratings", data.get("results", data.get("data", [])))
            raw_next = data.get("next_url") or data.get("next")
            if raw_next:
                sep = "&" if "?" in raw_next else "?"
                next_url = f"{raw_next}{sep}apiKey={MASSIVE_KEY}" if "apiKey" not in raw_next else raw_next
            else:
                next_url = None
        else:
            break

        if not ratings:
            break

        fetched += len(ratings)

        for rating in ratings:
            try:
                if _insert_rating(rating, db):
                    inserted += 1
            except Exception:
                continue

        if not next_url:
            break

    if inserted > 0:
        db.commit()

    return inserted, fetched


def _insert_rating(rating: dict, db) -> bool:
    """Validate and insert a single rating. Returns True if inserted."""
    ticker = (rating.get("ticker") or "").strip().upper()
    firm = (rating.get("analyst") or rating.get("firm") or rating.get("analyst_firm") or "").strip()
    action = (rating.get("action_company") or rating.get("rating_action") or rating.get("action") or "").strip()
    rating_current = (rating.get("rating_current") or rating.get("rating") or "").strip()
    pt_current = rating.get("pt_current") or rating.get("price_target") or ""
    pt_prior = rating.get("pt_prior") or rating.get("previous_price_target") or ""
    date_str = (rating.get("date") or "")[:10]
    url_news = rating.get("benzinga_news_url") or rating.get("url_news") or ""
    benzinga_id = str(rating.get("id") or rating.get("benzinga_id") or "")

    if not ticker or not firm or not date_str or len(date_str) < 8:
        return False
    if len(firm) > 50:
        return False

    if benzinga_id:
        ext_id = f"bz_{benzinga_id}"
        if db.execute(sql_text("SELECT 1 FROM predictions WHERE external_id = :eid LIMIT 1"), {"eid": ext_id}).first():
            return False

    action_lower = action.lower()
    if any(s in action_lower for s in SKIP_ACTIONS):
        return False

    direction = _get_direction(action_lower, rating_current.lower(), pt_current, pt_prior)
    if not direction:
        return False

    call_type = _get_call_type(action_lower, rating_current.lower(), pt_current)

    canonical = resolve_forecaster_alias(firm)
    if _is_self_analysis(canonical, ticker):
        return False

    forecaster = find_forecaster(canonical, db)
    if not forecaster:
        return False

    try:
        pred_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return False

    if prediction_exists_cross_scraper(ticker, forecaster.id, direction, pred_date, db):
        return False

    target_price = None
    if pt_current:
        try:
            target_price = float(str(pt_current).replace("$", "").replace(",", ""))
        except (ValueError, TypeError):
            pass

    entry_price = None
    if pt_prior:
        try:
            entry_price = float(str(pt_prior).replace("$", "").replace(",", ""))
        except (ValueError, TypeError):
            pass

    window_days = 365 if target_price else 90
    # Prefer real article URLs, reject generic quote pages
    source_url = url_news if url_news and "/quote/" not in url_news else f"https://www.benzinga.com/stock/{ticker}/ratings"
    from jobs.context_formatter import format_context
    context = format_context(canonical, action, rating_current, ticker, target_price)

    is_valid, result = validate_prediction(
        ticker=ticker, direction=direction, source_url=source_url,
        archive_url=source_url, context=context, forecaster_id=forecaster.id,
    )
    if not is_valid:
        return False
    if isinstance(result, dict):
        source_url = result.get("source_url", source_url)

    db.add(Prediction(
        forecaster_id=forecaster.id, ticker=ticker, direction=direction,
        prediction_date=pred_date,
        evaluation_date=pred_date + timedelta(days=window_days),
        window_days=window_days, source_url=source_url, archive_url=source_url,
        source_type="article", source_platform_id=f"mbz_{ticker}_{canonical}_{date_str}",
        external_id=f"bz_{benzinga_id}" if benzinga_id else None,
        target_price=target_price, entry_price=entry_price,
        sector=_get_sector_safe(ticker, db),
        context=context[:500], exact_quote=context,
        outcome="pending", verified_by="massive_benzinga",
        call_type=call_type,
    ))
    return True


def _get_sector_safe(ticker, db):
    try:
        from jobs.sector_lookup import get_sector
        return get_sector(ticker, db)
    except Exception:
        return "Other"


NEUTRAL_RATINGS = {"hold", "neutral", "equal weight", "equal-weight", "market perform",
                   "sector perform", "in-line", "in line", "peer perform", "market weight"}


def _is_neutral_rating(rating_lower):
    return any(n in rating_lower for n in NEUTRAL_RATINGS)


def _get_direction(action_lower, rating_lower, pt_current, pt_prior):
    # Upgrades/initiates → check if target rating is neutral
    if any(w in action_lower for w in ["upgrade", "initiates"]):
        if _is_neutral_rating(rating_lower):
            return "neutral"  # "Upgraded to Hold" = neutral, not bullish
        return "bullish"
    # Downgrades → check if target rating is neutral
    if "downgrade" in action_lower:
        if _is_neutral_rating(rating_lower):
            return "neutral"  # "Downgraded to Hold" = neutral, not bearish
        return "bearish"
    # Maintains/reiterates
    if "maintains" in action_lower or "reiterates" in action_lower:
        if _is_neutral_rating(rating_lower):
            return "neutral"
        if any(w in rating_lower for w in ["buy", "outperform", "overweight", "strong buy"]):
            return "bullish"
        if any(w in rating_lower for w in ["sell", "underperform", "underweight", "reduce"]):
            return "bearish"
        return "neutral"  # Unknown rating on maintains = neutral
    # Standalone ratings
    if any(w in rating_lower for w in ["buy", "outperform", "overweight", "strong buy", "positive"]):
        return "bullish"
    if any(w in rating_lower for w in ["sell", "underperform", "underweight", "strong sell", "negative", "reduce"]):
        return "bearish"
    if _is_neutral_rating(rating_lower):
        return "neutral"
    return None  # Only skip if truly unrecognized


def _get_call_type(action_lower: str, rating_lower: str, pt_current) -> str:
    if "upgrade" in action_lower:
        return "upgrade"
    if "downgrade" in action_lower:
        return "downgrade"
    if "initiate" in action_lower:
        return "new_coverage"
    if pt_current and str(pt_current).strip():
        return "price_target"
    return "rating"
