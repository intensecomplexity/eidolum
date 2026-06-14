"""Adjudicate the 40 DIRECTION_MISMATCH review rows (Nimrod-adjudicated 2026-06-12).

Source of truth: requote_review_direction_mismatch_2026_06_12.json (commit 3d18afd)
+ the disposition map below. RUN ON THE WORKER (hopeful-expression) so bucket A
re-scores through the real evaluator environment (price_bars + price cascade +
the evaluator's own helpers). Everything is id-pinned, idempotent, reversible.

Buckets:
  A  (6)  FLIP direction + RE-SCORE through the evaluator's own scoring path
          (_fetch_history / _closest_price / sanity_check_target / classify /
          bounded_return / tolerances / _calc_spy_return / _build_summary — the
          exact ticker_call branch from evaluate_batch, applied to one row, NO
          hand-computed outcome). marker adjudicated_2026_06_12=flip
  A' (2)  conditional buy-the-dip -> outcome='unresolved' (no flip).
          marker adjudicated_2026_06_12=conditional_unresolved
  B  (6)  third-party call -> is_reported_speech=TRUE (hidden via bundle).
          marker adjudicated_2026_06_12=reported_speech
  C  (25) no committed call / ticker absent -> outcome='unresolved' (phase3b).
          marker adjudicated_2026_06_12=no_call
  KEEP    614592 AVGO untouched.

Reversibility: every acted row gets a [pre_adjudication] JSON snapshot
(direction, outcome, actual_return, evaluation_date, is_reported_speech) embedded
in evaluation_summary AND echoed to the frozen results artifact.
Idempotent: skips any row already carrying 'adjudicated_2026_06_12'. Drift guard:
skips any row whose current (direction, outcome) no longer matches the artifact.
"""
import json
import os
import sys

for _p in ('/app/backend', '/app', '/home/nimroddd/quantanalytics/backend'):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import psycopg2

A = {606424: 'bullish', 606663: 'bullish', 609200: 'bearish',
     612643: 'bullish', 610663: 'bullish', 608944: 'bearish'}
Ap = [606412, 609272]
B = [605806, 613158, 607863, 613188, 614131, 614335]
C = [611044, 613851, 614701, 611013, 610972, 610789, 609419, 609000, 615010,
     608426, 616365, 610957, 614596, 614171, 609783, 608641, 614276, 608691,
     614198, 614292, 614463, 629269, 625650, 626649, 614584]

ART = {r['id']: r for r in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
       'requote_review_direction_mismatch_2026_06_12.json')))['rows']}


def pre_json(r):
    return json.dumps({'direction': r['direction'], 'outcome': r['outcome'],
                       'actual_return': float(r['actual_return']) if r['actual_return'] is not None else None,
                       'evaluation_date': str(r['evaluation_date']) if r['evaluation_date'] else None,
                       'is_reported_speech': r['is_reported_speech']})


