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
  * stock-peers-bulk was removed entirely — the replacement /stable/stock-peers
    is per-ticker and would need 10K+ calls. Skipped here with a TODO.
  * earnings-surprises-bulk requires ?year=YYYY (no "all years" option).
    We loop 2020..current year.
  * sector-performance was renamed to sector-performance-snapshot, switched
    to JSON, and requires ?date=YYYY-MM-DD. We use today/yesterday.
  * Field schemas diverged. We map what survives and let unmapped INSERT
    params remain NULL — the destination columns are all nullable.

After completion the 9 tables (8 populated, stock_peers skipped) hold all
the high-value reference data and survive the FMP plan downgrade.
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
        r = httpx.get(url, params=p, timeout=120)
        if r.status_code != 200:
            print(f"{TAG} {path} CSV HTTP {r.status_code} body={r.text[:150]}", flush=True)
            return []
        body = r.text
        if not body:
            return []
        # FMP bulk CSV always starts with a quoted header row; if not, it's
        # probably a JSON error envelope or some other shape.
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


# ═══════════════════════════════════════════════════════════════════════════
# 1. Company Profiles  (profile-bulk, CSV, ?part=0..N)
# ═══════════════════════════════════════════════════════════════════════════

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
    for part in range(0, 20):  # safety cap; observed part=0..3 active 2026-05-27
        rows = _get_csv("profile-bulk", {"part": part})
        if not rows:
            print(f"{TAG} profile-bulk part={part} empty — done after {total} rows", flush=True)
            break
        for row in rows:
            sym = _s(row.get("symbol"))
            if not sym:
                continue
            try:
                db.execute(text("""
                    INSERT INTO company_profiles (ticker, company_name, description,
                        sector, industry, market_cap, country, exchange, website,
                        ipo_date, employees, is_etf, is_actively_trading, logo_url,
                        ceo, city, state, currency, fetched_at)
                    VALUES (:t, :name, :desc, :sector, :industry, :mcap, :country,
                            :exchange, :website, :ipo, :emp, :etf, :active, :logo,
                            :ceo, :city, :state, :currency, NOW())
                    ON CONFLICT (ticker) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        description  = EXCLUDED.description,
                        sector       = EXCLUDED.sector,
                        industry     = EXCLUDED.industry,
                        market_cap   = EXCLUDED.market_cap,
                        country      = EXCLUDED.country,
                        exchange     = EXCLUDED.exchange,
                        website      = EXCLUDED.website,
                        ipo_date     = EXCLUDED.ipo_date,
                        employees    = EXCLUDED.employees,
                        is_etf       = EXCLUDED.is_etf,
                        is_actively_trading = EXCLUDED.is_actively_trading,
                        logo_url     = EXCLUDED.logo_url,
                        ceo          = EXCLUDED.ceo,
                        city         = EXCLUDED.city,
                        state        = EXCLUDED.state,
                        currency     = EXCLUDED.currency,
                        fetched_at   = NOW()
                """), {
                    "t": sym,
                    "name":     _s(row.get("companyName")),
                    "desc":     _s(row.get("description")),
                    "sector":   _s(row.get("sector")),
                    "industry": _s(row.get("industry")),
                    "mcap":     _i(row.get("marketCap")),
                    "country":  _s(row.get("country")),
                    "exchange": _s(row.get("exchange")) or _s(row.get("exchangeFullName")),
                    "website":  _s(row.get("website")),
                    "ipo":      _s(row.get("ipoDate")),
                    "emp":      _i(row.get("fullTimeEmployees")),
                    "etf":      _b(row.get("isEtf")),
                    "active":   _b(row.get("isActivelyTrading")),
                    "logo":     _s(row.get("image")),
                    "ceo":      _s(row.get("ceo")),
                    "city":     _s(row.get("city")),
                    "state":    _s(row.get("state")),
                    "currency": _s(row.get("currency")),
                })
                total += 1
                if total % 500 == 0:
                    db.commit()
            except Exception:
                pass
        db.commit()
        print(f"{TAG} profile-bulk part={part} done — cumulative={total:,}", flush=True)
    print(f"{TAG} Company profiles: {total:,} upserted", flush=True)
    return total


