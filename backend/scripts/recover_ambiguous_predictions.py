"""
recover_ambiguous_predictions.py — re-attribute & re-score the recoverable
is_ambiguous_symbol rows (2026-06-11 ship). Three phases:

  --prepare        Snapshot the 96 recovery rows (ETH 14 flagged + the 2
                   mislabeled May-2021 "Ethereum" analyst rows, SAND 34,
                   SOL 46), stamp their equity sector.
  --reset-pending  Reset them to outcome='pending' for re-evaluation.
                   RUN ONLY AFTER the worker is on the override build.
  --finalize       Clear is_ambiguous_symbol on rows that re-scored to a
                   real outcome; (re-)flag any that stayed no_data/pending.
                   Prints outcome deltas.

LB (173) / APC (165) / ARB (4) are NOT touched — no sourceable price
path (and the VSCO spin distorts LB) — they stay hidden by design.
"""
import json
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crypto_prices import EQUITY_ANALYST_SOURCES  # noqa: E402

SNAPSHOT = "/tmp/recover_snapshot.json"
EQ = sorted(EQUITY_ANALYST_SOURCES)

# ticker -> (row filter SQL, params, equity sector to stamp)
RECOVERY = {
    "ETH": ("ticker = 'ETH' AND verified_by = ANY(%s) AND prediction_date < '2021-08-16'",
            "Consumer Cyclical"),   # Ethan Allen (furniture)
    "SAND": ("ticker = 'SAND' AND verified_by = ANY(%s)", "Basic Materials"),
    "SOL": ("ticker = 'SOL' AND verified_by = ANY(%s)", "Industrials"),
}

REAL_OUTCOMES = ("hit", "near", "miss", "correct", "incorrect")


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


def phase_prepare():
    conn, cur = connect()
    snapshot = []
    for tick, (where, sector) in RECOVERY.items():
        cur.execute(
            f"UPDATE predictions SET sector = %s WHERE {where} "
            f"AND sector IS DISTINCT FROM %s", (sector, EQ, sector))
        stamped = cur.rowcount
        conn.commit()
        cur.execute(
            f"SELECT id, outcome, entry_price, actual_return, is_ambiguous_symbol "
            f"FROM predictions WHERE {where} ORDER BY id", (EQ,))
        rows = [{"id": r[0], "ticker": tick, "outcome": r[1],
                 "entry_price": float(r[2]) if r[2] is not None else None,
                 "actual_return": float(r[3]) if r[3] is not None else None,
                 "was_flagged": bool(r[4])}
                for r in cur.fetchall()]
        snapshot.extend(rows)
        outs = {}
        for r in rows:
            outs[r["outcome"]] = outs.get(r["outcome"], 0) + 1
        print(f"{tick:<5} rows={len(rows):<3} sector-stamped={stamped:<3} "
              f"old outcomes: {outs}")
        time.sleep(0.1)
    json.dump(snapshot, open(SNAPSHOT, "w"))
    print(f"snapshot: {SNAPSHOT} ({len(snapshot)} rows)")
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
    print(f"reset to pending: {cur.rowcount}/{len(ids)}")
    conn.commit()
    conn.close()


def phase_finalize():
    rows = json.load(open(SNAPSHOT))
    old = {r["id"]: r for r in rows}
    conn, cur = connect()
    cur.execute("""
        SELECT id, ticker, outcome, entry_price FROM predictions
        WHERE id = ANY(%s) ORDER BY ticker, id
    """, ([r["id"] for r in rows],))
    recovered, failed, deltas = [], [], {}
    for pid, tick, outcome, ep in cur.fetchall():
        o = old[pid]
        if outcome in REAL_OUTCOMES:
            recovered.append(pid)
            key = (tick, o["outcome"], outcome)
            deltas[key] = deltas.get(key, 0) + 1
        else:
            failed.append((pid, tick, outcome))
    cur.execute(
        "UPDATE predictions SET is_ambiguous_symbol = FALSE "
        "WHERE id = ANY(%s) AND is_ambiguous_symbol = TRUE", (recovered,))
    cleared = cur.rowcount
    fids = [f[0] for f in failed]
    flagged = 0
    if fids:
        cur.execute(
            "UPDATE predictions SET is_ambiguous_symbol = TRUE "
            "WHERE id = ANY(%s) AND is_ambiguous_symbol = FALSE", (fids,))
        flagged = cur.rowcount
    conn.commit()

    print(f"recovered (real outcome, flag cleared): {len(recovered)} "
          f"({cleared} had been flagged)")
    print(f"not recovered (stay/now hidden): {len(failed)} -> {failed or '[]'}")
    print(f"newly flagged failures: {flagged}")
    print(f"\n{'ticker':<6} {'old':<10} -> {'new':<10} n")
    for (t, o, n_), c in sorted(deltas.items(), key=lambda kv: (kv[0][0], -kv[1])):
        mark = "" if o == n_ else "  *"
        print(f"{t:<6} {str(o):<10} -> {n_:<10} {c}{mark}")
    conn.close()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--prepare"
    {"--prepare": phase_prepare, "--reset-pending": phase_reset,
     "--finalize": phase_finalize}[arg]()
