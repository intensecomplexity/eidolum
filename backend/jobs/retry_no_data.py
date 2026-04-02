"""
Retry no_data predictions using FMP /api/v3/historical-price-full.
yfinance is completely blocked on Railway (returns empty for all tickers).

Runs every 2 hours, processes 200 tickers per run.
Each FMP call returns the FULL price history for one ticker,
reused for all predictions on that ticker.

At 200 tickers/run × 12 runs/day = 2,400 tickers/day.
"""
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

FMP_KEY = os.getenv("FMP_KEY", "").strip()

_price_cache: dict[str, dict] = {}


def _fetch_fmp_history(ticker: str) -> dict:
    """Fetch full price history from FMP /api/v3/. Returns {date_str: close, ...}."""
    if ticker in _price_cache:
        return _price_cache[ticker]

    if not FMP_KEY:
        return {}

    import httpx
    try:
        r = httpx.get(
            f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}",
            params={"apikey": FMP_KEY, "serietype": "line"},
            timeout=15,
        )
        if r.status_code != 200:
            _price_cache[ticker] = {}
            return {}

        data = r.json()
        historical = data.get("historical", []) if isinstance(data, dict) else []
        prices = {}
        for day in historical:
            ds = (day.get("date") or "")[:10]
            close = day.get("close")
            if ds and close and float(close) > 0:
                prices[ds] = float(close)

        _price_cache[ticker] = prices
        return prices
    except Exception as e:
        print(f"[RetryNoData] FMP error for {ticker}: {e}")
        _price_cache[ticker] = {}
        return {}


def _closest_price(prices: dict, target_date) -> float | None:
    """Find closest price to target date within 5 business days."""
    if not prices or not target_date:
        return None
    target = target_date.date() if hasattr(target_date, 'date') else target_date
    ts = str(target)
    if ts in prices:
        return prices[ts]
    for offset in range(1, 6):
        for d in [target - timedelta(days=offset), target + timedelta(days=offset)]:
            ds = str(d)
            if ds in prices:
                return prices[ds]
    return None


def retry_no_data_batch(db, max_tickers: int = 200):
    """Re-evaluate no_data predictions using FMP historical prices."""
    _price_cache.clear()
    now = datetime.utcnow()

    if not FMP_KEY:
        print("[RetryNoData] FMP_KEY not set, cannot retry")
        return {"scored": 0, "remaining": 0}

    # Get no_data predictions grouped by ticker
    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days
        FROM predictions p
        WHERE p.outcome = 'no_data'
        ORDER BY p.ticker
        LIMIT 50000
    """)).fetchall()

    remaining_total = db.execute(sql_text(
        "SELECT COUNT(*) FROM predictions WHERE outcome = 'no_data'"
    )).scalar() or 0

    if not rows:
        print("[RetryNoData] No no_data predictions to retry")
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

    print(f"[RetryNoData] {remaining_total:,} no_data predictions across {total_tickers} tickers. Processing {len(tickers)} tickers this run.")

    total_scored = 0
    total_still_no_data = 0
    affected_forecasters = set()

    for i, ticker in enumerate(tickers):
        prices = _fetch_fmp_history(ticker)

        # Brief pause every 10 tickers (FMP rate limit)
        if (i + 1) % 10 == 0:
            time.sleep(0.5)

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

        if (i + 1) % 20 == 0:
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
