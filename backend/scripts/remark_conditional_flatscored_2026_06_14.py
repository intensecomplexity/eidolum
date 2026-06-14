"""Conditional flat-scoring remediation (2026-06-14) — the SPY "if countries find
a solution" class. Residual flat-scored conditionals the Phase-3/3b sweep missed:
explicit if/then calls whose realization is contingent on an unverified EVENT/MACRO
trigger (a) or a price/level trigger (b). Per-row claude -p Sonnet judged the
macro/event-first slice (117 rows: all non-ticker_call conditionals + the SPY
ticker_call 616645). 51 (a) + 4 (b) re-marked -> unresolved; 62 (c) genuine/
rhetorical calls left untouched.

FLAG-NOT-DELETE (phase3_remark_conditionals.sql pattern): outcome=unresolved drops
them from accuracy on every surface while keeping the row for audit. Original
{outcome, actual_return, evaluation_date} preserved inline as [pre_remediation] JSON.
Marker conditional_remark_2026_06_14. Idempotent (outcome-IN guard + NOT LIKE marker).
(b) rows also tagged price_trigger_pending_routing for a follow-up that re-routes
them through _process_conditional_calls (structured price/commodity trigger scoring).

Run:  DATABASE_PUBLIC_URL=... python3 backend/scripts/remark_conditional_flatscored_2026_06_14.py
then refresh_all_forecaster_stats (server-side).

NOTE: this judged the macro/event-first slice. The 964 ticker_call conditional
candidates (conditional clause present but typically embedded/rhetorical) are a
separate follow-up — see the ship report.
"""
import json, os, psycopg2

EVENT_MACRO = [
    610946, 610961, 611043, 611198, 611262, 611640, 611641, 611643, 611754, 612019,
    612074, 612138, 612432, 612503, 612541, 612721, 612740, 612814, 612842, 612843,
    612851, 613124, 613131, 613211, 613213, 613222, 613227, 614483, 614566, 614634,
    614638, 614779, 614838, 614921, 615118, 615119, 616313, 616314, 616369, 616385,
    616420, 616434, 616435, 616445, 616463, 616498, 616572, 616600, 616643, 616644,
    616645,
]
PRICE_TRIGGER = [
    611263, 611557, 612129, 614565,
]
SCORED = ('hit','correct','near','miss','incorrect')

SQL = """
UPDATE predictions
SET outcome='unresolved',
    evaluation_summary = %(tag)s || ' [pre_remediation] '
        || json_build_object('outcome',outcome,'actual_return',actual_return,
                             'evaluation_date',evaluation_date)::text
        || ' | prior: ' || COALESCE(evaluation_summary,'(none)'),
    evaluated_at = NOW()
WHERE id = ANY(%(ids)s) AND outcome IN %(scored)s
  AND COALESCE(evaluation_summary,'') NOT LIKE '%%conditional_remark_2026_06_14%%'
"""

def main():
    conn=psycopg2.connect(os.environ['DATABASE_PUBLIC_URL']); cur=conn.cursor(); total=0
    for tag, ids in (
        ('[conditional_remark_2026_06_14=event_macro] -> unresolved (unverified event/macro conditional)', EVENT_MACRO),
        ('[conditional_remark_2026_06_14=price_trigger_pending_routing] -> unresolved (price-trigger; re-route to _process_conditional_calls)', PRICE_TRIGGER),
    ):
        cur.execute(SQL, {'tag':tag,'ids':ids,'scored':SCORED})
        print(tag[:55], '->', cur.rowcount, '/', len(ids))
        total += cur.rowcount
    conn.commit()
    cur.execute("SELECT count(*) FROM predictions WHERE evaluation_summary LIKE '%conditional_remark_2026_06_14%'")
    print('total re-marked this run:', total, '; cohort rows tagged:', cur.fetchone()[0])
    conn.close()

if __name__=='__main__':
    main()
