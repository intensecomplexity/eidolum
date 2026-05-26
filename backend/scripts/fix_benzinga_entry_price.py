"""
One-time backfill: correct Benzinga predictions whose `entry_price`
was stamped with `pt_prior` (the analyst's prior price target) instead
of spot-at-prediction.

Background: three Benzinga writers (jobs/massive_benzinga.py,
jobs/benzinga_backfill.py, jobs/benzinga_web_scraper.py) historically
mapped the Benzinga API's `pt_prior` field into Prediction.entry_price.
That column is read by the evaluator as
    actual_return = (price - entry_price) / entry_price * 100
so every Benzinga return downstream was computed against a wrong
baseline. historical_evaluator already has a "Bug 8" re-lock that
fixes rows it re-scores; this script handles the long tail.

Phase A — clear pending rows so the evaluator's next pass fills
          entry_price from historical close (the now-canonical
          behavior after the writer fix).

Phase B — for already-scored rows, where stored entry_price deviates
          from the historical close on prediction_date by more than
          2%, re-stamp entry_price AND recompute actual_return using
          the historical close on evaluation_date as the exit price.
          Mirrors the same threshold and lookup historical_evaluator's
          Bug 8 uses.

Usage:
  python -m scripts.fix_benzinga_entry_price            # DRY RUN (default)
  python -m scripts.fix_benzinga_entry_price --commit   # write updates

Notes:
  - Outcome (hit/near/miss) is intentionally left alone. The
    historical_evaluator's next pass will reconcile if the corrected
    return implies a different verdict. Surgical fix, minimal blast.
  - Price-source cascade per ticker: Tiingo (~3y window) → FMP
    /stable/historical-price-eod/full (~30y window, catches delisted) →
    yfinance period='max' (local-only fallback). First non-empty wins
    and is cached. Each source has its own 429 backoff.

LANDMINE — yfinance fallback works ONLY when this script runs on a
local machine. Yahoo blocks Railway egress IPs
(see reference_eidolum_yfinance_blocked memory). Do not invoke this
script from any Railway service. FMP + Tiingo are safe everywhere.
"""
import os
import sys
import statistics
import time
from datetime import datetime, timedelta

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import text as sql_text

from database import BgSessionLocal

DEVIATION_THRESHOLD = 0.02  # 2% — same as historical_evaluator Bug 8
TIINGO_KEY = os.getenv("TIINGO_API_KEY", "").strip()
FMP_KEY = os.getenv("FMP_KEY", "").strip()
SCORED_BATCH_SIZE = int(os.getenv("BENZINGA_FIX_BATCH", "5000"))

_history_cache: dict[str, dict] = {}
_source_hits = {"tiingo": 0, "fmp": 0, "yfinance": 0, "none": 0}
_tiingo_blocked_until: datetime | None = None
_fmp_blocked_until: datetime | None = None


def _try_tiingo(ticker: str) -> dict:
    """Tiingo daily close history (~3y window). {} on failure or 429."""
    global _tiingo_blocked_until
    if not TIINGO_KEY:
        return {}
    if _tiingo_blocked_until and datetime.utcnow() < _tiingo_blocked_until:
        return {}
    try:
        r = httpx.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
            params={
                "startDate": (datetime.utcnow() - timedelta(days=365 * 3)).strftime("%Y-%m-%d"),
                "endDate": datetime.utcnow().strftime("%Y-%m-%d"),
                "columns": "close,date",
                "token": TIINGO_KEY,
            },
            timeout=15,
        )
        if r.status_code == 429:
            _tiingo_blocked_until = datetime.utcnow() + timedelta(hours=24)
            print(f"[benzinga-fix] Tiingo 429 — backing off 24h. body={r.text[:200]}", flush=True)
            return {}
        if r.status_code != 200:
            return {}
        data = r.json()
        prices: dict[str, float] = {}
        if isinstance(data, list):
            for day in data:
                ds = (day.get("date") or "")[:10]
                close = day.get("close")
                if ds and close and float(close) > 0:
                    prices[ds] = float(close)
        return prices
    except Exception as e:
        print(f"[benzinga-fix] Tiingo exception for {ticker}: {e}", flush=True)
        return {}


