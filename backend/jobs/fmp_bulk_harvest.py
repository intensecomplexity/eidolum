"""
FMP Bulk Harvest — patched 2026-05-27 against the current /stable/ API.

Empirical endpoint audit (full probe at /tmp/fmp_probe_results.txt) revealed
that since the v3→stable migration:

  * All bulk endpoints return CSV (not JSON) — the v3 helper that did
    r.json() silently failed on every successful response. Now uses
    csv.DictReader.
  * profile-bulk requires ?part=0..N chunking. Empirical N=3 (4 parts).
  * earning-calendar was renamed to earnings-calendar AND switched to
    JSON (it's no longer "bulk"-suffixed).
  * stock-peers-bulk was removed entirely — the replacement is per-ticker
    and would need 10K+ calls. Skipped here with a TODO.
  * earnings-surprises-bulk requires ?year=YYYY (no "all years" option).
    We loop 2020..current year.
  * sector-performance was renamed to sector-performance-snapshot, switched
    to JSON, and requires ?date=YYYY-MM-DD. We use today / yesterday.
  * Field schemas diverged. We map what survives and let unmapped INSERT
    params remain NULL — destination columns are all nullable.

Performance v2 (2026-05-27): per-row INSERT...ON CONFLICT was hitting
~70 rows/min on the 200K-row tables (every row was one network round-trip).
Replaced with a single _bulk_upsert helper that builds VALUES clauses of
500 rows per chunk — one round-trip per chunk instead of 500. Expected
total runtime drops from ~6h to ~5min for the full 9-table harvest.
"""
import csv
import io
import os
import time
from datetime import datetime, date as _date, timedelta

import httpx
from sqlalchemy import text

FMP_KEY = os.getenv("FMP_KEY", "")
BASE = "https://financialmodelingprep.com/stable/"
TAG = "[FMPHarvest]"


# ─── value coercion ──────────────────────────────────────────────────────
def _f(v):
    """Float or None — tolerates '', 'null', NaN."""
    if v is None or v == "" or v == "null":
        return None
    try:
        f = float(v)
        return f if (f == f) else None
    except (TypeError, ValueError):
        return None


