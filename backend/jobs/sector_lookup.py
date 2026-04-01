"""
Ticker-to-sector mapping with DB cache.
Uses Finnhub for sector lookup (yfinance blocked on cloud).
Falls back to a hardcoded map for major tickers.
"""
import os
import time
import httpx
from sqlalchemy import text as sql_text

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "").strip()

# In-memory cache (survives within a process, rebuilt on restart from DB)
_mem_cache: dict[str, str] = {}

# Hardcoded fallback for the most common tickers
KNOWN_SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology", "GOOG": "Technology",
    "META": "Technology", "AMZN": "Consumer Cyclical", "NVDA": "Technology", "AMD": "Technology",
    "INTC": "Technology", "QCOM": "Technology", "AVGO": "Technology", "CRM": "Technology",
    "ORCL": "Technology", "ADBE": "Technology", "NOW": "Technology", "PLTR": "Technology",
    "ARM": "Technology", "SMCI": "Technology", "MU": "Technology", "NFLX": "Communication Services",
    "DIS": "Communication Services", "CMCSA": "Communication Services",
    "TSLA": "Consumer Cyclical", "NKE": "Consumer Cyclical", "SBUX": "Consumer Cyclical",
    "HD": "Consumer Cyclical", "LULU": "Consumer Cyclical", "MCD": "Consumer Defensive",
    "WMT": "Consumer Defensive", "COST": "Consumer Defensive", "PG": "Consumer Defensive",
    "KO": "Consumer Defensive", "PEP": "Consumer Defensive",
    "JPM": "Financial Services", "GS": "Financial Services", "MS": "Financial Services",
    "BAC": "Financial Services", "WFC": "Financial Services", "C": "Financial Services",
    "SCHW": "Financial Services", "BLK": "Financial Services", "V": "Financial Services",
    "MA": "Financial Services", "COIN": "Financial Services",
    "XOM": "Energy", "CVX": "Energy", "OXY": "Energy", "SLB": "Energy",
    "JNJ": "Healthcare", "PFE": "Healthcare", "UNH": "Healthcare", "LLY": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare", "MRNA": "Healthcare", "ISRG": "Healthcare",
    "BA": "Industrials", "CAT": "Industrials", "HON": "Industrials", "UPS": "Industrials",
    "GE": "Industrials", "LMT": "Industrials", "RTX": "Industrials", "DE": "Industrials",
    "BTC": "Crypto", "ETH": "Crypto", "SOL": "Crypto", "MSTR": "Crypto",
    "SPY": "Index", "QQQ": "Index", "IWM": "Index", "DIA": "Index",
    "UBER": "Technology", "ABNB": "Consumer Cyclical", "SNOW": "Technology",
    "NET": "Technology", "CRWD": "Technology", "DDOG": "Technology",
    "F": "Consumer Cyclical", "GM": "Consumer Cyclical", "RIVN": "Consumer Cyclical",
    "T": "Communication Services", "VZ": "Communication Services", "TMUS": "Communication Services",
    "NEE": "Utilities", "SO": "Utilities", "DUK": "Utilities",
    "AMT": "Real Estate", "PLD": "Real Estate", "O": "Real Estate",
}


def get_sector(ticker: str, db=None) -> str:
    """Get sector for a ticker. Checks: memory → DB → Finnhub → hardcoded → 'Other'."""
    ticker = ticker.upper().strip()

    # 1. Memory cache
    if ticker in _mem_cache:
        return _mem_cache[ticker]

    # 2. DB cache
    if db:
        try:
            row = db.execute(sql_text("SELECT sector FROM ticker_sectors WHERE ticker = :t"), {"t": ticker}).first()
            if row and row[0]:
                _mem_cache[ticker] = row[0]
                return row[0]
        except Exception:
            pass

    # 3. Hardcoded
    if ticker in KNOWN_SECTORS:
        sector = KNOWN_SECTORS[ticker]
        _mem_cache[ticker] = sector
        _cache_to_db(ticker, sector, db)
        return sector

    # 4. Finnhub company profile
    if FINNHUB_KEY:
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/stock/profile2",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=5,
            )
            data = r.json()
            industry = data.get("finnhubIndustry", "")
            company_name = data.get("name", "")
            if industry:
                sector = _normalize_sector(industry)
                _mem_cache[ticker] = sector
                _cache_to_db(ticker, sector, db, company_name=company_name, industry=industry)
                return sector
        except Exception:
            pass

    # 5. Fallback
    _mem_cache[ticker] = "Other"
    return "Other"


