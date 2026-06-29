"""REVERT the 39 direction flips applied by verify_direction_apply_2026_06_29.py.

Gate-2 spot-check found the flipper unreliable on edge cases (inverse-ETF SH, bare price
levels, analyst/CEO relay), so ALL 39 are reverted to pre-flip state:
  * 31 non-terminal rows  -> direction-only restore (apply never touched outcome/return:
    rescore() returned early for non-terminal outcomes, mutating only p.direction).
  * 8 terminal rows        -> reconstruct the true eval price from the CURRENT (post-flip)
    stored return (inverting the apply: NO external fetch), set the ORIGINAL direction, and
    re-run the canonical _evaluate_prediction so outcome + actual_return + alpha are restored
    consistently. VERIFY recomputed outcome == snapshot orig_outcome as the oracle.

Reversible: writes the current (post-flip) state to verify_direction_revert_snapshot.jsonl
BEFORE touching anything. Idempotent: skips any row not currently at new_direction.
Commits ONLY with --apply AND zero verification mismatches. Default = DRY-RUN (rolls back).

Run: DATABASE_URL=$DATABASE_PUBLIC_URL python3 scripts/verify_direction_revert_2026_06_29.py [--apply]
"""
import os, sys, json, datetime
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from models import Prediction
from jobs.evaluator import _evaluate_prediction

SNAP = os.path.join(os.path.dirname(__file__), "verify_direction_apply_snapshot.jsonl")
REVERT_SNAP = os.path.join(os.path.dirname(__file__), "verify_direction_revert_snapshot.jsonl")


def _num(x):
    return float(x) if isinstance(x, Decimal) else x


def main(apply=False):
    db = BgSessionLocal()
    snap = [json.loads(l) for l in open(SNAP)]
    ids = [s["id"] for s in snap]
    now = datetime.datetime.utcnow()

    cur = {r["id"]: dict(r) for r in db.execute(sql(
        "SELECT id, direction, outcome, actual_return, entry_price, target_price, "
        "window_days, alpha, sp500_return, evaluated_at FROM predictions WHERE id = ANY(:ids)"
    ), {"ids": ids}).mappings()}

    # Reversibility: persist the current (post-flip) state BEFORE mutating.
    with open(REVERT_SNAP, "w") as f:
        for s in snap:
            c = cur[s["id"]]
            f.write(json.dumps({
                "id": s["id"], "ticker": s["ticker"],
                "direction": c["direction"], "outcome": c["outcome"],
                "actual_return": _num(c["actual_return"]), "alpha": _num(c["alpha"]),
                "sp500_return": _num(c["sp500_return"]),
                "evaluated_at": c["evaluated_at"].isoformat() if c["evaluated_at"] else None,
            }) + "\n")

    results = []
    for s in snap:
        pid = s["id"]; c = cur[pid]
        orig_dir = (s["orig_direction"] or "").lower()
        new_dir = (s["new_direction"] or "").lower()
        cur_dir = (c["direction"] or "").lower()
        terminal = s["new_outcome"] is not None

        if cur_dir != new_dir:
            results.append({"id": pid, "tk": s["ticker"], "mode": "SKIP",
                            "note": f"current dir={cur_dir!r} != snapshot new_dir={new_dir!r} (already reverted?)",
                            "ok": True})
            continue

        p = db.query(Prediction).filter(Prediction.id == pid).first()
        if not terminal:
            # apply only flipped direction; outcome/return untouched -> direction-only restore
            ok_out = (c["outcome"] == s["orig_outcome"])
            p.direction = orig_dir
            results.append({"id": pid, "tk": s["ticker"], "mode": "dir-only",
                            "note": f"{cur_dir}->{orig_dir}; outcome stays {c['outcome']!r}"
                                    + ("" if ok_out else f"  <-- WARN outcome {c['outcome']!r}!=orig {s['orig_outcome']!r}"),
                            "ok": ok_out})
        else:
            rnew = float(c["actual_return"])
            raw_move = rnew if cur_dir == "bullish" else -rnew      # invert apply's reconstruction
            price = float(c["entry_price"]) * (1 + raw_move / 100.0)
            p.direction = orig_dir
            _evaluate_prediction(p, price, now)                     # restores outcome+return
            # alpha = stored_return - sp500_return; sp500_return is direction-independent, so
            # recompute alpha off the restored return (FINNHUB may be unset -> evaluator skips it).
            if p.sp500_return is not None and p.actual_return is not None:
                p.alpha = round(float(p.actual_return) - float(p.sp500_return), 2)
            ok_out = (p.outcome == s["orig_outcome"])
            exp_ret = -rnew
            ok_ret = (p.actual_return is not None and abs(float(p.actual_return) - exp_ret) < 0.02)
            results.append({"id": pid, "tk": s["ticker"], "mode": "rescore",
                            "note": f"outcome {c['outcome']}->{p.outcome} (expect {s['orig_outcome']}) "
                                    f"{'OK' if ok_out else 'MISMATCH'}; "
                                    f"return {rnew}->{round(float(p.actual_return),2)} (expect {round(exp_ret,2)}) "
                                    f"{'OK' if ok_ret else 'MISMATCH'}",
                            "ok": ok_out and ok_ret})

    bad = [r for r in results if not r["ok"]]
    skipped = [r for r in results if r["mode"] == "SKIP"]
    print(f"rows={len(results)}  reverted={len(results)-len(skipped)}  skipped={len(skipped)}  mismatches={len(bad)}")
    for r in results:
        print(f"  [{r['id']}] {r['tk']:6} {r['mode']:9} {r['note']}")

    if not apply:
        db.rollback()
        print("\nDRY-RUN: rolled back, no writes. Pass --apply to commit (only commits if 0 mismatches).")
        return
    if bad:
        db.rollback()
        print(f"\n{len(bad)} MISMATCH(es) -> ROLLED BACK, NOT COMMITTED. Investigate before applying.")
        return
    db.commit()
    print("\nCOMMITTED. Revert applied.")


if __name__ == "__main__":
    main(apply=("--apply" in sys.argv))
