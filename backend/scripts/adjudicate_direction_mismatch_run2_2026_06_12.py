"""Adjudicate the 4 run-2 DIRECTION_MISMATCH review rows (Nimrod-adjudicated 2026-06-14).

Source: requote_review_direction_mismatch_run2_2026_06_12.json. Evidence/visibility
only — NO direction or hand-recomputed outcome changes; flag-not-delete; reversible
([pre_adjudication] JSON preserved in evaluation_summary). Idempotent (skips rows
already carrying 'adjudicated_run2_2026_06_12'). Drift-guarded against the artifact.

  606900 BTC  -> is_reported_speech=TRUE (displayed quote is a reviewed TikToker's
                words, not the host's call). outcome/direction unchanged.
  606579 INTC -> outcome='unresolved' (no committed forward call in transcript)
  607449 SBUX -> outcome='unresolved'
  612538 NVDA -> outcome='unresolved'

Run:  DATABASE_PUBLIC_URL=... python3 backend/scripts/adjudicate_direction_mismatch_run2_2026_06_12.py
then refresh_all_forecaster_stats (these rows leave the scored set).
"""
import json, os, psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ART = {r['id']: r for r in json.load(open(os.path.join(HERE,
       'requote_review_direction_mismatch_run2_2026_06_12.json')))['rows']}
PLAN = {606900: 'reported_speech', 606579: 'no_call', 607449: 'no_call', 612538: 'no_call'}


def main():
    conn = psycopg2.connect(os.environ['DATABASE_PUBLIC_URL']); conn.autocommit = False
    cur = conn.cursor(); acted = {}
    for pid, kind in PLAN.items():
        cur.execute("""SELECT direction,outcome,actual_return,evaluation_date,is_reported_speech,
            COALESCE(evaluation_summary,'') FROM predictions WHERE id=%s""", (pid,))
        r = cur.fetchone()
        a = ART[pid]
        if r is None or 'adjudicated_run2_2026_06_12' in r[5]:
            acted[pid] = 'skip_marked_or_missing'; continue
        if r[0] != a['labeled_direction'] or r[1] != a['current_outcome']:
            acted[pid] = f'skip_drift {r[0]}/{r[1]}'; continue
        pre = json.dumps({'direction': r[0], 'outcome': r[1],
                          'actual_return': float(r[2]) if r[2] is not None else None,
                          'evaluation_date': str(r[3]) if r[3] else None, 'is_reported_speech': r[4]})
        if kind == 'reported_speech':
            cur.execute("""UPDATE predictions SET is_reported_speech=TRUE,
                evaluation_summary=%s||COALESCE(evaluation_summary,'') WHERE id=%s
                AND COALESCE(evaluation_summary,'') NOT LIKE '%%adjudicated_run2_2026_06_12%%'""",
                (f"[adjudicated_run2_2026_06_12=reported_speech] hidden via bundle; outcome/direction unchanged. [pre_adjudication] {pre} | prior: ", pid))
        else:
            cur.execute("""UPDATE predictions SET outcome='unresolved', evaluated_at=NOW(),
                evaluation_summary=%s||COALESCE(evaluation_summary,'') WHERE id=%s
                AND COALESCE(evaluation_summary,'') NOT LIKE '%%adjudicated_run2_2026_06_12%%'""",
                (f"[adjudicated_run2_2026_06_12=no_call] -> unresolved (excluded from accuracy). [pre_adjudication] {pre} | prior: ", pid))
        acted[pid] = f'{kind}:{cur.rowcount}'
    conn.commit(); conn.close()
    print('adjudicated:', acted)


if __name__ == '__main__':
    main()
