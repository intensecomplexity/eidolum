"""
fmp_ultimate_harvest.py — harvest the rest of the FMP Ultimate /stable/ catalog
into permanent local tables, BEFORE downgrading the FMP plan.

Extends the existing harvest (price_bars + the 9 reference tables in
jobs/fmp_bulk_harvest.py) to 19 new tables. Standalone, NOT a worker cron.

Design (matches harvest_price_bars.py / fmp_bulk_harvest.py conventions):
  * /stable/ only; apikey query param. Bulk endpoints return CSV (first char
    is '"'); the rest are JSON lists.
  * Idempotent + resumable: psycopg2.extras.execute_values, explicit ::type
    CASTs, page_size=5000, dedup-by-PK in Python (CardinalityViolation guard),
    ON CONFLICT DO NOTHING (immutable history) or DO UPDATE (latest snapshot).
    Never overwrites with NULLs. Re-running changes no row counts.
  * Checkpoint per (category, unit) to a JSON file → a killed run resumes
    without re-fetching.
  * Storage guard: pauses a category if DB size nears 40GB.
  * Per-ticker categories fan out via ThreadPoolExecutor under a shared
    rate limiter; DB writes happen single-threaded on the main thread
    (psycopg2 connections are not thread-safe).

Run (from backend/):
    export DATABASE_PUBLIC_URL=$(railway run -s Postgres python3 -c \
        "import os;print(os.environ['DATABASE_PUBLIC_URL'])" | tail -1)
    railway run -s hopeful-expression python3 scripts/fmp_ultimate_harvest.py [--only cat,cat] [--limit N]

Existing tables (price_bars + the 9) are NEVER read-for-write or modified.
"""
import argparse
import atexit
import csv
import hashlib
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date as _date

import httpx
import psycopg2
from psycopg2.extras import execute_values

FMP_KEY = os.getenv("FMP_KEY", "").strip()
DB_URL = os.getenv("DATABASE_PUBLIC_URL") or os.getenv("DATABASE_URL")
BASE = "https://financialmodelingprep.com/stable/"
TAG = "[fmp-ult]"
CHECKPOINT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "_artifacts", "fmp_ultimate_harvest_checkpoint.json")
STORAGE_GUARD_GB = 38.0          # pause below the hard 40GB guard
ANNUAL_FROM = 2009
QUARTER_FROM = 2015

_stats = {"tables": {}, "started": datetime.utcnow().isoformat(), "exit": "unknown"}


# ─────────────────────────────────────────────────────── value coercion
def _finite(f):
    """None unless f is a finite float (rejects NaN and ±inf)."""
    if f != f or f == float("inf") or f == float("-inf"):
        return None
    return f


def _f(v):
    if v is None or v == "" or v == "null":
        return None
    try:
        return _finite(float(v))
    except (TypeError, ValueError):
        return None


_BIGINT_MAX = 9223372036854775807


def _i(v):
    if v is None or v == "" or v == "null":
        return None
    try:
        f = _finite(float(v))
        if f is None or f > _BIGINT_MAX or f < -_BIGINT_MAX - 1:
            return None  # out of BIGINT range (FMP returns occasional garbage)
        return int(f)
    except (TypeError, ValueError):
        return None


def _s(v):
    if v is None:
        return None
    s = str(v).strip().strip('"')
    return s or None


