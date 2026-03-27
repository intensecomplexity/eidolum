"""
Financial news scraper — uses Finnhub Company News API to find REAL analyst
upgrades, downgrades, and price target changes with actual article URLs.

Uses 3-layer defense + extracts the real forecaster name from headlines
(never attributes to the platform).
"""
import os
import re
import time
import threading
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Prediction, Forecaster
from jobs.prediction_validator import (
    is_real_prediction,
    get_direction,
    extract_forecaster_name,
    validate_prediction,
    resolve_forecaster_alias,
    FORECASTER_ALIASES,
)

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

# Track when each ticker last produced a NEW prediction — used by fast scraper to skip cold tickers
TICKER_LAST_FOUND = {}  # ticker -> datetime of last new prediction found
LAST_FULL_SCAN = None   # datetime of last full scraper run
ALL_TICKERS = None       # populated on first run from Finnhub

# Lock to prevent simultaneous scraper runs (shared by all scrapers)
SCRAPER_LOCK = threading.Lock()

# Hardcoded fallback if Finnhub symbol fetch fails
FALLBACK_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AVGO", "ORCL",
    "CRM", "ADBE", "AMD", "INTC", "QCOM", "NFLX", "CSCO", "IBM", "TXN", "MU",
    "AMAT", "LRCX", "MRVL", "SNPS", "CDNS", "FTNT", "PANW", "CRWD", "ZS",
    "NOW", "SNOW", "DDOG", "NET", "MDB", "OKTA", "ZM", "HUBS", "WDAY",
    "ARM", "SMCI", "MCHP", "ON", "ADI", "NXPI", "MPWR",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "V", "MA",
    "COF", "USB", "PNC", "TFC",
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "REGN", "VRTX", "ISRG", "MRNA",
    "WMT", "PG", "COST", "PEP", "KO", "MCD", "SBUX", "TGT",
    "NKE", "LULU", "CMG", "HLT", "MAR",
    "HD", "LOW", "BKNG", "ABNB", "UBER", "DASH", "PINS", "SNAP", "ETSY",
    "DIS", "CMCSA", "ROKU", "SPOT", "RBLX", "EA",
    "T", "VZ", "TMUS",
    "BA", "CAT", "GE", "HON", "LMT", "RTX", "NOC", "DE",
    "UPS", "FDX", "WM", "EMR", "ETN",
    "F", "GM", "RIVN", "LCID", "NIO",
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY",
    "NEE", "DUK", "SO",
    "AMT", "PLD", "CCI", "EQIX", "SPG", "O",
    "SQ", "PYPL", "COIN", "SOFI", "AFRM", "HOOD", "FIS", "FISV",
    "PLTR", "AI", "IONQ",
    "LIN", "APD", "SHW", "NEM", "FCX",
    "SPY", "QQQ", "ARKK", "XLF", "XLE", "XLK", "XLV",
    "GLD", "SLV", "IWM", "DIA", "SOXX", "SMH", "XBI",
]


def _fetch_all_us_tickers():
    """Fetch all US stock symbols from Finnhub. Returns 1000+ tickers."""
    if not FINNHUB_KEY:
        return FALLBACK_TICKERS
    try:
        r = httpx.get(
            "https://finnhub.io/api/v1/stock/symbol",
            params={"exchange": "US", "token": FINNHUB_KEY},
            timeout=30,
        )
        symbols = r.json()
        tickers = [
            s["symbol"] for s in symbols
            if s.get("type") in ("Common Stock", "ETP", "ETF")
        ]
        # Remove tickers with special characters, keep clean 1-5 char symbols
        tickers = [t for t in tickers if "." not in t and "-" not in t and 1 <= len(t) <= 5]
        print(f"[Tickers] Fetched {len(tickers)} US symbols from Finnhub")
        return tickers if tickers else FALLBACK_TICKERS
    except Exception as e:
        print(f"[Tickers] Error fetching symbols, using fallback: {e}")
        return FALLBACK_TICKERS


