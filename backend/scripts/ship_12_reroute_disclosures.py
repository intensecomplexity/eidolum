"""Ship #12 — optional disclosure reroute.

For rows flagged `disclosure_misroute` by ship_12_apply.py, this
script scores each row with a point-based heuristic (no Haiku call)
and migrates the highest-confidence candidates into the `disclosures`
table. The original prediction row stays in place — it remains
`excluded_from_training = TRUE`, the leaderboard is unchanged, we're
purely adding a disclosure record so the follow-through job can score
the position.

Dry-run is the default. The dry-run mode writes a CSV to
backend/scripts/ship_12_reroute_dryrun.csv with one row per candidate:

    prediction_id, ticker, confidence_score, context_truncated_100,
    would_insert, skipped_conflict

`skipped_conflict` is 1 when the `source_platform_id` already exists
in the `disclosures` table (UNIQUE constraint) and the INSERT would
have been a no-op; we ON CONFLICT DO NOTHING the real insert, but
flag the row in the CSV so the operator can see the collision count.

Schema adaptation (from ship spec review):
  - `disclosures.reasoning_text` is used where the spec said "context"
  - `disclosures.disclosed_at` gets `predictions.prediction_date`
  - `disclosures.action` is set to 'hold' for every reroute candidate
    (ownership language over neutral ticker_call = holding a position)
  - `disclosures.source_platform_id` already has a UNIQUE index; we
    use ON CONFLICT (source_platform_id) DO NOTHING
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ship_12_audit import (  # noqa: E402
    RULE_VERSION,
    REASONS,
    _connect,
    _OWNERSHIP_RE,
    _RATING_VOICE_RE,
)

REROUTE_THRESHOLD = 4
VERIFIED_BY = f"ship_12_reroute_{RULE_VERSION}"

_CURRENT_RE = re.compile(
    r"\b(current(?:ly)?|still|now|as\s+of)\b", re.IGNORECASE
)
_TARGET_RE = re.compile(r"\b(target|pt|price\s+target)\b", re.IGNORECASE)
_RATING_NOUN_RE = re.compile(r"\brate[sd]?\b|\brating\b", re.IGNORECASE)
_OWNERSHIP_VERB_RE = re.compile(
    r"\b(hold(?:ing)?|long|short|own(?:ing)?|position)\b", re.IGNORECASE
)
_FIRST_PERSON_RE = re.compile(r"\b(we|our|i|my)\b", re.IGNORECASE)


def _source_blob(context: str, exact_quote: str, quote_context: str) -> str:
    parts = [p for p in (context, exact_quote, quote_context) if p]
    return " ".join(parts)


def _score_candidate(context, exact_quote, quote_context, direction, target_price) -> int:
    """Hard-coded point heuristic. See ship spec STEP 4 for weights."""
    blob = _source_blob(context or "", exact_quote or "", quote_context or "")
    score = 0

    # +3: first-person pronoun within ~20 chars of ownership verb
    for fp in _FIRST_PERSON_RE.finditer(blob):
        start, end = fp.span()
        window = blob[max(0, start - 20) : end + 20]
        if _OWNERSHIP_VERB_RE.search(window):
            score += 3
            break

    # +2: "currently / still / now / as of" near the ownership verb
    for m in _OWNERSHIP_VERB_RE.finditer(blob):
        start, end = m.span()
        window = blob[max(0, start - 30) : end + 30]
        if _CURRENT_RE.search(window):
            score += 2
            break

    # +1: direction=neutral (or hold) and no price target
    if (direction or "").lower() in ("neutral", "hold") and target_price is None:
        score += 1

    # -2: analyst-rating noun present ("rates", "rating")
    if _RATING_NOUN_RE.search(blob):
        score -= 2

    # -2: price-target wording present
    if _TARGET_RE.search(blob):
        score -= 2

    return score


def _collect_candidates(conn) -> List[Tuple]:
    """Fetch every row flagged with disclosure_misroute, plus the
    fields we need for scoring and migration."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ticker, context, exact_quote, quote_context,
               direction, target_price, prediction_date,
               source_platform_id, forecaster_id
        FROM predictions
        WHERE excluded_from_training = TRUE
          AND exclusion_reason = 'disclosure_misroute'
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _existing_disclosure_spids(conn, spids: List[str]) -> set:
    if not spids:
        return set()
    cur = conn.cursor()
    placeholders = ",".join(["%s"] * len(spids))
    cur.execute(
        f"SELECT source_platform_id FROM disclosures "
        f"WHERE source_platform_id IN ({placeholders})",
        spids,
    )
    out = {r[0] for r in cur.fetchall() if r[0]}
    cur.close()
    return out


