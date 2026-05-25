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
  - Uses Tiingo as the price source (no daily cap on this account)
    with a 24h-block-on-429 mirror of historical_evaluator._try_tiingo.
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
SCORED_BATCH_SIZE = int(os.getenv("BENZINGA_FIX_BATCH", "5000"))

_history_cache: dict[str, dict] = {}
_tiingo_blocked_until: datetime | None = None


def _fetch_tiingo_history(ticker: str) -> dict:
    """Daily close history for the past ~3 years. {date_str: close}."""
    global _tiingo_blocked_until
    if ticker in _history_cache:
        return _history_cache[ticker]
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
            print(f"[benzinga-fix] Tiingo {r.status_code} for {ticker}. body={r.text[:200]}", flush=True)
            _history_cache[ticker] = {}
            return {}
        data = r.json()
        prices: dict[str, float] = {}
        if isinstance(data, list):
            for day in data:
                ds = (day.get("date") or "")[:10]
                close = day.get("close")
                if ds and close and float(close) > 0:
                    prices[ds] = float(close)
        _history_cache[ticker] = prices
        return prices
    except Exception as e:
        print(f"[benzinga-fix] Tiingo exception for {ticker}: {e}", flush=True)
        _history_cache[ticker] = {}
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
        prices = _fetch_tiingo_history(ticker)
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
        print(f"\n[Phase B] APPLYING {len(proposed):,} updates...")
        for p in proposed:
            db.execute(sql_text("""
                UPDATE predictions
                   SET entry_price = :ep, actual_return = :ret
                 WHERE id = :id
            """), {"ep": p["new_entry"], "ret": p["new_return"], "id": p["id"]})
        db.commit()
        print(f"[Phase B] APPLIED — {len(proposed):,} rows updated")
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
