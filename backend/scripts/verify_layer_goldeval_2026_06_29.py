"""PHASE 3 eval-gate: run the verify layer on the 69 gt_gold SUSPECTS and measure CATCH
(gold-invalid rejected) + FALSE-REJECT (gold-valid rejected — MUST be ~0). claude -p Sonnet,
2 workers (shared-box safe). Writes results JSON. READ-ONLY on predictions."""
import os, sys, json, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from scripts.verify_layer_2026_06_29 import suspect_kinds, verify

OUT = os.path.join(os.path.dirname(__file__), "verify_layer_goldeval_results.json")
db = BgSessionLocal()
gold = db.execute(sql("""SELECT g.prediction_id pid, g.gold_valid valid, g.gold_verdict gv,
  p.ticker, p.direction, COALESCE(NULLIF(p.source_verbatim_quote,''),p.exact_quote,p.context,'') quote
  FROM gt_gold g JOIN predictions p ON p.id=g.prediction_id""")).mappings().all()
suspects = [dict(r) for r in gold if suspect_kinds(dict(r))]
print(f"verifying {len(suspects)} gold suspects (claude -p sonnet, 2 workers)...", flush=True)

def run(r):
    vd, reason, why = verify(r)
    return {"pid": r["pid"], "valid": r["valid"], "gv": r["gv"], "kinds": suspect_kinds(r),
            "verdict": vd, "reason": reason, "why": why,
            "quote": " ".join((r["quote"] or "").split())[:200]}

with ThreadPoolExecutor(max_workers=2) as ex:
    res = list(ex.map(run, suspects))
json.dump(res, open(OUT, "w"), indent=1)

inv = [r for r in res if not r["valid"]]; val = [r for r in res if r["valid"]]
catch = sum(1 for r in inv if r["verdict"] == "REJECT")
fr = [r for r in val if r["verdict"] == "REJECT"]
print(f"\n=== VERIFY-LAYER GOLD EVAL ({len(suspects)} suspects) ===")
print(f"CATCH (invalid suspects rejected): {catch}/{len(inv)} = {100*catch/len(inv):.1f}%")
print(f"FALSE-REJECT (valid suspects rejected): {len(fr)}/{len(val)} = {100*len(fr)/max(1,len(val)):.1f}%  <-- MUST be ~0")
rej_by = collections.Counter(r["reason"] for r in res if r["verdict"] == "REJECT")
print(f"reject reasons: {dict(rej_by)}")
print("\nFALSE-REJECTS (valid rejected):", "NONE" if not fr else "")
for r in fr:
    print(f"  [{r['pid']}] {r['gv']} kinds={r['kinds']} reason={r['reason']} why={r['why']}\n     {r['quote']}")
print(f"\nresults -> {OUT}")
