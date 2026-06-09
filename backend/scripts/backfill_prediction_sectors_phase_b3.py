"""
backfill_prediction_sectors_phase_b3.py — Round 3 of the sector
reconciliation.

PART A: apply the 13 new TICKER_SECTOR_OVERRIDES entries (solar trio +
TTD/MSTR -> Technology; packaging group -> Consumer Cyclical). Like
Round 2: correct the ticker_sectors reference row AND re-stamp
predictions rows. Idempotent, per-ticker, lock_timeout, commit each.

PART B: print the ENTIRE remaining unadjudicated tail — every ticker
still stamped differently from its reference-derived target that is NOT
an ETF / crypto-collision / LB — with company_name so bad references
are spottable. PRINT ONLY, never applied.

Run: DATABASE_PUBLIC_URL=postgres://... python backend/scripts/backfill_prediction_sectors_phase_b3.py
"""
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.sector import display_sector  # noqa: E402
from crypto_prices import is_crypto  # noqa: E402
from jobs.sector_lookup import TICKER_SECTOR_OVERRIDES  # noqa: E402

ROUND3 = ["FSLR", "SEDG", "ENPH", "TTD", "MSTR",
          "OI", "CCK", "PKG", "SEE", "SON", "IP", "SLGN", "GEF"]

LEAVE_TICKER_REUSE = {"LB"}


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

    print("── PART A: Round 3 overrides applied ──")
    print(f"{'ticker':<8} {'target':<20} {'old ticker_sectors':<30} preds_updated")
    total = 0
    for ticker in ROUND3:
        target = TICKER_SECTOR_OVERRIDES[ticker]  # KeyError = map not extended
        cur.execute("SELECT sector FROM ticker_sectors WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
        old_ref = row[0] if row else "<no row>"
        if row is not None:
            cur.execute(
                "UPDATE ticker_sectors SET sector = %s "
                "WHERE ticker = %s AND sector IS DISTINCT FROM %s",
                (target, ticker, target))
        cur.execute(
            "UPDATE predictions SET sector = %s "
            "WHERE ticker = %s AND sector IS DISTINCT FROM %s",
            (target, ticker, target))
        n = cur.rowcount
        conn.commit()
        total += n
        print(f"{ticker:<8} {target:<20} {old_ref:<30} {n}")
        time.sleep(0.1)
    print(f"\nPart A applied: {total:,} prediction rows across {len(ROUND3)} tickers")

    # ── PART B: full unadjudicated tail (print only) ──
    cur.execute("SELECT ticker, sector, company_name FROM ticker_sectors")
    ts_rows = cur.fetchall()
    ts_map = {r[0]: r[1] for r in ts_rows}
    name_map = {r[0]: r[2] for r in ts_rows if r[2]}
    cur.execute("SELECT ticker, sector, company_name FROM company_profiles")
    for t, sec, nm in cur.fetchall():
        if nm and t not in name_map:
            name_map[t] = nm
    cp_map = {}
    cur.execute("SELECT ticker, sector FROM company_profiles WHERE sector IS NOT NULL")
    cp_map = dict(cur.fetchall())
    cur.execute("SELECT ticker, is_etf FROM company_profiles")
    etf_map = dict(cur.fetchall())

    def tgt(t):
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
    tail, etf_count, crypto_count, reuse_count = [], 0, 0, 0
    for tick, stamped, n in cur.fetchall():
        t = tgt(tick)
        if t == "Other" or stamped == t:
            continue
        if display_sector(stamped) in ("Other", t):
            continue
        if etf_map.get(tick):
            etf_count += n
            continue
        if is_crypto(tick):
            crypto_count += n
            continue
        if tick in LEAVE_TICKER_REUSE:
            reuse_count += n
            continue
        tail.append((tick, name_map.get(tick) or "?", n, stamped, t))
    tail.sort(key=lambda r: -r[2])

    print(f"\n── PART B: unadjudicated tail (PRINT ONLY) — "
          f"{sum(r[2] for r in tail):,} rows, {len({r[0] for r in tail})} tickers ──")
    print(f"{'ticker':<8} {'company_name':<36} {'rows':>5}  "
          f"{'current_stamp':<28} reference_target")
    for tick, name, n, stamped, t in tail:
        print(f"{tick:<8} {name[:35]:<36} {n:>5}  {stamped:<28} {t}")

    print(f"\nLEFT UNTOUCHED: ETF rows={etf_count:,}; "
          f"crypto-collision rows (LTC/SOL/SAND/TRX)={crypto_count:,}; "
          f"LB ticker-reuse rows={reuse_count:,}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
