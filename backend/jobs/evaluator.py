"""
Evaluator job — checks overdue predictions and marks them correct/incorrect.
Runs every 15 minutes via APScheduler.

When price data is unavailable (delisted tickers, missing data), predictions
are marked as "no_data" instead of being left pending forever.
"""
import httpx
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

# Cache to avoid hammering the API for the same ticker in one run
_price_cache = {}

# Track tickers we've already failed to fetch in this run
_failed_tickers = set()


def get_current_price(ticker: str) -> float | None:
    """Fetch current price. Tries Alpha Vantage first, falls back to yfinance (free)."""
    if ticker in _price_cache:
        return _price_cache[ticker]

    if ticker in _failed_tickers:
        return None

    # Try Alpha Vantage if key is set
    if ALPHA_VANTAGE_KEY:
        try:
            r = httpx.get(
                "https://www.alphavantage.co/query",
                params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": ALPHA_VANTAGE_KEY},
                timeout=10,
            )
            price = r.json().get("Global Quote", {}).get("05. price")
            if price:
                result = float(price)
                _price_cache[ticker] = result
                return result
        except Exception:
            pass

    # Fallback to yfinance (free, no key needed)
    try:
        from jobs.price_checker import get_current_price as yf_price
        result = yf_price(ticker)
        if result:
            _price_cache[ticker] = result
            return result
    except Exception:
        pass

    _failed_tickers.add(ticker)
    return None


def _evaluate_prediction(p: Prediction, price: float, now: datetime):
    """Score a single prediction. Returns True if scored."""
    if not p.entry_price or p.entry_price <= 0:
        return False

    actual_return = round(((price - p.entry_price) / p.entry_price) * 100, 2)

    if p.direction == "bullish":
        if p.target_price:
            p.outcome = "correct" if price >= p.target_price else "incorrect"
        else:
            p.outcome = "correct" if actual_return > 0 else "incorrect"
    elif p.direction == "bearish":
        if p.target_price:
            p.outcome = "correct" if price <= p.target_price else "incorrect"
        else:
            p.outcome = "correct" if actual_return < 0 else "incorrect"
    elif p.direction == "neutral":
        abs_ret = abs(actual_return)
        p.outcome = "correct" if abs_ret <= 5.0 else "near" if abs_ret <= 10.0 else "incorrect"
    else:
        return False

    p.actual_return = actual_return
    p.evaluated_at = now

    # Calculate alpha vs S&P 500 benchmark
    try:
        from jobs.historical_evaluator import _calc_spy_return
        spy_ret = _calc_spy_return(p.prediction_date, now)
        if spy_ret is not None:
            p.sp500_return = spy_ret
            p.alpha = round(actual_return - spy_ret, 2)
    except Exception:
        pass

    return True


def run_evaluator(db: Session):
    """Evaluate overdue pending predictions against current prices."""
    print(f"[Evaluator] Checking overdue predictions at {datetime.utcnow().isoformat()}")
    _price_cache.clear()
    _failed_tickers.clear()

    now = datetime.utcnow()

    # Find predictions past their evaluation window
    overdue = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.evaluation_date.isnot(None),
        Prediction.evaluation_date <= now,
    ).all()

    if not overdue:
        # Also check predictions without evaluation_date but past their window
        all_pending = db.query(Prediction).filter(
            Prediction.outcome == "pending",
            Prediction.evaluation_date.is_(None),
        ).all()
        overdue = [
            p for p in all_pending
            if p.prediction_date and
            (p.prediction_date + timedelta(days=p.window_days or 30)) <= now
        ]

    if not overdue:
        print("[Evaluator] No overdue predictions")
        db.close()
        return

    scored = 0
    no_data_count = 0
    skipped = 0

    for p in overdue:
        if not p.ticker or p.ticker == "UNKNOWN":
            continue

        price = get_current_price(p.ticker)

        if price is None:
            # No price data — check how long this prediction has been overdue
            eval_date = p.evaluation_date or (
                p.prediction_date + timedelta(days=p.window_days or 30) if p.prediction_date else None
            )
            if eval_date and (now - eval_date).days > 7:
                # Overdue by more than 7 days with no data — mark as no_data
                p.outcome = "no_data"
                p.evaluated_at = now
                no_data_count += 1
            else:
                skipped += 1
            continue

        if not p.entry_price or p.entry_price <= 0:
            # No entry price — can't calculate return, mark as no_data if old enough
            eval_date = p.evaluation_date or (
                p.prediction_date + timedelta(days=p.window_days or 30) if p.prediction_date else None
            )
            if eval_date and (now - eval_date).days > 7:
                p.outcome = "no_data"
                p.evaluated_at = now
                no_data_count += 1
            else:
                skipped += 1
            continue

        if _evaluate_prediction(p, price, now):
            scored += 1

    db.commit()
    print(f"[Evaluator] Evaluated {scored} predictions, {no_data_count} marked no_data, {skipped} skipped (retrying later)")

    # Recalculate stats for all affected forecasters
    from utils import recalculate_forecaster_stats
    affected_ids = set(p.forecaster_id for p in overdue if p.outcome in ("correct", "incorrect"))
    for fid in affected_ids:
        recalculate_forecaster_stats(fid, db)

    db.close()


def sweep_stuck_predictions(db: Session):
    """Daily sweep: find predictions stuck as pending past evaluation_date.
    Marks unfetchable ones as no_data after 7 days overdue."""
    print(f"[Sweep] Checking for stuck predictions at {datetime.utcnow().isoformat()}")
    _price_cache.clear()
    _failed_tickers.clear()

    now = datetime.utcnow()
    cutoff = now - timedelta(days=7)

    # Predictions overdue by more than 7 days
    stuck = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.evaluation_date.isnot(None),
        Prediction.evaluation_date <= cutoff,
    ).all()

    if not stuck:
        print("[Sweep] No stuck predictions found")
        return

    scored = 0
    no_data_count = 0

    for p in stuck:
        if not p.ticker or p.ticker == "UNKNOWN":
            p.outcome = "no_data"
            p.evaluated_at = now
            no_data_count += 1
            continue

        price = get_current_price(p.ticker)

        if price is None or not p.entry_price or p.entry_price <= 0:
            p.outcome = "no_data"
            p.evaluated_at = now
            no_data_count += 1
            continue

        if _evaluate_prediction(p, price, now):
            scored += 1

    db.commit()
    print(f"[Sweep] Scored {scored}, marked {no_data_count} as no_data out of {len(stuck)} stuck")

    from utils import recalculate_forecaster_stats
    affected_ids = set(p.forecaster_id for p in stuck if p.outcome in ("correct", "incorrect"))
    for fid in affected_ids:
        recalculate_forecaster_stats(fid, db)