def _try_fmp(ticker: str) -> dict:
    """FMP /stable/historical-price-eod/full — 30y window, catches
    delisted tickers Tiingo doesn't cover. Mirrors the legacy-endpoint
    fix from historical_evaluator._try_fmp."""
    global _fmp_blocked_until
    if not FMP_KEY:
        return {}
    if _fmp_blocked_until and datetime.utcnow() < _fmp_blocked_until:
        return {}
    try:
        from_date = (datetime.utcnow() - timedelta(days=365 * 30)).strftime("%Y-%m-%d")
        to_date = datetime.utcnow().strftime("%Y-%m-%d")
        r = httpx.get(
            "https://financialmodelingprep.com/stable/historical-price-eod/full",
            params={"symbol": ticker, "from": from_date, "to": to_date, "apikey": FMP_KEY},
            timeout=20,
        )
        if r.status_code == 429:
            _fmp_blocked_until = datetime.utcnow() + timedelta(hours=1)
            print(f"[benzinga-fix] FMP 429 — backing off 1h. body={r.text[:200]}", flush=True)
            return {}
        if r.status_code != 200:
            return {}
        data = r.json()
        historical = data.get("historical", data) if isinstance(data, dict) else data
        prices: dict[str, float] = {}
        if isinstance(historical, list):
            for day in historical:
                if not isinstance(day, dict):
                    continue
                ds = (day.get("date") or "")[:10]
                close = day.get("close") or day.get("adjClose")
                if ds and close:
                    try:
                        val = float(close)
                        if val > 0:
                            prices[ds] = val
                    except (ValueError, TypeError):
                        pass
        return prices
    except Exception as e:
        print(f"[benzinga-fix] FMP exception for {ticker}: {e}", flush=True)
        return {}


def _try_yfinance(ticker: str) -> dict:
    """yfinance period='max' — LOCAL ONLY. Yahoo blocks Railway egress.
    Returns {} on any exception; never crashes the run."""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    try:
        hist = yf.Ticker(ticker).history(period="max", auto_adjust=False)
        if hist is None or hist.empty:
            return {}
        prices: dict[str, float] = {}
        for ts, close in zip(hist.index, hist["Close"]):
            try:
                cv = float(close)
            except (ValueError, TypeError):
                continue
            if cv > 0:
                prices[ts.strftime("%Y-%m-%d")] = cv
        return prices
    except Exception as e:
        print(f"[benzinga-fix] yfinance exception for {ticker}: {e}", flush=True)
        return {}


def _fetch_price_history(ticker: str) -> dict:
    """Cascade: Tiingo → FMP → yfinance. First non-empty wins; cached
    per ticker (including empty after all sources fail, so we don't
    retry the same dead ticker on every prediction row)."""
    if ticker in _history_cache:
        return _history_cache[ticker]
    for src, fn in (("tiingo", _try_tiingo), ("fmp", _try_fmp), ("yfinance", _try_yfinance)):
        prices = fn(ticker)
        if prices:
            _history_cache[ticker] = prices
            _source_hits[src] += 1
            return prices
    _history_cache[ticker] = {}
    _source_hits["none"] += 1
    return {}


def _closest_close(prices: dict, target_date) -> float | None:
    """Mirror of historical_evaluator._closest_price — ±10d walk."""
    if not prices or not target_date:
        return None
    target = target_date.date() if hasattr(target_date, "date") else target_date
    ts = target.strftime("%Y-%m-%d")
    if ts in prices:
        return prices[ts]
    for offset in range(1, 11):
        for sign in (-1, 1):
            d = (target + timedelta(days=sign * offset)).strftime("%Y-%m-%d")
            if d in prices:
                return prices[d]
    return None


