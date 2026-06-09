"""
backfill_prediction_sectors_phase_b5.py — Round 5: flagged-tail closeout.

Applies the 9 Round-5 TICKER_SECTOR_OVERRIDES (reference row corrected +
predictions re-stamped, idempotent, lock_timeout). Leaves ROP / ATI /
DASH / BTU untouched (ambiguous or already-correct stamps) — counts
printed. Final residual sweep must show 0 unexpected rows.

Run: DATABASE_PUBLIC_URL=postgres://... python backend/scripts/backfill_prediction_sectors_phase_b5.py
"""
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.sector import display_sector  # noqa: E402
from crypto_prices import is_crypto  # noqa: E402
from jobs.sector_lookup import TICKER_SECTOR_OVERRIDES  # noqa: E402

ROUND5 = ["GRPN", "IAC", "RBLX", "TWLO", "FISV", "GPN", "KMT", "TREX", "AWI"]
LEAVE_AMBIGUOUS = {"ROP", "ATI", "DASH", "BTU"}
LEAVE_REUSE = {"LB", "APC"}


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

    print(f"{'ticker':<8} {'target':<24} {'old reference':<30} rows")
    total = 0
    for t in ROUND5:
        target = TICKER_SECTOR_OVERRIDES[t]
        cur.execute("SELECT sector FROM ticker_sectors WHERE ticker = %s", (t,))
        row = cur.fetchone()
        old = row[0] if row else "<no row>"
        if row is not None:
            cur.execute(
                "UPDATE ticker_sectors SET sector = %s "
                "WHERE ticker = %s AND sector IS DISTINCT FROM %s",
                (target, t, target))
        cur.execute(
            "UPDATE predictions SET sector = %s "
            "WHERE ticker = %s AND sector IS DISTINCT FROM %s",
            (target, t, target))
        n = cur.rowcount
        conn.commit()
        total += n
        print(f"{t:<8} {target:<24} {str(old)[:29]:<30} {n}")
        time.sleep(0.1)
    print(f"\nRound 5 applied: {total:,} rows")

    # Residual sweep.
    cur.execute("SELECT ticker, sector FROM ticker_sectors")
    ts_map = dict(cur.fetchall())
    cur.execute("SELECT ticker, sector FROM company_profiles WHERE sector IS NOT NULL")
    cp_map = dict(cur.fetchall())
    cur.execute("SELECT ticker, is_etf FROM company_profiles")
    etf_map = dict(cur.fetchall())

    def derived(t):
        if t in TICKER_SECTOR_OVERRIDES:
            return TICKER_SECTOR_OVERRIDES[t]
        if is_crypto(t):
            return "Crypto"
        d = display_sector(ts_map.get(t))
        if d == "Other":
            d = display_sector(cp_map.get(t))
        return d

    cur.execute("SELECT ticker, sector, COUNT(*) FROM predictions "
                "WHERE sector IS NOT NULL GROUP BY 1, 2")
    etf_n = crypto_n = reuse_n = amb_n = other_n = 0
    unexpected = []
    for tick, stamped, n in cur.fetchall():
        t = derived(tick)
        if t == "Other" or stamped == t:
            continue
        if display_sector(stamped) in ("Other", t):
            continue
        if etf_map.get(tick):
            etf_n += n
        elif is_crypto(tick):
            crypto_n += n
        elif tick in LEAVE_REUSE:
            reuse_n += n
        elif tick in LEAVE_AMBIGUOUS:
            amb_n += n
        else:
            other_n += n
            unexpected.append((tick, stamped, t, n))
    print(f"\nFINAL RESIDUAL: ETF={etf_n:,}  crypto-collision={crypto_n:,}  "
          f"ticker-reuse(LB/APC)={reuse_n:,}  "
          f"ambiguous(ROP/ATI/DASH/BTU)={amb_n:,}  unexpected={other_n:,}")
    if unexpected:
        print("UNEXPECTED (should be empty):", unexpected)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
