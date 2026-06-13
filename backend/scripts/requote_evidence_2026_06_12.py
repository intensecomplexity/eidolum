"""Quote-representativeness re-quote (2026-06-12) — EVIDENCE ONLY.

Targets the precision cohort of scored, VISIBLE youtube_haiku_v1 ticker_call rows
whose displayed source_verbatim_quote was unrepresentative: either it read in the
OPPOSITE direction to the label, or it named neither the ticker nor any pronoun
anchor (orphan quote). A one-row-per-call claude -p Sonnet judge re-read each row's
transcript in a ±90s wide window and returned one of:

  REQUOTE           — the host DOES make the labeled call here; judge returned a
                      byte-exact transcript substring (validated in code). This
                      script swaps in that sentence as the new evidence and
                      re-resolves source_timestamp_seconds by substring->segment.
  DIRECTION_MISMATCH — the transcript shows the OPPOSITE direction or no call at
                      all. NOT mutated here — written to the committed review
                      artifact requote_review_direction_mismatch_2026_06_12.json
                      for human (Nimrod) adjudication. Only a human flips scoring.
  INSUFFICIENT       — transcript missing/ambiguous. Untouched.

HARD INVARIANT: this script NEVER changes outcome, direction, actual_return, or
evaluation_date. It only rewrites source_verbatim_quote + source_timestamp_seconds
(evidence) and appends a marker. Timestamps are never nulled; all cohort rows
already had a timestamp (they were visible), so a REQUOTE only ever moves it to the
new sentence's segment.

Idempotent (NOT LIKE marker guard). Transactional. Run manually against prod:
    DATABASE_PUBLIC_URL=... python3 backend/scripts/requote_evidence_2026_06_12.py
No stats refresh needed — no outcomes changed.
"""
import json
import os

import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'requote_results_2026_06_12.json')
MARKER = '[requote_2026_06_12'


def main():
    data = json.load(open(RESULTS))
    verdicts = data['verdicts']
    requote = {int(p): v for p, v in verdicts.items()
               if v['verdict'] == 'REQUOTE' and v.get('quote') and v.get('ts') is not None}
    print(f'REQUOTE rows with quote+ts: {len(requote)}')

    conn = psycopg2.connect(os.environ['DATABASE_PUBLIC_URL'])
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM predictions WHERE id = ANY(%s) "
        "AND COALESCE(evaluation_summary,'') NOT LIKE %s",
        (list(requote), f'%{MARKER}%'))
    todo = [r[0] for r in cur.fetchall()]
    updated = 0
    for pid in todo:
        v = requote[pid]
        cur.execute(
            """UPDATE predictions
               SET source_verbatim_quote = %s,
                   source_timestamp_seconds = %s,
                   source_timestamp_method = 'requote_2026_06_12',
                   evaluation_summary = COALESCE(evaluation_summary,'')
                       || ' [requote_2026_06_12 evidence-only: verbatim quote + timestamp replaced; outcome/direction/return UNCHANGED]'
               WHERE id = %s""",
            (v['quote'], int(v['ts']), pid))
        updated += cur.rowcount
    conn.commit()
    print(f'evidence updated: {updated}')
    cur.execute("SELECT count(*) FROM predictions WHERE evaluation_summary LIKE %s", (f'%{MARKER}%',))
    print(f'total rows carrying requote marker: {cur.fetchone()[0]}')
    conn.close()


if __name__ == '__main__':
    main()
