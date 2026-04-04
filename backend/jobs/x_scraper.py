"""
X/Twitter Stock Prediction Scraper for Eidolum — V1 (Log Only)

Uses Apify Twitter scraper to find forward-looking stock predictions on X.
Seven-layer filter pipeline rejects spam, past-tense brags, questions, and noise.
V1: Logs qualifying predictions. No database writes.

Schedule: every 8 hours (3 runs/day = ~$22/month on Apify Starter $29).
Requires: APIFY_API_TOKEN env var.
"""
import os
import re
import time
import json
import httpx
from datetime import datetime, timedelta, timezone

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "").strip()
APIFY_API = "https://api.apify.com/v2"
APIFY_ACTOR = "apidojo~tweet-scraper"

BATCH_INDEX_FILE = "/tmp/x_scraper_batch_index.txt"

# ── Search batches with Twitter Advanced Search filters ──────────────────────
# min_faves:10 filters at Twitter level (free, cuts 90% noise)
SEARCH_BATCHES = [
    [
        '"price target" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"PT $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"target $" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
    [
        '"buy $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"sell $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"long $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"short $" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
    [
        '"breakout $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"breakdown $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"heading to $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"downside to $" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
    [
        '"looking for $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"next stop $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"calls for $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"expecting $" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
]

MIN_FOLLOWERS = 1000
MAX_CASHTAGS = 3
CURRENCY_IGNORE = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD"}

# ── Compiled filter patterns ─────────────────────────────────────────────────
SPAM_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'join\s+(my|our)\s+(discord|telegram|group|channel)',
    r'free\s+signals?', r'DM\s+(me|for)', r'link\s+in\s+bio',
    r'subscribe\s+(to|for|now)', r'alert\s+service',
    r'paid\s+(group|channel|membership)', r'sign\s+up',
    r'promo\s+code', r'discord\.gg', r't\.me/', r'bit\.ly/',
    r'use\s+code\b', r'limited\s+spots', r'join\s+now',
]]

PAST_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'\bi\s+bought\b', r'\bi\s+sold\b', r'\btook\s+profit',
    r'\bclosed\s+(my\s+)?position', r'\bnailed\s+it\b', r'\bcalled\s+it\b',
    r'\bwas\s+right\b', r'\btold\s+you\b', r'\balready\s+in\b',
    r'\bexited\b', r'\bbanked\b', r'\blocked\s+in\s+profit',
    r'\bcashed\s+out\b', r'\btook\s+the\s+trade\b',
    r'\bentered\s+(at|around)\b', r'\bgot\s+in\s+at\b',
    r'\bmy\s+entry\s+was\b', r'\bup\s+\d+%\s+(on|from)\b',
    r'\bbooked\b', r'\bclosed\s+for\b', r'\bsold\s+(half|some|all)\b',
    r'\btrimmed\b', r'\btrade\s+recap\b', r'\brecap\b',
    r'\bi\s+made\b.*\$\d', r'\bprofit\s+secured\b', r'\bin\s+at\s+\$\d',
]]

FORWARD_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'\btarget\b', r'\bPT\s*\$', r'\bprice\s+target\b',
    r'\bheading\s+to\b', r'\bwill\s+(reach|hit|break|test)\b',
    r'\bexpecting\b', r'\bsetup\b', r'\bbreakout\b', r'\bbreakdown\b',
    r'\bgoing\s+to\s+\$?\d', r'\blooking\s+for\b', r'\bnext\s+stop\b',
    r'\bdownside\s+to\b', r'\bupside\s+to\b', r'\bsupport\s+at\b',
    r'\bresistance\s+at\b', r'\bcalls?\s+for\b',
    r'\bbuy\b', r'\bsell\b', r'\blong\b', r'\bshort\b',
    r'\bbullish\b', r'\bbearish\b', r'\baccumulate\b', r'\bavoid\b',
]]

NEWS_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'\breports\s+earnings\b', r'\bearnings\s+(call|report|release)\b',
    r'\bIPO\s+(date|priced)\b', r'\bjust\s+announced\b',
    r'\bbreaking\b.*\bnews\b', r'\bFDA\s+(approval|decision)\b',
]]

QUESTION_START = re.compile(r'^(will|should|would|could|do you think|is)\b', re.IGNORECASE)

