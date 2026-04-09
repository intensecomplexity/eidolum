"""
X/Twitter Stock Prediction Scraper for Eidolum -- Tracked Accounts Model

Scrapes tweets from a curated list of ~25 high-signal financial accounts
stored in the tracked_x_accounts table. Classifies each tweet via Groq
(llama-3.3-70b-versatile by default).

Why Groq, not Haiku:
  Apr 8 2026 outage: the Anthropic billing account ran out of credit and
  every Haiku call returned HTTP 400 for 18 minutes, killing 377 tweets
  before detection. The X scraper is now off Anthropic billing for
  resilience and cost reasons. Haiku remains in use for OTHER pipelines
  (e.g. anywhere ANTHROPIC_API_KEY is consumed) — only the X scraper has
  migrated.

Apify actor: apidojo~tweet-scraper (Twitter User Scraper mode)
  Cost: ~$0.40 per 1000 tweets fetched
  Per run: ~25 accounts x 20 tweets = 500 tweets = ~$0.20/run
  4 runs/day = ~$0.80/day = ~$24/month (within $29 Starter plan)

Schedule: every 6 hours (4 runs/day).
Requires: APIFY_API_TOKEN, GROQ_API_KEY env vars.
ANTHROPIC_API_KEY is NO LONGER read by this scraper.
"""
import os
import re
import time
import json
import logging
import threading
from collections import deque
import httpx
from datetime import datetime, timedelta, timezone
from sqlalchemy import text as sql_text

log = logging.getLogger(__name__)

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "").strip()
APIFY_API = "https://api.apify.com/v2"
APIFY_ACTOR = "apidojo~tweet-scraper"
# Header-based auth keeps the token out of URL query strings, which httpx
# and urllib3 log at INFO level. Apify documents Bearer as a first-class
# auth method for the v2 API.
_APIFY_HEADERS = {"Authorization": f"Bearer {APIFY_API_TOKEN}"} if APIFY_API_TOKEN else {}

# ── Groq classifier config ──────────────────────────────────────────────────
# llama-3.3-70b-versatile is the eval-script winner from commit 2865f06.
# Free-tier limits (as of 2026-04): 30 RPM AND 12,000 TPM. Our HAIKU_SYSTEM
# prompt is ~3,600 tokens, so the binding constraint is TPM, not RPM:
#     12,000 TPM / (~3,600 in + ~200 out) ≈ 3.16 RPM ceiling
# We default GROQ_MAX_RPM to 3 to stay safely under TPM with headroom for
# the variable response size. Override with GROQ_MAX_RPM env var if you
# upgrade to Groq paid tier (which lifts the TPM cap dramatically).
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"
try:
    GROQ_MAX_RPM = max(1, int(os.getenv("GROQ_MAX_RPM", "3").strip() or "3"))
except ValueError:
    GROQ_MAX_RPM = 3
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class _GroqRateLimiter:
    """Sliding-window RPM limiter shared across the x_scraper process.

    The Groq free tier enforces both an RPM and a TPM ceiling. With a
    ~3,600-token system prompt, TPM (12,000) is the binding constraint —
    capping requests at ~3.2 RPM regardless of the documented 30 RPM RPM
    cap. Pacing the scraper at GROQ_MAX_RPM=3 keeps us under both.

    Implementation: a deque of monotonic timestamps. acquire() drops
    expired entries (>60s old), and if the window is already full it
    sleeps until the oldest entry rolls out.
    """

    def __init__(self, max_rpm: int):
        self.max_rpm = max_rpm
        self._times: "deque[float]" = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._times and now - self._times[0] >= 60.0:
                self._times.popleft()
            if len(self._times) >= self.max_rpm:
                wait = 60.0 - (now - self._times[0]) + 0.05
                if wait > 0:
                    # Release the lock while sleeping so other callers can
                    # at least observe the queue length. Re-acquire after.
                    self._lock.release()
                    try:
                        time.sleep(wait)
                    finally:
                        self._lock.acquire()
                    now = time.monotonic()
                    while self._times and now - self._times[0] >= 60.0:
                        self._times.popleft()
            self._times.append(now)


_groq_limiter = _GroqRateLimiter(GROQ_MAX_RPM)

TWEETS_PER_ACCOUNT = 20
CURRENCY_IGNORE = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF", "CNY", "HKD", "SGD"}

# Skip tweets older than this. Apify's tweet-scraper actor occasionally
# returns tweets from as far back as 2010-2011 for high-signal handles
# (it returns "recent" tweets but has no strict date filter), which wastes
# Haiku quota classifying 15-year-old content. 30 days is tight enough to
# keep predictions actionable but loose enough to survive a 2-4 day scraper
# outage without missing anything.
MAX_TWEET_AGE_DAYS = 30

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

# ── News-firehose blocklist ──────────────────────────────────────────────────
#
# Handles that post breaking-news headlines, not predictions. These accounts
# trigger TICKER_MENTION_RE via all-caps country/org names (TRUMP, IRAN,
# NATO, NYSE) and reach Haiku as false positives. Apr 9 forensics showed
# @DeItaone alone drove ~80% of the scraper's Anthropic spend by posting
# ~2,400 geopolitical headlines in 30 hours, every one correctly rejected
# by Haiku as "no asset" but each rejection still costing ~$0.0046.
#
# Blocked at the per-handle pre-fetch layer in run_x_scraper(), so blocked
# accounts never hit Apify or Haiku. SEED_ACCOUNTS in seed_x_accounts.py is
# the canonical list — DeItaone and zerohedge have been removed there too,
# so the seeder won't re-activate them. This Python set is belt-and-braces
# defense in case anyone re-adds them via the admin UI or a future seed.
BLOCKED_HANDLES = frozenset({
    'deitaone',         # Bloomberg-style breaking news firehose (#1 cost driver)
    'zerohedge',        # Same news-firehose pattern as deitaone
    'firstsquawk',      # Real-time market news aggregator
    'livesquawk',       # Real-time market news aggregator
    'breaking911',      # Breaking news
    'disclosetv',       # General news
    'spectatorindex',   # World news aggregator
    'insiderpaper',     # News aggregator
    'reutersbiz',       # Reuters business news feed
    'reuters',          # Reuters main
    'bloomberg',        # Bloomberg main
    'cnbcnow',          # CNBC breaking news
    'financialjuice',   # Market news feed
    'walterbloomberg',  # Headline mirror (alias of DeItaone)
})


def _is_blocked_handle(handle: str) -> bool:
    """Return True if the handle should be skipped entirely (news firehose)."""
    if not handle:
        return False
    return handle.lstrip('@').strip().lower() in BLOCKED_HANDLES


# ── Haiku AI classification ──────────────────────────────────────────────────

