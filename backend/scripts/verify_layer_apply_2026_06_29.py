"""PHASE 4 apply: run the verify layer over the population SUSPECTS and flag-not-delete the
CONFIRMED junk (verify REJECT). Reversible (snapshot JSONL appended per flag), checkpointed
(resumable), idempotent (only still-visible rows; skips done). claude -p Sonnet, 2 workers
(shared-box safe). Audit marker verify_layer_2026_06_29.

Run AFTER the gold eval-gate passes (FR~0). Optionally scope by suspect kind:
  KINDS=reported,hedged,dir_mismatch,vague_year python3 ... [--apply]
(default: all kinds). Live classifier code untouched; only flag columns written.
"""
import os, sys, json, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from scripts.verify_layer_2026_06_29 import suspect_kinds, verify, VIS_YTX

SNAP = os.path.join(os.path.dirname(__file__), "verify_layer_apply_snapshot.jsonl")
CKPT = os.path.join(os.path.dirname(__file__), "_verify_layer_ckpt.json")
MARKER = "verify_layer_2026_06_29"
# SAFE reasons only (gold eval-gate: FR=0). The high-catch wrong_direction + not_gradeable
# FAILED the gate (FR>0 — the gold treats conditional trade-plans & direction-label mismatches
# as VALID), so they are NOT applied — deferred. Scope the run to KINDS=reported,hedged.
REASON_FLAG = {"analyst_relay": "is_reported_speech", "real_hedge": "__conviction__"}
BATCH = 40


def load_ckpt():
    try: return set(json.load(open(CKPT)))
    except Exception: return set()


def main(apply=False, kinds=None):
    db = BgSessionLocal()
    rows = [dict(r) for r in db.execute(sql(f"""SELECT id, ticker, direction,
        COALESCE(NULLIF(source_verbatim_quote,''),exact_quote,context,'') quote
        FROM predictions WHERE {VIS_YTX}""")).mappings().all()]
    suspects = []
    for r in rows:
        k = suspect_kinds(r)
        if k and (kinds is None or any(x in kinds for x in k)):
            r["_kinds"] = k; suspects.append(r)
    print(f"suspects in scope: {len(suspects)} (kinds={kinds or 'ALL'})", flush=True)
    if not apply:
        print("DRY-RUN. pass --apply."); return

    done = load_ckpt()
    todo = [r for r in suspects if r["id"] not in done]
    print(f"already done: {len(done)}; to process: {len(todo)}", flush=True)
    flagged = collections.Counter(); processed = 0
    snap = open(SNAP, "a")
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        with ThreadPoolExecutor(max_workers=2) as ex:
            verdicts = list(ex.map(lambda r: (r, verify(r)), chunk))
        for r, (vd, reason, why) in verdicts:
            if vd == "REJECT" and reason in REASON_FLAG:
                flag = REASON_FLAG[reason]
                # snapshot BEFORE flagging (reversible)
                snap.write(json.dumps({"id": r["id"], "reason": reason, "flag": flag,
                                       "kinds": r["_kinds"], "marker": MARKER, "why": why}) + "\n")
                snap.flush()
                if flag == "__conviction__":
                    db.execute(sql("UPDATE predictions SET conviction_level='hedged' WHERE id=:i "
                                   "AND (conviction_level NOT IN ('hedged','hypothetical') OR conviction_level IS NULL)"), {"i": r["id"]})
                else:
                    db.execute(sql(f"UPDATE predictions SET {flag}=TRUE WHERE id=:i AND COALESCE({flag},FALSE)=FALSE"), {"i": r["id"]})
                flagged[reason] += 1
            done.add(r["id"]); processed += 1
        db.commit()
        json.dump(sorted(done), open(CKPT, "w"))
        print(f"  processed {processed}/{len(todo)}  flagged so far={dict(flagged)}", flush=True)
    snap.close()
    print(f"DONE. flagged {sum(flagged.values())} {dict(flagged)}")


if __name__ == "__main__":
    ks = os.environ.get("KINDS")
    main(apply=("--apply" in sys.argv), kinds=set(ks.split(",")) if ks else None)
