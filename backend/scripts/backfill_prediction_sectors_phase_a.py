"""
backfill_prediction_sectors_phase_a.py — Phase A of the predictions.sector
cache reconciliation (2026-06-10 ship).

predictions.sector is a denormalized per-row stamp that drifted: 319K rows
NULL (never stamped), 135K stamped with raw SIC/'Other' junk. Phase A fills
ONLY those classes with the ticker's canonical sector:

    target = 'Crypto'              if is_crypto(ticker)   (crypto guard —
                                   BTC-style tickers have a BAD reference
                                   sector like 'Financial Services')
           = display_sector(ticker_sectors.sector,
                            fallback company_profiles.sector)

A row is Phase-A-updatable only when its CURRENT stamp carries no
information that contradicts the target:
    sector IS NULL
    OR display_sector(sector) == 'Other'        (junk/stray stamp)
    OR display_sector(sector) == target          (same meaning, raw spelling)
Rows stamped with a DIFFERENT informative sector (the 129-ticker
contradiction class) are NOT touched — that's Phase B, pending review.
Tickers with no informative target are left entirely alone.

Idempotent (WHERE sector IS DISTINCT FROM target + the class guard).
Batched by id-range chunks with lock_timeout so a chunk aborts rather than
stalls live traffic; COMMIT per chunk.

Run: DATABASE_PUBLIC_URL=postgres://... python backend/scripts/backfill_prediction_sectors_phase_a.py
"""
import os
import sys
import time

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.sector import display_sector  # noqa: E402
from crypto_prices import is_crypto  # noqa: E402

CHUNK_ID_SPAN = 25_000
SLEEP_BETWEEN_CHUNKS = 0.25
INFORMATIVE_RESIDUAL = "Other"


def build_target_map(cur) -> dict:
    cur.execute("SELECT DISTINCT ticker FROM predictions")
    pred_tickers = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT ticker, sector FROM ticker_sectors")
    ts_map = dict(cur.fetchall())
    cur.execute("SELECT ticker, sector FROM company_profiles WHERE sector IS NOT NULL")
    cp_map = dict(cur.fetchall())

    target = {}
    for t in pred_tickers:
        if is_crypto(t):
            target[t] = "Crypto"
            continue
        d = display_sector(ts_map.get(t))
        if d == INFORMATIVE_RESIDUAL:
            d = display_sector(cp_map.get(t))
        if d != INFORMATIVE_RESIDUAL:
            target[t] = d
    return target


