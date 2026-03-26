"""
Substack/newsletter scraper — pulls predictions from finance writer RSS feeds.
No API key needed.
"""
import re
import feedparser
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster
from jobs.prediction_filter import is_valid_prediction

SUBSTACK_FEEDS = [
    {"name": "Meb Faber",           "handle": "MebFaber",       "url": "https://mebfaber.substack.com/feed"},
    {"name": "The Kobeissi Letter",  "handle": "KobeissiLetter", "url": "https://kobeissiletter.substack.com/feed"},
    {"name": "Compounding Quality",  "handle": "QCompounding",   "url": "https://compoundingquality.substack.com/feed"},
    {"name": "Macro Ops",            "handle": "MacroOps",       "url": "https://macro-ops.substack.com/feed"},
    {"name": "Brent Donnelly",       "handle": "donnelly_brent", "url": "https://www.spectramarkets.com/feed/"},
    {"name": "Sven Henrich",         "handle": "NorthmanTrader", "url": "https://northmantrader.com/feed/"},
    {"name": "Howard Lindzon",       "handle": "howardlindzon",  "url": "https://howardlindzon.substack.com/feed"},
    {"name": "Litquidity",           "handle": "litcapital",     "url": "https://litquidity.substack.com/feed"},
    {"name": "Ramp Capital",         "handle": "RampCapitalLLC", "url": "https://rampcapital.substack.com/feed"},
]


def scrape_substacks(db: Session):
    added = 0
    for source in SUBSTACK_FEEDS:
        forecaster = db.query(Forecaster).filter(
            Forecaster.handle == source["handle"]
        ).first()
        if not forecaster:
            continue

        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "")
                full_text = f"{title} {summary[:500]}"

                if not is_valid_prediction(full_text):
                    continue
                if db.query(Prediction).filter(Prediction.source_url == link).first():
                    continue

                ticker_match = re.search(r'\$([A-Z]{1,5})\b', full_text)
                ticker = ticker_match.group(1) if ticker_match else "SPY"

                direction = "bearish" if re.search(
                    r'\b(bear|short|sell|crash|drop|overvalued)\b', full_text, re.I
                ) else "bullish"

                db.add(Prediction(
                    forecaster_id=forecaster.id,
                    exact_quote=summary[:500] if summary else title,
                    context=title[:200],
                    source_url=link,
                    source_type="article",
                    ticker=ticker,
                    direction=direction,
                    outcome="pending",
                    prediction_date=datetime.utcnow(),
                    window_days=365,
                    verified_by="rss_feed",
                ))
                added += 1
            db.commit()
        except Exception as e:
            print(f"[Substack] {source['name']} error: {e}")
            db.rollback()

    print(f"[Substack] Added {added} predictions from newsletters")
