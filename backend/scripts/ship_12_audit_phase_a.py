"""Ship #12 Phase A v2 — verbose, read-only basket_shoehorn audit.

Re-runs the v12.3 basket_shoehorn rule from ship_12_audit.py against
production and prints, for every flagged row:

  - id, ticker, forecaster, source_platform_id
  - full context text (no truncation)
  - which of the 3 signals fired
  - sibling tickers from the same yt_<video_id>_ video

Read-only. Writes nothing. Designed to be run via:

    railway run --service hopeful-expression \
        python -m scripts.ship_12_audit_phase_a

DATABASE_PUBLIC_URL must point at the production Postgres. We use the
*public* URL (railway tcp proxy) because we are operating from WSL.
"""
from __future__ import annotations

import os
import sys

# Make the audit module importable whether we are run via `python -m`
# or as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ship_12_audit import (  # noqa: E402
    PHASE_A_PROTECTED_IDS,
    RULE_VERSION,
    _SELECT_BASKET_CANDIDATES,
    _SELECT_VIDEO_TICKER_PAIRS,
    _build_video_ticker_map,
    _filter_basket_shoehorn,
    _video_prefix,
    basket_shoehorn_signals,
)


def _connect():
    url = os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        raise SystemExit(
            "DATABASE_PUBLIC_URL is not set. "
            "Run via: railway run --service hopeful-expression "
            "python -m scripts.ship_12_audit_phase_a"
        )
    try:
        import psycopg2  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "psycopg2 is required. The system /usr/bin/python3 has it."
        ) from e
    import psycopg2
    return psycopg2.connect(url, connect_timeout=20)


def _resolve_forecaster_names(conn, fids: list[int]) -> dict[int, str]:
    """Look up forecaster.name for a list of ids in one query."""
    if not fids:
        return {}
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, name FROM forecasters WHERE id = ANY(%s)",
            (fids,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}
    finally:
        cur.close()


def check_no_hit_rows_in_flagged(
    flagged_ids: list[int],
    meta_by_id: dict[int, tuple],
) -> list[int]:
    """Belt-and-suspenders guard. Returns the ids of any flagged rows
    whose outcome is 'hit' AND whose entry_price has been stamped.

    Phase B must refuse to run while this list is non-empty — excluding
    a scored win retroactively would invalidate real performance data
    on the leaderboard.

    `meta_by_id` is keyed on prediction id and stores the row tuple
    `(id, forecaster_id, prediction_date, outcome, entry_price,
    target_price, sector)` exactly as the per-row meta query in `main()`
    constructs it. The function is pure so it can be unit-tested
    against synthetic dicts without a live DB.
    """
    offenders: list[int] = []
    for pid in flagged_ids:
        meta = meta_by_id.get(pid)
        if not meta:
            continue
        outcome = meta[3]
        entry_price = meta[4]
        if outcome == "hit" and entry_price is not None:
            offenders.append(pid)
    return offenders


def main() -> int:
    print(f"ship_12_audit_phase_a — basket_shoehorn rule {RULE_VERSION}")
    print(f"PHASE_A_PROTECTED_IDS: {dict(PHASE_A_PROTECTED_IDS)}")
    print()

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT_VIDEO_TICKER_PAIRS)
        sibling_pairs = cur.fetchall()
        cur.close()
        video_ticker_map = _build_video_ticker_map(sibling_pairs)
        print(f"Loaded {len(sibling_pairs):,} (video, ticker) pairs across "
              f"{len(video_ticker_map):,} distinct YouTube videos.")

        cur = conn.cursor()
        cur.execute(_SELECT_BASKET_CANDIDATES)
        basket_rows = cur.fetchall()
        cur.close()
        print(f"Loaded {len(basket_rows):,} basket candidate rows.")

        flagged_ids = _filter_basket_shoehorn(basket_rows, video_ticker_map)
        print(f"basket_shoehorn flagged: {len(flagged_ids)}")
        print()

        if not flagged_ids:
            print(f"OK — no rows flagged by {RULE_VERSION}.")
            return 0

        # Index rows by id for quick lookup, then resolve forecaster
        # names in one batch.
        rows_by_id = {r[0]: r for r in basket_rows}
        # We need forecaster_id for each flagged row — pull it directly.
        cur = conn.cursor()
        cur.execute(
            "SELECT id, forecaster_id, prediction_date, outcome, "
            "       entry_price, target_price, sector "
            "FROM predictions WHERE id = ANY(%s)",
            (flagged_ids,),
        )
        meta_by_id = {r[0]: r for r in cur.fetchall()}
        cur.close()

        fids = sorted({m[1] for m in meta_by_id.values() if m[1] is not None})
        names = _resolve_forecaster_names(conn, fids)

        for pid in flagged_ids:
            r = rows_by_id.get(pid)
            if r is None:
                print(f"--- id={pid} (row not in candidate set; bug) ---")
                continue
            sig = basket_shoehorn_signals(r, video_ticker_map)
            meta = meta_by_id.get(pid)
            forecaster = names.get(meta[1], "?") if meta else "?"
            siblings = sig["sibling_tickers"]
            sib_count = len(siblings)
            print(f"--- id={sig['id']} | ticker={sig['ticker']} | "
                  f"forecaster={forecaster} | "
                  f"source_platform_id={sig['source_platform_id']} ---")
            if meta:
                print(f"  prediction_date={meta[2]}  outcome={meta[3]}  "
                      f"entry_price={meta[4]}  target_price={meta[5]}  "
                      f"sector={meta[6]}")
            print(f"  signals: S1_multi_ticker={sig['signal_1_multi_ticker']} "
                  f"S2_basket_phrasing={sig['signal_2_basket_phrasing']} "
                  f"S3_no_conviction={sig['signal_3_no_conviction']}")
            print(f"  sibling_tickers ({sib_count}): {siblings}")
            print(f"  CONTEXT (full): {sig['context']}")
            print()

        # Confirm META is NOT in the flagged set.
        if 606202 in flagged_ids:
            print("ERROR: 606202 META IS FLAGGED — protection failed.")
            return 2

        # Belt-and-suspenders: refuse to proceed if any flagged row is
        # already a scored hit with a stamped entry_price. Phase B must
        # never retroactively invalidate a documented win.
        hit_offenders = check_no_hit_rows_in_flagged(flagged_ids, meta_by_id)
        if hit_offenders:
            print()
            print("=" * 64)
            print("ERROR: SCORED-HIT ROWS APPEAR IN FLAGGED SET")
            print("=" * 64)
            for pid in hit_offenders:
                meta = meta_by_id.get(pid)
                print(
                    f"  id={pid}  outcome=hit  entry_price={meta[4]}  "
                    f"prediction_date={meta[2]}  sector={meta[6]}"
                )
            print()
            print("Phase B must NOT run while these are in the set.")
            print("Tighten the rule, do not expand PHASE_A_PROTECTED_IDS.")
            return 3

        print(
            "OK — 606202 META is NOT in the flagged set "
            "(conviction marker + PHASE_A_PROTECTED_IDS protection)."
        )
        print(
            "OK — no scored-hit rows in the flagged set "
            "(check_no_hit_rows_in_flagged guard passed)."
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
