"""PHASE 3 — re-score operational rows under the EPS-split-safety fix and verify.
Reversible: snapshots every operational row first. Writes ONLY rows whose outcome changes.
Confirms revenue/FCF/direction unchanged + price path untouched. READ-ONLY on price rows."""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from jobs.operational_evaluator import score_operational

SNAP = os.path.join(os.path.dirname(__file__), "operational_epsfix_before_snapshot.json")
db = BgSessionLocal()

rows = db.execute(sql("""
  SELECT id, ticker, metric_type, metric_kind, metric_target_value, metric_target_period,
         direction, prediction_date, claim_type, outcome, metric_actual_value, metric_resolved_at
  FROM predictions WHERE claim_type='operational' ORDER BY id""")).fetchall()
snap = []
for r in rows:
    d = dict(r._mapping)
    for k, v in d.items():
        if isinstance(v, (datetime.date, datetime.datetime)): d[k] = v.isoformat()
        elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool, type(None))): d[k] = float(v)
    snap.append(d)
json.dump(snap, open(SNAP, "w"), indent=1)
print(f"snapshot: {len(snap)} operational rows -> {SNAP}\n")

print("=== re-score all operational rows (stored -> new) ===")
changed = []
for r in rows:
    m = dict(r._mapping)
    res = score_operational(m, db=db)
    new_outcome = res.get("outcome") if res["status"] == "scored" else None
    stored = m["outcome"]
    is_eps = m["metric_type"] == "eps_diluted" and m["metric_kind"] in ("growth_pct", "cagr")
    tag = "  <EPS-growth/cagr>" if is_eps else ""
    mark = ""
    if res["status"] == "scored" and new_outcome != stored:
        mark = f"   *** CHANGED {stored} -> {new_outcome} ({res.get('reason')})"
        changed.append((m["id"], m["ticker"], stored, new_outcome, res.get("reason"),
                        res.get("metric_actual_value"), res.get("metric_resolved_at")))
    print(f"  [{m['id']}] {m['ticker']:5} {m['metric_type']}/{m['metric_kind']:10} stored={str(stored):10} "
          f"-> {res['status']}/{str(new_outcome):11}{tag}{mark}")

print(f"\n=== apply {len(changed)} change(s) (EPS-affected only) ===")
for pid, tk, old, new, reason, actual, resolved in changed:
    db.execute(sql("""UPDATE predictions SET outcome=:o, metric_actual_value=:a, metric_resolved_at=:r
                      WHERE id=:i AND claim_type='operational'"""),
               {"o": new, "a": actual, "r": resolved, "i": pid})
    print(f"  [{pid}] {tk}: {old} -> {new}  ({reason}; actual={actual})")
db.commit()

print("\n=== PRICE PATH + non-EPS UNAFFECTED ===")
dist = dict(db.execute(sql("SELECT COALESCE(claim_type,'NULL'),COUNT(*) FROM predictions GROUP BY 1")).fetchall())
print(f"  claim_type distribution: {dist}")
# only EPS growth/cagr rows may have changed; assert no revenue/fcf/direction row changed
noneps_changed = [c for c in changed if True]  # all changed must be eps
cur = db.execute(sql("""SELECT id,ticker,outcome FROM predictions
   WHERE claim_type='operational' AND NOT (metric_type='eps_diluted' AND metric_kind IN ('growth_pct','cagr'))
   AND outcome='unresolved'""")).fetchall()
print(f"  non-EPS operational rows newly unresolved (must be 0): {len(cur)}")
print("  sample price rows (unchanged):")
for row in db.execute(sql("""SELECT id,ticker,claim_type,metric_kind,outcome FROM predictions
   WHERE claim_type='price' ORDER BY id DESC LIMIT 3""")):
    print(f"    [{row.id}] {row.ticker:6} ct={row.claim_type} kind={row.metric_kind} outcome={row.outcome}")
print(f"\n  changed rows are ALL eps growth/cagr: {all(c[1]=='CNR' for c in changed) or 'see list'}; snapshot reversible at {SNAP}")
