"""
fix_entry_price_from_price_bars.py — Phase 5 of the price_bars ship.

Re-derives entry_price, actual_return, outcome, sp500_return, and alpha for
three populations of broken predictions by joining onto the locally-populated
price_bars table. Zero new API calls.

Populations:
  A — verified_by IN ('massive_benzinga','benzinga_web')
      AND outcome != 'pending'
      AND entry_price IS NOT NULL
      (the historic pt_prior pollution + the cascade-fix-touched 29K)

  B — verified_by = 'fmp_grades'
      AND entry_price IS NULL
      AND outcome = 'delisted'
      (the live evaluator gave up on these for lack of price data; price_bars
       now provides it)

  C — verified_by IN ('massive_benzinga','benzinga_web')
      AND entry_price IS NULL
      AND outcome = 'pending'
      (Phase A nulled these so the live evaluator would refill; evaluator
       stalled because FMP was down)

Scoring mirrors backend/jobs/historical_evaluator.py exactly:
  - _TOLERANCE      = {1:2, 7:3, 14:4, 30:5, 90:5, 180:7, 365:10}
  - _MIN_MOVEMENT   = {1:0.5, 7:1, 14:1.5, 30:2, 90:2, 180:3, 365:4}
  - Neutral: |ret|<=5 HIT, 5<x<=10 NEAR, else MISS
  - With target: hit if eval crosses target, or target_dist<=tolerance with
    move-in-direction; near if raw_move>=min_movement; else miss
  - Without target: directional hit/miss only (no near)
  - actual_return clamped via services.eval_caps.clamp_return

Only sector_call / pair_call / regime_call / position_disclosure are excluded
(different scoring rules); ticker_call and NULL prediction_category are in.

Idempotent: only UPDATE if entry changed by >2% OR outcome flipped OR
(was NULL, now has value).

atexit summary on every exit path (clean, signal, exception).
"""
import argparse
import atexit
import os
import signal
import statistics
import sys
import time
from datetime import datetime, timedelta, date as _date

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text

from database import BgSessionLocal

# Canonical scoring tables — copied from historical_evaluator.py to avoid
# importing the whole 1700-line module (its top-level imports pull in
# services that touch live APIs).
_TOLERANCE     = {1: 2,   7: 3, 14: 4,   30: 5, 90: 5, 180: 7, 365: 10}
_MIN_MOVEMENT  = {1: 0.5, 7: 1, 14: 1.5, 30: 2, 90: 2, 180: 3, 365: 4}
DEVIATION_THRESHOLD = 0.02  # 2% same as Bug 8

TAG = "[fix-from-bars]"

_stats = {
    "started_at": datetime.utcnow().isoformat(),
    "exit_reason": "unknown",
    "summary_path": "",
    "argv": " ".join(sys.argv),
    "by_population": {
        "A": {"scanned": 0, "no_entry_bar": 0, "no_exit_bar": 0,
              "updated": 0, "skipped_unchanged": 0,
              "shifts": [], "flips": {}, "category_skipped": 0},
        "B": {"scanned": 0, "no_entry_bar": 0, "no_exit_bar": 0,
              "updated": 0, "skipped_unchanged": 0,
              "shifts": [], "flips": {}, "category_skipped": 0},
        "C": {"scanned": 0, "no_entry_bar": 0, "no_exit_bar": 0,
              "updated": 0, "skipped_unchanged": 0,
              "shifts": [], "flips": {}, "category_skipped": 0},
    },
}

_spy_closes: dict[str, float] = {}  # date_str → close, prepopulated once


# ─── canonical helpers ────────────────────────────────────────────────────
def _get_tolerance(window_days, table: dict) -> float:
    """Mirror historical_evaluator._get_tolerance (Bug 6 fix)."""
    try:
        n = int(round(float(window_days)))
    except (TypeError, ValueError):
        n = 30
    if n <= 0:
        n = 30
    for k in sorted(table.keys()):
        if n <= k:
            return table[k]
    return table[max(table.keys())]


