"""
Retry no_data predictions using THREE price sources:

1. Polygon (primary, recent): MASSIVE_API_KEY, 5 calls/min, no daily limit
   Covers ~2 years back (April 2024+). 10s between calls.

2. FMP (fallback, deep): FMP_KEY, 300 calls/day, history to 2000
   For pre-2024 predictions that Polygon can't cover.

3. Tiingo (fallback, deep): TIINGO_API_KEY, 1000 calls/day
   Minimal bandwidth: close-only columns + exact date ranges.
   For pre-2024 predictions when FMP budget exhausted.

Strategy: split tickers by eval_date. Recent → Polygon, old → FMP then Tiingo.
500 Polygon tickers/run + 300 FMP/day + 500 Tiingo/day = massive throughput.
"""
import os
import time
from datetime import datetime, timedelta, date as _date
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

POLYGON_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
FMP_KEY = os.getenv("FMP_KEY", "").strip()
TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip()

POLYGON_EARLIEST = _date(2024, 4, 1)

_price_cache: dict[str, dict] = {}

# Daily counters
_fmp_calls_today = 0
_fmp_day = ""
FMP_DAILY_LIMIT = 300  # Use full FMP budget for evaluation

_tiingo_calls_today = 0
_tiingo_day = ""
TIINGO_DAILY_LIMIT = 900  # Leave 100 for evaluator

# Tiingo 429 backoff
_tiingo_blocked_until = None


def _reset_counters():
    global _fmp_calls_today, _fmp_day, _tiingo_calls_today, _tiingo_day
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _fmp_day != today:
        _fmp_calls_today = 0
        _fmp_day = today
    if _tiingo_day != today:
        _tiingo_calls_today = 0
        _tiingo_day = today


def _fetch_polygon(ticker: str, start_date: str, end_date: str) -> dict:
    """Fetch daily prices from Polygon. Returns {date_str: close, ...}."""
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
            _price_cache[ticker] = {}
            return {}

        data = r.json()
        prices = {}
        for bar in (data.get("results") or []):
            ts_ms = bar.get("t")
            close = bar.get("c")
            if ts_ms and close and float(close) > 0:
                ds = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
                prices[ds] = round(float(close), 2)

        _price_cache[ticker] = prices
        return prices
    except Exception:
        _price_cache[ticker] = {}
        return {}


def _fetch_fmp(ticker: str) -> dict:
    """Fetch full history from FMP /api/v3/. Returns {date_str: close, ...}."""
    global _fmp_calls_today
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not FMP_KEY or _fmp_calls_today >= FMP_DAILY_LIMIT:
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
        prices = {}
        for day in (data.get("historical", []) if isinstance(data, dict) else []):
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


def _fetch_tiingo(ticker: str, start_date: str, end_date: str) -> dict:
    """Fetch prices from Tiingo. Minimal bandwidth: close+date only, exact range."""
    global _tiingo_calls_today, _tiingo_blocked_until
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not TIINGO_KEY or _tiingo_calls_today >= TIINGO_DAILY_LIMIT:
        return {}
    if _tiingo_blocked_until and datetime.utcnow() < _tiingo_blocked_until:
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

        if r.status_code == 429:
            _tiingo_blocked_until = datetime.utcnow() + timedelta(hours=24)
            print("[RetryNoData] Tiingo 429 — blocked for 24h")
            return {}
        if r.status_code != 200:
            _price_cache[ticker] = {}
            return {}

        data = r.json()
        prices = {}
        if isinstance(data, list):
            for day in data:
                ds = (day.get("date") or "")[:10]
                close = day.get("close") or day.get("adjClose")
                if ds and close and float(close) > 0:
                    prices[ds] = round(float(close), 2)

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
    for p in preds:
        ed = p["evaluation_date"]
        if ed:
            d = ed.date() if hasattr(ed, 'date') else ed
            if d >= POLYGON_EARLIEST:
                return True
    return False


def _score_predictions(preds, prices, now, ticker, verbose=False):
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
                    print(f"  [SKIP] id={p['id']}: no entry/pred price")
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


