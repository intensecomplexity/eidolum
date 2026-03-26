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

from jobs.prediction_filter import is_prediction

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
    """Scrape recent tweets from tracked Twitter/X accounts."""
    if not TWITTER_BEARER:
        print("[TwitterHistory] No TWITTER_BEARER_TOKEN, skipping")
        return

    import time
    headers = {"Authorization": f"Bearer {TWITTER_BEARER}"}
    total = 0
    scraped = 0
    skipped = 0

    forecasters = db.query(Forecaster).filter(
        Forecaster.channel_url.contains("x.com")
    ).all()
    print(f"[TwitterHistory] Found {len(forecasters)} Twitter accounts to scrape")

    for forecaster in forecasters:
        handle = forecaster.channel_url.rstrip("/").split("/")[-1]
        if not handle:
            skipped += 1
            continue

        user_id = get_user_id(handle, headers)
        if not user_id:
            skipped += 1
            continue

        try:
            r = httpx.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets",
                headers=headers,
                params={
                    "max_results": 10,
                    "tweet.fields": "created_at,text",
                    "exclude": "retweets,replies",
                },
                timeout=15,
            )

            if r.status_code == 429:
                print(f"[TwitterHistory] Rate limited after {scraped} accounts. Stopping.")
                break

            if r.status_code != 200:
                print(f"[TwitterHistory] API error {r.status_code} for {handle}: {r.text[:200]}")
                skipped += 1
                time.sleep(1)
                continue

            tweets = r.json().get("data", [])
            scraped += 1

            added = 0
            for tweet in tweets:
                if not is_prediction(tweet["text"]):
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
                    outcome="pending",
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

        time.sleep(1)  # Rate limit courtesy

    print(f"[TwitterHistory] Done! Scraped {scraped}, skipped {skipped}, added {total} predictions")


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
        # Nitter search for prediction-related tweets
        r = httpx.get(
            f"{nitter_base}/{handle}/search",
            params={"f": "tweets", "q": "predict OR target OR buy OR sell OR bull OR bear"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return 0

        # Extract tweet links from HTML
        tweet_links = re.findall(
            rf'/{re.escape(handle)}/status/(\d+)',
            r.text,
            re.IGNORECASE,
        )
        # Deduplicate
        tweet_ids = list(dict.fromkeys(tweet_links))[:50]

        for tweet_id in tweet_ids:
            source_url = f"https://x.com/{handle}/status/{tweet_id}"

            if db.query(Prediction).filter(
                Prediction.source_url == source_url
            ).first():
                continue

            # Fetch individual tweet page for text
            try:
                tr = httpx.get(
                    f"{nitter_base}/{handle}/status/{tweet_id}",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10,
                    follow_redirects=True,
                )
                # Extract tweet text from the main tweet content div
                text_match = re.search(
                    r'class="tweet-content[^"]*"[^>]*>(.*?)</div>',
                    tr.text,
                    re.DOTALL,
                )
                if not text_match:
                    continue
                # Strip HTML tags
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

            # Try to parse date from the page
            date_match = re.search(r'class="tweet-date"[^>]*><a[^>]*title="([^"]+)"', tr.text)
            try:
                pred_date = datetime.strptime(date_match.group(1).split(" · ")[0].strip(), "%b %d, %Y")
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


def scrape_nitter_rss(db: Session):
    """Scrape tweets via Nitter RSS feeds — no API key, no auth."""
    import feedparser
    from jobs.prediction_filter import is_valid_prediction

    NITTER_RSS_BASES = [
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
    ]

    forecasters = db.query(Forecaster).filter(
        Forecaster.channel_url.contains("x.com")
    ).all()
    print(f"[NitterRSS] Trying RSS for {len(forecasters)} accounts...")

    total = 0
    for forecaster in forecasters:
        handle = forecaster.channel_url.rstrip("/").split("/")[-1]
        if not handle:
            continue

        for base in NITTER_RSS_BASES:
            try:
                feed = feedparser.parse(f"{base}/{handle}/rss")
                if not feed.entries:
                    continue

                added = 0
                for entry in feed.entries[:15]:
                    text = entry.get("title", "") or entry.get("summary", "")
                    link = entry.get("link", "")
                    if not text or not is_valid_prediction(text):
                        continue

                    # Convert nitter link to x.com link
                    source_url = link.replace(base, "https://x.com") if base in link else link
                    if db.query(Prediction).filter(Prediction.source_url == source_url).first():
                        continue

                    try:
                        pub = entry.get("published_parsed")
                        pred_date = datetime(*pub[:6]) if pub else datetime.utcnow()
                    except Exception:
                        pred_date = datetime.utcnow()

                    p = Prediction(
                        forecaster_id=forecaster.id,
                        ticker="UNKNOWN",
                        direction="bullish",
                        exact_quote=text[:500],
                        context=text[:200],
                        source_url=source_url,
                        source_type="twitter",
                        prediction_date=pred_date,
                        window_days=365,
                        outcome="pending",
                        verified_by="ai_parsed",
                    )
                    db.add(p)
                    added += 1

                if added:
                    db.commit()
                    total += added
                    print(f"[NitterRSS] {forecaster.name}: {added} predictions")
                break  # Got results from this nitter instance, move on
            except Exception:
                continue

    print(f"[NitterRSS] Done! Added {total} predictions")
