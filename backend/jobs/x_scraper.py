"""
X/Twitter Stock Prediction Scraper for Eidolum — V1 (Log Only)

Uses Apify Twitter scraper to find forward-looking stock predictions on X.
Seven-layer filter pipeline rejects spam, past-tense brags, questions, and noise.
V1: Logs qualifying predictions. No database writes.

Schedule: every 6 hours, independent (no SCRAPER_LOCK).
Requires: APIFY_API_TOKEN env var.
"""
import os
import re
import time
import httpx
from datetime import datetime, timedelta

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "").strip()
APIFY_API = "https://api.apify.com/v2"
APIFY_ACTOR = "apidojo/tweet-scraper"

# ── Search query batches (rotate each run) ────────────────────────────────────
SEARCH_BATCHES = [
    ["price target $", "PT $", "target $"],
    ["buy $", "sell $", "long $", "short $"],
    ["breakout $", "breakdown $", "heading to $", "downside to $"],
    ["calls for $", "expecting $", "looking for $", "next stop $"],
]
_batch_index = 0

# ── Engagement minimums ──────────────────────────────────────────────────────
MIN_LIKES = 10
MIN_FOLLOWERS = 1000
MAX_CASHTAGS = 3

# ── Spam patterns ────────────────────────────────────────────────────────────
SPAM_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'join\s+(my|our)\s+(discord|telegram|group|channel)',
        r'free\s+signals?', r'DM\s+(me|for)', r'link\s+in\s+bio',
        r'subscribe', r'alert\s+service', r'paid\s+(group|channel|membership)',
        r'sign\s+up', r'promo\s+code', r'discord\.gg', r't\.me/',
    ]
]

# ── Past-tense patterns (reject brags about old trades) ──────────────────────
PAST_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\bi\s+bought\b', r'\bi\s+sold\b', r'\btook\s+profit',
        r'\bclosed\s+(my\s+)?position', r'\bnailed\s+it\b', r'\bcalled\s+it\b',
        r'\bwas\s+right\b', r'\btold\s+you\b', r'\balready\s+in\b',
        r'\bexited\b', r'\bbanked\b', r'\blocked\s+in\s+profit',
        r'\bcashed\s+out\b', r'\btook\s+the\s+trade\b',
        r'\bentered\s+(at|around)\b', r'\bgot\s+in\s+at\b',
        r'\bup\s+\d+%\s+(on|from)\b', r'\bbooked\b', r'\bclosed\s+for\b',
        r'\bsold\s+(half|some|all)\b', r'\btrimmed\b', r'\btrade\s+recap\b',
    ]
]

# ── Forward-looking patterns (at least one required) ─────────────────────────
FORWARD_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\btarget\b', r'\bPT\s*\$', r'\bprice\s+target\b',
        r'\bheading\s+to\b', r'\bwill\s+(reach|hit|break|test)\b',
        r'\bexpecting\b', r'\bsetup\b', r'\bbreakout\b', r'\bbreakdown\b',
        r'\bgoing\s+to\s+\$?\d', r'\blooking\s+for\b', r'\bnext\s+stop\b',
        r'\bdownside\s+to\b', r'\bupside\s+to\b', r'\bsupport\s+at\b',
        r'\bresistance\s+at\b', r'\bcalls?\s+for\b', r'\bsee\s+(it\s+)?hitting\b',
        r'\bbuy\b', r'\bsell\b', r'\blong\b', r'\bshort\b',
        r'\bbullish\b', r'\bbearish\b', r'\baccumulate\b', r'\bavoid\b',
    ]
]

# ── Direction signals ────────────────────────────────────────────────────────
BULL_WORDS = {
    "buy", "long", "calls", "bull", "bullish", "breakout", "upside",
    "moon", "ripping", "accumulate", "adding", "loading", "bounce",
    "undervalued", "cheap", "dip buy", "higher",
}
BEAR_WORDS = {
    "sell", "short", "puts", "bear", "bearish", "breakdown", "downside",
    "drilling", "dump", "avoid", "cutting", "overvalued", "fade",
    "rejected", "lower", "top is in",
}

