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
import logging
from datetime import datetime, timedelta, date as _date
from collections import defaultdict
from sqlalchemy import text as sql_text

log = logging.getLogger(__name__)

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

POLYGON_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
FMP_KEY = os.getenv("FMP_KEY", "").strip()
TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip()

# FMP_PLAN gates whether FMP is the primary price source.
#   "ultimate" — FMP is PRIMARY (3000/min, full history, global). No daily cap.
#   "starter"  — FMP is FALLBACK ONLY, 300 calls/day. (default, current behavior)
# Read at module load time, so the worker must restart to pick up changes.
# Railway auto-restarts on env var changes, so this is handled correctly.
FMP_PLAN = os.getenv("FMP_PLAN", "starter").lower()
FMP_IS_PRIMARY = FMP_PLAN == "ultimate"
FMP_DAILY_CAP = 999_999 if FMP_IS_PRIMARY else 300

# Dynamic: Polygon has ~2 years of history from today
POLYGON_EARLIEST = (datetime.utcnow() - timedelta(days=730)).date()

# US ticker whitelist — replaces the foreign-suffix blacklist.
#
# A US ticker is either:
#   (1) 1-5 uppercase letters (AAPL, NVDA, F, TSLA, GOOGL), OR
#   (2) An explicitly allowed dotted share-class symbol (BRK.A, BRK.B, ...).
#
# The previous implementation used the regex ^[A-Z]{1,3}\.[A-Z]$ for the
# dotted case, but that still lets in foreign-exchange tickers like
# ABEA.F (Frankfurt ADR), BMW.F, BAS.F, and any other 1-3 letter base
# followed by a 1-letter suffix. Since only a handful of legitimate US
# share-class tickers contain a dot, we hard-code them here instead.
#
# If a new US class share lists later (rare), add it to this set.
import re as _re
US_TICKER_REGEX = _re.compile(r'^[A-Z]{1,5}$')

US_DOTTED_ALLOWLIST = frozenset({
    "BRK.A", "BRK.B",   # Berkshire Hathaway
    "BF.A",  "BF.B",    # Brown-Forman
    "GEF.B",            # Greif Inc
    "HEI.A",            # HEICO
    "LEN.B",            # Lennar
    "MOG.A", "MOG.B",   # Moog Inc
    "RUSHA", "RUSHB",   # Rush Enterprises (no dot, but pair with above)
})


def is_us_ticker(ticker: str) -> bool:
    """True iff ticker is a recognised US-style symbol. Strict whitelist."""
    if not ticker:
        return False
    if US_TICKER_REGEX.match(ticker):
        return True
    return ticker in US_DOTTED_ALLOWLIST

_price_cache: dict[str, dict] = {}

# Daily counters
_fmp_calls_today = 0
_fmp_day = ""
# Alias for backwards-compat with the existing call sites that read
# FMP_DAILY_LIMIT. The single source of truth is FMP_DAILY_CAP (above),
# which is 999_999 in Ultimate mode and 300 in Starter mode.
FMP_DAILY_LIMIT = FMP_DAILY_CAP

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
    if not POLYGON_KEY or not is_us_ticker(ticker):
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
    if not TIINGO_KEY or _tiingo_calls_today >= TIINGO_DAILY_LIMIT or not is_us_ticker(ticker):
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
    if not FMP_KEY or _fmp_calls_today >= FMP_DAILY_LIMIT or not is_us_ticker(ticker):
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


# Debug counter — caps debug output at 20 predictions per RetryNoData run
_debug_counter = {"n": 0, "max": 20}


def _reset_debug_counter():
    _debug_counter["n"] = 0


def _dbg() -> bool:
    """Return True if we should log this prediction, and increment the counter."""
    if _debug_counter["n"] >= _debug_counter["max"]:
        return False
    _debug_counter["n"] += 1
    return True


