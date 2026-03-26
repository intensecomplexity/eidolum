"""
Financial news RSS scraper — pulls analyst predictions from CNBC, Reuters,
MarketWatch, Yahoo Finance, Benzinga, Seeking Alpha, etc.
Free, reliable, never rate-limited.
"""
import re
import feedparser
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

NEWS_FEEDS = [
    # CNBC
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135", "source": "CNBC"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258", "source": "CNBC Markets"},
    # MarketWatch
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", "source": "MarketWatch"},
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "source": "MarketWatch"},
    # Yahoo Finance
    {"url": "https://finance.yahoo.com/news/rssindex", "source": "Yahoo Finance"},
    # Reuters
    {"url": "https://feeds.reuters.com/reuters/businessNews", "source": "Reuters"},
    {"url": "https://feeds.reuters.com/reuters/companyNews", "source": "Reuters"},
    # Seeking Alpha
    {"url": "https://seekingalpha.com/feed.xml", "source": "Seeking Alpha"},
    # Benzinga
    {"url": "https://www.benzinga.com/feeds/analyst-ratings", "source": "Benzinga"},
    {"url": "https://www.benzinga.com/feeds/news", "source": "Benzinga"},
    # The Street
    {"url": "https://www.thestreet.com/.rss/full/", "source": "The Street"},
    # Investor's Business Daily
    {"url": "https://www.investors.com/feed/", "source": "IBD"},
    # Barron's
    {"url": "https://www.barrons.com/xml/rss/3_7551.xml", "source": "Barrons"},
]

PREDICTION_PATTERN = re.compile(
    r'('
    r'price target.{0,20}\$[\d,]+'
    r'|target.{0,10}of.{0,10}\$[\d,]+'
    r'|raises?.{0,20}to \$[\d,]+'
    r'|lowers?.{0,20}to \$[\d,]+'
    r'|initiates?.{0,30}(buy|sell|hold)'
    r'|upgrades?.{0,30}(buy|outperform)'
    r'|downgrades?.{0,30}(sell|underperform)'
    r'|will reach \$[\d,]+'
    r'|forecast.{0,20}\$[\d,]+'
    r'|expects?.{0,30}\$[\d,]+'
    r'|S&P.{0,20}(target|forecast|reach).{0,20}[\d,]+'
    r')',
    re.IGNORECASE,
)

FIRM_PATTERN = re.compile(
    r'(Goldman Sachs|Morgan Stanley|JPMorgan|Bank of America|Citigroup|Wells Fargo|'
    r'UBS|Barclays|Deutsche Bank|Credit Suisse|RBC Capital|Jefferies|Stifel|'
    r'Wedbush|Needham|Piper Sandler|Oppenheimer|Cowen|Baird|Raymond James|'
    r'Bernstein|Evercore|Mizuho|BTIG|Canaccord|Loop Capital|Truist|KeyBanc|'
    r'DA Davidson|Craig-Hallum|H\.C\. Wainwright)',
    re.IGNORECASE,
)

PRICE_PATTERN = re.compile(r'\$([0-9,]+(?:\.[0-9]+)?)')

_NON_TICKERS = frozenset({
    'CEO', 'CFO', 'IPO', 'ETF', 'USD', 'GDP', 'FED', 'SEC', 'FDA',
    'THE', 'FOR', 'AND', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN',
    'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'HAS', 'HIS', 'HOW', 'NEW',
})


def _extract_ticker(text: str) -> str | None:
    paren = re.search(r'\(([A-Z]{2,5})\)', text)
    if paren and paren.group(1) not in _NON_TICKERS:
        return paren.group(1)
    dollar = re.search(r'\$([A-Z]{2,5})\b', text)
    if dollar:
        return dollar.group(1)
    return None


def _get_or_create_forecaster(db: Session, firm_name: str, source: str) -> Forecaster:
    forecaster = db.query(Forecaster).filter(
        Forecaster.name.ilike(f"%{firm_name.split()[0]}%")
    ).first()
    if forecaster:
        return forecaster

    handle = re.sub(r'[^a-zA-Z0-9]', '', firm_name)[:20]
    existing = db.query(Forecaster).filter(Forecaster.handle == handle).first()
    if existing:
        return existing

    forecaster = Forecaster(
        name=firm_name,
        handle=handle,
        platform="institutional",
        channel_url=f"https://x.com/search?q={firm_name.replace(' ', '+')}",
    )
    db.add(forecaster)
    db.flush()
    return forecaster


def scrape_news_feeds(db: Session):
    """Scrape financial news RSS feeds for analyst predictions."""
    added = 0

    for feed_info in NEWS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])

            for entry in feed.entries[:50]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", ""))
                full_text = f"{title}. {summary}"

                if not PREDICTION_PATTERN.search(full_text):
                    continue

                if db.query(Prediction).filter(Prediction.source_url == link).first():
                    continue

                ticker = _extract_ticker(full_text)
                if not ticker:
                    continue

                # Extract price target
                prices = PRICE_PATTERN.findall(full_text)
                target_price = None
                if prices:
                    try:
                        target_price = float(prices[0].replace(",", ""))
                    except (ValueError, TypeError):
                        pass

                # Extract firm name
                firm_match = FIRM_PATTERN.search(full_text)
                forecaster_name = firm_match.group(0) if firm_match else feed_info["source"]
                forecaster = _get_or_create_forecaster(db, forecaster_name, feed_info["source"])

                direction = "bearish" if re.search(
                    r'\b(downgrade|sell|underperform|reduce|cut|lower)\b', full_text, re.I
                ) else "bullish"

                # Use the most specific sentence as quote
                quote = title
                for sentence in full_text.split('.'):
                    if PREDICTION_PATTERN.search(sentence) and ticker in sentence:
                        quote = sentence.strip()
                        break
                if len(quote) < 20:
                    quote = title

                pred = Prediction(
                    forecaster_id=forecaster.id,
                    exact_quote=quote[:500],
                    context=title[:200],
                    source_url=link,
                    source_type="article",
                    ticker=ticker,
                    direction=direction,
                    target_price=target_price,
                    outcome="pending",
                    prediction_date=datetime.utcnow(),
                    window_days=365,
                    verified_by="rss_feed",
                )
                db.add(pred)
                db.flush()

                # Archive as HTML evidence card
                try:
                    from archiver.screenshot import archive_proof_sync
                    archive_url = archive_proof_sync(
                        link, pred.id,
                        exact_quote=quote[:500],
                        forecaster_name=forecaster.name,
                        prediction_date=str(datetime.utcnow()),
                    )
                    if archive_url:
                        pred.archive_url = archive_url
                        pred.archived_at = datetime.utcnow()
                except Exception as e:
                    print(f"[News] Archive error for {link}: {e}")

                added += 1

        except Exception as e:
            print(f"[News] Error for {feed_info['source']}: {e}")
            db.rollback()
            continue

    if added > 0:
        db.commit()
    print(f"[News] Added {added} predictions from financial news feeds")
