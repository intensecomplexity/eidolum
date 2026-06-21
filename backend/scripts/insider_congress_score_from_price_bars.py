#!/usr/bin/env python3
"""Score insider/congress directional predictions against the LOCAL price_bars
asset — zero external API calls.

This deliberately does NOT route through the live evaluator: that path calls
_fetch_history(ticker, None, None) which returns {} for a None range, skips the
21M-row price_bars cache, and hits LIVE FMP per row (the known evaluator-bypass
bug). Scoring 87k+ rows through it would be a cost bomb. Instead we JOIN each
prediction against price_bars directly in SQL (the Phase-5 entry_price recompute
pattern): entry = closest close to the transaction date (±10d), exit = closest
close to the +365d evaluation date (±5d), benchmark = SPY over the same window.

Scoring mirrors jobs/historical_evaluator for a no-target directional call:
  raw_move   = (exit-entry)/entry*100
  ret        = bounded_return(raw_move if bullish else -raw_move, 365d)
               (services.eval_caps — same caps the leaderboard + simulator use)
  three-tier : ret >= MIN_MOVE(365)=4%  -> hit   (clear move in the call's favor)
               0 < ret < 4%             -> near  (right direction, sub-threshold)
               ret <= 0                 -> miss  (flat or against)
  alpha      = round(ret - raw_SPY_move, 2)   (matches the evaluator's convention)
Window-closed rows with no price_bars coverage -> no_data (flag-not-delete).
Future-window rows stay 'pending' (re-run later once their +365d closes).

Idempotent + resumable: only scores source_type insider/congress rows still
'pending' with a closed window; commits per batch; cursor-pages by id.

Run:  DATABASE_PUBLIC_URL=postgres://... python backend/scripts/insider_congress_score_from_price_bars.py
"""
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # backend/
from services.eval_caps import bounded_return  # noqa: E402

DSN = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
if not DSN:
    print("ERROR: set DATABASE_PUBLIC_URL")
    sys.exit(1)

BATCH = 5000
# All inserted rows use window_days=365; MIN_MOVEMENT[365]=4 in the evaluator's
# _MIN_MOVEMENT table. Looked up per-row so this stays correct if a future run
# inserts other windows.
_MIN_MOVEMENT = {1: 0.5, 7: 1, 14: 1.5, 30: 2, 90: 2, 180: 3, 365: 4}


def min_move(window_days):
    try:
        n = int(round(float(window_days)))
    except (TypeError, ValueError):
        n = 365
    if n <= 0:
        n = 365
    for k in sorted(_MIN_MOVEMENT):
        if n <= k:
            return _MIN_MOVEMENT[k]
    return _MIN_MOVEMENT[max(_MIN_MOVEMENT)]


SELECT_SQL = """
    SELECT p.id, p.ticker, p.direction, p.window_days,
           p.prediction_date, p.evaluation_date,
           (SELECT pb.close FROM price_bars pb
             WHERE pb.ticker = p.ticker
               AND pb.bar_date BETWEEN p.prediction_date::date - 10
                                   AND p.prediction_date::date + 10
             ORDER BY ABS(pb.bar_date - p.prediction_date::date) LIMIT 1) AS entry,
           (SELECT pb.close FROM price_bars pb
             WHERE pb.ticker = p.ticker
               AND pb.bar_date BETWEEN p.evaluation_date::date - 5
                                   AND p.evaluation_date::date + 5
             ORDER BY ABS(pb.bar_date - p.evaluation_date::date) LIMIT 1) AS exitp,
           (SELECT pb.close FROM price_bars pb
             WHERE pb.ticker = 'SPY'
               AND pb.bar_date BETWEEN p.prediction_date::date - 10
                                   AND p.prediction_date::date + 10
             ORDER BY ABS(pb.bar_date - p.prediction_date::date) LIMIT 1) AS spy_entry,
           (SELECT pb.close FROM price_bars pb
             WHERE pb.ticker = 'SPY'
               AND pb.bar_date BETWEEN p.evaluation_date::date - 5
                                   AND p.evaluation_date::date + 5
             ORDER BY ABS(pb.bar_date - p.evaluation_date::date) LIMIT 1) AS spy_exit
    FROM predictions p
    WHERE p.source_type IN ('insider','congress')
      AND (p.outcome = 'pending' OR p.outcome IS NULL OR p.outcome = '')
      AND p.evaluation_date <= CURRENT_DATE
      AND p.id > %s
    ORDER BY p.id
    LIMIT %s
"""

