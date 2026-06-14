"""Conditional flat-scoring remediation — FULL TAIL (2026-06-14, run 2).

Continues remark_conditional_flatscored_2026_06_14.py (run 1, the macro/event-first
slice). This run judged ALL 964 remaining ticker_call conditional candidates
one-row-per-call (claude -p Sonnet, 0 failures): 109 event/macro (a) + 156
price-trigger (b) -> unresolved; 699 (c) genuine/rhetorical calls left untouched.

Same flag-not-delete pattern + marker conditional_remark_2026_06_14 (idempotent;
NOT LIKE guard). (b) rows tagged price_trigger_pending_routing. [pre_remediation]
JSON preserved inline.

Run:  DATABASE_PUBLIC_URL=... python3 backend/scripts/remark_conditional_flatscored_tail_2026_06_14.py
then refresh_all_forecaster_stats (server-side).
"""
import os, psycopg2

EVENT_MACRO = [
    605665, 605674, 605810, 605817, 605834, 605843, 605850, 605859, 605897, 605926,
    605934, 606221, 606240, 606252, 606456, 606468, 606589, 606668, 606765, 606846,
    606861, 607017, 607040, 607100, 607196, 607224, 607292, 607617, 608010, 608038,
    608039, 608040, 608041, 608049, 608064, 608083, 608085, 608304, 608409, 608561,
    608627, 608651, 608677, 608897, 608912, 608919, 609195, 609403, 609445, 610063,
    610069, 610089, 610350, 610356, 610585, 610598, 610600, 610658, 610712, 610899,
    610924, 611014, 611270, 612051, 612054, 612055, 612056, 612058, 612061, 612085,
    612086, 612150, 612152, 612278, 612280, 612374, 612720, 612831, 612844, 613743,
    614046, 614274, 614290, 614309, 614375, 614412, 614691, 614699, 614954, 614996,
    615048, 615066, 615926, 616129, 616278, 616411, 616484, 616685, 616704, 616859,
    616907, 617110, 617211, 619134, 619137, 623185, 624732, 624747, 631312,
]
PRICE_TRIGGER = [
    323134, 323181, 323182, 427048, 452509, 452510, 452511, 452519, 605827, 605838,
    605848, 605922, 605933, 605977, 606212, 606405, 606424, 606598, 606628, 606662,
    606663, 606727, 606740, 606849, 606857, 606870, 606906, 606914, 606944, 607008,
    607087, 607131, 607317, 607495, 607516, 607551, 607593, 607595, 607597, 607651,
    608035, 608036, 608073, 608076, 608223, 608560, 608828, 609012, 609050, 609103,
    609189, 609192, 609207, 609511, 609772, 609810, 610481, 610483, 610563, 610657,
    610831, 611088, 611324, 611413, 612081, 612114, 612123, 612124, 612211, 612566,
    612569, 612573, 612577, 612604, 612610, 612624, 612637, 612643, 612654, 612662,
    612663, 612667, 612668, 612671, 612684, 612809, 612873, 613007, 613117, 613120,
    613859, 613860, 613965, 613972, 613977, 614018, 614019, 614026, 614028, 614030,
    614034, 614043, 614194, 614222, 614223, 614273, 614321, 614516, 614591, 614850,
    614873, 614998, 615037, 615071, 615072, 615073, 615074, 615647, 615648, 615649,
    615650, 615651, 615653, 615654, 615655, 615657, 615659, 615660, 615661, 615662,
    615666, 616211, 616487, 616488, 616489, 616582, 616584, 616650, 616663, 619084,
    622746, 623763, 624013, 624978, 625654, 626240, 626548, 626848, 627184, 628558,
    628653, 628782, 628785, 628795, 629536, 630442,
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
        print(tag[:55],'->',cur.rowcount,'/',len(ids)); total+=cur.rowcount
    conn.commit()
    cur.execute("SELECT count(*) FROM predictions WHERE evaluation_summary LIKE '%conditional_remark_2026_06_14%'")
    print('re-marked this run:',total,'; cohort rows tagged (cumulative):',cur.fetchone()[0])
    conn.close()

if __name__=='__main__':
    main()