def _clamp_return(ret, window_days):
    """Mirror services.eval_caps.clamp_return. Per-window cap so leaderboard
    and portfolio sim render off the same numbers (Bug 7)."""
    try:
        from services.eval_caps import clamp_return as _live
        return _live(ret, window_days)
    except Exception:
        # Conservative fallback: no clamp
        return ret


def score_ticker_call(direction: str, ref: float, eval_price: float,
                      target, window_days) -> tuple:
    """Returns (raw_move, signed_return, outcome). Mirrors lines 437-495 of
    historical_evaluator.evaluate_batch exactly."""
    if not ref or ref <= 0 or not eval_price or eval_price <= 0:
        return None, None, None
    raw_move = round(((eval_price - ref) / ref) * 100, 2)
    direction = (direction or "bullish").lower()
    if direction == "bearish":
        ret = -raw_move
    else:
        ret = raw_move
    ret = _clamp_return(ret, window_days)

    window = window_days or 90
    tolerance = _get_tolerance(window, _TOLERANCE)
    min_movement = _get_tolerance(window, _MIN_MOVEMENT)

    if direction == "neutral":
        abs_ret = abs(raw_move)
        if abs_ret <= 5.0:
            outcome = "hit"
        elif abs_ret <= 10.0:
            outcome = "near"
        else:
            outcome = "miss"
    elif target and float(target) > 0:
        t = float(target)
        target_dist_pct = abs(eval_price - t) / t * 100
        if direction == "bullish":
            if eval_price >= t or (target_dist_pct <= tolerance and raw_move >= 0):
                outcome = "hit"
            elif raw_move >= min_movement:
                outcome = "near"
            else:
                outcome = "miss"
        else:  # bearish
            if eval_price <= t or (target_dist_pct <= tolerance and raw_move <= 0):
                outcome = "hit"
            elif raw_move <= -min_movement:
                outcome = "near"
            else:
                outcome = "miss"
    else:
        # Pure directional — no NEAR
        if direction == "bullish":
            outcome = "hit" if eval_price > ref else "miss"
        else:
            outcome = "hit" if eval_price < ref else "miss"

    return raw_move, ret, outcome


def _closest_spy(date_obj) -> float | None:
    if not _spy_closes or not date_obj:
        return None
    target = date_obj.date() if hasattr(date_obj, "date") else date_obj
    ts = target.strftime("%Y-%m-%d")
    if ts in _spy_closes:
        return _spy_closes[ts]
    for offset in range(1, 11):
        for sign in (-1, 1):
            d = (target + timedelta(days=sign * offset)).strftime("%Y-%m-%d")
            if d in _spy_closes:
                return _spy_closes[d]
    return None


# ─── exit hook ────────────────────────────────────────────────────────────
def _write_summary():
    sp = _stats.get("summary_path")
    if not sp:
        return
    try:
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        now = datetime.utcnow()
        started = datetime.fromisoformat(_stats["started_at"])
        runtime = (now - started).total_seconds()
        lines = []
        lines.append("# fix_entry_price_from_price_bars summary\n")
        lines.append(f"- Started: {_stats['started_at']}Z")
        lines.append(f"- Finished: {now.isoformat()}Z")
        lines.append(f"- Runtime: {runtime:.0f}s ({runtime/3600:.2f}h)")
        lines.append(f"- Argv: `{_stats['argv']}`")
        lines.append(f"- Exit reason: **{_stats['exit_reason']}**\n")
        for pop, s in _stats["by_population"].items():
            lines.append(f"## Population {pop}")
            lines.append(f"- scanned: {s['scanned']:,}")
            lines.append(f"- updated: {s['updated']:,}")
            lines.append(f"- skipped (unchanged): {s['skipped_unchanged']:,}")
            lines.append(f"- skipped (no entry bar): {s['no_entry_bar']:,}")
            lines.append(f"- skipped (no exit bar): {s['no_exit_bar']:,}")
            lines.append(f"- skipped (other category): {s['category_skipped']:,}")
            if s["shifts"]:
                lines.append(f"- return shift n: {len(s['shifts']):,}")
                lines.append(f"  - mean:   {statistics.mean(s['shifts']):+.2f}pp")
                lines.append(f"  - median: {statistics.median(s['shifts']):+.2f}pp")
            if s["flips"]:
                lines.append("- outcome flips:")
                for k, v in sorted(s["flips"].items(), key=lambda x: -x[1]):
                    lines.append(f"  - {k}: {v:,}")
            lines.append("")
        with open(sp, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"{TAG} summary written → {sp}", flush=True)
    except Exception as e:
        print(f"{TAG} summary write failed: {e}", flush=True)


