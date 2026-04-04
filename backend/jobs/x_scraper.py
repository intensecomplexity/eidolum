"""
X/Twitter Stock Prediction Scraper for Eidolum — V1 (Log Only)

Uses Apify Twitter scraper to find stock predictions from X.
Extracts tickers and direction from tweet text using regex.
V1: Logs what it would create. No prediction inserts.

Schedule: every 6 hours, independent (no SCRAPER_LOCK).
Requires: APIFY_API_TOKEN env var from apify.com console.
"""
import os
import re
import time
import httpx
from datetime import datetime, timedelta

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "").strip()

# Apify Twitter scraper actor
APIFY_ACTOR = "apidojo/tweet-scraper"
APIFY_API = "https://api.apify.com/v2"

# Top tickers to search (high volume, most likely on fintwit)
DEFAULT_TICKERS = [
    "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "AMD",
    "PLTR", "SOFI", "NIO", "COIN", "BABA", "DIS", "NFLX", "BA",
    "JPM", "GS", "V", "MA", "PYPL", "SQ", "SHOP", "SNOW", "CRM",
]

BULLISH_WORDS = {
    "buy", "bull", "long", "calls", "moon", "undervalued", "buying",
    "accumulate", "load", "added", "position", "bullish", "breakout",
    "upside", "upgrade", "outperform", "sending", "ripping",
}
BEARISH_WORDS = {
    "sell", "bear", "short", "puts", "overvalued", "selling", "dump",
    "avoid", "exit", "bearish", "downgrade", "downside", "crash",
    "bubble", "underperform", "tanking", "fading",
}

# Minimum quality
MIN_LIKES = 10
MIN_FOLLOWERS = 1000
MAX_CASHTAGS = 3


def _extract_predictions(text: str, author: str, url: str, date: str) -> list:
    """Extract stock predictions from a tweet using regex."""
    tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
    if not tickers or len(tickers) > MAX_CASHTAGS:
        return []

    text_lower = text.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in text_lower)
    bear = sum(1 for w in BEARISH_WORDS if w in text_lower)

    if bull == 0 and bear == 0:
        return []

    direction = "bullish" if bull > bear else "bearish"

    target_match = re.search(
        r'(?:target|pt|price target|TP)\s*\$?(\d+(?:\.\d+)?)', text, re.IGNORECASE
    )
    price_target = float(target_match.group(1)) if target_match else None

    return [{
        "ticker": t,
        "direction": direction,
        "price_target": price_target,
        "source_url": url,
        "forecaster": f"@{author}",
        "date": date,
        "context": text[:280],
    } for t in tickers]


def _run_apify(search_terms: list, max_tweets: int = 200) -> list:
    """Run Apify Twitter scraper and return tweet results."""
    try:
        # Start actor run
        r = httpx.post(
            f"{APIFY_API}/acts/{APIFY_ACTOR}/runs",
            params={"token": APIFY_API_TOKEN},
            json={
                "searchTerms": search_terms,
                "maxTweets": max_tweets,
                "sort": "Latest",
                "tweetLanguage": "en",
            },
            timeout=30,
        )
        if r.status_code != 201:
            print(f"[XScraper] Apify start failed: HTTP {r.status_code}")
            return []

        run_id = r.json().get("data", {}).get("id")
        if not run_id:
            print("[XScraper] Apify returned no run ID")
            return []

        print(f"[XScraper] Apify run started: {run_id}")

        # Poll for completion (max 5 minutes)
        for _ in range(60):
            time.sleep(5)
            sr = httpx.get(
                f"{APIFY_API}/actor-runs/{run_id}",
                params={"token": APIFY_API_TOKEN},
                timeout=10,
            )
            status = sr.json().get("data", {}).get("status", "")
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break

        if status != "SUCCEEDED":
            print(f"[XScraper] Apify run ended: {status}")
            return []

        # Get results
        dr = httpx.get(
            f"{APIFY_API}/actor-runs/{run_id}/dataset/items",
            params={"token": APIFY_API_TOKEN},
            timeout=30,
        )
        items = dr.json() if dr.status_code == 200 else []
        return items if isinstance(items, list) else []

    except Exception as e:
        print(f"[XScraper] Apify error: {e}")
        return []


def run_x_scraper(db=None):
    """Main entry point. LOG ONLY — does not insert predictions."""
    if not APIFY_API_TOKEN:
        print("[XScraper] APIFY_API_TOKEN not set — skipping")
        return

    print("[XScraper] Starting run")

    # Build search terms: "$TICKER buy OR sell OR bull OR bear"
    search_terms = [f"${t} buy OR sell OR bull OR bear" for t in DEFAULT_TICKERS[:10]]
    print(f"[XScraper] Searching {len(search_terms)} terms")

    tweets = _run_apify(search_terms, max_tweets=200)
    print(f"[XScraper] Got {len(tweets)} tweets from Apify")

    total_predictions = 0
    total_skipped = 0
    total_no_signal = 0

    for tweet in tweets:
        # Extract fields (Apify format varies by actor version)
        text = tweet.get("full_text") or tweet.get("text") or ""
        author = (tweet.get("user", {}).get("screen_name")
                  or tweet.get("author", {}).get("userName") or "unknown")
        tweet_id = tweet.get("id_str") or str(tweet.get("id", ""))
        url = tweet.get("url") or f"https://x.com/{author}/status/{tweet_id}"
        date_str = (tweet.get("created_at") or tweet.get("createdAt") or "")[:10]
        likes = (tweet.get("favorite_count") or tweet.get("likeCount") or 0)
        followers = (tweet.get("user", {}).get("followers_count")
                     or tweet.get("author", {}).get("followers") or 0)
        is_rt = tweet.get("retweeted") or text.startswith("RT @")

        # Quality filters
        if is_rt:
            continue
        if likes < MIN_LIKES:
            total_skipped += 1
            continue
        if followers < MIN_FOLLOWERS:
            total_skipped += 1
            continue

        # Extract predictions
        preds = _extract_predictions(text, author, url, date_str)
        if not preds:
            total_no_signal += 1
            continue

        for p in preds:
            total_predictions += 1
            target_str = f", target=${p['price_target']:.0f}" if p["price_target"] else ""
            print(f"[XScraper] WOULD CREATE: @{author} → {p['direction'].upper()} on {p['ticker']}"
                  f"{target_str} [likes={likes:,}]")
            if total_predictions <= 10:
                print(f"[XScraper]   Tweet: {text[:120]}")
                print(f"[XScraper]   URL: {url}")

    print(f"[XScraper] Run complete — {len(tweets)} tweets, {total_predictions} would-create, "
          f"{total_skipped} low engagement, {total_no_signal} no clear signal")