def ensure_tickers():
    """Load all tickers once, cache globally."""
    global ALL_TICKERS
    if ALL_TICKERS is None:
        ALL_TICKERS = _fetch_all_us_tickers()
    return ALL_TICKERS


def resolve_redirect(url):
    """Follow Finnhub redirect to get real article URL."""
    try:
        r = httpx.head(url, follow_redirects=True, timeout=5)
        final = str(r.url)
        if final and final.startswith("http") and "finnhub.io" not in final:
            return final
    except Exception:
        pass
    return url


def archive_url(url):
    """Archive via Wayback Machine."""
    try:
        r = httpx.get(
            f"https://web.archive.org/save/{url}",
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "eidolum-archiver/1.0"},
        )
        loc = r.headers.get("content-location", "")
        if loc:
            return f"https://web.archive.org{loc}"
    except Exception:
        pass
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"https://web.archive.org/web/{ts}/{url}"


def find_forecaster(name, db):
    """Find forecaster using alias resolution. Creates new only for known/multi-word firms."""
    if not name or len(name.strip()) < 3:
        return None

    canonical = resolve_forecaster_alias(name.strip())

    # Try exact match on canonical name
    f = db.query(Forecaster).filter(Forecaster.name == canonical).first()
    if f:
        return f

    # Try case-insensitive
    f = db.query(Forecaster).filter(Forecaster.name.ilike(canonical)).first()
    if f:
        return f

    # Only create if canonical is a known alias or multi-word
    if " " not in canonical and canonical not in FORECASTER_ALIASES:
        return None

    handle = re.sub(r"[^a-zA-Z0-9]", "", canonical)[:20]
    existing = db.query(Forecaster).filter(Forecaster.handle == handle).first()
    if existing:
        return existing

    f = Forecaster(
        name=canonical,
        handle=handle,
        platform="institutional",
        channel_url="",
    )
    db.add(f)
    db.flush()
    print(f"[NewsScraper] Created forecaster: {canonical}")
    return f


def merge_duplicate_forecasters(db):
    """Merge forecasters that are the same firm with different names."""
    merged = 0
    for canonical, aliases in FORECASTER_ALIASES.items():
        main = db.query(Forecaster).filter(Forecaster.name == canonical).first()
        if not main:
            continue
        for alias in aliases:
            dupes = db.query(Forecaster).filter(
                Forecaster.name.ilike(alias),
                Forecaster.id != main.id,
            ).all()
            for dupe in dupes:
                db.execute(
                    text("UPDATE predictions SET forecaster_id = :main_id WHERE forecaster_id = :dupe_id"),
                    {"main_id": main.id, "dupe_id": dupe.id},
                )
                db.delete(dupe)
                merged += 1
                print(f"[Merge] Merged '{dupe.name}' into '{canonical}'")
    if merged:
        db.commit()
        print(f"[Merge] Merged {merged} duplicate forecasters")
    return merged


