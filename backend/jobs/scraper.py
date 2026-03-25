"""
Scraper job — fetches new predictions from Twitter/X and YouTube.
Runs every hour via APScheduler.
"""
import httpx
import os
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


def scrape_twitter(db: Session):
    """Fetch recent prediction-related tweets from tracked forecasters."""
    if not TWITTER_BEARER:
        print("[Scraper] No TWITTER_BEARER_TOKEN, skipping X scrape")
        return

    headers = {"Authorization": f"Bearer {TWITTER_BEARER}"}
    forecasters = db.query(Forecaster).filter(
        Forecaster.channel_url.contains("x.com")
    ).all()

    new_count = 0
    for f in forecasters:
        handle = f.channel_url.rstrip("/").split("/")[-1]
        try:
            r = httpx.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers=headers,
                params={
                    "query": f"from:{handle} (predict OR will OR target OR expect) -is:retweet",
                    "max_results": 10,
                    "tweet.fields": "created_at,text",
                },
                timeout=10,
            )
            if r.status_code != 200:
                print(f"[Scraper] Twitter API {r.status_code} for {handle}")
                continue

            for tweet in r.json().get("data", []):
                # Skip if we already have this tweet
                if db.query(Prediction).filter(
                    Prediction.source_platform_id == tweet["id"]
                ).first():
                    continue

                db.add(Prediction(
                    forecaster_id=f.id,
                    ticker="UNKNOWN",  # Will be parsed by AI later
                    direction="bullish",  # Will be classified later
                    prediction_date=datetime.utcnow(),
                    window_days=30,
                    outcome="pending",
                    exact_quote=tweet["text"][:500],
                    context=tweet["text"][:200],
                    source_type="twitter",
                    source_platform_id=tweet["id"],
                    source_url=f"https://x.com/{handle}/status/{tweet['id']}",
                    verified_by="ai_parsed",
                ))
                new_count += 1
        except Exception as e:
            print(f"[Scraper] Twitter error for {handle}: {e}")

    db.commit()
    if new_count:
        print(f"[Scraper] Found {new_count} new tweets")


def scrape_youtube(db: Session):
    """Fetch recent prediction videos from tracked YouTube forecasters."""
    if not YOUTUBE_API_KEY:
        print("[Scraper] No YOUTUBE_API_KEY, skipping YouTube scrape")
        return

    forecasters = db.query(Forecaster).filter(
        Forecaster.channel_url.contains("youtube.com")
    ).all()

    new_count = 0
    for f in forecasters:
        handle = f.channel_url.rstrip("/").split("/@")[-1] if "/@" in (f.channel_url or "") else f.handle
        try:
            r = httpx.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "key": YOUTUBE_API_KEY,
                    "q": f"{handle} prediction forecast",
                    "type": "video",
                    "maxResults": 5,
                    "order": "date",
                    "part": "snippet",
                },
                timeout=10,
            )
            if r.status_code != 200:
                print(f"[Scraper] YouTube API {r.status_code} for {handle}")
                continue

            for item in r.json().get("items", []):
                vid_id = item["id"].get("videoId")
                if not vid_id:
                    continue
                # Skip if we already have this video
                if db.query(Prediction).filter(
                    Prediction.source_platform_id == vid_id
                ).first():
                    continue

                title = item["snippet"]["title"][:500]
                db.add(Prediction(
                    forecaster_id=f.id,
                    ticker="UNKNOWN",  # Will be parsed by AI later
                    direction="bullish",  # Will be classified later
                    prediction_date=datetime.utcnow(),
                    window_days=30,
                    outcome="pending",
                    exact_quote=title,
                    context=title[:200],
                    source_type="youtube",
                    source_platform_id=vid_id,
                    source_url=f"https://youtube.com/watch?v={vid_id}",
                    source_title=title,
                    verified_by="ai_parsed",
                ))
                new_count += 1
        except Exception as e:
            print(f"[Scraper] YouTube error for {handle}: {e}")

    db.commit()
    if new_count:
        print(f"[Scraper] Found {new_count} new YouTube videos")


def run_scraper(db: Session):
    """Main entry point — scrape all platforms."""
    print(f"[Scraper] Starting at {datetime.utcnow().isoformat()}")
    try:
        scrape_twitter(db)
        scrape_youtube(db)
        print("[Scraper] Done")
    except Exception as e:
        print(f"[Scraper] Fatal error: {e}")
    finally:
        db.close()