def _b(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no", ""):
        return False
    return None


def _d(v):
    """Date string → 'YYYY-MM-DD' or None."""
    if not v:
        return None
    s = str(v).strip()[:10]
    return s if len(s) == 10 and s[4] == "-" else None


KIND = {  # kind -> (coercer, sql_type, value-cast)
    "f": (_f, "DOUBLE PRECISION", "%s::double precision"),
    "i": (_i, "BIGINT", "%s::bigint"),
    "s": (_s, "TEXT", "%s::text"),
    "b": (_b, "BOOLEAN", "%s::boolean"),
    "d": (_d, "DATE", "%s::date"),
}


# ─────────────────────────────────────────────────────── transport
def _get_csv(path, params=None, retries=4):
    """Returns list-of-dicts on success (possibly empty for a genuinely empty
    200), or None on a TRANSIENT failure (429/5xx/conn after retries) so the
    caller knows NOT to mark the unit done."""
    p = dict(params or {}); p["apikey"] = FMP_KEY
    backoff = [15, 30, 60, 90]
    for a in range(retries):
        try:
            r = httpx.get(BASE + path, params=p, timeout=180)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                if a < retries - 1:
                    print(f"{TAG} {path} {r.status_code} try {a+1} — sleep {backoff[a]}s", flush=True)
                    time.sleep(backoff[a]); continue
                return None
            if r.status_code != 200:
                print(f"{TAG} {path} CSV HTTP {r.status_code} {r.text[:120]}", flush=True)
                return None
            body = r.text
            if not body or body.lstrip()[:1] != '"':
                return []  # genuine empty / non-CSV 200
            return list(csv.DictReader(io.StringIO(body)))
        except Exception as e:
            if a < retries - 1:
                print(f"{TAG} {path} CSV exc {e} try {a+1} — sleep {backoff[a]}s", flush=True)
                time.sleep(backoff[a]); continue
            return None
    return None


def _get_json(path, params=None, retries=3):
    p = dict(params or {}); p["apikey"] = FMP_KEY
    backoff = [20, 45, 90]
    for a in range(retries):
        try:
            r = httpx.get(BASE + path, params=p, timeout=60)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                if a < retries - 1:
                    time.sleep(backoff[a]); continue
                return None
            if r.status_code != 200:
                return None
            j = r.json()
            return j if isinstance(j, list) else None
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout,
                httpx.RemoteProtocolError):
            if a < retries - 1:
                time.sleep(backoff[a]); continue
            return None
        except Exception:
            return None
    return None


# ─────────────────────────────────────────────────────── rate limiter
class Rate:
    def __init__(self, per_min):
        self.interval = 60.0 / max(1, per_min)
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            if now < self.next_t:
                time.sleep(self.next_t - now)
                now = time.time()
            self.next_t = now + self.interval


# ─────────────────────────────────────────────────────── DB helpers
def connect():
    c = psycopg2.connect(DB_URL)
    c.autocommit = False
    return c


def db_size_gb(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database())")
        return cur.fetchone()[0] / 1e9


