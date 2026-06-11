"""Fixtures for Phase-2 conditional macro triggers (historical_evaluator
._check_macro_trigger). Checks fed/commodity/index trigger firing against the
local fmp feeds, and that vague/no-direction/never-crossed stay UNRESOLVED.

Run: DATABASE_PUBLIC_URL=... python3 backend/scripts/test_macro_triggers.py
"""
import os, sys, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "jobs"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sqlalchemy import create_engine  # noqa: E402
import jobs.historical_evaluator as ev  # noqa: E402

DBURL = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
if not DBURL:
    sys.exit("need DATABASE_PUBLIC_URL")
db = create_engine(DBURL).connect()
D = datetime.datetime

CASES = [
    # label, trigger_type, condition, since, until, expect_fire
    ("fed cut (real 2024 cut)", "fed_decision", "if the Fed cuts rates", "2024-06-01", "2025-06-01", True),
    ("fed hike where none", "fed_decision", "if the Fed hikes", "2025-06-01", "2026-06-01", False),
    ("fed no direction word", "fed_decision", "if the Fed acts", "2024-01-01", "2025-06-01", False),
    ("gold breaks 3000", "market_event", "if gold breaks 3000", "2024-01-01", "2026-06-01", True),
    ("oil tops 100 (2022)", "market_event", "if oil tops 100", "2021-06-01", "2022-12-01", True),
    ("copper above 99999 (never)", "market_event", "if copper breaks above 99999", "2024-01-01", "2026-06-01", False),
    ("10yr above 4 (tenor word not level)", "economic_data", "if the 10 year yield breaks above 4", "2023-06-01", "2024-06-01", True),
    ("vague economy -> unresolved", "market_event", "if the economy slows down", "2024-01-01", "2026-06-01", False),
]


def main():
    fails = 0
    for label, tt, cond, s, u, exp in CASES:
        fired, reason = ev._check_macro_trigger(tt, cond, D.fromisoformat(s), D.fromisoformat(u), db)
        ok = (fired is not None) == exp
        if not ok:
            fails += 1
        print(f"  {'OK ' if ok else 'FAIL'} {label}: fired={fired} reason={reason}")
    db.close()
    print(f"\n{'ALL FIXTURES PASS' if fails == 0 else f'{fails} FAILURES'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
