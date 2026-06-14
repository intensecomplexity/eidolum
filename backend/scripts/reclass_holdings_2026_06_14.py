"""Holdings reclassification backfill (2026-06-14). Hide passive holding
disclosures: set is_holding_disclosure=TRUE (hidden via hedged_filter_sql bundle,
kill switch HIDE_HOLDING_DISCLOSURES) + outcome='unresolved' (off the accuracy
board). LLM-judged per row (HOLDING vs CALL vs OTHER); only HOLDING ids here.
CALL/OTHER untouched. flag-not-delete, idempotent (marker guard), [pre_remediation]
saved. Requires migration 0022 (is_holding_disclosure column). Run:
  DATABASE_PUBLIC_URL=... python3 backend/scripts/reclass_holdings_2026_06_14.py
then refresh_all_forecaster_stats.
"""
import json, os, psycopg2
MARKER='holding_reclass_2026_06_14'
HOLDING_IDS = [
    452236, 605707, 606362, 606422, 606575, 606581, 606582, 606618, 606619, 606625,
    606708, 606739, 606784, 606798, 606843, 606923, 607000, 607033, 607041, 607077,
    607167, 607168, 607225, 607228, 607248, 607269, 607279, 607295, 607425, 607426,
    607447, 607454, 607525, 607658, 607659, 607661, 607662, 607672, 607673, 607717,
    607857, 607916, 607964, 608121, 608337, 608340, 608353, 608369, 608373, 608376,
    608439, 608445, 608462, 608480, 608532, 608608, 609116, 609223, 609319, 609322,
    609412, 609469, 609646, 609967, 609990, 610435, 610436, 610489, 610492, 610808,
    610900, 610917, 610937, 610943, 611000, 611142, 612127, 612762, 612834, 612838,
    612922, 613738, 613744, 613756, 613786, 613787, 613788, 613967, 614269, 614280,
    614403, 616229, 616802, 624820, 625399, 627682,
]
SCORED=('hit','correct','near','miss','incorrect')
def main():
    conn=psycopg2.connect(os.environ['DATABASE_PUBLIC_URL']);cur=conn.cursor()
    cur.execute("""UPDATE predictions SET is_holding_disclosure=TRUE, outcome='unresolved',
        evaluation_summary='['||%s||'] passive holding disclosure -> hidden + off scoreboard. '
          ||'[pre_remediation] '||json_build_object('direction',direction,'outcome',outcome,
             'actual_return',actual_return,'is_holding_disclosure',is_holding_disclosure)::text
          ||' | prior: '||COALESCE(evaluation_summary,'(none)'), evaluated_at=NOW()
        WHERE id=ANY(%s) AND outcome IN %s
          AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'""",
        (MARKER, HOLDING_IDS, SCORED, MARKER))
    print('reclassed (scored->unresolved+hidden):', cur.rowcount)
    # any HOLDING rows not in scored set: just flag hidden (no outcome change)
    cur.execute("""UPDATE predictions SET is_holding_disclosure=TRUE,
        evaluation_summary='['||%s||'] passive holding disclosure -> hidden. | prior: '||COALESCE(evaluation_summary,'(none)')
        WHERE id=ANY(%s) AND outcome NOT IN %s AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'""",
        (MARKER, HOLDING_IDS, SCORED, MARKER))
    print('flagged (non-scored):', cur.rowcount)
    conn.commit()
    cur.execute("SELECT count(*) FROM predictions WHERE is_holding_disclosure=TRUE")
    print('total is_holding_disclosure=TRUE:', cur.fetchone()[0])
    conn.close()
if __name__=='__main__': main()
