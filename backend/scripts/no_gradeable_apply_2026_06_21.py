"""No-gradeable-claim apply step (2026-06-21).

Reads the per-row verdicts produced by no_gradeable_judge_2026_06_21.py and applies
the NOT_GRADEABLE action (GRADEABLE rows untouched):

  NOT_GRADEABLE -> is_no_gradeable_claim=TRUE (hidden via the hedged_filter_sql
    bundle, kill switch HIDE_NO_GRADEABLE_CLAIM) + outcome='unresolved' for rows
    currently scored OR pending (off the accuracy board / never mis-scored later).
    [pre_remediation] JSON saved to evaluation_summary so the change is fully
    reversible. marker no_gradeable_2026_06_21.

flag-not-delete, idempotent (re-flag guard + NOT LIKE marker guard), never deletes.
Requires migration 0024 (is_no_gradeable_claim). DRY-RUN by default — pass --commit
to write. Then POST /api/admin/refresh-forecaster-stats.

Run:
  DATABASE_PUBLIC_URL=... python3 backend/scripts/no_gradeable_apply_2026_06_21.py \
      <verdicts.jsonl> [--commit]
"""
import json
import os
import sys

import psycopg2

VP = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ng_verdicts.jsonl"
COMMIT = "--commit" in sys.argv
MARK = "no_gradeable_2026_06_21"
SCORED_OR_PENDING = ("hit", "correct", "near", "miss", "incorrect", "pending")

UPDATE = """
UPDATE predictions SET
  is_no_gradeable_claim = TRUE,
  outcome = CASE WHEN outcome IN ('hit','correct','near','miss','incorrect','pending')
                 THEN 'unresolved' ELSE outcome END,
  evaluation_summary =
    '[' || %(mark)s || '] no gradeable claim (no number, no direction) -> hidden + off scoreboard. '
    || '[pre_remediation] '
    || json_build_object('is_no_gradeable_claim', is_no_gradeable_claim,
                         'outcome', outcome, 'direction', direction,
                         'actual_return', actual_return)::text
    || ' | prior: ' || COALESCE(evaluation_summary, '(none)'),
  evaluated_at = NOW()
WHERE id = %(id)s
  AND COALESCE(is_no_gradeable_claim, FALSE) = FALSE
  AND COALESCE(evaluation_summary, '') NOT LIKE '%%' || %(mark)s || '%%'
"""


def main():
    ng_ids = []
    for ln in open(VP):
        try:
            o = json.loads(ln)
            if o.get("verdict") == "NOT_GRADEABLE":
                ng_ids.append(int(o["id"]))
        except Exception:
            pass
    ng_ids = sorted(set(ng_ids))
    print(f"NOT_GRADEABLE verdicts: {len(ng_ids)}  (mode={'COMMIT' if COMMIT else 'DRY-RUN'})")

    conn = psycopg2.connect(os.environ["DATABASE_PUBLIC_URL"])
    cur = conn.cursor()
    if not ng_ids:
        print("nothing to apply")
        conn.close()
        return

    # preview: how many are scored/pending (outcome will change) vs already off-board
    cur.execute(
        f"""SELECT
              count(*) FILTER (WHERE COALESCE(is_no_gradeable_claim,FALSE)=FALSE) AS to_flag,
              count(*) FILTER (WHERE outcome IN {SCORED_OR_PENDING}) AS outcome_change,
              count(*) FILTER (WHERE outcome IN ('hit','correct','near','miss','incorrect')) AS scored_now,
              count(*) FILTER (WHERE outcome='pending') AS pending_now,
              count(*) AS total
            FROM predictions WHERE id = ANY(%s)""",
        (ng_ids,),
    )
    to_flag, outc, scored, pending, total = cur.fetchone()
    print(f"  rows found {total} | to-flag {to_flag} | outcome->unresolved {outc} (scored {scored} + pending {pending})")

    if not COMMIT:
        print("DRY-RUN: no writes. Re-run with --commit to apply.")
        conn.close()
        return

    flagged = 0
    for pid in ng_ids:
        cur.execute(UPDATE, {"mark": MARK, "id": pid})
        flagged += cur.rowcount
    conn.commit()
    cur.execute("SELECT count(*) FROM predictions WHERE is_no_gradeable_claim=TRUE")
    total_true = cur.fetchone()[0]
    print(f"APPLIED: {flagged} rows flagged is_no_gradeable_claim + outcome remediated.")
    print(f"total is_no_gradeable_claim=TRUE now: {total_true}")
    conn.close()


if __name__ == "__main__":
    main()
