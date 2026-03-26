"""
Evaluator job — checks overdue predictions and marks them correct/incorrect.
Runs every 15 minutes via APScheduler.
"""
import httpx
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

# Cache to avoid hammering the API for the same ticker in one run
_price_cache = {}


def get_current_price(ticker: str) -> float | None:
    """Fetch current price. Tries Alpha Vantage first, falls back to yfinance (free)."""
    if ticker in _price_cache:
        return _price_cache[ticker]

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
        _price_cache[ticker] = result
        return result
    except Exception:
        return None


def run_evaluator(db: Session):
    """Evaluate overdue pending predictions against current prices."""
    print(f"[Evaluator] Checking overdue predictions at {datetime.utcnow().isoformat()}")
    _price_cache.clear()

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

    count = 0
    for p in overdue:
        if not p.ticker or p.ticker == "UNKNOWN":
            continue

        price = get_current_price(p.ticker)
        if price is None:
            continue

        # Calculate return
        if p.entry_price and p.entry_price > 0:
            actual_return = round(((price - p.entry_price) / p.entry_price) * 100, 2)
        else:
            continue

        # Evaluate based on direction
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

        p.actual_return = actual_return
        p.evaluation_date = now
        count += 1

    db.commit()
    print(f"[Evaluator] Evaluated {count}/{len(overdue)} predictions")

    # Recalculate stats for all affected forecasters
    from utils import recalculate_forecaster_stats
    affected_ids = set(p.forecaster_id for p in overdue if p.outcome in ("correct", "incorrect"))
    for fid in affected_ids:
        recalculate_forecaster_stats(fid, db)

    db.close()
