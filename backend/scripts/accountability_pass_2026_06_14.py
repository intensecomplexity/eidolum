"""Quote-accountability population pass — apply step (2026-06-14).

Reads the per-row accountability verdicts (SELF / REQUOTE_FIXABLE / NOT_ACCOUNTABLE)
produced by the cohort judge over visible-scored youtube/x ticker_call rows, and
applies the two actions (SELF + UNHEALABLE untouched):

  REQUOTE_FIXABLE -> EVIDENCE ONLY: source_verbatim_quote = the byte-exact claim
    sentence (already validated as a transcript substring by the judge) + resolve
    source_timestamp_seconds from the segment containing it. NEVER touch
    outcome/direction/actual_return; never null a timestamp (keep the old one if
    the sentence can't be located). marker requote_accountability_2026_06_14.

  NOT_ACCOUNTABLE -> is_no_claim=TRUE (hidden via hedged_filter_sql bundle, kill
    switch HIDE_NO_CLAIM) + outcome='unresolved' (off the accuracy board).
    [pre_remediation] JSON saved. marker noclaim_2026_06_14.

flag-not-delete, idempotent (NOT LIKE marker guard), never deletes. Requires
migration 0023 (is_no_claim). Reads cached timed transcripts from /tmp/heal/timed.
Run:  DATABASE_PUBLIC_URL=... python3 backend/scripts/accountability_pass_2026_06_14.py <verdicts.json> <cohort.json>
then refresh_all_forecaster_stats.
"""
import json, os, re, sys
import psycopg2

VP = sys.argv[1] if len(sys.argv) > 1 else '/tmp/acct_cohort_verdicts.json'
COH = sys.argv[2] if len(sys.argv) > 2 else '/tmp/acct_cohort.json'
RQ_MARK = 'requote_accountability_2026_06_14'
RQ_METHOD = 'requote_acct_2026_06_14'  # source_timestamp_method is varchar(32)
NC_MARK = 'noclaim_2026_06_14'


def norm(s): return re.sub(r'\s+', ' ', (s or '').lower()).strip()


def resolve_ts(vid, claim):
    """Return seconds of the segment containing the claim sentence, or None."""
    p = f'/tmp/heal/timed/{vid}.json'
    if not vid or not os.path.exists(p):
        return None
    segs = json.load(open(p)).get('segments', [])
    nc = norm(claim)
    if len(nc) < 15:
        return None
    # find the segment whose text (with a small forward window) contains the claim start
    parts, offs, pos = [], [], 0
    for s in segs:
        t = (s.get('text') or '').strip()
        if not t:
            continue
        parts.append(t)
        offs.append((pos, pos + len(t), int(s.get('start_ms') or 0)))
        pos += len(t) + 1
    full = norm(' '.join(parts))
    i = full.find(nc[:60])
    if i < 0:
        return None
    for a, b, ms in offs:
        if a <= i < b + 1:
            return ms // 1000
    return None


def main():
    verdicts = json.load(open(VP))
    cohort = {str(r['id']): r for r in json.load(open(COH))}
    conn = psycopg2.connect(os.environ['DATABASE_PUBLIC_URL'])
    cur = conn.cursor()
    rq = nc = rq_ts = 0
    for pid, v in verdicts.items():
        r = cohort.get(pid)
        if not r:
            continue
        verdict = v.get('verdict')
        if verdict == 'REQUOTE_FIXABLE' and v.get('claim'):
            claim = v['claim'].strip()[:2000]
            ts = resolve_ts(r.get('transcript_video_id'), v['claim'])
            if ts is not None:
                cur.execute("""UPDATE predictions SET source_verbatim_quote=%s,
                    source_timestamp_seconds=%s, source_timestamp_method=%s,
                    evaluation_summary='['||%s||' evidence-only: claim quote+ts; outcome/direction UNCHANGED] '||COALESCE(evaluation_summary,'')
                    WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'""",
                    (claim, ts, RQ_METHOD, RQ_MARK, int(pid), RQ_MARK))
                rq_ts += 1
            else:
                cur.execute("""UPDATE predictions SET source_verbatim_quote=%s,
                    evaluation_summary='['||%s||' evidence-only: claim quote (ts unresolved, kept)] '||COALESCE(evaluation_summary,'')
                    WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'""",
                    (claim, RQ_MARK, int(pid), RQ_MARK))
            rq += cur.rowcount
        elif verdict == 'NOT_ACCOUNTABLE':
            cur.execute("""UPDATE predictions SET is_no_claim=TRUE, outcome='unresolved',
                evaluation_summary='['||%s||'] no claim-bearing sentence in window -> hidden + off scoreboard. '
                  ||'[pre_remediation] '||json_build_object('direction',direction,'outcome',outcome,
                     'actual_return',actual_return)::text||' | prior: '||COALESCE(evaluation_summary,'(none)'),
                evaluated_at=NOW()
                WHERE id=%s AND outcome IN ('hit','correct','near','miss','incorrect')
                  AND COALESCE(evaluation_summary,'') NOT LIKE '%%'||%s||'%%'""",
                (NC_MARK, int(pid), NC_MARK))
            nc += cur.rowcount
    conn.commit()
    print(f"REQUOTE applied: {rq} (ts resolved: {rq_ts}); NOT_ACCOUNTABLE hidden: {nc}")
    cur.execute("SELECT count(*) FROM predictions WHERE is_no_claim=TRUE")
    print("total is_no_claim=TRUE:", cur.fetchone()[0])
    conn.close()


if __name__ == '__main__':
    main()
