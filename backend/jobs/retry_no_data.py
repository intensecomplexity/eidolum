"""
Retry no_data predictions using Tiingo historical prices.
Tiingo free tier: 1,000 requests/day, 2GB bandwidth/day.

BANDWIDTH OPTIMIZATION: instead of fetching full history from 2011,
calculates the exact date range needed per ticker (earliest prediction
to latest evaluation + padding). Also requests only close+date columns.
This cuts bandwidth ~90% vs full OHLC history.

Runs every hour, processes 40 tickers per run.
"""
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip()

_price_cache: dict[str, dict] = {}

# Daily tracking
_tiingo_symbols_today: set[str] = set()
_tiingo_day: str = ""
TIINGO_DAILY_SYMBOL_LIMIT = 950  # Leave 50 buffer for other uses


def _check_daily_limit(ticker: str) -> bool:
    global _tiingo_symbols_today, _tiingo_day
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _tiingo_day != today:
        _tiingo_symbols_today = set()
        _tiingo_day = today
    if ticker in _tiingo_symbols_today:
        return True
    return len(_tiingo_symbols_today) < TIINGO_DAILY_SYMBOL_LIMIT


def _date_range_for_ticker(preds: list) -> tuple[str, str]:
    """Calculate the minimal date range needed for a ticker's predictions.
    Returns (start_date, end_date) as YYYY-MM-DD strings."""
    dates = []
    for p in preds:
        if p["prediction_date"]:
            d = p["prediction_date"]
            dates.append(d.date() if hasattr(d, 'date') else d)
        if p["evaluation_date"]:
            d = p["evaluation_date"]
            dates.append(d.date() if hasattr(d, 'date') else d)

    if not dates:
        # Fallback: last 2 years
        end = datetime.utcnow().date()
        start = end - timedelta(days=730)
        return str(start), str(end)

    earliest = min(dates)
    latest = max(dates)
    # Add 30 days padding on each side for closest-price lookups
    start = earliest - timedelta(days=30)
    end = latest + timedelta(days=30)
    # Cap end at today
    today = datetime.utcnow().date()
    if end > today:
        end = today

    return str(start), str(end)


def _fetch_tiingo_history(ticker: str, start_date: str, end_date: str) -> dict:
    """Fetch price history from Tiingo for a specific date range.
    Only requests close+date columns to minimize bandwidth."""
    if ticker in _price_cache:
        return _price_cache[ticker]

    if not TIINGO_KEY:
        return {}

    if not _check_daily_limit(ticker):
        return {}

    import httpx
    try:
        r = httpx.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
            params={
                "startDate": start_date,
                "endDate": end_date,
                "resampleFreq": "daily",
                "columns": "close,date",
                "token": TIINGO_KEY,
            },
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
        _tiingo_symbols_today.add(ticker)
        return prices
    except Exception as e:
        if len(_tiingo_symbols_today) < 5:
            print(f"[RetryNoData] Tiingo error for {ticker}: {e}")
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
            ds = str(d)
            if ds in prices:
                return prices[ds]
    return None


def retry_no_data_batch(db, max_tickers: int = 40):
    """Re-evaluate no_data predictions using Tiingo with minimal date ranges."""
    _price_cache.clear()
    now = datetime.utcnow()

    if not TIINGO_KEY:
        print("[RetryNoData] TIINGO_API_KEY not set, cannot retry")
        return {"scored": 0, "remaining": 0}

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
          f"Processing {len(tickers)} tickers. Daily symbols: {len(_tiingo_symbols_today)}/{TIINGO_DAILY_SYMBOL_LIMIT}")

    total_scored = 0
    total_still_no_data = 0
    affected_forecasters = set()
    api_calls = 0

    for i, ticker in enumerate(tickers):
        preds = ticker_preds[ticker]

        # Calculate minimal date range for this ticker's predictions
        start_date, end_date = _date_range_for_ticker(preds)
        prices = _fetch_tiingo_history(ticker, start_date, end_date)
        api_calls += 1

        if prices and api_calls <= 3:
            print(f"[RetryNoData] {ticker}: {len(prices)} prices ({start_date} to {end_date}), {len(preds)} predictions")

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

        if (i + 1) % 20 == 0:
            db.commit()
            print(f"[RetryNoData] {i + 1}/{len(tickers)} tickers, {total_scored} re-scored, {api_calls} Tiingo calls")

        time.sleep(0.3)

    db.commit()

    if affected_forecasters:
        from utils import recalculate_forecaster_stats
        for fid in affected_forecasters:
            try:
                recalculate_forecaster_stats(fid, db)
            except Exception:
                pass

    remaining = remaining_total - total_scored
    print(f"[RetryNoData] DONE: {total_scored} re-scored, {total_still_no_data} still no data, "
          f"~{max(remaining, 0):,} remaining. {api_calls} Tiingo calls.")
    return {"scored": total_scored, "still_no_data": total_still_no_data, "remaining": max(remaining, 0)}
