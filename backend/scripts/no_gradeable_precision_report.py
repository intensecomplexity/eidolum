"""Gold-anchored visible-precision report (before/after the no-gradeable-claim pass).

Reproduces the GOLD_FINDINGS (2026-06-21) method: post-stratify the 200 human gold
labels by Haiku verdict class to the CURRENT visible-population class frequencies.
Reads live hide-flags from the DB, so running it before vs after the apply step shows
the precision lift (rows flagged is_no_gradeable_claim drop out of the visible set).

  raw_visible      = gold-valid / total, over gold rows currently passing the bundle
  stratified_visible = Σ_class  w_class(visible population)  ×  gold_valid_rate_class(visible gold)

Run:  DATABASE_PUBLIC_URL=... python3 backend/scripts/no_gradeable_precision_report.py
"""
import json
import os
from collections import Counter, defaultdict

import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
LABELS = os.path.join(HERE, "fullcov_results", "labels.jsonl")
GOLD = os.path.join(HERE, "groundtruth_2026_06_16", "gold_verdicts_200.jsonl")

BUNDLE = """(conviction_level NOT IN ('hedged','hypothetical') OR conviction_level IS NULL)
  AND COALESCE(is_reported_speech,FALSE)=FALSE
  AND COALESCE(is_ambiguous_symbol,FALSE)=FALSE
  AND COALESCE(is_weak_basket_call,FALSE)=FALSE
  AND COALESCE(is_holding_disclosure,FALSE)=FALSE
  AND COALESCE(is_no_claim,FALSE)=FALSE
  AND COALESCE(is_no_gradeable_claim,FALSE)=FALSE"""


def main():
    labels = {int(json.loads(l)["id"]): json.loads(l).get("verdict") for l in open(LABELS)}
    gold = {int(json.loads(l)["id"]): json.loads(l) for l in open(GOLD)}
    conn = psycopg2.connect(os.environ["DATABASE_PUBLIC_URL"])
    cur = conn.cursor()

    all_ids = list(labels)
    cur.execute(f"SELECT id FROM predictions WHERE id = ANY(%s) AND {BUNDLE}", (all_ids,))
    visible = {r[0] for r in cur.fetchall()}

    # population class weights over visible rows (class = Haiku full-cov verdict)
    pop = Counter(labels[i] for i in visible if labels.get(i))
    total = sum(pop.values())

    # gold per-class valid rate over currently-visible gold rows
    g_by_class = defaultdict(lambda: [0, 0])  # class -> [valid, n]
    raw_valid = raw_total = 0
    for pid, g in gold.items():
        if pid not in visible:
            continue
        raw_total += 1
        raw_valid += 1 if g["gold_valid"] else 0
        c = g["haiku_verdict"]
        g_by_class[c][1] += 1
        g_by_class[c][0] += 1 if g["gold_valid"] else 0

    # stratified: weight by visible-population share, rate from visible gold, over
    # classes that have at least one visible gold row (renormalized — same shape as
    # the GOLD_FINDINGS census).
    strat_num = strat_den = 0.0
    contrib = []
    for c, w in pop.items():
        if c in g_by_class and g_by_class[c][1] > 0:
            rate = g_by_class[c][0] / g_by_class[c][1]
            strat_num += w * rate
            strat_den += w
            contrib.append((c, w, g_by_class[c][1], rate))

    print(f"visible population rows (labels ∩ bundle): {total}")
    print(f"raw visible gold precision     : {raw_valid}/{raw_total} = {100*raw_valid/max(raw_total,1):.1f}%")
    print(f"stratified-to-visible precision: {100*strat_num/max(strat_den,1):.2f}%   "
          f"(GOLD_FINDINGS baseline headline = 47.6%)")
    print("\nper-class contribution (class | visible weight | gold n | gold-valid rate):")
    for c, w, gn, rate in sorted(contrib, key=lambda x: -x[1]):
        print(f"  {c:18s}  w={w:5d} ({100*w/total:4.1f}%)  goldn={gn:3d}  rate={100*rate:5.1f}%")
    conn.close()


if __name__ == "__main__":
    main()
