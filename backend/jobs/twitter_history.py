"""
Twitter/X historical prediction scraper.
Batches 20 accounts per run with offset rotation so all accounts
get covered every ~6 hours. Detailed error logging for debugging.
"""
import os
import re
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from models import Prediction, Forecaster
from jobs.prediction_filter import is_prediction

TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
BATCH_SIZE = 20  # Free tier: 15 req/15min — 20 accounts × 2 req = 40/hour is safe


# ── Config helpers ────────────────────────────────────────────────────────────

def _get_config(db: Session, key: str, default: str = "0") -> str:
    try:
        row = db.execute(sql_text("SELECT value FROM config WHERE key = :k"), {"k": key}).first()
        return row[0] if row else default
    except Exception:
        return default


def _set_config(db: Session, key: str, value: str):
    try:
        db.execute(sql_text(
            "INSERT INTO config (key, value) VALUES (:k, :v) "
            "ON CONFLICT(key) DO UPDATE SET value = :v"
        ), {"k": key, "v": value})
        db.commit()
    except Exception:
        db.rollback()


# ── Main scraper ──────────────────────────────────────────────────────────────

def scrape_twitter_history(db: Session):
    """Scrape a batch of 20 Twitter accounts with detailed logging."""
    if not TWITTER_BEARER:
        print("[Twitter] No TWITTER_BEARER_TOKEN set, skipping")
        return

    # Credits depleted — skip until next month reset
    print("[Twitter] Skipping — credits depleted until next month reset")
    return

    print(f"[Twitter] Bearer token set: True, length: {len(TWITTER_BEARER)}")
    headers = {"Authorization": f"Bearer {TWITTER_BEARER}"}

    # Get all X/Twitter forecasters
    forecasters = db.query(Forecaster).filter(
        Forecaster.channel_url.contains("x.com")
    ).all()
    total_accounts = len(forecasters)

    if not forecasters:
        print("[Twitter] No forecasters with x.com URLs found")
        return

    # Rotate batch offset
    offset = int(_get_config(db, "twitter_scrape_offset", "0"))
    batch = forecasters[offset:offset + BATCH_SIZE]
    if len(batch) < BATCH_SIZE and offset > 0:
        batch += forecasters[:BATCH_SIZE - len(batch)]
    next_offset = (offset + BATCH_SIZE) % total_accounts
    _set_config(db, "twitter_scrape_offset", str(next_offset))

    print(f"[Twitter] Scraping batch of {len(batch)}/{total_accounts} accounts (offset {offset}->{next_offset})")

    total_added = 0
    scraped = 0
    skipped = 0

    for forecaster in batch:
        handle = forecaster.channel_url.rstrip("/").split("/")[-1]
        if not handle:
            skipped += 1
            continue

        # Step 1: Get user ID
        try:
            r = httpx.get(
                f"https://api.twitter.com/2/users/by/username/{handle}",
                headers=headers, timeout=10
            )
        except Exception as e:
            print(f"[Twitter] @{handle}: connection error: {e}")
            skipped += 1
            time.sleep(2)
            continue

        if r.status_code == 429:
            print(f"[Twitter] Rate limited on user lookup after {scraped} accounts. Stopping batch.")
            break
        if r.status_code == 401:
            print(f"[Twitter] BEARER TOKEN INVALID — check TWITTER_BEARER_TOKEN env var. Response: {r.text[:200]}")
            break
        if r.status_code == 403:
            print(f"[Twitter] Forbidden for @{handle} — may need elevated access. Response: {r.text[:200]}")
            skipped += 1
            time.sleep(2)
            continue
        if r.status_code != 200:
            print(f"[Twitter] @{handle}: user lookup returned {r.status_code}: {r.text[:200]}")
            skipped += 1
            time.sleep(2)
            continue

        user_id = r.json().get("data", {}).get("id")
        if not user_id:
            print(f"[Twitter] @{handle}: no user ID in response: {r.text[:150]}")
            skipped += 1
            time.sleep(2)
            continue

        # Step 2: Get tweets
        try:
            r2 = httpx.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets",
                headers=headers,
                params={
                    "max_results": 10,
                    "tweet.fields": "created_at,text",
                    "exclude": "retweets,replies",
                },
                timeout=15,
            )
        except Exception as e:
            print(f"[Twitter] @{handle}: tweets connection error: {e}")
            skipped += 1
            time.sleep(2)
            continue

        if r2.status_code == 429:
            print(f"[Twitter] Rate limited on tweets after {scraped} accounts. Stopping batch.")
            break
        if r2.status_code != 200:
            print(f"[Twitter] @{handle}: tweets returned {r2.status_code}: {r2.text[:200]}")
            skipped += 1
            time.sleep(2)
            continue

        tweets = r2.json().get("data", [])
        scraped += 1
        added = 0

        for tweet in tweets:
            if not is_prediction(tweet.get("text", "")):
                continue

            source_url = f"https://x.com/{handle}/status/{tweet['id']}"

            if db.query(Prediction).filter(Prediction.source_url == source_url).first():
                continue

            ticker_match = re.search(r'\$([A-Z]{1,5})', tweet["text"])
            ticker = ticker_match.group(1) if ticker_match else "SPY"

            text_lower = tweet["text"].lower()
            direction = "bearish" if any(w in text_lower for w in [
                "bear", "sell", "short", "crash", "drop", "fall", "overvalued", "avoid"
            ]) else "bullish"

            try:
                pred_date = datetime.strptime(tweet["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
            except Exception:
                pred_date = datetime.utcnow()

            p = Prediction(
                forecaster_id=forecaster.id,
                context=tweet["text"][:200],
                exact_quote=tweet["text"][:500],
                source_url=source_url,
                source_type="twitter",
                source_platform_id=tweet["id"],
                ticker=ticker,
                direction=direction,
                outcome="pending",
                prediction_date=pred_date,
                window_days=365,
                verified_by="ai_parsed",
            )
            db.add(p)
            added += 1

        if added:
            db.commit()
            total_added += added
            print(f"[Twitter] @{handle}: +{added} predictions from {len(tweets)} tweets")

        time.sleep(2)  # 2s between accounts to stay within rate limits

    print(f"[Twitter] Batch done: scraped {scraped}, skipped {skipped}, added {total_added} predictions")


# ── Nitter fallback — scrapes public HTML when Twitter API is unavailable ─────

NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.woodland.cafe",
]


def _get_nitter_base() -> str | None:
    """Find a working Nitter instance."""
    for base in NITTER_INSTANCES:
        try:
            r = httpx.get(f"{base}/saylor", timeout=8, follow_redirects=True)
            if r.status_code == 200 and "tweet" in r.text.lower():
                return base
        except Exception:
            continue
    return None


def scrape_via_nitter(handle: str, forecaster_id: int, nitter_base: str, db: Session) -> int:
    """Scrape tweets for one handle via Nitter HTML."""
    added = 0
    try:
        r = httpx.get(
            f"{nitter_base}/{handle}/search",
            params={"f": "tweets", "q": "predict OR target OR buy OR sell OR bull OR bear"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return 0

        tweet_links = re.findall(
            rf'/{re.escape(handle)}/status/(\d+)',
            r.text,
            re.IGNORECASE,
        )
        tweet_ids = list(dict.fromkeys(tweet_links))[:50]

        for tweet_id in tweet_ids:
            source_url = f"https://x.com/{handle}/status/{tweet_id}"

            if db.query(Prediction).filter(Prediction.source_url == source_url).first():
                continue

            try:
                tr = httpx.get(
                    f"{nitter_base}/{handle}/status/{tweet_id}",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10,
                    follow_redirects=True,
                )
                text_match = re.search(
                    r'class="tweet-content[^"]*"[^>]*>(.*?)</div>',
                    tr.text,
                    re.DOTALL,
                )
                if not text_match:
                    continue
                tweet_text = re.sub(r'<[^>]+>', ' ', text_match.group(1)).strip()
            except Exception:
                continue

            if not is_prediction(tweet_text):
                continue

            ticker_match = re.search(r'\$([A-Z]{1,5})', tweet_text)
            ticker = ticker_match.group(1) if ticker_match else "SPY"

            text_lower = tweet_text.lower()
            direction = "bearish" if any(w in text_lower for w in [
                "bear", "sell", "short", "crash", "drop", "fall", "overvalued", "avoid"
            ]) else "bullish"

            date_match = re.search(r'class="tweet-date"[^>]*><a[^>]*title="([^"]+)"', tr.text)
            try:
                pred_date = datetime.strptime(date_match.group(1).split(" \u00b7 ")[0].strip(), "%b %d, %Y")
            except Exception:
                pred_date = datetime.utcnow()

            p = Prediction(
                forecaster_id=forecaster_id,
                context=tweet_text[:200],
                exact_quote=tweet_text[:500],
                source_url=source_url,
                source_type="twitter",
                source_platform_id=tweet_id,
                ticker=ticker,
                direction=direction,
                outcome="pending",
                prediction_date=pred_date,
                window_days=365,
                verified_by="ai_parsed",
            )
            db.add(p)
            added += 1

        if added:
            db.commit()

    except Exception as e:
        print(f"[Nitter] Error for {handle}: {e}")
        db.rollback()

    return added


def scrape_via_nitter_all(db: Session):
    """Scrape historical tweets via Nitter for all tracked accounts."""
    nitter_base = _get_nitter_base()
    if not nitter_base:
        print("[Nitter] No working Nitter instance found, skipping")
        return

    print(f"[Nitter] Using {nitter_base}")
    total = 0

    forecasters = db.query(Forecaster).filter(
        Forecaster.channel_url.contains("x.com")
    ).all()
    for forecaster in forecasters:
        handle = forecaster.channel_url.rstrip("/").split("/")[-1]
        if not handle:
            continue

        added = scrape_via_nitter(handle, forecaster.id, nitter_base, db)
        if added:
            print(f"[Nitter] {forecaster.name}: {added} predictions")
        total += added

    print(f"[Nitter] Done! Total predictions added: {total}")
