"""
Scraper job — fetches new predictions from Twitter/X, YouTube, and Reddit.
Runs every hour via APScheduler.
"""
import httpx, os, re
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


def archive_url(url: str) -> str | None:
    """Submit URL to archive.ph and return the archived URL."""
    try:
        r = httpx.post(
            "https://archive.ph/submit/",
            data={"url": url},
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
            timeout=15,
        )
        if r.url and "archive.ph/" in str(r.url):
            return str(r.url)
        match = re.search(r'https://archive\.ph/\w+', r.text)
        return match.group(0) if match else None
    except Exception:
        return None

# ── YouTube ──────────────────────────────────────────────────────────────────

def get_prediction_timestamp(video_id: str, statement: str):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        keywords = [w.lower() for w in statement.split() if len(w) > 4]
        best_match, best_score = None, 0
        for entry in transcript:
            score = sum(1 for kw in keywords if kw in entry['text'].lower())
            if score > best_score:
                best_score, best_match = score, entry
        return int(best_match['start']) if best_match and best_score >= 2 else None
    except:
        return None

def scrape_youtube(db: Session):
    if not YOUTUBE_API_KEY:
        print("[Scraper] No YOUTUBE_API_KEY, skipping")
        return
    forecasters = db.query(Forecaster).filter(Forecaster.channel_url.contains("youtube.com")).all()
    for f in forecasters:
        handle = f.channel_url.rstrip("/").split("/@")[-1]
        try:
            r = httpx.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={"key": YOUTUBE_API_KEY, "q": f"{handle} prediction forecast", "type": "video",
                        "maxResults": 5, "order": "date", "part": "snippet"},
                timeout=10
            )
            for item in r.json().get("items", []):
                vid_id = item["id"].get("videoId")
                if not vid_id or db.query(Prediction).filter(Prediction.source_platform_id == vid_id).first():
                    continue
                title = item["snippet"]["title"]
                description = item["snippet"].get("description", "")
                timestamp = get_prediction_timestamp(vid_id, title)
                source_url = f"https://youtube.com/watch?v={vid_id}"
                if timestamp:
                    source_url = f"https://youtube.com/watch?v={vid_id}&t={timestamp}s"
                full_quote = f"{title}\n\n{description}".strip() if description else title
                db.add(Prediction(
                    forecaster_id=f.id, ticker="UNKNOWN",
                    context=title[:200], exact_quote=full_quote,
                    source_type="youtube", source_platform_id=vid_id,
                    source_url=source_url, source_title=title[:500],
                    video_timestamp_sec=timestamp,
                    prediction_date=datetime.utcnow(), window_days=30,
                    direction="bullish", outcome="pending",
                    verified_by="ai_parsed",
                ))
        except Exception as e:
            print(f"[Scraper] YouTube error for {handle}: {e}")
    db.commit()
    print("[Scraper] YouTube done")

# ── Twitter/X ─────────────────────────────────────────────────────────────────

def scrape_twitter(db: Session):
    if not TWITTER_BEARER:
        print("[Scraper] No TWITTER_BEARER_TOKEN, skipping")
        return
    headers = {"Authorization": f"Bearer {TWITTER_BEARER}"}
    forecasters = db.query(Forecaster).filter(Forecaster.channel_url.contains("x.com")).all()
    KEYWORDS = re.compile(r'predict|will|target|expect|price|\$|forecast|bull|bear', re.I)
    for f in forecasters:
        handle = f.channel_url.rstrip("/").split("/")[-1]
        try:
            # Get user ID
            r = httpx.get(f"https://api.twitter.com/2/users/by/username/{handle}",
                          headers=headers, timeout=10)
            user_id = r.json().get("data", {}).get("id")
            if not user_id:
                continue
            # Get timeline
            r = httpx.get(f"https://api.twitter.com/2/users/{user_id}/tweets",
                          headers=headers,
                          params={"max_results": 10, "tweet.fields": "created_at,text", "exclude": "retweets"},
                          timeout=10)
            for tweet in r.json().get("data", []):
                if not KEYWORDS.search(tweet["text"]):
                    continue
                if db.query(Prediction).filter(Prediction.source_platform_id == tweet["id"]).first():
                    continue
                tweet_url = f"https://x.com/{handle}/status/{tweet['id']}"
                archive = archive_url(tweet_url)
                db.add(Prediction(
                    forecaster_id=f.id, ticker="UNKNOWN",
                    context=tweet["text"][:200],
                    exact_quote=tweet["text"], source_type="twitter",
                    source_platform_id=tweet["id"],
                    source_url=tweet_url,
                    archive_url=archive,
                    prediction_date=datetime.utcnow(), window_days=30,
                    direction="bullish", outcome="pending",
                    verified_by="ai_parsed",
                ))
        except Exception as e:
            print(f"[Scraper] Twitter error for {handle}: {e}")
    db.commit()
    print("[Scraper] Twitter done")

# ── Reddit / WallStreetBets ───────────────────────────────────────────────────

def scrape_reddit(db: Session):
    forecasters = db.query(Forecaster).filter(Forecaster.channel_url.contains("reddit.com")).all()
    KEYWORDS = re.compile(r'predict|will|target|expect|price|\$|forecast|bull|bear|moon|calls|puts', re.I)
    headers = {"User-Agent": "eidolum-scraper/1.0"}
    for f in forecasters:
        # support both /r/subreddit and /user/username
        channel = f.channel_url.rstrip("/")
        if "/r/" in channel:
            subreddit = channel.split("/r/")[1].split("/")[0]
            url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=25"
        elif "/user/" in channel:
            username = channel.split("/user/")[1].split("/")[0]
            url = f"https://www.reddit.com/user/{username}/submitted.json?limit=25"
        else:
            continue
        try:
            r = httpx.get(url, headers=headers, timeout=10)
            posts = r.json().get("data", {}).get("children", [])
            for post in posts:
                data = post.get("data", {})
                post_id = data.get("id")
                title = data.get("title", "")
                selftext = data.get("selftext", "")
                permalink = data.get("permalink", "")
                full_text = f"{title} {selftext}"
                if not KEYWORDS.search(full_text):
                    continue
                if not post_id or db.query(Prediction).filter(Prediction.source_platform_id == post_id).first():
                    continue
                source_url = f"https://reddit.com{permalink}"
                full_quote = f"{title}\n\n{selftext}".strip() if selftext else title
                archive = archive_url(source_url)
                db.add(Prediction(
                    forecaster_id=f.id, ticker="UNKNOWN",
                    context=title[:200],
                    exact_quote=full_quote,
                    source_type="reddit",
                    source_platform_id=post_id,
                    source_url=source_url,
                    archive_url=archive,
                    prediction_date=datetime.utcnow(), window_days=30,
                    direction="bullish", outcome="pending",
                    verified_by="ai_parsed",
                ))
        except Exception as e:
            print(f"[Scraper] Reddit error for {f.channel_url}: {e}")
    db.commit()
    print("[Scraper] Reddit done")

def run_scraper(db: Session):
    print("[Scraper] Starting...")
    scrape_twitter(db)
    scrape_youtube(db)
    scrape_reddit(db)
    print("[Scraper] All done")
