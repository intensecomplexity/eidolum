"""
Expanded Reddit scraper — pulls from 20 finance subreddits.
"""
import re
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster
from jobs.prediction_filter import is_valid_prediction

EXPANDED_SUBREDDITS = [
    "wallstreetbets", "investing", "stocks", "SecurityAnalysis",
    "options", "ValueInvesting", "StockMarket", "dividends",
    "pennystocks", "RobinHood", "Superstonk", "algotrading",
    "thetagang", "Bogleheads", "personalfinance", "CryptoCurrency",
    "Bitcoin", "ethereum", "SatoshiStreetBets", "CryptoMoonShots",
]


def scrape_reddit_expanded(db: Session):
    headers = {"User-Agent": "eidolum-scraper/1.0"}
    added = 0
    one_year_ago = datetime.utcnow() - timedelta(days=365)

    for subreddit in EXPANDED_SUBREDDITS:
        # Find or create forecaster for this subreddit
        handle = f"r_{subreddit}"
        forecaster = db.query(Forecaster).filter(
            Forecaster.handle == handle
        ).first()
        if not forecaster:
            forecaster = Forecaster(
                name=f"r/{subreddit}",
                handle=handle,
                platform="reddit",
                channel_url=f"https://www.reddit.com/r/{subreddit}",
            )
            db.add(forecaster)
            db.flush()

        for sort in ["top", "hot"]:
            try:
                url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?t=year&limit=100"
                r = httpx.get(url, headers=headers, timeout=10)
                if r.status_code != 200:
                    continue

                posts = r.json().get("data", {}).get("children", [])
                for post in posts:
                    data = post.get("data", {})
                    post_id = data.get("id", "")
                    title = data.get("title", "")
                    selftext = data.get("selftext", "")
                    permalink = data.get("permalink", "")
                    created = data.get("created_utc", 0)
                    full_text = f"{title} {selftext[:300]}"

                    if not is_valid_prediction(full_text):
                        continue

                    post_date = datetime.utcfromtimestamp(created) if created else datetime.utcnow()
                    if post_date < one_year_ago:
                        continue

                    source_url = f"https://reddit.com{permalink}"
                    if db.query(Prediction).filter(
                        Prediction.source_url == source_url
                    ).first():
                        continue

                    ticker_match = re.search(r'\$([A-Z]{1,5})\b', full_text)
                    ticker = ticker_match.group(1) if ticker_match else "SPY"

                    text_lower = full_text.lower()
                    direction = "bearish" if any(w in text_lower for w in [
                        "bear", "sell", "short", "crash", "put", "drop", "fall",
                    ]) else "bullish"

                    db.add(Prediction(
                        forecaster_id=forecaster.id,
                        exact_quote=(selftext[:500] if selftext else title),
                        context=title[:200],
                        source_url=source_url,
                        source_type="reddit",
                        source_platform_id=post_id,
                        ticker=ticker,
                        direction=direction,
                        outcome="pending",
                        prediction_date=post_date,
                        window_days=365,
                        verified_by="ai_parsed",
                    ))
                    added += 1
                db.commit()
            except Exception as e:
                print(f"[RedditExpanded] r/{subreddit} error: {e}")
                db.rollback()

    print(f"[RedditExpanded] Added {added} predictions from {len(EXPANDED_SUBREDDITS)} subreddits")
