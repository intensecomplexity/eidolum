"""Target-error mop-up (2026-06-11 audit). id-pinned, idempotent, reversible.

PART A — correct 3 pre-split AVGO targets stored in the RAW frame while the
price series is split-adjusted, then RE-EVALUATE (reuse the evaluator's own
scoring helpers). The split ratio is READ from fmp_splits (not hardcoded).
  Originals (for reversibility): 614187 tgt 578, 611104 tgt 533, 611072 tgt 622.8
PART B — flag 2 unrecoverable number errors -> 'unresolved' (flag-not-delete):
  605675 GOLD (3000 = gold COMMODITY price on Barrick stock),
  605607 QQQ  (59.79 = "5979" index level mangled onto the ETF).

Idempotent: PART A only corrects while target/entry still ~ split ratio (raw);
after correction target/entry ~ 1 so a re-run is a no-op. PART B skips already-
unresolved rows. Run manually against prod, then refresh forecaster stats.
  DATABASE_PUBLIC_URL=... python3 backend/scripts/fix_target_errors_audit.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "jobs"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sqlalchemy import create_engine, text  # noqa: E402
import historical_evaluator as ev  # noqa: E402

DBURL = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
if not DBURL:
    sys.exit("need DATABASE_PUBLIC_URL")
db = create_engine(DBURL).connect()

AVGO_IDS = [614187, 611104, 611072]
FLAG_IDS = [605675, 605607]


def rescore_ticker_call(direction, entry, ret, target, window_days):
    """Reuse the evaluator's ticker_call scoring formula + tolerance buckets.
    exit derived from the (split-adjusted) stored actual_return. Bullish only
    here (all 3 AVGO are bullish)."""
    raw_move = ret  # bullish: ret == raw_move
    exit_price = entry * (1 + raw_move / 100.0)
    tol = ev._get_tolerance(window_days or 90, ev._TOLERANCE)
    min_move = ev._get_tolerance(window_days or 90, ev._MIN_MOVEMENT)
    tp = float(target)
    target_dist_pct = abs(exit_price - tp) / tp * 100
    if direction == "bullish":
        if exit_price >= tp or target_dist_pct <= tol:
            return "hit", exit_price
        return ("near", exit_price) if raw_move >= min_move else ("miss", exit_price)
    # (bearish path included for completeness; unused for the 3 AVGO)
    if exit_price <= tp or target_dist_pct <= tol:
        return "hit", exit_price
    return ("near", exit_price) if raw_move <= -min_move else ("miss", exit_price)


print("=== PART A: AVGO split-frame target correction + re-eval ===")
for pid in AVGO_IDS:
    r = db.execute(text("""SELECT ticker,direction,outcome,target_price,entry_price,actual_return,
        window_days,prediction_date FROM predictions WHERE id=:i"""), {"i": pid}).first()
    tk, d, oc, tgt, entry, ret, win, pdate = r
    tgt, entry, ret = float(tgt), float(entry), float(ret)
    # cumulative forward-split ratio after prediction_date, from fmp_splits
    splits = db.execute(text("SELECT numerator,denominator FROM fmp_splits "
                             "WHERE symbol=:t AND date > :d"), {"t": tk, "d": pdate}).fetchall()
    ratio = 1.0
    for num, den in splits:
        if num and den:
            ratio *= float(num) / float(den)
    if ratio <= 1.05:
        print(f"  SKIP {pid}: no forward split (ratio={ratio})"); continue
    # idempotency: only correct while the raw target is still present
    if not (0.6 * ratio <= tgt / entry <= 1.5 * ratio):
        print(f"  SKIP {pid}: target/entry={tgt/entry:.2f} not ~ratio {ratio} (already corrected?)"); continue
    corrected = tgt / ratio
    r_new = corrected / entry
    if not (0.3 <= r_new <= 3.0):
        print(f"  FLAG-FOR-REVIEW {pid}: corrected {corrected:.2f} still off vs entry {entry:.2f} (r={r_new:.2f}) — SKIPPED")
        continue
    new_oc, exit_price = rescore_ticker_call(d, entry, ret, corrected, win)
    summary = (f"Target split-corrected (audit 2026-06-11): {tgt} -> {round(corrected,2)} "
               f"(/{ratio:.0f} via fmp_splits); re-evaluated {oc}->{new_oc} "
               f"(entry {round(entry,2)}, exit {round(exit_price,2)})")
    db.execute(text("""UPDATE predictions SET target_price=:tp, outcome=:o,
        evaluation_summary=:s, evaluated_at=NOW() WHERE id=:i"""),
        {"tp": round(corrected, 4), "o": new_oc, "s": summary[:500], "i": pid})
    print(f"  {pid} {tk}: tgt {tgt} -> {round(corrected,2)} (/{ratio:.0f}) | r {round(tgt/entry,2)}->{round(r_new,2)} | outcome {oc}->{new_oc}")

print("\n=== PART B: flag 2 unrecoverable number errors -> unresolved ===")
res = db.execute(text("""UPDATE predictions SET outcome='unresolved',
    evaluation_summary='Number-error flag (audit 2026-06-11): target is not a stock price target (commodity price / mangled index level) -> unresolved',
    evaluated_at=NOW()
    WHERE id = ANY(:ids) AND outcome IN ('hit','near','miss','correct','incorrect')"""),
    {"ids": FLAG_IDS})
print(f"  flagged {res.rowcount} rows -> unresolved")

db.commit()
db.close()
print("\nDone. Now: server-side POST /api/admin/refresh-forecaster-stats")
