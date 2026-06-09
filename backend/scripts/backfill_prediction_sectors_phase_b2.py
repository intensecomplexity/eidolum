"""
backfill_prediction_sectors_phase_b2.py — Phase B Round 2 (finishes the
predictions.sector reconciliation).

Two apply groups, per Nimrod's 2026-06-10 sign-off:

OVERRIDES (11 tickers): the ticker's REFERENCE rows are wrong, so the
hand-verified TICKER_SECTOR_OVERRIDES map (jobs/sector_lookup.py) is the
truth. For these we correct BOTH:
  - ticker_sectors.sector (the reference row — /api/sectors buckets by
    it at read time; _cache_to_db + the override now keep it correct), and
  - predictions.sector (the per-row stamp).

CLUSTERS (13 tickers): reference is correct, stamps drifted. Cross-check
derived reference target == cluster target before writing; mismatch ->
skip + flag.

LEFT UNTOUCHED (permanent/flagged): ETFs (writer guards them), LB
(ticker reuse), LTC (crypto-equity collision), the packaging group
(Morningstar ambiguity), everything else unseen. Residual printed at end.

Idempotent; per-ticker UPDATE with lock_timeout, commit each.

Run: DATABASE_PUBLIC_URL=postgres://... python backend/scripts/backfill_prediction_sectors_phase_b2.py
"""
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.sector import display_sector  # noqa: E402
from crypto_prices import is_crypto  # noqa: E402
from jobs.sector_lookup import TICKER_SECTOR_OVERRIDES  # noqa: E402

CLUSTERS = {
    "ANET": "Technology", "CSCO": "Technology", "CIEN": "Technology",
    "FFIV": "Technology", "MSI": "Technology",
    "PTCT": "Healthcare", "ALNY": "Healthcare", "EXAS": "Healthcare",
    "NBIX": "Healthcare", "ACAD": "Healthcare", "MYGN": "Healthcare",
    "NTLA": "Healthcare", "ARGX": "Healthcare",
}


def derived_target(cur, ticker):
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

    print("── OVERRIDES (reference rows corrected + rows re-stamped) ──")
    print(f"{'ticker':<8} {'target':<24} {'old ticker_sectors':<36} preds_updated")
    for ticker, target in TICKER_SECTOR_OVERRIDES.items():
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
        print(f"{ticker:<8} {target:<24} {old_ref:<36} {n}")
        time.sleep(0.1)

    print("\n── CLUSTERS (reference correct, stamps reconciled) ──")
    print(f"{'ticker':<8} {'target':<24} {'derived':<24} preds_updated")
    for ticker, target in CLUSTERS.items():
        d = derived_target(cur, ticker)
        if d != target:
            flagged.append((ticker, target, d))
            print(f"{ticker:<8} {target:<24} {d:<24} SKIPPED — derived mismatch")
            continue
        cur.execute(
            "UPDATE predictions SET sector = %s "
            "WHERE ticker = %s AND sector IS DISTINCT FROM %s",
            (target, ticker, target))
        n = cur.rowcount
        conn.commit()
        total += n
        print(f"{ticker:<8} {target:<24} {d:<24} {n}")
        time.sleep(0.1)

    print(f"\nRound 2 applied: {total:,} prediction rows; "
          f"flagged: {flagged or 'none'}")

    # Final residual — deliberately untouched.
    cur.execute("SELECT ticker, sector FROM ticker_sectors")
    ts_map = dict(cur.fetchall())
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
    rows = []
    for tick, stamped, n in cur.fetchall():
        t = tgt(tick)
        if t == "Other" or stamped == t:
            continue
        if display_sector(stamped) in ("Other", t):
            continue
        rows.append((tick, n, stamped, t, bool(etf_map.get(tick))))
    rows.sort(key=lambda r: -r[1])
    etf_rows = sum(r[1] for r in rows if r[4])
    print(f"\nFINAL RESIDUAL (untouched): {sum(r[1] for r in rows):,} rows, "
          f"{len({r[0] for r in rows})} tickers (ETF rows: {etf_rows:,})")
    print(f"{'ticker':<9} {'rows':>5}  {'stamped':<30} {'target':<24} flag")
    for tick, n, stamped, t, etf in rows:
        flag = "ETF" if etf else ("CRYPTO-COLLISION" if is_crypto(tick) else "-")
        print(f"{tick:<9} {n:>5}  {stamped:<30} {t:<24} {flag}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
