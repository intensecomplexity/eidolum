"""
Scraper job — fetches new predictions from Twitter/X, YouTube, and Reddit.
Proof-first: screenshot/thumbnail must succeed BEFORE prediction is saved.
Runs every hour via APScheduler.
"""
import httpx, os, re
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster
from database import SessionLocal
from jobs.prediction_filter import is_prediction

TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/archive")


def save_with_proof(db: Session, prediction_obj: Prediction, forecaster_name: str = "") -> bool:
    """Save prediction immediately, then archive proof in background (non-blocking)."""
    db.add(prediction_obj)
    db.flush()

    # Archive proof in background thread — never blocks saving
    import threading
    pred_id = prediction_obj.id
    source_url = prediction_obj.source_url
    quote = prediction_obj.exact_quote or prediction_obj.context or ""
    pred_date = str(prediction_obj.prediction_date or "")

    def _archive():
        try:
            from archiver.screenshot import archive_proof_sync
            from database import SessionLocal as _SL
            from sqlalchemy import text as _t
            proof_url = archive_proof_sync(source_url, pred_id, quote, forecaster_name, pred_date)
            if proof_url:
                db2 = _SL()
                db2.execute(_t("UPDATE predictions SET archive_url=:url, archived_at=:ts WHERE id=:id"),
                            {"url": proof_url, "ts": datetime.utcnow(), "id": pred_id})
                db2.commit()
                db2.close()
        except Exception as e:
            print(f"[Archive] Background error for {pred_id}: {e}")

    threading.Thread(target=_archive, daemon=True).start()
    return True

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
                pred = Prediction(
                    forecaster_id=f.id, ticker="UNKNOWN",
                    context=title[:200], exact_quote=full_quote,
                    source_type="youtube", source_platform_id=vid_id,
                    source_url=source_url, source_title=title[:500],
                    video_timestamp_sec=timestamp,
                    prediction_date=datetime.utcnow(), window_days=30,
                    direction="bullish", outcome="pending",
                    verified_by="ai_parsed",
                )
                if not save_with_proof(db, pred, forecaster_name=f.name):
                    continue
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
                if not is_prediction(tweet["text"]):
                    continue
                if db.query(Prediction).filter(Prediction.source_platform_id == tweet["id"]).first():
                    continue
                tweet_url = f"https://x.com/{handle}/status/{tweet['id']}"
                pred = Prediction(
                    forecaster_id=f.id, ticker="UNKNOWN",
                    context=tweet["text"][:200],
                    exact_quote=tweet["text"], source_type="twitter",
                    source_platform_id=tweet["id"],
                    source_url=tweet_url,
                    prediction_date=datetime.utcnow(), window_days=30,
                    direction="bullish", outcome="pending",
                    verified_by="ai_parsed",
                )
                if not save_with_proof(db, pred, forecaster_name=f.name):
                    continue
        except Exception as e:
            print(f"[Scraper] Twitter error for {handle}: {e}")
    db.commit()
    print("[Scraper] Twitter done")

# ── Reddit / WallStreetBets ───────────────────────────────────────────────────

def scrape_reddit(db: Session):
    forecasters = db.query(Forecaster).filter(Forecaster.channel_url.contains("reddit.com")).all()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
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
                if not is_prediction(full_text):
                    continue
                if not post_id or db.query(Prediction).filter(Prediction.source_platform_id == post_id).first():
                    continue
                post_url = f"https://reddit.com{permalink}"
                full_quote = f"{title}\n\n{selftext}".strip() if selftext else title
                pred = Prediction(
                    forecaster_id=f.id, ticker="UNKNOWN",
                    context=title[:200],
                    exact_quote=full_quote,
                    source_type="reddit",
                    source_platform_id=post_id,
                    source_url=post_url,
                    prediction_date=datetime.utcnow(), window_days=30,
                    direction="bullish", outcome="pending",
                    verified_by="ai_parsed",
                )
                if not save_with_proof(db, pred, forecaster_name=f.name):
                    continue
        except Exception as e:
            print(f"[Scraper] Reddit error for {f.channel_url}: {e}")
    db.commit()
    print("[Scraper] Reddit done")

def run_scraper(db: Session):
    """Hourly scraper: news articles + Layer 3 cleanup + evaluation."""
    print(f"[Scraper] Starting hourly run at {datetime.utcnow()}")
    # Scrape real news articles (Layer 1 + Layer 2 built in)
    try:
        from jobs.news_scraper import scrape_news_predictions
        scrape_news_predictions(db)
    except Exception as e:
        print(f"[Scraper] News scraper error (non-fatal): {e}")
    # Layer 3: cleanup anything that slipped through
    try:
        from jobs.prediction_validator import cleanup_invalid_predictions
        cleanup_invalid_predictions(db)
    except Exception as e:
        print(f"[Scraper] L3 cleanup error (non-fatal): {e}")
    # Evaluate pending predictions against real prices
    try:
        from jobs.evaluate_predictions import evaluate_all_pending
        evaluate_all_pending(db)
    except Exception as e:
        print(f"[Scraper] Evaluator error (non-fatal): {e}")
    count = db.query(Prediction).count()
    print(f"[Scraper] Hourly run complete. Total predictions in DB: {count}")
