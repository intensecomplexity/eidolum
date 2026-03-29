"""
Benzinga historical backfill — crawls day by day from 2 years ago to today.
Stores progress in the config table so it resumes after restart.
Connection-safe: opens/closes DB per batch, never holds connections during API calls.
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

# Backfill state
_backfill_running = False
_backfill_stop = False
_backfill_status = {
    "running": False,
    "current_date": None,
    "days_completed": 0,
    "total_days": 0,
    "predictions_inserted": 0,
    "last_error": None,
}


def get_backfill_status() -> dict:
    return dict(_backfill_status)


def stop_backfill():
    global _backfill_stop
    _backfill_stop = True


def run_backfill(start_date: date = None, end_date: date = None):
    """Day-by-day backfill. Connection-safe: opens/closes DB per batch of 30 days."""
    global _backfill_running, _backfill_stop, _backfill_status
    from database import BgSessionLocal

    if _backfill_running:
        print("[Backfill] Already running")
        return
    if not MASSIVE_KEY:
        print("[Backfill] No MASSIVE_API_KEY")
        return

    _backfill_running = True
    _backfill_stop = False

    if not start_date:
        start_date = date(2024, 3, 29)
    if not end_date:
        end_date = date.today()

    # Check for resume point
    db = BgSessionLocal()
    try:
        resume = db.query(Config).filter(Config.key == "backfill_last_date").first()
        if resume and resume.value:
            try:
                resumed_date = datetime.strptime(resume.value, "%Y-%m-%d").date()
                if resumed_date > start_date:
                    start_date = resumed_date + timedelta(days=1)
                    print(f"[Backfill] Resuming from {start_date}")
            except Exception:
                pass
    finally:
        db.close()

    total_days = (end_date - start_date).days + 1
    if total_days <= 0:
        print(f"[Backfill] Already caught up (last={start_date - timedelta(days=1)}, today={end_date})")
        _backfill_running = False
        return

    _backfill_status.update({
        "running": True, "current_date": str(start_date),
        "days_completed": 0, "total_days": total_days,
        "predictions_inserted": 0, "last_error": None,
    })

    print(f"[Backfill] Starting: {start_date} -> {end_date} ({total_days} days)")
    total_inserted = 0
    days_done = 0
    current = start_date
    batch_days = 0

    try:
        while current <= end_date:
            if _backfill_stop:
                print(f"[Backfill] Stopped at {current}")
                break

            day_str = current.strftime("%Y-%m-%d")
            _backfill_status["current_date"] = day_str

            # Open a fresh DB connection per day
            db = BgSessionLocal()
            try:
                inserted, fetched = _process_day(day_str, db)
                total_inserted += inserted

                if inserted > 0 or fetched > 0:
                    print(f"[Backfill] {day_str}: fetched={fetched} inserted={inserted}")

                # Save progress
                _save_progress(db, day_str)
            except Exception as e:
                _backfill_status["last_error"] = f"{day_str}: {e}"
                print(f"[Backfill] Error on {day_str}: {e}")
                # Don't stop, skip this day and continue
            finally:
                db.close()

            days_done += 1
            batch_days += 1
            _backfill_status["days_completed"] = days_done
            _backfill_status["predictions_inserted"] = total_inserted

            current += timedelta(days=1)

            # Pause between days (0.5s) and longer pause every 30 days
            time.sleep(0.5)
            if batch_days >= 30:
                print(f"[Backfill] Batch of 30 days complete. {days_done}/{total_days} done, {total_inserted} inserted. Pausing 10s.")
                time.sleep(10)
                batch_days = 0

    except Exception as e:
        _backfill_status["last_error"] = str(e)
        print(f"[Backfill] Fatal error at {current}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _backfill_running = False
        _backfill_status["running"] = False
        print(f"[Backfill] Complete: {days_done} days, {total_inserted} inserted")


def auto_resume_backfill():
    """Called on startup. If backfill isn't caught up to today, resume in background."""
    import threading
    if not MASSIVE_KEY:
        return

    from database import BgSessionLocal
    db = BgSessionLocal()
    try:
        resume = db.query(Config).filter(Config.key == "backfill_last_date").first()
        if resume and resume.value:
            last = datetime.strptime(resume.value, "%Y-%m-%d").date()
            if last >= date.today() - timedelta(days=1):
                print(f"[Backfill] Already caught up (last={last})")
                return
            print(f"[Backfill] Auto-resuming from {last + timedelta(days=1)}")
        else:
            print("[Backfill] No previous progress, starting fresh")
    finally:
        db.close()

    threading.Thread(target=run_backfill, daemon=True).start()


def _process_day(day_str: str, db) -> tuple:
    """Fetch and insert all ratings for a single day. Returns (inserted, fetched)."""
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
            except Exception as e:
                # Log and skip individual rating errors
                continue

        if not next_url or page >= 10:
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
    url_news = rating.get("url_news") or rating.get("benzinga_news_url") or ""
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

    # Derive call_type from action
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
    source_url = url_news or f"https://www.benzinga.com/quote/{ticker}/analyst-ratings"
    from jobs.context_formatter import format_context
    context = format_context(canonical, action, rating_current, ticker, target_price)

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


def _get_direction(action_lower, rating_lower, pt_current, pt_prior):
    if any(w in action_lower for w in ["upgrade", "initiates"]):
        return "bullish"
    if "downgrade" in action_lower:
        return "bearish"
    if "maintains" in action_lower or "reiterates" in action_lower:
        if not pt_current or str(pt_current) == str(pt_prior):
            return None
        if any(w in rating_lower for w in ["buy", "outperform", "overweight", "strong buy"]):
            return "bullish"
        if any(w in rating_lower for w in ["sell", "underperform", "underweight", "reduce"]):
            return "bearish"
        return None
    if any(w in rating_lower for w in ["buy", "outperform", "overweight", "strong buy", "positive"]):
        return "bullish"
    if any(w in rating_lower for w in ["sell", "underperform", "underweight", "strong sell", "negative", "reduce"]):
        return "bearish"
    return None


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


def _save_progress(db, day_str: str):
    row = db.query(Config).filter(Config.key == "backfill_last_date").first()
    if row:
        row.value = day_str
    else:
        db.add(Config(key="backfill_last_date", value=day_str))
    db.commit()