def retry_no_data_batch(db, max_tickers: int = 500):
    """Re-evaluate no_data predictions. Polygon → FMP → Tiingo by date."""
    _price_cache.clear()
    _reset_counters()
    now = datetime.utcnow()

    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days
        FROM predictions p
        WHERE p.outcome = 'no_data'
        ORDER BY p.ticker
        LIMIT 100000
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

    # Split by date: recent → Polygon, old → FMP/Tiingo
    polygon_tickers = []
    old_tickers = []
    for ticker, preds in ticker_preds.items():
        if _needs_polygon(preds):
            polygon_tickers.append(ticker)
        else:
            old_tickers.append(ticker)

    polygon_batch = polygon_tickers[:max_tickers]
    fmp_batch = old_tickers[:FMP_DAILY_LIMIT - _fmp_calls_today]
    tiingo_batch = old_tickers[len(fmp_batch):len(fmp_batch) + TIINGO_DAILY_LIMIT - _tiingo_calls_today]

    print(f"[RetryNoData] {remaining_total:,} no_data across {len(ticker_preds)} tickers "
          f"({len(polygon_tickers)} recent, {len(old_tickers)} old). "
          f"This run: {len(polygon_batch)} Polygon + {len(fmp_batch)} FMP + {len(tiingo_batch)} Tiingo")

    total_scored = 0
    total_still_no_data = 0
    affected_forecasters = set()

    def _write_updates(updates):
        nonlocal total_scored
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

    # ── Phase 1: Polygon (recent, 5/min = 10s between) ──
    for i, ticker in enumerate(polygon_batch):
        preds = ticker_preds[ticker]
        start_date, end_date = _date_range(preds)
        prices = _fetch_polygon(ticker, start_date, end_date)

        verbose = i < 3
        if verbose:
            eval_dates = [p["evaluation_date"] for p in preds if p["evaluation_date"]]
            price_dates = sorted(prices.keys()) if prices else []
            print(f"[RetryNoData] POLYGON {ticker}: {len(preds)} preds, "
                  f"eval={min(eval_dates).strftime('%Y-%m-%d') if eval_dates else '?'}..{max(eval_dates).strftime('%Y-%m-%d') if eval_dates else '?'}, "
                  f"{len(prices)} prices ({price_dates[0] if price_dates else '?'}..{price_dates[-1] if price_dates else '?'})")

        updates, nd = _score_predictions(preds, prices, now, ticker, verbose=verbose)
        total_still_no_data += nd
        if updates:
            _write_updates(updates)

        if (i + 1) % 5 == 0:
            db.commit()
        if (i + 1) % 50 == 0:
            print(f"[RetryNoData] Polygon {i + 1}/{len(polygon_batch)}, {total_scored} scored")

        time.sleep(10)  # 5 calls/min = 12s, use 10s to be slightly aggressive

    db.commit()
    polygon_scored = total_scored

    # ── Phase 2: FMP (old predictions, 300/day) ──
    for i, ticker in enumerate(fmp_batch):
        if _fmp_calls_today >= FMP_DAILY_LIMIT:
            break
        prices = _fetch_fmp(ticker)

        verbose = i < 2
        if verbose:
            eval_dates = [p["evaluation_date"] for p in ticker_preds[ticker] if p["evaluation_date"]]
            print(f"[RetryNoData] FMP {ticker}: {len(ticker_preds[ticker])} preds, "
                  f"eval={min(eval_dates).strftime('%Y-%m-%d') if eval_dates else '?'}..{max(eval_dates).strftime('%Y-%m-%d') if eval_dates else '?'}, "
                  f"{len(prices)} prices")

        updates, nd = _score_predictions(ticker_preds[ticker], prices, now, ticker, verbose=verbose)
        total_still_no_data += nd
        if updates:
            _write_updates(updates)

        if (i + 1) % 10 == 0:
            db.commit()
        time.sleep(0.3)

    db.commit()
    fmp_scored = total_scored - polygon_scored

    # ── Phase 3: Tiingo (old predictions, 900/day, minimal bandwidth) ──
    tiingo_scored_start = total_scored
    for i, ticker in enumerate(tiingo_batch):
        if _tiingo_calls_today >= TIINGO_DAILY_LIMIT:
            break
        if _tiingo_blocked_until and datetime.utcnow() < _tiingo_blocked_until:
            break

        preds = ticker_preds[ticker]
        start_date, end_date = _date_range(preds)
        prices = _fetch_tiingo(ticker, start_date, end_date)

        updates, nd = _score_predictions(preds, prices, now, ticker)
        total_still_no_data += nd
        if updates:
            _write_updates(updates)

        if (i + 1) % 10 == 0:
            db.commit()
        time.sleep(0.5)

    db.commit()
    tiingo_scored = total_scored - polygon_scored - fmp_scored

    # Update forecaster stats
    if affected_forecasters:
        from utils import recalculate_forecaster_stats
        for fid in affected_forecasters:
            try:
                recalculate_forecaster_stats(fid, db)
            except Exception:
                pass

    remaining = remaining_total - total_scored
    print(f"[RetryNoData] DONE: {total_scored} scored "
          f"(Polygon:{polygon_scored} FMP:{fmp_scored} Tiingo:{tiingo_scored}), "
          f"{total_still_no_data} still no data, ~{max(remaining, 0):,} remaining. "
          f"FMP: {_fmp_calls_today}/{FMP_DAILY_LIMIT}, Tiingo: {_tiingo_calls_today}/{TIINGO_DAILY_LIMIT}")
    return {"scored": total_scored, "remaining": max(remaining, 0)}
