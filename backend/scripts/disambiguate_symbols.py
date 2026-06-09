"""
disambiguate_symbols.py — one-off backfill for the 2026-06-10 symbol
disambiguation ship. Three phases (idempotent, lock_timeout'd):

  --flag           Apply the column DDL; flag is_ambiguous_symbol on the
                   unattributable classes; re-stamp active-equity
                   collision analyst rows' sector; snapshot the rows
                   slated for re-evaluation to /tmp/reeval_snapshot.json.
  --reset-pending  Reset the snapshot rows to outcome='pending' so the
                   evaluator re-scores them against the EQUITY price.
                   RUN ONLY AFTER the worker is on the source-aware
                   build, or they'll re-score against the coin again.
  --report-deltas  Compare current outcomes vs the snapshot.

Classes flagged (see crypto_prices.py for the maps):
  ticker reuse:        LB < 2021-08-02 (L Brands), APC all (Anadarko),
                       ARB analyst rows (Arbitron)
  dead-equity crypto:  SOL/SAND analyst rows (Emeren/Sandstorm — equity
                       gone), ETH analyst rows < 2020 (Ethan Allen era)
ETH analyst rows from 2021 (coin-priced, ~$3,485 entries) stay Ethereum —
NOT flagged, NOT re-stamped (the documented exception).

Re-evaluated (active equities only): LTC, BCH, TRX, ATOM analyst rows.
"""
import json
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crypto_prices import EQUITY_ANALYST_SOURCES  # noqa: E402

SNAPSHOT = "/tmp/reeval_snapshot.json"
EQ = sorted(EQUITY_ANALYST_SOURCES)
ACTIVE_EQUITY = {"LTC": "Real Estate", "BCH": "Financial Services",
                 "TRX": "Basic Materials", "ATOM": "Technology"}

FLAG_SETS = [
    ("LB stale era (L Brands)",
     "ticker = 'LB' AND prediction_date < '2021-08-02'", []),
    ("APC all (Anadarko)", "ticker = 'APC'", []),
    ("ARB analyst rows (Arbitron)",
     "ticker = 'ARB' AND verified_by = ANY(%s)", [EQ]),
    ("SOL analyst rows (Emeren, delisted)",
     "ticker = 'SOL' AND verified_by = ANY(%s)", [EQ]),
    ("SAND analyst rows (Sandstorm, acquired)",
     "ticker = 'SAND' AND verified_by = ANY(%s)", [EQ]),
    ("ETH analyst rows < 2020 (Ethan Allen era)",
     "ticker = 'ETH' AND verified_by = ANY(%s) AND prediction_date < '2020-01-01'", [EQ]),
]


def connect():
    dsn = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: set DATABASE_PUBLIC_URL")
        sys.exit(1)
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET lock_timeout = '5s'")
    cur.execute("SET statement_timeout = '120s'")
    conn.commit()
    return conn, cur


