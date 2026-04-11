"""Ship #12 — revert the two v12.2 basket_shoehorn exclusions in prod.

Background
----------
v12.2 of the basket_shoehorn audit rule was applied to production at
some point and excluded exactly two rows:

  - 605761 TSLA  (New Money — legitimate basket the v12.4 rewrite still
                  flags, but the v12.2 audit-trail tag is stale)
  - 606202 META  (Chip Stock Investor — outcome=hit with entry_price
                  $294.29 stamped, the exact win the v12.4 rewrite was
                  meant to protect)

We need to clear both rows back to `excluded_from_training=FALSE` so
the v12.4 rule can re-evaluate them with the corrected logic. META
will then drop via _has_conviction_marker("going with Meta") AND the
PHASE_A_PROTECTED_IDS backstop. TSLA will be re-flagged by v12.4 with
a clean rule_version tag (currently a separate ship — basket_shoehorn
is NOT in Phase B's approved reasons).

Behaviour
---------
- Default mode is `--dry-run` (the UPDATE runs inside a transaction
  and the transaction is rolled back). `--apply` is required to commit.
- Prints before-state and after-state for both rows so the operator
  can eyeball the diff before pulling the trigger.
- Asserts the UPDATE rowcount is exactly 2 and refuses to commit if
  not. This catches "someone else already reverted one of them" or
  "the row got re-tagged with a newer rule_version" without leaving
  the table in a partially-fixed state.

Usage
-----
  # Verify (default — no writes):
  DATABASE_PUBLIC_URL=... python -m scripts.ship_12_revert_v122_basket
  DATABASE_PUBLIC_URL=... python -m scripts.ship_12_revert_v122_basket --dry-run

  # Pull the trigger (Nimrod only):
  DATABASE_PUBLIC_URL=... python -m scripts.ship_12_revert_v122_basket --apply

DO NOT run `--apply` without explicit approval. The script writes
nothing in dry-run mode and is safe to re-run any number of times.
"""
from __future__ import annotations

import argparse
import os
import sys


# The two prediction ids the v12.2 basket_shoehorn rule excluded.
# Hard-coded so a typo in argv can never widen the blast radius.
ROW_IDS: tuple[int, ...] = (605761, 606202)

# Strict WHERE clause: id-in AND tag-match. Any row that's been
# re-tagged since the audit (e.g. by a future v12.5 apply) will not
# match and the rowcount assertion will fail safe.
UPDATE_SQL = """
    UPDATE predictions
    SET excluded_from_training = FALSE,
        exclusion_reason = NULL,
        exclusion_flagged_at = NULL,
        exclusion_rule_version = NULL
    WHERE id = ANY(%s)
      AND exclusion_rule_version = 'v12.2'
      AND exclusion_reason = 'basket_shoehorn'
"""

SELECT_SQL = """
    SELECT id, ticker, forecaster_id, outcome, entry_price,
           excluded_from_training, exclusion_reason, exclusion_rule_version
    FROM predictions
    WHERE id = ANY(%s)
    ORDER BY id
"""


def _print_state(cur, label: str) -> list[tuple]:
    """Pretty-print the row state for both target ids."""
    cur.execute(SELECT_SQL, (list(ROW_IDS),))
    rows = cur.fetchall()
    print(f"--- {label} ---")
    if not rows:
        print("  (no rows returned)")
        return rows
    for r in rows:
        (rid, ticker, fid, outcome, entry_price,
         excluded, reason, version) = r
        print(
            f"  id={rid:6d}  ticker={ticker:6s}  forecaster_id={fid}  "
            f"outcome={outcome}  entry_price={entry_price}\n"
            f"            excluded_from_training={excluded}  "
            f"exclusion_reason={reason}  exclusion_rule_version={version}"
        )
    print()
    return rows


def _connect():
    url = os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        raise SystemExit(
            "DATABASE_PUBLIC_URL is not set. Source it from the Postgres "
            "service variables (the worker service env does not expose it):\n"
            "  DPU=$(railway variables -s Postgres --json | "
            "python3 -c \"import json,sys; print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])\")"
        )
    try:
        import psycopg2  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "psycopg2 is required. The system /usr/bin/python3 has it."
        ) from e
    import psycopg2
    return psycopg2.connect(url, connect_timeout=20)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Revert the two v12.2 basket_shoehorn exclusions in prod.",
    )
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--apply",
        action="store_true",
        help="Actually commit the revert. Defaults to dry-run.",
    )
    grp.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the UPDATE inside a transaction and roll back. Default.",
    )
    args = parser.parse_args(argv)

    apply_mode = bool(args.apply)
    dry_run = not apply_mode  # default behavior

    print(f"ship_12_revert_v122_basket — mode={'APPLY' if apply_mode else 'DRY RUN'}")
    print(f"target ids: {list(ROW_IDS)}")
    print(f"target tag: exclusion_rule_version='v12.2' AND exclusion_reason='basket_shoehorn'")
    print()

    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        before_rows = _print_state(cur, "BEFORE")
        if not before_rows:
            print("ABORT: no rows returned for the target ids.")
            conn.rollback()
            return 2
        if len(before_rows) != len(ROW_IDS):
            print(
                f"ABORT: expected {len(ROW_IDS)} rows, "
                f"got {len(before_rows)}."
            )
            conn.rollback()
            return 2

        cur.execute(UPDATE_SQL, (list(ROW_IDS),))
        affected = cur.rowcount
        print(f"UPDATE affected_rows={affected}")
        print()

        if affected != 2:
            print(
                f"ABORT: expected affected_rows=2, got {affected}. "
                "Refusing to commit. Rolling back."
            )
            conn.rollback()
            raise SystemExit(2)

        # Re-query inside the same (uncommitted) transaction so the
        # operator can see what the post-revert state would look like.
        _print_state(cur, "AFTER (in transaction)")

        if dry_run:
            conn.rollback()
            print("DRY RUN — rollback")
            return 0

        conn.commit()
        print("COMMITTED")
        return 0
    finally:
        try:
            cur.close()
        finally:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