def scrape_news_predictions(db: Session):
    """Scrape real prediction articles with 3-layer defense."""
    global LAST_FULL_SCAN
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[NewsScraper] Another scraper running, skipping")
        return
    try:
        _scrape_news_predictions_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _scrape_news_predictions_inner(db: Session):
    global LAST_FULL_SCAN
    if not FINNHUB_KEY:
        print("[NewsScraper] No FINNHUB_KEY")
        return

    today = datetime.utcnow()
    to_date = today.strftime("%Y-%m-%d")

    # Smart time window: 90 days on first run, then only since last scan
    if LAST_FULL_SCAN is None:
        from_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        print("[NewsScraper] First run — scanning 90 days of history")
    else:
        # Go back to last scan minus 1 hour buffer, minimum 1 day
        lookback = max(today - LAST_FULL_SCAN + timedelta(hours=1), timedelta(days=1))
        from_date = (today - lookback).strftime("%Y-%m-%d")
        print(f"[NewsScraper] Incremental scan — from {from_date}")

    added = 0
    rejected_l1 = 0
    rejected_l2 = 0

    tickers = ensure_tickers()

    seen_urls = set()
    existing = db.execute(text("SELECT source_url FROM predictions WHERE source_url IS NOT NULL"))
    for row in existing:
        if row[0]:
            seen_urls.add(row[0])

    print(f"[NewsScraper] Starting — {len(seen_urls)} existing, {len(tickers)} tickers to scan")

    batch_size = 50
    for i, ticker in enumerate(tickers):
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/company-news",
                params={
                    "symbol": ticker,
                    "from": from_date,
                    "to": to_date,
                    "token": FINNHUB_KEY,
                },
                timeout=10,
            )
            if r.status_code != 200:
                continue
            articles = r.json()
            if not isinstance(articles, list):
                continue

            for article in articles[:30]:
                headline = article.get("headline", "")
                summary = article.get("summary", "")
                source = article.get("source", "")
                raw_url = article.get("url", "")
                dt = article.get("datetime", 0)

                if not raw_url or raw_url in seen_urls:
                    continue

                # === LAYER 1: Strict filter ===
                if not is_real_prediction(headline, summary):
                    rejected_l1 += 1
                    continue

                direction = get_direction(headline, summary)
                if not direction:
                    rejected_l1 += 1
                    continue

                # Extract the REAL forecaster — SKIP if no known analyst found
                forecaster_name = extract_forecaster_name(headline, source, ticker)
                if not forecaster_name:
                    rejected_l1 += 1
                    continue
                forecaster = find_forecaster(forecaster_name, db)
                if not forecaster:
                    rejected_l1 += 1
                    continue

                # Resolve URL and archive
                real_url = resolve_redirect(raw_url)
                if real_url in seen_urls:
                    continue

                arch = archive_url(real_url)

                # Eval window
                text_lower = (headline + " " + summary).lower()
                window_days = 365 if "price target" in text_lower or "target" in text_lower else 90
                pred_date = datetime.fromtimestamp(dt) if dt else today
                eval_date = pred_date + timedelta(days=window_days)

                # === LAYER 2: Validation ===
                is_valid, reason = validate_prediction(
                    ticker=ticker,
                    direction=direction,
                    source_url=real_url,
                    archive_url=arch,
                    context=headline,
                    forecaster_id=forecaster.id,
                )
                if not is_valid:
                    rejected_l2 += 1
                    continue

                # PASSED — save
                pred = Prediction(
                    forecaster_id=forecaster.id,
                    ticker=ticker,
                    direction=direction,
                    prediction_date=pred_date,
                    evaluation_date=eval_date,
                    window_days=window_days,
                    source_url=real_url,
                    archive_url=arch,
                    source_type="article",
                    context=headline[:500],
                    exact_quote=headline,
                    outcome="pending",
                    verified_by="finnhub_news",
                )
                db.add(pred)
                seen_urls.add(raw_url)
                seen_urls.add(real_url)
                added += 1
                TICKER_LAST_FOUND[ticker] = datetime.utcnow()

                if added % 25 == 0:
                    db.commit()
                    print(f"[NewsScraper] {added} predictions added...")

            time.sleep(1.1)

            # Batch pause every 50 tickers to stay under rate limit
            if (i + 1) % batch_size == 0 and (i + 1) < len(tickers):
                db.commit()
                print(
                    f"[NewsScraper] Batch {(i + 1) // batch_size} done "
                    f"({i + 1}/{len(tickers)}), {added} added, pausing 10s..."
                )
                time.sleep(10)
            elif (i + 1) % 100 == 0:
                print(f"[NewsScraper] {i + 1}/{len(tickers)} tickers, {added} added")

        except Exception as e:
            print(f"[NewsScraper] Error for {ticker}: {e}")
            continue

    db.commit()
    LAST_FULL_SCAN = datetime.utcnow()
    print(f"[NewsScraper] DONE: {added} added, {rejected_l1} rejected L1, {rejected_l2} rejected L2 ({len(tickers)} tickers scanned)")