HAIKU_SYSTEM = """You are a strict classifier evaluating tweets for stock predictions on Eidolum, a financial accountability platform. Eidolum holds forecasters to a high standard. Vague mentions, macro commentary, and self-promotional cashtags are NOT predictions and must be rejected.

A valid prediction requires ALL THREE of the following. If any are missing, return is_prediction=false.

REQUIREMENT 1 -- SPECIFIC TICKER, SECTOR ETF, OR RECOGNIZED SECTOR PHRASE
ONE of the following must appear LITERALLY in the tweet text:
  (a) A stock cashtag ($AAPL), all-caps stock symbol (AAPL), or recognized
      sector/index ETF (XLK, SPY, QQQ, XLE, XLF, XLV, XLY, XLP, XLI, XLU,
      XLB, XLRE, XLC, IWM, DIA, SMH, SOXX). Treat as prediction_type
      "price_target".
  (b) A recognized SECTOR PHRASE: "tech", "semis", "semiconductors", "chips",
      "financials", "banks", "regional banks", "energy", "oil", "healthcare",
      "pharma", "biotech", "consumer", "consumer discretionary", "retail",
      "consumer staples", "staples", "industrials", "utilities", "real estate",
      "reits", "homebuilders", "housing", "materials", "communication services",
      "media". Treat as prediction_type "sector_call" and put the phrase
      EXACTLY as it appears in the tweet (lowercase) in the "sector" field.
Not in a hashtag. Not inferred from context. Not from the author's bio.

REQUIREMENT 2 -- IDENTIFIABLE DIRECTION ABOUT THAT TICKER
The tweet must make a clear bullish or bearish claim ABOUT the specific ticker. The direction must be the subject of the tweet. Acceptable direction signals include:
  - Explicit ratings: Buy, Sell, Strong Buy, Outperform, Bullish, Bearish
  - Price targets: 'going to $250', 'PT $300', 'target $50'
  - Action language: 'going long', 'shorting', 'loading up', 'getting out', 'cutting'
  - Movement language: 'breaking out', 'topping here', 'rolling over', 'ripping', 'crashing'
  - Outcome language: 'will beat', 'will miss', 'is going much higher', 'has more downside'

REQUIREMENT 3 -- CONCRETE DIRECTIONAL CLAIM
The direction must be specific and actionable, not a vague vibe. At least ONE of the following must be present:
  - A price target (any specific number)
  - A timeframe (by Q2, next month, into earnings, EOY)
  - An explicit rating word (Buy, Sell, Bullish, Bearish, Long, Short, Outperform, Underperform)
  - A strong directional action verb: breaking out, topping, rolling over, ripping, crashing, crushed, pumping, dumping, getting destroyed, headed higher, headed lower, moon, tank, collapse, rally, squeeze, breakout, breakdown, reversal, capitulation
  - A position disclosure or trade action: "new position", "initiating long/short", "added to", "cut my stake", "exited", "bought", "sold", "went long/short", "loaded up", "reduced", "increased stake", "took profit", "13F disclosure", "Scion Q[1-4]"

Vague vibes like "looking strong", "might be interesting", "watching closely", "not loving", "feels like", "thinking about" are still REJECTED.

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

H) Macro/no-symbol tweets
   Examples: 'Stocks are cheap here', 'The Fed will cut rates next month'
   Reason: No specific symbol AND no recognized sector phrase.
   NOTE: 'Tech is rolling over by Q2' is now a SECTOR CALL (not rejected),
   because "tech" is a recognized sector phrase and "by Q2" is a timeframe.

ACCEPT THESE PATTERNS (return is_prediction=true):

  - 'Initiating long $AAPL, $250 PT, services growth thesis, 12 month horizon'
  - '$NVDA going to rip this earnings, target $200'
  - 'Selling all my $TSLA before Q1 deliveries, will disappoint'
  - 'Going long $XLE into year-end, energy is the trade for 2026'
  - 'Bearish $META, ad spend deceleration, target $400 by Q2'
  - '$BTC breaking out, $100k by EOY'
  - 'Short $SHOP here, $50 target, valuation extreme'
  - 'New position $PARA, 900K shares' (Burry-style disclosure = bullish signal, even without a price target)
  - 'Semis are going to rip in Q2 2026' -> sector_call, sector="semis", bullish, timeframe="Q2 2026"
  - 'Bearish on regional banks for the next 6 months' -> sector_call, sector="regional banks", bearish, timeframe="6 months"
  - 'Homebuilders look cooked into year-end' -> sector_call, sector="homebuilders", bearish, timeframe="year-end"

POSITION DISCLOSURES (a second accepted prediction_type):

Besides price-target predictions, Eidolum also tracks position disclosures.
A position disclosure is a tweet where the author says they opened, added
to, trimmed, or exited a stock position. Examples:

  - 'New position in $NVDA'                 -> open,  bullish
  - 'Loaded up on $META'                    -> add,   bullish
  - 'Added to my $GOOGL stake'              -> add,   bullish
  - 'Trimmed $TSLA'                         -> trim,  bullish
  - 'Exited my $AAPL completely'            -> exit,  bullish
  - 'Sold all my $AMD'                      -> exit,  bullish
  - 'Initiating short $SHOP'                -> open,  bearish
  - 'Covered my $NFLX short'                -> exit,  bearish
  - '13F: new 900K share position in $PARA' -> open,  bullish

Position disclosures do NOT need a price target, a timeframe, or an
explicit rating word. The ACTION (open/add/trim/exit) is the signal.
Target_price and timeframe stay null for these.

For position disclosures, set:
  prediction_type = "position_disclosure"
  position_action = "open" | "add" | "trim" | "exit"
  direction       = "bullish" for long positions, "bearish" for short positions
                    (trim/exit keep the SAME direction as the underlying position)

Everything else (L0-L4 scale, rejection rules) still applies. A tweet that
merely MENTIONS a holding without stating an action ("long $NVDA for years")
is still a price-target-style call if it has a directional claim; only the
explicit open/add/trim/exit language counts as a position disclosure.

OUTPUT FORMAT (strict JSON, no extra text):
{
  "is_prediction": true | false,
  "prediction_type": "price_target" | "position_disclosure" | "sector_call" | null,
  "position_action": "open" | "add" | "trim" | "exit" | null,
  "sector": "semis" | "regional banks" | null,
  "ticker": "AAPL" | null,
  "direction": "bullish" | "bearish" | "neutral" | null,
  "target_price": 250.00 | null,
  "timeframe": "3 months" | "by Q2" | "EOY" | null,
  "confidence": "high" | "medium" | "low",
  "closeness_level": 0 | 1 | 2 | 3 | 4 | null,
  "reason": "brief explanation, max 100 chars"
}

For price-target predictions, prediction_type="price_target", position_action=null, sector=null.
For position disclosures, prediction_type="position_disclosure", position_action is set, sector=null.
For sector calls, prediction_type="sector_call", sector=<phrase from tweet>, ticker=null,
target_price=null, timeframe REQUIRED, direction REQUIRED.
If prediction_type is omitted, assume "price_target".

SECTOR CALLS (a third accepted prediction_type):

A sector call is a tweet that makes a bullish or bearish call on a SECTOR
(not a single stock). The author names a sector phrase from Requirement 1(b)
and asserts a direction with a timeframe. We map the phrase to a sector
ETF server-side (e.g., "semis" -> SOXX, "regional banks" -> KRE, "tech" -> XLK)
and score the call as the ETF's return vs SPY's return over the window.

Sector calls do NOT need a price target. They DO need a timeframe — without
one they are vague vibes and must be REJECTED.

Examples:
  - 'Semis are going to rip in Q2 2026'         -> sector="semis",          bullish, "Q2 2026"
  - 'Bearish on regional banks for 6 months'     -> sector="regional banks", bearish, "6 months"
  - 'Homebuilders look cooked into year-end'     -> sector="homebuilders",   bearish, "year-end"
  - 'Energy is a buy here for the next 12 months'-> sector="energy",         bullish, "12 months"
  - 'Pharma topping into Q3'                     -> sector="pharma",         bearish, "Q3"

For sector calls, set:
  prediction_type = "sector_call"
  sector          = the lowercase phrase exactly as it appears in the tweet
  direction       = "bullish" or "bearish"
  timeframe       = REQUIRED (e.g., "Q2", "6 months", "EOY", "year-end")
  ticker          = null  (we resolve sector -> ETF server-side)
  target_price    = null

A tweet that names a sector phrase but has NO timeframe is still a vague vibe
and must be rejected (closeness_level=4 if it had directional lean).

If is_prediction is false, set ticker/direction/target_price/timeframe/confidence to null, explain WHY in reason, AND set closeness_level using the criteria below.

═══════════════════════════════════════════════════════════════════════════
CLOSENESS LEVEL CRITERIA (apply in order; use the FIRST level that matches)
═══════════════════════════════════════════════════════════════════════════

L4 -- "Almost a prediction"
  REQUIRES ALL OF:
    - Has a literal ticker or sector ETF in the text ($AAPL, NVDA, XLE, SPY)
    - Has a clear directional lean about that ticker (up/down/long/short)
    - Missing EXACTLY ONE of: price target, timeframe, explicit rating word
  AND AT LEAST ONE OF:
    - Uses hedged language: "could", "might", "looks like", "seems"
    - Is conditional: "if X holds/breaks, then Y"
    - Is a watchlist with a lean but no commit: "watching $NVDA for a long"
  Examples:
    - "$NVDA looking strong into earnings, could run"  (hedged, no target/timeframe)
    - "Watching $TSLA, I think the bottom is in"       (lean + hedge, no commit)
    - "If $AAPL holds $170, big move coming"           (conditional)
  TIEBREAKER: If the tweet has ALL THREE (ticker + direction + target/timeframe/rating),
              it should have been ACCEPTED, not L4. L4 is strictly "almost".

L3 -- "Directional but vague"
  REQUIRES:
    - Has a literal ticker
    - Has SOME directional context (bullish/bearish lean)
    - But reads as commentary/observation, not a call
  DIFFERS FROM L4 by:
    - L3 has no "missing one element" -- it never had the shape of an actionable
      call in the first place. L4 is a near-miss; L3 is a take.
  Examples:
    - "Still love $META long-term, patient capital wins"    (opinion, no action)
    - "$COIN earnings tomorrow, positioning is interesting" (observation)
    - "$SPY grinding higher, nothing to do"                 (commentary + non-call)

L2 -- "Opinion/sentiment" (ticker mentioned, no directional claim)
  REQUIRES:
    - Has at least one literal ticker
    - NO directional claim about that ticker
  COMMON PATTERNS:
    - Watchlists: "Tickers on my radar: $AAPL $MSFT $GOOGL"
    - Portfolio updates: "Added $NVDA to the pile"
    - Chart observations: "$AMZN chart looks like a triangle"
    - News repetition: "$BMNR reports earnings tomorrow"
  Examples:
    - "Stocks on my radar today: $AAPL $MSFT $GOOGL"
    - "Portfolio update: added $NVDA"
    - "$AMZN chart looks like a triangle"

L1 -- "Off-topic market talk" (finance, but no specific ticker or ETF)
  REQUIRES:
    - Tweet is finance-related (macro, Fed, rates, crypto generalities, sectors)
    - NO literal ticker or sector ETF anywhere in the text
  Examples:
    - "Fed will cut 3 times next year"
    - "Bond market is broken"
    - "Crypto about to have a moment"
    - "Markets are forward looking, Iran war 90% priced in"

L0 -- "Not finance at all" (off-topic)
  REQUIRES:
    - Tweet is about personal life, politics, sports, memes, promotion
    - NO meaningful finance content
  Examples:
    - "Great dinner at Carbone last night"
    - "Elon is right about everything"
    - "GM to everyone in the TL"

═══════════════════════════════════════════════════════════════════════════
HOW TO ASSIGN (decision procedure -- follow in order)
═══════════════════════════════════════════════════════════════════════════

  1. Does the tweet mention any stock/ETF ticker in the text? If NO -> L1 or L0.
     - If it talks about markets/Fed/macro/crypto -> L1
     - Otherwise                                  -> L0

  2. Ticker IS present. Does the tweet make a directional claim about it?
     If NO -> L2 (opinion/sentiment/watchlist/news repetition).

  3. Direction IS present. Does it ALSO have a price target, timeframe,
     OR an explicit rating word (buy/sell/bullish/bearish/long/short/
     outperform/underperform/overweight/underweight)?
     If YES -> is_prediction=true (ACCEPT, closeness_level=null).
     If NO but directional shape is almost right (hedged/conditional/
        "looking for", "watching for a run") -> L4 (almost a prediction).
     If NO and it reads as commentary/opinion -> L3 (directional but vague).

═══════════════════════════════════════════════════════════════════════════
CONSISTENCY RULES
═══════════════════════════════════════════════════════════════════════════
  - L4 is rare. Don't inflate. An L4 tweet is one a human reviewer would
    look at and say "that was close."
  - Never assign L4 to a tweet without a literal ticker -- those are L1 or L0.
  - Never assign L3 to a watchlist or portfolio update -- those are L2.
  - Never assign L2 to a macro take -- those are L1.
  - When in doubt between two levels, pick the LOWER one. L0 floor for safety.

When is_prediction is true, set closeness_level to null (accepted tweets are not "close to" anything, they ARE predictions).

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


def _extract_closeness_level(result: dict | None) -> int | None:
    """Extract and validate closeness_level from Haiku response. 0-4 or None."""
    if not result:
        return None
    cl = result.get("closeness_level")
    if cl is None:
        return None
    try:
        cl = int(cl)
    except (ValueError, TypeError):
        return None
    if cl < 0 or cl > 4:
        return None
    return cl


VALID_POSITION_ACTIONS = {"open", "add", "trim", "exit"}

def _extract_position_fields(result: dict | None) -> tuple[str, str | None]:
    """Return (prediction_type, position_action) from a Haiku classification.

    - If Haiku says prediction_type='position_disclosure' AND position_action
      is in the allowed set, returns ('position_disclosure', action).
    - Otherwise defaults to ('price_target', None).
    """
    if not result:
        return "price_target", None
    ptype = (result.get("prediction_type") or "").strip().lower()
    if ptype != "position_disclosure":
        return "price_target", None
    action = (result.get("position_action") or "").strip().lower()
    if action not in VALID_POSITION_ACTIONS:
        return "price_target", None
    return "position_disclosure", action


def _extract_sector_fields(result: dict | None, tweet_text: str) -> tuple[str | None, str | None, str | None]:
    """Return (etf_ticker, sector_phrase, error) for a sector_call result.

    Returns ('SOXX', 'semis', None) if Haiku said sector_call AND the sector
    phrase appears literally in the tweet AND it resolves to an ETF.
    Returns (None, sector_phrase, 'sector_etf_unknown') if the phrase doesn't
    resolve. Returns (None, None, 'sector_phrase_not_in_text') if Haiku
    hallucinated a sector that isn't in the tweet. Returns (None, None, None)
    if this is not a sector call at all.
    """
    if not result:
        return None, None, None
    ptype = (result.get("prediction_type") or "").strip().lower()
    if ptype != "sector_call":
        return None, None, None

    from services.sector_etf_map import resolve_sector_to_etf, find_sector_phrase_in_text

    sector_phrase = (result.get("sector") or "").strip().lower()
    if not sector_phrase:
        return None, None, "sector_phrase_not_in_text"

    # Defense in depth: phrase must appear literally in tweet (Haiku may hallucinate)
    if sector_phrase not in tweet_text.lower():
        # Maybe the phrase Haiku returned is a synonym; try matching ANY known
        # sector phrase that appears in the tweet
        found = find_sector_phrase_in_text(tweet_text)
        if not found:
            return None, sector_phrase, "sector_phrase_not_in_text"
        sector_phrase = found

    etf = resolve_sector_to_etf(sector_phrase)
    if not etf:
        return None, sector_phrase, "sector_etf_unknown"

    return etf, sector_phrase, None


def validate_haiku_result(result: dict, tweet_text: str) -> tuple[bool, str]:
    """Python-side safety net for the new strict Haiku prompt.

    Returns (is_valid, reason). Even if Haiku says is_prediction=true, this
    enforces the three requirements from the prompt independently.

    Sector calls (prediction_type='sector_call') get a slightly different
    validation: ticker is server-resolved so the ticker_in_text check is
    skipped, but a timeframe is REQUIRED (otherwise it's a vague vibe).
    """
    if not result or not result.get("is_prediction"):
        return False, "haiku_rejected"
    if result.get("confidence") == "low":
        return False, "low_confidence"

    ptype = (result.get("prediction_type") or "").strip().lower()
    is_sector_call = ptype == "sector_call"
    is_vibes = ptype == "vibes"
    is_position = ptype == "position_disclosure"

    if is_sector_call:
        # Sector calls: sector phrase substitutes for ticker. We don't validate
        # the literal sector phrase here — _extract_sector_fields will do that
        # in the run loop and reject with sector_phrase_not_in_text /
        # sector_etf_unknown if it fails.
        sector_phrase = (result.get("sector") or "").strip()
        if not sector_phrase:
            return False, "no_sector_phrase"
        # Direction
        direction = (result.get("direction") or "").lower()
        if direction not in ("bullish", "bearish"):
            return False, "no_direction"
        # Sector calls REQUIRE a timeframe (no ambiguity allowed)
        if not result.get("timeframe"):
            return False, "no_timeframe_for_sector_call"
        return True, "accepted"

    ticker = result.get("ticker")
    if not ticker:
        return False, "no_ticker"

    # Requirement 1: ticker must literally appear in tweet text (applies
    # to vibes too — vibes need a real ticker, not a hallucinated one)
    if not _ticker_in_text(ticker, tweet_text):
        return False, "ticker_not_in_text"

    # Requirement 2: must have a direction
    direction = (result.get("direction") or "").lower()
    if direction not in ("bullish", "bearish", "neutral"):
        return False, "no_direction"

    if is_vibes:
        # Vibes: ticker + direction is enough. confidence_tier=0.5 captures
        # the lower trust. We deliberately do NOT require a target or
        # timeframe for vibes — that's the whole point of the type.
        return True, "accepted"

    if is_position:
        # Position disclosures: Haiku already asserted this is an open/add/
        # trim/exit action. The action IS the signal. We only require a
        # valid position_action value — everything else (target, timeframe,
        # rating) is irrelevant for this type. Trust the concept-first
        # classification; don't re-check fintwit shorthand with regex.
        paction = (result.get("position_action") or "").strip().lower()
        if paction not in ("open", "add", "trim", "exit"):
            return False, "invalid_position_action"
        return True, "accepted"

    # Requirement 3: concrete directional claim — target, timeframe, explicit
    # rating, OR a strong directional action verb. The action-verb path
    # accepts real fintwit calls like "$NVDA breaking out" or "$TSLA crashing"
    # that don't always carry a numeric target.
    has_target = result.get("target_price") is not None
    has_timeframe = bool(result.get("timeframe"))
    has_explicit_rating = bool(_EXPLICIT_RATING_RE.search(tweet_text))
    text_lower = tweet_text.lower()
    has_strong_action = any(v in text_lower for v in [
        # directional verbs
        'breaking out', 'breakout', 'topping', 'rolling over',
        'ripping', 'crashing', 'crushed', 'pumping', 'dumping',
        'headed higher', 'headed lower', 'going higher',
        'going lower', 'moon', 'tank', 'collapse', 'rally',
        'squeeze', 'breakdown', 'reversal', 'capitulation',
        'going to', 'target',
        # fintwit shorthand keywords
        ' long ', ' long,', ' long.', ' long\n', ' long ',
        ' short ', ' short,', ' short.', ' short\n',
        ' calls ', ' puts ', 'call ', 'put ',  # options without strike
        ' stop ', ' entry ', ' alert ', ' trigger ',
        # position disclosures / trade actions (Burry/Ackman/Einhorn style)
        'new position', 'initiating long', 'initiating short',
        'added to', 'cut my', 'exited', 'bought ', 'sold ',
        'went long', 'went short', 'loaded up', 'took profit',
        '13f', 'increased stake', 'reduced stake', 'covered',
    ])
    # Options notation: $TICKER 600c | $TICKER 600p (call/put with strike)
    has_options_strike = bool(re.search(
        r'\$[A-Z]{1,5}\s+\d+(?:\.\d+)?[cp]\b', tweet_text, re.IGNORECASE
    ))
    if not (has_target or has_timeframe or has_explicit_rating or has_strong_action or has_options_strike):
        return False, "no_concrete_signal"

    return True, "accepted"


def _sanitize_tweet_for_haiku(text: str) -> str:
    """Make a tweet safe to put inside a JSON request body to Anthropic.

    Anthropic's API has been observed to return HTTP 400 on tweets that
    contain certain unicode control characters or zero-width sequences.
    The 🚨 emoji itself is fine (4-byte UTF-8) but it often appears
    alongside zero-width joiners, BOM markers, U+FFFC object replacement,
    bidi marks, and stray null/SOH/EOT control bytes that some scraper
    pipelines leak through.

    Steps:
      1. Unicode NFKC normalization (folds compat sequences)
      2. Strip control chars EXCEPT \\n and \\t (preserves line breaks)
      3. Strip the BOM and zero-width joiners that confuse JSON parsers
      4. Truncate to 500 chars (Haiku output budget is tight)
      5. Strip leading/trailing whitespace
    """
    import unicodedata
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    out_chars = []
    for c in text:
        if c == "\n" or c == "\t":
            out_chars.append(c)
            continue
        # Drop all control category 'C' chars (Cc, Cf, Cs, Co, Cn).
        # This includes the BOM (U+FEFF), zero-width joiners (U+200D),
        # bidi marks (U+200E/U+200F), object replacement (U+FFFC), and
        # the C0/C1 control sets.
        if unicodedata.category(c)[0] == "C":
            continue
        out_chars.append(c)
    cleaned = "".join(out_chars)[:500].strip()
    return cleaned


def _classify_with_groq(tweet_text: str) -> dict:
    """Call Groq llama-3.3-70b-versatile to classify a single tweet.

    ALWAYS returns a dict. On success, the dict is Groq's parsed JSON
    response with _success=True added. On any failure (missing key, HTTP
    error, parse error, timeout, retries exhausted, rate limit) the dict
    contains:
        {"_success": False, "error": "<short_error_tag>",
         "is_prediction": False}
    so the caller never has to deal with None and can distinguish
    classifier FAILURES from classifier REJECTIONS.

    Pacing: every call goes through the process-wide _GroqRateLimiter
    BEFORE issuing the HTTP request. The limiter sleeps until the call
    fits inside the per-minute budget, so the request count never
    exceeds GROQ_MAX_RPM by construction. The HTTP-level 429 retry
    loop below is a SECOND line of defense in case the server-side
    counter and our window drift apart.

    Retries on HTTP 429 with exponential backoff (2s, 4s). After 3
    exhausted retries, returns error="groq_rate_limited". NEVER falls
    back to Haiku — the X scraper has been deliberately decoupled from
    Anthropic billing per the Apr 8 outage post-mortem.
    """
    if not GROQ_API_KEY:
        print("[X-SCRAPER] Groq NO_KEY — GROQ_API_KEY missing", flush=True)
        return {"_success": False, "error": "no_api_key", "is_prediction": False}

    # Reuse the Haiku-era sanitizer: it strips unicode control bytes and
    # zero-width joiners, which trip up any LLM JSON-mode parser, not
    # just Anthropic's. Name retained for diff minimalism — rename in a
    # follow-up cleanup pass.
    sanitized = _sanitize_tweet_for_haiku(tweet_text)
    if not sanitized:
        return {"_success": False, "error": "empty_after_sanitize",
                "is_prediction": False}

    max_retries = 3
    base_delay = 2.0
    last_status = None
    last_body_snippet = ""

    # Same prompt as Haiku — verified end-to-end against Groq llama-3.3-70b
    # before merge. Groq's response_format=json_object guarantees parseable
    # output, eliminating the markdown-fence stripping path.
    request_body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": HAIKU_SYSTEM},
            {"role": "user", "content": sanitized},
        ],
        "temperature": 0.1,
        "max_tokens": 250,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(max_retries):
        # Pace BEFORE the HTTP call so we never burst over the per-minute
        # budget on the first attempt of a tight loop.
        _groq_limiter.acquire()
        try:
            r = httpx.post(GROQ_URL, headers=headers, json=request_body, timeout=30)
            last_status = r.status_code
            last_body_snippet = (r.text or "")[:500]

            if r.status_code == 429:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(
                        f"[X-SCRAPER] Groq 429, backing off {delay}s "
                        f"(attempt {attempt + 1}/{max_retries}) body={last_body_snippet[:200]}",
                        flush=True,
                    )
                    time.sleep(delay)
                    continue
                print(
                    f"[X-SCRAPER] Groq RATE_LIMIT exhausted on tweet: "
                    f"{tweet_text[:80]!r} body={last_body_snippet[:200]}",
                    flush=True,
                )
                return {"_success": False, "error": "groq_rate_limited",
                        "is_prediction": False}

            if r.status_code in (401, 403):
                print(f"[X-SCRAPER] Groq AUTH_{r.status_code} body={last_body_snippet}", flush=True)
                return {"_success": False,
                        "error": f"auth_{r.status_code}: {last_body_snippet[:200]}",
                        "is_prediction": False}

            if r.status_code != 200:
                # Surface the full body so we can diagnose without a round
                # trip. Tag includes "http_NNN: <body>" so it lands in the
                # x_scraper_rejections.haiku_reason column for grep.
                print(
                    f"[X-SCRAPER] Groq HTTP_{r.status_code} model='{GROQ_MODEL}' "
                    f"tweet={sanitized[:120]!r}",
                    flush=True,
                )
                print(
                    f"[X-SCRAPER] Groq HTTP_{r.status_code} body={last_body_snippet}",
                    flush=True,
                )
                err_detail = last_body_snippet.replace("\n", " ")[:350]
                return {
                    "_success": False,
                    "error": f"http_{r.status_code}: {err_detail}",
                    "is_prediction": False,
                }

            resp_json = r.json()
            content = (
                ((resp_json.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            )
            content = (content or "").strip()
            if content.startswith("```"):
                # Defensive: response_format=json_object should never wrap
                # in fences, but strip them just in case the model regresses.
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as pe:
                raw_snippet = (content or "no content")[:200]
                print(
                    f"[X-SCRAPER] Groq PARSE_ERROR: {pe} | raw={raw_snippet!r}",
                    flush=True,
                )
                return {
                    "_success": False,
                    "error": f"parse_error: {raw_snippet}",
                    "is_prediction": False,
                }

            if not isinstance(parsed, dict):
                print(
                    f"[X-SCRAPER] Groq NON_DICT response: {type(parsed).__name__}",
                    flush=True,
                )
                return {"_success": False, "error": "non_dict_response",
                        "is_prediction": False}

            parsed["_success"] = True
            return parsed

        except httpx.TimeoutException as te:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(
                    f"[X-SCRAPER] Groq TIMEOUT, backing off {delay}s "
                    f"(attempt {attempt + 1}/{max_retries})",
                    flush=True,
                )
                time.sleep(delay)
                continue
            print(f"[X-SCRAPER] Groq TIMEOUT exhausted: {te}", flush=True)
            return {"_success": False, "error": "timeout", "is_prediction": False}

        except Exception as e:
            msg = str(e).lower()
            if ("429" in msg or "rate_limit" in msg) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(
                    f"[X-SCRAPER] Groq exception 429, backing off {delay}s "
                    f"(attempt {attempt + 1}/{max_retries}): {e}",
                    flush=True,
                )
                time.sleep(delay)
                continue
            if attempt == 0:
                print(f"[X-SCRAPER] Groq UNKNOWN {type(e).__name__}: {e}", flush=True)
            return {"_success": False, "error": f"unknown_{type(e).__name__}",
                    "is_prediction": False}

    # Should never reach here, but return a safe default just in case
    return {"_success": False, "error": "retry_loop_fallthrough",
            "is_prediction": False}


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
    """Quick pre-filter before sending to AI. Returns rejection reason or None if OK.

    Tweets pass if they contain EITHER a ticker-shaped token OR a recognized
    sector phrase. The min-length floor is 8 chars because fintwit shorthand
    like "$AAPL long" (10 chars), "$META breakout" (14), or "$NVDA 600c" (10)
    is the WHOLE POINT of accounts like @unusual_whales / @ripster47 /
    @markflowchatter — anything tighter than 8 chars can't carry a ticker
    plus minimal context.
    """
    if is_rt:
        return "retweet"
    if len(text.strip()) < 8:
        return "too_short"
    if any(p.search(text) for p in SPAM_PATTERNS):
        return "spam"
    if not TICKER_MENTION_RE.search(text):
        # Allow sector-call candidates through to Haiku.
        from services.sector_etf_map import find_sector_phrase_in_text
        if not find_sector_phrase_in_text(text):
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
            headers=_APIFY_HEADERS,
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
            sr = httpx.get(f"{APIFY_API}/actor-runs/{run_id}", headers=_APIFY_HEADERS, timeout=15)
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
                       params={"format": "json"}, headers=_APIFY_HEADERS, timeout=60)
        items = dr.json() if dr.status_code == 200 else []
        return items if isinstance(items, list) else []

    except Exception as e:
        print(f"[X-SCRAPER] Apify error for @{handle}: {e}", flush=True)
        return []


# ── Insert prediction into database ──────────────────────────────────────────

def _insert_prediction(db, ticker: str, direction: str, target_price, timeframe_days: int,
                       author: str, body: str, tid: str, tweet_url: str, pred_date: datetime,
                       prediction_type: str = "price_target",
                       position_action: str | None = None,
                       confidence_tier: float = 1.0) -> bool:
    """Insert a single prediction. Returns True on success.

    For position disclosures (prediction_type='position_disclosure',
    position_action in {open, add}): target_price stays None, evaluation_date
    is set to prediction_date + 365d as a fallback horizon, and
    confidence_tier defaults to 0.85 (caller should pass this).

    Trim/exit actions should NOT reach this function — they should call
    position_matcher.close_position() to close an existing open position.
    """
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

        # Pillar 4: store the immutable tweet ID. Tweets need no Wayback archive
        # because the tweet ID itself is the archive (snowflake-decoded for date,
        # reconstructible into a URL).
        try:
            tweet_id_int = int(tid) if tid else None
        except (ValueError, TypeError):
            tweet_id_int = None

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
            tweet_id=tweet_id_int,
            context=context[:500], exact_quote=body[:500],
            outcome="pending", verified_by="x_scraper",
            prediction_type=prediction_type,
            position_action=position_action,
            confidence_tier=confidence_tier,
        ))
        return True
    except Exception:
        return False


# ── Persist rejected tweets for admin debug view ─────────────────────────────

def log_rejection(db, tweet: dict, handle: str, rejection_reason: str,
                  haiku_reason: str | None, haiku_raw: dict | None,
                  closeness_level: int | None = None) -> None:
    """Persist a rejected tweet to x_scraper_rejections.
    Best-effort: a persist failure must NEVER break the scrape loop.

    closeness_level: 0-4 from Haiku (or None for pre-classification rejections
    like no_tweet_id, and for any row where Haiku didn't return a level).
    """
    try:
        tid_raw = tweet.get("id") or tweet.get("id_str") or 0
        try:
            tweet_id = int(tid_raw) if tid_raw else 0
        except (ValueError, TypeError):
            tweet_id = 0

        body = _get_tweet_body(tweet) or ""

        tweet_created = None
        if tweet_id:
            try:
                tweet_created = tweet_id_to_datetime(tweet_id)
            except Exception:
                tweet_created = None

        # Cap haiku_raw at ~10KB to avoid bloating the table
        raw_json = None
        if haiku_raw:
            try:
                serialized = json.dumps(haiku_raw)
                if len(serialized) <= 10240:
                    raw_json = serialized
                else:
                    raw_json = json.dumps({"_truncated": True, "_size": len(serialized)})
            except Exception:
                raw_json = None

        # Defense in depth: never write NULL or empty haiku_reason. Earlier
        # versions had `(haiku_reason or "")[:500] if haiku_reason else None`
        # which collapsed empty strings to NULL. We now floor at a constant
        # so the column is always queryable and counts up by failure mode.
        if haiku_reason is None or (isinstance(haiku_reason, str) and not haiku_reason.strip()):
            hr_value = "no_reason_returned"
        else:
            hr_value = str(haiku_reason)[:500]

        # rejected_at intentionally omitted: Postgres DEFAULT NOW() fills it.
        # The DDL default is set on the live table by an ALTER TABLE migration
        # in worker.py startup, and the model has server_default=func.now() so
        # fresh DBs get it via create_all. Eight columns, eight values.
        db.execute(sql_text("""
            INSERT INTO x_scraper_rejections
                (tweet_id, handle, tweet_text, tweet_created_at,
                 rejection_reason, haiku_reason, haiku_raw_response,
                 closeness_level)
            VALUES (:tid, :h, :tt, :tc, :rr, :hr, CAST(:hraw AS JSONB), :cl)
        """), {
            "tid": tweet_id,
            "h": handle,
            "tt": body[:2000],  # cap text at 2KB
            "tc": tweet_created,
            "rr": rejection_reason,
            "hr": hr_value,
            "hraw": raw_json,
            "cl": closeness_level,
        })
        db.commit()
    except Exception as e:
        log.warning(f"[X-SCRAPER] log_rejection failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass


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
    """Main entry point. Scrapes tracked X accounts and classifies tweets with Groq."""
    print("[X-SCRAPER] run_x_scraper() called", flush=True)
    print(
        f"[X-SCRAPER] classifier=groq model={GROQ_MODEL} max_rpm={GROQ_MAX_RPM}",
        flush=True,
    )

    if not APIFY_API_TOKEN:
        print("[X-SCRAPER] APIFY_API_TOKEN not set, skipping", flush=True)
        return
    if not GROQ_API_KEY:
        print("[X-SCRAPER] FATAL: GROQ_API_KEY not set. Cannot run without classifier.", flush=True)
        return

    # Seed accounts if table is empty
    try:
        from jobs.seed_x_accounts import seed_tracked_x_accounts
        seed_tracked_x_accounts(db)
    except Exception as e:
        print(f"[X-SCRAPER] Seed error: {e}", flush=True)

    # One-time backfill: patch any existing NULL rejected_at rows so the
    # /rejections/summary endpoint can find them. Idempotent: future runs
    # match nothing because the column is now always populated on insert.
    try:
        db.execute(sql_text(
            "UPDATE x_scraper_rejections SET rejected_at = NOW() WHERE rejected_at IS NULL"
        ))
        db.commit()
    except Exception as e:
        log.warning(f"[X-SCRAPER] rejected_at backfill failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    # Prune rejection log to last 7 days (best-effort, never block scrape).
    # NOTE: rows whose rejected_at is older than 7d are dropped — the backfill
    # above runs first so legitimate recent rows are not lost.
    try:
        db.execute(sql_text(
            "DELETE FROM x_scraper_rejections WHERE rejected_at < NOW() - INTERVAL '7 days'"
        ))
        db.commit()
    except Exception as e:
        log.warning(f"[X-SCRAPER] rejection cleanup failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass

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
        "blocked_handles": 0,
    }
    # Strict-mode rejection breakdown (Phase 5)
    rejection_reasons: dict[str, int] = {}
    first_tweet_logged = False
    # Debug log cap: print up to 50 haiku_rejected tweets per run for prompt tuning
    haiku_rejected_logged = 0

    for account_id, handle in accounts:
        # Hard-block news-firehose handles before Apify is even called.
        # Saves both Apify cost AND Haiku cost. See BLOCKED_HANDLES at the
        # top of this file for the rationale.
        if _is_blocked_handle(handle):
            total_stats["blocked_handles"] += 1
            print(f"[X-SCRAPER] @{handle}: BLOCKED (news firehose, skipping)", flush=True)
            continue

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

                # Pillar 6: derive prediction_date from tweet ID (snowflake) only.
                # If decoding fails, SKIP the tweet — empty results are better than wrong
                # results. This prevents the year-1900 bug from ever recurring.
                pred_date = tweet_id_to_datetime(tid)
                if not pred_date:
                    print(f"[X-SCRAPER-WARN] no tweet id, skipping (tid={tid!r})", flush=True)
                    rejection_reasons["no_tweet_id"] = rejection_reasons.get("no_tweet_id", 0) + 1
                    log_rejection(db, tweet, handle, "no_tweet_id", None, None)
                    continue

                # Age filter: drop tweets older than MAX_TWEET_AGE_DAYS. Apify
                # occasionally returns 10+ year old tweets for accounts with
                # deep history, which wastes Haiku quota on unactionable
                # content. Count these so we can see the volume in the
                # per-run summary.
                age_days = (datetime.utcnow() - pred_date).days
                if age_days > MAX_TWEET_AGE_DAYS:
                    rejection_reasons["too_old"] = rejection_reasons.get("too_old", 0) + 1
                    log_rejection(db, tweet, handle, "too_old",
                                  f"tweet_age_days={age_days}", None, None)
                    continue

                # Passive discovery
                _record_mentioned_handles(body, tracked_handles, db)

                reason = _prefilter_tweet(body, is_rt)
                if reason:
                    continue

                total_stats["prefilter_pass"] += 1
                total_stats["ai_sent"] += 1

                # Classify with Groq (always returns a dict — see _classify_with_groq).
                # The rate limiter inside _classify_with_groq paces calls to
                # GROQ_MAX_RPM, so we no longer need a manual sleep here.
                result = _classify_with_groq(body)

                # Classifier FAILURE (distinct from classifier REJECTION):
                # if _success is False, Groq didn't give us a real verdict.
                # Log with a specific rejection_reason so the distribution in
                # x_scraper_rejections tells us exactly what went wrong.
                # NOTE: rejection_reason stays "haiku_error" / "haiku_rejected"
                # for now to keep the rejection-viewer filters working. The
                # haiku_reason column gets the new groq error tag. Column
                # rename is a separate follow-up migration.
                classifier_failed = result.get("_success") is False
                if classifier_failed:
                    err_tag = result.get("error", "unknown_failure")
                    rej_key = f"groq_{err_tag.split(':')[0]}"
                    rejection_reasons[rej_key] = rejection_reasons.get(rej_key, 0) + 1
                    log_rejection(db, tweet, handle, "haiku_error", err_tag, result, None)
                    continue

                # Phase 5: unified strict validation (matches the Haiku prompt's 3 requirements)
                is_valid, reject_reason = validate_haiku_result(result, body)
                # Normalize haiku_reason once so EVERY downstream log_rejection
                # call writes a non-null value. log_rejection has a defense-in-
                # depth fallback too, but doing it here is cheaper and clearer.
                haiku_reason = (result.get("reason") or "").strip() or "no_reason_returned"
                closeness_level = _extract_closeness_level(result)
                if not is_valid:
                    # Debug log for haiku_rejected rejections — capped at 50 per run
                    # so we can verify the soft prompt without flooding logs.
                    if reject_reason == "haiku_rejected" and haiku_rejected_logged < 50:
                        if log.isEnabledFor(logging.INFO):
                            log.info(
                                f"[X-SCRAPER-DEBUG] haiku_rejected: @{handle} "
                                f"tweet_id={tid} reason={haiku_reason} "
                                f"level={closeness_level} text={body[:150]!r}"
                            )
                        haiku_rejected_logged += 1
                    rejection_reasons[reject_reason] = rejection_reasons.get(reject_reason, 0) + 1
                    # haiku_reason was normalized above to never be empty.
                    log_rejection(
                        db, tweet, handle, reject_reason,
                        haiku_reason,
                        result, closeness_level,
                    )
                    continue

                confidence = (result.get("confidence") or "low").lower()
                total_stats["ai_predictions"] += 1
                if confidence == "high":
                    total_stats["ai_high"] += 1
                else:
                    total_stats["ai_medium"] += 1

                # Sector call resolution: if Haiku said sector_call, resolve the
                # sector phrase to an ETF ticker and substitute it for the
                # missing literal ticker. Reject if the phrase is unknown or
                # not actually present in the tweet text.
                sector_etf, sector_phrase, sector_err = _extract_sector_fields(result, body)
                if sector_err:
                    rejection_reasons[sector_err] = rejection_reasons.get(sector_err, 0) + 1
                    log_rejection(db, tweet, handle, sector_err, haiku_reason, result, closeness_level)
                    continue
                is_sector_call = sector_etf is not None
                if is_sector_call:
                    ticker = sector_etf
                else:
                    ticker = (result.get("ticker") or "").upper().lstrip("$")
                direction = (result.get("direction") or "").lower()
                # We only insert directional predictions; "neutral" is rejected here
                if direction not in ("bullish", "bearish"):
                    rejection_reasons["neutral_or_no_direction"] = rejection_reasons.get("neutral_or_no_direction", 0) + 1
                    log_rejection(db, tweet, handle, "neutral_or_no_direction", haiku_reason, result, closeness_level)
                    continue

                # Currency tickers are never predictions (n/a for sector calls)
                if not is_sector_call and ticker in CURRENCY_IGNORE:
                    rejection_reasons["currency_ticker"] = rejection_reasons.get("currency_ticker", 0) + 1
                    log_rejection(db, tweet, handle, "currency_ticker", haiku_reason, result, closeness_level)
                    continue

                # Phase 1: ticker must be a recognised stock symbol form OR an allowed sector ETF.
                # find_forecaster + the rest of the pipeline accept any uppercase ticker, so the
                # gate here is just: if it's not in the explicit ETF allowlist, it must look like
                # a normal cashtag-style symbol (1-5 uppercase letters). Crypto and stocks both
                # satisfy that. The ETF allowlist gives sector ETFs an explicit pass even if
                # downstream sector lookup would otherwise treat them as "Other".
                if not (re.fullmatch(r"[A-Z]{1,5}", ticker) or _is_allowed_etf(ticker)):
                    rejection_reasons["invalid_ticker_format"] = rejection_reasons.get("invalid_ticker_format", 0) + 1
                    log_rejection(db, tweet, handle, "invalid_ticker_format", haiku_reason, result, closeness_level)
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

                # Position disclosure branch: if Haiku classified this as a
                # position_disclosure with a valid action, route open/add to
                # the insert path with a 365d fallback horizon, and trim/exit
                # to position_matcher to close the existing open position.
                ptype, paction = _extract_position_fields(result)
                if ptype == "position_disclosure" and paction in ("trim", "exit") and db:
                    from jobs.news_scraper import find_forecaster
                    from services.position_matcher import find_open_position, close_position
                    forecaster = find_forecaster(handle, db)
                    if not forecaster:
                        total_stats["dupes"] += 1
                        continue
                    open_pos = find_open_position(db, forecaster.id, ticker)
                    if open_pos:
                        close_position(db, open_pos["id"], pred_date)
                        total_stats["position_closed"] = total_stats.get("position_closed", 0) + 1
                        print(f"[X-SCRAPER] @{handle} {paction.upper()} ${ticker} → "
                              f"closed position id={open_pos['id']}", flush=True)
                    else:
                        rejection_reasons["position_exit_no_match"] = \
                            rejection_reasons.get("position_exit_no_match", 0) + 1
                        log_rejection(db, tweet, handle, "position_exit_no_match",
                                      haiku_reason, result, closeness_level)
                    continue

                # Vibes branch: ticker + direction with no concrete target.
                # confidence_tier=0.5, default 30-day window, no target_price.
                is_vibes = (result.get("prediction_type") or "").strip().lower() == "vibes"

                if db:
                    if is_sector_call:
                        # Sector call: ticker is the resolved ETF, target stays
                        # null, confidence slightly downweighted vs explicit
                        # price-target predictions.
                        ok = _insert_prediction(
                            db, ticker, direction, None, tf_days,
                            handle, body, tid, tweet_url, pred_date,
                            prediction_type="sector_call",
                            position_action=None,
                            confidence_tier=0.85,
                        )
                    elif is_vibes:
                        # Vibes: 30-day default window, no target, conf 0.5
                        vibes_window = tf_days if result.get("timeframe") else 30
                        ok = _insert_prediction(
                            db, ticker, direction, None, vibes_window,
                            handle, body, tid, tweet_url, pred_date,
                            prediction_type="vibes",
                            position_action=None,
                            confidence_tier=0.5,
                        )
                    elif ptype == "position_disclosure" and paction in ("open", "add"):
                        # Position open/add: 365-day fallback horizon, lower confidence
                        ok = _insert_prediction(
                            db, ticker, direction, None, 365,
                            handle, body, tid, tweet_url, pred_date,
                            prediction_type="position_disclosure",
                            position_action=paction,
                            confidence_tier=0.85,
                        )
                    else:
                        ok = _insert_prediction(
                            db, ticker, direction, target_price, tf_days,
                            handle, body, tid, tweet_url, pred_date,
                        )
                    if ok:
                        total_stats["inserted"] += 1
                        account_preds += 1
                        if is_sector_call:
                            total_stats["sector_call"] = total_stats.get("sector_call", 0) + 1
                            print(f"[X-SCRAPER] @{handle} SECTOR_CALL {direction} ${ticker} ({sector_phrase})", flush=True)
                        elif is_vibes:
                            total_stats["vibes"] = total_stats.get("vibes", 0) + 1
                            print(f"[X-SCRAPER] @{handle} VIBES {direction} ${ticker}", flush=True)
                        elif ptype == "position_disclosure":
                            total_stats["position_open"] = total_stats.get("position_open", 0) + 1
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

    # Summary (Phase 5D — exact format spec)
    rejected_total = sum(rejection_reasons.values())
    reasons_str = ", ".join(f"{k}={v}" for k, v in sorted(rejection_reasons.items(), key=lambda x: -x[1]))
    print(f"[X-SCRAPER] Done: {total_stats['inserted']} inserted, {rejected_total} rejected ({reasons_str or 'none'})", flush=True)
    print(f"[X-SCRAPER] RUN COMPLETE:", flush=True)
    print(f"  Accounts: {total_stats['accounts_scraped']}/{len(accounts)} scraped, {total_stats['blocked_handles']} blocked (news firehose)", flush=True)
    print(f"  Tweets: {total_stats['tweets_fetched']} fetched, {total_stats['prefilter_pass']} passed pre-filter, {total_stats['rejected_empty_body']} empty-body", flush=True)
    print(f"  Groq ({GROQ_MODEL}): {total_stats['ai_sent']} sent, {total_stats['ai_predictions']} accepted ({total_stats['ai_high']} high, {total_stats['ai_medium']} medium)", flush=True)
    print(f"  INSERTED: {total_stats['inserted']} | Dupes: {total_stats['dupes']} | Errors: {total_stats['errors']}", flush=True)
    est_apify = total_stats['tweets_fetched'] * 0.40 / 1000
    # Groq llama-3.3-70b paid-tier pricing (as of 2026-04): $0.59/M input,
    # $0.79/M output. ~3,750 in + ~150 out per call. Free tier = $0.
    est_groq_in = total_stats['ai_sent'] * 3750 * 0.59 / 1_000_000
    est_groq_out = total_stats['ai_sent'] * 150 * 0.79 / 1_000_000
    print(
        f"  Est cost: Apify ~${est_apify:.2f}, Groq ~${est_groq_in + est_groq_out:.4f} "
        f"(FREE on free tier)",
        flush=True,
    )


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
