"""
Retry no_data predictions using Tiingo historical prices.
Tiingo: 500 requests/hour, NO daily limit. Vastly better than FMP (300/day).

Runs every hour, processes 200 tickers per run.
Each Tiingo call returns the full price history for one ticker.
At 200 tickers/hour, ~2,500 unique tickers cleared in ~13 hours.
"""
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip()

_price_cache: dict[str, dict] = {}


def _fetch_tiingo_history(ticker: str) -> dict:
    """Fetch full price history from Tiingo. Returns {date_str: close, ...}.
    Tiingo limit: 500 req/hour, no daily cap."""
    if ticker in _price_cache:
        return _price_cache[ticker]

    if not TIINGO_KEY:
        return {}

    import httpx
    try:
        r = httpx.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
            params={"startDate": "2011-01-01", "token": TIINGO_KEY},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            _price_cache[ticker] = {}
            return {}

        data = r.json()
        if not isinstance(data, list):
            _price_cache[ticker] = {}
            return {}

        prices = {}
        for day in data:
            ds = (day.get("date") or "")[:10]
            close = day.get("close") or day.get("adjClose")
            if ds and close and float(close) > 0:
                prices[ds] = float(close)

        _price_cache[ticker] = prices
        return prices
    except Exception as e:
        if len(_price_cache) < 5:
            print(f"[RetryNoData] Tiingo error for {ticker}: {e}")
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
    """Re-evaluate no_data predictions using Tiingo historical prices.
    200 tickers per run, 0.5s delay = ~2 minutes per run."""
    _price_cache.clear()
    now = datetime.utcnow()

    if not TIINGO_KEY:
        print("[RetryNoData] TIINGO_API_KEY not set, cannot retry no_data predictions")
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

    print(f"[RetryNoData] {remaining_total:,} no_data across {total_tickers} tickers. "
          f"Processing {len(tickers)} tickers via Tiingo (500 req/hr limit).")

    total_scored = 0
    total_still_no_data = 0
    affected_forecasters = set()
    api_calls = 0

    for i, ticker in enumerate(tickers):
        prices = _fetch_tiingo_history(ticker)
        api_calls += 1

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
            ret = -raw_move if direction == "bearish" else raw_move

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
                "direction": direction, "summary": summary, "fid": p["forecaster_id"],
            })
            affected_forecasters.add(p["forecaster_id"])

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

        # Commit + log every 25 tickers
        if (i + 1) % 25 == 0:
            db.commit()
            print(f"[RetryNoData] {i + 1}/{len(tickers)} tickers, {total_scored} re-scored, {api_calls} Tiingo calls")

        # Rate limit: ~3.6 req/sec to stay well within 500/hr
        time.sleep(0.3)

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
    print(f"[RetryNoData] DONE: {total_scored} re-scored, {total_still_no_data} still no data, "
          f"~{max(remaining, 0):,} remaining. {api_calls} Tiingo calls for {len(tickers)} tickers.")
    return {"scored": total_scored, "still_no_data": total_still_no_data, "remaining": max(remaining, 0)}
