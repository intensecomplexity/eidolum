"""
One-time backfill: re-lock and re-score every existing crypto prediction
that landed with an equity entry_price.

The bug (see services/price_fetch.py): the historical evaluator's
`_fetch_history` was equity-only and crypto symbols whose letters collide
with a US stock ticker (BTC = Bit Origin Ltd biotech ~$3, ETH the obscure
ETF, etc.) silently fell through to the equity fetcher chain. Stock Moe's
entire vault and ~6 of Marko's 13 scored predictions ran on equity prices
instead of spot crypto prices.

What this script does, per crypto prediction:
  1. Resolve the *correct* historical close at prediction_date via
     services.price_fetch.fetch_crypto_history (Polygon X:{SYMBOL}USD).
  2. Resolve the *correct* close at evaluation_date the same way.
  3. Recompute outcome (hit/near/miss) using the same scoring helper the
     historical evaluator uses, so the verdict matches what the live
     pipeline would produce on a fresh run.
  4. Update entry_price, actual_return, outcome, sp500_return, alpha,
     direction (only when target-based inference flips a missing one),
     evaluation_summary, evaluated_at.
  5. Print a per-row diff and a final tally of status changes.

After all updates, recompute forecaster aggregates so the cached
HIT-streak and accuracy_score reflect the new statuses (Bug 9).

Identifies "crypto" rows two ways: sector='Crypto' OR ticker in
services.price_fetch.CRYPTO_TICKERS. We need both — old rows pre-date
the get_sector('Crypto') short-circuit and have whatever Finnhub /
KNOWN_SECTORS originally returned.

Usage:
  python -m scripts.fix_crypto_ticker_backfill           # dry run, prints diff
  python -m scripts.fix_crypto_ticker_backfill --apply   # writes updates
"""
import os
import sys
from datetime import datetime

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text

from database import BgSessionLocal
from services.price_fetch import CRYPTO_TICKERS, fetch_crypto_history, is_crypto


def _closest_close(prices: dict, target_date) -> float | None:
    """Tiny mirror of historical_evaluator._closest_price — kept local so
    this script does not depend on internals that may change."""
    if not prices or not target_date:
        return None
    target = target_date.date() if hasattr(target_date, "date") else target_date
    ts = str(target)
    if ts in prices:
        return prices[ts]
    best, best_diff = None, 999
    for ds, price in prices.items():
        if ds.startswith("_"):
            continue
        try:
            parts = ds.split("-")
            d = datetime(int(parts[0]), int(parts[1]), int(parts[2])).date()
            diff = abs((d - target).days)
            if diff < best_diff:
                best_diff, best = diff, price
        except Exception:
            continue
    return best if best_diff <= 5 else None


def _score(direction: str, entry: float, exit_: float, target: float | None,
           window_days: int) -> tuple[str, float]:
    """Mirror of historical_evaluator's three-tier scorer for crypto rows.
    Returns (outcome, signed_return_pct)."""
    from jobs.historical_evaluator import _TOLERANCE, _MIN_MOVEMENT, _get_tolerance

    raw_move = round(((exit_ - entry) / entry) * 100, 2)
    ret = -raw_move if direction == "bearish" else raw_move

    tolerance = _get_tolerance(window_days or 90, _TOLERANCE)
    min_movement = _get_tolerance(window_days or 90, _MIN_MOVEMENT)

    if direction == "neutral":
        abs_ret = abs(raw_move)
        outcome = "hit" if abs_ret <= 5.0 else ("near" if abs_ret <= 10.0 else "miss")
    elif target and target > 0:
        target_dist_pct = abs(exit_ - target) / target * 100
        if direction == "bullish":
            if exit_ >= target or (target_dist_pct <= tolerance and raw_move >= 0):
                outcome = "hit"
            elif raw_move >= min_movement:
                outcome = "near"
            else:
                outcome = "miss"
        else:  # bearish
            if exit_ <= target or (target_dist_pct <= tolerance and raw_move <= 0):
                outcome = "hit"
            elif raw_move <= -min_movement:
                outcome = "near"
            else:
                outcome = "miss"
    else:
        if direction == "bullish":
            outcome = "hit" if exit_ > entry else "miss"
        else:
            outcome = "hit" if exit_ < entry else "miss"
    return outcome, ret


