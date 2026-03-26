"""
Financial news scraper — uses Finnhub Company News API to find REAL analyst
upgrades, downgrades, and price target changes with actual article URLs.

Uses 3-layer defense + extracts the real forecaster name from headlines
(never attributes to the platform).
"""
import os
import re
import time
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
)

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META",
    "AVGO", "CRM", "ADBE", "AMD", "INTC", "QCOM", "NFLX", "ORCL",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK",
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK",
    "WMT", "PG", "COST", "PEP", "KO", "MCD", "NKE", "SBUX",
    "BA", "CAT", "GE", "HON", "LMT", "RTX",
    "PLTR", "CRWD", "PANW", "SQ", "PYPL", "COIN", "SNOW",
    "SOFI", "ARM", "SMCI", "RIVN",
    "XOM", "CVX",
    "SPY", "QQQ", "ARKK", "XLF", "XLE", "GLD", "IWM",
]


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
    """Find existing forecaster by name. Only creates new if name is multi-word (real firm)."""
    if not name or len(name.strip()) < 3:
        return None

    name = name.strip()

    # Try exact match
    f = db.query(Forecaster).filter(Forecaster.name == name).first()
    if f:
        return f

    # Try case-insensitive match
    f = db.query(Forecaster).filter(Forecaster.name.ilike(name)).first()
    if f:
        return f

    # Only create new forecaster if it's a multi-word name (real firm, not "Job" or "Oil")
    if " " not in name:
        return None

    handle = re.sub(r"[^a-zA-Z0-9]", "", name)[:20]
    existing = db.query(Forecaster).filter(Forecaster.handle == handle).first()
    if existing:
        return existing

    f = Forecaster(
        name=name,
        handle=handle,
        platform="institutional",
        channel_url="",
    )
    db.add(f)
    db.flush()
    print(f"[NewsScraper] Created new forecaster: {name}")
    return f


def scrape_news_predictions(db: Session):
    """Scrape real prediction articles with 3-layer defense."""
    if not FINNHUB_KEY:
        print("[NewsScraper] No FINNHUB_KEY")
        return

    today = datetime.utcnow()
    from_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    added = 0
    rejected_l1 = 0
    rejected_l2 = 0

    seen_urls = set()
    existing = db.execute(text("SELECT source_url FROM predictions WHERE source_url IS NOT NULL"))
    for row in existing:
        if row[0]:
            seen_urls.add(row[0])

    print(f"[NewsScraper] Starting — {len(seen_urls)} existing, {len(TICKERS)} tickers")

    for i, ticker in enumerate(TICKERS):
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
                forecaster_name = extract_forecaster_name(headline, source)
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

                if added % 25 == 0:
                    db.commit()
                    print(f"[NewsScraper] {added} predictions added...")

            time.sleep(1.1)
            if (i + 1) % 10 == 0:
                print(
                    f"[NewsScraper] {i + 1}/{len(TICKERS)} tickers, "
                    f"{added} added, {rejected_l1} rejected L1, {rejected_l2} rejected L2"
                )

        except Exception as e:
            print(f"[NewsScraper] Error for {ticker}: {e}")
            continue

    db.commit()
    print(f"[NewsScraper] DONE: {added} added, {rejected_l1} rejected L1, {rejected_l2} rejected L2")


# Top 15 most-watched tickers for the fast 15-minute scraper
FAST_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META",
    "AMD", "NFLX", "JPM", "BA", "NKE", "DIS", "COIN", "PLTR",
]


def scrape_fast_predictions(db: Session):
    """Fast scraper — runs every 15 min, checks top 15 tickers, last 2 days only."""
    if not FINNHUB_KEY:
        return

    today = datetime.utcnow()
    from_date = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    added = 0

    seen_urls = set()
    existing = db.execute(text("SELECT source_url FROM predictions WHERE source_url IS NOT NULL"))
    for row in existing:
        if row[0]:
            seen_urls.add(row[0])

    for ticker in FAST_TICKERS:
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

                forecaster_name = extract_forecaster_name(headline, source)
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

            time.sleep(1.1)

        except Exception as e:
            print(f"[FastScraper] Error for {ticker}: {e}")
            continue

    if added > 0:
        db.commit()
        print(f"[FastScraper] Added {added} new predictions")
