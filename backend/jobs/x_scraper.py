"""
X/Twitter Stock Prediction Scraper for Eidolum -- Tracked Accounts Model

Scrapes tweets from a curated list of ~25 high-signal financial accounts
stored in the tracked_x_accounts table. Uses Claude Haiku to classify
each tweet as a prediction (or not).

Apify actor: apidojo~tweet-scraper (Twitter User Scraper mode)
  Cost: ~$0.40 per 1000 tweets fetched
  Per run: ~25 accounts x 20 tweets = 500 tweets = ~$0.20/run
  4 runs/day = ~$0.80/day = ~$24/month (within $29 Starter plan)

Schedule: every 6 hours (4 runs/day).
Requires: APIFY_API_TOKEN, ANTHROPIC_API_KEY env vars.
"""
import os
import re
import time
import json
import httpx
from datetime import datetime, timedelta, timezone
from sqlalchemy import text as sql_text

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
APIFY_API = "https://api.apify.com/v2"
APIFY_ACTOR = "apidojo~tweet-scraper"

TWEETS_PER_ACCOUNT = 20
CURRENCY_IGNORE = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF", "CNY", "HKD", "SGD"}

# ── Spam pre-filter (cheap, applied before AI) ──────────────────────────────
SPAM_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'join\s+(my|our)\s+(discord|telegram|group|channel)',
    r'free\s+signals?', r'DM\s+(me|for)', r'link\s+in\s+bio',
    r'subscribe\s+(to|for|now)', r'alert\s+service',
    r'paid\s+(group|channel|membership)', r'sign\s+up',
    r'promo\s+code', r'discord\.gg', r't\.me/', r'bit\.ly/',
    r'use\s+code\b', r'limited\s+spots', r'join\s+now',
]]

TICKER_MENTION_RE = re.compile(r'\$[A-Z]{1,5}\b|(?<!\w)[A-Z]{2,5}(?!\w)')

# ── Haiku AI classification (reused from original) ──────────────────────────

HAIKU_SYSTEM = """You analyze financial tweets to extract stock/crypto predictions.
Respond ONLY with JSON. No explanation.

A prediction must be FORWARD-LOOKING -- the person believes a stock will go up or down.

VALID predictions:
- "$AAPL going to 200" -> prediction
- "NVDA is a buy here" -> prediction
- "shorting TSLA, overvalued" -> prediction (bearish)
- "loading calls on META" -> prediction (bullish)
- "puts on AMZN, this dumps to 150" -> prediction (bearish, target 150)
- "accumulating GOOGL under 170" -> prediction (bullish)

NOT predictions (reject these):
- "I sold AAPL at 190" -> past tense, not a prediction
- "took profit on NVDA" -> past action
- "TSLA earnings were great" -> commentary, no direction
- "what do you think about MSFT?" -> question
- "I bought AAPL last week" -> past action
- Retweets, news summaries, questions, watchlists

Response format:
{"is_prediction": true, "ticker": "AAPL", "direction": "bullish", "target_price": null, "confidence": "high", "timeframe": "90d", "reasoning": "5 words max"}

If multiple tickers with different directions, pick the PRIMARY one.
If not a prediction: {"is_prediction": false}"""

TIMEFRAME_MAP = {"today": 1, "this week": 7, "next week": 14, "this month": 30,
                 "short-term": 30, "medium-term": 90, "long-term": 365, "by end of year": None}


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
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content)
    except Exception:
        return None


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


def _parse_ai_timeframe(tf_str: str) -> int:
    if not tf_str:
        return 90
    tf = tf_str.strip().lower()
    m = re.match(r'^(\d+)d$', tf)
    if m:
        return int(m.group(1))
    for name, days in TIMEFRAME_MAP.items():
        if name in tf:
            if days is None:
                now = datetime.now(timezone.utc)
                return max((datetime(now.year, 12, 31, tzinfo=timezone.utc) - now).days, 1)
            return days
    return 90


def _extract_cashtags(text: str) -> list[str]:
    tags = re.findall(r'\$([A-Z]{1,5})\b', text)
    return [t for t in tags if t not in CURRENCY_IGNORE]


def _prefilter_tweet(text: str, is_rt: bool) -> str | None:
    """Quick pre-filter before sending to AI. Returns rejection reason or None if OK."""
    if is_rt:
        return "retweet"
    if len(text.strip()) < 15:
        return "too_short"
    if any(p.search(text) for p in SPAM_PATTERNS):
        return "spam"
    if not TICKER_MENTION_RE.search(text):
        return "no_ticker_ref"
    cashtags = _extract_cashtags(text)
    if len(cashtags) > 5:
        return "too_many_tickers"
    return None


# ── Apify: fetch tweets for a single user ────────────────────────────────────