def main():
    dsn = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: set DATABASE_PUBLIC_URL")
        sys.exit(1)

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET lock_timeout = '5s'")
    cur.execute("SET statement_timeout = '120s'")

    target = build_target_map(cur)
    print(f"informative targets for {len(target):,} prediction tickers "
          f"({sum(1 for t in target.values() if t == 'Crypto')} crypto-guarded)")

    # raw_canon: display canonical for every raw value currently stamped in
    # predictions.sector — drives the "is this stamp junk?" per-row test.
    cur.execute("SELECT DISTINCT sector FROM predictions WHERE sector IS NOT NULL")
    raw_canon = [(r[0], display_sector(r[0])) for r in cur.fetchall()]

    cur.execute("""
        CREATE TEMP TABLE ticker_target (
            ticker VARCHAR(20) PRIMARY KEY, target VARCHAR(40) NOT NULL)
    """)
    execute_values(cur, "INSERT INTO ticker_target (ticker, target) VALUES %s",
                   list(target.items()), page_size=5000)
    cur.execute("""
        CREATE TEMP TABLE raw_canon (
            raw TEXT PRIMARY KEY, canon VARCHAR(40) NOT NULL)
    """)
    execute_values(cur, "INSERT INTO raw_canon (raw, canon) VALUES %s",
                   raw_canon, page_size=1000)
    conn.commit()

    cur.execute("SELECT MIN(id), MAX(id) FROM predictions")
    lo, hi = cur.fetchone()
    print(f"id range {lo:,}..{hi:,}, chunk span {CHUNK_ID_SPAN:,}")

    UPDATE_SQL = """
        UPDATE predictions p
        SET sector = tt.target
        FROM ticker_target tt
        WHERE p.id BETWEEN %(lo)s AND %(hi)s
          AND p.ticker = tt.ticker
          AND p.sector IS DISTINCT FROM tt.target
          AND (
                p.sector IS NULL
                OR COALESCE((SELECT rc.canon FROM raw_canon rc
                             WHERE rc.raw = p.sector), 'Other')
                   IN ('Other', tt.target)
              )
    """

    total_updated = 0
    t0 = time.time()
    chunk_lo = lo
    while chunk_lo <= hi:
        chunk_hi = min(chunk_lo + CHUNK_ID_SPAN - 1, hi)
        for attempt in range(3):
            try:
                cur.execute(UPDATE_SQL, {"lo": chunk_lo, "hi": chunk_hi})
                n = cur.rowcount
                conn.commit()
                break
            except psycopg2.OperationalError as e:
                conn.rollback()
                print(f"  chunk {chunk_lo}-{chunk_hi} attempt {attempt+1} aborted "
                      f"({str(e).strip()[:80]}) — retrying", flush=True)
                time.sleep(2.0 * (attempt + 1))
        else:
            print(f"FATAL: chunk {chunk_lo}-{chunk_hi} failed 3x — stopping. "
                  f"Re-run resumes safely (idempotent).")
            sys.exit(2)
        total_updated += n
        if n:
            print(f"  ids {chunk_lo:>9,}-{chunk_hi:>9,}: {n:>6,} rows "
                  f"(total {total_updated:,})", flush=True)
        chunk_lo = chunk_hi + 1
        time.sleep(SLEEP_BETWEEN_CHUNKS)

    elapsed = time.time() - t0
    print(f"\nPhase A complete: {total_updated:,} rows updated in {elapsed:,.0f}s")

    # Reconciliation: Phase-A-eligible drifted rows remaining must be 0.
    cur.execute("""
        SELECT COUNT(*)
        FROM predictions p
        JOIN ticker_target tt ON tt.ticker = p.ticker
        WHERE p.sector IS DISTINCT FROM tt.target
          AND (p.sector IS NULL
               OR COALESCE((SELECT rc.canon FROM raw_canon rc
                            WHERE rc.raw = p.sector), 'Other')
                  IN ('Other', tt.target))
    """)
    remaining = cur.fetchone()[0]
    print(f"reconciliation: Phase-A-eligible drifted rows remaining = {remaining:,} "
          f"({'OK' if remaining == 0 else 'NOT CLEAN — investigate'})")

    # Phase B preview: the contradiction class, untouched by this script.
    cur.execute("""
        SELECT p.ticker, p.sector, tt.target, COUNT(*)
        FROM predictions p
        JOIN ticker_target tt ON tt.ticker = p.ticker
        JOIN raw_canon rc ON rc.raw = p.sector
        WHERE p.sector IS DISTINCT FROM tt.target
          AND rc.canon NOT IN ('Other', tt.target)
        GROUP BY p.ticker, p.sector, tt.target
        ORDER BY COUNT(*) DESC, p.ticker
    """)
    rows = cur.fetchall()
    n_tickers = len({r[0] for r in rows})
    n_rows = sum(r[3] for r in rows)
    print(f"\nPhase B contradiction class (UNTOUCHED): {n_rows:,} rows, "
          f"{n_tickers} tickers")
    print(f"{'ticker':<9} {'rows':>5}  {'stamped_sector':<28} -> target")
    for tick, stamped, tgt, n in rows:
        flag = " [CRYPTO-GUARDED]" if is_crypto(tick) else ""
        print(f"{tick:<9} {n:>5}  {stamped:<28} -> {tgt}{flag}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
