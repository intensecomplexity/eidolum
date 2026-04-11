"""Ship #12 — apply exclusion flags for one reason at a time.

Re-runs the same audit as ship_12_audit.py, then UPDATEs the flagged
rows with `excluded_from_training = TRUE`, `exclusion_reason = <reason>`,
`exclusion_flagged_at = NOW()`, `exclusion_rule_version = <rule_version>`.

Dry-run is the default. `--apply` is required to actually write. A
single `--reason` must be specified per invocation — this forces
intentional execution and keeps transactions short.

Rows that already carry `excluded_from_training = TRUE` are skipped
(never overwrite; never downgrade an exclusion reason).

Exit codes:
  0 — success (dry-run or apply)
  1 — usage error
  2 — DB error / unexpected row-count drift (apply rolled back)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List

# Make the audit module importable whether we're run via `python -m`
# or directly as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ship_12_audit import (  # noqa: E402
    RULE_VERSION,
    REASONS,
    run_audit,
    _connect,
)


# Phase B approved reasons — hardcoded allowlist. basket_shoehorn and
# invented_timeframe are deferred to later ships and must not be
# runnable from this script even though they appear in REASONS.
#
# basket_shoehorn was rewritten as v12.4 (3-signal AND with conviction
# markers and PHASE_A_PROTECTED_IDS) but the rule has not been validated
# against enough real data to pull the trigger automatically on 554K
# rows. invented_timeframe currently flags 351,836 rows (63% of the
# corpus) and needs the window_days upper-cap fix (Ship #12.2) before
# it's safe to apply.
#
# Editing this set is the only legitimate way to widen Phase B's scope
# — that change should be reviewed in its own commit, not snuck in via
# a `--reason` argument at the call site.
_PHASE_B_APPROVED_REASONS: frozenset[str] = frozenset({
    "disclosure_misroute",
    "duplicate_source",
    "unresolvable_reference",
})


def _apply_one_reason(
    conn,
    reason: str,
    ids: List[int],
    limit: int,
    rule_version: str,
) -> int:
    """Flag `ids` with `reason` inside a single transaction with a
    SAVEPOINT. Returns the number of rows actually updated. Raises
    RuntimeError if the update count drifts from expectation (race)."""
    if not ids:
        return 0

    capped = ids[:limit]
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute("SAVEPOINT ship12_apply")

        placeholders = ",".join(["%s"] * len(capped))
        sql = (
            f"UPDATE predictions "
            f"SET excluded_from_training = TRUE, "
            f"    exclusion_reason = %s, "
            f"    exclusion_flagged_at = NOW(), "
            f"    exclusion_rule_version = %s "
            f"WHERE id IN ({placeholders}) "
            f"  AND excluded_from_training = FALSE"
        )
        params = [reason, rule_version] + capped
        cur.execute(sql, params)
        affected = cur.rowcount

        # Drift check: at most len(capped) rows should have matched,
        # and the skipped-already-excluded delta is (capped - affected).
        # We accept affected <= len(capped). Strictly greater is
        # impossible in Postgres for IN(...), but we still assert.
        if affected > len(capped):
            cur.execute("ROLLBACK TO SAVEPOINT ship12_apply")
            cur.execute("ROLLBACK")
            raise RuntimeError(
                f"drift detected: affected={affected} > capped={len(capped)}"
            )

        cur.execute("RELEASE SAVEPOINT ship12_apply")
        cur.execute("COMMIT")
        return affected
    except Exception:
        try:
            cur.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        cur.close()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ship #12 apply exclusion flags (one reason per run)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Default is dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run flag (default behavior anyway).",
    )
    parser.add_argument(
        "--reason",
        choices=list(REASONS) + ["manual_review"],
        help="Reason tag to apply. Required with --apply.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Cap on rows updated per run (default 10000). Re-run to process more.",
    )
    parser.add_argument(
        "--rule-version",
        default=RULE_VERSION,
        help=f"Rule version tag written to the row (default {RULE_VERSION}).",
    )
    args = parser.parse_args(argv)

    if args.apply and not args.reason:
        parser.error("--apply requires --reason <name>")
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    # Phase B allowlist enforcement. The argparse `choices` accept the
    # full REASONS tuple for telemetry / dry-run reasons, but `--apply`
    # is restricted to the deliberately-narrow allowlist defined above.
    # `manual_review` is also accepted as an escape hatch for one-off
    # admin work; basket_shoehorn / invented_timeframe are NOT.
    if (
        args.apply
        and args.reason not in _PHASE_B_APPROVED_REASONS
        and args.reason != "manual_review"
    ):
        parser.error(
            f"--reason {args.reason!r} is not approved for Phase B. "
            f"Approved: {sorted(_PHASE_B_APPROVED_REASONS)}. "
            f"To change this, edit _PHASE_B_APPROVED_REASONS in ship_12_apply.py."
        )

    conn = _connect()
    try:
        flagged = run_audit(conn)
    except Exception as e:
        conn.close()
        print(f"audit failed: {e}", file=sys.stderr)
        return 2

    counts = {k: len(v) for k, v in flagged.items()}
    print()
    print(f"ship_12_apply — rule_version {args.rule_version}")
    print(f"{'reason':<28} {'count':>10}")
    print("-" * 40)
    for reason in REASONS:
        marker = "<-- target" if reason == args.reason else ""
        print(f"{reason:<28} {counts[reason]:>10,} {marker}")
    print()

    if not args.apply:
        print("DRY-RUN — no writes. Re-run with --apply --reason <name> to flag rows.")
        conn.close()
        return 0

    ids = flagged[args.reason]
    if not ids:
        print(f"nothing to flag for reason={args.reason}. exit 0.")
        conn.close()
        return 0

    to_write = min(len(ids), args.limit)
    print(
        f"PLANNED UPDATE: reason={args.reason} "
        f"candidate_ids={len(ids)} will_update={to_write} "
        f"limit={args.limit}"
    )
    print("sleeping 3 seconds so the plan stays visible ...")
    time.sleep(3)

    try:
        written = _apply_one_reason(
            conn,
            reason=args.reason,
            ids=ids,
            limit=args.limit,
            rule_version=args.rule_version,
        )
    except Exception as e:
        print(f"apply failed ({e}); transaction rolled back", file=sys.stderr)
        conn.close()
        return 2

    print(f"APPLIED: reason={args.reason} rows_updated={written}")
    if to_write > written:
        skipped = to_write - written
        print(
            f"  ({skipped} candidate ids were already excluded — skipped, not overwritten)"
        )
    if len(ids) > args.limit:
        remaining = len(ids) - args.limit
        print(f"  ({remaining} more candidates remain — re-run to continue)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
