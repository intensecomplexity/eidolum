"""
One-off data-repair: bound every prediction's actual_return to [-100, +window cap].

Two sources of impossible returns were found in a 2026-06-08 audit:
  - the 15-min evaluator stored RAW, unsigned, UNCLAMPED returns, so a winning
    bear call could read negative and an outlier could read thousands of %;
  - old rows carried a corrupted entry_price (a delayed/stale lookup), producing
    values like CASY -12071.6% or AMD +8037.2%.

Repair strategy (price_bars ONLY — no paid API calls):
  Tier A (recompute): if price_bars has a close near both the prediction_date
    (entry/ref) and the evaluation date, recompute the canonical P&L-frame
    return — direction-signed, then bounded via services.eval_caps.bounded_return
    — and re-lock entry_price to the price_bars close. Alpha is recomputed from
    the new return when sp500_return is present.
  Tier B (bound-only): if price_bars can't cover the row, leave entry_price as-is
    and simply bound the existing stored value into [-100, +window cap] so the
    impossible magnitude can never poison averages or reach the UI. Historical
    data is corrected/bounded, never deleted.

Bulk write via psycopg2.extras.execute_values with explicit ::type casts.

Usage:
  DATABASE_PUBLIC_URL=... python3 backend/scripts/fix_impossible_returns.py          # dry-run
  DATABASE_PUBLIC_URL=... python3 backend/scripts/fix_impossible_returns.py --commit  # write
"""
import os
import sys
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.eval_caps import bounded_return  # noqa: E402

COMMIT = "--commit" in sys.argv

# Per-window absolute cap, mirrored in SQL so the illegal-row filter matches
# services.eval_caps.max_return_pct exactly.
CAP_SQL = (
    "CASE WHEN COALESCE(window_days,90)<=30 THEN 50 "
    "WHEN window_days<=90 THEN 100 "
    "WHEN window_days<=180 THEN 150 ELSE 200 END"
)

SELECT_SQL = f"""
SELECT p.id, p.ticker, p.direction, COALESCE(p.window_days,90) AS wd,
       p.actual_return, p.entry_price, p.sp500_return,
       rb.close AS ref_close, eb.close AS eval_close
FROM predictions p
LEFT JOIN LATERAL (
    SELECT b.close FROM price_bars b
    WHERE b.ticker = p.ticker
      AND b.bar_date BETWEEN p.prediction_date::date - 10 AND p.prediction_date::date + 10
    ORDER BY abs(b.bar_date - p.prediction_date::date) LIMIT 1
) rb ON true
LEFT JOIN LATERAL (
    SELECT b.close FROM price_bars b
    WHERE b.ticker = p.ticker
      AND b.bar_date BETWEEN
          (COALESCE(p.evaluation_date, p.evaluated_at::date,
                    p.prediction_date::date + (COALESCE(p.window_days,90) || ' days')::interval)::date) - 10
          AND
          (COALESCE(p.evaluation_date, p.evaluated_at::date,
                    p.prediction_date::date + (COALESCE(p.window_days,90) || ' days')::interval)::date) + 10
    ORDER BY abs(b.bar_date -
          COALESCE(p.evaluation_date, p.evaluated_at::date,
                   p.prediction_date::date + (COALESCE(p.window_days,90) || ' days')::interval)::date) LIMIT 1
) eb ON true
WHERE p.actual_return IS NOT NULL
  AND (p.actual_return < -100 OR p.actual_return > {CAP_SQL})
"""

UPDATE_SQL = """
UPDATE predictions AS p SET
  actual_return = v.actual_return::numeric,
  entry_price   = v.entry_price::numeric,
  alpha         = v.alpha::numeric
FROM (VALUES %s) AS v(id, actual_return, entry_price, alpha)
WHERE p.id = v.id::bigint
"""


def main():
    url = os.environ["DATABASE_PUBLIC_URL"]
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute(SELECT_SQL)
    rows = cur.fetchall()
    print(f"illegal rows fetched: {len(rows)}")

    updates = []
    tier_a = tier_b = 0
    samples = []
    for (pid, ticker, direction, wd, old_ret, old_entry, sp500, ref_close, eval_close) in rows:
        if ref_close and eval_close and float(ref_close) > 0:
            ref = float(ref_close)
            raw_move = (float(eval_close) - ref) / ref * 100.0
            signed = -raw_move if direction == "bearish" else raw_move
            new_ret = round(bounded_return(signed, wd), 2)
            new_entry = round(ref, 2)
            tier_a += 1
            tier = "A"
        else:
            # Tier B: bound the existing value, keep entry_price.
            new_ret = round(bounded_return(float(old_ret), wd), 2)
            new_entry = float(old_entry) if old_entry is not None else None
            tier_b += 1
            tier = "B"
        new_alpha = round(new_ret - float(sp500), 2) if sp500 is not None else None
        updates.append((pid, new_ret, new_entry, new_alpha))
        if len(samples) < 12:
            samples.append((tier, ticker, direction, wd, old_ret, new_ret, old_entry, new_entry))

    print(f"Tier A (recompute from price_bars): {tier_a}")
    print(f"Tier B (bound-only, no price_bars): {tier_b}")
    print("samples (tier, ticker, dir, wd, old_ret -> new_ret, old_entry -> new_entry):")
    for s in samples:
        print("  ", s)

    # entry_price can be NULL for a Tier-B row that never had one; the UPDATE
    # keeps it NULL. Guard against feeding a NULL into ::numeric cleanly.
    if COMMIT:
        execute_values(cur, UPDATE_SQL, updates, template="(%s,%s,%s,%s)", page_size=5000)
        conn.commit()
        print(f"COMMITTED {len(updates)} rows")
    else:
        print(f"DRY-RUN — would update {len(updates)} rows (pass --commit to write)")
    conn.close()


if __name__ == "__main__":
    main()
