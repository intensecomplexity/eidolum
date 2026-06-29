"""PART B: build a BLIND, stratified ~120-row direction-flip eval sample over still-visible
YT+X predictions, deliberately oversampling the edge classes that broke the flip pass:
  (a) inverse / leveraged-short ETFs    (SH, SQQQ, SDS, PSQ, SPXU, SOXS, ...)
  (b) bare price-level quotes           (a level/PT/"test 100" with NO explicit direction word)
  (c) analyst / CEO / firm relay quotes
  (d) dir_mismatch suspects             (verify_layer.suspect_kinds -> 'dir_mismatch')
  (e) random NORMAL committed calls     (to measure FALSE-flip rate on correct-direction rows)

Outputs (local):
  direction_eval_120_2026-06-29.csv         <- BLIND sheet (no stratum hint, shuffled). Upload this.
  direction_eval_120_manifest.jsonl         <- private: + stratum label, for our composition report.
Becomes gt_dir_gold once Nimrod labels true_direction. READ-ONLY on the DB.
"""
import os, re, sys, csv, json, random, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from jobs.representativeness_guard import _BULL, _BEAR, _cue
from scripts.reject_rules_judge_2026_06_29 import REPORTED
from scripts.verify_layer_2026_06_29 import suspect_kinds, VIS_YTX

random.seed(20260629)
HERE = os.path.dirname(__file__)

INVERSE = {  # inverse / leveraged-short ETFs only (NOT bull leveraged)
    "SH","SDS","SPXU","SPXS","SDOW","DXD","DOG","PSQ","QID","SQQQ","RWM","TWM","TZA","MZZ",
    "SOXS","SARK","TSLQ","NVD","NVDS","AAPD","MSFD","SPDN","SJB","YANG","EUM","EFZ","DRV",
    "FAZ","SRTY","LABD","BERZ","KOLD","SCO","DUST","JDST","ERY","SDP","REW","SMN","TYO",
    "PST","TBT","TBF","TTT","DRIP","HDGE","MYY","EPV","FXP","WEBS",
}
_LEVEL = re.compile(
    r"(\$\s?\d|\b\d{2,}\s?(?:k\b|dollars?)|\bpt\b|price\s+target|fair\s+value|\bretest|"
    r"\btest(?:s|ing|ed)?\s+(?:the\s+)?\$?\d|\btarget\b\s+(?:of\s+)?\$?\d|"
    r"\b\d{2,}\s+(?:level|area|zone|support|resistance))", re.I)
_RELAY = re.compile(
    r"\b(analysts?|upgrade[ds]?|downgrade[ds]?|reiterat\w*|initiat\w*\s+coverage|price\s+target|"
    r"CEO|CFO|chairman|founder|guidance|BofA|Goldman|Morgan\s+Stanley|JPMorgan|Citi(?:group)?|"
    r"Wedbush|Barclays|UBS|Wells\s+Fargo|Jefferies|Raymond\s+James|Piper|Evercore|"
    r"(?:she|he|they)\s+(?:says?|said|projects?|expects?|forecast))\b", re.I)

TARGET = {"a_inverse_etf": 18, "c_relay": 20, "b_bare_level": 24, "d_dir_mismatch": 25}  # e fills to 120
TOTAL = 120


def stratum(r):
    """Assign ONE stratum by priority: inverse > relay > bare-level > dir_mismatch > normal."""
    q = r["quote"] or ""
    if (r["ticker"] or "").upper() in INVERSE:
        return "a_inverse_etf"
    if REPORTED.search(q) or _RELAY.search(q):
        return "c_relay"
    if _LEVEL.search(q) and not _cue(q, _BULL) and not _cue(q, _BEAR):
        return "b_bare_level"
    if "dir_mismatch" in suspect_kinds(r):
        return "d_dir_mismatch"
    return "e_normal"


def main():
    db = BgSessionLocal()
    rows = [dict(r) for r in db.execute(sql(f"""
        SELECT id, source_type, ticker, direction,
               COALESCE(NULLIF(source_verbatim_quote,''),exact_quote,context,'') AS quote
        FROM predictions WHERE {VIS_YTX} AND direction IS NOT NULL
          AND COALESCE(NULLIF(source_verbatim_quote,''),exact_quote,context,'') <> ''""")).mappings().all()]
    print(f"still-visible YT+X rows w/ direction+quote: {len(rows)}")

    buckets = collections.defaultdict(list)
    for r in rows:
        buckets[stratum(r)].append(r)
    print("available per stratum:", {k: len(v) for k, v in sorted(buckets.items())})

    picked, seen = [], set()
    # edge strata first (fixed targets), then normal fills to TOTAL
    for strat in ("a_inverse_etf", "c_relay", "b_bare_level", "d_dir_mismatch"):
        pool = [r for r in buckets[strat] if r["id"] not in seen]
        random.shuffle(pool)
        take = pool[:TARGET[strat]]
        for r in take:
            r["_stratum"] = strat; picked.append(r); seen.add(r["id"])
    pool = [r for r in buckets["e_normal"] if r["id"] not in seen]
    random.shuffle(pool)
    for r in pool[:max(0, TOTAL - len(picked))]:
        r["_stratum"] = "e_normal"; picked.append(r); seen.add(r["id"])

    random.shuffle(picked)  # final blind order (no suspect-vs-not hint)

    # BLIND csv
    csv_path = os.path.join(HERE, "direction_eval_120_2026-06-29.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "source", "ticker", "stored_direction", "full_quote", "true_direction", "notes"])
        for r in picked:
            w.writerow([r["id"], r["source_type"], r["ticker"], r["direction"],
                        " ".join((r["quote"] or "").split()), "", ""])
    # private manifest (NOT uploaded)
    man_path = os.path.join(HERE, "direction_eval_120_manifest.jsonl")
    with open(man_path, "w") as f:
        for r in picked:
            f.write(json.dumps({"id": r["id"], "stratum": r["_stratum"], "ticker": r["ticker"],
                                "source": r["source_type"], "stored_direction": r["direction"]}) + "\n")

    comp = collections.Counter(r["_stratum"] for r in picked)
    src = collections.Counter(r["source_type"] for r in picked)
    print(f"\nSAMPLE n={len(picked)}")
    print("composition by stratum:", dict(sorted(comp.items())))
    print("by source:", dict(src))
    print("inverse-ETF tickers included:", sorted({r["ticker"] for r in picked if r["_stratum"] == "a_inverse_etf"}))
    print(f"\nBLIND csv -> {csv_path}")
    print(f"manifest  -> {man_path}")
    db.close()


if __name__ == "__main__":
    main()
