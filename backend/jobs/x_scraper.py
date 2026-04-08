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

# Pillar 1: sector and broad-market ETFs accepted alongside individual stock tickers
ALLOWED_SECTOR_ETFS = {
    # SPDR sector ETFs
    "XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC",
    # Broad market
    "SPY", "QQQ", "IWM", "DIA",
    # Semis
    "SMH", "SOXX",
    # Biotech
    "XBI", "IBB",
    # Banks
    "KRE", "KBE",
    # Homebuilders
    "XHB", "ITB",
    # Oil/energy
    "XOP", "OIH",
    # Metals
    "GLD", "SLV",
    # Bonds
    "TLT", "IEF", "SHY",
}

# Words that count as "explicit rating" for the Pillar 2 / Requirement 3 check.
# Whole-word match, case-insensitive.
EXPLICIT_RATING_WORDS = {
    "buy", "sell", "bullish", "bearish", "long", "short",
    "outperform", "underperform", "strong buy", "strong sell",
    "overweight", "underweight",
}
_EXPLICIT_RATING_RE = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in EXPLICIT_RATING_WORDS) + r')\b',
    re.IGNORECASE,
)

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

# ── Haiku AI classification ──────────────────────────────────────────────────

HAIKU_SYSTEM = """You are a strict classifier evaluating tweets for stock predictions on Eidolum, a financial accountability platform. Eidolum holds forecasters to a high standard. Vague mentions, macro commentary, and self-promotional cashtags are NOT predictions and must be rejected.

A valid prediction requires ALL THREE of the following. If any are missing, return is_prediction=false.

REQUIREMENT 1 -- SPECIFIC TICKER OR SECTOR ETF
A literal stock cashtag ($AAPL), all-caps stock symbol (AAPL), or recognized sector/index ETF (XLK, SPY, QQQ, etc.) must appear in the tweet text. Not in a hashtag. Not inferred from context. Not from the author's bio.

REQUIREMENT 2 -- IDENTIFIABLE DIRECTION ABOUT THAT TICKER
The tweet must make a clear bullish or bearish claim ABOUT the specific ticker. The direction must be the subject of the tweet. Acceptable direction signals include:
  - Explicit ratings: Buy, Sell, Strong Buy, Outperform, Bullish, Bearish
  - Price targets: 'going to $250', 'PT $300', 'target $50'
  - Action language: 'going long', 'shorting', 'loading up', 'getting out', 'cutting'
  - Movement language: 'breaking out', 'topping here', 'rolling over', 'ripping', 'crashing'
  - Outcome language: 'will beat', 'will miss', 'is going much higher', 'has more downside'

REQUIREMENT 3 -- AT LEAST ONE OF: PRICE TARGET, TIMEFRAME, OR EXPLICIT RATING
To prevent vague vibes from counting, you must also identify at least one of:
  - A price target (any specific number)
  - A timeframe (by Q2, next month, this week, by year-end, into earnings, EOY)
  - An explicit rating word (Buy, Sell, Bullish, Bearish, Long, Short)

REJECT THESE PATTERNS (return is_prediction=false):

A) Macro/sector commentary with a tagged cashtag as a sign-off
   Example: 'Markets are forward looking, Iran war 90% priced in, Fed has tough job. $BMNR'
   Reason: BMNR is a sign-off, not the subject. Macro commentary about markets is not a prediction.

B) Vague vibes without target or timeframe
   Examples: '$NVDA looking strong here', 'Not loving the chart on $TSLA', '$AMD might be interesting'
   Reason: No target, no timeframe, no explicit rating. Pure vibes.

C) Self-promotional ticker tags
   Example: 'Just published our Q4 outlook! $FUNDX'
   Reason: Self-promotion, not a forecast.

D) Questions and hedges
   Examples: 'Anyone else loading up on $PLTR?', 'Will $TSLA rally? We will see'
   Reason: Questions and 'we will see' are not predictions.

E) Hypotheticals
   Example: '$XOM is where I would be if I had cash'
   Reason: Hypothetical, not a position or call.

F) Pure observations without direction
   Example: 'Watching $AAPL closely into earnings'
   Reason: Watching is not predicting.

G) News repetition without claim
   Example: '$BMNR reports earnings tomorrow'
   Reason: Stating a fact is not a prediction.

H) Macro/no-ticker tweets
   Examples: 'Stocks are cheap here', 'Tech is rolling over' (no ticker or ETF)
   Reason: No specific symbol.

ACCEPT THESE PATTERNS (return is_prediction=true):

  - 'Initiating long $AAPL, $250 PT, services growth thesis, 12 month horizon'
  - '$NVDA going to rip this earnings, target $200'
  - 'Selling all my $TSLA before Q1 deliveries, will disappoint'
  - 'Going long $XLE into year-end, energy is the trade for 2026'
  - 'Bearish $META, ad spend deceleration, target $400 by Q2'
  - '$BTC breaking out, $100k by EOY'
  - 'Short $SHOP here, $50 target, valuation extreme'

OUTPUT FORMAT (strict JSON, no extra text):
{
  "is_prediction": true | false,
  "ticker": "AAPL" | null,
  "direction": "bullish" | "bearish" | "neutral" | null,
  "target_price": 250.00 | null,
  "timeframe": "3 months" | "by Q2" | "EOY" | null,
  "confidence": "high" | "medium" | "low",
  "reason": "brief explanation, max 100 chars"
}

If is_prediction is false, set all other fields to null and explain WHY in reason.

DEFAULT TO REJECT. When in doubt, return is_prediction=false. Eidolum prefers fewer high-quality predictions over many low-quality ones."""