# ═══════════════════════════════════════════════════════════════════════════
# 2. Analyst Consensus  (upgrades-downgrades-consensus-bulk, CSV, no params)
# ═══════════════════════════════════════════════════════════════════════════

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

    rows = _get_csv("upgrades-downgrades-consensus-bulk")
    count = 0
    for r in rows:
        sym = _s(r.get("symbol"))
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO analyst_consensus
                    (ticker, strong_buy, buy, hold, sell, strong_sell, consensus, fetched_at)
                VALUES (:t, :sb, :b, :h, :s, :ss, :c, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    strong_buy = EXCLUDED.strong_buy, buy = EXCLUDED.buy,
                    hold = EXCLUDED.hold, sell = EXCLUDED.sell,
                    strong_sell = EXCLUDED.strong_sell,
                    consensus = EXCLUDED.consensus, fetched_at = NOW()
            """), {
                "t": sym,
                "sb": _i(r.get("strongBuy")) or 0,
                "b":  _i(r.get("buy")) or 0,
                "h":  _i(r.get("hold")) or 0,
                "s":  _i(r.get("sell")) or 0,
                "ss": _i(r.get("strongSell")) or 0,
                "c":  _s(r.get("consensus")),
            })
            count += 1
            if count % 500 == 0:
                db.commit()
        except Exception:
            pass
    db.commit()
    print(f"{TAG} Analyst consensus: {count:,} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# 3. Price Target Summary  (price-target-summary-bulk, CSV, no params)
# Schema note: /stable/ no longer returns high/low per period or current
# price — only count + avg per period. Old columns kept; high/low/current
# stay NULL going forward.
# ═══════════════════════════════════════════════════════════════════════════

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

    rows = _get_csv("price-target-summary-bulk")
    count = 0
    for r in rows:
        sym = _s(r.get("symbol"))
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO price_target_summary
                    (ticker, last_month_avg, last_month_high, last_month_low,
                     last_quarter_avg, last_quarter_high, last_quarter_low,
                     last_year_avg, last_year_high, last_year_low,
                     current_price, fetched_at)
                VALUES (:t, :lma, NULL, NULL, :lqa, NULL, NULL, :lya, NULL, NULL,
                        NULL, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    last_month_avg   = EXCLUDED.last_month_avg,
                    last_quarter_avg = EXCLUDED.last_quarter_avg,
                    last_year_avg    = EXCLUDED.last_year_avg,
                    fetched_at = NOW()
            """), {
                "t":   sym,
                "lma": _f(r.get("lastMonthAvgPriceTarget")),
                "lqa": _f(r.get("lastQuarterAvgPriceTarget")),
                "lya": _f(r.get("lastYearAvgPriceTarget")),
            })
            count += 1
            if count % 500 == 0:
                db.commit()
        except Exception:
            pass
    db.commit()
    print(f"{TAG} Price target summary: {count:,} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# 4. Stock Ratings  (rating-bulk, CSV, no params)
# Schema note: no overall "score" or "recommendation" in /stable/ — those
# stay NULL. New "returnOnAssetsScore" isn't kept; old roe/de/pe/pb map.
# ═══════════════════════════════════════════════════════════════════════════

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

    rows = _get_csv("rating-bulk")
    count = 0
    for r in rows:
        sym = _s(r.get("symbol"))
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO stock_ratings (ticker, rating, score, recommendation,
                    dcf_score, roe_score, de_score, pe_score, pb_score, fetched_at)
                VALUES (:t, :r, NULL, NULL, :dcf, :roe, :de, :pe, :pb, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    rating = EXCLUDED.rating,
                    dcf_score = EXCLUDED.dcf_score,
                    roe_score = EXCLUDED.roe_score,
                    de_score  = EXCLUDED.de_score,
                    pe_score  = EXCLUDED.pe_score,
                    pb_score  = EXCLUDED.pb_score,
                    fetched_at = NOW()
            """), {
                "t":   sym,
                "r":   _s(r.get("rating")),
                "dcf": _i(r.get("discountedCashFlowScore")),
                "roe": _i(r.get("returnOnEquityScore")),
                "de":  _i(r.get("debtToEquityScore")),
                "pe":  _i(r.get("priceToEarningsScore")),
                "pb":  _i(r.get("priceToBookScore")),
            })
            count += 1
            if count % 500 == 0:
                db.commit()
        except Exception:
            pass
    db.commit()
    print(f"{TAG} Stock ratings: {count:,} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# 5. Earnings Calendar  (earnings-calendar, JSON, no "bulk" suffix anymore)
# ═══════════════════════════════════════════════════════════════════════════

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
    count = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        sym = _s(item.get("symbol"))
        dt = _s(item.get("date"))
        if not sym or not dt:
            continue
        try:
            db.execute(text("""
                INSERT INTO earnings_history
                    (ticker, date, eps_estimated, eps_actual, revenue_estimated,
                     revenue_actual, fiscal_period, fetched_at)
                VALUES (:t, :d, :ee, :ea, :re, :ra, NULL, NOW())
                ON CONFLICT (ticker, date) DO UPDATE SET
                    eps_estimated     = EXCLUDED.eps_estimated,
                    eps_actual        = EXCLUDED.eps_actual,
                    revenue_estimated = EXCLUDED.revenue_estimated,
                    revenue_actual    = EXCLUDED.revenue_actual,
                    fetched_at = NOW()
            """), {
                "t": sym, "d": dt,
                "ee": _f(item.get("epsEstimated")),
                "ea": _f(item.get("epsActual")),
                "re": _i(item.get("revenueEstimated")),
                "ra": _i(item.get("revenueActual")),
            })
            count += 1
            if count % 500 == 0:
                db.commit()
        except Exception:
            pass
    db.commit()
    print(f"{TAG} Earnings calendar: {count:,} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# 6. Stock Peers  — SKIPPED (no longer a bulk endpoint)
# /stable/stock-peers is now per-ticker (requires ?symbol=X). Calling it
# for every 10K+ ticker would burn 10K+ FMP calls. Defer to a separate
# targeted job that pulls peers only for top-N forecasted tickers.
# ═══════════════════════════════════════════════════════════════════════════

def harvest_stock_peers(db) -> int:
    print(f"{TAG} === Stock Peers === SKIPPED (no bulk endpoint in /stable/)", flush=True)
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# 7. Key Metrics TTM  (key-metrics-ttm-bulk, CSV, no params)
# Schema diverged heavily from v3. We map the survivors: market_cap,
# current_ratio, roe, ev_to_ebitda. The rest stay NULL until we widen
# the destination schema (or rename columns to match the new fields).
# ═══════════════════════════════════════════════════════════════════════════

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

    rows = _get_csv("key-metrics-ttm-bulk")
    count = 0
    for r in rows:
        sym = _s(r.get("symbol"))
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO key_metrics (ticker, market_cap, pe_ratio, eps,
                    dividend_yield, revenue, net_income, roe, debt_to_equity,
                    current_ratio, book_value_per_share, free_cash_flow_per_share,
                    price_to_book, price_to_sales, ev_to_ebitda, fetched_at)
                VALUES (:t, :mc, NULL, NULL, NULL, NULL, NULL, :roe, NULL, :cr,
                        NULL, NULL, NULL, NULL, :eve, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    market_cap   = EXCLUDED.market_cap,
                    roe          = EXCLUDED.roe,
                    current_ratio = EXCLUDED.current_ratio,
                    ev_to_ebitda = EXCLUDED.ev_to_ebitda,
                    fetched_at   = NOW()
            """), {
                "t":   sym,
                "mc":  _i(r.get("marketCap")),
                "roe": _f(r.get("returnOnEquityTTM")),
                "cr":  _f(r.get("currentRatioTTM")),
                "eve": _f(r.get("evToEBITDATTM")),
            })
            count += 1
            if count % 500 == 0:
                db.commit()
        except Exception:
            pass
    db.commit()
    print(f"{TAG} Key metrics: {count:,} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# 8. Earnings Surprises  (earnings-surprises-bulk, CSV, ?year=YYYY required)
# ═══════════════════════════════════════════════════════════════════════════

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
        rows = _get_csv("earnings-surprises-bulk", {"year": year})
        if not rows:
            continue
        year_count = 0
        for r in rows:
            sym = _s(r.get("symbol"))
            dt  = _s(r.get("date"))
            if not sym or not dt:
                continue
            actual    = _f(r.get("epsActual"))
            estimated = _f(r.get("epsEstimated"))
            surprise = None
            if actual is not None and estimated and estimated != 0:
                surprise = round((actual - estimated) / abs(estimated) * 100, 2)
            try:
                db.execute(text("""
                    INSERT INTO earnings_surprises
                        (ticker, date, eps_estimated, eps_actual, surprise_pct, fetched_at)
                    VALUES (:t, :d, :ee, :ea, :sp, NOW())
                    ON CONFLICT (ticker, date) DO UPDATE SET
                        eps_estimated = EXCLUDED.eps_estimated,
                        eps_actual    = EXCLUDED.eps_actual,
                        surprise_pct  = EXCLUDED.surprise_pct,
                        fetched_at    = NOW()
                """), {"t": sym, "d": dt, "ee": estimated, "ea": actual, "sp": surprise})
                year_count += 1
                if year_count % 1000 == 0:
                    db.commit()
            except Exception:
                pass
        db.commit()
        total += year_count
        print(f"{TAG} earnings-surprises year={year}: +{year_count:,} (total {total:,})", flush=True)
    print(f"{TAG} Earnings surprises: {total:,} upserted", flush=True)
    return total


# ═══════════════════════════════════════════════════════════════════════════
# 9. Sector Performance  (sector-performance-snapshot, JSON, ?date=YYYY-MM-DD)
# Schema note: snapshot is per (sector, exchange) per date. Old table is
# PK(sector) only — we collapse to NASDAQ rows to keep one row per sector.
# Future: add exchange column + composite PK for full coverage.
# ═══════════════════════════════════════════════════════════════════════════

def harvest_sector_performance(db) -> int:
    print(f"{TAG} === Sector Performance ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS sector_performance (
            sector VARCHAR(100) PRIMARY KEY,
            change_pct FLOAT,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Try today, fall back to yesterday if no data (market closed weekends/holidays)
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

    count = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        # Collapse to NASDAQ rows to keep one row per sector
        if (item.get("exchange") or "").upper() != "NASDAQ":
            continue
        sector = _s(item.get("sector"))
        pct = _f(item.get("averageChange"))
        if not sector or pct is None:
            continue
        try:
            db.execute(text("""
                INSERT INTO sector_performance (sector, change_pct, fetched_at)
                VALUES (:s, :p, NOW())
                ON CONFLICT (sector) DO UPDATE SET
                    change_pct = EXCLUDED.change_pct,
                    fetched_at = NOW()
            """), {"s": sector, "p": pct})
            count += 1
        except Exception:
            pass
    db.commit()
    print(f"{TAG} Sector performance: {count:,} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def run_fmp_bulk_harvest(db=None):
    """Run the full FMP bulk harvest. Idempotent — safe to re-run."""
    print(f"{TAG} ═══════════════════════════════════════════", flush=True)
    print(f"{TAG} Starting FMP Bulk Harvest (patched 2026-05-27)", flush=True)

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
        time.sleep(1)  # tiny breather between datasets

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
