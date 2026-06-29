"""PHASE 3 eval-gate for direction-correction. Runs the corrector on gold rows WITH a direction
and measures: false-flip on gold-VALID (correct-direction) rows (MUST be ~0) + catch on the gold
wrong_direction row. claude -p Sonnet, 2 workers. Writes results JSON. READ-ONLY on predictions."""
import os, sys, json, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from scripts.verify_direction_2026_06_29 import judge, should_flip

OUT = os.path.join(os.path.dirname(__file__), "verify_direction_goldeval_results.json")
db = BgSessionLocal()
# valid gold rows (correct direction = false-flip test) + the wrong_direction row (catch test)
rows = db.execute(sql("""SELECT g.prediction_id pid, g.gold_verdict gv, g.gold_valid valid, p.ticker, p.direction,
  COALESCE(NULLIF(p.source_verbatim_quote,''),p.exact_quote,p.context,'') quote
  FROM gt_gold g JOIN predictions p ON p.id=g.prediction_id
  WHERE p.direction IS NOT NULL AND (g.gold_valid OR g.gold_verdict='wrong_direction')""")).mappings().all()
rows = [dict(r) for r in rows]
print(f"gold direction-eval rows: {len(rows)} (valid={sum(r['valid'] for r in rows)} correct-dir, wrong_direction={sum(r['gv']=='wrong_direction' for r in rows)})", flush=True)

def run(r):
    j = judge(r)
    return {**{k: r[k] for k in ("pid", "gv", "valid", "ticker", "direction")},
            "quote": " ".join((r["quote"] or "").split())[:220], "flip": should_flip(r, j),
            "true_dir": j.get("true_direction"), "cls": j.get("classification"),
            "conf": j.get("confidence"), "evidence": j.get("evidence", ""), "why": j.get("why", "")}

with ThreadPoolExecutor(max_workers=2) as ex:
    res = list(ex.map(run, rows))
json.dump(res, open(OUT, "w"), indent=1)

valid = [r for r in res if r["valid"]]; wd = [r for r in res if r["gv"] == "wrong_direction"]
false_flip = [r for r in valid if r["flip"]]
catch = [r for r in wd if r["flip"]]
print(f"\n=== DIRECTION-CORRECTOR GOLD EVAL ===")
print(f"FALSE-FLIP (correct-direction rows flipped): {len(false_flip)}/{len(valid)} = {100*len(false_flip)/len(valid):.1f}%  <-- MUST be ~0 (each adjudicated below)")
print(f"CATCH (wrong_direction flipped): {len(catch)}/{len(wd)}")
print(f"\n=== PROPOSED FLIPS on gold-VALID rows (ADJUDICATE: true contradiction or false-flip?) ===")
for r in false_flip:
    print(f"  [{r['pid']}] {r['gv']} stored={r['direction']} -> true={r['true_dir']} conf={r['conf']} ev={r['evidence']!r}\n     {r['quote']}")
if not false_flip:
    print("  NONE")
print(f"\n=== wrong_direction row(s) ===")
for r in wd:
    print(f"  [{r['pid']}] stored={r['direction']} -> true={r['true_dir']} cls={r['cls']} flip={r['flip']}: {r['quote'][:120]}")
print(f"\nresults -> {OUT}")
