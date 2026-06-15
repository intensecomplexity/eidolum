"""Pre-guard cohort cleanup — APPLY (2026-06-15).

Applies the JUDGE verdicts (HOLDING / NO_CALL / REPORTED / keep) to the exact
flags the forward guard sets at insert. id-pinned, idempotent (flag + marker
guards), flag-not-delete, [pre_remediation] preserved, never deletes, never nulls
a timestamp. Direction-corrections are NOT applied (scope: hide-flags only).

  HOLDING  -> is_holding_disclosure=TRUE + outcome='unresolved'  (off scoreboard)
  NO_CALL  -> is_weak_basket_call=TRUE                           (hidden via bundle)
  REPORTED -> is_reported_speech=TRUE                            (hidden via bundle)
  keep     -> untouched

Safe to run repeatedly (per wave). Run:
  DATABASE_PUBLIC_URL=... python3 backend/scripts/preguard_cohort_apply_2026_06_15.py \
    /tmp/preguard_verdicts.json
"""
import json, os, sys
import psycopg2

VP = sys.argv[1] if len(sys.argv) > 1 else '/tmp/preguard_verdicts.json'
HOLD_MARK = 'preguard_hold_2026_06_15'
NOCALL_MARK = 'preguard_nocall_2026_06_15'
REP_MARK = 'preguard_reported_2026_06_15'


def main():
    verdicts = json.load(open(VP))
    by = {'HOLDING': [], 'NO_CALL': [], 'REPORTED': []}
    for pid, v in verdicts.items():
        if v.get('verdict') in by:
            by[v['verdict']].append(int(pid))
    conn = psycopg2.connect(os.environ['DATABASE_PUBLIC_URL'])
    cur = conn.cursor()
    h = nc = rp = 0
    if by['HOLDING']:
        cur.execute("""UPDATE predictions SET is_holding_disclosure=TRUE, outcome='unresolved', evaluated_at=NOW(),
            evaluation_summary='['||%s||' passive holding (shipped holding_guard); [pre_remediation] prior_outcome='||outcome||'] '||COALESCE(evaluation_summary,'')
            WHERE id = ANY(%s) AND COALESCE(is_holding_disclosure,FALSE)=FALSE""",
            (HOLD_MARK, by['HOLDING']))
        h = cur.rowcount
    if by['NO_CALL']:
        cur.execute("""UPDATE predictions SET is_weak_basket_call=TRUE,
            evaluation_summary='['||%s||' no-call narration (shipped rep_guard REJECT_NO_CALL); [pre_remediation] hidden] '||COALESCE(evaluation_summary,'')
            WHERE id = ANY(%s) AND COALESCE(is_weak_basket_call,FALSE)=FALSE""",
            (NOCALL_MARK, by['NO_CALL']))
        nc = cur.rowcount
    if by['REPORTED']:
        cur.execute("""UPDATE predictions SET is_reported_speech=TRUE,
            evaluation_summary='['||%s||' third-party attribution (shipped rep_guard REPORTED_SPEECH); [pre_remediation] hidden] '||COALESCE(evaluation_summary,'')
            WHERE id = ANY(%s) AND COALESCE(is_reported_speech,FALSE)=FALSE""",
            (REP_MARK, by['REPORTED']))
        rp = cur.rowcount
    conn.commit()
    from collections import Counter
    print("verdict tallies:", dict(Counter(v.get('verdict') for v in verdicts.values())))
    print(f"APPLIED this run: holding={h} no_call={nc} reported={rp} "
          f"(candidates: {len(by['HOLDING'])}/{len(by['NO_CALL'])}/{len(by['REPORTED'])})")
    conn.close()


if __name__ == '__main__':
    main()