def phase_a_clear_pending(db, commit: bool) -> int:
    """NULL out entry_price on pending Benzinga rows so the evaluator
    fills it from historical close on next pass."""
    count_row = db.execute(sql_text("""
        SELECT COUNT(*) FROM predictions
         WHERE verified_by IN ('massive_benzinga','benzinga_web')
           AND outcome = 'pending'
           AND entry_price IS NOT NULL
    """)).fetchone()
    n = int(count_row[0]) if count_row else 0
    print(f"\n[Phase A] Pending Benzinga rows with non-null entry_price: {n:,}")
    if commit and n > 0:
        result = db.execute(sql_text("""
            UPDATE predictions SET entry_price = NULL
             WHERE verified_by IN ('massive_benzinga','benzinga_web')
               AND outcome = 'pending'
               AND entry_price IS NOT NULL
        """))
        db.commit()
        print(f"[Phase A] APPLIED — set {result.rowcount} rows to entry_price=NULL")
    else:
        print(f"[Phase A] DRY RUN — would set {n:,} rows to entry_price=NULL")
    return n


def phase_b_restamp_scored(db, commit: bool) -> dict:
    """For scored Benzinga rows, lookup historical close on
    prediction_date. If stored entry deviates >2%, restamp entry_price
    and recompute actual_return using close on evaluation_date.

    Outcome is NOT touched — historical_evaluator's next pass owns
    that reconciliation.
    """
    print(f"\n[Phase B] Scanning scored Benzinga rows (batch={SCORED_BATCH_SIZE})...")
    rows = db.execute(sql_text("""
        SELECT id, ticker, prediction_date, evaluation_date,
               direction, entry_price, actual_return, outcome
          FROM predictions
         WHERE verified_by IN ('massive_benzinga','benzinga_web')
           AND outcome != 'pending'
           AND entry_price IS NOT NULL
           AND prediction_date IS NOT NULL
           AND evaluation_date IS NOT NULL
         ORDER BY prediction_date DESC
         LIMIT :lim
    """), {"lim": SCORED_BATCH_SIZE}).fetchall()

    print(f"[Phase B] Loaded {len(rows):,} candidate rows")

    proposed: list[dict] = []
    skipped_no_history = 0
    skipped_no_close = 0
    within_threshold = 0

    last_tick = time.time()
    for i, r in enumerate(rows):
        if i and i % 500 == 0:
            elapsed = time.time() - last_tick
            print(f"  ...scanned {i:,} rows ({elapsed:.1f}s for last 500)", flush=True)
            last_tick = time.time()

        ticker = r.ticker
        if not ticker:
            continue
        prices = _fetch_price_history(ticker)
        if not prices:
            skipped_no_history += 1
            continue
        new_entry = _closest_close(prices, r.prediction_date)
        if not new_entry or new_entry <= 0:
            skipped_no_close += 1
            continue
        stored = float(r.entry_price)
        deviation = abs(stored - new_entry) / new_entry
        if deviation <= DEVIATION_THRESHOLD:
            within_threshold += 1
            continue
        new_exit = _closest_close(prices, r.evaluation_date)
        if not new_exit or new_exit <= 0:
            skipped_no_close += 1
            continue
        direction = (r.direction or "bullish").lower()
        raw_move = round(((new_exit - new_entry) / new_entry) * 100, 2)
        new_return = -raw_move if direction == "bearish" else raw_move
        proposed.append({
            "id": int(r.id),
            "ticker": ticker,
            "old_entry": stored,
            "new_entry": float(new_entry),
            "old_return": float(r.actual_return) if r.actual_return is not None else None,
            "new_return": float(new_return),
            "outcome": r.outcome,
            "deviation_pct": deviation * 100,
        })

    print(f"\n[Phase B] Scan complete:")
    print(f"  candidates loaded         : {len(rows):,}")
    print(f"  proposed restamps         : {len(proposed):,}")
    print(f"  within {DEVIATION_THRESHOLD*100:.0f}% (skipped)        : {within_threshold:,}")
    print(f"  skipped (no history)      : {skipped_no_history:,}")
    print(f"  skipped (no close in range): {skipped_no_close:,}")
    print(f"  distinct tickers fetched  : {len(_history_cache):,}")
    print(f"  source hits — tiingo={_source_hits['tiingo']} "
          f"fmp={_source_hits['fmp']} "
          f"yfinance={_source_hits['yfinance']} "
          f"none={_source_hits['none']}")

    if proposed:
        old_rets = [p["old_return"] for p in proposed if p["old_return"] is not None]
        new_rets = [p["new_return"] for p in proposed if p["old_return"] is not None]
        shifts = [n - o for o, n in zip(old_rets, new_rets)]
        if shifts:
            print(f"\n[Phase B] Return shift distribution (new − old, percentage points):")
            print(f"  mean    = {statistics.mean(shifts):+.2f}")
            print(f"  median  = {statistics.median(shifts):+.2f}")
            print(f"  stdev   = {statistics.pstdev(shifts):.2f}")
            print(f"  min     = {min(shifts):+.2f}")
            print(f"  max     = {max(shifts):+.2f}")
            abs_shifts = [abs(s) for s in shifts]
            print(f"  mean|shift| = {statistics.mean(abs_shifts):.2f}")
            print(f"  median|shift| = {statistics.median(abs_shifts):.2f}")

        print(f"\n[Phase B] 5 sample restamps:")
        for p in proposed[:5]:
            print(
                f"  id={p['id']:>7}  {p['ticker']:>6}  "
                f"entry {p['old_entry']:>9.2f} → {p['new_entry']:>9.2f}  "
                f"return {p['old_return']:>+7.2f}% → {p['new_return']:>+7.2f}%  "
                f"outcome={p['outcome']}  dev={p['deviation_pct']:>6.1f}%"
            )

    if commit and proposed:
        print(f"\n[Phase B] APPLYING {len(proposed):,} updates in batches of 500...")
        applied = 0
        chunk = 500
        i = 0
        while i < len(proposed):
            batch = proposed[i:i + chunk]
            for attempt in range(3):
                try:
                    for p in batch:
                        db.execute(sql_text("""
                            UPDATE predictions
                               SET entry_price = :ep, actual_return = :ret
                             WHERE id = :id
                        """), {"ep": p["new_entry"], "ret": p["new_return"], "id": p["id"]})
                    db.commit()
                    applied += len(batch)
                    if (i // chunk) % 10 == 0:
                        print(f"  ...committed {applied:,}/{len(proposed):,}", flush=True)
                    break
                except Exception as e:
                    print(f"  [retry {attempt+1}/3] batch starting at {i}: {e}", flush=True)
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    try:
                        db.close()
                    except Exception:
                        pass
                    time.sleep(2 ** attempt)
                    db = BgSessionLocal()
            else:
                print(f"  [give up] batch starting at {i} — {len(batch)} rows skipped", flush=True)
            i += chunk
        print(f"[Phase B] APPLIED — {applied:,}/{len(proposed):,} rows updated")
    elif proposed:
        print(f"\n[Phase B] DRY RUN — would update {len(proposed):,} rows")
    return {
        "candidates": len(rows),
        "proposed": len(proposed),
        "within_threshold": within_threshold,
        "skipped_no_history": skipped_no_history,
        "skipped_no_close": skipped_no_close,
    }


def main():
    commit = "--commit" in sys.argv
    mode = "COMMIT" if commit else "DRY RUN"
    print(f"[benzinga-fix] mode={mode}")
    if not TIINGO_KEY:
        print("[benzinga-fix] ERROR: TIINGO_API_KEY not set", flush=True)
        sys.exit(2)
    db = BgSessionLocal()
    try:
        phase_a_clear_pending(db, commit)
        phase_b_restamp_scored(db, commit)
    finally:
        db.close()
    print(f"\n[benzinga-fix] done (mode={mode})")


if __name__ == "__main__":
    main()
