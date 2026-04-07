"""
Retry no_data predictions using THREE price sources:

1. Polygon (primary, recent): MASSIVE_API_KEY, 5 calls/min, no daily limit
   Covers ~2 years back. 10s between calls.

2. Tiingo (PRIMARY for old data): TIINGO_API_KEY, Power plan ($30/mo)
   100K calls/day, 10K calls/hour, 40GB/month bandwidth, 30+ years history.
   0.05s between calls. Handles the vast majority of the backlog.

3. FMP (last resort): FMP_KEY, 300 calls/day, history to 2000
   Only used when both Polygon and Tiingo fail for a ticker.

Strategy: Polygon for 2024+ → Tiingo for everything else → FMP last resort.
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

# Dynamic: Polygon has ~2 years of history from today
POLYGON_EARLIEST = (datetime.utcnow() - timedelta(days=730)).date()

# Foreign tickers — no free price source supports these
FOREIGN_SUFFIXES = ('.L', '.TO', '.HK', '.PA', '.DE', '.SS', '.SZ', '.AX', '.SI',
                    '.MI', '.MC', '.AS', '.BR', '.ST', '.HE', '.OL', '.CO', '.T', '.KS')

def is_foreign_ticker(ticker: str) -> bool:
    if not ticker:
        return False
    return ticker.upper().endswith(FOREIGN_SUFFIXES)

_price_cache: dict[str, dict] = {}

# Daily counters
_fmp_calls_today = 0
_fmp_day = ""
FMP_DAILY_LIMIT = 300

_tiingo_calls_today = 0
_tiingo_day = ""
TIINGO_DAILY_LIMIT = 95000  # Power plan: 100K/day, leave 5K buffer

# Tiingo 429 backoff — short retry on Power plan (was 24h on free)
_tiingo_blocked_until = None
_tiingo_consecutive_429s = 0


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
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not POLYGON_KEY or is_foreign_ticker(ticker):
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
        prices = {}
        for bar in (r.json().get("results") or []):
            ts_ms = bar.get("t")
            close = bar.get("c")
            if ts_ms and close and float(close) > 0:
                prices[datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")] = round(float(close), 2)
        _price_cache[ticker] = prices
        return prices
    except Exception:
        _price_cache[ticker] = {}
        return {}


def _fetch_tiingo(ticker: str, start_date: str, end_date: str) -> dict:
    """Fetch prices from Tiingo Power plan. 10K calls/hour, 0.05s delay."""
    global _tiingo_calls_today, _tiingo_blocked_until, _tiingo_consecutive_429s
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not TIINGO_KEY or _tiingo_calls_today >= TIINGO_DAILY_LIMIT or is_foreign_ticker(ticker):
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
            _tiingo_consecutive_429s += 1
            if _tiingo_consecutive_429s >= 3:
                _tiingo_blocked_until = datetime.utcnow() + timedelta(minutes=5)
                print(f"[RetryNoData] Tiingo 3x 429 — backing off 5 min")
            else:
                _tiingo_blocked_until = datetime.utcnow() + timedelta(seconds=60)
                print(f"[RetryNoData] Tiingo 429 — waiting 60s (#{_tiingo_consecutive_429s})")
            return {}

        _tiingo_consecutive_429s = 0  # Reset on success

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


def _fetch_fmp(ticker: str) -> dict:
    global _fmp_calls_today
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not FMP_KEY or _fmp_calls_today >= FMP_DAILY_LIMIT or is_foreign_ticker(ticker):
        return {}
    import httpx
    try:
        r = httpx.get(
            f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}",
            params={"apikey": FMP_KEY, "serietype": "line"}, timeout=15,
        )
        _fmp_calls_today += 1
        if r.status_code != 200:
            _price_cache[ticker] = {}
            return {}
        prices = {}
        for day in (r.json().get("historical", []) if isinstance(r.json(), dict) else []):
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
            no_data += 1
            continue
        ref = p["entry_price"]
        if not ref or ref <= 0:
            ref = _closest_price(prices, p["prediction_date"])
            if not ref or ref <= 0:
                no_data += 1
                continue
        target = p["target_price"]
        direction = p["direction"]
        if target and target > 0 and ref > 0:
            if target > ref: direction = "bullish"
            elif target < ref: direction = "bearish"
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
        updates.append({"id": p["id"], "outcome": outcome, "ret": ret, "ep": ref,
                        "direction": direction, "summary": summary, "fid": p["forecaster_id"]})
    return updates, no_data


def retry_no_data_batch(db, max_tickers: int = 1000):
    """Re-evaluate no_data predictions. Polygon → Tiingo → FMP."""
    _reset_counters()
    now = datetime.utcnow()

    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days
        FROM predictions p
        WHERE p.outcome = 'no_data'
          AND p.ticker NOT LIKE '%%.L' AND p.ticker NOT LIKE '%%.TO'
          AND p.ticker NOT LIKE '%%.HK' AND p.ticker NOT LIKE '%%.PA'
          AND p.ticker NOT LIKE '%%.DE' AND p.ticker NOT LIKE '%%.SS'
          AND p.ticker NOT LIKE '%%.SZ' AND p.ticker NOT LIKE '%%.AX'
          AND p.ticker NOT LIKE '%%.SI' AND p.ticker NOT LIKE '%%.MI'
          AND p.ticker NOT LIKE '%%.MC' AND p.ticker NOT LIKE '%%.AS'
          AND p.ticker NOT LIKE '%%.T' AND p.ticker NOT LIKE '%%.KS'
        ORDER BY p.ticker
        LIMIT 200000
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

    # Filter out any foreign tickers that slipped through
    foreign_count = 0
    for ticker in list(ticker_preds.keys()):
        if is_foreign_ticker(ticker):
            del ticker_preds[ticker]
            foreign_count += 1
    if foreign_count:
        print(f"[RetryNoData] Skipped {foreign_count} foreign tickers", flush=True)

    # Split: Polygon for recent, Tiingo for old, FMP as last resort
    polygon_tickers = []
    old_tickers = []
    for ticker, preds in ticker_preds.items():
        if _needs_polygon(preds):
            polygon_tickers.append(ticker)
        else:
            old_tickers.append(ticker)

    polygon_batch = polygon_tickers[:max_tickers]
    tiingo_batch = old_tickers[:max_tickers]  # Tiingo handles the bulk now
    fmp_batch = []  # FMP only for tickers Tiingo fails on (populated during run)

    print(f"[RetryNoData] {remaining_total:,} no_data across {len(ticker_preds)} tickers "
          f"({len(polygon_tickers)} recent, {len(old_tickers)} old). "
          f"This run: {len(polygon_batch)} Polygon + {len(tiingo_batch)} Tiingo")

    total_scored = 0
    total_still_no_data = 0
    total_hits = 0
    total_nears = 0
    total_misses = 0
    affected_forecasters = set()
    cache_hits = 0
    tiingo_calls = 0
    polygon_calls = 0
    fmp_calls = 0
    tiingo_empty = 0

    def _write_updates(updates):
        nonlocal total_scored, total_hits, total_nears, total_misses
        for u in updates:
            db.execute(sql_text("""
                UPDATE predictions SET outcome=:o, actual_return=:r, direction=:d,
                entry_price=COALESCE(entry_price,:ep), evaluation_summary=:s,
                evaluated_at=:now WHERE id=:id
            """), {"o": u["outcome"], "r": u["ret"], "d": u["direction"],
                   "ep": u["ep"], "s": u["summary"], "now": now, "id": u["id"]})
            if u["outcome"] in ("hit", "correct"): total_hits += 1
            elif u["outcome"] == "near": total_nears += 1
            else: total_misses += 1
        total_scored += len(updates)
        for u in updates:
            affected_forecasters.add(u["fid"])

    # ── Phase 1: Polygon (recent, 5/min = 10s between) ──
    for i, ticker in enumerate(polygon_batch):
        preds = ticker_preds[ticker]
        start_date, end_date = _date_range(preds)

        if ticker in _price_cache:
            cache_hits += 1
            prices = _price_cache[ticker]
        else:
            prices = _fetch_polygon(ticker, start_date, end_date)
            polygon_calls += 1

        updates, nd = _score_predictions(preds, prices, now, ticker)
        total_still_no_data += nd
        if updates:
            _write_updates(updates)

        if (i + 1) % 5 == 0:
            db.commit()
        if (i + 1) % 50 == 0:
            print(f"[RetryNoData] Polygon {i + 1}/{len(polygon_batch)}, {total_scored} scored")
        time.sleep(10)  # Polygon: 5 calls/min

    db.commit()
    polygon_scored = total_scored
    print(f"[RetryNoData-DEBUG] Polygon phase: {len(polygon_batch)} tickers, "
          f"{polygon_calls} API calls, {polygon_scored} scored, {total_still_no_data} still no_data", flush=True)

    # ── Phase 2: Tiingo (old predictions, Power plan: 10K calls/hour) ──
    tiingo_failed_tickers = []
    for i, ticker in enumerate(tiingo_batch):
        if _tiingo_calls_today >= TIINGO_DAILY_LIMIT:
            print(f"[RetryNoData] Tiingo daily limit reached at ticker {i}")
            break
        if _tiingo_blocked_until and datetime.utcnow() < _tiingo_blocked_until:
            # Wait out the backoff
            wait_secs = (_tiingo_blocked_until - datetime.utcnow()).total_seconds()
            if wait_secs > 0 and wait_secs < 400:
                print(f"[RetryNoData] Tiingo backoff: waiting {wait_secs:.0f}s")
                time.sleep(wait_secs)
            elif wait_secs >= 400:
                break

        preds = ticker_preds[ticker]
        start_date, end_date = _date_range(preds)

        if ticker in _price_cache:
            cache_hits += 1
            prices = _price_cache[ticker]
        else:
            prices = _fetch_tiingo(ticker, start_date, end_date)
            tiingo_calls += 1
            if not prices:
                tiingo_empty += 1
                tiingo_failed_tickers.append(ticker)

        updates, nd = _score_predictions(preds, prices, now, ticker)
        total_still_no_data += nd
        if updates:
            _write_updates(updates)

        if (i + 1) % 10 == 0:
            db.commit()
        if (i + 1) % 100 == 0:
            print(f"[RetryNoData] Tiingo {i + 1}/{len(tiingo_batch)}, {total_scored - polygon_scored} scored, "
                  f"calls: {tiingo_calls}, empty: {tiingo_empty}")
        time.sleep(0.05)  # Tiingo Power: 10K/hour = ~2.8/sec, 0.05s is safe

    db.commit()
    tiingo_scored = total_scored - polygon_scored

    # ── Phase 3: FMP (tickers Tiingo failed on, 300/day) ──
    fmp_scored_start = total_scored
    for i, ticker in enumerate(tiingo_failed_tickers[:FMP_DAILY_LIMIT - _fmp_calls_today]):
        if _fmp_calls_today >= FMP_DAILY_LIMIT:
            break
        preds = ticker_preds[ticker]
        prices = _fetch_fmp(ticker)
        fmp_calls += 1

        updates, nd = _score_predictions(preds, prices, now, ticker)
        total_still_no_data += nd
        if updates:
            _write_updates(updates)
        if (i + 1) % 10 == 0:
            db.commit()
        time.sleep(0.3)
    db.commit()
    fmp_scored = total_scored - polygon_scored - tiingo_scored

    # Update forecaster stats
    if affected_forecasters:
        from utils import recalculate_forecaster_stats
        for fid in affected_forecasters:
            try:
                recalculate_forecaster_stats(fid, db)
            except Exception:
                pass

    remaining = remaining_total - total_scored
    runs_per_day = 48  # every 30 min
    est_days = round(remaining / max(total_scored, 1) / runs_per_day, 1) if total_scored > 0 else 999

    print(f"[RetryNoData] RUN COMPLETE:")
    print(f"  Tickers processed: {len(polygon_batch) + len(tiingo_batch)}")
    print(f"  Predictions scored: {total_scored} (hit={total_hits}, near={total_nears}, miss={total_misses})")
    print(f"  Sources: Polygon={polygon_scored}, Tiingo={tiingo_scored}, FMP={fmp_scored}")
    print(f"  API calls: Polygon={polygon_calls}, Tiingo={tiingo_calls} ({tiingo_empty} empty), FMP={fmp_calls}")
    print(f"  Cache hits: {cache_hits}")
    print(f"  Remaining no_data: {remaining:,} (was {remaining_total:,})")
    print(f"  Est. days to clear: {est_days}")
    return {"scored": total_scored, "remaining": max(remaining, 0)}