def _i(v):
    """Int or None — tolerates ''/'null'/float strings."""
    if v is None or v == "" or v == "null":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _b(v):
    """Bool or None — tolerates true/false/1/0/yes/no strings."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no", ""):
        return False
    return None


def _s(v):
    """String or None — strips, empties → None."""
    if v is None:
        return None
    s = str(v).strip().strip('"')
    return s or None


# ─── transport ───────────────────────────────────────────────────────────
def _get_csv(path: str, params: dict | None = None) -> list[dict]:
    """GET a CSV bulk endpoint. Returns list-of-dicts (DictReader) or []."""
    p = dict(params or {})
    p["apikey"] = FMP_KEY
    url = BASE + path
    try:
        r = httpx.get(url, params=p, timeout=180)
        if r.status_code != 200:
            print(f"{TAG} {path} CSV HTTP {r.status_code} body={r.text[:150]}", flush=True)
            return []
        body = r.text
        if not body:
            return []
        first_char = body.lstrip()[:1]
        if first_char != '"':
            return []
        reader = csv.DictReader(io.StringIO(body))
        return list(reader)
    except Exception as e:
        print(f"{TAG} {path} CSV exception: {e}", flush=True)
        return []


def _get_json(path: str, params: dict | None = None):
    """GET a JSON endpoint. Returns parsed JSON or None."""
    p = dict(params or {})
    p["apikey"] = FMP_KEY
    url = BASE + path
    try:
        r = httpx.get(url, params=p, timeout=60)
        if r.status_code != 200:
            print(f"{TAG} {path} JSON HTTP {r.status_code} body={r.text[:150]}", flush=True)
            return None
        return r.json()
    except Exception as e:
        print(f"{TAG} {path} JSON exception: {e}", flush=True)
        return None


def _ensure_table(db, ddl: str) -> None:
    try:
        db.execute(text(ddl))
        db.commit()
    except Exception:
        db.rollback()


# ─── bulk-upsert helper ──────────────────────────────────────────────────
def _bulk_upsert(db, table: str, rows: list[dict], cols: list[str],
                 pk_cols: list[str], update_cols: list[str],
                 chunk_size: int = 500) -> int:
    """Chunked VALUES INSERT with ON CONFLICT DO UPDATE. Returns inserted count.

    One round-trip per chunk instead of per row → ~500× speedup on big
    bulks. Falls back to per-row on chunk failure so a single bad row
    doesn't kill the whole batch.
    """
    if not rows:
        return 0
    cols_sql   = ", ".join(cols)
    pk_sql     = ", ".join(pk_cols)
    update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    total = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        placeholders = []
        params = {}
        for j, row in enumerate(chunk):
            row_ph = []
            for col in cols:
                key = f"{col}_{j}"
                row_ph.append(f":{key}")
                params[key] = row.get(col)
            placeholders.append("(" + ",".join(row_ph) + ")")
        sql = (
            f"INSERT INTO {table} ({cols_sql}) VALUES "
            + ",".join(placeholders) +
            f" ON CONFLICT ({pk_sql}) DO UPDATE SET {update_sql}"
        )
        try:
            db.execute(text(sql), params)
            total += len(chunk)
        except Exception as e:
            print(f"{TAG} _bulk_upsert {table} chunk {i} failed ({e}); falling back row-by-row", flush=True)
            try:
                db.rollback()
            except Exception:
                pass
            # Per-row fallback so one bad row doesn't lose the whole chunk
            for row in chunk:
                try:
                    single_sql = (
                        f"INSERT INTO {table} ({cols_sql}) VALUES ("
                        + ",".join(f":{c}" for c in cols) +
                        f") ON CONFLICT ({pk_sql}) DO UPDATE SET {update_sql}"
                    )
                    db.execute(text(single_sql), row)
                    total += 1
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
            try:
                db.commit()
            except Exception:
                pass
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    return total


# ═══════════════════════════════════════════════════════════════════════════
# 1. Company Profiles  (profile-bulk, CSV, ?part=0..N)
# ═══════════════════════════════════════════════════════════════════════════

PROFILE_COLS = [
    "ticker", "company_name", "description", "sector", "industry", "market_cap",
    "country", "exchange", "website", "ipo_date", "employees", "is_etf",
    "is_actively_trading", "logo_url", "ceo", "city", "state", "currency",
]
PROFILE_UPDATE = [c for c in PROFILE_COLS if c != "ticker"]


def harvest_company_profiles(db) -> int:
    print(f"{TAG} === Company Profiles ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS company_profiles (
            ticker VARCHAR(20) PRIMARY KEY,
            company_name TEXT,
            description TEXT,
            sector VARCHAR(100),
            industry VARCHAR(200),
            market_cap BIGINT,
            country VARCHAR(100),
            exchange VARCHAR(50),
            website TEXT,
            ipo_date VARCHAR(20),
            employees INTEGER,
            is_etf BOOLEAN DEFAULT FALSE,
            is_actively_trading BOOLEAN DEFAULT TRUE,
            logo_url TEXT,
            ceo TEXT,
            city VARCHAR(100),
            state VARCHAR(100),
            currency VARCHAR(10),
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    total = 0
    for part in range(0, 20):  # observed 4 parts active 2026-05-27
        csv_rows = _get_csv("profile-bulk", {"part": part})
        if not csv_rows:
            print(f"{TAG} profile-bulk part={part} empty — done after {total:,} rows", flush=True)
            break
        prepared = []
        for r in csv_rows:
            sym = _s(r.get("symbol"))
            if not sym:
                continue
            prepared.append({
                "ticker":   sym,
                "company_name": _s(r.get("companyName")),
                "description":  _s(r.get("description")),
                "sector":   _s(r.get("sector")),
                "industry": _s(r.get("industry")),
                "market_cap": _i(r.get("marketCap")),
                "country":  _s(r.get("country")),
                "exchange": _s(r.get("exchange")) or _s(r.get("exchangeFullName")),
                "website":  _s(r.get("website")),
                "ipo_date": _s(r.get("ipoDate")),
                "employees": _i(r.get("fullTimeEmployees")),
                "is_etf":    _b(r.get("isEtf")),
                "is_actively_trading": _b(r.get("isActivelyTrading")),
                "logo_url":  _s(r.get("image")),
                "ceo":       _s(r.get("ceo")),
                "city":      _s(r.get("city")),
                "state":     _s(r.get("state")),
                "currency":  _s(r.get("currency")),
            })
        n = _bulk_upsert(db, "company_profiles", prepared, PROFILE_COLS, ["ticker"], PROFILE_UPDATE)
        total += n
        print(f"{TAG} profile-bulk part={part}: +{n:,} (total {total:,})", flush=True)
    print(f"{TAG} Company profiles: {total:,} upserted", flush=True)
    return total


# ═══════════════════════════════════════════════════════════════════════════
# 2. Analyst Consensus  (upgrades-downgrades-consensus-bulk, CSV)
# ═══════════════════════════════════════════════════════════════════════════

CONSENSUS_COLS = ["ticker", "strong_buy", "buy", "hold", "sell", "strong_sell", "consensus"]
CONSENSUS_UPDATE = [c for c in CONSENSUS_COLS if c != "ticker"]


def harvest_analyst_consensus(db) -> int:
    print(f"{TAG} === Analyst Consensus ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS analyst_consensus (
            ticker VARCHAR(20) PRIMARY KEY,
            strong_buy INTEGER DEFAULT 0,
            buy INTEGER DEFAULT 0,
            hold INTEGER DEFAULT 0,
            sell INTEGER DEFAULT 0,
            strong_sell INTEGER DEFAULT 0,
            consensus VARCHAR(20),
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    csv_rows = _get_csv("upgrades-downgrades-consensus-bulk")
    prepared = []
    for r in csv_rows:
        sym = _s(r.get("symbol"))
        if not sym:
            continue
        prepared.append({
            "ticker":   sym,
            "strong_buy":  _i(r.get("strongBuy")) or 0,
            "buy":         _i(r.get("buy")) or 0,
            "hold":        _i(r.get("hold")) or 0,
            "sell":        _i(r.get("sell")) or 0,
            "strong_sell": _i(r.get("strongSell")) or 0,
            "consensus":   _s(r.get("consensus")),
        })
    n = _bulk_upsert(db, "analyst_consensus", prepared, CONSENSUS_COLS, ["ticker"], CONSENSUS_UPDATE)
    print(f"{TAG} Analyst consensus: {n:,} upserted", flush=True)
    return n


# ═══════════════════════════════════════════════════════════════════════════
# 3. Price Target Summary  (price-target-summary-bulk, CSV)
# ═══════════════════════════════════════════════════════════════════════════

PTS_COLS = ["ticker", "last_month_avg", "last_quarter_avg", "last_year_avg"]
PTS_UPDATE = [c for c in PTS_COLS if c != "ticker"]


def harvest_price_target_summary(db) -> int:
    print(f"{TAG} === Price Target Summary ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS price_target_summary (
            ticker VARCHAR(20) PRIMARY KEY,
            last_month_avg FLOAT, last_month_high FLOAT, last_month_low FLOAT,
            last_quarter_avg FLOAT, last_quarter_high FLOAT, last_quarter_low FLOAT,
            last_year_avg FLOAT, last_year_high FLOAT, last_year_low FLOAT,
            current_price FLOAT,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    csv_rows = _get_csv("price-target-summary-bulk")
    prepared = []
    for r in csv_rows:
        sym = _s(r.get("symbol"))
        if not sym:
            continue
        prepared.append({
            "ticker": sym,
            "last_month_avg":   _f(r.get("lastMonthAvgPriceTarget")),
            "last_quarter_avg": _f(r.get("lastQuarterAvgPriceTarget")),
            "last_year_avg":    _f(r.get("lastYearAvgPriceTarget")),
        })
    n = _bulk_upsert(db, "price_target_summary", prepared, PTS_COLS, ["ticker"], PTS_UPDATE)
    print(f"{TAG} Price target summary: {n:,} upserted", flush=True)
    return n


# ═══════════════════════════════════════════════════════════════════════════
# 4. Stock Ratings  (rating-bulk, CSV)
# ═══════════════════════════════════════════════════════════════════════════

RATING_COLS = ["ticker", "rating", "dcf_score", "roe_score", "de_score", "pe_score", "pb_score"]
RATING_UPDATE = [c for c in RATING_COLS if c != "ticker"]


def harvest_stock_ratings(db) -> int:
    print(f"{TAG} === Stock Ratings ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS stock_ratings (
            ticker VARCHAR(20) PRIMARY KEY,
            rating VARCHAR(10),
            score INTEGER,
            recommendation VARCHAR(30),
            dcf_score INTEGER, roe_score INTEGER, de_score INTEGER,
            pe_score INTEGER, pb_score INTEGER,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    csv_rows = _get_csv("rating-bulk")
    prepared = []
    for r in csv_rows:
        sym = _s(r.get("symbol"))
        if not sym:
            continue
        prepared.append({
            "ticker":    sym,
            "rating":    _s(r.get("rating")),
            "dcf_score": _i(r.get("discountedCashFlowScore")),
            "roe_score": _i(r.get("returnOnEquityScore")),
            "de_score":  _i(r.get("debtToEquityScore")),
            "pe_score":  _i(r.get("priceToEarningsScore")),
            "pb_score":  _i(r.get("priceToBookScore")),
        })
    n = _bulk_upsert(db, "stock_ratings", prepared, RATING_COLS, ["ticker"], RATING_UPDATE)
    print(f"{TAG} Stock ratings: {n:,} upserted", flush=True)
    return n


# ═══════════════════════════════════════════════════════════════════════════
# 5. Earnings Calendar  (earnings-calendar, JSON)
# ═══════════════════════════════════════════════════════════════════════════

EARN_COLS = ["ticker", "date", "eps_estimated", "eps_actual",
             "revenue_estimated", "revenue_actual"]
EARN_UPDATE = [c for c in EARN_COLS if c not in ("ticker", "date")]


def harvest_earnings_calendar(db) -> int:
    print(f"{TAG} === Earnings Calendar ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS earnings_history (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            date DATE NOT NULL,
            eps_estimated FLOAT,
            eps_actual FLOAT,
            revenue_estimated BIGINT,
            revenue_actual BIGINT,
            fiscal_period VARCHAR(20),
            fetched_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(ticker, date)
        )
    """)

    data = _get_json("earnings-calendar")
    if not isinstance(data, list):
        return 0
    prepared = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sym = _s(item.get("symbol"))
        dt = _s(item.get("date"))
        if not sym or not dt:
            continue
        prepared.append({
            "ticker": sym, "date": dt,
            "eps_estimated":     _f(item.get("epsEstimated")),
            "eps_actual":        _f(item.get("epsActual")),
            "revenue_estimated": _i(item.get("revenueEstimated")),
            "revenue_actual":    _i(item.get("revenueActual")),
        })
    n = _bulk_upsert(db, "earnings_history", prepared, EARN_COLS,
                    ["ticker", "date"], EARN_UPDATE)
    print(f"{TAG} Earnings calendar: {n:,} upserted", flush=True)
    return n