# ── Price target patterns ────────────────────────────────────────────────────
PRICE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'(?:target|PT|price\s+target)\s*\$?([\d,.]+)',
        r'\$[A-Z]{1,5}\s+(?:to|at|towards?)\s+\$?([\d,.]+)',
        r'(?:heading|going|path)\s+to\s+\$?([\d,.]+)',
        r'(?:downside|upside)\s+(?:to|target)\s+\$?([\d,.]+)',
        r'next\s+stop\s+\$?([\d,.]+)',
    ]
]

# ── Question-only patterns ───────────────────────────────────────────────────
QUESTION_STARTS = re.compile(r'^(will|should|would|could|do you think|is)\b', re.IGNORECASE)


def _get_batch():
    """Get the next search query batch (rotates across runs)."""
    global _batch_index
    batch = SEARCH_BATCHES[_batch_index % len(SEARCH_BATCHES)]
    _batch_index += 1
    return batch


def _run_apify(search_terms: list, max_tweets: int = 200) -> list:
    """Run Apify Twitter scraper. Returns list of tweet dicts."""
    try:
        r = httpx.post(
            f"{APIFY_API}/acts/{APIFY_ACTOR}/runs",
            params={"token": APIFY_API_TOKEN},
            json={"searchTerms": search_terms, "maxTweets": max_tweets, "sort": "Latest", "tweetLanguage": "en"},
            timeout=30,
        )
        if r.status_code != 201:
            print(f"[X-SCRAPER] Apify start failed: HTTP {r.status_code}")
            return []

        run_id = r.json().get("data", {}).get("id")
        if not run_id:
            return []

        print(f"[X-SCRAPER] Apify run {run_id} started, polling...")

        for _ in range(30):
            time.sleep(10)
            sr = httpx.get(f"{APIFY_API}/actor-runs/{run_id}", params={"token": APIFY_API_TOKEN}, timeout=15)
            data = sr.json().get("data", {})
            status = data.get("status", "")
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break

        if status != "SUCCEEDED":
            print(f"[X-SCRAPER] Apify run ended: {status}")
            return []

        dataset_id = data.get("defaultDatasetId")
        if not dataset_id:
            return []

        dr = httpx.get(f"{APIFY_API}/datasets/{dataset_id}/items", params={"token": APIFY_API_TOKEN}, timeout=30)
        items = dr.json() if dr.status_code == 200 else []
        return items if isinstance(items, list) else []

    except Exception as e:
        print(f"[X-SCRAPER] Apify error: {e}")
        return []


def _extract_tweet_fields(tweet: dict) -> dict | None:
    """Normalize tweet fields from Apify response (format varies by actor)."""
    text = tweet.get("full_text") or tweet.get("text") or ""
    if not text:
        return None
    author = tweet.get("user", {}).get("screen_name") or tweet.get("author", {}).get("userName") or ""
    tweet_id = tweet.get("id_str") or str(tweet.get("id", ""))
    url = tweet.get("url") or (f"https://x.com/{author}/status/{tweet_id}" if author and tweet_id else "")
    date_str = (tweet.get("created_at") or tweet.get("createdAt") or "")[:19]
    likes = int(tweet.get("favorite_count") or tweet.get("likeCount") or 0)
    followers = int(tweet.get("user", {}).get("followers_count") or tweet.get("author", {}).get("followers") or 0)
    is_rt = bool(tweet.get("retweeted")) or text.startswith("RT @")
    is_reply = bool(tweet.get("in_reply_to_status_id") or tweet.get("inReplyToStatusId"))
    return {"text": text, "author": author, "url": url, "date": date_str,
            "likes": likes, "followers": followers, "is_rt": is_rt, "is_reply": is_reply}


def _classify_direction(text: str) -> str:
    text_lower = text.lower()
    bull = sum(1 for w in BULL_WORDS if w in text_lower)
    bear = sum(1 for w in BEAR_WORDS if w in text_lower)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "unknown"


