"""
Financial news scraper — uses Finnhub Company News API to find REAL analyst
upgrades, downgrades, and price target changes with actual article URLs.

Uses 3-layer defense system:
  Layer 1: Strict scraper filter (analyst action + rating word, reject patterns)
  Layer 2: Validation function (all 7 required fields)
  Layer 3: Hourly cleanup (catch anything that slipped through)
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Prediction, Forecaster
from jobs.prediction_validator import (
    is_real_prediction,
    get_direction,
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

SOURCE_MAP = {
    "marketwatch": "MarketWatch", "cnbc": "CNBC", "reuters": "Reuters",
    "bloomberg": "Bloomberg", "barrons": "Barron's", "barron": "Barron's",
    "seeking alpha": "Seeking Alpha", "seekingalpha": "Seeking Alpha",
    "motley fool": "Motley Fool", "fool.com": "Motley Fool",
    "thestreet": "The Street", "benzinga": "Benzinga",
    "investors.com": "Investor's Business Daily",
    "yahoo": "Yahoo Finance", "forbes": "Forbes",
    "zacks": "Zacks Investment Research", "tipranks": "TipRanks",
    "morningstar": "Morningstar", "business insider": "Business Insider",
    "insider": "Business Insider", "financial times": "Financial Times",
    "ft.com": "Financial Times",
    "goldman": "Goldman Sachs", "jp morgan": "JP Morgan",
    "jpmorgan": "JP Morgan", "morgan stanley": "Morgan Stanley",
    "bank of america": "Bank of America", "bofa": "Bank of America",
    "citi": "Citi Research", "ubs": "UBS", "barclays": "Barclays",
    "deutsche bank": "Deutsche Bank", "wells fargo": "Wells Fargo",
    "hsbc": "HSBC", "wedbush": "Wedbush Securities",
    "dan ives": "Dan Ives", "oppenheimer": "Oppenheimer",
    "piper": "Piper Sandler", "fundstrat": "Fundstrat Global",
    "tom lee": "Tom Lee", "cathie wood": "Cathie Wood",
    "ark invest": "ARK Invest", "jim cramer": "Jim Cramer",
}


def match_forecaster(source, headline, db):
    text_lower = (source + " " + headline).lower()
    for kw, name in SOURCE_MAP.items():
        if kw in text_lower:
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if f:
                return f
    return db.query(Forecaster).filter(Forecaster.handle == "WallStConsensus").first()


def resolve_redirect(finnhub_url):
    """Follow Finnhub redirect to get the real article URL."""
    try:
        r = httpx.head(finnhub_url, follow_redirects=True, timeout=5)
        final = str(r.url)
        if final and final.startswith("http") and "finnhub.io" not in final:
            return final
    except Exception:
        pass
    return finnhub_url


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


def scrape_news_predictions(db: Session):
    """Scrape real prediction articles — with 3-layer defense."""
    if not FINNHUB_KEY:
        print("[NewsScraper] No FINNHUB_KEY")
        return

    today = datetime.utcnow()
    from_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    added = 0
    rejected_l1 = 0  # Failed scraper filter
    rejected_l2 = 0  # Failed validation

    seen_urls = set()
    existing = db.execute(text("SELECT source_url FROM predictions WHERE source_url IS NOT NULL"))
    for row in existing:
        if row[0]:
            seen_urls.add(row[0])

    print(f"[NewsScraper] Starting — {len(seen_urls)} existing, {len(TICKERS)} tickers to scan")

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

                # === LAYER 1: Scraper filter ===
                if not is_real_prediction(headline, summary):
                    rejected_l1 += 1
                    continue

                direction = get_direction(headline, summary)
                if not direction:
                    rejected_l1 += 1
                    continue

                forecaster = match_forecaster(source, headline, db)
                if not forecaster:
                    continue

                # Resolve Finnhub redirect to real URL
                real_url = resolve_redirect(raw_url)

                if real_url in seen_urls:
                    continue

                # Archive the article
                arch = archive_url(real_url)

                # Determine eval window
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

                # Passed both layers — save
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
                print(f"[NewsScraper] {i + 1}/{len(TICKERS)} tickers done, {added} added, {rejected_l1} rejected L1, {rejected_l2} rejected L2")

        except Exception as e:
            print(f"[NewsScraper] Error for {ticker}: {e}")
            continue

    db.commit()
    print(f"[NewsScraper] DONE: {added} added, {rejected_l1} rejected by filter, {rejected_l2} rejected by validator")
