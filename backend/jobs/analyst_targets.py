"""
Analyst price target scraper — pulls upgrade/downgrade/target changes from RSS feeds.
These are ideal predictions: "Goldman raises NVDA target from $150 to $200"
"""
import re
import feedparser
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster
from jobs.prediction_filter import is_prediction

ANALYST_FEEDS = [
    "https://www.benzinga.com/analyst-ratings/analyst-color/feed",
    "https://feeds.marketwatch.com/marketwatch/marketpulse/",
]

ANALYST_PATTERN = re.compile(
    r'(raises?|lowers?|cuts?|boosts?|increases?|reiterates?|initiates?).{0,30}'
    r'(price target|pt|target).{0,20}\$?([0-9,]+)',
    re.IGNORECASE
)

TICKER_PATTERN = re.compile(r'\(([A-Z]{1,5})\)|\$([A-Z]{1,5})')


def _extract_ticker(text: str) -> str:
    m = TICKER_PATTERN.search(text)
    return (m.group(1) or m.group(2)) if m else "SPY"


def scrape_analyst_targets(db: Session):
    """Scrape analyst price target changes from RSS feeds."""
    total = 0

    for feed_url in ANALYST_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:50]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "")
                full_text = f"{title} {summary}"

                if not ANALYST_PATTERN.search(full_text):
                    continue

                # Extract firm name (first capitalized words before action verb)
                firm_match = re.match(
                    r'^([A-Z][a-zA-Z\s&\']+?)\s+'
                    r'(raises?|lowers?|cuts?|boosts?|initiates?|reiterates?)',
                    title
                )
                firm_name = firm_match.group(1).strip() if firm_match else None
                if not firm_name:
                    continue

                # Only save for known forecasters
                forecaster = db.query(Forecaster).filter(
                    Forecaster.name.ilike(f"%{firm_name.split()[0]}%")
                ).first()
                if not forecaster:
                    continue

                if db.query(Prediction).filter(Prediction.source_url == link).first():
                    continue

                ticker = _extract_ticker(full_text)
                direction = "bearish" if re.search(
                    r'(lower|cut|downgrade|reduce)', title, re.I
                ) else "bullish"

                # Extract target price
                target_match = re.search(r'\$([0-9,]+)', full_text)
                target_price = None
                if target_match:
                    try:
                        target_price = float(target_match.group(1).replace(",", ""))
                    except ValueError:
                        pass

                p = Prediction(
                    forecaster_id=forecaster.id,
                    context=title[:200],
                    exact_quote=title[:500],
                    source_url=link,
                    source_type="article",
                    ticker=ticker,
                    direction=direction,
                    target_price=target_price,
                    outcome="pending_review",
                    prediction_date=datetime.utcnow(),
                    window_days=365,
                    verified_by="ai_parsed",
                )
                db.add(p)
                total += 1

            db.commit()
        except Exception as e:
            print(f"[Analyst] Feed error for {feed_url}: {e}")
            db.rollback()

    print(f"[Analyst] Done! {total} price target predictions added")
