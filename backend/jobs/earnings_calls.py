"""
Earnings call guidance scraper — pulls CEO forward guidance from transcript feeds.
These are high-quality predictions: "We expect Q2 revenue of $25B"
"""
import re
import feedparser
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

GUIDANCE_PATTERN = re.compile(
    r'(we expect|we anticipate|we guide|guidance of|we project|outlook of|'
    r'we will reach|target of|revenue of \$|eps of \$|we forecast)',
    re.IGNORECASE
)

TICKER_PATTERN = re.compile(r'\(([A-Z]{1,5})\)')

EARNINGS_FEEDS = [
    "https://www.fool.com/earnings-call-transcripts/feed.xml",
]


def scrape_earnings_calls(db: Session):
    """Pull CEO guidance statements from earnings call transcript feeds."""
    total = 0

    for feed_url in EARNINGS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "")

                # Extract ticker from title like "Apple (AAPL) Q1 2025 Earnings Call"
                ticker_match = TICKER_PATTERN.search(title)
                if not ticker_match:
                    continue
                ticker = ticker_match.group(1)

                if not GUIDANCE_PATTERN.search(summary):
                    continue

                if db.query(Prediction).filter(Prediction.source_url == link).first():
                    continue

                # Extract company name from title
                company_match = re.match(r'^(.+?)\s*\(', title)
                company = company_match.group(1).strip() if company_match else ""
                if not company:
                    continue

                # Find matching forecaster
                forecaster = db.query(Forecaster).filter(
                    Forecaster.name.ilike(f"%{company.split()[0]}%")
                ).first()
                if not forecaster:
                    continue

                p = Prediction(
                    forecaster_id=forecaster.id,
                    context=f"{title}: management guidance"[:200],
                    exact_quote=summary[:500],
                    source_url=link,
                    source_type="article",
                    ticker=ticker,
                    direction="bullish",
                    outcome="pending_review",
                    prediction_date=datetime.utcnow(),
                    window_days=90,
                    verified_by="ai_parsed",
                )
                db.add(p)
                total += 1

            db.commit()
        except Exception as e:
            print(f"[Earnings] Feed error: {e}")
            db.rollback()

    print(f"[Earnings] Done! {total} guidance predictions added")