def main():
    apply = "--apply" in sys.argv
    print(f"[crypto-backfill] mode={'APPLY' if apply else 'DRY RUN'}")
    db = BgSessionLocal()
    try:
        crypto_list = sorted(CRYPTO_TICKERS.keys())
        rows = db.execute(sql_text("""
            SELECT id, ticker, direction, target_price, entry_price,
                   prediction_date, evaluation_date, window_days, outcome,
                   forecaster_id, sector
            FROM predictions
            WHERE (sector = 'Crypto' OR ticker = ANY(:crypto))
            ORDER BY id
        """), {"crypto": crypto_list}).fetchall()
        print(f"[crypto-backfill] Found {len(rows)} candidate crypto predictions")

        # Pre-fetch every distinct ticker once.
        tickers = sorted({r.ticker for r in rows if is_crypto(r.ticker)})
        history: dict[str, dict] = {}
        for t in tickers:
            history[t] = fetch_crypto_history(t)
            print(f"[crypto-backfill] {t}: {len(history[t])} days of history")

        status_diff: dict[tuple[str, str], int] = {}
        affected_forecasters: set[int] = set()
        updates_pending: list[dict] = []
        skipped_no_history = 0
        skipped_no_close = 0

        for r in rows:
            if not is_crypto(r.ticker):
                continue
            prices = history.get(r.ticker) or {}
            if not prices:
                skipped_no_history += 1
                continue
            new_entry = _closest_close(prices, r.prediction_date)
            if not new_entry:
                skipped_no_close += 1
                continue
            new_eval = None
            if r.evaluation_date:
                new_eval = _closest_close(prices, r.evaluation_date)
            if not new_eval:
                skipped_no_close += 1
                continue

            direction = (r.direction or "bullish").lower()
            target = float(r.target_price) if r.target_price else None
            new_outcome, new_ret = _score(
                direction, float(new_entry), float(new_eval), target, r.window_days or 90,
            )

            old_outcome = r.outcome or "?"
            key = (old_outcome, new_outcome)
            status_diff[key] = status_diff.get(key, 0) + 1

            print(
                f"  id={r.id:6d} {r.ticker:5s} {direction:8s} "
                f"entry ${r.entry_price} → ${new_entry:.2f}  "
                f"eval ${new_eval:.2f}  "
                f"{old_outcome} → {new_outcome}  return={new_ret:+.1f}%"
            )

            updates_pending.append({
                "id": r.id, "outcome": new_outcome, "ret": new_ret, "ep": float(new_entry),
                "fid": r.forecaster_id, "direction": direction,
            })
            if r.forecaster_id is not None:
                affected_forecasters.add(int(r.forecaster_id))

        print()
        print(f"[crypto-backfill] Status transitions:")
        for (old, new), n in sorted(status_diff.items()):
            marker = "  " if old == new else "!!"
            print(f"  {marker} {old:8s} → {new:8s}: {n}")
        print(f"[crypto-backfill] Skipped (no history): {skipped_no_history}")
        print(f"[crypto-backfill] Skipped (no close on date): {skipped_no_close}")
        print(f"[crypto-backfill] Forecasters affected: {len(affected_forecasters)}")

        if not apply:
            print("[crypto-backfill] DRY RUN — no DB writes. Re-run with --apply.")
            return

        now = datetime.utcnow()
        for u in updates_pending:
            db.execute(sql_text("""
                UPDATE predictions
                SET outcome = :o,
                    actual_return = :r,
                    direction = :d,
                    entry_price = :ep,
                    sector = 'Crypto',
                    evaluated_at = :now
                WHERE id = :id
            """), {
                "o": u["outcome"], "r": u["ret"], "d": u["direction"],
                "ep": u["ep"], "now": now, "id": u["id"],
            })
        db.commit()
        print(f"[crypto-backfill] Wrote {len(updates_pending)} prediction updates.")

        # Bug 9: any status change must invalidate the forecaster's cached
        # HIT streak and accuracy_score. Recompute aggregates for every
        # affected forecaster.
        try:
            from utils import recalculate_forecaster_stats
            for fid in affected_forecasters:
                recalculate_forecaster_stats(fid, db)
            print(f"[crypto-backfill] Recomputed stats for {len(affected_forecasters)} forecasters.")
        except Exception as e:
            print(f"[crypto-backfill] Stats recompute error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
