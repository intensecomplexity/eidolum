"""
Retry no_data predictions using yfinance (free, unlimited).
Runs hourly, processes 50 tickers per run with 2s delays.
At ~1,200 tickers/day, clears the 217K backlog in 2-3 days.
Does NOT use FMP — saves that budget for the grades scraper.
"""
import time
from datetime import datetime
from collections import defaultdict
from sqlalchemy import text as sql_text

# Import scoring thresholds from the main evaluator
from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

_yf_cache: dict[str, dict] = {}


def _fetch_yf_history(ticker: str) -> dict:
    """Download full price history for a ticker using yfinance. Returns {date_str: close, ...}."""
    if ticker in _yf_cache:
        return _yf_cache[ticker]

    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        hist = stock.history(period="max")
        if hist is None or len(hist) == 0:
            _yf_cache[ticker] = {}
            return {}

        prices = {}
        for date_idx, row in hist.iterrows():
            ds = str(date_idx.date())
            close = row.get("Close")
            if close and float(close) > 0:
                prices[ds] = float(close)

        _yf_cache[ticker] = prices
        return prices
    except Exception as e:
        print(f"[RetryNoData] yfinance error for {ticker}: {e}")
        _yf_cache[ticker] = {}
        return {}


def _closest_price(prices: dict, target_date) -> float | None:
    """Find closest price to target date within 5 business days."""
    if not prices or not target_date:
        return None
    target = target_date.date() if hasattr(target_date, 'date') else target_date
    ts = str(target)
    if ts in prices:
        return prices[ts]
    # Search nearby dates (weekends/holidays)
    from datetime import timedelta
    for offset in range(1, 6):
        for d in [target - timedelta(days=offset), target + timedelta(days=offset)]:
            ds = str(d)
            if ds in prices:
                return prices[ds]
    return None


def retry_no_data_batch(db, max_tickers: int = 50):
    """Re-evaluate no_data predictions using yfinance. Max 50 tickers per run."""
    _yf_cache.clear()
    now = datetime.utcnow()

    # Get no_data predictions grouped by ticker
    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days
        FROM predictions p
        WHERE p.outcome = 'no_data'
        ORDER BY p.ticker
        LIMIT 10000
    """)).fetchall()

    remaining_total = db.execute(sql_text(
        "SELECT COUNT(*) FROM predictions WHERE outcome = 'no_data'"
    )).scalar() or 0

    if not rows:
        print(f"[RetryNoData] No no_data predictions to retry")
        return {"scored": 0, "remaining": 0}

    # Group by ticker
    ticker_preds = defaultdict(list)
    for r in rows:
        ticker_preds[r[1]].append({
            "id": r[0], "ticker": r[1], "direction": r[2],
            "target_price": float(r[3]) if r[3] else None,
            "entry_price": float(r[4]) if r[4] else None,
            "evaluation_date": r[5], "prediction_date": r[6],
            "forecaster_id": r[7], "window_days": r[8],
        })

    tickers = list(ticker_preds.keys())[:max_tickers]
    total_tickers = len(ticker_preds)

    print(f"[RetryNoData] {remaining_total} no_data predictions across {total_tickers} tickers. Processing {len(tickers)} tickers this run.")

    total_scored = 0
    total_still_no_data = 0
    affected_forecasters = set()

    for i, ticker in enumerate(tickers):
        prices = _fetch_yf_history(ticker)
        time.sleep(2)  # Rate limit yfinance

        preds = ticker_preds[ticker]
        updates = []

        for p in preds:
            eval_price = _closest_price(prices, p["evaluation_date"])
            if eval_price is None:
                total_still_no_data += 1
                continue

            ref = p["entry_price"]
            if not ref or ref <= 0:
                ref = _closest_price(prices, p["prediction_date"])
                if not ref or ref <= 0:
                    total_still_no_data += 1
                    continue

            target = p["target_price"]
            direction = p["direction"]
            if target and target > 0 and ref > 0:
                if target > ref:
                    direction = "bullish"
                elif target < ref:
                    direction = "bearish"

            raw_move = round(((eval_price - ref) / ref) * 100, 2)
            if direction == "bearish":
                ret = -raw_move
            else:
                ret = raw_move

            window = p.get("window_days") or 90
            tolerance = _get_tolerance(window, _TOLERANCE)
            min_movement = _get_tolerance(window, _MIN_MOVEMENT)

            if direction == "neutral":
                abs_ret = abs(raw_move)
                outcome = "hit" if abs_ret <= 5.0 else "near" if abs_ret <= 10.0 else "miss"
            elif target and target > 0:
                target_dist_pct = abs(eval_price - target) / target * 100
                if direction == "bullish":
                    outcome = "hit" if (eval_price >= target or target_dist_pct <= tolerance) else "near" if raw_move >= min_movement else "miss"
                else:
                    outcome = "hit" if (eval_price <= target or target_dist_pct <= tolerance) else "near" if raw_move <= -min_movement else "miss"
            else:
                if direction == "bullish":
                    outcome = "hit" if eval_price > ref else "miss"
                else:
                    outcome = "hit" if eval_price < ref else "miss"

            summary = _build_summary(p["ticker"], direction, outcome, ref, eval_price, target, ret)
            updates.append({
                "id": p["id"], "outcome": outcome, "ret": ret, "ep": ref,
                "direction": direction, "summary": summary,
                "fid": p["forecaster_id"],
            })
            affected_forecasters.add(p["forecaster_id"])

        # Write results
        if updates:
            for u in updates:
                db.execute(sql_text("""
                    UPDATE predictions SET outcome=:o, actual_return=:r, direction=:d,
                    entry_price=COALESCE(entry_price,:ep), evaluation_summary=:s,
                    evaluated_at=:now WHERE id=:id
                """), {
                    "o": u["outcome"], "r": u["ret"], "d": u["direction"],
                    "ep": u["ep"], "s": u["summary"], "now": now, "id": u["id"],
                })
            total_scored += len(updates)

        if (i + 1) % 10 == 0:
            db.commit()
            print(f"[RetryNoData] Progress: {i + 1}/{len(tickers)} tickers, {total_scored} re-scored")

    db.commit()

    # Update forecaster stats
    if affected_forecasters:
        from utils import recalculate_forecaster_stats
        for fid in affected_forecasters:
            try:
                recalculate_forecaster_stats(fid, db)
            except Exception:
                pass

    remaining = remaining_total - total_scored
    print(f"[RetryNoData] DONE: {total_scored} re-scored, {total_still_no_data} still no data, ~{max(remaining, 0):,} remaining across {total_tickers - len(tickers)} untouched tickers")
    return {"scored": total_scored, "still_no_data": total_still_no_data, "remaining": max(remaining, 0)}
