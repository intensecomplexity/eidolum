"""FMP macro harvest — commodities, forex majors, economic indicators,
treasury rates. Persist-once / keep-forever before any FMP downgrade.

NEW local tables (created here, IF NOT EXISTS — run manually as owner via
DATABASE_PUBLIC_URL; RUN_STARTUP_DDL is false in prod so app boot won't make
them):
  fmp_commodities(symbol,date)            EOD OHLCV for the ~40 futures
  fmp_forex(symbol,date)                  EOD OHLCV for the FX majors
  fmp_economic_indicators(name,date)      US macro series (GDP/CPI/rates/...)
  fmp_treasury_rates(date)                full yield curve, daily

Idempotent: psycopg2.extras.execute_values + ON CONFLICT DO UPDATE,
page_size=5000, dedup-by-PK first (avoids CardinalityViolation). Reusable as
the daily incremental — re-running upserts the latest rows. Storage-guarded:
aborts before any feed if the DB would pass ~38GB (40GB volume cap).

Usage: DATABASE_PUBLIC_URL=... FMP_KEY=... python3 backend/scripts/harvest_fmp_macro.py
"""
import io, json, os, sys, time, urllib.request, urllib.parse
import psycopg2
from psycopg2.extras import execute_values

DBURL = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
KEY = os.environ.get("FMP_KEY")
if not DBURL or not KEY:
    sys.exit("need DATABASE_PUBLIC_URL + FMP_KEY")
BASE = "https://financialmodelingprep.com/stable/"
SOFT_CAP_GB = 38.0

FOREX_MAJORS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "EURCHF", "AUDJPY", "CHFJPY", "EURAUD",
    "EURCAD", "GBPAUD", "USDCNH", "USDMXN", "USDSGD", "USDHKD",
]
ECON = [
    "GDP", "realGDP", "nominalPotentialGDP", "realGDPPerCapita", "federalFunds",
    "CPI", "inflationRate", "inflation", "retailSales", "consumerSentiment",
    "durableGoods", "unemploymentRate", "totalNonfarmPayroll", "initialClaims",
    "industrialProductionTotalIndex",
    "newPrivatelyOwnedHousingUnitsStartedTotalUnits", "totalVehicleSales",
    "retailMoneyFunds", "smoothedUSRecessionProbabilities",
    "30YearFixedRateMortgageAverage", "15YearFixedRateMortgageAverage",
    "commercialBankInterestRateOnCreditCardPlansAllAccounts",
    "3MonthOr90DayRatesAndYieldsCertificatesOfDeposit",
]


def _get(path, params):
    params = dict(params or {}); params["apikey"] = KEY
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == 3:
                print(f"  ! {path} {params.get('symbol') or params.get('name','')}: {e}", flush=True)
                return []
            time.sleep(1.5 * (attempt + 1))
    return []


def _num(v):
    try:
        if v in (None, "", "null"):
            return None
        return float(v)
    except Exception:
        return None


def size_gb(cur):
    cur.execute("SELECT pg_database_size(current_database())")
    return cur.fetchone()[0] / 1e9


def table_mb(cur, t):
    cur.execute("SELECT pg_total_relation_size(%s)", (t,))
    return (cur.fetchone()[0] or 0) / 1e6


def guard(cur, label):
    sz = size_gb(cur)
    print(f"[guard] DB {sz:.2f} GB (headroom to {SOFT_CAP_GB:.0f}GB: {SOFT_CAP_GB - sz:.2f} GB) before {label}", flush=True)
    if sz >= SOFT_CAP_GB:
        sys.exit(f"STORAGE GUARD: {sz:.2f}GB >= {SOFT_CAP_GB}GB soft cap — aborting before {label}")


def bulk_upsert(cur, table, cols, pk_cols, rows):
    if not rows:
        return 0
    # dedup by PK (last wins) to avoid ON CONFLICT cardinality violation
    pk_idx = [cols.index(c) for c in pk_cols]
    by_pk = {tuple(r[i] for i in pk_idx): r for r in rows}
    deduped = list(by_pk.values())
    set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pk_cols)
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
           f"ON CONFLICT ({', '.join(pk_cols)}) DO UPDATE SET {set_clause}")
    execute_values(cur, sql, deduped, page_size=5000)
    return len(deduped)


def _eod_full_history(symbol):
    """Backward-paginate historical-price-eod/full until exhausted (API caps
    ~5000 rows/call). Returns all rows."""
    out, to = [], "2026-12-31"
    seen_oldest = None
    for _ in range(12):  # 12*5000 = 60k cap guard
        rows = _get("historical-price-eod/full", {"symbol": symbol, "from": "1970-01-01", "to": to})
        if not rows:
            break
        out.extend(rows)
        oldest = min(r["date"] for r in rows)
        if oldest == seen_oldest or len(rows) < 4900:
            break
        seen_oldest = oldest
        # next window ends the day before the current oldest
        y, m, d = (int(x) for x in oldest.split("-"))
        import datetime
        to = (datetime.date(y, m, d) - datetime.timedelta(days=1)).isoformat()
    return out