# Top 30 most-watched tickers for the fast 15-minute scraper
FAST_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AVGO",
    "AMD", "NFLX", "CRM", "ADBE", "INTC", "QCOM", "ARM", "SMCI",
    "JPM", "BAC", "GS", "MS", "V", "MA",
    "UNH", "LLY", "PFE", "NKE", "BA", "DIS",
    "XOM", "COIN", "PLTR", "CRWD", "PANW", "SOFI", "SQ", "PYPL",
    "SNOW", "NOW", "UBER", "HD",
]


def scrape_fast_predictions(db: Session):
    """Fast scraper — runs every 15 min. Skips cold tickers to save API calls."""
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[FastScraper] Another scraper running, skipping")
        return
    try:
        _scrape_fast_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _scrape_fast_inner(db: Session):
    if not FINNHUB_KEY:
        return

    today = datetime.utcnow()
    # Only fetch articles from last few hours (Finnhub date granularity is daily, so use today)
    from_date = (today - timedelta(hours=4)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")
    hot_cutoff = today - timedelta(days=3)

    # Filter to hot tickers (had a prediction in last 3 days) + always-check list
    always_check = set(FAST_TICKERS[:10])  # Top 10 always checked
    tickers_to_check = []
    skipped = 0
    for ticker in FAST_TICKERS:
        if ticker in always_check:
            tickers_to_check.append(ticker)
        elif ticker in TICKER_LAST_FOUND and TICKER_LAST_FOUND[ticker] >= hot_cutoff:
            tickers_to_check.append(ticker)
        else:
            skipped += 1

    added = 0

    seen_urls = set()
    existing = db.execute(text("SELECT source_url FROM predictions WHERE source_url IS NOT NULL"))
    for row in existing:
        if row[0]:
            seen_urls.add(row[0])

    if skipped:
        print(f"[FastScraper] Checking {len(tickers_to_check)} tickers (skipped {skipped} cold)")

    for ticker in tickers_to_check:
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/company-news",
                params={
                    "symbol": ticker,
                    "from": from_date,
                    "to": to_date,
                    "token": FINNHUB_KEY,
                },
                timeout=10,
            )
            if r.status_code != 200:
                continue
            articles = r.json()
            if not isinstance(articles, list):
                continue

            for article in articles[:15]:
                headline = article.get("headline", "")
                summary = article.get("summary", "")
                source = article.get("source", "")
                raw_url = article.get("url", "")
                dt = article.get("datetime", 0)

                if not raw_url or raw_url in seen_urls:
                    continue
                if not is_real_prediction(headline, summary):
                    continue

                direction = get_direction(headline, summary)
                if not direction:
                    continue

                forecaster_name = extract_forecaster_name(headline, source, ticker)
                if not forecaster_name:
                    continue
                forecaster = find_forecaster(forecaster_name, db)
                if not forecaster:
                    continue

                real_url = resolve_redirect(raw_url)
                if real_url in seen_urls:
                    continue

                arch = archive_url(real_url)

                text_lower = (headline + " " + summary).lower()
                window_days = 365 if "price target" in text_lower or "target" in text_lower else 90
                pred_date = datetime.fromtimestamp(dt) if dt else today
                eval_date = pred_date + timedelta(days=window_days)

                is_valid, _ = validate_prediction(
                    ticker=ticker, direction=direction,
                    source_url=real_url, archive_url=arch,
                    context=headline, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                    prediction_date=pred_date, evaluation_date=eval_date,
                    window_days=window_days, source_url=real_url, archive_url=arch,
                    source_type="article", context=headline[:500], exact_quote=headline,
                    outcome="pending", verified_by="finnhub_news",
                ))
                seen_urls.add(raw_url)
                seen_urls.add(real_url)
                added += 1
                TICKER_LAST_FOUND[ticker] = datetime.utcnow()

            time.sleep(1.1)

        except Exception as e:
            print(f"[FastScraper] Error for {ticker}: {e}")
            continue

    if added > 0:
        db.commit()
        print(f"[FastScraper] Added {added} new predictions")


