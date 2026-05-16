"""Backtest the classifier validation gate against canonical fixtures and
the 61 predictions soft-deleted in the 2026-05-14 pre-screencast cull.

Usage:  DATABASE_URL=... python3 scripts/backtest_classifier_gate.py
(falls back to DATABASE_PUBLIC_URL / DBURL env var).

Read-only — performs no writes.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "jobs"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text  # noqa: E402
import classifier_validation as gate  # noqa: E402

DBURL = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")
         or os.environ.get("DBURL"))

# fixture id -> expected outcome
FIXTURES = {
    614884: ("REJECT", "MACRO — fake ticker"),
    624849: ("REJECT", "LOW — context is Home Depot"),
    624850: ("PASS", "GOOGL — Fast Graphs showcase"),
    616514: ("PASS", "AXTI — Chip Stock Investor showcase"),
    616987: ("PASS", "PEP — Let's Talk Money showcase"),
}


def _row(db, pid):
    r = db.execute(text(
        "SELECT id,ticker,direction,source_url,source_verbatim_quote,created_at "
        "FROM predictions WHERE id=:i"), {"i": pid}).first()
    if not r:
        return None
    return {"id": r[0], "ticker": r[1], "direction": r[2], "source_url": r[3],
            "source_verbatim_quote": r[4], "created_at": r[5]}


def _rules_fired(pred, db):
    """All rule reasons that fire for a prediction (not short-circuited)."""
    q = pred.get("source_verbatim_quote")
    fired = []
    if not gate.check_ticker_real(pred.get("ticker"), db)[0]:
        fired.append("invalid_ticker")
    if not gate.check_ticker_in_quote(pred.get("ticker"), q, db)[0]:
        fired.append("ticker_not_in_context")
    if not gate.check_ad_read(q)[0]:
        fired.append("ad_read")
    if not gate.check_past_tense(q)[0]:
        fired.append("past_tense_only")
    if not gate.check_contradiction(pred.get("source_url"), pred.get("direction"),
                                    pred.get("ticker"), db,
                                    ref_time=pred.get("created_at"),
                                    exclude_id=pred.get("id"))[0]:
        fired.append("contradictory_pair")
    if not gate.check_min_length(q)[0]:
        fired.append("context_too_short")
    return fired


def main():
    engine = create_engine(DBURL)
    with engine.connect() as db:
        print("=" * 78)
        print("FIXTURE RESULTS")
        print("=" * 78)
        all_pass = True
        for pid, (expected, label) in FIXTURES.items():
            pred = _row(db, pid)
            if pred is None:
                print(f"  id={pid}: NOT FOUND"); all_pass = False; continue
            accepted, reason = gate.validate_or_reject(
                pred, db, ref_time=pred["created_at"], exclude_id=pid)
            actual = "PASS" if accepted else "REJECT"
            fired = _rules_fired(pred, db)
            ok = (actual == expected)
            all_pass &= ok
            print(f"  [{'OK ' if ok else 'FAIL'}] id={pid} {pred['ticker']:6s} "
                  f"expected={expected:6s} actual={actual:6s} "
                  f"rules_fired={fired or ['none']}  ({label})")

        print()
        print("=" * 78)
        print("61-ROW BACKTEST (exclusion_rule_version='screencast_cull')")
        print("=" * 78)
        rows = db.execute(text(
            "SELECT id,ticker,direction,source_url,source_verbatim_quote,created_at "
            "FROM predictions WHERE exclusion_rule_version='screencast_cull' "
            "ORDER BY id")).fetchall()
        caught = 0
        by_reason = {}
        missed = []
        for r in rows:
            pred = {"id": r[0], "ticker": r[1], "direction": r[2],
                    "source_url": r[3], "source_verbatim_quote": r[4],
                    "created_at": r[5]}
            accepted, reason = gate.validate_or_reject(
                pred, db, ref_time=pred["created_at"], exclude_id=pred["id"])
            if not accepted:
                caught += 1
                by_reason[reason] = by_reason.get(reason, 0) + 1
            else:
                missed.append((pred["id"], pred["ticker"]))
        total = len(rows)
        print(f"  caught {caught}/{total}  ({100 * caught // total if total else 0}%)")
        for reason, n in sorted(by_reason.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {n}")
        if missed:
            print(f"  missed ({len(missed)}): {missed}")

        print()
        print("=" * 78)
        threshold_ok = caught >= 50
        print(f"VERDICT: fixtures {'ALL PASS' if all_pass else 'FAILED'} | "
              f"backtest {caught}/{total} {'>=50 OK' if threshold_ok else '<50 FAIL'}")
        return 0 if (all_pass and threshold_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
