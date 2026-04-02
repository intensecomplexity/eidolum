"""
Retry no_data predictions using Polygon (recent) + Tiingo (historical).

Polygon Stocks Basic (free): 5 calls/min, no daily limit, 2 years of data.
Tiingo (free): 1,000 calls/day, 30+ years of data.

Strategy:
- Predictions with eval_date after April 2024 → Polygon (faster, unlimited)
- Predictions with eval_date before April 2024 → Tiingo (limited, deep history)
- Process Polygon tickers first, then Tiingo tickers
- Group by ticker, fetch once per ticker, score all predictions from cache
"""
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

POLYGON_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip()

# Polygon: 2 years of data cutoff
POLYGON_CUTOFF = datetime(2024, 4, 1)

_price_cache: dict[str, dict] = {}

# Tiingo daily tracking (1,000/day limit)
_tiingo_calls_today = 0
_tiingo_day = ""
TIINGO_DAILY_LIMIT = 950


def _reset_tiingo_counter():
    global _tiingo_calls_today, _tiingo_day
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _tiingo_day != today:
        _tiingo_calls_today = 0
        _tiingo_day = today


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
            params={"adjusted": "true", "sort": "asc", "apiKey": POLYGON_KEY},
            timeout=15,
        )
        if r.status_code != 200:
            _price_cache[ticker] = {}
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
    except Exception as e:
        _price_cache[ticker] = {}
        return {}


def _fetch_tiingo(ticker: str, start_date: str, end_date: str) -> dict:
    """Fetch daily prices from Tiingo. Limit: 950 unique tickers/day."""
    global _tiingo_calls_today
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not TIINGO_KEY:
        return {}

    _reset_tiingo_counter()
    if _tiingo_calls_today >= TIINGO_DAILY_LIMIT:
        return {}

    import httpx
    try:
        r = httpx.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
            params={
                "startDate": start_date, "endDate": end_date,
                "columns": "close,date", "token": TIINGO_KEY,
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        _tiingo_calls_today += 1

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
    except Exception:
        _price_cache[ticker] = {}
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


def retry_no_data_batch(db, max_tickers: int = 80):
    """Re-evaluate no_data predictions. Polygon for recent, Tiingo for old."""
    _price_cache.clear()
    _reset_tiingo_counter()
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

    # Split tickers into Polygon (recent) vs Tiingo (old)
    polygon_tickers = []
    tiingo_tickers = []
    for ticker, preds in ticker_preds.items():
        # If ANY prediction has eval_date within Polygon's range, use Polygon
        latest_eval = max((p["evaluation_date"] for p in preds if p["evaluation_date"]), default=None)
        if latest_eval and latest_eval >= POLYGON_CUTOFF:
            polygon_tickers.append(ticker)
        else:
            tiingo_tickers.append(ticker)

    # Limit totals
    polygon_batch = polygon_tickers[:max_tickers]
    tiingo_remaining = max(0, max_tickers - len(polygon_batch))
    tiingo_batch = tiingo_tickers[:tiingo_remaining]

    print(f"[RetryNoData] {remaining_total:,} no_data across {len(ticker_preds)} tickers. "
          f"This run: {len(polygon_batch)} Polygon + {len(tiingo_batch)} Tiingo. "
          f"Tiingo budget: {_tiingo_calls_today}/{TIINGO_DAILY_LIMIT}")

    total_scored = 0
    total_still_no_data = 0
    polygon_scored = 0
    tiingo_scored = 0
    affected_forecasters = set()

    # ── Phase 1: Polygon (recent, 5 calls/min = 12s between calls) ──
    for i, ticker in enumerate(polygon_batch):
        preds = ticker_preds[ticker]
        start_date, end_date = _date_range(preds)
        prices = _fetch_polygon(ticker, start_date, end_date)

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
            polygon_scored += len(updates)
            total_scored += len(updates)
            for u in updates:
                affected_forecasters.add(u["fid"])

        if (i + 1) % 5 == 0:
            db.commit()

        time.sleep(12)  # Polygon: 5 calls/min

    db.commit()

    # ── Phase 2: Tiingo (old predictions, 950/day limit) ──
    for i, ticker in enumerate(tiingo_batch):
        if _tiingo_calls_today >= TIINGO_DAILY_LIMIT:
            print(f"[RetryNoData] Tiingo daily limit reached at ticker {i}/{len(tiingo_batch)}")
            break

        preds = ticker_preds[ticker]
        start_date, end_date = _date_range(preds)
        prices = _fetch_tiingo(ticker, start_date, end_date)

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
            tiingo_scored += len(updates)
            total_scored += len(updates)
            for u in updates:
                affected_forecasters.add(u["fid"])

        if (i + 1) % 10 == 0:
            db.commit()

        time.sleep(0.5)  # Tiingo: generous limit

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
    print(f"[RetryNoData] DONE: {total_scored} scored (Polygon:{polygon_scored} + Tiingo:{tiingo_scored}), "
          f"{total_still_no_data} still no data, ~{max(remaining, 0):,} remaining. "
          f"Tiingo today: {_tiingo_calls_today}/{TIINGO_DAILY_LIMIT}")
    return {"scored": total_scored, "polygon": polygon_scored, "tiingo": tiingo_scored, "remaining": max(remaining, 0)}