def phase_flag():
    conn, cur = connect()
    # The ALTER needs a brief ACCESS EXCLUSIVE lock; scraper transactions
    # hold ACCESS SHARE for tens of seconds at a time. Retry with the
    # short 5s lock_timeout until we land in a gap — each failed attempt
    # stalls other queries at most 5s, never a long pileup.
    for attempt in range(60):
        try:
            cur.execute("""
                ALTER TABLE predictions
                  ADD COLUMN IF NOT EXISTS is_ambiguous_symbol BOOLEAN NOT NULL DEFAULT FALSE
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS ix_predictions_is_ambiguous_symbol
                  ON predictions (is_ambiguous_symbol) WHERE is_ambiguous_symbol = TRUE
            """)
            conn.commit()
            break
        except psycopg2.OperationalError:
            conn.rollback()
            print(f"  DDL attempt {attempt + 1}: lock busy, retrying...", flush=True)
            time.sleep(4)
    else:
        print("FATAL: could not acquire DDL lock in 60 attempts")
        sys.exit(2)
    print("column + partial index ready")

    print("\n── flagging unattributable classes ──")
    total = 0
    for label, where, params in FLAG_SETS:
        cur.execute(
            f"UPDATE predictions SET is_ambiguous_symbol = TRUE "
            f"WHERE {where} AND is_ambiguous_symbol = FALSE", params)
        n = cur.rowcount
        conn.commit()
        total += n
        print(f"  {label:<42} flagged {n}")
        time.sleep(0.1)
    print(f"total flagged: {total}")

    print("\n── re-stamping active-equity collision analyst rows ──")
    for tick, sector in ACTIVE_EQUITY.items():
        cur.execute(
            "UPDATE predictions SET sector = %s "
            "WHERE ticker = %s AND verified_by = ANY(%s) "
            "AND sector IS DISTINCT FROM %s",
            (sector, tick, EQ, sector))
        print(f"  {tick:<6} -> {sector:<20} re-stamped {cur.rowcount}")
        conn.commit()
        time.sleep(0.1)

    print("\n── snapshotting re-eval rows (active equities, scored) ──")
    cur.execute("""
        SELECT id, ticker, outcome, entry_price, actual_return
        FROM predictions
        WHERE ticker = ANY(%s) AND verified_by = ANY(%s)
          AND outcome NOT IN ('pending') AND outcome IS NOT NULL
        ORDER BY ticker, id
    """, (list(ACTIVE_EQUITY), EQ))
    rows = [{"id": r[0], "ticker": r[1], "outcome": r[2],
             "entry_price": float(r[3]) if r[3] is not None else None,
             "actual_return": float(r[4]) if r[4] is not None else None}
            for r in cur.fetchall()]
    json.dump(rows, open(SNAPSHOT, "w"))
    by = {}
    for r in rows:
        by.setdefault(r["ticker"], []).append(r)
    for t, rs in sorted(by.items()):
        outs = {}
        for r in rs:
            outs[r["outcome"]] = outs.get(r["outcome"], 0) + 1
        print(f"  {t:<6} {len(rs)} scored rows to re-eval; outcomes now: {outs}")
    print(f"snapshot: {SNAPSHOT} ({len(rows)} rows)")
    conn.close()


def phase_reset():
    rows = json.load(open(SNAPSHOT))
    ids = [r["id"] for r in rows]
    conn, cur = connect()
    cur.execute("""
        UPDATE predictions
        SET outcome = 'pending', entry_price = NULL, actual_return = NULL,
            evaluation_summary = NULL, sp500_return = NULL, alpha = NULL,
            evaluated_at = NULL
        WHERE id = ANY(%s)
    """, (ids,))
    print(f"reset to pending: {cur.rowcount} rows (of {len(ids)} snapshot)")
    conn.commit()
    conn.close()


def phase_report():
    rows = json.load(open(SNAPSHOT))
    old = {r["id"]: r for r in rows}
    conn, cur = connect()
    cur.execute("""
        SELECT id, ticker, outcome, entry_price, actual_return
        FROM predictions WHERE id = ANY(%s) ORDER BY ticker, id
    """, ([r["id"] for r in rows],))
    pending = changed = same = 0
    deltas = {}
    for pid, tick, outcome, ep, ar in cur.fetchall():
        o = old[pid]
        if outcome == 'pending':
            pending += 1
            continue
        key = (tick, o["outcome"], outcome)
        deltas[key] = deltas.get(key, 0) + 1
        if o["outcome"] != outcome:
            changed += 1
        else:
            same += 1
    print(f"re-evaluated: {changed + same} (changed={changed}, same={same}); "
          f"still pending: {pending}")
    print(f"{'ticker':<7} {'old':<10} -> {'new':<10} n")
    for (t, o, n_), c in sorted(deltas.items(), key=lambda kv: (kv[0][0], -kv[1])):
        mark = "" if o == n_ else "  *"
        print(f"{t:<7} {o:<10} -> {n_:<10} {c}{mark}")
    conn.close()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--flag"
    {"--flag": phase_flag, "--reset-pending": phase_reset,
     "--report-deltas": phase_report}[arg]()
