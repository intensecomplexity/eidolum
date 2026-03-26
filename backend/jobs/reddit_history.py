"""
Reddit historical prediction scraper — goes back 1 year for major finance subreddits.
Extracts predictions using keyword matching on post titles and text.
"""
import re
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

from jobs.prediction_filter import is_prediction

REDDIT_SOURCES = [
    {"name": "WSB Consensus",    "url": "https://www.reddit.com/r/wallstreetbets/top.json?t=year&limit=100"},
    {"name": "r/investing",      "url": "https://www.reddit.com/r/investing/top.json?t=year&limit=100"},
    {"name": "r/stocks",         "url": "https://www.reddit.com/r/stocks/top.json?t=year&limit=100"},
    {"name": "DeepFuckingValue", "url": "https://www.reddit.com/user/DeepFuckingValue/submitted.json?limit=100"},
    {"name": "WSB Consensus",    "url": "https://www.reddit.com/r/wallstreetbets/search.json?q=prediction+target&sort=top&t=year&limit=100"},
    {"name": "r/stocks",         "url": "https://www.reddit.com/r/stocks/search.json?q=price+target+buy+sell&sort=top&t=year&limit=100"},
]


def scrape_reddit_history(db: Session):
    """Scrape top posts from the past year across tracked subreddits and users."""
    headers = {"User-Agent": "eidolum-scraper/1.0"}
    total = 0

    for source in REDDIT_SOURCES:
        first_name = source["name"].split()[0]
        forecaster = db.query(Forecaster).filter(
            Forecaster.name.ilike(f"%{first_name}%")
        ).first()
        if not forecaster:
            print(f"[RedditHistory] Forecaster not found: {source['name']}")
            continue

        try:
            r = httpx.get(source["url"], headers=headers, timeout=15)
            posts = r.json().get("data", {}).get("children", [])

            one_year_ago = datetime.utcnow() - timedelta(days=365)
            added = 0

            for post in posts:
                data = post.get("data", {})
                post_id = data.get("id")
                title = data.get("title", "")
                selftext = data.get("selftext", "")
                permalink = data.get("permalink", "")
                created = data.get("created_utc", 0)
                full_text = f"{title} {selftext}"

                if not is_prediction(full_text):
                    continue

                post_date = datetime.utcfromtimestamp(created)
                if post_date < one_year_ago:
                    continue

                source_url = f"https://reddit.com{permalink}"

                # Skip duplicates
                if db.query(Prediction).filter(
                    Prediction.source_url == source_url
                ).first():
                    continue

                # Detect ticker from $TICKER patterns
                ticker_match = re.search(r'\$([A-Z]{1,5})', full_text)
                ticker = ticker_match.group(1) if ticker_match else "SPY"

                text_lower = full_text.lower()
                direction = "bearish" if any(w in text_lower for w in [
                    "bear", "sell", "short", "crash", "put", "drop", "overvalued", "avoid"
                ]) else "bullish"

                p = Prediction(
                    forecaster_id=forecaster.id,
                    context=title[:200],
                    exact_quote=(selftext[:500] if selftext else title[:500]),
                    source_url=source_url,
                    source_type="reddit",
                    source_platform_id=post_id,
                    ticker=ticker,
                    direction=direction,
                    outcome="pending",
                    prediction_date=post_date,
                    window_days=365,
                    verified_by="ai_parsed",
                )
                db.add(p)
                added += 1

            db.commit()
            total += added
            print(f"[RedditHistory] {source['name']}: {added} predictions from {len(posts)} posts")

        except Exception as e:
            print(f"[RedditHistory] Error for {source['name']}: {e}")
            db.rollback()

    print(f"[RedditHistory] Done! Total predictions added: {total}")