def _extract_price_target(text: str) -> float | None:
    for pat in PRICE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def run_x_scraper(db=None):
    """Main entry point. LOG ONLY — does not insert predictions."""
    if not APIFY_API_TOKEN:
        print("[X-SCRAPER] APIFY_API_TOKEN not set — skipping")
        return

    batch = _get_batch()
    batch_num = (_batch_index - 1) % len(SEARCH_BATCHES) + 1
    print(f"[X-SCRAPER] Starting run — batch {batch_num}/{len(SEARCH_BATCHES)}: {batch}")

    tweets = _run_apify(batch, max_tweets=200)
    print(f"[X-SCRAPER] Fetched {len(tweets)} tweets")

    # Filter funnel counters
    c = {"fetched": len(tweets), "engagement": 0, "cashtag": 0, "spam": 0,
         "past": 0, "forward": 0, "question": 0, "qualifying": 0}
    seen_ids = set()
    predictions = []

    for tweet in tweets:
        t = _extract_tweet_fields(tweet)
        if not t:
            continue

        # Dedup
        if t["url"] in seen_ids:
            continue
        seen_ids.add(t["url"])

        text = t["text"]

        # Filter 1: Engagement
        if t["is_rt"] or t["is_reply"] or t["likes"] < MIN_LIKES or t["followers"] < MIN_FOLLOWERS:
            continue
        c["engagement"] += 1

        # Filter 2: Cashtags
        tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
        if not tickers or len(tickers) > MAX_CASHTAGS:
            continue
        c["cashtag"] += 1

        # Filter 3: Spam
        if any(p.search(text) for p in SPAM_PATTERNS):
            continue
        c["spam"] += 1

        # Filter 4: Past tense
        if any(p.search(text) for p in PAST_PATTERNS):
            continue
        c["past"] += 1

        # Filter 5: Forward-looking
        if not any(p.search(text) for p in FORWARD_PATTERNS):
            continue
        c["forward"] += 1

        # Filter 6: Question-only
        stripped = text.strip()
        if stripped.endswith("?") and QUESTION_STARTS.match(stripped):
            continue
        c["question"] += 1

        # ── Passed all filters → extract prediction ──────────────────────
        direction = _classify_direction(text)
        price_target = _extract_price_target(text)
        c["qualifying"] += 1

        for ticker in tickers:
            target_str = f", target=${price_target:.0f}" if price_target else ""
            predictions.append({
                "ticker": ticker, "direction": direction, "price_target": price_target,
                "author": t["author"], "url": t["url"], "date": t["date"],
                "likes": t["likes"], "followers": t["followers"],
            })

            print(f"[X-SCRAPER] PREDICTION FOUND:")
            print(f"  Ticker: ${ticker}")
            print(f"  Direction: {direction.upper()}")
            if price_target:
                print(f"  Price Target: ${price_target:.2f}")
            print(f"  Author: @{t['author']} ({t['followers']:,} followers)")
            print(f"  Likes: {t['likes']:,}")
            print(f"  Tweet: {text[:150]}")
            print(f"  URL: {t['url']}")

    # Summary
    unique_tickers = len(set(p["ticker"] for p in predictions))
    bull_count = sum(1 for p in predictions if p["direction"] == "bullish")
    bear_count = sum(1 for p in predictions if p["direction"] == "bearish")
    with_target = sum(1 for p in predictions if p["price_target"])

    print(f"[X-SCRAPER] RUN COMPLETE:")
    print(f"  Batch: {batch_num}/{len(SEARCH_BATCHES)}")
    print(f"  Tweets fetched: {c['fetched']}")
    print(f"  After engagement filter: {c['engagement']}")
    print(f"  After cashtag filter: {c['cashtag']}")
    print(f"  After spam filter: {c['spam']}")
    print(f"  After past-tense filter: {c['past']}")
    print(f"  After forward-looking filter: {c['forward']}")
    print(f"  After question filter: {c['question']}")
    print(f"  Qualifying predictions: {c['qualifying']}")
    print(f"  Direction: {bull_count} bullish, {bear_count} bearish")
    print(f"  Unique tickers: {unique_tickers}")
    print(f"  With price targets: {with_target}")
    print(f"  Total predictions logged: {len(predictions)}")
