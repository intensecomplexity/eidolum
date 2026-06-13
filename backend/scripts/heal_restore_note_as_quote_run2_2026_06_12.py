"""Heal pass run 2 (2026-06-12) — restore VERIFIED rows of the
'unverified_quote_2026_06_12' cohort; pin REFUTED rows as permanently unresolved.

Companion artifact (same directory, committed together):
    heal_run2_results_2026_06_12.json
holds the per-row verdicts from the one-row-per-call claude -p Sonnet wide-window
verification: VERIFIED rows carry a verbatim quote that was validated in code as an
exact substring of the live-fetched timed transcript, plus the timestamp resolved by
substring->segment match. The 80 'judged_bad_2026_06_12' rows are NOT in scope.

What this script does per verdict:
  VERIFIED (quote + resolved timestamp):
    - restore outcome / actual_return / evaluation_date FROM the row's own
      [pre_remediation] JSON in evaluation_summary (NEVER recomputed; pending-era
      rows restore to outcome='pending' with NULL return/eval-date);
    - set source_verbatim_quote = the verified quote,
      source_timestamp_seconds = the resolved seconds (these rows were NULL-ts,
      which is what hid them from every YT-visible surface),
      source_timestamp_method = 'heal_pass_2026_06_12';
    - append a '[healed_2026_06_12 ...]' marker, KEEPING the full pre_remediation
      record for audit.
  VERIFIED with no resolvable timestamp: NOT restored (YouTube visibility requires
    a timestamp — hard rule); listed in the artifact for run 2.
  REFUTED: stays unresolved; appends '[heal_2026_06_12: REFUTED]' so the row never
    re-enters a future heal candidate list.
  INSUFFICIENT / UNHEALABLE: untouched (run-2 material / permanently unresolved).

Idempotent: restores skip rows already carrying the healed marker; refuted notes
skip rows already noted. Transactional. Run manually against prod:
    DATABASE_PUBLIC_URL=... python3 backend/scripts/heal_restore_note_as_quote_run2_2026_06_12.py
then a full stats refresh (refresh_all_forecaster_stats on the worker via railway ssh).
"""
import json
import os

import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACT = os.path.join(HERE, 'heal_run2_results_2026_06_12.json')
COHORT_TAG = 'unverified_quote_2026_06_12'
HEALED_MARKER = '[healed_2026_06_12'
REFUTED_MARKER = '[heal_2026_06_12: REFUTED]'


def parse_pre_remediation(summary: str) -> dict:
    blob = summary.split('[pre_remediation] ', 1)[1].split(' | prior: ', 1)[0]
    return json.loads(blob)


def main():
    results = json.load(open(ARTIFACT))['verdicts']
    verified = {int(pid): v for pid, v in results.items()
                if v['verdict'] == 'VERIFIED' and v.get('ts') is not None and v.get('quote')}
    refuted = [int(pid) for pid, v in results.items() if v['verdict'] == 'REFUTED']
    print(f'artifact: {len(verified)} restorable VERIFIED, {len(refuted)} REFUTED')

    conn = psycopg2.connect(os.environ['DATABASE_PUBLIC_URL'])
    cur = conn.cursor()
    cur.execute(
        "SELECT id, evaluation_summary FROM predictions "
        "WHERE id = ANY(%s) AND outcome = 'unresolved' "
        "AND evaluation_summary LIKE %s AND evaluation_summary NOT LIKE %s",
        (list(verified), f'%{COHORT_TAG}%', f'%{HEALED_MARKER}%'))
    restored = 0
    for pid, summary in cur.fetchall():
        pre = parse_pre_remediation(summary)
        v = verified[pid]
        cur.execute(
            """UPDATE predictions
               SET outcome = %s,
                   actual_return = %s,
                   evaluation_date = %s,
                   source_verbatim_quote = %s,
                   source_timestamp_seconds = %s,
                   source_timestamp_method = 'heal_pass_2026_06_12',
                   evaluation_summary = evaluation_summary
                       || ' [healed_2026_06_12 verified; quote+timestamp restored from live transcript]'
               WHERE id = %s AND outcome = 'unresolved'""",
            (pre['outcome'], pre.get('actual_return'), pre.get('evaluation_date'),
             v['quote'], int(v['ts']), pid))
        restored += cur.rowcount
    print(f'restored: {restored}')

    cur.execute(
        "UPDATE predictions SET evaluation_summary = evaluation_summary || ' ' || %s "
        "WHERE id = ANY(%s) AND outcome = 'unresolved' "
        "AND evaluation_summary LIKE %s AND evaluation_summary NOT LIKE %s",
        (REFUTED_MARKER, refuted, f'%{COHORT_TAG}%', f'%{REFUTED_MARKER}%'))
    print(f'refuted-noted: {cur.rowcount}')
    conn.commit()

    cur.execute(
        "SELECT count(*) FROM predictions WHERE evaluation_summary LIKE %s",
        (f'%{HEALED_MARKER}%',))
    print(f'total rows carrying healed marker: {cur.fetchone()[0]}')
    conn.close()


if __name__ == '__main__':
    main()