TIMEFRAME_MAP = {"today": 1, "this week": 7, "next week": 14, "this month": 30,
                 "short-term": 30, "medium-term": 90, "long-term": 365, "by end of year": None}


# ── Tweet ID → datetime (Twitter snowflake formula) ──────────────────────────

TWITTER_EPOCH_MS = 1288834974657  # 2010-11-04T01:42:54.657Z

def tweet_id_to_datetime(tweet_id) -> datetime | None:
    """Decode Twitter snowflake ID to UTC datetime. Returns None on failure."""
    try:
        tid = int(tweet_id)
        ms = (tid >> 22) + TWITTER_EPOCH_MS
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OSError):
        return None


def _get_tweet_body(tweet: dict) -> str:
    """Extract tweet text from Apify response, trying all known field names."""
    for field in ("full_text", "text", "fullText", "rawContent", "body"):
        val = tweet.get(field)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _ticker_in_text(ticker: str, text: str) -> bool:
    """Check if a ticker appears literally in tweet text."""
    if not ticker or not text:
        return False
    upper = text.upper()
    t = ticker.upper()
    # Check cashtag $AAPL
    if f"${t}" in upper:
        return True
    # Check standalone word: space/start + TICKER + space/end/punctuation
    pattern = rf'(?<![A-Z]){re.escape(t)}(?![A-Z])'
    return bool(re.search(pattern, upper))


def _is_allowed_etf(ticker: str) -> bool:
    """Pillar 1: ticker is a recognized sector or broad-market ETF."""
    return bool(ticker) and ticker.upper().lstrip("$") in ALLOWED_SECTOR_ETFS