BULL_WORDS = {
    "buy", "long", "calls", "bull", "bullish", "breakout", "upside",
    "moon", "ripping", "accumulate", "adding", "loading", "bounce",
    "undervalued", "cheap", "dip buy", "higher", "oversold",
}
BEAR_WORDS = {
    "sell", "short", "puts", "bear", "bearish", "breakdown", "downside",
    "drilling", "dump", "avoid", "cutting", "overvalued", "fade",
    "rejected", "lower", "top is in", "overbought",
}

PRICE_PATS = [re.compile(p, re.IGNORECASE) for p in [
    r'(?:target|PT|price\s+target)\s*\$?([\d,]+(?:\.\d{1,2})?)',
    r'\$[A-Z]{1,5}\s+(?:to|at|towards?)\s+\$?([\d,]+(?:\.\d{1,2})?)',
    r'(?:heading|going|path)\s+to\s+\$?([\d,]+(?:\.\d{1,2})?)',
    r'(?:downside|upside)\s+(?:to|target)\s+\$?([\d,]+(?:\.\d{1,2})?)',
    r'next\s+stop\s+\$?([\d,]+(?:\.\d{1,2})?)',
]]

TIMEFRAME_PATS = [
    (re.compile(r'\btoday\b', re.I), 1),
    (re.compile(r'\bthis\s+week\b|\bEOW\b', re.I), 7),
    (re.compile(r'\bnext\s+week\b|\bswing\b|\bshort[\s-]term\b', re.I), 14),
    (re.compile(r'\bthis\s+month\b|\bEOM\b', re.I), 30),
    (re.compile(r'\blong[\s-]term\b', re.I), 365),
    (re.compile(r'\b(by\s+(end\s+of\s+)?year|EOY)\b', re.I), None),
]


def _get_batch_index() -> int:
    try:
        with open(BATCH_INDEX_FILE) as f:
            return (int(f.read().strip()) + 1) % len(SEARCH_BATCHES)
    except Exception:
        return 0


def _save_batch_index(idx: int):
    try:
        with open(BATCH_INDEX_FILE, "w") as f:
            f.write(str(idx))
    except Exception:
        pass


def _call_apify(search_terms: list, max_per_query: int = 150) -> list:
    """Run Apify tweet scraper and return results."""
    try:
        r = httpx.post(
            f"{APIFY_API}/acts/{APIFY_ACTOR}/runs",
            params={"token": APIFY_API_TOKEN},
            json={
                "searchTerms": search_terms,
                "maxItems": max_per_query * len(search_terms),
                "sort": "Latest",
            },
            timeout=30,
        )
        if r.status_code != 201:
            print(f"[X-SCRAPER] Apify start failed: HTTP {r.status_code}")
            return []

        run_id = r.json().get("data", {}).get("id")
        if not run_id:
            return []
        print(f"[X-SCRAPER] Apify run {run_id} started, polling...")

        dataset_id = None
        for _ in range(30):
            time.sleep(10)
            sr = httpx.get(f"{APIFY_API}/actor-runs/{run_id}", params={"token": APIFY_API_TOKEN}, timeout=15)
            data = sr.json().get("data", {})
            status = data.get("status", "")
            if status == "SUCCEEDED":
                dataset_id = data.get("defaultDatasetId")
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"[X-SCRAPER] Apify run {status}")
                return []

        if not dataset_id:
            print("[X-SCRAPER] Apify run timed out or no dataset")
            return []

        dr = httpx.get(f"{APIFY_API}/datasets/{dataset_id}/items",
                       params={"token": APIFY_API_TOKEN, "format": "json"}, timeout=60)
        items = dr.json() if dr.status_code == 200 else []
        return items if isinstance(items, list) else []

    except Exception as e:
        print(f"[X-SCRAPER] Apify error: {e}")
        return []


def _extract_cashtags(text: str) -> list[str]:
    tags = re.findall(r'\$([A-Z]{1,5})\b', text)
    return [t for t in tags if t not in CURRENCY_IGNORE]


def _classify(text: str) -> str:
    lo = text.lower()
    b = sum(1 for w in BULL_WORDS if w in lo)
    r = sum(1 for w in BEAR_WORDS if w in lo)
    return "bullish" if b > r else "bearish" if r > b else "unknown"


