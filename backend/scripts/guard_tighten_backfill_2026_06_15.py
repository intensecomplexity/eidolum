"""STEP 4 backfill for the 2026-06-15 guard-tightening ship (bounded part).

Two deterministic, idempotent, flag-not-delete actions:

A) TARGET wrong-side (Bug 4b): scored YouTube rows whose target is on the wrong
   side of the locked entry (bullish target far below / bearish far above, per
   services.target_sanity.sanity_check_target with direction) are re-scored
   DIRECTION-ONLY. We null target_price (original preserved in
   evaluation_summary [pre_remediation]) + reset outcome='pending' +
   evaluated_at=NULL so the canonical evaluator re-scores direction-only on its
   next pass — robust regardless of which code the evaluator service is running.
   AVGO 631403 (pending) gets its bogus target nulled too. Equity + crypto with
   a reliable entry; index ETFs included only when the wrong-side rule fires
   (logically sound: a bearish target above entry is wrong-side for any asset).

B) Confirmed PRE-GUARD leaks (inserted 06-11, before the 06-14 guards shipped):
   the shipped guards were re-run read-only and returned —
     631378 GOOG -> HOLDING            => is_holding_disclosure + unresolved
     631386 GOOGL-> REJECT_NO_CALL     => is_weak_basket_call
     631548 SBUX -> REJECT_NO_CALL     => is_weak_basket_call
     631555 META -> REJECT_NO_CALL     => is_weak_basket_call
   Matches exactly what insert_youtube_prediction would have set.

READ-ONLY on everything else. Idempotent (marker + flag guards). Never deletes.
Run:  DATABASE_PUBLIC_URL=... python3 backend/scripts/guard_tighten_backfill_2026_06_15.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import psycopg2
from services.target_sanity import sanity_check_target

TGT_MARK = 'target_wrongside_2026_06_15'
HOLD_MARK = 'holdback_2026_06_15'
REP_MARK = 'repnocall_backfill_2026_06_15'
SCORED = "outcome IN ('hit','correct','near','miss','incorrect')"

# Part B verdicts (from the read-only re-run of the SHIPPED guards)
HOLDING_LEAKS = [631378]
REPNOCALL_LEAKS = [631386, 631548, 631555]


def main():
    conn = psycopg2.connect(os.environ['DATABASE_PUBLIC_URL'])
    cur = conn.cursor()

    # ---- Part A: target wrong-side -> direction-only ----
    cur.execute(f"""SELECT id,ticker,direction,target_price::float,window_days,entry_price::float,outcome
        FROM predictions
        WHERE source_type='youtube' AND target_price IS NOT NULL AND entry_price IS NOT NULL
          AND {SCORED}""")
    a_rows = cur.fetchall()
    a_ids = []
    for pid, tk, d, t, wd, ep, oc in a_rows:
        before = sanity_check_target(ep, t, wd)
        after = sanity_check_target(ep, t, wd, direction=d)
        if before is not None and after is None:
            a_ids.append((pid, oc, t))
    a_applied = 0
    for pid, oc, t in a_ids:
        cur.execute(f"""UPDATE predictions SET
              target_price=NULL, outcome='pending', evaluated_at=NULL,
              evaluation_summary='['||%s||' wrong-side target ->direction-only; [pre_remediation] target='||%s||' prior_outcome='||%s||'] '||COALESCE(evaluation_summary,'')
            WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'""",
            (TGT_MARK, str(t), oc, pid, TGT_MARK))
        a_applied += cur.rowcount
    # AVGO 631403 (pending) — null its bogus target too, traceable.
    cur.execute(f"""UPDATE predictions SET target_price=NULL,
          evaluation_summary='['||%s||' wrong-side target ->direction-only; [pre_remediation] target='||target_price::text||'] '||COALESCE(evaluation_summary,'')
        WHERE id=631403 AND target_price IS NOT NULL
          AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'""",
        (TGT_MARK, TGT_MARK))
    a_avgo = cur.rowcount

    # ---- Part B: confirmed pre-guard leaks ----
    cur.execute(f"""UPDATE predictions SET is_holding_disclosure=TRUE, outcome='unresolved', evaluated_at=NOW(),
          evaluation_summary='['||%s||' passive holding (shipped holding_guard re-run=HOLDING); [pre_remediation] prior_outcome='||outcome||'] '||COALESCE(evaluation_summary,'')
        WHERE id = ANY(%s) AND COALESCE(is_holding_disclosure,FALSE)=FALSE""",
        (HOLD_MARK, HOLDING_LEAKS))
    b_hold = cur.rowcount
    cur.execute(f"""UPDATE predictions SET is_weak_basket_call=TRUE,
          evaluation_summary='['||%s||' no-call narration (shipped rep_guard re-run=REJECT_NO_CALL); [pre_remediation] hidden] '||COALESCE(evaluation_summary,'')
        WHERE id = ANY(%s) AND COALESCE(is_weak_basket_call,FALSE)=FALSE""",
        (REP_MARK, REPNOCALL_LEAKS))
    b_rep = cur.rowcount

    conn.commit()
    print(f"Part A target wrong-side: candidates={len(a_ids)} applied={a_applied} | AVGO631403 nulled={a_avgo}")
    print(f"Part B leaks: holding={b_hold} (of {len(HOLDING_LEAKS)}) | weak_basket={b_rep} (of {len(REPNOCALL_LEAKS)})")
    # verify
    cur.execute("SELECT id,outcome,target_price,is_holding_disclosure,is_weak_basket_call FROM predictions WHERE id = ANY(%s) ORDER BY id",
                (HOLDING_LEAKS + REPNOCALL_LEAKS + [631403],))
    for r in cur.fetchall():
        print("  ", r)
    conn.close()


if __name__ == '__main__':
    main()