def validate_haiku_result(result: dict, tweet_text: str) -> tuple[bool, str]:
    """Python-side safety net for the new strict Haiku prompt.

    Returns (is_valid, reason). Even if Haiku says is_prediction=true, this
    enforces the three requirements from the prompt independently.
    """
    if not result or not result.get("is_prediction"):
        return False, "haiku_rejected"
    if result.get("confidence") == "low":
        return False, "low_confidence"

    ticker = result.get("ticker")
    if not ticker:
        return False, "no_ticker"

    # Requirement 1: ticker must literally appear in tweet text
    if not _ticker_in_text(ticker, tweet_text):
        return False, "ticker_not_in_text"

    # Requirement 2: must have a direction
    direction = (result.get("direction") or "").lower()
    if direction not in ("bullish", "bearish", "neutral"):
        return False, "no_direction"

    # Requirement 3: at least one of price target, timeframe, or explicit rating word
    has_target = result.get("target_price") is not None
    has_timeframe = bool(result.get("timeframe"))
    has_explicit_rating = bool(_EXPLICIT_RATING_RE.search(tweet_text))
    if not (has_target or has_timeframe or has_explicit_rating):
        return False, "no_target_timeframe_or_rating"

    return True, "accepted"


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
                       author: str, body: str, tid: str, tweet_url: str, pred_date: datetime) -> bool:
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
        if prediction_exists_cross_scraper(ticker, forecaster.id, direction, pred_date, db):
            return False

        context = f"@{author}: {body[:300]}"
        from models import Prediction
        db.add(Prediction(
            forecaster_id=forecaster.id, ticker=ticker, direction=direction,
            prediction_date=pred_date,
            evaluation_date=pred_date + timedelta(days=timeframe_days),
            window_days=timeframe_days,
            target_price=target_price,
            source_url=tweet_url, archive_url=None,
            source_type="x", source_platform_id=source_id,
            context=context[:500], exact_quote=body[:500],
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
        "rejected_empty_body": 0,
    }
    # Strict-mode rejection breakdown (Phase 5)
    rejection_reasons: dict[str, int] = {}
    first_tweet_logged = False

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

            # Log first tweet structure for debugging
            if not first_tweet_logged and tweets:
                print(f"[X-SCRAPER-DEBUG] Raw tweet keys: {sorted(tweets[0].keys())}", flush=True)
                first_tweet_logged = True

            # Pre-filter + classify
            seen = set()
            for tweet in tweets:
                tid = str(tweet.get("id", ""))
                body = _get_tweet_body(tweet)
                if not tid or not body or tid in seen:
                    if tid and not body:
                        total_stats["rejected_empty_body"] += 1
                    continue
                seen.add(tid)

                is_rt = bool(tweet.get("isRetweet") or tweet.get("retweeted") or body.startswith("RT @"))
                tweet_url = tweet.get("url") or f"https://x.com/{handle}/status/{tid}"

                # Derive prediction_date from tweet ID (snowflake), not from Apify date field
                pred_date = tweet_id_to_datetime(tid)
                if not pred_date:
                    print(f"[X-SCRAPER-WARN] Could not decode tweet ID {tid} to datetime, using NOW", flush=True)
                    pred_date = datetime.utcnow()

                # Passive discovery
                _record_mentioned_handles(body, tracked_handles, db)

                reason = _prefilter_tweet(body, is_rt)
                if reason:
                    continue

                total_stats["prefilter_pass"] += 1
                total_stats["ai_sent"] += 1

                # Classify with Haiku
                result = _classify_with_haiku(body)
                time.sleep(0.02)  # rate limit Haiku calls

                # Phase 5: unified strict validation (matches the Haiku prompt's 3 requirements)
                is_valid, reject_reason = validate_haiku_result(result or {}, body)
                if not is_valid:
                    rejection_reasons[reject_reason] = rejection_reasons.get(reject_reason, 0) + 1
                    continue

                confidence = (result.get("confidence") or "low").lower()
                total_stats["ai_predictions"] += 1
                if confidence == "high":
                    total_stats["ai_high"] += 1
                else:
                    total_stats["ai_medium"] += 1

                ticker = (result.get("ticker") or "").upper().lstrip("$")
                direction = (result.get("direction") or "").lower()
                # We only insert directional predictions; "neutral" is rejected here
                if direction not in ("bullish", "bearish"):
                    rejection_reasons["neutral_or_no_direction"] = rejection_reasons.get("neutral_or_no_direction", 0) + 1
                    continue

                # Currency tickers are never predictions
                if ticker in CURRENCY_IGNORE:
                    rejection_reasons["currency_ticker"] = rejection_reasons.get("currency_ticker", 0) + 1
                    continue

                # Phase 1: ticker must be a recognised stock symbol form OR an allowed sector ETF.
                # find_forecaster + the rest of the pipeline accept any uppercase ticker, so the
                # gate here is just: if it's not in the explicit ETF allowlist, it must look like
                # a normal cashtag-style symbol (1-5 uppercase letters). Crypto and stocks both
                # satisfy that. The ETF allowlist gives sector ETFs an explicit pass even if
                # downstream sector lookup would otherwise treat them as "Other".
                if not (re.fullmatch(r"[A-Z]{1,5}", ticker) or _is_allowed_etf(ticker)):
                    rejection_reasons["invalid_ticker_format"] = rejection_reasons.get("invalid_ticker_format", 0) + 1
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
                        handle, body, tid, tweet_url, pred_date,
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
    rejected_total = sum(rejection_reasons.values())
    reasons_str = ", ".join(f"{k}={v}" for k, v in sorted(rejection_reasons.items(), key=lambda x: -x[1]))
    print(f"[X-SCRAPER] Done: {total_stats['inserted']} inserted, {rejected_total} rejected (rejection reasons: {reasons_str or 'none'})", flush=True)
    print(f"[X-SCRAPER] RUN COMPLETE:", flush=True)
    print(f"  Accounts: {total_stats['accounts_scraped']}/{len(accounts)}", flush=True)
    print(f"  Tweets: {total_stats['tweets_fetched']} fetched, {total_stats['prefilter_pass']} passed pre-filter, {total_stats['rejected_empty_body']} empty-body", flush=True)
    print(f"  Haiku: {total_stats['ai_sent']} sent, {total_stats['ai_predictions']} accepted ({total_stats['ai_high']} high, {total_stats['ai_medium']} medium)", flush=True)
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