def ensure_table(conn, table, columns, pk_cols):
    """columns: list of (name, kind). Adds fetched_at + source. PK from pk_cols."""
    defs = []
    for name, _src, kind in columns:
        sqltype = KIND[kind][1]
        nn = " NOT NULL" if name in pk_cols else ""
        defs.append(f"{name} {sqltype}{nn}")
    defs.append("fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    defs.append("source VARCHAR(16) NOT NULL DEFAULT 'fmp'")
    defs.append(f"PRIMARY KEY ({', '.join(pk_cols)})")
    ddl = f"CREATE TABLE IF NOT EXISTS {table} (\n  " + ",\n  ".join(defs) + "\n)"
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def upsert(conn, table, columns, pk_cols, rows, conflict="nothing"):
    """rows: list of dicts keyed by column name. execute_values + ::casts +
    page_size=5000 + dedup-by-PK. Returns rows attempted (post-dedup)."""
    if not rows:
        return 0
    colnames = [c[0] for c in columns]
    # dedup by PK (last wins)
    seen = {}
    for r in rows:
        seen[tuple(r.get(c) for c in pk_cols)] = r
    deduped = list(seen.values())
    tuples = [tuple(r.get(c) for c in colnames) for r in deduped]
    template = "(" + ",".join(KIND[c[2]][2] for c in columns) + ")"
    cols_sql = ",".join(colnames)
    if conflict == "nothing":
        action = "DO NOTHING"
    else:  # update non-pk cols + refresh fetched_at
        upd = [c for c in colnames if c not in pk_cols]
        action = "DO UPDATE SET " + ",".join(f"{c}=EXCLUDED.{c}" for c in upd) \
                 + ",fetched_at=now()"
    sql = (f"INSERT INTO {table} ({cols_sql}) VALUES %s "
           f"ON CONFLICT ({','.join(pk_cols)}) {action}")
    with conn.cursor() as cur:
        execute_values(cur, sql, tuples, template=template, page_size=5000)
    conn.commit()
    return len(deduped)


def map_rows(raw, columns, inject=None):
    """raw: list of FMP dicts. columns: (col, src_key, kind). inject: dict of
    {col: literal} added to every row. Returns list of column-keyed dicts."""
    out = []
    inj = inject or {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = {}
        for col, src, kind in columns:
            row[col] = KIND[kind][0](item.get(src))
        row.update(inj)
        out.append(row)
    return out


def row_hash(row, fields):
    h = hashlib.md5("|".join(str(row.get(f)) for f in fields).encode()).hexdigest()
    return h


# ─────────────────────────────────────────────────────── checkpoint
def load_cp():
    try:
        with open(CHECKPOINT) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cp(cp):
    os.makedirs(os.path.dirname(CHECKPOINT), exist_ok=True)
    tmp = CHECKPOINT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cp, f)
    os.replace(tmp, CHECKPOINT)


# ═══════════════════════════════════════════════════════ TABLE SPECS
# Each P1 fundamental: (col, src_key, kind). PK (symbol, date, period).
INCOME = [("symbol","symbol","s"),("date","date","d"),("period","period","s"),
    ("fiscal_year","fiscalYear","i"),("reported_currency","reportedCurrency","s"),
    ("revenue","revenue","i"),("cost_of_revenue","costOfRevenue","i"),
    ("gross_profit","grossProfit","i"),("rnd_expenses","researchAndDevelopmentExpenses","i"),
    ("operating_expenses","operatingExpenses","i"),("operating_income","operatingIncome","i"),
    ("ebitda","ebitda","i"),("ebit","ebit","i"),("interest_expense","interestExpense","i"),
    ("income_tax_expense","incomeTaxExpense","i"),("net_income","netIncome","i"),
    ("eps","eps","f"),("eps_diluted","epsDiluted","f"),
    ("weighted_avg_shares","weightedAverageShsOut","i")]

BALANCE = [("symbol","symbol","s"),("date","date","d"),("period","period","s"),
    ("fiscal_year","fiscalYear","i"),("reported_currency","reportedCurrency","s"),
    ("total_assets","totalAssets","i"),("total_current_assets","totalCurrentAssets","i"),
    ("cash_and_equivalents","cashAndCashEquivalents","i"),("inventory","inventory","i"),
    ("goodwill","goodwill","i"),("total_liabilities","totalLiabilities","i"),
    ("total_current_liabilities","totalCurrentLiabilities","i"),
    ("short_term_debt","shortTermDebt","i"),("long_term_debt","longTermDebt","i"),
    ("total_debt","totalDebt","i"),("net_debt","netDebt","i"),
    ("total_stockholders_equity","totalStockholdersEquity","i"),
    ("retained_earnings","retainedEarnings","i"),("common_stock","commonStock","i")]

CASHFLOW = [("symbol","symbol","s"),("date","date","d"),("period","period","s"),
    ("fiscal_year","fiscalYear","i"),("reported_currency","reportedCurrency","s"),
    ("net_income","netIncome","i"),("depreciation_amortization","depreciationAndAmortization","i"),
    ("stock_based_compensation","stockBasedCompensation","i"),
    ("operating_cash_flow","operatingCashFlow","i"),
    ("capital_expenditure","capitalExpenditure","i"),("free_cash_flow","freeCashFlow","i"),
    ("net_cash_investing","netCashProvidedByInvestingActivities","i"),
    ("net_cash_financing","netCashProvidedByFinancingActivities","i"),
    ("dividends_paid","netDividendsPaid","i"),
    ("common_stock_repurchased","commonStockRepurchased","i"),
    ("net_change_in_cash","netChangeInCash","i")]

RATIOS = [("symbol","symbol","s"),("date","date","d"),("period","period","s"),
    ("fiscal_year","fiscalYear","i"),
    ("gross_profit_margin","grossProfitMargin","f"),("operating_profit_margin","operatingProfitMargin","f"),
    ("net_profit_margin","netProfitMargin","f"),("current_ratio","currentRatio","f"),
    ("quick_ratio","quickRatio","f"),("debt_to_equity","debtToEquityRatio","f"),
    ("debt_to_assets","debtToAssetsRatio","f"),("interest_coverage","interestCoverageRatio","f"),
    ("pe_ratio","priceToEarningsRatio","f"),("pb_ratio","priceToBookRatio","f"),
    ("ps_ratio","priceToSalesRatio","f"),("div_yield","dividendYield","f"),
    ("payout_ratio","dividendPayoutRatio","f"),("revenue_per_share","revenuePerShare","f"),
    ("book_value_per_share","bookValuePerShare","f"),("fcf_per_share","freeCashFlowPerShare","f"),
    ("ev_multiple","enterpriseValueMultiple","f")]

KEYMET = [("symbol","symbol","s"),("date","date","d"),("period","period","s"),
    ("fiscal_year","fiscalYear","i"),("market_cap","marketCap","i"),
    ("enterprise_value","enterpriseValue","i"),("ev_to_ebitda","evToEBITDA","f"),
    ("ev_to_sales","evToSales","f"),("net_debt_to_ebitda","netDebtToEBITDA","f"),
    ("return_on_equity","returnOnEquity","f"),("return_on_assets","returnOnAssets","f"),
    ("return_on_invested_capital","returnOnInvestedCapital","f"),
    ("earnings_yield","earningsYield","f"),("free_cash_flow_yield","freeCashFlowYield","f"),
    ("working_capital","workingCapital","i"),("invested_capital","investedCapital","i"),
    ("graham_number","grahamNumber","f"),("days_sales_outstanding","daysOfSalesOutstanding","f")]

SCORES = [("symbol","symbol","s"),("altman_z_score","altmanZScore","f"),
    ("piotroski_score","piotroskiScore","i"),("working_capital","workingCapital","i"),
    ("total_assets","totalAssets","i"),("retained_earnings","retainedEarnings","i"),
    ("ebit","ebit","i"),("market_cap","marketCap","i"),
    ("total_liabilities","totalLiabilities","i"),("revenue","revenue","i")]

RATIOS_TTM = [("symbol","symbol","s"),
    ("gross_profit_margin_ttm","grossProfitMarginTTM","f"),
    ("operating_profit_margin_ttm","operatingProfitMarginTTM","f"),
    ("net_profit_margin_ttm","netProfitMarginTTM","f"),
    ("current_ratio_ttm","currentRatioTTM","f"),("quick_ratio_ttm","quickRatioTTM","f"),
    ("debt_to_equity_ttm","debtToEquityRatioTTM","f"),
    ("pe_ratio_ttm","priceToEarningsRatioTTM","f"),("pb_ratio_ttm","priceToBookRatioTTM","f"),
    ("ps_ratio_ttm","priceToSalesRatioTTM","f"),("div_yield_ttm","dividendYieldTTM","f"),
    ("interest_coverage_ttm","interestCoverageRatioTTM","f"),
    ("revenue_per_share_ttm","revenuePerShareTTM","f"),
    ("book_value_per_share_ttm","bookValuePerShareTTM","f"),
    ("fcf_per_share_ttm","freeCashFlowPerShareTTM","f"),
    ("enterprise_value_ttm","enterpriseValueTTM","i"),
    ("ev_multiple_ttm","enterpriseValueMultipleTTM","f"),
    ("effective_tax_rate_ttm","effectiveTaxRateTTM","f")]

ESTIMATES = [("symbol","symbol","s"),("date","date","d"),("period","period","s"),
    ("revenue_avg","revenueAvg","i"),("revenue_low","revenueLow","i"),
    ("revenue_high","revenueHigh","i"),("ebitda_avg","ebitdaAvg","i"),
    ("ebit_avg","ebitAvg","i"),("net_income_avg","netIncomeAvg","i"),
    ("eps_avg","epsAvg","f"),("eps_high","epsHigh","f"),("eps_low","epsLow","f"),
    ("num_analysts_revenue","numAnalystsRevenue","i"),("num_analysts_eps","numAnalystsEps","i")]

GRADES = [("symbol","symbol","s"),("date","date","d"),
    ("strong_buy","analystRatingsStrongBuy","i"),("buy","analystRatingsBuy","i"),
    ("hold","analystRatingsHold","i"),("sell","analystRatingsSell","i"),
    ("strong_sell","analystRatingsStrongSell","i")]

# individual analyst actions (full upgrade/downgrade history) — same firm can
# act twice on one date, so PK is a row hash like insider trades
GRADES_ACT = [("row_hash","","s"),("symbol","symbol","s"),("date","date","d"),
    ("grading_company","gradingCompany","s"),("previous_grade","previousGrade","s"),
    ("new_grade","newGrade","s"),("action","action","s")]

EARNINGS = [("symbol","symbol","s"),("date","date","d"),
    ("eps_actual","epsActual","f"),("eps_estimated","epsEstimated","f"),
    ("revenue_actual","revenueActual","i"),("revenue_estimated","revenueEstimated","i"),
    ("last_updated","lastUpdated","d")]

DIVIDENDS = [("symbol","symbol","s"),("date","date","d"),("record_date","recordDate","d"),
    ("payment_date","paymentDate","d"),("declaration_date","declarationDate","d"),
    ("adj_dividend","adjDividend","f"),("dividend","dividend","f"),
    ("div_yield","yield","f"),("frequency","frequency","s")]

SPLITS = [("symbol","symbol","s"),("date","date","d"),("numerator","numerator","f"),
    ("denominator","denominator","f"),("split_type","splitType","s")]

INSIDER = [("row_hash","","s"),("symbol","symbol","s"),("filing_date","filingDate","d"),
    ("transaction_date","transactionDate","d"),("reporting_cik","reportingCik","s"),
    ("reporting_name","reportingName","s"),("type_of_owner","typeOfOwner","s"),
    ("transaction_type","transactionType","s"),
    ("acquisition_or_disposition","acquisitionOrDisposition","s"),
    ("securities_transacted","securitiesTransacted","f"),("price","price","f"),
    ("securities_owned","securitiesOwned","f"),("security_name","securityName","s"),
    ("form_type","formType","s"),("url","url","s")]

INSTOWN = [("symbol","symbol","s"),("date","date","d"),
    ("investors_holding","investorsHolding","i"),
    ("number_of_13f_shares","numberOf13Fshares","i"),("total_invested","totalInvested","i"),
    ("ownership_percent","ownershipPercent","f"),("new_positions","newPositions","i"),
    ("increased_positions","increasedPositions","i"),("closed_positions","closedPositions","i"),
    ("reduced_positions","reducedPositions","i"),("put_call_ratio","putCallRatio","f")]

EXECS = [("symbol","symbol","s"),("name","name","s"),("title","title","s"),
    ("pay","pay","i"),("currency_pay","currencyPay","s"),("gender","gender","s"),
    ("year_born","yearBorn","i"),("title_since","titleSince","s"),("active","active","s")]

EMPLOYEES = [("symbol","symbol","s"),("period_of_report","periodOfReport","d"),
    ("filing_date","filingDate","d"),("employee_count","employeeCount","i"),
    ("form_type","formType","s"),("cik","cik","s")]

CONGRESS = [("row_hash","","s"),("chamber","chamber","s"),("symbol","symbol","s"),
    ("disclosure_date","disclosureDate","d"),("transaction_date","transactionDate","d"),
    ("first_name","firstName","s"),("last_name","lastName","s"),("office","office","s"),
    ("district","district","s"),("owner","owner","s"),
    ("asset_description","assetDescription","s"),("asset_type","assetType","s"),
    ("trade_type","type","s"),("amount","amount","s"),("link","link","s")]

STOCK_LIST = [("symbol","symbol","s"),("company_name","companyName","s")]
EXCHANGES = [("exchange","exchange","s"),("name","name","s"),
    ("country_name","countryName","s"),("country_code","countryCode","s"),
    ("symbol_suffix","symbolSuffix","s"),("delay","delay","s")]
FLOAT = [("symbol","symbol","s"),("date","date","d"),("free_float","freeFloat","f"),
    ("float_shares","floatShares","i"),("outstanding_shares","outstandingShares","i")]


# ═══════════════════════════════════════════════════════ harvest modes
def harvest_bulk_year(conn, cp, table, endpoint, columns, periods):
    """Fundamentals bulk: loop (period, year). period 'annual'|'quarter'."""
    pk = ["symbol", "date", "period"]
    ensure_table(conn, table, columns, pk)
    done = set(cp.get(table, {}).get("done", []))
    total = 0
    cur_year = datetime.utcnow().year
    units = []
    for period in periods:
        start = ANNUAL_FROM if period == "annual" else QUARTER_FROM
        for year in range(start, cur_year + 1):
            units.append((period, year))
    for period, year in units:
        key = f"{period}:{year}"
        if key in done:
            continue
        time.sleep(1.5)  # pace bulk CSV calls — they're huge and 429 easily
        raw = _get_csv(endpoint, {"year": year, "period": period})
        if raw is None:
            print(f"{TAG} {table} {key}: transient fetch fail — NOT marked done, retry next run", flush=True)
            continue
        rows = [r for r in map_rows(raw, columns) if r.get("symbol") and r.get("date")]
        n = upsert(conn, table, columns, pk, rows, conflict="nothing")
        total += n
        done.add(key)
        cp[table] = {"done": sorted(done)}
        save_cp(cp)
        print(f"{TAG} {table} {key}: +{n:,} (run total {total:,})", flush=True)
    _stats["tables"][table] = total
    return total


def harvest_single(conn, cp, table, endpoint, columns, pk, conflict, csv_mode=True):
    ensure_table(conn, table, columns, pk)
    if cp.get(table, {}).get("done"):
        print(f"{TAG} {table}: already done (checkpoint)", flush=True)
        return 0
    raw = _get_csv(endpoint) if csv_mode else _get_json(endpoint)
    if raw is None:
        print(f"{TAG} {table}: transient fetch fail — NOT marked done, retry next run", flush=True)
        return 0
    rows = map_rows(raw, columns)
    rows = [r for r in rows if all(r.get(k) is not None for k in pk if k != "row_hash")]
    n = upsert(conn, table, columns, pk, rows, conflict=conflict)
    cp[table] = {"done": True}; save_cp(cp)
    _stats["tables"][table] = n
    print(f"{TAG} {table}: {n:,} upserted", flush=True)
    return n


def harvest_paginated(conn, cp, table, endpoint, columns, pk, conflict,
                      inject=None, hash_fields=None, max_pages=400):
    ensure_table(conn, table, columns, pk)
    # Key checkpoint by (table, endpoint): senate-latest and house-latest both
    # write fmp_congress_trades but paginate independently, so a table-only key
    # would make the second resume at the first's end page and skip everything.
    cp_key = f"{table}:{endpoint}"
    start_page = cp.get(cp_key, {}).get("page", 0)
    total = 0
    page = start_page
    while page < max_pages:
        raw = _get_json(endpoint, {"page": page})
        if not raw:
            break
        rows = map_rows(raw, columns, inject=inject)
        if hash_fields:
            for r in rows:
                r["row_hash"] = row_hash(r, hash_fields)
        n = upsert(conn, table, columns, pk, rows, conflict=conflict)
        total += n
        page += 1
        cp[cp_key] = {"page": page}; save_cp(cp)
        if page % 10 == 0:
            print(f"{TAG} {table} page {page}: run total {total:,}", flush=True)
    _stats["tables"][table] = _stats["tables"].get(table, 0) + total
    print(f"{TAG} {table}: +{total:,} (through page {page})", flush=True)
    return total


def harvest_per_ticker(conn, cp, table, endpoint, columns, pk, tickers, rate,
                       conflict="nothing", param_sets=None, inject_keys=None,
                       hash_fields=None, workers=10, batch=200):
    """Fan out per-ticker fetches under the rate limiter; upsert on main thread.
    param_sets(ticker) -> list of param dicts (each → one request). inject_keys:
    list of (col, param_key) copied from the param dict into each row."""
    ensure_table(conn, table, columns, pk)
    hw = cp.get(table, {}).get("hw", 0)
    if param_sets is None:
        param_sets = lambda t: [{"symbol": t}]
    inject_keys = inject_keys or []
    todo = tickers[hw:]
    total = 0
    t0 = time.time()

    def fetch_one(ticker):
        results = []
        for ps in param_sets(ticker):
            rate.wait()
            raw = _get_json(endpoint, ps) or []
            inj = {"symbol": ticker}
            for col, pkey in inject_keys:
                inj[col] = ps.get(pkey)
            rows = map_rows(raw, columns, inject=inj)
            if hash_fields:
                for r in rows:
                    r["row_hash"] = row_hash(r, hash_fields)
            results.extend(rows)
        return results

    for b in range(0, len(todo), batch):
        if db_size_gb(conn) >= STORAGE_GUARD_GB:
            print(f"{TAG} STORAGE GUARD hit ({db_size_gb(conn):.1f}GB) — pausing {table}", flush=True)
            _stats["exit"] = f"storage_guard@{table}"
            break
        chunk = todo[b:b + batch]
        collected = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_one, t): t for t in chunk}
            for fut in as_completed(futs):
                try:
                    collected.extend(fut.result())
                except Exception as e:
                    print(f"{TAG} {table} {futs[fut]} fetch err: {e}", flush=True)
        n = upsert(conn, table, columns, pk, collected, conflict=conflict)
        total += n
        hw += len(chunk)
        cp[table] = {"hw": hw}; save_cp(cp)
        rate_n = hw / max(1e-6, (time.time() - t0))
        print(f"{TAG} {table} {hw}/{len(tickers)} tickers, +{total:,} rows "
              f"({rate_n*60:.0f} tic/min)", flush=True)
    _stats["tables"][table] = total
    return total