def _score_predictions(preds, prices, now, ticker, verbose=False):
    updates = []
    no_data = 0
    for p in preds:
        should_log = _dbg()

        try:
            # CHECKPOINT A — Candidate loaded
            if should_log:
                print(f"[RetryNoData-DEBUG] A: pred_id={p['id']} ticker={ticker} "
                      f"entry_date={p['prediction_date']} eval_date={p['evaluation_date']} "
                      f"direction={p['direction']} target={p['target_price']}", flush=True)

            # CHECKPOINT B — Prices fetched
            if should_log:
                price_count = len(prices) if prices else 0
                sample_keys = list(prices.keys())[:3] if prices else None
                print(f"[RetryNoData-DEBUG] B: pred_id={p['id']} "
                      f"prices_fetched={price_count} "
                      f"price_keys_sample={sample_keys}", flush=True)

            # CHECKPOINT D — Eval price lookup (happens before entry in original flow)
            eval_date_key = None
            if p["evaluation_date"]:
                ed = p["evaluation_date"]
                eval_date_key = str(ed.date() if hasattr(ed, 'date') else ed)
            eval_price = _closest_price(prices, p["evaluation_date"])
            if should_log:
                print(f"[RetryNoData-DEBUG] D: pred_id={p['id']} "
                      f"eval_price={eval_price} "
                      f"lookup_date={eval_date_key}", flush=True)
            if eval_price is None:
                no_data += 1
                if should_log:
                    print(f"[RetryNoData-DEBUG] E: pred_id={p['id']} "
                          f"outcome=DROPPED reason=eval_price_none", flush=True)
                continue

            # CHECKPOINT C — Entry price lookup
            entry_date_key = None
            if p["prediction_date"]:
                pd_ = p["prediction_date"]
                entry_date_key = str(pd_.date() if hasattr(pd_, 'date') else pd_)
            ref = p["entry_price"]
            entry_source = "stored"
            if not ref or ref <= 0:
                ref = _closest_price(prices, p["prediction_date"])
                entry_source = "lookup"
            if should_log:
                print(f"[RetryNoData-DEBUG] C: pred_id={p['id']} "
                      f"entry_price={ref} source={entry_source} "
                      f"lookup_date={entry_date_key}", flush=True)
            if not ref or ref <= 0:
                no_data += 1
                if should_log:
                    print(f"[RetryNoData-DEBUG] E: pred_id={p['id']} "
                          f"outcome=DROPPED reason=entry_price_none", flush=True)
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

            # CHECKPOINT E — Scoring decision
            if should_log:
                print(f"[RetryNoData-DEBUG] E: pred_id={p['id']} "
                      f"outcome={outcome} return={ret} "
                      f"reason=scored", flush=True)

            updates.append({"id": p["id"], "outcome": outcome, "ret": ret, "ep": ref,
                            "direction": direction, "summary": summary, "fid": p["forecaster_id"]})
        except Exception as e:
            no_data += 1
            print(f"[RetryNoData-DEBUG] EXCEPTION on pred_id={p.get('id', '?')}: "
                  f"{type(e).__name__}: {e}", flush=True)
    return updates, no_data