# ═══════════════════════════════════════════════════════════════════════════
# 6. Stock Peers  — SKIPPED (no bulk endpoint in /stable/)
# ═══════════════════════════════════════════════════════════════════════════

def harvest_stock_peers(db) -> int:
    print(f"{TAG} === Stock Peers === SKIPPED (no bulk endpoint in /stable/)", flush=True)
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# 7. Key Metrics TTM  (key-metrics-ttm-bulk, CSV) — schema diverged heavily
# ═══════════════════════════════════════════════════════════════════════════

KEY_COLS = ["ticker", "market_cap", "roe", "current_ratio", "ev_to_ebitda"]
KEY_UPDATE = [c for c in KEY_COLS if c != "ticker"]


def harvest_key_metrics(db) -> int:
    print(f"{TAG} === Key Metrics TTM ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS key_metrics (
            ticker VARCHAR(20) PRIMARY KEY,
            market_cap BIGINT,
            pe_ratio FLOAT,
            eps FLOAT,
            dividend_yield FLOAT,
            revenue BIGINT,
            net_income BIGINT,
            roe FLOAT,
            debt_to_equity FLOAT,
            current_ratio FLOAT,
            book_value_per_share FLOAT,
            free_cash_flow_per_share FLOAT,
            price_to_book FLOAT,
            price_to_sales FLOAT,
            ev_to_ebitda FLOAT,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    csv_rows = _get_csv("key-metrics-ttm-bulk")
    prepared = []
    for r in csv_rows:
        sym = _s(r.get("symbol"))
        if not sym:
            continue
        prepared.append({
            "ticker":        sym,
            "market_cap":    _i(r.get("marketCap")),
            "roe":           _f(r.get("returnOnEquityTTM")),
            "current_ratio": _f(r.get("currentRatioTTM")),
            "ev_to_ebitda":  _f(r.get("evToEBITDATTM")),
        })
    n = _bulk_upsert(db, "key_metrics", prepared, KEY_COLS, ["ticker"], KEY_UPDATE)
    print(f"{TAG} Key metrics: {n:,} upserted", flush=True)
    return n


# ═══════════════════════════════════════════════════════════════════════════
# 8. Earnings Surprises  (earnings-surprises-bulk, CSV, ?year=YYYY)
# ═══════════════════════════════════════════════════════════════════════════

SURP_COLS = ["ticker", "date", "eps_estimated", "eps_actual", "surprise_pct"]
SURP_UPDATE = [c for c in SURP_COLS if c not in ("ticker", "date")]


def harvest_earnings_surprises(db) -> int:
    print(f"{TAG} === Earnings Surprises ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS earnings_surprises (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            date DATE NOT NULL,
            eps_estimated FLOAT,
            eps_actual FLOAT,
            surprise_pct FLOAT,
            fetched_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(ticker, date)
        )
    """)

    cur_year = datetime.utcnow().year
    total = 0
    for year in range(2020, cur_year + 1):
        csv_rows = _get_csv("earnings-surprises-bulk", {"year": year})
        if not csv_rows:
            continue
        prepared = []
        for r in csv_rows:
            sym = _s(r.get("symbol"))
            dt  = _s(r.get("date"))
            if not sym or not dt:
                continue
            actual    = _f(r.get("epsActual"))
            estimated = _f(r.get("epsEstimated"))
            surprise  = None
            if actual is not None and estimated and estimated != 0:
                surprise = round((actual - estimated) / abs(estimated) * 100, 2)
            prepared.append({
                "ticker": sym, "date": dt,
                "eps_estimated": estimated, "eps_actual": actual,
                "surprise_pct":  surprise,
            })
        n = _bulk_upsert(db, "earnings_surprises", prepared, SURP_COLS,
                        ["ticker", "date"], SURP_UPDATE)
        total += n
        print(f"{TAG} earnings-surprises year={year}: +{n:,} (total {total:,})", flush=True)
    print(f"{TAG} Earnings surprises: {total:,} upserted", flush=True)
    return total


# ═══════════════════════════════════════════════════════════════════════════
# 9. Sector Performance  (sector-performance-snapshot, JSON, ?date=YYYY-MM-DD)
# ═══════════════════════════════════════════════════════════════════════════

SECT_COLS = ["sector", "change_pct"]
SECT_UPDATE = ["change_pct"]


def harvest_sector_performance(db) -> int:
    print(f"{TAG} === Sector Performance ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS sector_performance (
            sector VARCHAR(100) PRIMARY KEY,
            change_pct FLOAT,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    today = _date.today()
    data = None
    for offset in (0, 1, 2, 3, 4):
        d = today - timedelta(days=offset)
        data = _get_json("sector-performance-snapshot", {"date": d.strftime("%Y-%m-%d")})
        if isinstance(data, list) and data:
            print(f"{TAG} sector snapshot from {d}", flush=True)
            break
    if not isinstance(data, list):
        return 0

    prepared = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if (item.get("exchange") or "").upper() != "NASDAQ":
            continue  # collapse to NASDAQ to keep one row per sector
        sector = _s(item.get("sector"))
        pct = _f(item.get("averageChange"))
        if not sector or pct is None:
            continue
        prepared.append({"sector": sector, "change_pct": pct})
    n = _bulk_upsert(db, "sector_performance", prepared, SECT_COLS, ["sector"], SECT_UPDATE)
    print(f"{TAG} Sector performance: {n:,} upserted", flush=True)
    return n


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def run_fmp_bulk_harvest(db=None):
    """Run the full FMP bulk harvest. Idempotent — safe to re-run."""
    print(f"{TAG} ═══════════════════════════════════════════", flush=True)
    print(f"{TAG} Starting FMP Bulk Harvest (v2 patched + bulk upsert 2026-05-27)", flush=True)

    if not FMP_KEY:
        print(f"{TAG} No FMP_KEY — skipping", flush=True)
        return

    if db is None:
        from database import BgSessionLocal
        db = BgSessionLocal()
        own = True
    else:
        own = False

    start = time.time()
    results: dict = {}

    harvests = [
        ("company_profiles",     harvest_company_profiles),
        ("analyst_consensus",    harvest_analyst_consensus),
        ("price_target_summary", harvest_price_target_summary),
        ("stock_ratings",        harvest_stock_ratings),
        ("earnings_calendar",    harvest_earnings_calendar),
        # stock_peers SKIPPED — no bulk endpoint in /stable/
        ("key_metrics",          harvest_key_metrics),
        ("earnings_surprises",   harvest_earnings_surprises),
        ("sector_performance",   harvest_sector_performance),
    ]

    for name, fn in harvests:
        try:
            results[name] = fn(db)
        except Exception as e:
            print(f"{TAG} {name} FAILED: {e}", flush=True)
            results[name] = f"ERROR: {e}"
        time.sleep(1)

    elapsed = time.time() - start
    print(f"{TAG} ═══════════════════════════════════════════", flush=True)
    print(f"{TAG} HARVEST COMPLETE in {elapsed:.0f}s", flush=True)
    for name, count in results.items():
        print(f"{TAG}   {name}: {count}", flush=True)
    print(f"{TAG} Safe to downgrade FMP plan after verifying data.", flush=True)

    if own:
        try:
            db.close()
        except Exception:
            pass