# ═══════════════════════════════════════════════════════ registry + main
def load_tickers(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM price_bars ORDER BY ticker")
        return [r[0] for r in cur.fetchall()]


def recent_quarters(n=2):
    y = datetime.utcnow().year
    q = (datetime.utcnow().month - 1) // 3  # last completed quarter index 0..3 (rough)
    out = []
    yy, qq = y, max(1, q)
    for _ in range(n):
        out.append({"year": yy, "quarter": qq})
        qq -= 1
        if qq < 1:
            qq = 4; yy -= 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma list of categories")
    ap.add_argument("--limit", type=int, default=0, help="cap tickers (testing)")
    ap.add_argument("--rate-limit", type=int, default=2400)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--checkpoint", default="", help="override checkpoint path (isolate concurrent runs)")
    args = ap.parse_args()
    if args.checkpoint:
        global CHECKPOINT
        CHECKPOINT = args.checkpoint

    if not FMP_KEY:
        print(f"{TAG} ERROR: FMP_KEY not set", flush=True); sys.exit(2)
    if not DB_URL:
        print(f"{TAG} ERROR: DATABASE_PUBLIC_URL not set", flush=True); sys.exit(2)

    atexit.register(lambda: print(f"{TAG} EXIT ({_stats['exit']}) tables={_stats['tables']}", flush=True))
    conn = connect()
    rate = Rate(args.rate_limit)
    cp = load_cp()
    tickers = load_tickers(conn)
    if args.limit:
        tickers = tickers[:args.limit]
    print(f"{TAG} universe={len(tickers):,} tickers  db={db_size_gb(conn):.2f}GB  rate={args.rate_limit}/min", flush=True)

    # category -> callable(conn, cp)
    reg = {
        # P1 fundamentals (bulk CSV by year)
        "income":     lambda: harvest_bulk_year(conn, cp, "fmp_income_statements", "income-statement-bulk", INCOME, ["annual","quarter"]),
        "balance":    lambda: harvest_bulk_year(conn, cp, "fmp_balance_sheets", "balance-sheet-statement-bulk", BALANCE, ["annual","quarter"]),
        "cashflow":   lambda: harvest_bulk_year(conn, cp, "fmp_cash_flows", "cash-flow-statement-bulk", CASHFLOW, ["annual","quarter"]),
        "ratios":     lambda: harvest_bulk_year(conn, cp, "fmp_ratios", "ratios-bulk", RATIOS, ["annual","quarter"]),
        "keymetrics": lambda: harvest_bulk_year(conn, cp, "fmp_key_metrics_annual", "key-metrics-bulk", KEYMET, ["annual","quarter"]),
        "scores":     lambda: harvest_single(conn, cp, "fmp_financial_scores", "scores-bulk", SCORES, ["symbol"], "update"),
        "ratios_ttm": lambda: harvest_single(conn, cp, "fmp_ratios_ttm", "ratios-ttm-bulk", RATIOS_TTM, ["symbol"], "update"),
        # reference singles
        "stock_list": lambda: harvest_single(conn, cp, "fmp_stock_list", "stock-list", STOCK_LIST, ["symbol"], "update", csv_mode=False),
        "exchanges":  lambda: harvest_single(conn, cp, "fmp_exchanges", "available-exchanges", EXCHANGES, ["exchange"], "update", csv_mode=False),
        # paginated firehoses (bounded)
        "float":      lambda: harvest_paginated(conn, cp, "fmp_shares_float", "shares-float-all", FLOAT, ["symbol","date"], "nothing"),
        "senate":     lambda: harvest_paginated(conn, cp, "fmp_congress_trades", "senate-latest", CONGRESS, ["row_hash"], "nothing", inject={"chamber":"senate"}, hash_fields=["chamber","symbol","transaction_date","first_name","last_name","amount","asset_description"]),
        "house":      lambda: harvest_paginated(conn, cp, "fmp_congress_trades", "house-latest", CONGRESS, ["row_hash"], "nothing", inject={"chamber":"house"}, hash_fields=["chamber","symbol","transaction_date","first_name","last_name","amount","asset_description"]),
        # per-ticker
        "insider":    lambda: harvest_per_ticker(conn, cp, "fmp_insider_trades", "insider-trading/search", INSIDER, ["row_hash"], tickers, rate, hash_fields=["symbol","filing_date","transaction_date","reporting_cik","transaction_type","securities_transacted","price","acquisition_or_disposition"], workers=args.workers),
        "grades":     lambda: harvest_per_ticker(conn, cp, "fmp_grades_historical", "grades-historical", GRADES, ["symbol","date"], tickers, rate, workers=args.workers),
        "grades_actions": lambda: harvest_per_ticker(conn, cp, "fmp_grades_actions", "grades", GRADES_ACT, ["row_hash"], tickers, rate, hash_fields=["symbol","date","grading_company","previous_grade","new_grade","action"], workers=args.workers),
        "earnings":   lambda: harvest_per_ticker(conn, cp, "fmp_earnings", "earnings", EARNINGS, ["symbol","date"], tickers, rate, workers=args.workers),
        "dividends":  lambda: harvest_per_ticker(conn, cp, "fmp_dividends", "dividends", DIVIDENDS, ["symbol","date"], tickers, rate, workers=args.workers),
        "splits":     lambda: harvest_per_ticker(conn, cp, "fmp_splits", "splits", SPLITS, ["symbol","date"], tickers, rate, workers=args.workers),
        "execs":      lambda: harvest_per_ticker(conn, cp, "fmp_key_executives", "key-executives", EXECS, ["symbol","name","title"], tickers, rate, conflict="update", workers=args.workers),
        "employees":  lambda: harvest_per_ticker(conn, cp, "fmp_employee_count", "employee-count", EMPLOYEES, ["symbol","period_of_report"], tickers, rate, workers=args.workers),
        "estimates":  lambda: harvest_per_ticker(conn, cp, "fmp_analyst_estimates", "analyst-estimates", ESTIMATES, ["symbol","date","period"], tickers, rate, param_sets=lambda t: [{"symbol":t,"period":"annual"},{"symbol":t,"period":"quarter"}], inject_keys=[("period","period")], workers=args.workers),
        "instown":    lambda: harvest_per_ticker(conn, cp, "fmp_institutional_ownership_summary", "institutional-ownership/symbol-positions-summary", INSTOWN, ["symbol","date"], tickers, rate, conflict="update", param_sets=lambda t, qs=recent_quarters(2): [dict(symbol=t, **q) for q in qs], workers=args.workers),
        # NOTE: full 13F holdings cross-product intentionally NOT harvested
        # (institutional-ownership/latest firehose) — storage-guard risk.
        # Hook: add a 'holdings' category here if the volume is upsized.
        # NOTE: historical-market-capitalization intentionally SKIPPED —
        # daily, ~20M rows, derivable from price_bars × shares outstanding.
    }
    order = ["income","balance","cashflow","ratios","keymetrics","scores","ratios_ttm",
             "stock_list","exchanges","float","senate","house",
             "grades","dividends","splits","execs","employees","estimates","insider","instown",
             "grades_actions","earnings"]

    cats = [c.strip() for c in args.only.split(",") if c.strip()] or order
    for cat in cats:
        if cat not in reg:
            print(f"{TAG} unknown category {cat}", flush=True); continue
        if db_size_gb(conn) >= STORAGE_GUARD_GB:
            print(f"{TAG} STORAGE GUARD {db_size_gb(conn):.1f}GB — stopping before {cat}", flush=True)
            _stats["exit"] = "storage_guard"; break
        print(f"{TAG} ═══ {cat} ═══", flush=True)
        try:
            reg[cat]()
        except Exception as e:
            print(f"{TAG} {cat} FAILED: {type(e).__name__}: {e}", flush=True)
            try: conn.rollback()
            except Exception: pass
    if _stats["exit"] == "unknown":
        _stats["exit"] = "completed"
    print(f"{TAG} DONE db={db_size_gb(conn):.2f}GB tables={_stats['tables']}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
