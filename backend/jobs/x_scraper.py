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
import logging
import httpx
from datetime import datetime, timedelta, timezone
from sqlalchemy import text as sql_text

log = logging.getLogger(__name__)

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

    # Requirement 1: ticker must literally appear in tweet text
    if not _ticker_in_text(ticker, tweet_text):
        return False, "ticker_not_in_text"

    # Requirement 2: must have a direction
    direction = (result.get("direction") or "").lower()
    if direction not in ("bullish", "bearish", "neutral"):
        return False, "no_direction"

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
        # position disclosures / trade actions (Burry/Ackman/Einhorn style)
        'new position', 'initiating long', 'initiating short',
        'added to', 'cut my', 'exited', 'bought ', 'sold ',
        'went long', 'went short', 'loaded up', 'took profit',
        '13f', 'increased stake', 'reduced stake',
    ])
    if not (has_target or has_timeframe or has_explicit_rating or has_strong_action):
        return False, "no_concrete_signal"

    return True, "accepted"


def _classify_with_haiku(tweet_text: str) -> dict | None:
    """Call Claude Haiku to classify a single tweet. Returns parsed dict or None.

    Retries on HTTP 429 (rate limit) with exponential backoff:
      attempt 1: immediate
      attempt 2: wait 2s
      attempt 3: wait 4s
    Returns None on any other error or after retries are exhausted.
    """
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY in ("placeholder", "sk-ant-placeholder"):
        return None

    max_retries = 3
    base_delay = 2.0

    for attempt in range(max_retries):
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
            if r.status_code == 429:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(f"[X-SCRAPER] Haiku 429, backing off {delay}s "
                          f"(attempt {attempt + 1}/{max_retries})", flush=True)
                    time.sleep(delay)
                    continue
                print(f"[X-SCRAPER] Haiku 429 — retries exhausted, dropping tweet", flush=True)
                return None
            if r.status_code != 200:
                return None
            content = r.json().get("content", [{}])[0].get("text", "")
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content)
        except Exception as e:
            msg = str(e).lower()
            if ("429" in msg or "rate_limit" in msg) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"[X-SCRAPER] Haiku exception 429, backing off {delay}s "
                      f"(attempt {attempt + 1}/{max_retries}): {e}", flush=True)
                time.sleep(delay)
                continue
            # Non-429 error or out of retries
            if attempt == 0:
                # Only log the first attempt's error to avoid spam
                print(f"[X-SCRAPER] Haiku error: {e}", flush=True)
            return None
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
    """Quick pre-filter before sending to AI. Returns rejection reason or None if OK.

    Tweets pass if they contain EITHER a ticker-shaped token OR a recognized
    sector phrase (so sector calls like 'semis are going to rip' aren't
    pre-filter rejected before Haiku ever sees them).
    """
    if is_rt:
        return "retweet"
    if len(text.strip()) < 15:
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
            "hr": (haiku_reason or "")[:500] if haiku_reason else None,
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
    }
    # Strict-mode rejection breakdown (Phase 5)
    rejection_reasons: dict[str, int] = {}
    first_tweet_logged = False
    # Debug log cap: print up to 50 haiku_rejected tweets per run for prompt tuning
    haiku_rejected_logged = 0

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

                # Pillar 6: derive prediction_date from tweet ID (snowflake) only.
                # If decoding fails, SKIP the tweet — empty results are better than wrong
                # results. This prevents the year-1900 bug from ever recurring.
                pred_date = tweet_id_to_datetime(tid)
                if not pred_date:
                    print(f"[X-SCRAPER-WARN] no tweet id, skipping (tid={tid!r})", flush=True)
                    rejection_reasons["no_tweet_id"] = rejection_reasons.get("no_tweet_id", 0) + 1
                    log_rejection(db, tweet, handle, "no_tweet_id", None, None)
                    continue

                # Passive discovery
                _record_mentioned_handles(body, tracked_handles, db)

                reason = _prefilter_tweet(body, is_rt)
                if reason:
                    continue

                total_stats["prefilter_pass"] += 1
                total_stats["ai_sent"] += 1

                # Classify with Haiku
                result = _classify_with_haiku(body)
                time.sleep(0.1)  # rate limit Haiku calls (was 0.02s — 0.1s avoids 429 bursts)

                # Phase 5: unified strict validation (matches the Haiku prompt's 3 requirements)
                is_valid, reject_reason = validate_haiku_result(result or {}, body)
                haiku_reason = (result or {}).get("reason", "") if isinstance(result, dict) else ""
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
                    log_rejection(db, tweet, handle, reject_reason, haiku_reason, result, closeness_level)
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