def retry_no_data_batch(db, max_tickers: int | None = None):
    """Re-evaluate no_data predictions.
    Starter mode: Polygon → Tiingo → FMP fallback (max 1000 tickers/run).
    Ultimate mode: FMP → Polygon → Tiingo fallback (max 10000 tickers/run).
    """
    _reset_counters()
    _reset_debug_counter()
    now = datetime.utcnow()

    # FMP Ultimate handles ~3000 calls/min, so 10K tickers complete in ~3-4
    # minutes including overhead. Starter caps at 1000 because Polygon's
    # 5/min cap dominates the run time (1000 tickers ≈ 3.3 hours).
    if max_tickers is None:
        max_tickers = 10_000 if FMP_IS_PRIMARY else 1000

    log.info(
        f'[RetryNoData] Mode: '
        f'{"FMP Ultimate (primary)" if FMP_IS_PRIMARY else "Polygon/Tiingo (standard)"}. '
        f'Max tickers: {max_tickers}. FMP daily cap: {FMP_DAILY_CAP}.'
    )

    # Two disjoint queries partitioned by PREDICTION_DATE (not eval_date).
    # Polygon covers exactly 2 years of history. If we partition by eval_date
    # we end up routing predictions to Polygon that have an entry_date OLDER
    # than Polygon's window — eval lookup succeeds but entry lookup fails,
    # producing entry_price=None and a dropped prediction.
    # Switching to prediction_date guarantees BOTH endpoints are inside the
    # window (eval_date >= prediction_date always).
    # Regex {1,3} not {1,4} — no real US class share has a 4-letter base,
    # but ABEA.F (Frankfurt) etc. did slip through with the looser version.
    polygon_query = r"""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days
        FROM predictions p
        WHERE p.outcome = 'no_data'
          AND p.prediction_date IS NOT NULL
          AND p.prediction_date >= NOW() - INTERVAL '2 years'
          AND p.evaluation_date <= NOW()
          AND (
              p.ticker ~ '^[A-Z]{1,5}$'
              OR p.ticker IN ('BRK.A','BRK.B','BF.A','BF.B','GEF.B','HEI.A','LEN.B','MOG.A','MOG.B')
          )
        ORDER BY p.ticker
        LIMIT :lim
    """
    tiingo_query = r"""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days
        FROM predictions p
        WHERE p.outcome = 'no_data'
          AND p.prediction_date IS NOT NULL
          AND p.prediction_date < NOW() - INTERVAL '2 years'
          AND p.evaluation_date <= NOW()
          AND (
              p.ticker ~ '^[A-Z]{1,5}$'
              OR p.ticker IN ('BRK.A','BRK.B','BF.A','BF.B','GEF.B','HEI.A','LEN.B','MOG.A','MOG.B')
          )
        ORDER BY p.ticker
        LIMIT :lim
    """
    log.info(f'[RetryNoData-CANDIDATES] Polygon query preview: {polygon_query[:500]}')
    log.info(f'[RetryNoData-CANDIDATES] Tiingo query preview:  {tiingo_query[:500]}')

    polygon_rows = db.execute(sql_text(polygon_query), {"lim": max_tickers}).fetchall()
    tiingo_rows = db.execute(sql_text(tiingo_query), {"lim": max_tickers}).fetchall()

    if FMP_IS_PRIMARY:
        log.info(
            f'[RetryNoData-CANDIDATES] FMP primary mode. '
            f'Loaded {len(polygon_rows) + len(tiingo_rows)} total US candidates. '
            f'All will be tried against FMP first.'
        )
    else:
        log.info(
            f'[RetryNoData-CANDIDATES] Loaded {len(polygon_rows)} Polygon + '
            f'{len(tiingo_rows)} Tiingo candidates. '
            f'Polygon first 5: {[r[1] for r in polygon_rows[:5]]} '
            f'Tiingo first 5: {[r[1] for r in tiingo_rows[:5]]}'
        )

    # remaining_total: how many no_data US-ticker rows are left in total.
    # Same regex filter so the stat reflects what this job will ever process.
    remaining_total = db.execute(sql_text(r"""
        SELECT COUNT(*) FROM predictions
        WHERE outcome = 'no_data'
          AND evaluation_date IS NOT NULL
          AND (
              ticker ~ '^[A-Z]{1,5}$'
              OR ticker IN ('BRK.A','BRK.B','BF.A','BF.B','GEF.B','HEI.A','LEN.B','MOG.A','MOG.B')
          )
    """)).scalar() or 0

    if not polygon_rows and not tiingo_rows:
        print("[RetryNoData] No no_data predictions to retry")
        return {"scored": 0, "remaining": 0}

    def _row_to_pred(r):
        return {
            "id": r[0], "ticker": r[1], "direction": r[2],
            "target_price": float(r[3]) if r[3] else None,
            "entry_price": float(r[4]) if r[4] else None,
            "evaluation_date": r[5], "prediction_date": r[6],
            "forecaster_id": r[7], "window_days": r[8],
        }

    polygon_preds_by_ticker = defaultdict(list)
    for r in polygon_rows:
        polygon_preds_by_ticker[r[1]].append(_row_to_pred(r))

    tiingo_preds_by_ticker = defaultdict(list)
    for r in tiingo_rows:
        tiingo_preds_by_ticker[r[1]].append(_row_to_pred(r))

    # Belt-and-braces: drop any non-US tickers that slipped through (the SQL
    # regex already enforces this, but a stale cache or schema change could
    # leak something through). NOT a delete from the DB.
    foreign_count = 0
    for d in (polygon_preds_by_ticker, tiingo_preds_by_ticker):
        for ticker in list(d.keys()):
            if not is_us_ticker(ticker):
                del d[ticker]
                foreign_count += 1
    if foreign_count:
        print(f"[RetryNoData] Skipped {foreign_count} foreign tickers", flush=True)

    polygon_batch = list(polygon_preds_by_ticker.keys())
    tiingo_batch = list(tiingo_preds_by_ticker.keys())

    print(f"[RetryNoData] {remaining_total:,} US no_data total. "
          f"This run: {len(polygon_batch)} Polygon tickers "
          f"({len(polygon_rows)} recent preds) + "
          f"{len(tiingo_batch)} Tiingo tickers ({len(tiingo_rows)} old preds)")

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

    polygon_scored = 0
    tiingo_scored = 0
    fmp_scored = 0

    if FMP_IS_PRIMARY:
        # ═══════════════════════════════════════════════════════════════
        # FMP Ultimate path: FMP first for ALL candidates (recent + old),
        # Polygon/Tiingo as fallbacks for FMP failures.
        # FMP Ultimate: 3000 calls/min, full history, global. No daily cap.
        # ═══════════════════════════════════════════════════════════════
        # Merge both partitioned dicts. polygon_preds and tiingo_preds are
        # disjoint by prediction_date so there is never a key collision.
        all_preds_by_ticker = {**polygon_preds_by_ticker, **tiingo_preds_by_ticker}
        all_tickers = list(all_preds_by_ticker.keys())
        log.info(f'[RetryNoData] FMP Ultimate mode — processing '
                 f'{len(all_tickers)} tickers as PRIMARY')

        fmp_failed_tickers = []
        for i, ticker in enumerate(all_tickers):
            preds = all_preds_by_ticker[ticker]

            if ticker in _price_cache:
                cache_hits += 1
                prices = _price_cache[ticker]
            else:
                prices = _fetch_fmp(ticker)
                fmp_calls += 1

            if not prices:
                fmp_failed_tickers.append(ticker)
            else:
                updates, nd = _score_predictions(preds, prices, now, ticker)
                total_still_no_data += nd
                if updates:
                    _write_updates(updates)

            if (i + 1) % 25 == 0:
                db.commit()
            if (i + 1) % 200 == 0:
                print(f"[RetryNoData] FMP {i + 1}/{len(all_tickers)}, {total_scored} scored, "
                      f"{len(fmp_failed_tickers)} failed")
            # FMP Ultimate: 3000/min = 50/sec. 0.02s sleep = 50/sec safe.
            time.sleep(0.02)

        db.commit()
        fmp_scored = total_scored
        print(f"[RetryNoData-DEBUG] FMP primary phase: {len(all_tickers)} tickers, "
              f"{fmp_calls} API calls, {fmp_scored} scored, "
              f"{len(fmp_failed_tickers)} failed, {total_still_no_data} still no_data", flush=True)

        # ── Polygon fallback for FMP-failed RECENT tickers ──
        polygon_fallback = [t for t in fmp_failed_tickers if t in polygon_preds_by_ticker]
        for i, ticker in enumerate(polygon_fallback):
            preds = polygon_preds_by_ticker[ticker]
            start_date, end_date = _date_range(preds)
            prices = _fetch_polygon(ticker, start_date, end_date)
            polygon_calls += 1

            updates, nd = _score_predictions(preds, prices, now, ticker)
            total_still_no_data += nd
            if updates:
                _write_updates(updates)

            if (i + 1) % 5 == 0:
                db.commit()
            time.sleep(10)  # Polygon: 5 calls/min — kept slow for fallback safety
        db.commit()
        polygon_scored = total_scored - fmp_scored

        # ── Tiingo fallback for FMP-failed OLD tickers ──
        tiingo_fallback = [t for t in fmp_failed_tickers if t in tiingo_preds_by_ticker]
        for i, ticker in enumerate(tiingo_fallback):
            if _tiingo_calls_today >= TIINGO_DAILY_LIMIT:
                break
            preds = tiingo_preds_by_ticker[ticker]
            start_date, end_date = _date_range(preds)
            prices = _fetch_tiingo(ticker, start_date, end_date)
            tiingo_calls += 1
            if not prices:
                tiingo_empty += 1

            updates, nd = _score_predictions(preds, prices, now, ticker)
            total_still_no_data += nd
            if updates:
                _write_updates(updates)

            if (i + 1) % 10 == 0:
                db.commit()
            time.sleep(0.05)
        db.commit()
        tiingo_scored = total_scored - fmp_scored - polygon_scored

    else:
        # ═══════════════════════════════════════════════════════════════
        # Starter path (default): Polygon → Tiingo → FMP fallback.
        # BIT-IDENTICAL to pre-Ultimate behavior.
        # ═══════════════════════════════════════════════════════════════
        # ── Phase 1: Polygon (recent preds only, 5/min = 10s between) ──
        for i, ticker in enumerate(polygon_batch):
            preds = polygon_preds_by_ticker[ticker]
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

        # ── Phase 2: Tiingo (old preds only, Power plan: 10K calls/hour) ──
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

            preds = tiingo_preds_by_ticker[ticker]
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
        for i, ticker in enumerate(tiingo_failed_tickers[:FMP_DAILY_LIMIT - _fmp_calls_today]):
            if _fmp_calls_today >= FMP_DAILY_LIMIT:
                break
            preds = tiingo_preds_by_ticker[ticker]
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
