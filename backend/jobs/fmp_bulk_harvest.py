"""
FMP Bulk Harvest — one-time download of all high-value datasets before
downgrading from Ultimate ($139/mo) to Starter ($29/mo).

Creates new tables, fetches bulk endpoints, upserts data. Idempotent.
"""
import os
import time
import httpx
from datetime import datetime
from sqlalchemy import text

FMP_KEY = os.getenv("FMP_KEY", "")
BASE = "https://financialmodelingprep.com"
TAG = "[FMPHarvest]"

# Debug counter so we only emit verbose URL/body logs for the FIRST call of each run
_first_response_logged = {"done": False}


def _redact_url(url: str) -> str:
    """Strip API key from URL for safe logging."""
    if not FMP_KEY:
        return url
    return url.replace(FMP_KEY, "XXX")


def _get(path: str, params: dict = None, timeout: int = 60) -> list | dict | None:
    """Call FMP API. Returns parsed JSON or None.

    Phase 4 debug logging: logs full redacted URL on EVERY call, plus the
    response status and body snippet for the FIRST call of each run.
    """
    if not params:
        params = {}
    params["apikey"] = FMP_KEY
    last_status = None
    last_body = ""
    # /api/v3/ was deprecated 2025-08-31 and now returns 403 "Legacy Endpoint".
    # Only the /stable/ namespace is supported on FMP Ultimate.
    for prefix in ["/stable/"]:
        url = f"{BASE}{prefix}{path}"
        # Build the full URL with query params for logging
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode({k: v for k, v in params.items() if k != 'apikey'})}&apikey=XXX"
        print(f"{TAG}-DEBUG calling: {full_url}", flush=True)
        try:
            r = httpx.get(url, params=params, timeout=timeout)
            last_status = r.status_code
            last_body = r.text[:200] if r.text else ""
            # First-response debug log (one per run)
            if not _first_response_logged["done"]:
                print(f"{TAG}-DEBUG first response status={r.status_code} body={last_body}", flush=True)
                _first_response_logged["done"] = True
            if r.status_code == 200:
                data = r.json()
                if data and (isinstance(data, list) or isinstance(data, dict)):
                    return data
                print(f"{TAG}-DEBUG {path} prefix {prefix} returned 200 but empty/invalid body", flush=True)
            else:
                print(f"{TAG}-DEBUG {path} prefix {prefix} returned status={r.status_code}", flush=True)
        except Exception as e:
            print(f"{TAG} {_redact_url(url)} error: {e}", flush=True)
    print(f"{TAG} {path} — no data from any prefix (last_status={last_status} last_body={last_body[:80]})", flush=True)
    return None


