"""
Analyst price target scraper — pulls from Benzinga/MarketWatch RSS feeds.
No API key needed.
"""
import re
import feedparser
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

TARGET_PATTERN = re.compile(
    r'(raises?|lowers?|cuts?|boosts?|upgrades?|downgrades?|initiates?|reiterates?)'
    r'.{0,50}(price target|pt|target price|to \$[\d,]+)',
    re.IGNORECASE,
)
FIRM_PATTERN = re.compile(
    r'^([A-Z][A-Za-z\s&]+?)\s+(raises?|lowers?|cuts?|upgrades?|downgrades?|initiates?)',
    re.IGNORECASE,
)
TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b(?=\s+(?:price target|pt|to \$|from \$|\(|\s+\$))')
PRICE_PATTERN = re.compile(r'to \$([0-9,]+)')


def scrape_tipranks(db: Session):
    """Scrape analyst price target changes from public RSS feeds."""
    sources = [
        "https://www.benzinga.com/analyst-ratings/feed",
        "https://feeds.content.dowjones.io/public/rss/mw_bulletins",
    ]

    added = 0
    for feed_url in sources:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:100]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                if not TARGET_PATTERN.search(title):
                    continue
                if db.query(Prediction).filter(Prediction.source_url == link).first():
                    continue

                firm_match = FIRM_PATTERN.match(title)
                firm = firm_match.group(1).strip() if firm_match else None
                ticker_match = TICKER_PATTERN.search(title)
                ticker = ticker_match.group(1) if ticker_match else None
                price_match = PRICE_PATTERN.search(title)
                target_price = float(price_match.group(1).replace(",", "")) if price_match else None

                if not ticker:
                    continue

                # Find forecaster by firm name
                forecaster = None
                if firm:
                    forecaster = db.query(Forecaster).filter(
                        Forecaster.name.ilike(f"%{firm.split()[0]}%")
                    ).first()
                if not forecaster:
                    forecaster = db.query(Forecaster).filter(
                        Forecaster.handle == "WallStAnalysts"
                    ).first()
                    if not forecaster:
                        forecaster = Forecaster(
                            name="Wall Street Analysts",
                            handle="WallStAnalysts",
                            platform="institutional",
                            channel_url="https://x.com/Benzinga",
                        )
                        db.add(forecaster)
                        db.flush()

                direction = "bearish" if re.search(r'(lower|cut|downgrade|reduce|sell)', title, re.I) else "bullish"

                db.add(Prediction(
                    forecaster_id=forecaster.id,
                    exact_quote=title[:500],
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
                ))
                added += 1
        except Exception as e:
            print(f"[Analyst] Feed error for {feed_url}: {e}")
    db.commit()
    print(f"[Analyst] Added {added} analyst price target predictions")