def _price_target(text: str) -> float | None:
    for p in PRICE_PATS:
        m = p.search(text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def _timeframe(text: str) -> int:
    for pat, days in TIMEFRAME_PATS:
        if pat.search(text):
            if days is not None:
                return days
            now = datetime.now(timezone.utc)
            return max((datetime(now.year, 12, 31, tzinfo=timezone.utc) - now).days, 1)
    return 30


def run_x_scraper(db=None):
    """Main entry point. LOG ONLY."""
    if not APIFY_API_TOKEN:
        print("[X-SCRAPER] APIFY_API_TOKEN not set — skipping")
        return

    batch_idx = _get_batch_index()
    batch = SEARCH_BATCHES[batch_idx]
    _save_batch_index(batch_idx)
    print(f"[X-SCRAPER] Starting — batch {batch_idx + 1}/{len(SEARCH_BATCHES)}")

    tweets = _call_apify(batch, max_per_query=150)
    print(f"[X-SCRAPER] Fetched {len(tweets)} tweets")

    # Log sample structure on first run
    if tweets:
        print(f"[X-SCRAPER] Sample tweet keys: {list(tweets[0].keys())[:15]}")

    stats = {k: 0 for k in ["fetched", "dedup", "followers", "cashtag", "spam",
                              "past", "forward", "question", "news", "qualifying",
                              "bullish", "bearish", "unknown", "with_target"]}
    stats["fetched"] = len(tweets)
    seen = set()
    unique_tickers = set()

    for tweet in tweets:
        tid = str(tweet.get("id_str") or tweet.get("id", ""))
        text = tweet.get("full_text") or tweet.get("text") or ""
        if not tid or not text or tid in seen:
            continue
        seen.add(tid)
        stats["dedup"] += 1

        user = tweet.get("user", {})
        author = user.get("screen_name") or tweet.get("author", {}).get("userName", "")
        followers = int(user.get("followers_count") or tweet.get("author", {}).get("followers") or 0)
        likes = int(tweet.get("favorite_count") or tweet.get("likeCount") or 0)
        created = (tweet.get("created_at") or tweet.get("createdAt") or "")[:19]

        # F1: Followers
        if followers < MIN_FOLLOWERS:
            continue
        stats["followers"] += 1

        # F2: Cashtags
        tickers = _extract_cashtags(text)
        if not tickers or len(tickers) > MAX_CASHTAGS:
            continue
        stats["cashtag"] += 1

        # F3: Spam
        if any(p.search(text) for p in SPAM_PATTERNS):
            continue
        stats["spam"] += 1

        # F4: Past tense
        if any(p.search(text) for p in PAST_PATTERNS):
            continue
        stats["past"] += 1

        # F5: Forward-looking
        if not any(p.search(text) for p in FORWARD_PATTERNS):
            continue
        stats["forward"] += 1

        # F6: Question-only
        s = text.strip()
        if s.endswith("?") and QUESTION_START.match(s) and not re.search(r'\b(target|PT|heading|expect)\b', s, re.I):
            continue
        stats["question"] += 1

        # F7: News-only
        if any(p.search(text) for p in NEWS_PATTERNS) and not any(p.search(text) for p in FORWARD_PATTERNS):
            continue
        stats["news"] += 1

        # ── Passed all filters ───────────────────────────────────────────
        direction = _classify(text)
        pt = _price_target(text)
        tf = _timeframe(text)
        url = f"https://x.com/{author}/status/{tid}"

        stats["qualifying"] += 1
        if direction == "bullish": stats["bullish"] += 1
        elif direction == "bearish": stats["bearish"] += 1
        else: stats["unknown"] += 1
        if pt: stats["with_target"] += 1
        unique_tickers.update(tickers)

        pt_str = f"${pt:.2f}" if pt else "none"
        print(f"[X-SCRAPER] PREDICTION: @{author} ({followers:,} flw, {likes} likes) "
              f"→ {direction.upper()} {' '.join('$'+t for t in tickers)} "
              f"PT={pt_str} TF={tf}d")
        if stats["qualifying"] <= 15:
            print(f"  Tweet: {text[:180]}")
            print(f"  URL: {url}")

    print(f"[X-SCRAPER] RUN COMPLETE (batch {batch_idx+1}/{len(SEARCH_BATCHES)}):")
    print(f"  Fetched: {stats['fetched']} → dedup: {stats['dedup']} → followers: {stats['followers']}")
    print(f"  → cashtag: {stats['cashtag']} → spam: {stats['spam']} → past: {stats['past']}")
    print(f"  → forward: {stats['forward']} → question: {stats['question']} → news: {stats['news']}")
    print(f"  Qualifying: {stats['qualifying']} ({stats['bullish']} bull, {stats['bearish']} bear, {stats['unknown']} unk)")
    print(f"  Unique tickers: {len(unique_tickers)} | With PT: {stats['with_target']}")
    print(f"  Est. cost: ${stats['fetched'] * 0.40 / 1000:.2f}")
