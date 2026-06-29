"""PHASE 6 — end-to-end verification. For every backfilled operational row, re-derive the
full chain quote -> extracted {metric,kind,target,period} -> fetched actual -> outcome and
eye-check it. Then confirm the PRICE path is unaffected (counts + sample + routing).
READ-ONLY (re-reads the DB state the backfill wrote)."""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from services.financial_actuals import get_financial_actual
from jobs.operational_evaluator import score_operational, resolve_target_period

HERE = os.path.dirname(__file__)
back = json.load(open(os.path.join(HERE, "operational_backfill_results.json")))
snap = json.load(open(os.path.join(HERE, "operational_backfill_before_snapshot.json")))
touched_ids = [r["id"] for r in snap]
db = BgSessionLocal()

print("="*72)
print("PHASE 6 — END-TO-END VERIFICATION")
print("="*72)
print(f"\nbackfill: candidates={back['candidates']} operational_tagged={back['operational_tagged']} "
      f"scored={back['scored']} {back['scored_breakdown']} pending={back['pending']} hit_rate={back['hit_rate']}")

print("\n--- per operational row: quote -> extraction -> actual -> outcome ---")
for r in back["rows"]:
    if r["claim_type"] != "operational":
        continue
    p = db.execute(sql("""SELECT ticker, direction, claim_type, metric_type, metric_kind,
        metric_target_value, metric_target_period, metric_actual_value, metric_resolved_at,
        outcome, evaluation_deferred, prediction_date,
        COALESCE(NULLIF(source_verbatim_quote,''),exact_quote,context,'') q
        FROM predictions WHERE id=:i"""), {"i": r["id"]}).fetchone()
    m = dict(p._mapping)
    tp = resolve_target_period(m["metric_target_period"], m["prediction_date"])
    act = get_financial_actual(m["ticker"], m["metric_type"], tp, db=db) if tp else {"status": "no_period"}
    rescore = score_operational(m, db=db)
    flag = "DEFER✓" if m["evaluation_deferred"] else "DEFER✗"
    print(f"\n [{r['id']}] {m['ticker']} {m['metric_type']}/{m['metric_kind']} tgt={m['metric_target_value']} "
          f"period={m['metric_target_period']}->{tp}  {flag}")
    print(f"     quote: {' '.join((m['q'] or '').split())[:120]}")
    print(f"     actual({tp}): {act.get('status')} value={act.get('value')} report={act.get('report_date')}")
    print(f"     stored outcome={m['outcome']} actual_value={m['metric_actual_value']} resolved={m['metric_resolved_at']}")
    print(f"     re-score now: {rescore['status']} outcome={rescore.get('outcome')} {rescore.get('reason') or ''}")

print("\n--- PRICE PATH UNAFFECTED ---")
dist = dict(db.execute(sql("SELECT COALESCE(claim_type,'NULL'), COUNT(*) FROM predictions GROUP BY 1")).fetchall())
print(f" claim_type distribution: {dist}")
defer = db.execute(sql("""SELECT COUNT(*) FILTER (WHERE evaluation_deferred), COUNT(*)
    FROM predictions WHERE claim_type='operational'""")).fetchone()
print(f" operational rows: {defer[1]} total, {defer[0]} have evaluation_deferred=TRUE (rerouted off price)")
# only the snapshotted ids changed claim_type
chg = db.execute(sql("""SELECT COUNT(*) FROM predictions
    WHERE claim_type='operational' AND id <> ALL(:ids)"""), {"ids": touched_ids}).fetchone()[0]
print(f" operational rows NOT in snapshot (unexpected collateral): {chg}  (must be 0)")
# sample untouched price rows
print(" sample price rows (must be claim_type=price, metric_* NULL):")
for row in db.execute(sql("""SELECT id, ticker, claim_type, metric_kind, metric_target_value, outcome
    FROM predictions WHERE claim_type='price' AND id <> ALL(:ids) ORDER BY id DESC LIMIT 4"""),
    {"ids": touched_ids}):
    print(f"   [{row.id}] {row.ticker:5} ct={row.claim_type} kind={row.metric_kind} tgt={row.metric_target_value} outcome={row.outcome}")
print(f"\n VERDICT: price rows untouched except the {len(touched_ids)} intended reroutes; "
      f"operational rows all deferred={'YES' if defer[0]==defer[1] else 'NO'}; collateral={'NONE' if chg==0 else chg}")