UPDATE_SQL = """
    UPDATE predictions p SET
        entry_price = v.ep::numeric,
        actual_return = v.ret::numeric,
        outcome = v.outcome::text,
        sp500_return = v.spy::numeric,
        alpha = v.alpha::numeric,
        evaluation_summary = v.summary::text,
        evaluated_at = NOW()
    FROM (VALUES %s) AS v(id, ep, ret, outcome, spy, alpha, summary)
    WHERE p.id = v.id::int
"""


def main():
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()

    last_id = 0
    scored = no_data = 0
    buckets = {"hit": 0, "near": 0, "miss": 0}

    while True:
        cur.execute(SELECT_SQL, (last_id, BATCH))
        rows = cur.fetchall()
        if not rows:
            break

        updates = []  # (id, ep, ret, outcome, spy, alpha, summary)
        for (pid, ticker, direction, window_days, pdate, edate,
             entry, exitp, spy_entry, spy_exit) in rows:
            last_id = pid
            if entry is None or exitp is None or float(entry) <= 0:
                # window closed but no usable price coverage -> no_data
                updates.append((pid, None, None, "no_data", None, None,
                                f"{ticker} {direction}: no price_bars coverage in window"))
                no_data += 1
                continue
            entry_f, exit_f = float(entry), float(exitp)
            raw_move = round((exit_f - entry_f) / entry_f * 100, 2)
            signed = raw_move if direction == "bullish" else -raw_move
            ret = bounded_return(signed, window_days)

            mv = min_move(window_days)
            if ret >= mv:
                outcome = "hit"
            elif ret > 0:
                outcome = "near"
            else:
                outcome = "miss"
            buckets[outcome] += 1

            spy_return = None
            alpha = None
            if spy_entry is not None and spy_exit is not None and float(spy_entry) > 0:
                spy_return = round((float(spy_exit) - float(spy_entry)) / float(spy_entry) * 100, 2)
                alpha = round(ret - spy_return, 2)

            summary = (f"{ticker} {direction}: ${entry_f:,.2f} -> ${exit_f:,.2f} "
                       f"({ret:+.1f}%) [{outcome}]")
            updates.append((pid, entry_f, ret, outcome, spy_return, alpha, summary))
            scored += 1

        execute_values(
            cur, UPDATE_SQL, updates,
            template="(%s::int, %s::numeric, %s::numeric, %s::text, %s::numeric, %s::numeric, %s::text)",
            page_size=5000,
        )
        conn.commit()
        print(f"  batch -> last_id={last_id}  scored={scored}  no_data={no_data}  "
              f"(hit={buckets['hit']} near={buckets['near']} miss={buckets['miss']})")

    # Final tallies (whole insider/congress population, all-time)
    cur.execute("""
        SELECT source_type, outcome, COUNT(*)
        FROM predictions WHERE source_type IN ('insider','congress')
        GROUP BY source_type, outcome ORDER BY source_type, outcome
    """)
    print("=== insider_congress_score_from_price_bars ===")
    print(f"this run: scored={scored} (hit={buckets['hit']} near={buckets['near']} "
          f"miss={buckets['miss']}), no_data={no_data}")
    print("population outcome distribution:")
    for st, oc, n in cur.fetchall():
        print(f"  {st:9} {str(oc):9} {n}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