def _normalize_sector(raw: str) -> str:
    """Map Finnhub industry names to standard sectors."""
    raw_lower = raw.lower()
    mapping = {
        "technology": "Technology", "software": "Technology", "semiconductors": "Technology",
        "hardware": "Technology", "internet": "Technology", "electronic": "Technology",
        "health": "Healthcare", "pharma": "Healthcare", "biotech": "Healthcare", "medical": "Healthcare",
        "bank": "Financial Services", "financial": "Financial Services", "insurance": "Financial Services",
        "capital markets": "Financial Services", "asset management": "Financial Services",
        "energy": "Energy", "oil": "Energy", "gas": "Energy", "petroleum": "Energy",
        "retail": "Consumer Cyclical", "auto": "Consumer Cyclical", "apparel": "Consumer Cyclical",
        "hotel": "Consumer Cyclical", "restaurant": "Consumer Cyclical", "luxury": "Consumer Cyclical",
        "food": "Consumer Defensive", "beverage": "Consumer Defensive", "household": "Consumer Defensive",
        "tobacco": "Consumer Defensive", "packaged": "Consumer Defensive",
        "aerospace": "Industrials", "defense": "Industrials", "construction": "Industrials",
        "industrial": "Industrials", "machinery": "Industrials", "transport": "Industrials",
        "media": "Communication Services", "entertainment": "Communication Services",
        "telecom": "Communication Services", "advertising": "Communication Services",
        "real estate": "Real Estate", "reit": "Real Estate",
        "utility": "Utilities", "electric": "Utilities", "water": "Utilities",
        "mining": "Basic Materials", "chemical": "Basic Materials", "steel": "Basic Materials",
        "metals": "Basic Materials",
    }
    for keyword, sector in mapping.items():
        if keyword in raw_lower:
            return sector
    return raw or "Other"


def _cache_to_db(ticker: str, sector: str, db=None, company_name: str = "", industry: str = "", description: str = "", logo_url: str = ""):
    """Cache sector, company name, industry, description, and logo_url to DB table."""
    if not db:
        return
    try:
        if company_name or description or logo_url:
            db.execute(sql_text("""
                INSERT INTO ticker_sectors (ticker, sector, company_name, industry, description, logo_url)
                VALUES (:t, :s, :cn, :ind, :desc, :logo)
                ON CONFLICT (ticker) DO UPDATE SET sector = :s,
                    company_name = COALESCE(NULLIF(:cn, ''), ticker_sectors.company_name),
                    industry = COALESCE(NULLIF(:ind, ''), ticker_sectors.industry),
                    description = COALESCE(NULLIF(:desc, ''), ticker_sectors.description),
                    logo_url = COALESCE(NULLIF(:logo, ''), ticker_sectors.logo_url)
            """), {"t": ticker, "s": sector, "cn": company_name, "ind": industry, "desc": description, "logo": logo_url})
        else:
            db.execute(sql_text("""
                INSERT INTO ticker_sectors (ticker, sector) VALUES (:t, :s)
                ON CONFLICT (ticker) DO UPDATE SET sector = :s
            """), {"t": ticker, "s": sector})
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def backfill_sectors_batch(max_tickers: int = 200) -> dict:
    """Look up and set sectors for predictions missing sector data."""
    from database import BgSessionLocal as SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(sql_text("""
            SELECT DISTINCT ticker FROM predictions
            WHERE (sector IS NULL OR sector = '' OR sector = 'Other')
            LIMIT :lim
        """), {"lim": max_tickers}).fetchall()
    finally:
        db.close()

    if not rows:
        return {"tickers_processed": 0, "updated": 0}

    tickers = [r[0] for r in rows]
    updated = 0

    for i, ticker in enumerate(tickers):
        db = SessionLocal()
        try:
            sector = get_sector(ticker, db)
            if sector and sector != "Other":
                db.execute(sql_text(
                    "UPDATE predictions SET sector = :s WHERE ticker = :t AND (sector IS NULL OR sector = '' OR sector = 'Other')"
                ), {"s": sector, "t": ticker})
                db.commit()
                updated += 1
        except Exception:
            db.rollback()
        finally:
            db.close()
        if (i + 1) % 20 == 0:
            time.sleep(0.5)  # Brief pause every 20 tickers

    return {"tickers_processed": len(tickers), "updated": updated, "remaining": "check again"}