def _fetch_user_tweets(handle: str, max_items: int = TWEETS_PER_ACCOUNT) -> list:
    """Fetch recent tweets for a single X handle via Apify. Returns list of tweet dicts."""
    try:
        payload = {
            "twitterHandles": [handle],
            "maxItems": max_items,
            "sort": "Latest",
        }

        r = httpx.post(
            f"{APIFY_API}/acts/{APIFY_ACTOR}/runs",
            params={"token": APIFY_API_TOKEN},
            json=payload,
            timeout=30,
        )
        if r.status_code != 201:
            print(f"[X-SCRAPER] Apify start failed for @{handle}: HTTP {r.status_code}", flush=True)
            return []

        run_id = r.json().get("data", {}).get("id")
        if not run_id:
            return []

        # Poll for completion (max 90s)
        dataset_id = None
        for _ in range(18):  # 18 x 5s = 90s max
            time.sleep(5)
            sr = httpx.get(f"{APIFY_API}/actor-runs/{run_id}", params={"token": APIFY_API_TOKEN}, timeout=15)
            data = sr.json().get("data", {})
            status = data.get("status", "")
            if status == "SUCCEEDED":
                dataset_id = data.get("defaultDatasetId")
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"[X-SCRAPER] Apify run for @{handle}: {status}", flush=True)
                return []

        if not dataset_id:
            print(f"[X-SCRAPER] Apify timeout for @{handle}", flush=True)
            return []

        dr = httpx.get(f"{APIFY_API}/datasets/{dataset_id}/items",
                       params={"token": APIFY_API_TOKEN, "format": "json"}, timeout=60)
        items = dr.json() if dr.status_code == 200 else []
        return items if isinstance(items, list) else []

    except Exception as e:
        print(f"[X-SCRAPER] Apify error for @{handle}: {e}", flush=True)
        return []


# ── Insert prediction into database ──────────────────────────────────────────

def _insert_prediction(db, ticker: str, direction: str, target_price, timeframe_days: int,
                       author: str, text: str, tid: str, tweet_url: str, created: str) -> bool:
    """Insert a single prediction. Returns True on success."""
    try:
        source_id = f"x_{tid}_{ticker}"
        if db.execute(sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
                      {"sid": source_id}).first():
            return False

        from jobs.news_scraper import find_forecaster
        forecaster = find_forecaster(author, db)
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


# ── Passive discovery: record mentioned @handles ─────────────────────────────

def _record_mentioned_handles(text: str, tracked_handles: set, db):
    """Find @handles in tweet text and upsert into suggested_x_accounts."""
    mentions = re.findall(r'@([A-Za-z0-9_]{1,15})', text)
    for handle in mentions:
        if handle.lower() in tracked_handles:
            continue
        try:
            db.execute(sql_text("""
                INSERT INTO suggested_x_accounts (handle, mention_count, first_seen_at, last_seen_at)
                VALUES (:h, 1, NOW(), NOW())
                ON CONFLICT (handle) DO UPDATE
                SET mention_count = suggested_x_accounts.mention_count + 1,
                    last_seen_at = NOW()
                WHERE suggested_x_accounts.dismissed = FALSE
            """), {"h": handle})
        except Exception:
            pass


# ── Main entry point ─────────────────────────────────────────────────────────

