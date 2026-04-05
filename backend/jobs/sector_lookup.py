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


def _cache_to_db(ticker: str, sector: str, db=None, company_name: str = "", industry: str = "", description: str = "", logo_url: str = "", logo_domain: str = ""):
    """Cache sector, company name, industry, description, logo_url, and logo_domain to DB table."""
    if not db:
        return
    # Always ensure a logo_url — fall back to FMP CDN pattern
    if not logo_url:
        logo_url = f"https://financialmodelingprep.com/image-stock/{ticker.upper()}.png"
    try:
        db.execute(sql_text("""
            INSERT INTO ticker_sectors (ticker, sector, company_name, industry, description, logo_url, logo_domain)
            VALUES (:t, :s, :cn, :ind, :desc, :logo, :dom)
            ON CONFLICT (ticker) DO UPDATE SET sector = :s,
                company_name = COALESCE(NULLIF(:cn, ''), ticker_sectors.company_name),
                industry = COALESCE(NULLIF(:ind, ''), ticker_sectors.industry),
                description = COALESCE(NULLIF(:desc, ''), ticker_sectors.description),
                logo_url = COALESCE(NULLIF(:logo, ''), ticker_sectors.logo_url),
                logo_domain = COALESCE(NULLIF(:dom, ''), ticker_sectors.logo_domain)
        """), {"t": ticker, "s": sector, "cn": company_name, "ind": industry, "desc": description, "logo": logo_url, "dom": logo_domain})
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
    for end in (".", ".\n"):
        idx = text.find(end)
        if idx > 0 and idx < 200:
            sentence = text[:idx + 1].strip()
            return sentence[:max_len]
    return text[:max_len].strip()


def _first_two_sentences(text: str, max_len: int = 280) -> str:
    """Extract the first two sentences for a meaningful description."""
    if not text:
        return ""
    import re
    sentences = re.split(r'(?<=\.)\s+', text.strip())
    result = ""
    for s in sentences[:2]:
        if len(result) + len(s) + 1 > max_len:
            break
        result = (result + " " + s).strip()
    return result or text[:max_len].strip()


def _extract_domain(url: str) -> str:
    """Extract domain from URL. 'https://www.apple.com/abc' -> 'apple.com'"""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _get_tickers_needing_data(limit: int) -> list:
    """Get tickers missing description or logo, prioritized by prediction count.
    Also re-fetches tickers where description equals company_name (bad data)."""
    from database import BgSessionLocal as SessionLocal
    db = SessionLocal()
    try:
        rows = db.execute(sql_text("""
            SELECT p.ticker, COUNT(*) as cnt
            FROM predictions p
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE ts.description IS NULL OR ts.description = '' OR LENGTH(ts.description) < 50
                  OR ts.logo_domain IS NULL OR ts.logo_domain = ''
                  OR ts.description = ts.company_name
            GROUP BY p.ticker
            ORDER BY cnt DESC
            LIMIT :lim
        """), {"lim": limit}).fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        print(f"[DescBackfill] Query error: {e}")
        return []
    finally:
        db.close()


def backfill_descriptions():
    """Populate ticker_sectors using FMP /stable/profile endpoint.
    Fetches: company name, description (2 sentences), logo URL, logo domain, sector, industry.
    Max 50 tickers per run. 0.5s delay between calls. Handles errors gracefully."""
    import httpx
    from database import BgSessionLocal as SessionLocal

    fmp_key = os.getenv("FMP_KEY", "").strip()
    if not fmp_key:
        print("[DescBackfill] FMP_KEY not set, trying yfinance fallback")
        backfill_descriptions_yfinance()
        return

    tickers = _get_tickers_needing_data(50)
    if not tickers:
        print("[DescBackfill] All tickers already have descriptions + logos")
        return

    updated = 0
    errors = 0
    print(f"[DescBackfill-FMP] Starting: {len(tickers)} tickers")

    for i, ticker in enumerate(tickers):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/stable/profile",
                params={"symbol": ticker, "apikey": fmp_key},
                timeout=10,
            )

            if r.status_code != 200:
                if i < 5:
                    print(f"[DescBackfill-FMP] {ticker}: HTTP {r.status_code}")
                errors += 1
                time.sleep(0.5)
                continue

            # Parse JSON safely
            try:
                data = r.json()
            except Exception:
                if i < 5:
                    print(f"[DescBackfill-FMP] {ticker}: invalid JSON response")
                errors += 1
                time.sleep(0.5)
                continue

            if isinstance(data, list):
                data = data[0] if data else {}
            if not isinstance(data, dict) or not data:
                time.sleep(0.5)
                continue

            company_name = data.get("companyName") or ""
            description_raw = data.get("description") or ""
            description = _first_two_sentences(description_raw)
            logo_url = data.get("image") or ""
            website = data.get("website") or ""
            logo_domain = _extract_domain(website)
            sector_raw = data.get("sector") or ""
            industry_raw = data.get("industry") or ""
            sector = _normalize_sector(sector_raw) if sector_raw else KNOWN_SECTORS.get(ticker, "Other")

            if description or company_name or logo_url or logo_domain:
                db = SessionLocal()
                try:
                    _cache_to_db(ticker, sector, db,
                                 company_name=company_name,
                                 industry=industry_raw,
                                 description=description,
                                 logo_url=logo_url,
                                 logo_domain=logo_domain)
                    updated += 1
                    if updated <= 3 or updated % 10 == 0:
                        print(f"[DescBackfill-FMP] {ticker}: OK (name={company_name[:30]}, desc={len(description)}ch, domain={logo_domain})")
                finally:
                    db.close()

        except Exception as e:
            errors += 1
            if i < 5:
                print(f"[DescBackfill-FMP] {ticker}: {type(e).__name__}: {e}")

        time.sleep(0.5)

    print(f"[DescBackfill-FMP] Done: {updated} updated, {errors} errors, {len(tickers)} total")


# ── FALLBACK: yfinance version (slower, no API key needed) ──────────────────
# Switch to this if FMP is unavailable by calling backfill_descriptions_yfinance()
# from main.py instead of backfill_descriptions().

def backfill_descriptions_yfinance():
    """Fallback: populate ticker_sectors using yfinance (free, no key).
    Slower (2s delay) and max 20 tickers per run to avoid 429 rate limits."""
    from database import BgSessionLocal as SessionLocal

    tickers = _get_tickers_needing_data(20)
    if not tickers:
        print("[DescBackfill-YF] All tickers already have descriptions")
        return

    updated = 0
    print(f"[DescBackfill-YF] Starting: {len(tickers)} tickers (yfinance fallback)")

    for i, ticker in enumerate(tickers):
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            info = stock.info or {}

            company_name = info.get("shortName") or info.get("longName") or ""
            summary = info.get("longBusinessSummary") or ""
            description = _first_two_sentences(summary)
            sector_raw = info.get("sector") or ""
            industry_raw = info.get("industry") or ""
            website = info.get("website") or ""
            logo_domain = _extract_domain(website)
            sector = _normalize_sector(sector_raw) if sector_raw else KNOWN_SECTORS.get(ticker, "Other")

            if description or company_name:
                db = SessionLocal()
                try:
                    _cache_to_db(ticker, sector, db,
                                 company_name=company_name,
                                 industry=industry_raw,
                                 description=description,
                                 logo_domain=logo_domain)
                    updated += 1
                finally:
                    db.close()
        except Exception as e:
            if i < 3:
                print(f"[DescBackfill-YF] {ticker}: {e}")

        time.sleep(2)  # Slower to avoid Yahoo 429s

    print(f"[DescBackfill-YF] Done: {updated}/{len(tickers)} via yfinance")
