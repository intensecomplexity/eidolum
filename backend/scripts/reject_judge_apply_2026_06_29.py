"""APPLY the gold-eval'd deterministic reject-judge to the USER-VISIBLE youtube+x population
(the classifier output the gold represents). Flag-not-delete, reversible (snapshot first).
SCOPE: source_type IN ('youtube','x'), currently visible, NOT operational. Wall-St article/
insider/congress rows are EXCLUDED — the judge is quote-based and invalid there.

reason -> existing hide-flag:
  no_anchor / buy_wishlist / past_tense -> is_no_gradeable_claim
  reported_speech                       -> is_reported_speech
  holding                               -> is_holding_disclosure
  hedged                                -> conviction_level='hedged'
Live classifier code is NOT touched. Run: DATABASE_URL=$DATABASE_PUBLIC_URL python3 ... [--apply]
"""
import os, sys, json, collections, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from scripts.reject_rules_judge_2026_06_29 import reject_judge

SNAP = os.path.join(os.path.dirname(__file__), "reject_judge_apply_2026_06_29_snapshot.json")
MARKER = "reject_judge_2026_06_29"
# SAFE-to-apply = the no-anchor-gated reasons only (a row with NO number/level AND NO timeframe
# is non-gradeable by the locked rule's definition — validated 0 false-reject on gold + a 116-row
# spot-check). 'reported_speech' and 'hedged' can reject ANCHORED rows and a deep audit found
# residual false-rejects there (own-theses-mentioning-an-analyst; rhetorical hedge phrases), so
# they are DEFERRED to the cost-gated LLM verify — NOT applied deterministically.
REASON_FLAG = {"no_anchor": "is_no_gradeable_claim", "buy_wishlist": "is_no_gradeable_claim",
               "past_tense": "is_no_gradeable_claim", "holding": "is_holding_disclosure"}
DEFERRED = {"reported_speech", "hedged"}
VIS = ("source_type IN ('youtube','x') AND COALESCE(claim_type,'price')<>'operational' "
       "AND NOT (source_type='youtube' AND source_timestamp_seconds IS NULL) "
       "AND (conviction_level NOT IN ('hedged','hypothetical') OR conviction_level IS NULL) "
       "AND COALESCE(is_reported_speech,FALSE)=FALSE AND COALESCE(is_ambiguous_symbol,FALSE)=FALSE "
       "AND COALESCE(is_weak_basket_call,FALSE)=FALSE AND COALESCE(is_holding_disclosure,FALSE)=FALSE "
       "AND COALESCE(is_no_claim,FALSE)=FALSE AND COALESCE(is_no_gradeable_claim,FALSE)=FALSE")


def main(apply=False):
    db = BgSessionLocal()
    rows = db.execute(sql(f"""
      SELECT id, source_type, conviction_level AS conv, COALESCE(claim_type,'price') AS claim_type,
        COALESCE(NULLIF(source_verbatim_quote,''),exact_quote,context,'') AS quote
      FROM predictions WHERE {VIS}""")).mappings().all()
    print(f"visible youtube+x non-operational rows scanned: {len(rows)}")

    by_flag = collections.defaultdict(list)   # flag -> [ids]
    by_reason = collections.Counter()
    snapshot = []
    deferred = collections.Counter()
    for r in rows:
        rej, reason = reject_judge(dict(r))
        if not rej:
            continue
        by_reason[reason] += 1
        if reason in DEFERRED:                      # reported/hedged -> NOT applied (LLM-verify later)
            deferred[reason] += 1
            continue
        by_flag[REASON_FLAG[reason]].append(r["id"])
        snapshot.append({"id": r["id"], "reason": reason, "flag": REASON_FLAG[reason],
                         "src": r["source_type"]})
    total = sum(len(v) for v in by_flag.values())
    print(f"rejected total={sum(by_reason.values())}  by reason={dict(by_reason)}")
    print(f"APPLYING {total} rows  by flag={ {k:len(v) for k,v in by_flag.items()} }   DEFERRED(not applied)={dict(deferred)}")

    if not apply:
        print("DRY-RUN (no writes). pass --apply to write.")
        return

    json.dump({"marker": MARKER, "applied_at": None, "count": total, "rows": snapshot},
              open(SNAP, "w"), indent=1)
    print(f"snapshot saved (reversible): {SNAP}")

    for flag, ids in by_flag.items():
        if not ids:
            continue
        if flag == "__conviction__":
            db.execute(sql("UPDATE predictions SET conviction_level='hedged' "
                           "WHERE id = ANY(:ids) AND (conviction_level NOT IN ('hedged','hypothetical') OR conviction_level IS NULL)"),
                       {"ids": ids})
        else:
            db.execute(sql(f"UPDATE predictions SET {flag}=TRUE "
                           f"WHERE id = ANY(:ids) AND COALESCE({flag},FALSE)=FALSE"), {"ids": ids})
        print(f"  flagged {len(ids)} rows -> {flag}")
    db.commit()
    print("COMMITTED.")


if __name__ == "__main__":
    main(apply=("--apply" in sys.argv))