# ═══════════════════════════════════════════════════════════════════════════
# NewsAPI scraper — real article URLs from major financial news sites
# ═══════════════════════════════════════════════════════════════════════════

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
NEWSAPI_LAST_RUN = None  # Track last run to only fetch new articles

# 2 combined queries instead of 6 — saves API calls (free tier = 100/day)
NEWSAPI_QUERIES = [
    "analyst upgrades downgrades stock rating",
    "price target raises lowers initiates coverage",
]


def scrape_newsapi(db: Session):
    """Scrape analyst predictions from NewsAPI.org — real article URLs."""
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[NewsAPI] Another scraper running, skipping")
        return
    try:
        _newsapi_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _newsapi_inner(db: Session):
    global NEWSAPI_LAST_RUN
    if not NEWSAPI_KEY:
        print("[NewsAPI] No NEWSAPI_KEY, skipping")
        return

    added = 0

    for query in NEWSAPI_QUERIES:
        try:
            params = {
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 100,
                "apiKey": NEWSAPI_KEY,
            }
            # Only fetch articles published after our last check
            if NEWSAPI_LAST_RUN:
                params["from"] = NEWSAPI_LAST_RUN

            r = httpx.get("https://newsapi.org/v2/everything", params=params, timeout=30)
            data = r.json()
            if data.get("status") != "ok":
                print(f"[NewsAPI] Query '{query}': {data.get('message', 'error')}")
                continue

            articles = data.get("articles", [])
            print(f"[NewsAPI] Query '{query}': {len(articles)} articles")

            for article in articles:
                title = article.get("title", "")
                url = article.get("url", "")
                published = article.get("publishedAt", "")

                if not title or not url:
                    continue

                # Check URL first (cheapest check — avoids wasting CPU on Layer 1)
                if db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": url}).first():
                    continue

                # Layer 1 strict filter
                if not is_real_prediction(title):
                    continue

                direction = get_direction(title)
                if not direction:
                    continue

                # Extract ticker from title: (AAPL) or (NYSE:AAPL)
                ticker_match = re.search(r"\((?:NYSE|NASDAQ|NASD)?:?\s*([A-Z]{1,5})\)", title)
                if not ticker_match:
                    continue
                ticker = ticker_match.group(1)

                # Extract forecaster
                forecaster_name = extract_forecaster_name(title, "", ticker)
                if not forecaster_name:
                    continue

                forecaster = find_forecaster(forecaster_name, db)
                if not forecaster:
                    continue

                # Parse date
                date_str = (published or "")[:10]
                if not date_str or len(date_str) < 8:
                    continue
                try:
                    pred_date = datetime.strptime(date_str, "%Y-%m-%d")
                except Exception:
                    continue

                # Archive via Wayback Machine
                arch = url
                try:
                    ar = httpx.get(f"https://web.archive.org/save/{url}", timeout=10, follow_redirects=True)
                    loc = ar.headers.get("content-location", "")
                    if loc:
                        arch = f"https://web.archive.org{loc}"
                    else:
                        arch = f"https://web.archive.org/web/{url}"
                except Exception:
                    arch = f"https://web.archive.org/web/{url}"

                text_lower = title.lower()
                window_days = 365 if "price target" in text_lower or "target" in text_lower else 90

                # Layer 2 validation
                is_valid, _ = validate_prediction(
                    ticker=ticker, direction=direction, source_url=url,
                    archive_url=arch, context=title, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                    prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=window_days),
                    window_days=window_days, source_url=url, archive_url=arch,
                    source_type="article", context=title[:500], exact_quote=title,
                    outcome="pending", verified_by="newsapi",
                ))
                added += 1

            time.sleep(2)  # Rate limit between queries

        except Exception as e:
            print(f"[NewsAPI] Error for '{query}': {e}")

    if added:
        db.commit()
    NEWSAPI_LAST_RUN = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[NewsAPI] Done: {added} predictions added (next run will fetch from {NEWSAPI_LAST_RUN})")
