"""
Retry no_data predictions using Polygon (primary) + FMP (fallback for pre-2024).

Polygon.io (Massive rebrand): MASSIVE_API_KEY, Stocks Basic plan.
- 5 calls/min (12s between calls), no daily limit
- ~2 years of history (April 2024 to present)

FMP /api/v3/historical-price-full: FMP_KEY
- 300 calls/day, full history back to 2000
- Fallback for predictions Polygon can't cover

Strategy:
- Split tickers: recent eval_dates (2024+) → Polygon, old → FMP
- Process Polygon tickers first (unlimited), then FMP (200/day budget)
"""
import os
import time
from datetime import datetime, timedelta, date as _date
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

POLYGON_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
FMP_KEY = os.getenv("FMP_KEY", "").strip()

POLYGON_EARLIEST = _date(2024, 4, 1)  # Polygon ~2yr history cutoff

_price_cache: dict[str, dict] = {}
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
    """Fetch daily prices from Polygon. Returns {date_str: close, ...}."""
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not POLYGON_KEY:
        return {}

    import httpx
    try:
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
        r = httpx.get(
            url,
            params={"adjusted": "true", "sort": "asc", "limit": "5000", "apiKey": POLYGON_KEY},
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
                # Convert millisecond timestamp to YYYY-MM-DD
                ds = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
                prices[ds] = round(float(close), 2)

        _price_cache[ticker] = prices
        return prices
    except Exception as e:
        _price_cache[ticker] = {}
        return {}


def _fetch_fmp(ticker: str) -> dict:
    """Fetch full history from FMP /api/v3/. Returns {date_str: close, ...}."""
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
            _price_cache[ticker] = {}
            return {}

        data = r.json()
        historical = data.get("historical", []) if isinstance(data, dict) else []
        prices = {}
        for day in historical:
            ds = (day.get("date") or "")[:10]
            close = day.get("close")
            if ds and close and float(close) > 0:
                prices[ds] = round(float(close), 2)

        _price_cache[ticker] = prices
        return prices
    except Exception:
        _fmp_calls_today += 1
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


def _needs_polygon(preds: list) -> bool:
    """Check if any prediction has an eval_date within Polygon's range."""
    for p in preds:
        ed = p["evaluation_date"]
        if ed:
            d = ed.date() if hasattr(ed, 'date') else ed
            if d >= POLYGON_EARLIEST:
                return True
    return False


def _score_predictions(preds: list, prices: dict, now: datetime, ticker: str, verbose: bool = False) -> tuple[list, int]:
    """Score predictions against price data. Returns (updates, still_no_data_count)."""
    updates = []
    no_data = 0
    for p in preds:
        eval_price = _closest_price(prices, p["evaluation_date"])
        if eval_price is None:
            if verbose:
                print(f"  [SKIP] id={p['id']}: no price for eval_date={p['evaluation_date']}")
            no_data += 1
            continue

        ref = p["entry_price"]
        if not ref or ref <= 0:
            ref = _closest_price(prices, p["prediction_date"])
            if not ref or ref <= 0:
                if verbose:
                    print(f"  [SKIP] id={p['id']}: no entry/pred price (pred_date={p['prediction_date']})")
                no_data += 1
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

        summary = _build_summary(ticker, direction, outcome, ref, eval_price, target, ret)
        updates.append({
            "id": p["id"], "outcome": outcome, "ret": ret, "ep": ref,
            "direction": direction, "summary": summary, "fid": p["forecaster_id"],
        })
    return updates, no_data


def retry_no_data_batch(db, max_tickers: int = 200):
    """Re-evaluate no_data predictions. Polygon for recent, FMP for old."""
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

    # Split: Polygon for recent, FMP for old
    polygon_tickers = []
    fmp_tickers = []
    for ticker, preds in ticker_preds.items():
        if _needs_polygon(preds):
            polygon_tickers.append(ticker)
        else:
            fmp_tickers.append(ticker)

    # Limit Polygon to max_tickers, FMP gets the rest up to budget
    polygon_batch = polygon_tickers[:max_tickers]
    fmp_budget_left = max(0, max_tickers - len(polygon_batch))
    fmp_batch = fmp_tickers[:min(fmp_budget_left, FMP_DAILY_LIMIT - _fmp_calls_today)]

    print(f"[RetryNoData] {remaining_total:,} no_data across {len(ticker_preds)} tickers. "
          f"This run: {len(polygon_batch)} Polygon + {len(fmp_batch)} FMP. "
          f"FMP budget: {_fmp_calls_today}/{FMP_DAILY_LIMIT}")

    total_scored = 0
    total_still_no_data = 0
    affected_forecasters = set()

    def _process_ticker(ticker, prices, verbose):
        nonlocal total_scored, total_still_no_data
        preds = ticker_preds[ticker]

        if verbose:
            eval_dates = [p["evaluation_date"] for p in preds if p["evaluation_date"]]
            entry_count = sum(1 for p in preds if p["entry_price"] and p["entry_price"] > 0)
            price_dates = sorted(prices.keys()) if prices else []
            print(f"[RetryNoData] DIAG {ticker}: {len(preds)} preds, "
                  f"eval={min(eval_dates).strftime('%Y-%m-%d') if eval_dates else 'none'}..{max(eval_dates).strftime('%Y-%m-%d') if eval_dates else 'none'}, "
                  f"{entry_count}/{len(preds)} have entry_price, "
                  f"prices: {len(prices)} days ({price_dates[0] if price_dates else 'none'}..{price_dates[-1] if price_dates else 'none'})")

        updates, no_data = _score_predictions(preds, prices, now, ticker, verbose=verbose)
        total_still_no_data += no_data

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

        if verbose:
            print(f"[RetryNoData] DIAG {ticker}: scored {len(updates)}, still no_data {no_data}")

    # Phase 1: Polygon (recent predictions, 5 calls/min = 12s between)
    for i, ticker in enumerate(polygon_batch):
        preds = ticker_preds[ticker]
        start_date, end_date = _date_range(preds)
        prices = _fetch_polygon(ticker, start_date, end_date)

        _process_ticker(ticker, prices, verbose=(i < 3))

        if (i + 1) % 5 == 0:
            db.commit()
            if (i + 1) % 20 == 0:
                print(f"[RetryNoData] Polygon {i + 1}/{len(polygon_batch)}, {total_scored} scored")

        time.sleep(12)  # 5 calls/min

    db.commit()

    # Phase 2: FMP (old predictions, 200/day budget)
    for i, ticker in enumerate(fmp_batch):
        if _fmp_calls_today >= FMP_DAILY_LIMIT:
            print(f"[RetryNoData] FMP budget exhausted at ticker {i}/{len(fmp_batch)}")
            break

        prices = _fetch_fmp(ticker)
        _process_ticker(ticker, prices, verbose=(i < 2 and len(polygon_batch) == 0))

        if (i + 1) % 5 == 0:
            db.commit()
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
    print(f"[RetryNoData] DONE: {total_scored} scored, {total_still_no_data} still no data, "
          f"~{max(remaining, 0):,} remaining. FMP: {_fmp_calls_today}/{FMP_DAILY_LIMIT}")
    return {"scored": total_scored, "remaining": max(remaining, 0)}