def main():
    from jobs.historical_evaluator import (
        _fetch_history, _closest_price, _get_tolerance, _TOLERANCE, _MIN_MOVEMENT,
        _calc_spy_return, _build_summary,
    )
    from services.target_sanity import sanity_check_target
    from services.direction_classifier import classify as classify_direction
    from services.eval_caps import bounded_return

    conn = psycopg2.connect(os.environ.get('DATABASE_PUBLIC_URL') or os.environ['DATABASE_URL'])
    conn.autocommit = False
    cur = conn.cursor()
    results = {}

    def load(pid):
        cur.execute("""SELECT id,ticker,direction,outcome,actual_return,evaluation_date,
            is_reported_speech,COALESCE(evaluation_summary,''),target_price,entry_price,
            prediction_date,window_days,forecaster_id FROM predictions WHERE id=%s""", (pid,))
        row = cur.fetchone()
        if not row:
            return None
        keys = ['id', 'ticker', 'direction', 'outcome', 'actual_return', 'evaluation_date',
                'is_reported_speech', 'summary', 'target_price', 'entry_price',
                'prediction_date', 'window_days', 'forecaster_id']
        return dict(zip(keys, row))

    def guard(r, pid):
        a = ART[pid]
        if 'adjudicated_2026_06_12' in r['summary']:
            return 'already_marked'
        if r['direction'] != a['labeled_direction'] or r['outcome'] != a['current_outcome']:
            return f"drift db({r['direction']}/{r['outcome']}) vs art({a['labeled_direction']}/{a['current_outcome']})"
        return None

    # ── BUCKET A: flip + re-score via evaluator helpers ──────────────────
    for pid, new_dir in A.items():
        r = load(pid)
        g = guard(r, pid)
        if g:
            results[pid] = {'bucket': 'A', 'skipped': g}
            continue
        ticker = r['ticker']
        prices = _fetch_history(ticker, None, None)
        if not prices:
            results[pid] = {'bucket': 'A', 'skipped': 'no_prices'}
            continue
        eval_price = _closest_price(prices, r['evaluation_date'])
        historical_entry = _closest_price(prices, r['prediction_date'])
        ref = float(r['entry_price']) if r['entry_price'] else None
        if historical_entry and historical_entry > 0:
            if not ref or ref <= 0:
                ref = historical_entry
            elif abs(ref - historical_entry) / historical_entry > 0.02:
                ref = historical_entry
        if eval_price is None or not ref or ref <= 0:
            results[pid] = {'bucket': 'A', 'skipped': 'no_price_point'}
            continue
        target = sanity_check_target(ref, float(r['target_price']) if r['target_price'] else None, r['window_days'])
        direction = classify_direction(new_dir, entry_price=ref, target_price=target) or 'bullish'
        raw_move = round(((eval_price - ref) / ref) * 100, 2)
        ret = -raw_move if direction == 'bearish' else raw_move
        ret = bounded_return(ret, r['window_days'])
        window = r['window_days'] or 90
        tolerance = _get_tolerance(window, _TOLERANCE)
        min_movement = _get_tolerance(window, _MIN_MOVEMENT)
        if target and target > 0:
            target_dist_pct = abs(eval_price - target) / target * 100
            if direction == 'bullish':
                outcome = 'hit' if (eval_price >= target or (target_dist_pct <= tolerance and raw_move >= 0)) else ('near' if raw_move >= min_movement else 'miss')
            else:
                outcome = 'hit' if (eval_price <= target or (target_dist_pct <= tolerance and raw_move <= 0)) else ('near' if raw_move <= -min_movement else 'miss')
        else:
            if direction == 'bullish':
                outcome = 'hit' if eval_price > ref else 'miss'
            else:
                outcome = 'hit' if eval_price < ref else 'miss'
        spy_return = _calc_spy_return(r['prediction_date'], r['evaluation_date'])
        pred_alpha = round(ret - spy_return, 2) if spy_return is not None else None
        summary = _build_summary(ticker, direction, outcome, ref, eval_price, target, ret)
        new_summary = (f"{summary} [adjudicated_2026_06_12=flip] [pre_adjudication] {pre_json(r)} | prior: {r['summary']}")
        cur.execute("""UPDATE predictions SET direction=%s, outcome=%s, actual_return=%s,
            entry_price=%s, sp500_return=%s, alpha=%s, evaluation_summary=%s, evaluated_at=NOW()
            WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE '%%adjudicated_2026_06_12%%'""",
            (direction, outcome, ret, ref, spy_return, pred_alpha, new_summary, pid))
        results[pid] = {'bucket': 'A', 'ticker': ticker, 'fid': r['forecaster_id'],
                        'before': {'direction': r['direction'], 'outcome': r['outcome'], 'ret': float(r['actual_return']) if r['actual_return'] is not None else None},
                        'after': {'direction': direction, 'outcome': outcome, 'ret': ret}}

    # ── BUCKET A' + C: outcome -> unresolved (flag-not-delete) ───────────
    for pid in Ap + C:
        r = load(pid)
        g = guard(r, pid)
        if g:
            results[pid] = {'bucket': "A'" if pid in Ap else 'C', 'skipped': g}
            continue
        kind = 'conditional_unresolved' if pid in Ap else 'no_call'
        new_summary = (f"[adjudicated_2026_06_12={kind}] -> unresolved (excluded from accuracy). "
                       f"[pre_adjudication] {pre_json(r)} | prior: {r['summary']}")
        cur.execute("""UPDATE predictions SET outcome='unresolved', evaluation_summary=%s, evaluated_at=NOW()
            WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE '%%adjudicated_2026_06_12%%'""",
            (new_summary, pid))
        results[pid] = {'bucket': "A'" if pid in Ap else 'C', 'ticker': r['ticker'],
                        'fid': r['forecaster_id'], 'before': {'outcome': r['outcome']}, 'after': {'outcome': 'unresolved'}}

    # ── BUCKET B: is_reported_speech=TRUE (no direction/outcome change) ───
    for pid in B:
        r = load(pid)
        g = guard(r, pid)
        if g:
            results[pid] = {'bucket': 'B', 'skipped': g}
            continue
        new_summary = (f"[adjudicated_2026_06_12=reported_speech] hidden via bundle; outcome/direction unchanged. "
                       f"[pre_adjudication] {pre_json(r)} | prior: {r['summary']}")
        cur.execute("""UPDATE predictions SET is_reported_speech=TRUE, evaluation_summary=%s
            WHERE id=%s AND COALESCE(evaluation_summary,'') NOT LIKE '%%adjudicated_2026_06_12%%'""",
            (new_summary, pid))
        results[pid] = {'bucket': 'B', 'ticker': r['ticker'], 'fid': r['forecaster_id'],
                        'before': {'is_reported_speech': r['is_reported_speech']}, 'after': {'is_reported_speech': True}}

    conn.commit()
    conn.close()
    print('RESULTS_JSON_START')
    print(json.dumps(results))
    print('RESULTS_JSON_END')
    from collections import Counter
    acted = [k for k, v in results.items() if 'skipped' not in v]
    skipped = {k: v['skipped'] for k, v in results.items() if 'skipped' in v}
    print(f'acted: {len(acted)} | skipped: {len(skipped)} {skipped}')
    print('by bucket:', dict(Counter(v['bucket'] for v in results.values() if 'skipped' not in v)))


if __name__ == '__main__':
    main()