def harvest_eod(cur, conn, table, symbols, source):
    guard(cur, table)
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
        symbol VARCHAR(16) NOT NULL, date DATE NOT NULL,
        open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
        volume BIGINT, change NUMERIC, change_percent NUMERIC, vwap NUMERIC,
        source VARCHAR(16) NOT NULL DEFAULT '{source}',
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (symbol, date))""")
    conn.commit()
    cols = ["symbol", "date", "open", "high", "low", "close", "volume",
            "change", "change_percent", "vwap"]
    total = 0
    for i, sym in enumerate(symbols, 1):
        rows = _eod_full_history(sym)
        recs = []
        for r in rows:
            vol = r.get("volume")
            recs.append((sym, r["date"], _num(r.get("open")), _num(r.get("high")),
                         _num(r.get("low")), _num(r.get("close")),
                         int(vol) if vol not in (None, "", "null") else None,
                         _num(r.get("change")), _num(r.get("changePercent")),
                         _num(r.get("vwap"))))
        n = bulk_upsert(cur, table, cols, ["symbol", "date"], recs)
        conn.commit()
        total += n
        print(f"  [{i}/{len(symbols)}] {sym}: +{n} (total {total})", flush=True)
    print(f"[done] {table}: {total} rows, {table_mb(cur, table):.1f} MB", flush=True)
    return total


def harvest_economic(cur, conn):
    guard(cur, "fmp_economic_indicators")
    cur.execute("""CREATE TABLE IF NOT EXISTS fmp_economic_indicators (
        name VARCHAR(80) NOT NULL, date DATE NOT NULL, value NUMERIC,
        source VARCHAR(16) NOT NULL DEFAULT 'fmp',
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (name, date))""")
    conn.commit()
    cols = ["name", "date", "value"]
    total = 0
    for nm in ECON:
        rows = _get("economic-indicators", {"name": nm, "from": "1960-01-01", "to": "2026-12-31"})
        recs = [(r["name"], r["date"], _num(r.get("value"))) for r in rows if r.get("date")]
        n = bulk_upsert(cur, "fmp_economic_indicators", cols, ["name", "date"], recs)
        conn.commit(); total += n
        print(f"  {nm}: +{n}", flush=True)
    print(f"[done] fmp_economic_indicators: {total} rows, {table_mb(cur,'fmp_economic_indicators'):.1f} MB", flush=True)
    return total


def harvest_treasury(cur, conn):
    guard(cur, "fmp_treasury_rates")
    tenors = ["month1", "month2", "month3", "month6", "year1", "year2",
              "year3", "year5", "year7", "year10", "year20", "year30"]
    cur.execute("CREATE TABLE IF NOT EXISTS fmp_treasury_rates (date DATE PRIMARY KEY, "
                + ", ".join(f"{t} NUMERIC" for t in tenors)
                + ", source VARCHAR(16) NOT NULL DEFAULT 'fmp', fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
    conn.commit()
    cols = ["date"] + tenors
    out, to = [], "2026-12-31"
    seen = None
    for _ in range(12):
        rows = _get("treasury-rates", {"from": "1960-01-01", "to": to})
        if not rows:
            break
        out.extend(rows)
        oldest = min(r["date"] for r in rows)
        if oldest == seen or len(rows) < 4900:
            break
        seen = oldest
        import datetime
        y, m, d = (int(x) for x in oldest.split("-"))
        to = (datetime.date(y, m, d) - datetime.timedelta(days=1)).isoformat()
    recs = [tuple([r["date"]] + [_num(r.get(t)) for t in tenors]) for r in out if r.get("date")]
    n = bulk_upsert(cur, "fmp_treasury_rates", cols, ["date"], recs)
    conn.commit()
    print(f"[done] fmp_treasury_rates: {n} rows, {table_mb(cur,'fmp_treasury_rates'):.1f} MB", flush=True)
    return n


def main():
    conn = psycopg2.connect(DBURL); cur = conn.cursor()
    print(f"=== START DB {size_gb(cur):.2f} GB ===", flush=True)
    commodities = [x["symbol"] for x in _get("commodities-list", {})]
    print(f"commodities: {len(commodities)} symbols", flush=True)
    harvest_eod(cur, conn, "fmp_commodities", commodities, "fmp")
    harvest_eod(cur, conn, "fmp_forex", FOREX_MAJORS, "fmp")
    harvest_economic(cur, conn)
    harvest_treasury(cur, conn)
    print(f"=== END DB {size_gb(cur):.2f} GB ===", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
