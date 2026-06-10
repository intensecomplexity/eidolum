"""Hide weak basket/inferred-direction predictions from user surfaces.

Background
----------
2026-06-10: 130 live YouTube rows matched the basket-enumeration regex
(ticker appears inside an enumerated company list). ~half are legit
explicit collective calls ("I'm still buying PANW, CRWD, FTNT, ZS"), so
a one-shot claude -p judge classified each row: does the speaker make an
EXPLICIT forward directional call covering THIS ticker? Verdicts live in
`_artifacts/basket_judge_verdicts_2026-06-10.json` (input quotes in
`_artifacts/basket_judge_input_2026-06-10.json`). Exemplar weak row:
616182 (BWB → AA bearish from tariff-mechanics basket).

This script flags the judged-weak ("explicit_call": false) rows with
`is_weak_basket_call = TRUE`. The flag is the established visibility
class (is_reported_speech / is_ambiguous_symbol pattern): rows stay in
the DB for audit, hidden from user-facing surfaces via the bundled
hedged_filter_sql helper in routers/_prediction_filters.py, kill switch
HIDE_WEAK_BASKET_CALLS.

Reversible: per-row boolean (UPDATE ... SET is_weak_basket_call=FALSE to
unflag) + env kill switch flips every surface back at once.

Usage
-----
  # Verify (default — no writes, transaction rolled back):
  DATABASE_PUBLIC_URL=... python -m scripts.hide_weak_basket_calls

  # Pull the trigger:
  DATABASE_PUBLIC_URL=... python -m scripts.hide_weak_basket_calls --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import psycopg2

ARTIFACTS = os.path.join(os.path.dirname(__file__), "_artifacts")
VERDICTS = os.path.join(ARTIFACTS, "basket_judge_verdicts_2026-06-10.json")

DDL = """
    ALTER TABLE predictions
      ADD COLUMN IF NOT EXISTS is_weak_basket_call BOOLEAN NOT NULL DEFAULT FALSE
"""
DDL_INDEX = """
    CREATE INDEX IF NOT EXISTS ix_predictions_is_weak_basket_call
      ON predictions (is_weak_basket_call) WHERE is_weak_basket_call = TRUE
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit the flags")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("RECOVERY_DATABASE_URL")
    if not url:
        print("FATAL: set DATABASE_PUBLIC_URL")
        sys.exit(2)

    verdicts = json.load(open(VERDICTS))
    weak_ids = sorted(int(k) for k, v in verdicts.items() if not v["explicit_call"])
    print(f"{len(verdicts)} verdicts, {len(weak_ids)} judged weak")

    conn = psycopg2.connect(url, connect_timeout=10)
    cur = conn.cursor()

    # DDL with the short-lock retry pattern (see disambiguate_symbols.py):
    # scraper transactions hold ACCESS SHARE for tens of seconds; retry
    # until we land in a gap, stalling other queries at most 5s each try.
    cur.execute("SET lock_timeout = '5s'")
    for attempt in range(60):
        try:
            cur.execute(DDL)
            cur.execute(DDL_INDEX)
            conn.commit()
            break
        except psycopg2.OperationalError:
            conn.rollback()
            print(f"  DDL attempt {attempt + 1}: lock busy, retrying...", flush=True)
            time.sleep(4)
    else:
        print("FATAL: could not acquire DDL lock in 60 attempts")
        sys.exit(2)
    print("column + partial index ready")

    cur.execute(
        """UPDATE predictions SET is_weak_basket_call = TRUE
           WHERE id = ANY(%s) AND is_weak_basket_call = FALSE
           RETURNING id""",
        (weak_ids,),
    )
    flagged = [r[0] for r in cur.fetchall()]
    print(f"UPDATE matched {len(flagged)} of {len(weak_ids)} judged-weak ids")
    missing = set(weak_ids) - set(flagged)
    if missing:
        print(f"  not flagged (already TRUE or id gone): {sorted(missing)}")

    if args.apply:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("DRY RUN — rolled back (rerun with --apply)")
    conn.close()


if __name__ == "__main__":
    main()
