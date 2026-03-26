"""
Financial news scraper — uses Finnhub Company News API to find REAL analyst
upgrades, downgrades, and price target changes with actual article URLs.

Strict filtering: only articles where an analyst/firm takes an explicit action
(upgrades, downgrades, initiates, raises/lowers price target) with a clear
rating (buy, sell, overweight, underperform, etc.) are accepted.

Press releases, corporate news, clickbait, and earnings reports are rejected.
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

# ── Analyst action words: someone is making a call ──────────────────────────
ANALYST_ACTIONS = [
    "upgrades", "upgrade", "downgrades", "downgrade",
    "initiates", "initiate", "initiates coverage", "initiated",
    "reiterates", "reiterate", "reiterated",
    "maintains", "maintain", "maintained",
    "raises price target", "lowers price target", "cuts price target",
    "sets price target", "boosts price target", "slashes price target",
    "raises target", "lowers target", "cuts target", "sets target",
    "boosts target", "slashes target",
    "raises pt", "lowers pt", "cuts pt",
    "price target raised", "price target lowered", "price target cut",
    "target raised", "target lowered", "target cut",
    "resumed coverage", "resumes coverage",
    "starts coverage", "started coverage",
]

# ── Rating words: the actual rating being assigned ──────────────────────────
RATING_WORDS = [
    "buy", "sell", "hold", "neutral", "equal weight", "equal-weight",
    "overweight", "underweight", "outperform", "underperform",
    "market perform", "sector perform", "peer perform",
    "strong buy", "strong sell",
    "top pick", "conviction buy", "conviction list",
    "price target", "target of $", "target to $", "pt of $", "pt to $",
    "target price", "price objective",
]

# ── Reject patterns: not predictions, skip immediately ──────────────────────
REJECT_KEYWORDS = [
    "signs agreement", "framework agreement", "partnership", "acquisition", "merger",
    "reports earnings", "earnings report", "quarterly results", "revenue growth",
    "quarterly earnings", "beats estimates", "misses estimates",
    "earnings call", "earnings beat", "earnings miss", "earnings preview",
    "dividend", "stock split", "buyback", "repurchase",
    "appoints", "names ceo", "names cfo", "hires", "board of directors",
    "patent", "fda approval", "fda clears", "clinical trial", "regulatory approval",
    "lawsuit", "settlement", "investigation", "subpoena", "indictment",
    "product launch", "announces partnership", "signs deal", "contract win",
    "supply agreement", "joint venture", "strategic alliance",
    "ipo", "secondary offering", "shelf registration",
    "stock offering", "share offering", "public offering",
    "recall", "data breach", "cybersecurity incident",
]

# ── Bullish / bearish classification ────────────────────────────────────────
BULLISH_PATTERNS = [
    r'\bupgrades?\b', r'\braises?\s+(price\s+)?target', r'\bboosts?\s+(price\s+)?target',
    r'\bbuy\b', r'\boverweight\b', r'\boutperform\b', r'\bstrong buy\b',
    r'\btop pick\b', r'\bconviction\s+buy\b', r'\bconviction\s+list\b',
    r'\btarget\s+(raised|increased)', r'\bprice\s+target\s+raised\b',
    r'\binitiates?\b.*\b(buy|overweight|outperform)\b',
    r'\breiterates?\b.*\b(buy|overweight|outperform)\b',
    r'\bmaintains?\b.*\b(buy|overweight|outperform)\b',
    r'\bbullish\b',
]

BEARISH_PATTERNS = [
    r'\bdowngrades?\b', r'\blowers?\s+(price\s+)?target', r'\bcuts?\s+(price\s+)?target',
    r'\bslash(es)?\s+(price\s+)?target',
    r'\bsell\b', r'\bunderweight\b', r'\bunderperform\b', r'\bstrong sell\b',
    r'\btarget\s+(lowered|cut|reduced|slashed)',
    r'\bprice\s+target\s+(lowered|cut)\b',
    r'\binitiates?\b.*\b(sell|underweight|underperform)\b',
    r'\breiterates?\b.*\b(sell|underweight|underperform)\b',
    r'\bmaintains?\b.*\b(sell|underweight|underperform)\b',
    r'\bbearish\b', r'\breduce\b',
]

_bullish_re = [re.compile(p, re.IGNORECASE) for p in BULLISH_PATTERNS]
_bearish_re = [re.compile(p, re.IGNORECASE) for p in BEARISH_PATTERNS]

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
    """Strict filter: requires analyst action + rating, rejects corporate news."""
    combined = (headline + " " + summary).lower()

    # Headlines ending with ? are clickbait questions, not analyst calls
    if headline.rstrip().endswith("?"):
        return False

    # Reject corporate news, press releases, earnings, etc.
    if any(rk in combined for rk in REJECT_KEYWORDS):
        return False

    # Must have an analyst action word (someone is making a call)
    has_action = any(a in combined for a in ANALYST_ACTIONS)
    if not has_action:
        return False

    # Must have a rating word (the actual rating being assigned)
    has_rating = any(r in combined for r in RATING_WORDS)
    if not has_rating:
        return False

    return True


def get_direction(headline, summary):
    """Extract direction using regex patterns for high-confidence classification."""
    combined = headline + " " + summary

    bull_score = sum(1 for rx in _bullish_re if rx.search(combined))
    bear_score = sum(1 for rx in _bearish_re if rx.search(combined))

    if bull_score > bear_score:
        return "bullish"
    elif bear_score > bull_score:
        return "bearish"
    # Can't determine direction with confidence — skip
    return None


def resolve_url(finnhub_url):
    """Follow redirects to get the final article URL."""
    try:
        r = httpx.head(finnhub_url, follow_redirects=True, timeout=5)
        final = str(r.url)
        if final and final.startswith("http"):
            return final
    except Exception:
        pass
    return finnhub_url


def match_forecaster(source, headline, db):
    combined = (source + " " + headline).lower()
    for keyword, name in SOURCE_MAP.items():
        if keyword in combined:
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if f:
                return f
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

                # Resolve redirect to get final article URL
                final_url = resolve_url(url)

                # Deduplicate by source_url
                exists = db.execute(
                    text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"),
                    {"u": final_url},
                ).first()
                if exists:
                    continue

                forecaster = match_forecaster(source, headline, db)
                if not forecaster:
                    continue

                # Archive the page via Wayback Machine
                archived = archive_url(final_url)

                pred_date = datetime.fromtimestamp(dt) if dt else today
                target_price = extract_target_price(headline, summary)

                pred = Prediction(
                    forecaster_id=forecaster.id,
                    ticker=ticker,
                    direction=direction,
                    prediction_date=pred_date,
                    source_url=final_url,
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

    # Retroactively clean existing predictions that fail the strict filter
    cleanup_bad_predictions(db)


def cleanup_bad_predictions(db: Session):
    """Delete predictions that don't pass the strict is_prediction filter."""
    try:
        all_preds = db.query(Prediction).filter(
            Prediction.verified_by == "finnhub_news"
        ).all()
        deleted = 0
        for p in all_preds:
            headline = p.exact_quote or p.context or ""
            if not is_prediction(headline, ""):
                db.delete(p)
                deleted += 1
        if deleted:
            db.commit()
            print(f"[NewsScraper] Cleaned up {deleted} non-prediction articles from DB")
    except Exception as e:
        db.rollback()
        print(f"[NewsScraper] Cleanup error: {e}")
