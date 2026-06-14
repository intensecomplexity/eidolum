"""Backfill: correct historical analyst rows where a BULLISH/BEARISH rating was
stored direction='neutral' (the old "Maintains/Reiterates Buy -> neutral" bug;
QA audit 2026-06-14, f11eb2e). HISTORICAL BACKFILL ONLY — forward writer behavior
is unchanged (reaffirmation-skip preserved by product decision); the invariant is
locked by backend/tests/test_rating_direction_invariant.py.

Mislabel signal (0 ambiguous in sizing): source_type='article', direction='neutral',
context carries the rating-derived label ': Bullish —' or ': Bearish —' (which
diverges from the stored neutral direction). Genuine neutrals (': Neutral —' /
hold-family) are NEVER touched.

Per row:
  - correct direction from the context label;
  - save [pre_remediation] {direction, outcome, actual_return, alpha, sp500_return,
    evaluation_date} so it is fully reversible;
  - SCORED rows: RE-EVALUATE through the evaluator's OWN ticker_call scoring branch
    (sanity_check_target / classify / bounded_return / tolerances / _calc_spy_return
    / _build_summary) using the row's stored entry_price as ref and price_bars
    (price_store.get_history) for eval_price — same entry_price/window/price path,
    no hand-rolled outcome. If price_bars can't price the eval date, the row is set
    to outcome='pending' (the evaluator re-scores it later via its full cascade).
  - PENDING/unscored rows: set the corrected direction only (evaluator scores later).
Marker maintains_direction_fix_2026_06_14. Idempotent (NOT LIKE marker guard).
flag-not-delete; never deletes. Run ON THE WORKER (price_bars + evaluator helpers):
  DATABASE_PUBLIC_URL=... python3 fix_maintains_direction_2026_06_14.py
then refresh_all_forecaster_stats.
"""
import json, os
import psycopg2
import sys
for p in ('/app/backend', '/app', '/home/nimroddd/quantanalytics/backend'):
    if p not in sys.path:
        sys.path.insert(0, p)

MARKER = 'maintains_direction_fix_2026_06_14'
SCORED = ('hit', 'correct', 'near', 'miss', 'incorrect')