def _ensure_table(db, ddl: str):
    """Create table if not exists."""
    try:
        db.execute(text(ddl))
        db.commit()
    except Exception:
        db.rollback()


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 1: Company Profiles Bulk
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

    data = _get("profile-bulk")
    if not data or not isinstance(data, list):
        # Fallback: try profile?symbol= for top tickers
        print(f"{TAG} Bulk endpoint failed, trying top tickers individually", flush=True)
        rows = db.execute(text("""
            SELECT DISTINCT ticker FROM predictions
            ORDER BY ticker LIMIT 2000
        """)).fetchall()
        data = []
        for i, row in enumerate(rows):
            resp = _get(f"profile/{row[0]}")
            if resp and isinstance(resp, list):
                data.extend(resp)
            if (i + 1) % 100 == 0:
                print(f"{TAG} Profiles: {i+1}/{len(rows)} tickers fetched", flush=True)
            time.sleep(0.05)

    count = 0
    for item in data:
        sym = item.get("symbol", "")
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO company_profiles (ticker, company_name, description, sector, industry,
                    market_cap, country, exchange, website, ipo_date, employees,
                    is_etf, is_actively_trading, logo_url, ceo, city, state, currency, fetched_at)
                VALUES (:t, :name, :desc, :sector, :industry, :mcap, :country, :exchange,
                    :website, :ipo, :emp, :etf, :active, :logo, :ceo, :city, :state, :currency, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    company_name = EXCLUDED.company_name, description = EXCLUDED.description,
                    sector = EXCLUDED.sector, industry = EXCLUDED.industry,
                    market_cap = EXCLUDED.market_cap, country = EXCLUDED.country,
                    exchange = EXCLUDED.exchange, website = EXCLUDED.website,
                    ipo_date = EXCLUDED.ipo_date, employees = EXCLUDED.employees,
                    is_etf = EXCLUDED.is_etf, is_actively_trading = EXCLUDED.is_actively_trading,
                    logo_url = EXCLUDED.logo_url, ceo = EXCLUDED.ceo,
                    city = EXCLUDED.city, state = EXCLUDED.state, currency = EXCLUDED.currency,
                    fetched_at = NOW()
            """), {
                "t": sym, "name": item.get("companyName"), "desc": item.get("description"),
                "sector": item.get("sector"), "industry": item.get("industry"),
                "mcap": item.get("mktCap"), "country": item.get("country"),
                "exchange": item.get("exchangeShortName") or item.get("exchange"),
                "website": item.get("website"), "ipo": item.get("ipoDate"),
                "emp": item.get("fullTimeEmployees"), "etf": item.get("isEtf", False),
                "active": item.get("isActivelyTrading", True),
                "logo": item.get("image"), "ceo": item.get("ceo"),
                "city": item.get("city"), "state": item.get("state"),
                "currency": item.get("currency"),
            })
            count += 1
        except Exception:
            pass
        if count % 500 == 0 and count > 0:
            db.commit()

    db.commit()
    print(f"{TAG} Company profiles: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 2: Analyst Consensus Bulk
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

    data = _get("upgrades-downgrades-consensus-bulk")
    if not data or not isinstance(data, list):
        print(f"{TAG} Consensus bulk not available", flush=True)
        return 0

    count = 0
    for item in data:
        sym = item.get("symbol", "")
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO analyst_consensus (ticker, strong_buy, buy, hold, sell, strong_sell, consensus, fetched_at)
                VALUES (:t, :sb, :b, :h, :s, :ss, :c, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    strong_buy = EXCLUDED.strong_buy, buy = EXCLUDED.buy, hold = EXCLUDED.hold,
                    sell = EXCLUDED.sell, strong_sell = EXCLUDED.strong_sell,
                    consensus = EXCLUDED.consensus, fetched_at = NOW()
            """), {
                "t": sym, "sb": item.get("strongBuy", 0), "b": item.get("buy", 0),
                "h": item.get("hold", 0), "s": item.get("sell", 0),
                "ss": item.get("strongSell", 0), "c": item.get("consensus"),
            })
            count += 1
        except Exception:
            pass
        if count % 500 == 0 and count > 0:
            db.commit()

    db.commit()
    print(f"{TAG} Analyst consensus: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 3: Price Target Summary Bulk
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

    data = _get("price-target-summary-bulk")
    if not data or not isinstance(data, list):
        print(f"{TAG} Price target summary bulk not available", flush=True)
        return 0

    count = 0
    for item in data:
        sym = item.get("symbol", "")
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO price_target_summary (ticker, last_month_avg, last_month_high, last_month_low,
                    last_quarter_avg, last_quarter_high, last_quarter_low,
                    last_year_avg, last_year_high, last_year_low, current_price, fetched_at)
                VALUES (:t, :lma, :lmh, :lml, :lqa, :lqh, :lql, :lya, :lyh, :lyl, :cp, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    last_month_avg = EXCLUDED.last_month_avg, last_month_high = EXCLUDED.last_month_high,
                    last_month_low = EXCLUDED.last_month_low, last_quarter_avg = EXCLUDED.last_quarter_avg,
                    last_quarter_high = EXCLUDED.last_quarter_high, last_quarter_low = EXCLUDED.last_quarter_low,
                    last_year_avg = EXCLUDED.last_year_avg, last_year_high = EXCLUDED.last_year_high,
                    last_year_low = EXCLUDED.last_year_low, current_price = EXCLUDED.current_price,
                    fetched_at = NOW()
            """), {
                "t": sym,
                "lma": item.get("lastMonthAvgPriceTarget"), "lmh": item.get("lastMonthHighPriceTarget"),
                "lml": item.get("lastMonthLowPriceTarget"), "lqa": item.get("lastQuarterAvgPriceTarget"),
                "lqh": item.get("lastQuarterHighPriceTarget"), "lql": item.get("lastQuarterLowPriceTarget"),
                "lya": item.get("lastYearAvgPriceTarget"), "lyh": item.get("lastYearHighPriceTarget"),
                "lyl": item.get("lastYearLowPriceTarget"), "cp": item.get("lastPrice"),
            })
            count += 1
        except Exception:
            pass
        if count % 500 == 0 and count > 0:
            db.commit()

    db.commit()
    print(f"{TAG} Price target summary: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 5: Ratings Snapshot Bulk
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

    data = _get("rating-bulk")
    if not data or not isinstance(data, list):
        print(f"{TAG} Rating bulk not available", flush=True)
        return 0

    count = 0
    for item in data:
        sym = item.get("symbol", "")
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO stock_ratings (ticker, rating, score, recommendation,
                    dcf_score, roe_score, de_score, pe_score, pb_score, fetched_at)
                VALUES (:t, :r, :s, :rec, :dcf, :roe, :de, :pe, :pb, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    rating = EXCLUDED.rating, score = EXCLUDED.score,
                    recommendation = EXCLUDED.recommendation,
                    dcf_score = EXCLUDED.dcf_score, roe_score = EXCLUDED.roe_score,
                    de_score = EXCLUDED.de_score, pe_score = EXCLUDED.pe_score,
                    pb_score = EXCLUDED.pb_score, fetched_at = NOW()
            """), {
                "t": sym, "r": item.get("rating"), "s": item.get("ratingScore"),
                "rec": item.get("ratingRecommendation"),
                "dcf": item.get("ratingDetailsDCFScore"), "roe": item.get("ratingDetailsROEScore"),
                "de": item.get("ratingDetailsDEScore"), "pe": item.get("ratingDetailsPEScore"),
                "pb": item.get("ratingDetailsPBScore"),
            })
            count += 1
        except Exception:
            pass
        if count % 500 == 0 and count > 0:
            db.commit()

    db.commit()
    print(f"{TAG} Stock ratings: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 6: Earnings Calendar (2025 + 2026)
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

    count = 0
    for year_range in [
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", "2026-12-31"),
    ]:
        data = _get("earning-calendar", {"from": year_range[0], "to": year_range[1]})
        if not data or not isinstance(data, list):
            continue
        print(f"{TAG} Earnings {year_range[0][:4]}: {len(data)} entries", flush=True)
        for item in data:
            sym = item.get("symbol", "")
            dt = item.get("date", "")
            if not sym or not dt:
                continue
            try:
                db.execute(text("""
                    INSERT INTO earnings_history (ticker, date, eps_estimated, eps_actual,
                        revenue_estimated, revenue_actual, fiscal_period, fetched_at)
                    VALUES (:t, :d, :ee, :ea, :re, :ra, :fp, NOW())
                    ON CONFLICT (ticker, date) DO UPDATE SET
                        eps_estimated = EXCLUDED.eps_estimated, eps_actual = EXCLUDED.eps_actual,
                        revenue_estimated = EXCLUDED.revenue_estimated, revenue_actual = EXCLUDED.revenue_actual,
                        fiscal_period = EXCLUDED.fiscal_period, fetched_at = NOW()
                """), {
                    "t": sym, "d": dt, "ee": item.get("epsEstimated"),
                    "ea": item.get("eps"), "re": item.get("revenueEstimated"),
                    "ra": item.get("revenue"), "fp": item.get("fiscalDateEnding"),
                })
                count += 1
            except Exception:
                pass
        db.commit()

    print(f"{TAG} Earnings calendar: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 7: Stock Peers Bulk
# ═══════════════════════════════════════════════════════════════════════════

def harvest_stock_peers(db) -> int:
    print(f"{TAG} === Stock Peers ===", flush=True)
    _ensure_table(db, """
        CREATE TABLE IF NOT EXISTS stock_peers (
            ticker VARCHAR(20) NOT NULL,
            peer_ticker VARCHAR(20) NOT NULL,
            fetched_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (ticker, peer_ticker)
        )
    """)

    data = _get("stock-peers-bulk")
    if not data or not isinstance(data, list):
        print(f"{TAG} Stock peers bulk not available", flush=True)
        return 0

    count = 0
    for item in data:
        sym = item.get("symbol", "")
        peers = item.get("peersList", [])
        if not sym or not isinstance(peers, list):
            continue
        for peer in peers:
            if not peer or peer == sym:
                continue
            try:
                db.execute(text("""
                    INSERT INTO stock_peers (ticker, peer_ticker, fetched_at)
                    VALUES (:t, :p, NOW())
                    ON CONFLICT (ticker, peer_ticker) DO NOTHING
                """), {"t": sym, "p": peer})
                count += 1
            except Exception:
                pass
        if count % 1000 == 0 and count > 0:
            db.commit()

    db.commit()
    print(f"{TAG} Stock peers: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 8: Key Metrics TTM Bulk
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

    data = _get("key-metrics-ttm-bulk")
    if not data or not isinstance(data, list):
        print(f"{TAG} Key metrics bulk not available", flush=True)
        return 0

    count = 0
    for item in data:
        sym = item.get("symbol", "")
        if not sym:
            continue
        try:
            db.execute(text("""
                INSERT INTO key_metrics (ticker, market_cap, pe_ratio, eps, dividend_yield,
                    revenue, net_income, roe, debt_to_equity, current_ratio,
                    book_value_per_share, free_cash_flow_per_share,
                    price_to_book, price_to_sales, ev_to_ebitda, fetched_at)
                VALUES (:t, :mc, :pe, :eps, :dy, :rev, :ni, :roe, :dte, :cr,
                    :bvps, :fcfps, :ptb, :pts, :eve, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    market_cap = EXCLUDED.market_cap, pe_ratio = EXCLUDED.pe_ratio,
                    eps = EXCLUDED.eps, dividend_yield = EXCLUDED.dividend_yield,
                    revenue = EXCLUDED.revenue, net_income = EXCLUDED.net_income,
                    roe = EXCLUDED.roe, debt_to_equity = EXCLUDED.debt_to_equity,
                    current_ratio = EXCLUDED.current_ratio,
                    book_value_per_share = EXCLUDED.book_value_per_share,
                    free_cash_flow_per_share = EXCLUDED.free_cash_flow_per_share,
                    price_to_book = EXCLUDED.price_to_book,
                    price_to_sales = EXCLUDED.price_to_sales,
                    ev_to_ebitda = EXCLUDED.ev_to_ebitda, fetched_at = NOW()
            """), {
                "t": sym, "mc": item.get("marketCapTTM"), "pe": item.get("peRatioTTM"),
                "eps": item.get("netIncomePerShareTTM"), "dy": item.get("dividendYieldTTM"),
                "rev": item.get("revenueTTM"), "ni": item.get("netIncomeTTM"),
                "roe": item.get("roeTTM"), "dte": item.get("debtToEquityTTM"),
                "cr": item.get("currentRatioTTM"), "bvps": item.get("bookValuePerShareTTM"),
                "fcfps": item.get("freeCashFlowPerShareTTM"),
                "ptb": item.get("priceToBookRatioTTM"), "pts": item.get("priceToSalesRatioTTM"),
                "eve": item.get("enterpriseValueOverEBITDATTM"),
            })
            count += 1
        except Exception:
            pass
        if count % 500 == 0 and count > 0:
            db.commit()

    db.commit()
    print(f"{TAG} Key metrics: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 9: Earnings Surprises Bulk
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

    data = _get("earnings-surprises-bulk")
    if not data or not isinstance(data, list):
        print(f"{TAG} Earnings surprises bulk not available", flush=True)
        return 0

    count = 0
    for item in data:
        sym = item.get("symbol", "")
        dt = item.get("date", "")
        if not sym or not dt:
            continue
        actual = item.get("actualEarningResult")
        estimated = item.get("estimatedEarning")
        surprise = None
        if actual is not None and estimated and estimated != 0:
            surprise = round((actual - estimated) / abs(estimated) * 100, 2)
        try:
            db.execute(text("""
                INSERT INTO earnings_surprises (ticker, date, eps_estimated, eps_actual, surprise_pct, fetched_at)
                VALUES (:t, :d, :ee, :ea, :sp, NOW())
                ON CONFLICT (ticker, date) DO UPDATE SET
                    eps_estimated = EXCLUDED.eps_estimated, eps_actual = EXCLUDED.eps_actual,
                    surprise_pct = EXCLUDED.surprise_pct, fetched_at = NOW()
            """), {"t": sym, "d": dt, "ee": estimated, "ea": actual, "sp": surprise})
            count += 1
        except Exception:
            pass
        if count % 1000 == 0 and count > 0:
            db.commit()

    db.commit()
    print(f"{TAG} Earnings surprises: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# PRIORITY 10: Sector/Industry Performance
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

    count = 0
    for endpoint in ["sector-performance", "sectors-performance"]:
        data = _get(endpoint)
        if data and isinstance(data, list):
            for item in data:
                name = item.get("sector", "")
                if not name:
                    continue
                pct_str = item.get("changesPercentage", "0")
                try:
                    pct = float(str(pct_str).replace("%", ""))
                except (ValueError, TypeError):
                    pct = 0
                try:
                    db.execute(text("""
                        INSERT INTO sector_performance (sector, change_pct, fetched_at)
                        VALUES (:s, :p, NOW())
                        ON CONFLICT (sector) DO UPDATE SET change_pct = EXCLUDED.change_pct, fetched_at = NOW()
                    """), {"s": name, "p": pct})
                    count += 1
                except Exception:
                    pass
            db.commit()
            break

    print(f"{TAG} Sector performance: {count} upserted", flush=True)
    return count


# ═══════════════════════════════════════════════════════════════════════════
# MAIN HARVEST
# ═══════════════════════════════════════════════════════════════════════════

def run_fmp_bulk_harvest(db=None):
    """Run the full FMP bulk harvest. Idempotent — safe to re-run."""
    print(f"{TAG} ═══════════════════════════════════════════", flush=True)
    print(f"{TAG} Starting FMP Bulk Harvest", flush=True)

    if not FMP_KEY:
        print(f"{TAG} No FMP_KEY — skipping", flush=True)
        return

    start = time.time()
    results = {}

    harvests = [
        ("company_profiles", harvest_company_profiles),
        ("analyst_consensus", harvest_analyst_consensus),
        ("price_target_summary", harvest_price_target_summary),
        ("stock_ratings", harvest_stock_ratings),
        ("earnings_calendar", harvest_earnings_calendar),
        ("stock_peers", harvest_stock_peers),
        ("key_metrics", harvest_key_metrics),
        ("earnings_surprises", harvest_earnings_surprises),
        ("sector_performance", harvest_sector_performance),
    ]

    for name, fn in harvests:
        try:
            count = fn(db)
            results[name] = count
        except Exception as e:
            print(f"{TAG} {name} FAILED: {e}", flush=True)
            results[name] = f"ERROR: {e}"
        time.sleep(2)  # Brief pause between datasets

    elapsed = time.time() - start
    print(f"{TAG} ═══════════════════════════════════════════", flush=True)
    print(f"{TAG} HARVEST COMPLETE in {elapsed:.0f}s", flush=True)
    for name, count in results.items():
        print(f"{TAG}   {name}: {count}", flush=True)
    print(f"{TAG} Safe to downgrade FMP plan after verifying data.", flush=True)