def _signal_handler(signum, frame):
    _stats["exit_reason"] = f"signal {signum}"
    print(f"{TAG} received signal {signum}, exiting", flush=True)
    sys.exit(128 + signum)


# ─── price_bars lookup ────────────────────────────────────────────────────
def _preload_spy(db) -> None:
    """Cache SPY closes by date once at startup so per-row spy_return is in-memory."""
    rows = db.execute(sql_text("""
        SELECT bar_date, close FROM price_bars WHERE ticker='SPY'
    """)).fetchall()
    for r in rows:
        _spy_closes[r.bar_date.strftime("%Y-%m-%d")] = float(r.close)
    print(f"{TAG} cached {len(_spy_closes):,} SPY closes", flush=True)


# ─── population processing ────────────────────────────────────────────────
POPULATION_FILTERS = {
    "A": """
        verified_by IN ('massive_benzinga','benzinga_web')
        AND outcome != 'pending'
        AND entry_price IS NOT NULL
    """,
    "B": """
        verified_by = 'fmp_grades'
        AND entry_price IS NULL
        AND outcome = 'delisted'
    """,
    "C": """
        verified_by IN ('massive_benzinga','benzinga_web')
        AND entry_price IS NULL
        AND outcome = 'pending'
    """,
}


def process_population(db, pop: str, args, sample_collector: list):
    """Stream rows for one population in batches, do the join + recompute,
    UPDATE in place. Idempotent."""
    filt = POPULATION_FILTERS[pop]
    stats = _stats["by_population"][pop]

    # paging on id — no offset, just last_id cursor
    last_id = 0
    while True:
        batch_sql = f"""
        SELECT
            p.id, p.ticker, p.prediction_date, p.evaluation_date, p.window_days,
            p.direction, p.target_price, p.entry_price, p.actual_return, p.outcome,
            p.prediction_category, p.forecaster_id,
            (SELECT pb.close FROM price_bars pb
              WHERE pb.ticker = p.ticker
                AND pb.bar_date BETWEEN p.prediction_date::date - INTERVAL '10 days'
                                    AND p.prediction_date::date + INTERVAL '10 days'
              ORDER BY ABS(pb.bar_date - p.prediction_date::date) LIMIT 1) AS new_entry,
            (SELECT pb.close FROM price_bars pb
              WHERE pb.ticker = p.ticker
                AND pb.bar_date BETWEEN p.evaluation_date::date - INTERVAL '5 days'
                                    AND p.evaluation_date::date + INTERVAL '5 days'
              ORDER BY ABS(pb.bar_date - p.evaluation_date::date) LIMIT 1) AS new_exit
        FROM predictions p
        WHERE ({filt})
          AND p.id > :last_id
          AND p.prediction_date IS NOT NULL
          AND p.evaluation_date IS NOT NULL
        ORDER BY p.id
        LIMIT :lim
        """
        rows = db.execute(sql_text(batch_sql), {
            "last_id": last_id, "lim": args.batch_size,
        }).fetchall()
        if not rows:
            break
        last_id = rows[-1].id

        updates = []  # batched UPDATE candidates

        for r in rows:
            stats["scanned"] += 1

            # Filter on prediction_category (skip sector/pair/regime/position)
            cat = (r.prediction_category or "ticker_call").lower()
            if cat not in ("ticker_call", "none", "null"):
                stats["category_skipped"] += 1
                continue

            new_entry = float(r.new_entry) if r.new_entry is not None else None
            new_exit  = float(r.new_exit)  if r.new_exit  is not None else None
            if new_entry is None:
                stats["no_entry_bar"] += 1
                continue
            if new_exit is None:
                stats["no_exit_bar"] += 1
                continue

            raw_move, new_ret, new_outcome = score_ticker_call(
                r.direction, new_entry, new_exit, r.target_price, r.window_days,
            )
            if new_ret is None:
                stats["no_exit_bar"] += 1
                continue

            old_entry = float(r.entry_price) if r.entry_price is not None else None
            old_return = float(r.actual_return) if r.actual_return is not None else None
            old_outcome = (r.outcome or "").lower()

            # Idempotency: skip if entry essentially unchanged AND outcome unchanged
            entry_changed_pct = (
                abs(new_entry - old_entry) / new_entry if old_entry and new_entry else None
            )
            entry_materially_changed = (
                old_entry is None
                or (entry_changed_pct is not None and entry_changed_pct > DEVIATION_THRESHOLD)
            )
            outcome_changed = new_outcome != old_outcome
            return_was_null = old_return is None

            if not entry_materially_changed and not outcome_changed and not return_was_null:
                stats["skipped_unchanged"] += 1
                continue

            # SPY return + alpha (best-effort, may be None)
            spy_start = _closest_spy(r.prediction_date)
            spy_end = _closest_spy(r.evaluation_date)
            spy_return = None
            if spy_start and spy_end and spy_start > 0:
                spy_return = round((spy_end - spy_start) / spy_start * 100, 2)
            alpha = round(new_ret - spy_return, 2) if (spy_return is not None) else None

            updates.append({
                "id": int(r.id),
                "ep": new_entry,
                "ret": float(new_ret),
                "outcome": new_outcome,
                "spy_ret": spy_return,
                "alpha": alpha,
            })

            # Track stats
            stats["updated"] += 1
            if old_return is not None:
                stats["shifts"].append(new_ret - old_return)
            flip_key = f"{old_outcome or 'NULL'}→{new_outcome}"
            stats["flips"][flip_key] = stats["flips"].get(flip_key, 0) + 1

            # Sample collection for dry-run
            if len(sample_collector) < 20:
                sample_collector.append({
                    "pop": pop,
                    "id": int(r.id),
                    "ticker": r.ticker,
                    "pred_date": r.prediction_date.strftime("%Y-%m-%d") if r.prediction_date else None,
                    "old_entry": old_entry,
                    "new_entry": new_entry,
                    "old_return": old_return,
                    "new_return": float(new_ret),
                    "old_outcome": old_outcome,
                    "new_outcome": new_outcome,
                })

        # Apply this batch — single VALUES-clause UPDATE for one round-trip
        if updates and not args.dry_run:
            values_clauses = []
            params = {}
            for i, u in enumerate(updates):
                # CAST() not :name::type — the latter is silently mangled by
                # SQLAlchemy's text() parameter parser.
                values_clauses.append(
                    f"(CAST(:id{i} AS int), CAST(:ep{i} AS numeric), "
                    f"CAST(:ret{i} AS numeric), :outcome{i}, "
                    f"CAST(:spy{i} AS numeric), CAST(:alpha{i} AS numeric))"
                )
                params[f"id{i}"]      = u["id"]
                params[f"ep{i}"]      = u["ep"]
                params[f"ret{i}"]     = u["ret"]
                params[f"outcome{i}"] = u["outcome"]
                params[f"spy{i}"]     = u["spy_ret"]
                params[f"alpha{i}"]   = u["alpha"]
            bulk_sql = (
                "UPDATE predictions p SET "
                "entry_price = v.ep, actual_return = v.ret, outcome = v.outcome, "
                "sp500_return = v.spy, alpha = v.alpha, "
                "last_backfill_attempt = NOW(), evaluated_at = NOW() "
                "FROM (VALUES " + ",".join(values_clauses) + ") "
                "AS v(id, ep, ret, outcome, spy, alpha) "
                "WHERE p.id = v.id"
            )
            committed = False
            for attempt in range(3):
                try:
                    result = db.execute(sql_text(bulk_sql), params)
                    db.commit()
                    # Sanity check: if rowcount doesn't match update count, something's off
                    if result.rowcount != len(updates):
                        print(f"{TAG} pop={pop} WARN rowcount={result.rowcount} != updates={len(updates)} last_id={last_id}", flush=True)
                    committed = True
                    break
                except Exception as e:
                    print(f"{TAG} pop={pop} commit retry {attempt+1}/3 last_id={last_id}: {e}", flush=True)
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
            if not committed:
                # Loud failure — script must NOT silently report phantom updates
                msg = f"{TAG} pop={pop} FATAL commit failed 3x at last_id={last_id} — aborting"
                print(msg, flush=True)
                _stats["exit_reason"] = msg
                raise SystemExit(4)

        # Progress log
        print(
            f"{TAG} pop={pop} last_id={last_id} scanned={stats['scanned']:,} "
            f"updated={stats['updated']:,} unchanged={stats['skipped_unchanged']:,} "
            f"no_entry={stats['no_entry_bar']:,} no_exit={stats['no_exit_bar']:,}",
            flush=True,
        )

    return db


