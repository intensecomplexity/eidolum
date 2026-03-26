"""
Financial news scraper — uses Finnhub Company News API to find REAL articles
with REAL URLs that contain actual stock predictions (upgrades, downgrades,
price targets, etc.). Each prediction links to the original article.
Archives via Wayback Machine for permanent proof.
"""
import os
import re
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Prediction, Forecaster

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM", "BAC", "V",
    "JNJ", "UNH", "WMT", "PG", "MA", "HD", "DIS", "ADBE", "CRM", "NFLX",
    "COST", "PEP", "AVGO", "TMO", "AMD", "INTC", "QCOM", "GS", "MS", "C",
    "BA", "CAT", "GE", "HON", "LMT", "MCD", "NKE", "PYPL", "COIN", "PLTR",
    "CRWD", "PANW", "XOM", "CVX", "LLY", "PFE", "ABBV", "MRK", "SOFI", "ARM",
    "SMCI", "SQ", "SNOW", "NET", "BLK", "SCHW", "LOW", "SBUX", "TXN", "RIVN",
]

PREDICTION_KEYWORDS = [
    "upgrade", "downgrade", "buy rating", "sell rating", "hold rating",
    "price target", "raises target", "lowers target", "cuts target",
    "overweight", "underweight", "outperform", "underperform",
    "raises to", "lowers to", "initiates coverage", "reiterates",
    "top pick", "conviction buy", "conviction list", "strong buy",
    "maintains buy", "maintains sell", "maintains overweight",
    "bullish", "bearish",
]

BULLISH_WORDS = [
    "upgrade", "buy", "overweight", "outperform", "raises",
    "strong buy", "top pick", "conviction", "positive", "bullish",
]
BEARISH_WORDS = [
    "downgrade", "sell", "underweight", "underperform", "lowers",
    "cuts", "negative", "bearish", "reduce",
]

SOURCE_MAP = {
    "marketwatch": "MarketWatch", "cnbc": "CNBC", "reuters": "Reuters",
    "bloomberg": "Bloomberg", "barron": "Barron's", "seeking alpha": "Seeking Alpha",
    "seekingalpha": "Seeking Alpha", "motley fool": "Motley Fool", "fool.com": "Motley Fool",
    "thestreet": "The Street", "benzinga": "Benzinga", "investor": "Investor's Business Daily",
    "yahoo": "Yahoo Finance", "forbes": "Forbes", "zacks": "Zacks Investment Research",
    "tipranks": "TipRanks", "morningstar": "Morningstar", "business insider": "Business Insider",
    "financial times": "Financial Times", "ft.com": "Financial Times",
    "kiplinger": "Kiplinger", "goldman": "Goldman Sachs",
    "jp morgan": "JP Morgan", "jpmorgan": "JP Morgan",
    "morgan stanley": "Morgan Stanley", "bank of america": "Bank of America",
    "bofa": "Bank of America", "citi": "Citi Research", "ubs": "UBS",
    "barclays": "Barclays", "deutsche": "Deutsche Bank", "wells fargo": "Wells Fargo",
    "hsbc": "HSBC", "wedbush": "Wedbush Securities", "oppenheimer": "Oppenheimer",
    "piper": "Piper Sandler", "fundstrat": "Fundstrat Global",
    "cathie wood": "Cathie Wood", "ark invest": "ARK Invest",
    "dan ives": "Dan Ives", "tom lee": "Tom Lee", "jim cramer": "Jim Cramer",
}

PRICE_PATTERN = re.compile(r'\$([0-9,]+(?:\.[0-9]+)?)')


def is_prediction(headline, summary):
    combined = (headline + " " + summary).lower()
    return any(kw in combined for kw in PREDICTION_KEYWORDS)


def get_direction(headline, summary):
    combined = (headline + " " + summary).lower()
    bull = sum(1 for w in BULLISH_WORDS if w in combined)
    bear = sum(1 for w in BEARISH_WORDS if w in combined)
    if bull > bear:
        return "bullish"
    elif bear > bull:
        return "bearish"
    return None


def match_forecaster(source, headline, db):
    combined = (source + " " + headline).lower()
    for keyword, name in SOURCE_MAP.items():
        if keyword in combined:
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if f:
                return f
    # Fallback
    return db.query(Forecaster).filter(Forecaster.handle == "WallStConsensus").first()


def archive_url(url):
    """Create Wayback Machine archive URL. Also try to save the page."""
    try:
        httpx.get(
            f"https://web.archive.org/save/{url}",
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "eidolum-archiver/1.0"},
        )
    except Exception:
        pass
    ts = datetime.utcnow().strftime("%Y%m%d")
    return f"https://web.archive.org/web/{ts}/{url}"


def extract_target_price(headline, summary):
    combined = headline + " " + summary
    match = PRICE_PATTERN.search(combined)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except (ValueError, TypeError):
            pass
    return None


def scrape_news_predictions(db: Session):
    """Scrape real financial news articles that contain stock predictions."""
    if not FINNHUB_KEY:
        print("[NewsScraper] No FINNHUB_KEY set")
        return

    today = datetime.utcnow()
    from_date = (today - timedelta(days=60)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    total_added = 0

    for ticker in TICKERS:
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
                url = article.get("url", "")
                dt = article.get("datetime", 0)

                if not url or not headline:
                    continue
                if not is_prediction(headline, summary):
                    continue

                direction = get_direction(headline, summary)
                if not direction:
                    continue

                # Deduplicate by source_url
                exists = db.execute(
                    text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"),
                    {"u": url},
                ).first()
                if exists:
                    continue

                forecaster = match_forecaster(source, headline, db)
                if not forecaster:
                    continue

                # Archive the page via Wayback Machine
                archived = archive_url(url)

                pred_date = datetime.fromtimestamp(dt) if dt else today
                target_price = extract_target_price(headline, summary)

                pred = Prediction(
                    forecaster_id=forecaster.id,
                    ticker=ticker,
                    direction=direction,
                    prediction_date=pred_date,
                    source_url=url,
                    archive_url=archived,
                    source_type="article",
                    exact_quote=headline[:500],
                    context=headline[:200],
                    target_price=target_price,
                    outcome="pending",
                    window_days=90,
                    verified_by="finnhub_news",
                )
                db.add(pred)
                total_added += 1

                if total_added % 50 == 0:
                    db.commit()
                    print(f"[NewsScraper] {total_added} real predictions added...")

            time.sleep(1.1)  # Finnhub rate limit: 60 calls/min

        except Exception as e:
            print(f"[NewsScraper] Error {ticker}: {e}")
            continue

    db.commit()
    print(f"[NewsScraper] Done: {total_added} real article predictions added")
