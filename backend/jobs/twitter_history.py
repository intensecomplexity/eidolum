"""
Twitter/X historical prediction scraper — goes back 1 year for major finance accounts.
Extracts predictions using keyword matching on tweet text.
"""
import os
import re
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")

PREDICTION_PATTERN = re.compile(
    r'(price target|will reach|going to|could hit|expect|predict|forecast|'
    r'bull|bear|buy|sell|short|long|target of|I think|I believe|overvalued|'
    r'undervalued|crash|moon|bottom|top|\$[A-Z]{1,5})',
    re.IGNORECASE
)

TWITTER_ACCOUNTS = [
    {"name": "Michael Saylor",       "handle": "saylor"},
    {"name": "Elon Musk",            "handle": "elonmusk"},
    {"name": "Jim Cramer",           "handle": "jimcramer"},
    {"name": "Peter Schiff",         "handle": "PeterSchiff"},
    {"name": "Raoul Pal",            "handle": "RaoulGMI"},
    {"name": "Cathie Wood",          "handle": "CathieDWood"},
    {"name": "Bill Ackman",          "handle": "BillAckman"},
    {"name": "Tom Lee",              "handle": "fundstrat"},
    {"name": "Dan Ives",             "handle": "DanIves"},
    {"name": "Chamath Palihapitiya", "handle": "chamath"},
    {"name": "Unusual Whales",       "handle": "unusual_whales"},
    {"name": "Liz Ann Sonders",      "handle": "LizAnnSonders"},
    {"name": "Gary Black",           "handle": "GaryBlack00"},
]


def get_user_id(handle: str, headers: dict) -> str | None:
    try:
        r = httpx.get(
            f"https://api.twitter.com/2/users/by/username/{handle}",
            headers=headers, timeout=10
        )
        return r.json().get("data", {}).get("id")
    except Exception:
        return None


def scrape_twitter_history(db: Session):
    """Scrape up to 1 year of tweets from tracked Twitter/X accounts."""
    if not TWITTER_BEARER:
        print("[TwitterHistory] No TWITTER_BEARER_TOKEN, skipping")
        return

    headers = {"Authorization": f"Bearer {TWITTER_BEARER}"}
    total = 0

    for account in TWITTER_ACCOUNTS:
        handle = account["handle"]
        first_name = account["name"].split()[0]
        forecaster = db.query(Forecaster).filter(
            Forecaster.name.ilike(f"%{first_name}%")
        ).first()
        if not forecaster:
            print(f"[TwitterHistory] Forecaster not found: {account['name']}")
            continue

        user_id = get_user_id(handle, headers)
        if not user_id:
            print(f"[TwitterHistory] User ID not found: {handle}")
            continue

        try:
            r = httpx.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets",
                headers=headers,
                params={
                    "max_results": 100,
                    "tweet.fields": "created_at,text",
                    "exclude": "retweets,replies",
                    "start_time": (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                timeout=15
            )
            tweets = r.json().get("data", [])

            added = 0
            for tweet in tweets:
                if not PREDICTION_PATTERN.search(tweet["text"]):
                    continue

                source_url = f"https://x.com/{handle}/status/{tweet['id']}"

                # Skip duplicates
                if db.query(Prediction).filter(
                    Prediction.source_url == source_url
                ).first():
                    continue

                # Detect ticker from $TICKER patterns
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
                    outcome="pending_review",
                    prediction_date=pred_date,
                    window_days=365,
                    verified_by="ai_parsed",
                )
                db.add(p)
                added += 1

            db.commit()
            total += added
            print(f"[TwitterHistory] {forecaster.name}: {added} predictions from {len(tweets)} tweets")

        except Exception as e:
            print(f"[TwitterHistory] Error for {handle}: {e}")
            db.rollback()

    print(f"[TwitterHistory] Done! Total predictions added: {total}")