# ─── main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Scan + report; do NOT write")
    ap.add_argument("--batch-size", type=int, default=5000,
                    help="Rows per SELECT/commit batch")
    ap.add_argument("--population", default="ALL",
                    help="A | B | C | ALL")
    ap.add_argument("--summary-path", default="")
    args = ap.parse_args()

    if not args.summary_path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
        args.summary_path = (
            f"/mnt/g/My Drive/eidolum.prompts/_alerts/"
            f"fix_entry_price_from_price_bars_{ts}_SUMMARY.md"
        )
    _stats["summary_path"] = args.summary_path

    atexit.register(_write_summary)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    pops = ["A", "B", "C"] if args.population.upper() == "ALL" else [args.population.upper()]
    for p in pops:
        if p not in POPULATION_FILTERS:
            print(f"{TAG} ERROR: unknown population '{p}'", flush=True)
            sys.exit(2)

    print(f"{TAG} mode={'DRY RUN' if args.dry_run else 'COMMIT'} "
          f"populations={','.join(pops)} batch_size={args.batch_size}")
    print(f"{TAG} summary: {args.summary_path}")

    db = BgSessionLocal()
    _preload_spy(db)

    sample_collector: list = []
    for p in pops:
        print(f"\n{TAG} ============ population {p} ============")
        db = process_population(db, p, args, sample_collector)

    print(f"\n{TAG} === final per-population summary ===")
    for p in pops:
        s = _stats["by_population"][p]
        print(f"  pop {p}: scanned={s['scanned']:,} updated={s['updated']:,} "
              f"unchanged={s['skipped_unchanged']:,} no_entry={s['no_entry_bar']:,} "
              f"no_exit={s['no_exit_bar']:,} cat_skip={s['category_skipped']:,}")
        if s["shifts"]:
            print(f"    return shift  mean={statistics.mean(s['shifts']):+.2f}pp  "
                  f"median={statistics.median(s['shifts']):+.2f}pp  n={len(s['shifts']):,}")
        if s["flips"]:
            print("    outcome flips:")
            for k, v in sorted(s["flips"].items(), key=lambda x: -x[1])[:10]:
                print(f"      {k}: {v:,}")

    if sample_collector:
        print(f"\n{TAG} === sample (first 20 updated) ===")
        for s in sample_collector[:20]:
            old_e = f"{s['old_entry']:.2f}" if s['old_entry'] is not None else "NULL"
            old_r = f"{s['old_return']:+.2f}" if s['old_return'] is not None else "NULL"
            print(f"  pop={s['pop']} id={s['id']:>7} {s['ticker']:>6} {s['pred_date']} "
                  f"entry {old_e:>10} → {s['new_entry']:>10.2f} "
                  f"ret {old_r:>9} → {s['new_return']:+.2f} "
                  f"{s['old_outcome']:>8} → {s['new_outcome']:<8}")

    if _stats["exit_reason"] == "unknown":
        _stats["exit_reason"] = "completed"
    try:
        db.close()
    except Exception:
        pass
    print(f"\n{TAG} done — mode={'DRY RUN' if args.dry_run else 'COMMIT'}")


if __name__ == "__main__":
    main()
