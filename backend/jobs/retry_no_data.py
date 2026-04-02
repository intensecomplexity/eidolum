"""
Retry no_data predictions using Polygon (primary) + FMP (fallback for pre-2024).

Polygon Stocks Basic (free): 5 calls/min, no daily limit, ~2 years of data.
FMP (paid, $29/mo): 300 calls/day, full history.
Tiingo: disabled (429 bandwidth exhausted).

Strategy:
- ALL tickers go through Polygon first (5 calls/min = 12s between)
- If Polygon returns no data (pre-April 2024), try FMP (200/day budget)
- 200 tickers/run × 12s = 40 min per run, fits in 1-hour interval
- ~100 predictions per ticker = 20,000 scored per run
"""
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

POLYGON_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
FMP_KEY = os.getenv("FMP_KEY", "").strip()

# Polygon covers ~2 years back
POLYGON_CUTOFF = datetime(2024, 4, 1)

_price_cache: dict[str, dict] = {}

# FMP daily budget for this job (out of 300/day total)
_fmp_calls_today = 0
_fmp_day = ""
FMP_DAILY_LIMIT = 200


def _reset_fmp_counter():
    global _fmp_calls_today, _fmp_day
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _fmp_day != today:
        _fmp_calls_today = 0
        _fmp_day = today


def _fetch_polygon(ticker: str, start_date: str, end_date: str) -> dict:
    """Fetch daily prices from Polygon. Rate: 5/min (12s between calls)."""
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not POLYGON_KEY:
        return {}

    import httpx
    try:
        r = httpx.get(
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}",
            params={"adjusted": "true", "sort": "asc", "limit": "5000", "apiKey": POLYGON_KEY},
            timeout=15,
        )
        if r.status_code != 200:
            return {}

        data = r.json()
        results = data.get("results") or []
        prices = {}
        for bar in results:
            ts_ms = bar.get("t")
            close = bar.get("c")
            if ts_ms and close and float(close) > 0:
                ds = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
                prices[ds] = float(close)

        _price_cache[ticker] = prices
        return prices
    except Exception:
        return {}


def _fetch_fmp(ticker: str) -> dict:
    """Fetch full history from FMP /api/v3/. Budget: 200/day for this job."""
    global _fmp_calls_today
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not FMP_KEY:
        return {}

    _reset_fmp_counter()
    if _fmp_calls_today >= FMP_DAILY_LIMIT:
        return {}

    import httpx
    try:
        r = httpx.get(
            f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}",
            params={"apikey": FMP_KEY, "serietype": "line"},
            timeout=15,
        )
        _fmp_calls_today += 1
        if r.status_code != 200:
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
    except Exception:
        _fmp_calls_today += 1
        return {}


def _closest_price(prices: dict, target_date) -> float | None:
    if not prices or not target_date:
        return None
    target = target_date.date() if hasattr(target_date, 'date') else target_date
    ts = str(target)
    if ts in prices:
        return prices[ts]
    for offset in range(1, 6):
        for d in [target - timedelta(days=offset), target + timedelta(days=offset)]:
            if str(d) in prices:
                return prices[str(d)]
    return None


def _date_range(preds: list) -> tuple[str, str]:
    """Minimal date range for a ticker's predictions (30 day padding)."""
    dates = []
    for p in preds:
        if p["prediction_date"]:
            d = p["prediction_date"]
            dates.append(d.date() if hasattr(d, 'date') else d)
        if p["evaluation_date"]:
            d = p["evaluation_date"]
            dates.append(d.date() if hasattr(d, 'date') else d)
    if not dates:
        end = datetime.utcnow().date()
        return str(end - timedelta(days=730)), str(end)
    start = min(dates) - timedelta(days=30)
    end = min(max(dates) + timedelta(days=30), datetime.utcnow().date())
    return str(start), str(end)


def _score_predictions(preds: list, prices: dict, now: datetime) -> list:
    """Score predictions against price data. Returns list of update dicts."""
    updates = []
    for p in preds:
        eval_price = _closest_price(prices, p["evaluation_date"])
        if eval_price is None:
            continue

        ref = p["entry_price"]
        if not ref or ref <= 0:
            ref = _closest_price(prices, p["prediction_date"])
            if not ref or ref <= 0:
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
            outcome = "hit" if (eval_price > ref if direction == "bullish" else eval_price < ref) else "miss"

        summary = _build_summary(p["ticker"], direction, outcome, ref, eval_price, target, ret)
        updates.append({
            "id": p["id"], "outcome": outcome, "ret": ret, "ep": ref,
            "direction": direction, "summary": summary, "fid": p["forecaster_id"],
        })
    return updates


def retry_no_data_batch(db, max_tickers: int = 200):
    """Re-evaluate no_data predictions. Polygon primary, FMP fallback for old data."""
    _price_cache.clear()
    _reset_fmp_counter()
    now = datetime.utcnow()

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
          f"Processing {len(tickers)} tickers. FMP budget: {_fmp_calls_today}/{FMP_DAILY_LIMIT}")

    total_scored = 0
    total_still_no_data = 0
    polygon_scored = 0
    fmp_scored = 0
    affected_forecasters = set()

    for i, ticker in enumerate(tickers):
        preds = ticker_preds[ticker]
        start_date, end_date = _date_range(preds)

        # Try Polygon first (all tickers)
        prices = _fetch_polygon(ticker, start_date, end_date)

        # If Polygon returned nothing (pre-2024 data), try FMP
        if not prices and _fmp_calls_today < FMP_DAILY_LIMIT:
            prices = _fetch_fmp(ticker)
            if prices:
                fmp_scored_before = total_scored

        updates = _score_predictions(preds, prices, now)
        total_still_no_data += len(preds) - len(updates)

        if updates:
            for u in updates:
                db.execute(sql_text("""
                    UPDATE predictions SET outcome=:o, actual_return=:r, direction=:d,
                    entry_price=COALESCE(entry_price,:ep), evaluation_summary=:s,
                    evaluated_at=:now WHERE id=:id
                """), {"o": u["outcome"], "r": u["ret"], "d": u["direction"],
                       "ep": u["ep"], "s": u["summary"], "now": now, "id": u["id"]})
            total_scored += len(updates)
            for u in updates:
                affected_forecasters.add(u["fid"])

        # Commit every 5 tickers
        if (i + 1) % 5 == 0:
            db.commit()
            if (i + 1) % 20 == 0:
                print(f"[RetryNoData] {i + 1}/{len(tickers)} tickers, {total_scored} scored")

        # Polygon rate limit: 5 calls/min = 12s between calls
        time.sleep(12)

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
    print(f"[RetryNoData] DONE: {total_scored} scored, {total_still_no_data} still no data, "
          f"~{max(remaining, 0):,} remaining. FMP: {_fmp_calls_today}/{FMP_DAILY_LIMIT}")
    return {"scored": total_scored, "remaining": max(remaining, 0)}
