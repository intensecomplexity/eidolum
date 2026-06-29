"""PHASE-2 eval gate. Runs the operational extractor over the fixtures and checks:
  (a) NO REGRESSION: every 'price' fixture tags claim_type='price'.
  (b) the four 'operational' gold cases extract the right (metric, metric_kind).
  (c) 'not_a_prediction' rows do not become operational.
ACCEPTANCE = (a) all pass AND (b) all four pass. Writes a JSON report. claude -p, billed
to Max. Concurrency capped at 2 (shared box; never exceed 5 total claude -p)."""
import json, sys, os
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.operational_extractor import extract_operational

FIX = json.load(open(os.path.join(os.path.dirname(__file__), "..", "jobs", "_fixtures", "operational_extraction.json")))
OUT = os.path.join(os.path.dirname(__file__), "operational_extraction_eval_results.json")


def run_one(kind, fx):
    r = extract_operational(fx["ticker"], fx["quote"])
    ct = (r.get("claim_type") or "").lower()
    rec = {"group": kind, "ticker": fx["ticker"], "id": fx.get("id"),
           "got_claim_type": ct, "got_metric": r.get("metric"), "got_kind": r.get("metric_kind"),
           "got_target": r.get("target_value"), "got_period": r.get("target_period"),
           "got_direction": r.get("direction"), "error": r.get("_error")}
    if kind == "operational":
        rec["expect_metric"], rec["expect_kind"] = fx["expect_metric"], fx["expect_kind"]
        rec["pass"] = (ct == "operational" and r.get("metric") == fx["expect_metric"]
                       and (r.get("metric_kind") or "").lower() == fx["expect_kind"])
    elif kind == "price":
        rec["pass"] = (ct == "price")
    else:
        rec["pass"] = (ct != "operational")
    return rec


jobs = [(k, fx) for k in ("operational", "price", "not_a_prediction") for fx in FIX[k]]
print(f"running {len(jobs)} extractions (claude -p, 2 workers)...", flush=True)
with ThreadPoolExecutor(max_workers=2) as ex:
    results = list(ex.map(lambda kf: run_one(*kf), jobs))

by = {"operational": [], "price": [], "not_a_prediction": []}
for r in results:
    by[r["group"]].append(r)

op_pass = sum(1 for r in by["operational"] if r["pass"])
price_pass = sum(1 for r in by["price"] if r["pass"])
nap_pass = sum(1 for r in by["not_a_prediction"] if r["pass"])
accept = (op_pass == len(by["operational"]) and price_pass == len(by["price"]))

report = {"acceptance": accept,
          "operational": f"{op_pass}/{len(by['operational'])}",
          "price_no_regression": f"{price_pass}/{len(by['price'])}",
          "not_a_prediction": f"{nap_pass}/{len(by['not_a_prediction'])}",
          "rows": results}
json.dump(report, open(OUT, "w"), indent=1)

print("\n=== PHASE-2 EXTRACTION EVAL ===")
for r in results:
    star = "ok " if r["pass"] else "XX "
    exp = f" expect=({r.get('expect_metric')},{r.get('expect_kind')})" if r["group"] == "operational" else ""
    print(f" {star}[{r['group']:16}] {r['ticker']:5} -> ct={r['got_claim_type']:16} "
          f"metric={r['got_metric']} kind={r['got_kind']} tgt={r['got_target']} per={r['got_period']}{exp}"
          + (f"  ERR={r['error']}" if r["error"] else ""))
print(f"\n operational(4 cases): {report['operational']}   price(no-regression): {report['price_no_regression']}"
      f"   not_a_prediction: {report['not_a_prediction']}")
print(f" ACCEPTANCE (price-all + 4-cases): {'PASS' if accept else 'FAIL'}")
print(f" report -> {OUT}")
