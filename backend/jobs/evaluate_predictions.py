"""
Prediction evaluator — scores pending predictions against actual stock prices.
Uses Finnhub candle API for historical prices.
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from models import Prediction
from sqlalchemy import text


FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")


def _get_close_price(ticker, date_obj, cache):
    """Get closing price for a ticker on a specific date using Finnhub candles."""
    cache_key = f"{ticker}_{date_obj.strftime('%Y-%m-%d')}"
    if cache_key in cache:
        return cache[cache_key]

    # Fetch a 5-day window around the target date to handle weekends/holidays
    start = int((date_obj - timedelta(days=3)).timestamp())
    end = int((date_obj + timedelta(days=3)).timestamp())

    try:
        r = httpx.get(
            "https://finnhub.io/api/v1/stock/candle",
            params={"symbol": ticker, "resolution": "D", "from": start, "to": end, "token": FINNHUB_KEY},
            timeout=10,
        )
        data = r.json()
        closes = data.get("c", [])
        timestamps = data.get("t", [])

        if not closes or data.get("s") == "no_data":
            cache[cache_key] = None
            return None

        # Find the closest price to target date
        target_ts = int(date_obj.timestamp())
        best_price = None
        best_diff = float("inf")
        for i, ts in enumerate(timestamps):
            diff = abs(ts - target_ts)
            if diff < best_diff:
                best_diff = diff
                best_price = closes[i]

        cache[cache_key] = best_price
        return best_price

    except Exception:
        cache[cache_key] = None
        return None


def evaluate_all_pending(db):
    """Evaluate ALL pending predictions that are past their evaluation window."""
    if not FINNHUB_KEY:
        print("[Evaluator] No FINNHUB_KEY — cannot evaluate")
        return

    now = datetime.utcnow()

    # Find all pending predictions past their evaluation date
    pending = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.ticker.isnot(None),
        Prediction.prediction_date.isnot(None),
    ).all()

    # Filter to only those past their evaluation window
    due = []
    for p in pending:
        window = p.window_days or 90
        eval_date = p.prediction_date + timedelta(days=window)
        if eval_date <= now:
            due.append(p)

    if not due:
        print(f"[Evaluator] {len(pending)} pending, 0 due for evaluation")
        return

    print(f"[Evaluator] {len(due)} predictions due for evaluation (out of {len(pending)} pending)")

    evaluated = 0
    errors = 0
    price_cache = {}

    for i, p in enumerate(due):
        try:
            ticker = (p.ticker or "").upper().strip()
            if not ticker or len(ticker) > 6:
                continue

            window = p.window_days or 90
            start_date = p.prediction_date
            end_date = start_date + timedelta(days=window)

            # Get price at prediction date (entry) and at evaluation date (exit)
            entry_price = p.entry_price  # Use stored entry price if available
            if not entry_price or entry_price <= 0:
                entry_price = _get_close_price(ticker, start_date, price_cache)
                time.sleep(0.3)

            exit_price = _get_close_price(ticker, end_date, price_cache)
            time.sleep(0.3)

            if not entry_price or not exit_price or entry_price <= 0:
                errors += 1
                continue

            direction = (p.direction or "bullish").lower()
            pct_return = round(((exit_price - entry_price) / entry_price) * 100, 2)

            if direction in ("bear", "bearish"):
                outcome = "correct" if exit_price <= entry_price else "incorrect"
                adjusted_return = -pct_return
            else:
                outcome = "correct" if exit_price >= entry_price else "incorrect"
                adjusted_return = pct_return

            p.outcome = outcome
            p.entry_price = entry_price
            p.actual_return = adjusted_return
            p.alpha = adjusted_return
            p.evaluation_date = end_date
            evaluated += 1

            if evaluated % 100 == 0:
                db.commit()
                print(f"[Evaluator] Scored {evaluated}/{len(due)} predictions...")

            # Rate limit: ~2 calls per prediction, sleep to stay under 60/min
            if (i + 1) % 25 == 0:
                time.sleep(5)

        except Exception as e:
            print(f"[Evaluator] Error on #{p.id}: {e}")
            errors += 1

    db.commit()

    # Recalculate forecaster stats
    try:
        from utils import recalculate_forecaster_stats
        forecaster_ids = set(p.forecaster_id for p in due if p.outcome != "pending")
        for fid in forecaster_ids:
            recalculate_forecaster_stats(fid, db)
        print(f"[Evaluator] Updated stats for {len(forecaster_ids)} forecasters")
    except Exception as e:
        print(f"[Evaluator] Stats update error: {e}")

    print(f"[Evaluator] Done: {evaluated} scored, {errors} errors, {len(due) - evaluated - errors} skipped (no price data)")