def run_x_scraper(db=None):
    """Main entry point. Scrapes tracked X accounts and classifies tweets with Haiku."""
    print("[X-SCRAPER] run_x_scraper() called", flush=True)

    if not APIFY_API_TOKEN:
        print("[X-SCRAPER] APIFY_API_TOKEN not set, skipping", flush=True)
        return
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY in ("placeholder", "sk-ant-placeholder"):
        print("[X-SCRAPER] FATAL: ANTHROPIC_API_KEY not set. Cannot run without AI classifier.", flush=True)
        return

    # Seed accounts if table is empty
    try:
        from jobs.seed_x_accounts import seed_tracked_x_accounts
        seed_tracked_x_accounts(db)
    except Exception as e:
        print(f"[X-SCRAPER] Seed error: {e}", flush=True)

    # Load active accounts
    rows = db.execute(sql_text(
        "SELECT id, handle FROM tracked_x_accounts WHERE active = TRUE ORDER BY last_scraped_at NULLS FIRST"
    )).fetchall()

    if not rows:
        print("[X-SCRAPER] No active tracked accounts found", flush=True)
        return

    accounts = [(r[0], r[1]) for r in rows]
    tracked_handles = {h.lower() for _, h in accounts}
    print(f"[X-SCRAPER] Loaded {len(accounts)} active accounts", flush=True)

    total_stats = {
        "accounts_scraped": 0, "tweets_fetched": 0, "prefilter_pass": 0,
        "ai_sent": 0, "ai_predictions": 0, "ai_high": 0, "ai_medium": 0,
        "inserted": 0, "dupes": 0, "errors": 0,
    }

    for account_id, handle in accounts:
        try:
            account_tweets = 0
            account_preds = 0

            print(f"[X-SCRAPER] Scraping @{handle}...", flush=True)
            tweets = _fetch_user_tweets(handle)
            account_tweets = len(tweets)
            total_stats["tweets_fetched"] += account_tweets

            if not tweets:
                print(f"[X-SCRAPER] @{handle}: 0 tweets returned", flush=True)
                _update_account_stats(db, account_id, 0, 0)
                time.sleep(2)
                continue

            # Pre-filter + classify
            seen = set()
            for tweet in tweets:
                tid = str(tweet.get("id", ""))
                text = tweet.get("text") or tweet.get("full_text") or ""
                if not tid or not text or tid in seen:
                    continue
                seen.add(tid)

                author_obj = tweet.get("author") or {}
                user_obj = tweet.get("user") or {}
                is_rt = bool(tweet.get("isRetweet") or tweet.get("retweeted") or text.startswith("RT @"))
                tweet_url = tweet.get("url") or f"https://x.com/{handle}/status/{tid}"
                created = (tweet.get("createdAt") or tweet.get("created_at") or "")[:19]

                # Passive discovery
                _record_mentioned_handles(text, tracked_handles, db)

                reason = _prefilter_tweet(text, is_rt)
                if reason:
                    continue

                total_stats["prefilter_pass"] += 1
                total_stats["ai_sent"] += 1

                # Classify with Haiku
                result = _classify_with_haiku(text)
                time.sleep(0.02)  # rate limit Haiku calls

                if not result or not result.get("is_prediction"):
                    continue

                confidence = result.get("confidence", "low")
                if confidence not in ("high", "medium"):
                    continue

                total_stats["ai_predictions"] += 1
                if confidence == "high":
                    total_stats["ai_high"] += 1
                else:
                    total_stats["ai_medium"] += 1

                ticker = (result.get("ticker") or "").upper()
                direction = result.get("direction", "").lower()
                if direction not in ("bullish", "bearish"):
                    continue

                tickers = _extract_cashtags(text)
                if not ticker and tickers:
                    ticker = tickers[0]
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

                if db:
                    ok = _insert_prediction(
                        db, ticker, direction, target_price, tf_days,
                        handle, text, tid, tweet_url, created,
                    )
                    if ok:
                        total_stats["inserted"] += 1
                        account_preds += 1
                    else:
                        total_stats["dupes"] += 1

            _update_account_stats(db, account_id, account_tweets, account_preds)
            total_stats["accounts_scraped"] += 1

            if account_preds > 0:
                print(f"[X-SCRAPER] @{handle}: {account_tweets} tweets, {account_preds} predictions inserted", flush=True)

        except Exception as e:
            total_stats["errors"] += 1
            print(f"[X-SCRAPER] Error scraping @{handle}: {e}", flush=True)

        time.sleep(2)  # rate limit between accounts

    # Commit all inserts
    if db and total_stats["inserted"] > 0:
        try:
            db.commit()
        except Exception as e:
            print(f"[X-SCRAPER] Commit error: {e}", flush=True)
            db.rollback()

    # Summary
    print(f"[X-SCRAPER] RUN COMPLETE:", flush=True)
    print(f"  Accounts: {total_stats['accounts_scraped']}/{len(accounts)}", flush=True)
    print(f"  Tweets: {total_stats['tweets_fetched']} fetched, {total_stats['prefilter_pass']} passed pre-filter", flush=True)
    print(f"  Haiku: {total_stats['ai_sent']} sent, {total_stats['ai_predictions']} predictions ({total_stats['ai_high']} high, {total_stats['ai_medium']} medium)", flush=True)
    print(f"  INSERTED: {total_stats['inserted']} | Dupes: {total_stats['dupes']} | Errors: {total_stats['errors']}", flush=True)
    est_apify = total_stats['tweets_fetched'] * 0.40 / 1000
    est_haiku = total_stats['ai_sent'] * 220 * 0.80 / 1_000_000
    print(f"  Est cost: Apify ~${est_apify:.2f}, Haiku ~${est_haiku:.3f}", flush=True)


def _update_account_stats(db, account_id: int, tweets_found: int, preds_extracted: int):
    """Update tracked account stats after scraping."""
    try:
        db.execute(sql_text("""
            UPDATE tracked_x_accounts
            SET last_scraped_at = NOW(),
                last_scrape_tweets_found = :tweets,
                last_scrape_predictions_extracted = :preds,
                total_tweets_scraped = COALESCE(total_tweets_scraped, 0) + :tweets,
                total_predictions_extracted = COALESCE(total_predictions_extracted, 0) + :preds
            WHERE id = :id
        """), {"tweets": tweets_found, "preds": preds_extracted, "id": account_id})
        db.commit()
    except Exception:
        pass