def _write_dryrun_csv(path: str, scored: List[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "prediction_id",
                "ticker",
                "confidence_score",
                "context_truncated_100",
                "would_insert",
                "skipped_conflict",
            ]
        )
        for r in scored:
            ctx = (r["context"] or "")[:100].replace("\n", " ")
            w.writerow(
                [
                    r["id"],
                    r["ticker"],
                    r["score"],
                    ctx,
                    int(bool(r["would_insert"])),
                    int(bool(r["skipped_conflict"])),
                ]
            )


def _insert_disclosure(conn, row: dict) -> bool:
    """INSERT ... ON CONFLICT DO NOTHING. Returns True if a new row
    was actually inserted (rowcount==1), False otherwise."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO disclosures
              (forecaster_id, ticker, action, reasoning_text,
               disclosed_at, source_platform_id,
               source_prediction_id, created_at)
            VALUES (%s, %s, 'hold', %s, %s, %s, %s, NOW())
            ON CONFLICT (source_platform_id) DO NOTHING
            """,
            (
                row["forecaster_id"],
                row["ticker"],
                row["context"],
                row["prediction_date"],
                row["source_platform_id"],
                row["id"],
            ),
        )
        inserted = cur.rowcount == 1
        return inserted
    finally:
        cur.close()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ship #12 — dry-run-first disclosure reroute."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Default is dry-run (CSV only).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=REROUTE_THRESHOLD,
        help=f"Minimum confidence score to include (default {REROUTE_THRESHOLD}).",
    )
    parser.add_argument(
        "--csv",
        default=os.path.join(os.path.dirname(__file__), "ship_12_reroute_dryrun.csv"),
        help="Path for the dry-run CSV.",
    )
    args = parser.parse_args(argv)

    conn = _connect()
    try:
        rows = _collect_candidates(conn)
    except Exception as e:
        conn.close()
        print(f"collection failed: {e}", file=sys.stderr)
        return 2

    if not rows:
        print(
            "No rows flagged with disclosure_misroute yet. "
            "Run ship_12_apply.py --apply --reason disclosure_misroute first."
        )
        conn.close()
        return 0

    scored = []
    for r in rows:
        (
            _id,
            ticker,
            context,
            exact_quote,
            quote_context,
            direction,
            target_price,
            prediction_date,
            source_platform_id,
            forecaster_id,
        ) = r
        score = _score_candidate(
            context, exact_quote, quote_context, direction, target_price
        )
        scored.append(
            {
                "id": _id,
                "ticker": ticker,
                "context": context,
                "exact_quote": exact_quote,
                "quote_context": quote_context,
                "direction": direction,
                "target_price": target_price,
                "prediction_date": prediction_date,
                "source_platform_id": source_platform_id,
                "forecaster_id": forecaster_id,
                "score": score,
                "would_insert": score >= args.threshold and source_platform_id is not None,
                "skipped_conflict": False,
            }
        )

    # Detect pre-existing disclosure collisions so the CSV shows them.
    candidate_spids = [
        s["source_platform_id"] for s in scored if s["would_insert"]
    ]
    existing = _existing_disclosure_spids(conn, candidate_spids)
    for s in scored:
        if s["would_insert"] and s["source_platform_id"] in existing:
            s["skipped_conflict"] = True
            s["would_insert"] = False

    _write_dryrun_csv(args.csv, scored)

    eligible = sum(1 for s in scored if s["would_insert"])
    conflicts = sum(1 for s in scored if s["skipped_conflict"])
    below_threshold = sum(1 for s in scored if s["score"] < args.threshold)

    print()
    print(f"ship_12_reroute_disclosures — threshold={args.threshold}")
    print(f"  total candidates:      {len(scored):>8,}")
    print(f"  eligible to insert:    {eligible:>8,}")
    print(f"  below threshold:       {below_threshold:>8,}")
    print(f"  skipped (conflict):    {conflicts:>8,}")
    print(f"  dry-run CSV:           {args.csv}")
    print()

    if not args.apply:
        print("DRY-RUN — no writes. Re-run with --apply after reviewing the CSV.")
        conn.close()
        return 0

    print(
        f"PLANNED INSERT: {eligible} disclosures "
        f"(source_prediction_id populated)"
    )
    print("sleeping 3 seconds so the plan stays visible ...")
    time.sleep(3)

    inserted = 0
    for s in scored:
        if not s["would_insert"]:
            continue
        try:
            ok = _insert_disclosure(conn, s)
            if ok:
                inserted += 1
        except Exception as e:
            conn.rollback()
            print(
                f"insert failed for prediction_id={s['id']}: {e}",
                file=sys.stderr,
            )
            conn.close()
            return 2
    conn.commit()
    conn.close()

    print(f"APPLIED: {inserted} disclosures inserted, {eligible - inserted} no-ops")
    return 0


if __name__ == "__main__":
    sys.exit(main())