def main():
    from jobs.historical_evaluator import (
        _closest_price, _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _calc_spy_return, _build_summary)
    from services.target_sanity import sanity_check_target
    from services.direction_classifier import classify as classify_direction
    from services.eval_caps import bounded_return
    from services import price_store

    conn = psycopg2.connect(os.environ.get('DATABASE_PUBLIC_URL') or os.environ['DATABASE_URL'])
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, ticker, outcome, actual_return, alpha, sp500_return, evaluation_date,
               prediction_date, window_days, entry_price, target_price,
               (context ~ ': Bullish —') AS is_bull
        FROM predictions
        WHERE source_type='article' AND direction='neutral'
          AND (context ~ ': Bullish —' OR context ~ ': Bearish —')
          AND COALESCE(evaluation_summary,'') NOT LIKE '%{MARKER}%'
    """)
    cols = ['id', 'ticker', 'outcome', 'actual_return', 'alpha', 'sp500_return', 'evaluation_date',
            'prediction_date', 'window_days', 'entry_price', 'target_price', 'is_bull']
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    print(f"mislabeled rows to fix: {len(rows)}")

    # group by ticker for one price fetch each
    from collections import defaultdict
    byt = defaultdict(list)
    for r in rows:
        byt[r['ticker']].append(r)

    rescored = pending_only = no_price = 0
    counts = {'miss->hit': 0, 'hit->miss': 0, 'near->': 0, 'other': 0}
    for i, (ticker, group) in enumerate(byt.items()):
        pds = [g['prediction_date'] for g in group if g['prediction_date']]
        start = (min(pds).date() if pds else None)
        hist = price_store.get_history(ticker, start, __import__('datetime').date.today()) if start else {}
        for r in group:
            new_dir = 'bullish' if r['is_bull'] else 'bearish'
            pre = json.dumps({'direction': 'neutral', 'outcome': r['outcome'],
                              'actual_return': float(r['actual_return']) if r['actual_return'] is not None else None,
                              'alpha': float(r['alpha']) if r['alpha'] is not None else None,
                              'sp500_return': float(r['sp500_return']) if r['sp500_return'] is not None else None,
                              'evaluation_date': str(r['evaluation_date']) if r['evaluation_date'] else None})
            tagpre = f"[{MARKER}={new_dir}] [pre_remediation] {pre} | prior: "
            scored = r['outcome'] in SCORED
            ref = float(r['entry_price']) if r['entry_price'] else None
            eval_price = _closest_price(hist, r['evaluation_date']) if hist else None
            if scored and ref and ref > 0 and eval_price:
                window = r['window_days'] or 90
                target = sanity_check_target(ref, float(r['target_price']) if r['target_price'] else None, window)
                direction = classify_direction(new_dir, entry_price=ref, target_price=target) or new_dir
                raw_move = round(((eval_price - ref) / ref) * 100, 2)
                ret = -raw_move if direction == 'bearish' else raw_move
                ret = bounded_return(ret, window)
                tol = _get_tolerance(window, _TOLERANCE); mm = _get_tolerance(window, _MIN_MOVEMENT)
                if target and target > 0:
                    tdp = abs(eval_price - target) / target * 100
                    if direction == 'bullish':
                        outcome = 'hit' if (eval_price >= target or (tdp <= tol and raw_move >= 0)) else ('near' if raw_move >= mm else 'miss')
                    else:
                        outcome = 'hit' if (eval_price <= target or (tdp <= tol and raw_move <= 0)) else ('near' if raw_move <= -mm else 'miss')
                else:
                    outcome = ('hit' if eval_price > ref else 'miss') if direction == 'bullish' else ('hit' if eval_price < ref else 'miss')
                spy = _calc_spy_return(r['prediction_date'], r['evaluation_date'])
                alpha = round(ret - spy, 2) if spy is not None else None
                summ = _build_summary(ticker, direction, outcome, ref, eval_price, target, ret)
                cur.execute("""UPDATE predictions SET direction=%s, outcome=%s, actual_return=%s,
                    sp500_return=%s, alpha=%s, evaluation_summary=%s||COALESCE(evaluation_summary,''),
                    evaluated_at=NOW() WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE %s""",
                    (direction, outcome, ret, spy, alpha, summ + ' ' + tagpre, r['id'], f'%{MARKER}%'))
                rescored += 1
                key = f"{r['outcome']}->{outcome}"
                counts[key] = counts.get(key, 0) + 1
            elif scored:
                # corrected direction but cannot price eval -> let evaluator re-score later
                cur.execute("""UPDATE predictions SET direction=%s, outcome='pending', actual_return=NULL,
                    evaluation_summary=%s||COALESCE(evaluation_summary,'') WHERE id=%s
                    AND COALESCE(evaluation_summary,'') NOT LIKE %s""",
                    (new_dir, tagpre + '(no price_bars eval; requeued pending) ', r['id'], f'%{MARKER}%'))
                no_price += 1
            else:
                cur.execute("""UPDATE predictions SET direction=%s,
                    evaluation_summary=%s||COALESCE(evaluation_summary,'') WHERE id=%s
                    AND COALESCE(evaluation_summary,'') NOT LIKE %s""",
                    (new_dir, tagpre + '(was pending) ', r['id'], f'%{MARKER}%'))
                pending_only += 1
        if (i + 1) % 300 == 0:
            conn.commit(); print(f"  ...{i+1} tickers processed", flush=True)
    conn.commit()
    print(f"DONE rescored={rescored} pending_only={pending_only} no_price_requeued={no_price}")
    print(f"outcome changes: {counts}")
    conn.close()


if __name__ == '__main__':
    main()
