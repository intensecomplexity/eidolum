"""
Retry no_data predictions using FMP /api/v3/historical-price-full.
Uses BATCH endpoint: comma-separated tickers in one call (5 per call).
100 FMP calls x 5 tickers = 500 tickers per day.

Runs every 2 hours, processes 100 tickers per run (20 batch calls).
"""
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

FMP_KEY = os.getenv("FMP_KEY", "").strip()

_price_cache: dict[str, dict] = {}


def _fetch_fmp_batch(tickers: list[str]) -> dict[str, dict]:
    """Fetch price history for up to 5 tickers in ONE FMP call.
    Uses comma-separated symbols: /api/v3/historical-price-full/AAPL,MSFT,GOOG
    Returns {ticker: {date_str: close, ...}, ...}"""
    if not FMP_KEY or not tickers:
        return {}

    # Check cache first
    uncached = [t for t in tickers if t not in _price_cache]
    if not uncached:
        return {t: _price_cache.get(t, {}) for t in tickers}

    import httpx
    result = {}
    symbols = ",".join(uncached[:5])  # Max 5 per batch

    try:
        r = httpx.get(
            f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbols}",
            params={"apikey": FMP_KEY, "serietype": "line"},
            timeout=20,
        )
        if r.status_code != 200:
            # Mark all as empty so we don't retry
            for t in uncached:
                _price_cache[t] = {}
            return {t: _price_cache.get(t, {}) for t in tickers}

        data = r.json()

        # Single ticker returns {"symbol": "AAPL", "historical": [...]}
        # Multiple tickers returns {"historicalStockList": [{"symbol": "AAPL", "historical": [...]}, ...]}
        if isinstance(data, dict):
            if "historicalStockList" in data:
                # Multi-ticker response
                for item in data["historicalStockList"]:
                    sym = item.get("symbol", "")
                    prices = {}
                    for day in (item.get("historical") or []):
                        ds = (day.get("date") or "")[:10]
                        close = day.get("close")
                        if ds and close and float(close) > 0:
                            prices[ds] = float(close)
                    _price_cache[sym] = prices
                    result[sym] = prices
            elif "historical" in data:
                # Single ticker response
                sym = data.get("symbol", uncached[0] if uncached else "")
                prices = {}
                for day in data["historical"]:
                    ds = (day.get("date") or "")[:10]
                    close = day.get("close")
                    if ds and close and float(close) > 0:
                        prices[ds] = float(close)
                _price_cache[sym] = prices
                result[sym] = prices

        # Mark tickers with no data
        for t in uncached:
            if t not in _price_cache:
                _price_cache[t] = {}

    except Exception as e:
        print(f"[RetryNoData] FMP batch error for {symbols}: {e}")
        for t in uncached:
            _price_cache[t] = {}

    return {t: _price_cache.get(t, {}) for t in tickers}


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


def retry_no_data_batch(db, max_tickers: int = 100):
    """Re-evaluate no_data predictions using FMP batch historical prices.
    5 tickers per API call = 20 calls for 100 tickers."""
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
    batch_size = 5  # Tickers per FMP call
    api_calls = 0

    print(f"[RetryNoData] {remaining_total:,} no_data across {total_tickers} tickers. Processing {len(tickers)} tickers ({len(tickers) // batch_size + 1} API calls).")

    total_scored = 0
    total_still_no_data = 0
    affected_forecasters = set()

    # Process in batches of 5 tickers
    for batch_start in range(0, len(tickers), batch_size):
        batch_tickers = tickers[batch_start:batch_start + batch_size]
        batch_prices = _fetch_fmp_batch(batch_tickers)
        api_calls += 1
        time.sleep(0.5)  # Brief pause between batch calls

        for ticker in batch_tickers:
            prices = batch_prices.get(ticker, {})
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

        # Commit every 5 batches (25 tickers)
        if (batch_start // batch_size + 1) % 5 == 0:
            db.commit()
            print(f"[RetryNoData] Progress: {min(batch_start + batch_size, len(tickers))}/{len(tickers)} tickers, {total_scored} re-scored, {api_calls} API calls")

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
          f"~{max(remaining, 0):,} remaining. Used {api_calls} FMP calls for {len(tickers)} tickers.")
    return {"scored": total_scored, "still_no_data": total_still_no_data, "remaining": max(remaining, 0), "api_calls": api_calls}
