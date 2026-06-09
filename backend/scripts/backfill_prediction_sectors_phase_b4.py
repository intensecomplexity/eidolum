"""
backfill_prediction_sectors_phase_b4.py — Round 4 (FINAL) of the sector
reconciliation. Closes the equity tail.

PART A: 7 new TICKER_SECTOR_OVERRIDES (bad references proven wrong by
company identity). Reference row corrected + rows re-stamped.

PART B: 14 clean-reference tickers re-stamped to their reference-derived
target (cross-checked against the expected target; mismatch -> skip+flag).

PART C: sweep of the remaining tail — apply the reference target where
company identity supports it; SKIP + FLAG where the company name
contradicts the reference (the SWK/TMO pattern) or the symbol is reused.

LEAVE permanently: ETFs, crypto-collisions (LTC/SOL/SAND/TRX), LB, APC
(ARKO/Anadarko ticker reuse). Counts printed.

Run: DATABASE_PUBLIC_URL=postgres://... python backend/scripts/backfill_prediction_sectors_phase_b4.py
"""
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.sector import display_sector  # noqa: E402
from crypto_prices import is_crypto  # noqa: E402
from jobs.sector_lookup import TICKER_SECTOR_OVERRIDES  # noqa: E402

ROUND4_OVERRIDES = ["SWK", "MTN", "PLNT", "GME", "LYB", "SPWR", "RUN"]

PART_B = {
    "XYZ": "Technology", "LYFT": "Technology", "PAYC": "Technology",
    "PCTY": "Technology", "DV": "Technology",
    "TRIP": "Consumer Cyclical",
    "ETN": "Industrials", "EMR": "Industrials", "ROK": "Industrials",
    "GLW": "Industrials",
    "VMC": "Basic Materials", "MLM": "Basic Materials",
    "APLS": "Healthcare", "UTHR": "Healthcare",
}

# PART C sweep judgments. APPLY: company identity supports the reference
# target. FLAG: company identity contradicts it (SWK/TMO pattern) — skip,
# print for review.
PART_C_APPLY = {
    "MHK": "Consumer Cyclical",   # Mohawk Industries — flooring
    "FIS": "Technology",          # Fidelity National Info Services — fintech software
    "SSYS": "Technology",         # Stratasys — 3D printing
    "DDD": "Technology",          # 3D Systems
    "TEL": "Technology",          # TE Connectivity — electronic components
    "GNRC": "Industrials",        # Generac — machinery
    "BE": "Industrials",          # Bloom Energy
    "SYY": "Consumer Defensive",  # Sysco — food distribution
    "DLTR": "Consumer Defensive", # Dollar Tree
    "INFN": "Technology",         # Infinera — optical networking
}
PART_C_FLAG = {
    "GRPN": "Groupon is a consumer marketplace (ETSY-override pattern), ref says Communication Services",
    "IAC": "IAC = internet content (Comm Services in Morningstar), ref says Technology",
    "TWLO": "Twilio = software infrastructure (Technology in Morningstar), ref says Comm Services",
    "KMT": "Kennametal = industrial tooling (Industrials), ref says Basic Materials",
    "DASH": "DoorDash = internet retail (Consumer Cyclical), ref says Comm Services",
    "BTU": "Peabody = thermal coal (Morningstar Energy; current stamp Energy looks right), ref says Basic Materials",
    "TREX": "Trex = building products (Industrials), ref says Basic Materials",
    "AWI": "Armstrong World = building products (Industrials), ref says Basic Materials",
    "ATI": "ATI specialty alloys — Industrials/Materials ambiguous",
    "FISV": "Fiserv = fintech software (Technology), ref says Industrials",
    "RBLX": "Roblox = gaming/multimedia (Comm Services; current stamp looks right), ref says Technology",
    "ROP": "Roper = application software (Technology in Morningstar), ref says Industrials",
    "GPN": "Global Payments — processor classification ambiguous, ref says Industrials",
}
LEAVE = {"LB", "APC"}  # ticker reuse (L Brands/LandBridge, Anadarko/ARKO)


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

    def restamp(ticker, target, fix_reference=False):
        if fix_reference:
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
        time.sleep(0.1)
        return n

    total = 0
    print("── PART A: Round 4 overrides ──")
    print(f"{'ticker':<8} {'target':<20} {'old reference':<26} rows")
    for t in ROUND4_OVERRIDES:
        target = TICKER_SECTOR_OVERRIDES[t]
        old = ts_map.get(t, "<no row>")
        n = restamp(t, target, fix_reference=True)
        total += n
        print(f"{t:<8} {target:<20} {str(old)[:25]:<26} {n}")

    print("\n── PART B: clean-reference applies ──")
    print(f"{'ticker':<8} {'target':<20} {'derived':<20} rows")
    flagged_b = []
    for t, target in PART_B.items():
        d = derived(t)
        if d != target:
            flagged_b.append((t, target, d))
            print(f"{t:<8} {target:<20} {d:<20} SKIPPED — derived mismatch")
            continue
        n = restamp(t, target)
        total += n
        print(f"{t:<8} {target:<20} {d:<20} {n}")

    print("\n── PART C: tail sweep ──")
    print(f"{'ticker':<8} {'target':<20} {'derived':<20} rows")
    flagged_c = []
    for t, target in PART_C_APPLY.items():
        d = derived(t)
        if d != target:
            flagged_c.append((t, target, f"derived mismatch ({d})"))
            print(f"{t:<8} {target:<20} {d:<20} SKIPPED — derived mismatch")
            continue
        n = restamp(t, target)
        total += n
        print(f"{t:<8} {target:<20} {d:<20} {n}")

    print("\nFLAGGED FOR REVIEW (not applied):")
    for t, reason in PART_C_FLAG.items():
        print(f"  {t:<6} — {reason}")
    if flagged_b or flagged_c:
        print(f"  cross-check skips: {flagged_b + flagged_c}")

    print(f"\nTotal rows applied this round: {total:,}")

    # Final residual.
    cur.execute("SELECT ticker, sector, COUNT(*) FROM predictions "
                "WHERE sector IS NOT NULL GROUP BY 1, 2")
    etf_n = crypto_n = reuse_n = flag_n = other_n = 0
    other_rows = []
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
        elif tick in LEAVE:
            reuse_n += n
        elif tick in PART_C_FLAG:
            flag_n += n
        else:
            other_n += n
            other_rows.append((tick, stamped, t, n))
    print(f"\nFINAL RESIDUAL: ETF={etf_n:,}  crypto-collision={crypto_n:,}  "
          f"ticker-reuse(LB/APC)={reuse_n:,}  flagged-for-review={flag_n:,}  "
          f"unexpected-other={other_n:,}")
    if other_rows:
        print("UNEXPECTED (should be empty):", other_rows)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
