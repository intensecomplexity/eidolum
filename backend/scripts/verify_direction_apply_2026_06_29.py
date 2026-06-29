"""PHASE 4: apply direction-correction over the 465 dir_mismatch candidates. For CONFIRMED
contradictions only: flip predictions.direction to the true direction, then RE-SCORE the row
with the canonical evaluator (_evaluate_prediction) using the eval price reconstructed from the
stored return (NO external fetch — respects the FMP hold). Reversible (snapshot original
direction+outcome+return), checkpointed, idempotent. Marker dir_correct_2026_06_29.

Run AFTER the gold gate passes (false-flip~0). claude -p Sonnet, 2 workers.
"""
import os, sys, json, collections, datetime
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from models import Prediction
from jobs.evaluator import _evaluate_prediction
from scripts.verify_direction_2026_06_29 import judge, should_flip
from scripts.verify_layer_2026_06_29 import suspect_kinds, VIS_YTX

SNAP = os.path.join(os.path.dirname(__file__), "verify_direction_apply_snapshot.jsonl")
CKPT = os.path.join(os.path.dirname(__file__), "_verify_direction_ckpt.json")
MARKER = "dir_correct_2026_06_29"
TERMINAL = {"hit", "correct", "miss", "incorrect", "near"}
BATCH = 30


def _ckpt():
    try: return set(json.load(open(CKPT)))
    except Exception: return set()


def rescore(db, pid, new_dir, now):
    """Reload row, flip direction, re-score from reconstructed eval price. Returns (old,new) outcome."""
    p = db.query(Prediction).filter(Prediction.id == pid).first()
    old = p.outcome
    orig_dir = (p.direction or "").lower()
    p.direction = new_dir
    if old not in TERMINAL or not p.entry_price or p.actual_return is None:
        return (old, None)  # not previously scored -> flip only; worker will score later
    raw_move = float(p.actual_return) if orig_dir == "bullish" else -float(p.actual_return)
    price = float(p.entry_price) * (1 + raw_move / 100.0)
    _evaluate_prediction(p, price, now)   # canonical: recomputes p.outcome + p.actual_return
    return (old, p.outcome)


def main(apply=False):
    db = BgSessionLocal()
    rows = [dict(r) for r in db.execute(sql(f"""SELECT id, ticker, direction,
        COALESCE(NULLIF(source_verbatim_quote,''),exact_quote,context,'') quote
        FROM predictions WHERE {VIS_YTX}""")).mappings().all()]
    cand = [r for r in rows if "dir_mismatch" in suspect_kinds(r)]
    print(f"dir_mismatch candidates: {len(cand)}", flush=True)
    if not apply:
        print("DRY-RUN."); return
    done = _ckpt(); todo = [r for r in cand if r["id"] not in done]
    print(f"to process: {len(todo)}", flush=True)
    now = datetime.datetime.utcnow(); snap = open(SNAP, "a")
    flips = collections.Counter(); transitions = collections.Counter(); processed = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        with ThreadPoolExecutor(max_workers=2) as ex:
            judged = list(ex.map(lambda r: (r, judge(r)), chunk))
        for r, j in judged:
            if should_flip(r, j):
                new_dir = j["true_direction"].lower()
                old_out, new_out = rescore(db, r["id"], new_dir, now)
                snap.write(json.dumps({"id": r["id"], "marker": MARKER, "ticker": r["ticker"],
                    "orig_direction": r["direction"], "new_direction": new_dir,
                    "orig_outcome": old_out, "new_outcome": new_out,
                    "evidence": j.get("evidence", ""), "why": j.get("why", "")}) + "\n"); snap.flush()
                flips[f"{r['direction']}->{new_dir}"] += 1
                if old_out in TERMINAL and new_out: transitions[f"{old_out}->{new_out}"] += 1
            done.add(r["id"]); processed += 1
        db.commit(); json.dump(sorted(done), open(CKPT, "w"))
        print(f"  processed {processed}/{len(todo)}  flips={sum(flips.values())} {dict(flips)}  scoring={dict(transitions)}", flush=True)
    snap.close()
    print(f"DONE. flips={sum(flips.values())} {dict(flips)}  outcome-transitions={dict(transitions)}")


if __name__ == "__main__":
    main(apply=("--apply" in sys.argv))
