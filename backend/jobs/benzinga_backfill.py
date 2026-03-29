"""
Benzinga historical backfill — crawls day by day from 2 years ago to today.
Stores progress in the config table so it resumes after restart.
Evaluates expired predictions using yfinance historical prices.
"""
import os
import time
import httpx
from datetime import datetime, timedelta, date
from decimal import Decimal
from sqlalchemy.orm import Session
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
    "predictions_evaluated": 0,
    "last_error": None,
}


def get_backfill_status() -> dict:
    return dict(_backfill_status)


def stop_backfill():
    global _backfill_stop
    _backfill_stop = True


def run_backfill(db: Session, start_date: date = None, end_date: date = None):
    """Day-by-day backfill from start_date to end_date."""
    global _backfill_running, _backfill_stop, _backfill_status

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
    resume = db.query(Config).filter(Config.key == "backfill_last_date").first()
    if resume and resume.value:
        try:
            resumed_date = datetime.strptime(resume.value, "%Y-%m-%d").date()
            if resumed_date > start_date:
                start_date = resumed_date + timedelta(days=1)
                print(f"[Backfill] Resuming from {start_date}")
        except Exception:
            pass

    total_days = (end_date - start_date).days + 1
    _backfill_status.update({
        "running": True, "current_date": str(start_date),
        "days_completed": 0, "total_days": total_days,
        "predictions_inserted": 0, "predictions_evaluated": 0, "last_error": None,
    })

    print(f"[Backfill] Starting: {start_date} → {end_date} ({total_days} days)")
    total_inserted = 0
    total_evaluated = 0

    current = start_date
    days_done = 0

    try:
        while current <= end_date:
            if _backfill_stop:
                print(f"[Backfill] Stopped at {current}")
                break

            day_str = current.strftime("%Y-%m-%d")
            _backfill_status["current_date"] = day_str

            inserted, fetched = _process_day(day_str, db)
            total_inserted += inserted

            # Evaluate expired predictions from this day
            evaluated = _evaluate_day(day_str, db)
            total_evaluated += evaluated

            if inserted > 0 or fetched > 0:
                print(f"[Backfill] {day_str}: fetched={fetched} inserted={inserted} evaluated={evaluated}")

            # Save progress
            _save_progress(db, day_str)

            days_done += 1
            _backfill_status["days_completed"] = days_done
            _backfill_status["predictions_inserted"] = total_inserted
            _backfill_status["predictions_evaluated"] = total_evaluated

            current += timedelta(days=1)
            time.sleep(0.5)  # Be nice to the API

    except Exception as e:
        _backfill_status["last_error"] = str(e)
        print(f"[Backfill] Error at {current}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _backfill_running = False
        _backfill_status["running"] = False
        print(f"[Backfill] Complete: {days_done} days, {total_inserted} inserted, {total_evaluated} evaluated")


def _process_day(day_str: str, db: Session) -> tuple[int, int]:
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
        except Exception:
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
            if _insert_rating(rating, db):
                inserted += 1

        if not next_url or page >= 10:
            break

    if inserted > 0:
        db.commit()

    return inserted, fetched


def _insert_rating(rating: dict, db: Session) -> bool:
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

    # Layer 1: external_id dedup
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

    # Layer 3: cross-scraper dedup
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
    pt_str = f", PT ${pt_current}" if pt_current else ""
    context = f"{canonical} {action} {rating_current} on {ticker}{pt_str}"

    is_valid, _ = validate_prediction(
        ticker=ticker, direction=direction, source_url=source_url,
        archive_url=source_url, context=context, forecaster_id=forecaster.id,
    )
    if not is_valid:
        return False

    pred = Prediction(
        forecaster_id=forecaster.id, ticker=ticker, direction=direction,
        prediction_date=pred_date,
        evaluation_date=pred_date + timedelta(days=window_days),
        window_days=window_days, source_url=source_url, archive_url=source_url,
        source_type="article", source_platform_id=f"mbz_{ticker}_{canonical}_{date_str}",
        external_id=f"bz_{benzinga_id}" if benzinga_id else None,
        target_price=target_price, entry_price=entry_price,
        context=context[:500], exact_quote=context,
        outcome="pending", verified_by="massive_benzinga",
    )
    db.add(pred)
    return True


def _evaluate_day(day_str: str, db: Session) -> int:
    """Evaluate predictions from this day whose window has already passed."""
    now = datetime.utcnow()
    preds = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.verified_by == "massive_benzinga",
        Prediction.evaluation_date.isnot(None),
        Prediction.evaluation_date <= now,
        Prediction.prediction_date >= datetime.strptime(day_str, "%Y-%m-%d"),
        Prediction.prediction_date < datetime.strptime(day_str, "%Y-%m-%d") + timedelta(days=1),
    ).all()

    if not preds:
        return 0

    evaluated = 0
    for i, p in enumerate(preds):
        try:
            price = _get_historical_price(p.ticker, p.evaluation_date)
            if price is None:
                continue

            entry = p.entry_price or p.target_price
            if not entry:
                continue

            if p.direction == "bullish":
                outcome = "correct" if price > entry else "incorrect"
            else:
                outcome = "correct" if price < entry else "incorrect"

            p.outcome = outcome
            p.evaluated_at = now
            p.actual_return = round((price - entry) / entry * 100, 2) if entry else None
            evaluated += 1

        except Exception:
            continue

        # Batch: commit + sleep every 50
        if (i + 1) % 50 == 0:
            db.commit()
            time.sleep(1)

    db.commit()
    return evaluated


_hist_cache: dict[str, dict] = {}


def _get_historical_price(ticker: str, eval_date) -> float | None:
    """Get closing price at evaluation date using yfinance."""
    cache_key = f"{ticker}_{eval_date.strftime('%Y-%m-%d')}"
    if cache_key in _hist_cache:
        return _hist_cache[cache_key]

    try:
        import yfinance as yf
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FT
        def _fetch():
            t = yf.Ticker(ticker)
            start = (eval_date - timedelta(days=5)).strftime("%Y-%m-%d")
            end = (eval_date + timedelta(days=1)).strftime("%Y-%m-%d")
            h = t.history(start=start, end=end)
            if h is not None and not h.empty:
                return round(float(h['Close'].iloc[-1]), 2)
            return None

        with ThreadPoolExecutor(max_workers=1) as ex:
            result = ex.submit(_fetch).result(timeout=10)

        if result:
            _hist_cache[cache_key] = result
        return result
    except Exception:
        return None


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


def _save_progress(db: Session, day_str: str):
    row = db.query(Config).filter(Config.key == "backfill_last_date").first()
    if row:
        row.value = day_str
    else:
        db.add(Config(key="backfill_last_date", value=day_str))
    db.commit()