def backfill_company_names():
    """Populate ticker_sectors with company_name for all unique tickers in predictions.
    Uses Finnhub for lookup, caches in ticker_sectors. Runs once at startup."""
    from database import BgSessionLocal as SessionLocal

    db = SessionLocal()
    try:
        # Find tickers missing company_name in ticker_sectors
        rows = db.execute(sql_text("""
            SELECT DISTINCT p.ticker
            FROM predictions p
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE ts.company_name IS NULL OR ts.company_name = ''
        """)).fetchall()
    finally:
        db.close()

    if not rows:
        print("[CompanyBackfill] All tickers already have company names")
        return

    tickers = [r[0] for r in rows]
    updated = 0

    for i, ticker in enumerate(tickers):
        db = SessionLocal()
        try:
            # Try Finnhub profile lookup
            company_name = ""
            industry = ""
            sector = KNOWN_SECTORS.get(ticker, "Other")

            if FINNHUB_KEY:
                try:
                    r = httpx.get(
                        "https://finnhub.io/api/v1/stock/profile2",
                        params={"symbol": ticker, "token": FINNHUB_KEY},
                        timeout=5,
                    )
                    data = r.json()
                    company_name = data.get("name", "")
                    industry = data.get("finnhubIndustry", "")
                    if industry:
                        sector = _normalize_sector(industry)
                except Exception:
                    pass

            if company_name:
                _cache_to_db(ticker, sector, db, company_name=company_name, industry=industry)
                updated += 1
            elif not company_name:
                # Ensure at least the sector row exists
                _cache_to_db(ticker, sector, db)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()

        # Rate limit: Finnhub free tier is 60/min
        if (i + 1) % 30 == 0:
            time.sleep(1)

    print(f"[CompanyBackfill] Processed {len(tickers)} tickers, updated {updated} company names")


def _first_sentence(text: str, max_len: int = 150) -> str:
    """Extract the first sentence, capped at max_len characters."""
    if not text:
        return ""
    # Split on period followed by space or end of string
    for end in (".", ".\n"):
        idx = text.find(end)
        if idx > 0 and idx < 200:
            sentence = text[:idx + 1].strip()
            return sentence[:max_len]
    return text[:max_len].strip()


def backfill_descriptions():
    """Populate ticker_sectors description + logo_url using FMP /stable/profile.
    Prioritizes tickers with most predictions. Max 50 per run (FMP 300/day limit).
    Skips tickers that already have both description and logo_url."""
    import httpx
    from database import BgSessionLocal as SessionLocal

    fmp_key = os.getenv("FMP_KEY", "").strip()
    if not fmp_key:
        print("[DescBackfill] FMP_KEY not set, skipping")
        return

    db = SessionLocal()
    try:
        # Prioritize tickers with most predictions that are missing description or logo
        rows = db.execute(sql_text("""
            SELECT p.ticker, COUNT(*) as cnt
            FROM predictions p
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE (ts.description IS NULL OR ts.description = ''
                   OR ts.logo_url IS NULL OR ts.logo_url = '')
            GROUP BY p.ticker
            ORDER BY cnt DESC
            LIMIT 50
        """)).fetchall()
    finally:
        db.close()

    if not rows:
        print("[DescBackfill] All tickers already have descriptions + logos")
        return

    tickers = [r[0] for r in rows]
    updated = 0
    print(f"[DescBackfill] {len(tickers)} tickers need descriptions/logos (using FMP)")

    for i, ticker in enumerate(tickers):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/stable/profile",
                params={"symbol": ticker, "apikey": fmp_key},
                timeout=10,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if isinstance(data, list) and data:
                data = data[0]
            if not isinstance(data, dict):
                continue

            company_name = data.get("companyName") or ""
            description_raw = data.get("description") or ""
            description = _first_sentence(description_raw)
            logo_url = data.get("image") or ""
            sector_raw = data.get("sector") or ""
            industry_raw = data.get("industry") or ""
            sector = _normalize_sector(sector_raw) if sector_raw else KNOWN_SECTORS.get(ticker, "Other")

            if description or company_name or logo_url:
                db = SessionLocal()
                try:
                    _cache_to_db(ticker, sector, db,
                                 company_name=company_name,
                                 industry=industry_raw,
                                 description=description,
                                 logo_url=logo_url)
                    updated += 1
                finally:
                    db.close()
        except Exception as e:
            if i < 3:
                print(f"[DescBackfill] Error for {ticker}: {e}")

        # Rate limit: ~5 per second to stay within 300/day
        time.sleep(0.5)

    print(f"[DescBackfill] Done: {updated}/{len(tickers)} descriptions/logos added via FMP")
