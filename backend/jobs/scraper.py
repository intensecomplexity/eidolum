"""
Scraper job — fetches new predictions from Twitter/X, YouTube, and Reddit.
Proof-first: screenshot/thumbnail must succeed BEFORE prediction is saved.
Runs every hour via APScheduler.
"""
import httpx, os, re, shutil
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster
from database import SessionLocal
from jobs.prediction_filter import is_prediction

TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/archive")


def save_with_proof(db: Session, prediction_obj: Prediction) -> bool:
    """
    Try to archive proof FIRST. Only save the prediction if proof is obtained.
    Returns True if saved, False if rejected.
    """
    from archiver.screenshot import archive_proof_sync

    proof_url = archive_proof_sync(prediction_obj.source_url, 0)
    if not proof_url:
        print(f"[Archive] REJECTED — no proof for: {(prediction_obj.source_url or '')[:80]}")
        return False

    prediction_obj.archive_url = proof_url
    prediction_obj.archived_at = datetime.utcnow()
    db.add(prediction_obj)
    db.flush()  # get real ID

    # Rename archive file from p0_ to real ID
    if proof_url.startswith("/archive/p0_"):
        old_name = proof_url.replace("/archive/", "")
        new_name = old_name.replace("p0_", f"p{prediction_obj.id}_")
        old_path = os.path.join(ARCHIVE_DIR, old_name)
        new_path = os.path.join(ARCHIVE_DIR, new_name)
        if os.path.exists(old_path) and old_path != new_path:
            shutil.move(old_path, new_path)
            prediction_obj.archive_url = f"/archive/{new_name}"

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
                if not save_with_proof(db, pred):
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
                if not save_with_proof(db, pred):
                    continue
        except Exception as e:
            print(f"[Scraper] Twitter error for {handle}: {e}")
    db.commit()
    print("[Scraper] Twitter done")

# ── Reddit / WallStreetBets ───────────────────────────────────────────────────

def scrape_reddit(db: Session):
    forecasters = db.query(Forecaster).filter(Forecaster.channel_url.contains("reddit.com")).all()
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
                if not save_with_proof(db, pred):
                    continue
        except Exception as e:
            print(f"[Scraper] Reddit error for {f.channel_url}: {e}")
    db.commit()
    print("[Scraper] Reddit done")

def run_scraper(db: Session):
    print(f"[Scraper] Starting hourly run at {datetime.utcnow()}")
    scrape_twitter(db)
    scrape_youtube(db)
    scrape_reddit(db)
    try:
        from jobs.quiver_scraper import scrape_congress_trades
        scrape_congress_trades(db)
    except Exception as e:
        print(f"[Scraper] Quiver error (non-fatal): {e}")
    try:
        from jobs.youtube_history import run_youtube_history
        run_youtube_history(db)
    except Exception as e:
        print(f"[Scraper] YouTube history error (non-fatal): {e}")
    try:
        from jobs.twitter_history import scrape_twitter_history
        scrape_twitter_history(db)
    except Exception as e:
        print(f"[Scraper] Twitter history error (non-fatal): {e}")
    try:
        from jobs.reddit_history import scrape_reddit_history
        scrape_reddit_history(db)
    except Exception as e:
        print(f"[Scraper] Reddit history error (non-fatal): {e}")
    try:
        from jobs.analyst_targets import scrape_analyst_targets
        scrape_analyst_targets(db)
    except Exception as e:
        print(f"[Scraper] Analyst targets error (non-fatal): {e}")
    try:
        from jobs.kalshi_scraper import scrape_kalshi
        scrape_kalshi(db)
    except Exception as e:
        print(f"[Scraper] Kalshi error (non-fatal): {e}")
    try:
        from jobs.earnings_calls import scrape_earnings_calls
        scrape_earnings_calls(db)
    except Exception as e:
        print(f"[Scraper] Earnings calls error (non-fatal): {e}")
    try:
        from jobs.tipranks_scraper import scrape_tipranks
        scrape_tipranks(db)
    except Exception as e:
        print(f"[Scraper] TipRanks/Benzinga error (non-fatal): {e}")
    try:
        from jobs.reddit_expanded import scrape_reddit_expanded
        scrape_reddit_expanded(db)
    except Exception as e:
        print(f"[Scraper] Reddit expanded error (non-fatal): {e}")
    try:
        from jobs.substack_scraper import scrape_substacks
        scrape_substacks(db)
    except Exception as e:
        print(f"[Scraper] Substack error (non-fatal): {e}")
    try:
        from jobs.finviz_scraper import scrape_finviz_upgrades
        scrape_finviz_upgrades(db)
    except Exception as e:
        print(f"[Scraper] Finviz error (non-fatal): {e}")
    count = db.query(Prediction).count()
    print(f"[Scraper] Hourly run complete. Total predictions in DB: {count}")
