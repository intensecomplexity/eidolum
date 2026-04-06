"""
X/Twitter Stock Prediction Scraper for Eidolum

Uses Apify Twitter scraper to find forward-looking stock predictions on X.
Two extraction modes:
  1. Claude Haiku AI classification (if ANTHROPIC_API_KEY is set)
  2. Regex-based extraction (fallback)

Schedule: every 6 hours (4 runs/day).
Requires: APIFY_API_TOKEN env var. Optional: ANTHROPIC_API_KEY for AI mode.
"""
import os
import re
import time
import json
import httpx
from datetime import datetime, timedelta, timezone

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
APIFY_API = "https://api.apify.com/v2"
APIFY_ACTOR = "apidojo~tweet-scraper"

BATCH_INDEX_FILE = "/tmp/x_scraper_batch_index.txt"

# ── Search batches with Twitter Advanced Search filters ──────────────────────
SEARCH_BATCHES = [
    [
        '"price target" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"PT $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"target $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"my target" min_faves:10 lang:en -filter:replies -filter:retweets',
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
    [
        '"bull case" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"bear case" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"price prediction" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"will hit $" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
    [
        '"buy rating" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"sell rating" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"upgrade" "$" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"downgrade" "$" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
    [
        '"my target" stock min_faves:10 lang:en -filter:replies -filter:retweets',
        '"will reach $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"going to $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"path to $" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
    [
        '"overweight" "$" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"underweight" "$" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"outperform" "$" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"underperform" "$" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
    [
        '"accumulate $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"adding $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"initiated coverage" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"raises target" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
    [
        '"support at $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"resistance at $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"upside to $" min_faves:10 lang:en -filter:replies -filter:retweets',
        '"fair value" "$" min_faves:10 lang:en -filter:replies -filter:retweets',
    ],
]

MIN_FOLLOWERS = 1000
MIN_LIKES_DEFAULT = 10
MIN_LIKES_HIGH_FOLLOWERS = 5  # Lower threshold for 10K+ follower accounts
MAX_CASHTAGS = 5
CURRENCY_IGNORE = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF", "CNY", "HKD", "SGD"}

# ── Cheap pre-filters (applied before AI) ────────────────────────────────────
SPAM_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'join\s+(my|our)\s+(discord|telegram|group|channel)',
    r'free\s+signals?', r'DM\s+(me|for)', r'link\s+in\s+bio',
    r'subscribe\s+(to|for|now)', r'alert\s+service',
    r'paid\s+(group|channel|membership)', r'sign\s+up',
    r'promo\s+code', r'discord\.gg', r't\.me/', r'bit\.ly/',
    r'use\s+code\b', r'limited\s+spots', r'join\s+now',
]]

# Regex to detect ANY potential ticker reference (cheap pre-filter for AI)
TICKER_MENTION_RE = re.compile(r'\$[A-Z]{1,5}\b|(?<!\w)[A-Z]{2,5}(?!\w)')

# ── Regex fallback patterns (used when AI is unavailable) ────────────────────
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

TIMEFRAME_MAP = {"today": 1, "this week": 7, "next week": 14, "this month": 30,
                 "short-term": 30, "medium-term": 90, "long-term": 365, "by end of year": None}

# ── Haiku AI classification ──────────────────────────────────────────────────

HAIKU_SYSTEM = """You analyze financial tweets to extract stock/crypto predictions.
Respond ONLY with JSON. No explanation.

A prediction must be FORWARD-LOOKING — the person believes a stock will go up or down.

VALID predictions:
- "$AAPL going to 200" → prediction
- "NVDA is a buy here" → prediction
- "shorting TSLA, overvalued" → prediction
- "loading calls on META" → prediction (bullish)
- "puts on AMZN, this dumps to 150" → prediction (bearish, target 150)
- "accumulating GOOGL under 170" → prediction (bullish)

NOT predictions (reject these):
- "I sold AAPL at 190" → past tense, not a prediction
- "took profit on NVDA" → past action
- "TSLA earnings were great" → commentary, no direction
- "what do you think about MSFT?" → question
- "I bought AAPL last week" → past action
- Retweets, news summaries, questions, watchlists

Response format:
{"is_prediction": true, "ticker": "AAPL", "direction": "bullish", "target_price": null, "confidence": "high", "timeframe": "90d", "reasoning": "5 words max"}

If multiple tickers with different directions, pick the PRIMARY one.
If not a prediction: {"is_prediction": false}"""


def _classify_with_haiku(tweet_text: str) -> dict | None:
    """Call Claude Haiku to classify a single tweet. Returns parsed dict or None."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY in ("placeholder", "sk-ant-placeholder"):
        return None
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "system": HAIKU_SYSTEM,
                "messages": [{"role": "user", "content": tweet_text[:500]}],
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        content = r.json().get("content", [{}])[0].get("text", "")
        # Parse JSON from response (handle markdown code blocks)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content)
    except Exception:
        return None


def _classify_batch_with_haiku(tweets: list[dict]) -> list[dict | None]:
    """Classify a batch of tweets with Haiku. Returns list of results (None on failure)."""
    results = []
    for tw in tweets:
        result = _classify_with_haiku(tw["text"])
        results.append(result)
        time.sleep(0.02)  # ~50 req/sec safe rate
    return results


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_tweet_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.utcnow()
    s = date_str.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%a %b %d %H:%M:%S +0000 %Y",
        "%a %b %d %H:%M:%S %Y",
        "%a %b %d %H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


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
    try:
        payload = {
            "searchTerms": search_terms,
            "maxItems": max_per_query * len(search_terms),
            "sort": "Latest",
        }
        import json as _json
        print(f"[X-SCRAPER] Apify payload: {_json.dumps(payload)}", flush=True)

        r = httpx.post(
            f"{APIFY_API}/acts/{APIFY_ACTOR}/runs",
            params={"token": APIFY_API_TOKEN},
            json=payload,
            timeout=30,
        )
        if r.status_code != 201:
            print(f"[X-SCRAPER] Apify start failed: HTTP {r.status_code}", flush=True)
            return []

        run_id = r.json().get("data", {}).get("id")
        if not run_id:
            return []
        print(f"[X-SCRAPER] Apify run {run_id} started, polling...", flush=True)

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
                print(f"[X-SCRAPER] Apify run {status}", flush=True)
                return []

        if not dataset_id:
            print("[X-SCRAPER] Apify run timed out or no dataset", flush=True)
            return []

        dr = httpx.get(f"{APIFY_API}/datasets/{dataset_id}/items",
                       params={"token": APIFY_API_TOKEN, "format": "json"}, timeout=60)
        items = dr.json() if dr.status_code == 200 else []
        return items if isinstance(items, list) else []

    except Exception as e:
        print(f"[X-SCRAPER] Apify error: {e}", flush=True)
        return []


def _extract_cashtags(text: str) -> list[str]:
    tags = re.findall(r'\$([A-Z]{1,5})\b', text)
    return [t for t in tags if t not in CURRENCY_IGNORE]


def _classify_regex(text: str) -> str:
    lo = text.lower()
    b = sum(1 for w in BULL_WORDS if w in lo)
    r = sum(1 for w in BEAR_WORDS if w in lo)
    return "bullish" if b > r else "bearish" if r > b else "unknown"


def _price_target(text: str) -> float | None:
    for p in PRICE_PATS:
        m = p.search(text)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if 0.5 < val < 100000:
                    return val
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
    return 90  # Default 90 days for social media predictions


def _parse_ai_timeframe(tf_str: str) -> int:
    """Convert AI timeframe string like '30d', '90d', 'this week' to days."""
    if not tf_str:
        return 90
    tf = tf_str.strip().lower()
    # Try "Nd" format
    m = re.match(r'^(\d+)d$', tf)
    if m:
        return int(m.group(1))
    # Try named timeframes
    for name, days in TIMEFRAME_MAP.items():
        if name in tf:
            if days is None:
                now = datetime.now(timezone.utc)
                return max((datetime(now.year, 12, 31, tzinfo=timezone.utc) - now).days, 1)
            return days
    return 90


# ── Pre-filter tweets for AI processing ──────────────────────────────────────

def _prefilter_tweet(text: str, followers: int, likes: int, is_rt: bool) -> str | None:
    """Quick pre-filter before sending to AI. Returns rejection reason or None if OK."""
    if is_rt:
        return "retweet"
    if followers < MIN_FOLLOWERS:
        return "followers"
    min_likes = MIN_LIKES_HIGH_FOLLOWERS if followers >= 10000 else MIN_LIKES_DEFAULT
    if likes < min_likes:
        return "likes"
    if len(text.strip()) < 15:
        return "too_short"
    if any(p.search(text) for p in SPAM_PATTERNS):
        return "spam"
    # Must mention at least one potential ticker
    if not TICKER_MENTION_RE.search(text):
        return "no_ticker_ref"
    # Too many cashtags = watchlist spam
    cashtags = _extract_cashtags(text)
    if len(cashtags) > MAX_CASHTAGS:
        return "too_many_tickers"
    return None


# ── Regex fallback pipeline (original 7-layer filter) ────────────────────────

def _process_tweet_regex(text: str, tickers: list[str]) -> dict | None:
    """Original regex extraction. Returns prediction dict or None."""
    if any(p.search(text) for p in PAST_PATTERNS):
        return None
    if not any(p.search(text) for p in FORWARD_PATTERNS):
        return None
    s = text.strip()
    if s.endswith("?") and QUESTION_START.match(s) and not re.search(r'\b(target|PT|heading|expect)\b', s, re.I):
        return None
    if any(p.search(text) for p in NEWS_PATTERNS) and not any(p.search(text) for p in FORWARD_PATTERNS):
        return None

    direction = _classify_regex(text)
    if direction == "unknown":
        return None

    return {
        "direction": direction,
        "ticker": tickers[0] if tickers else None,
        "target_price": _price_target(text),
        "timeframe": _timeframe(text),
        "method": "regex",
    }


# ── Insert prediction into database ──────────────────────────────────────────

def _insert_prediction(db, ticker: str, direction: str, target_price, timeframe_days: int,
                       author: str, text: str, tid: str, tweet_url: str, created: str) -> bool:
    """Insert a single prediction. Returns True on success."""
    try:
        source_id = f"x_{tid}_{ticker}"
        from sqlalchemy import text as sql_text
        if db.execute(sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
                      {"sid": source_id}).first():
            return False  # Already exists

        display_name = author
        from jobs.news_scraper import find_forecaster
        forecaster = find_forecaster(display_name, db)
        if not forecaster:
            return False

        from jobs.prediction_validator import prediction_exists_cross_scraper
        pred_date = _parse_tweet_date(created)
        if prediction_exists_cross_scraper(ticker, forecaster.id, direction, pred_date, db):
            return False

        context = f"@{author}: {text[:300]}"
        from models import Prediction
        db.add(Prediction(
            forecaster_id=forecaster.id, ticker=ticker, direction=direction,
            prediction_date=pred_date,
            evaluation_date=pred_date + timedelta(days=timeframe_days),
            window_days=timeframe_days,
            target_price=target_price,
            source_url=tweet_url, archive_url=None,
            source_type="x", source_platform_id=source_id,
            context=context[:500], exact_quote=text[:500],
            outcome="pending", verified_by="x_scraper",
        ))
        return True
    except Exception:
        return False


# ── Main entry point ─────────────────────────────────────────────────────────

def run_x_scraper(db=None):
    """Main entry point. Finds predictions on X/Twitter and inserts into database."""
    print("[X-SCRAPER] run_x_scraper() called", flush=True)
    if not APIFY_API_TOKEN:
        print("[X-SCRAPER] APIFY_API_TOKEN not set — skipping", flush=True)
        return

    use_ai = bool(ANTHROPIC_API_KEY and ANTHROPIC_API_KEY not in ("placeholder", "sk-ant-placeholder"))
    print(f"[X-SCRAPER] Mode: {'AI (Haiku)' if use_ai else 'Regex fallback'}", flush=True)
    if not use_ai:
        print("[X-SCRAPER] Set ANTHROPIC_API_KEY in Railway for AI extraction", flush=True)

    batch_idx = _get_batch_index()
    batch = SEARCH_BATCHES[batch_idx]
    _save_batch_index(batch_idx)
    print(f"[X-SCRAPER] Starting — batch {batch_idx + 1}/{len(SEARCH_BATCHES)}", flush=True)

    tweets = _call_apify(batch, max_per_query=250)
    print(f"[X-SCRAPER] Fetched {len(tweets)} tweets", flush=True)

    if tweets:
        print(f"[X-SCRAPER] Sample tweet keys: {list(tweets[0].keys())[:15]}")

    stats = {"fetched": len(tweets), "prefilter_pass": 0, "ai_sent": 0,
             "ai_predictions": 0, "ai_high": 0, "ai_medium": 0, "ai_rejected": 0,
             "regex_pass": 0, "inserted": 0, "dupes": 0, "insert_errors": 0,
             "bullish": 0, "bearish": 0, "with_target": 0, "ai_tokens": 0}
    prefilter_reasons = {}
    seen = set()
    unique_tickers = set()

    # ── Phase 1: Parse and pre-filter all tweets ────────────────────────
    candidates = []
    for tweet in tweets:
        tid = str(tweet.get("id", ""))
        text = tweet.get("text") or tweet.get("full_text") or ""
        if not tid or not text or tid in seen:
            continue
        seen.add(tid)

        author_obj = tweet.get("author") or {}
        user_obj = tweet.get("user") or {}
        author = author_obj.get("userName") or user_obj.get("screen_name") or ""
        followers = int(author_obj.get("followers") or user_obj.get("followers_count") or 0)
        likes = int(tweet.get("likeCount") or tweet.get("favorite_count") or 0)
        is_rt = bool(tweet.get("isRetweet") or tweet.get("retweeted") or text.startswith("RT @"))
        tweet_url = tweet.get("url") or (f"https://x.com/{author}/status/{tid}" if author else "")
        created = (tweet.get("createdAt") or tweet.get("created_at") or "")[:19]

        reason = _prefilter_tweet(text, followers, likes, is_rt)
        if reason:
            prefilter_reasons[reason] = prefilter_reasons.get(reason, 0) + 1
            continue

        stats["prefilter_pass"] += 1
        tickers = _extract_cashtags(text)
        candidates.append({
            "tid": tid, "text": text, "author": author, "followers": followers,
            "likes": likes, "tweet_url": tweet_url, "created": created, "tickers": tickers,
        })

    print(f"[X-SCRAPER] Pre-filter: {stats['prefilter_pass']} pass, {sum(prefilter_reasons.values())} rejected", flush=True)
    for reason, count in sorted(prefilter_reasons.items(), key=lambda x: -x[1]):
        print(f"[X-SCRAPER]   {reason}: {count}", flush=True)

    # ── Phase 2: Classify tweets ────────────────────────────────────────
    predictions_to_insert = []

    if use_ai and candidates:
        print(f"[X-SCRAPER] Sending {len(candidates)} tweets to Haiku...", flush=True)
        stats["ai_sent"] = len(candidates)

        for i in range(0, len(candidates), 20):
            batch_tweets = candidates[i:i+20]
            results = _classify_batch_with_haiku(batch_tweets)

            for tw, result in zip(batch_tweets, results):
                if not result or not result.get("is_prediction"):
                    stats["ai_rejected"] += 1
                    continue

                confidence = result.get("confidence", "low")
                if confidence not in ("high", "medium"):
                    stats["ai_rejected"] += 1
                    continue

                stats["ai_predictions"] += 1
                if confidence == "high":
                    stats["ai_high"] += 1
                else:
                    stats["ai_medium"] += 1

                ticker = (result.get("ticker") or "").upper()
                direction = result.get("direction", "").lower()
                if direction not in ("bullish", "bearish"):
                    continue

                # Use AI ticker or fall back to cashtag extraction
                if not ticker and tw["tickers"]:
                    ticker = tw["tickers"][0]
                if not ticker or ticker in CURRENCY_IGNORE:
                    continue

                target_price = result.get("target_price")
                if target_price is not None:
                    try:
                        target_price = float(target_price)
                        if not (0.5 < target_price < 100000):
                            target_price = None
                    except (ValueError, TypeError):
                        target_price = None

                tf_days = _parse_ai_timeframe(result.get("timeframe", "90d"))

                predictions_to_insert.append({
                    "ticker": ticker, "direction": direction,
                    "target_price": target_price, "timeframe": tf_days,
                    "author": tw["author"], "text": tw["text"],
                    "tid": tw["tid"], "tweet_url": tw["tweet_url"],
                    "created": tw["created"],
                })

            if (i + 20) % 100 == 0 and i > 0:
                print(f"[X-SCRAPER] AI progress: {min(i+20, len(candidates))}/{len(candidates)}", flush=True)

    else:
        # Regex fallback
        for tw in candidates:
            tickers = tw["tickers"] if tw["tickers"] else _extract_cashtags(tw["text"])
            if not tickers:
                continue
            result = _process_tweet_regex(tw["text"], tickers)
            if not result:
                continue
            stats["regex_pass"] += 1
            predictions_to_insert.append({
                "ticker": result["ticker"], "direction": result["direction"],
                "target_price": result["target_price"], "timeframe": result["timeframe"],
                "author": tw["author"], "text": tw["text"],
                "tid": tw["tid"], "tweet_url": tw["tweet_url"],
                "created": tw["created"],
            })

    # ── Phase 3: Insert predictions ─────────────────────────────────────
    for pred in predictions_to_insert:
        direction = pred["direction"]
        if direction == "bullish":
            stats["bullish"] += 1
        else:
            stats["bearish"] += 1
        if pred["target_price"]:
            stats["with_target"] += 1
        unique_tickers.add(pred["ticker"])

        if stats["inserted"] + stats["dupes"] < 10:
            pt_str = f"${pred['target_price']:.0f}" if pred['target_price'] else "none"
            print(f"[X-SCRAPER] @{pred['author']} → {direction.upper()} ${pred['ticker']} PT={pt_str}", flush=True)

        if db:
            ok = _insert_prediction(
                db, pred["ticker"], direction, pred["target_price"], pred["timeframe"],
                pred["author"], pred["text"], pred["tid"], pred["tweet_url"], pred["created"],
            )
            if ok:
                stats["inserted"] += 1
            else:
                stats["dupes"] += 1

    # Commit all inserts
    if db and stats["inserted"] > 0:
        try:
            db.commit()
        except Exception as e:
            print(f"[X-SCRAPER] Commit error: {e}", flush=True)
            db.rollback()

    # ── Summary ─────────────────────────────────────────────────────────
    method = "AI" if use_ai else "Regex"
    print(f"[X-SCRAPER] RUN COMPLETE (batch {batch_idx+1}/{len(SEARCH_BATCHES)}, {method}):", flush=True)
    print(f"  Fetched: {stats['fetched']} → pre-filter: {stats['prefilter_pass']}", flush=True)
    if use_ai:
        print(f"  Haiku: {stats['ai_sent']} sent → {stats['ai_predictions']} predictions ({stats['ai_high']} high, {stats['ai_medium']} medium), {stats['ai_rejected']} rejected", flush=True)
    else:
        print(f"  Regex: {stats['regex_pass']} passed filters", flush=True)
    hit_rate = stats['inserted'] / stats['fetched'] * 100 if stats['fetched'] > 0 else 0
    print(f"  Qualifying: {len(predictions_to_insert)} ({stats['bullish']} bull, {stats['bearish']} bear) | With PT: {stats['with_target']}", flush=True)
    print(f"  INSERTED: {stats['inserted']} | Dupes: {stats['dupes']} | Unique tickers: {len(unique_tickers)}", flush=True)
    print(f"  Hit rate: {hit_rate:.1f}% | Est Apify cost: ${stats['fetched'] * 0.40 / 1000:.2f}", flush=True)
    if use_ai:
        est_haiku = stats['ai_sent'] * 220 * 0.80 / 1_000_000  # ~220 tokens avg, $0.80/MTok
        print(f"  Est Haiku cost: ~${est_haiku:.3f} ({stats['ai_sent']} calls)", flush=True)
