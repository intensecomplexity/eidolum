"""
backfill_prediction_sectors_phase_b.py — Phase B (ALLOWLIST ONLY) of the
predictions.sector reconciliation.

Applies the Nimrod-approved subset of the 127-ticker contradiction class
(rows stamped with a DIFFERENT informative sector than the ticker's
canonical). Everything not in ALLOWLIST is printed, never touched —
including all ETFs (company_profiles.is_etf), crypto (guarded to 'Crypto'
already), and the flagged bad-reference tickers (TMO, PFG, Z, ZG, COTY,
ADM, ETSY, AKAM, WCC, MRNA, CNK, LB).

Safety: per-ticker UPDATE (largest is META at ~741 rows), lock_timeout,
commit per ticker, idempotent (sector IS DISTINCT FROM target). Before
updating, each ticker's reference-derived target is cross-checked against
the allowlist target — mismatch -> skip + flag, no write.

Run: DATABASE_PUBLIC_URL=postgres://... python backend/scripts/backfill_prediction_sectors_phase_b.py
"""
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.sector import display_sector  # noqa: E402
from crypto_prices import is_crypto  # noqa: E402

ALLOWLIST = {
    "META": "Communication Services",
    "GOOGL": "Communication Services",
    "GOOG": "Communication Services",
    "DG": "Consumer Defensive",
    "COST": "Consumer Defensive",
    "TGT": "Consumer Defensive",
    "UBER": "Industrials",
    "MCD": "Consumer Cyclical",
    "DHI": "Consumer Cyclical",
    "LEN": "Consumer Cyclical",
    "TOL": "Consumer Cyclical",
    "KBH": "Consumer Cyclical",
    "MTH": "Consumer Cyclical",
    "SRPT": "Healthcare",
    "VRTX": "Healthcare",
    "INCY": "Healthcare",
    "GILD": "Healthcare",
    "AMGN": "Healthcare",
    "COHR": "Technology",
}


def derived_target(cur, ticker: str):
    if is_crypto(ticker):
        return "Crypto"
    cur.execute("SELECT sector FROM ticker_sectors WHERE ticker = %s", (ticker,))
    row = cur.fetchone()
    d = display_sector(row[0] if row else None)
    if d == "Other":
        cur.execute("SELECT sector FROM company_profiles WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
        d = display_sector(row[0] if row else None)
    return d


def main():
    dsn = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: set DATABASE_PUBLIC_URL")
        sys.exit(1)
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET lock_timeout = '5s'")
    cur.execute("SET statement_timeout = '60s'")
    conn.commit()

    total = 0
    flagged = []
    print(f"{'ticker':<8} {'target':<24} {'derived':<24} rows_updated")
    for ticker, target in ALLOWLIST.items():
        d = derived_target(cur, ticker)
        if d != target:
            flagged.append((ticker, target, d))
            print(f"{ticker:<8} {target:<24} {d:<24} SKIPPED — derived target mismatch")
            continue
        if is_crypto(ticker):
            flagged.append((ticker, target, "Crypto"))
            print(f"{ticker:<8} {target:<24} {'Crypto':<24} SKIPPED — crypto guard")
            continue
        cur.execute(
            "UPDATE predictions SET sector = %s "
            "WHERE ticker = %s AND sector IS DISTINCT FROM %s",
            (target, ticker, target),
        )
        n = cur.rowcount
        conn.commit()
        total += n
        print(f"{ticker:<8} {target:<24} {d:<24} {n}")
        time.sleep(0.1)

    print(f"\nPhase B applied: {total:,} rows across {len(ALLOWLIST) - len(flagged)} tickers; "
          f"{len(flagged)} skipped/flagged: {flagged or 'none'}")

    # Remaining UNAPPLIED contradiction tail, with is_etf flag — review only.
    cur.execute("SELECT ticker, sector FROM ticker_sectors")
    ts_map = dict(cur.fetchall())
    cur.execute("SELECT ticker, sector FROM company_profiles WHERE sector IS NOT NULL")
    cp_map = dict(cur.fetchall())
    cur.execute("SELECT ticker, is_etf FROM company_profiles")
    etf_map = dict(cur.fetchall())

    def tgt(t):
        if is_crypto(t):
            return "Crypto"
        d = display_sector(ts_map.get(t))
        if d == "Other":
            d = display_sector(cp_map.get(t))
        return d

    cur.execute("SELECT ticker, sector, COUNT(*) FROM predictions "
                "WHERE sector IS NOT NULL GROUP BY 1, 2")
    rows = []
    for tick, stamped, n in cur.fetchall():
        t = tgt(tick)
        if t in ("Other",) or stamped == t:
            continue
        if display_sector(stamped) in ("Other", t):
            continue  # Phase-A class (junk) — none should remain
        rows.append((tick, n, stamped, t, bool(etf_map.get(tick))))
    rows.sort(key=lambda r: -r[1])
    print(f"\nUNAPPLIED contradiction tail: {sum(r[1] for r in rows):,} rows, "
          f"{len({r[0] for r in rows})} tickers")
    print(f"{'ticker':<9} {'rows':>5}  {'stamped':<30} {'target':<24} is_etf")
    for tick, n, stamped, t, etf in rows:
        crypto = " [CRYPTO]" if is_crypto(tick) else ""
        print(f"{tick:<9} {n:>5}  {stamped:<30} {t:<24} {'ETF' if etf else '-'}{crypto}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
