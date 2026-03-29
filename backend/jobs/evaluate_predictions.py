"""
Prediction evaluator — scores pending predictions against actual stock prices.
Uses Finnhub candle API for historical prices, grouped by ticker for efficiency.
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from collections import defaultdict
from models import Prediction


FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")


def _fetch_candles(ticker, from_date, to_date):
    """Fetch daily candles for a ticker. Returns dict of {date_str: close_price}."""
    start_ts = int(from_date.timestamp())
    end_ts = int(to_date.timestamp())

    try:
        r = httpx.get(
            "https://finnhub.io/api/v1/stock/candle",
            params={"symbol": ticker, "resolution": "D", "from": start_ts, "to": end_ts, "token": FINNHUB_KEY},
            timeout=15,
        )
        data = r.json()
        closes = data.get("c", [])
        timestamps = data.get("t", [])

        if not closes or data.get("s") == "no_data":
            return {}

        prices = {}
        for i, ts in enumerate(timestamps):
            dt = datetime.utcfromtimestamp(ts)
            prices[dt.strftime("%Y-%m-%d")] = closes[i]
        return prices

    except Exception:
        return {}


def _find_closest_price(prices, target_date, max_days=5):
    """Find the closest available price to the target date."""
    for offset in range(max_days + 1):
        for delta in [offset, -offset]:
            d = (target_date + timedelta(days=delta)).strftime("%Y-%m-%d")
            if d in prices:
                return prices[d]
    return None


def evaluate_all_pending(db):
    """Bulk evaluate ALL pending predictions past their window, grouped by ticker."""
    if not FINNHUB_KEY:
        print("[Evaluator] No FINNHUB_KEY — cannot evaluate")
        return

    now = datetime.utcnow()

    from sqlalchemy import text as sql_text

    # Count totals
    total_pending = db.query(Prediction).filter(Prediction.outcome == "pending").count()

    # SQL-level filter: only predictions past their evaluation window
    # prediction_date + window_days < now
    due = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.ticker.isnot(None),
        Prediction.prediction_date.isnot(None),
    ).all()

    # Filter in Python since interval math varies by DB engine
    due = [p for p in due if p.prediction_date + timedelta(days=p.window_days or 90) <= now]

    today_count = total_pending - len(due)
    if not due:
        print(f"[Evaluator] {total_pending} pending ({today_count} recent, 0 due for evaluation)")
        return

    print(f"[Evaluator] {len(due)} past-due predictions to score ({today_count} recent stay pending)")

    # Group by ticker for efficient API calls
    by_ticker = defaultdict(list)
    for p in due:
        by_ticker[p.ticker.upper()].append(p)

    print(f"[Evaluator] {len(due)} predictions due across {len(by_ticker)} tickers")

    evaluated = 0
    errors = 0
    tickers_done = 0

    for ticker, preds in by_ticker.items():
        try:
            # Find date range needed for this ticker
            earliest = min(p.prediction_date for p in preds)
            latest_eval = max(p.prediction_date + timedelta(days=p.window_days or 90) for p in preds)
            # Add buffer for weekends
            from_date = earliest - timedelta(days=5)
            to_date = min(latest_eval + timedelta(days=5), now)

            prices = _fetch_candles(ticker, from_date, to_date)
            time.sleep(1.1)

            if not prices:
                errors += len(preds)
                tickers_done += 1
                if tickers_done <= 3:
                    print(f"[Evaluator] {ticker}: no price data ({len(preds)} predictions skipped)")
                continue

            ticker_correct = 0
            ticker_total = 0
            for p in preds:
                window = p.window_days or 90
                start_date = p.prediction_date
                end_date = start_date + timedelta(days=window)

                entry = p.entry_price if (p.entry_price and p.entry_price > 0) else _find_closest_price(prices, start_date)
                exit_price = _find_closest_price(prices, end_date)

                if not entry or not exit_price or entry <= 0:
                    errors += 1
                    continue

                direction = (p.direction or "bullish").lower()
                pct_return = round(((exit_price - entry) / entry) * 100, 2)

                if direction in ("bear", "bearish"):
                    outcome = "correct" if exit_price <= entry else "incorrect"
                    adjusted = -pct_return
                else:
                    outcome = "correct" if exit_price >= entry else "incorrect"
                    adjusted = pct_return

                p.outcome = outcome
                p.entry_price = entry
                p.actual_return = adjusted
                p.evaluation_date = end_date
                p.evaluated_at = now

                # Calculate alpha vs S&P 500 benchmark
                from jobs.historical_evaluator import _calc_spy_return
                spy_ret = _calc_spy_return(p.prediction_date, end_date)
                if spy_ret is not None:
                    p.sp500_return = spy_ret
                    p.alpha = round(adjusted - spy_ret, 2)
                else:
                    p.alpha = adjusted
                evaluated += 1
                ticker_total += 1
                if outcome == "correct":
                    ticker_correct += 1

            if ticker_total > 0 and tickers_done < 10:
                print(f"[Evaluator] {ticker}: {ticker_correct}/{ticker_total} correct")

            tickers_done += 1
            if tickers_done % 50 == 0:
                db.commit()
                print(f"[Evaluator] {tickers_done}/{len(by_ticker)} tickers, {evaluated} scored")

        except Exception as e:
            print(f"[Evaluator] Error for {ticker}: {e}")
            errors += 1
            tickers_done += 1

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

    print(f"[Evaluator] Done: {evaluated} scored, {errors} errors, {len(by_ticker)} tickers processed")
