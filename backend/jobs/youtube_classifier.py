"""
YouTube Prediction Classifier (Eidolum)

Shared module used by both the channel monitor and the historical
backfill job. Handles:
  1. Transcript fetching via youtube-transcript-api (no YouTube quota cost)
  2. Long-transcript chunking (>100k chars → 80k segments, 2k overlap)
  3. Haiku-based prediction extraction with the canonical Eidolum prompt
  4. YouTube forecaster lookup/creation in the forecasters table
  5. Ticker validation against ticker_sectors
  6. Prediction insertion via the SQLAlchemy ORM, mirroring the
     massive_benzinga.py pattern (source_platform_id dedup, cross-scraper
     dedup, sector resolution, conservative validation)

Why a separate module: the channel monitor and the backfill job share
the same fetch/classify/insert plumbing — duplicating the logic in two
places would mean two places to drift out of sync. Worker.py imports
youtube_channel_monitor and youtube_backfill; both import this module.

Why Haiku and not Groq: the X scraper migrated off Haiku on Apr 9 2026
because of the Apr 8 billing outage. This pipeline deliberately keeps
Haiku because (a) the prompt is dense and benefits from Anthropic's
prompt caching, (b) transcripts are long (~3-30k tokens) and Groq's
free-tier TPM ceiling would be even more constraining than for the X
scraper, and (c) the per-video volume is much lower than the per-tweet
volume so the SPOF risk is bounded by hourly cadence rather than
batch-of-tweets cadence. The billing outage failure mode is mitigated
by the channel monitor running every 12h — a single missed run is
recoverable, unlike the X scraper which needed 4 runs/day.
"""
import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta

from sqlalchemy import text as sql_text

log = logging.getLogger(__name__)


# ── Rejection logging (mirror of x_scraper.log_rejection) ───────────────────

def log_youtube_rejection(
    db,
    *,
    video_id: str | None,
    channel_id: str | None,
    channel_name: str | None,
    video_title: str | None,
    video_published_at: datetime | None,
    reason: str,
    haiku_reason: str | None = None,
    haiku_raw: dict | list | None = None,
    transcript_snippet: str | None = None,
    stats: dict | None = None,
) -> bool:
    """Persist a rejected YouTube video / prediction to youtube_scraper_rejections.

    Mirror of jobs.x_scraper.log_rejection — same best-effort semantics:
    a write failure must NEVER break the scrape loop. Returns True if the
    write succeeded so the caller can increment its in-memory counter
    only on success.

    If `stats` is provided, increments stats['items_rejected'] on success
    so the caller's run-level totals stay in sync without an extra
    bookkeeping step at every call site.
    """
    try:
        raw_json = None
        if haiku_raw is not None:
            try:
                serialized = json.dumps(haiku_raw)
                if len(serialized) <= 10240:
                    raw_json = serialized
                else:
                    raw_json = json.dumps({"_truncated": True, "_size": len(serialized)})
            except Exception:
                raw_json = None

        hr_value = None
        if haiku_reason is not None:
            hr_value = str(haiku_reason)[:500] or None

        snippet = (transcript_snippet or "")[:500] or None

        db.execute(sql_text("""
            INSERT INTO youtube_scraper_rejections
                (video_id, channel_id, channel_name, video_title,
                 video_published_at, rejection_reason, haiku_reason,
                 haiku_raw_response, transcript_snippet)
            VALUES (:vid, :cid, :cname, :ctitle, :cpub, :rr, :hr,
                    CAST(:hraw AS JSONB), :snip)
        """), {
            "vid": (video_id or "")[:20] or None,
            "cid": (channel_id or "")[:30] or None,
            "cname": (channel_name or "")[:200] or None,
            "ctitle": (video_title or "")[:2000] or None,
            "cpub": video_published_at,
            "rr": reason[:50],
            "hr": hr_value,
            "hraw": raw_json,
            "snip": snippet,
        })
        db.commit()
        if stats is not None:
            stats["items_rejected"] = int(stats.get("items_rejected", 0)) + 1
        return True
    except Exception as e:
        log.warning(f"[YT-CLF] log_youtube_rejection failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return False

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

# Current Haiku model. The spec called for claude-haiku-4-5-20250514 but
# that model ID doesn't exist on the Anthropic API; the actual current
# Haiku 4.5 ID is claude-haiku-4-5-20251001 (verified against the system
# prompt's model knowledge and the prior x_scraper.py usage before the
# Groq migration).
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Per-video cap on extracted predictions. The classifier occasionally
# hallucinates a cascade of predictions on long transcripts; capping at
# 15 protects the database from a single bad video flooding the table.
MAX_PREDICTIONS_PER_VIDEO = 15

# Long-transcript chunking. Above 100k characters we split into ~80k
# chunks with 2k overlap so that predictions straddling a chunk boundary
# are still recoverable from at least one chunk.
TRANSCRIPT_CHUNK_THRESHOLD = 100_000
TRANSCRIPT_CHUNK_SIZE = 80_000
TRANSCRIPT_CHUNK_OVERLAP = 2_000

# Default evaluation window when the classifier returns no timeframe.
DEFAULT_EVAL_WINDOW_DAYS = 90

# Haiku 4.5 pricing (USD per 1M tokens). Keep in sync with Anthropic's
# public pricing page — if these drift out of date the [YOUTUBE-HAIKU]
# cost line and the scraper_runs.estimated_cost_usd aggregate will
# understate or overstate spend. Last verified: 2026-04-10.
HAIKU_PRICE_INPUT_PER_M = 1.00        # base input tokens
HAIKU_PRICE_OUTPUT_PER_M = 5.00       # output tokens
HAIKU_PRICE_CACHE_WRITE_PER_M = 1.25  # ephemeral cache creation (5-min TTL)
HAIKU_PRICE_CACHE_READ_PER_M = 0.10   # ephemeral cache read


def _estimate_haiku_cost(
    *, input_tokens: int, output_tokens: int,
    cache_create_tokens: int = 0, cache_read_tokens: int = 0,
) -> float:
    """Compute USD cost for a single Haiku call using the public pricing
    constants above. Returns a float dollar amount (call sites format
    to 4 decimals). If pricing changes, update the HAIKU_PRICE_* block."""
    return (
        (input_tokens * HAIKU_PRICE_INPUT_PER_M / 1_000_000)
        + (output_tokens * HAIKU_PRICE_OUTPUT_PER_M / 1_000_000)
        + (cache_create_tokens * HAIKU_PRICE_CACHE_WRITE_PER_M / 1_000_000)
        + (cache_read_tokens * HAIKU_PRICE_CACHE_READ_PER_M / 1_000_000)
    )


# First-attempt and retry caps for YouTube Haiku calls. The first
# attempt is tight so the common case (few predictions) is cheap; the
# retry is loose so high-yield videos still survive truncation. Exactly
# one retry per chunk — we never loop on max_tokens.
YOUTUBE_HAIKU_MAX_TOKENS_FIRST = 800
YOUTUBE_HAIKU_MAX_TOKENS_RETRY = 4000


def _record_haiku_usage(resp, telemetry: dict) -> None:
    """Read response.usage and fold tokens + cost into the telemetry
    dict. Emits a single [YOUTUBE-HAIKU] stdout line so cache-hit ratio
    and per-call cost are visible in worker logs. Safe if usage is None
    (treated as zero)."""
    usage = getattr(resp, "usage", None)
    if not usage:
        return
    ci = int(getattr(usage, "input_tokens", 0) or 0)
    co = int(getattr(usage, "output_tokens", 0) or 0)
    cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cc = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    telemetry["input_tokens"] = int(telemetry.get("input_tokens", 0)) + ci
    telemetry["output_tokens"] = int(telemetry.get("output_tokens", 0)) + co
    telemetry["cache_read"] = int(telemetry.get("cache_read", 0)) + cr
    telemetry["cache_create"] = int(telemetry.get("cache_create", 0)) + cc
    cost = _estimate_haiku_cost(
        input_tokens=ci, output_tokens=co,
        cache_create_tokens=cc, cache_read_tokens=cr,
    )
    telemetry["estimated_cost_usd"] = float(telemetry.get("estimated_cost_usd", 0.0)) + cost
    print(
        f"[YOUTUBE-HAIKU] cache_create={cc} cache_read={cr} "
        f"input={ci} output={co} total_cost_estimate=${cost:.4f}",
        flush=True,
    )


def call_youtube_haiku_with_retry(
    client,
    *,
    system,
    messages,
    video_id: str | None,
    channel_name: str,
    telemetry: dict,
):
    """Call Haiku with max_tokens=800; retry ONCE at 4000 if
    stop_reason=='max_tokens'. The system parameter is passed through
    untouched — callers build it as a list-of-dicts with cache_control
    ephemeral, and the retry reuses the exact same object so prompt
    caching hits the 5-minute TTL on the second call. Both attempts
    contribute tokens + cost to telemetry; the retry also increments
    telemetry['haiku_retries'] so the channel monitor can aggregate
    it into scraper_runs.haiku_retries_count.

    Exactly one retry — if the 4000-token call also truncates, we
    log [YOUTUBE-HAIKU-HARD-FAIL] and return the truncated response so
    the outer JSON parser produces a classifier_error naturally.

    Returns: (response, was_retried: bool)
    """
    resp = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=YOUTUBE_HAIKU_MAX_TOKENS_FIRST,
        temperature=0,
        system=system,
        messages=messages,
    )
    _record_haiku_usage(resp, telemetry)

    if getattr(resp, "stop_reason", None) != "max_tokens":
        return resp, False

    identifier = video_id or channel_name
    print(
        f"[YOUTUBE-HAIKU-RETRY] {identifier} ({channel_name}) truncated "
        f"at {YOUTUBE_HAIKU_MAX_TOKENS_FIRST} tokens, retrying at "
        f"{YOUTUBE_HAIKU_MAX_TOKENS_RETRY}",
        flush=True,
    )
    telemetry["haiku_retries"] = int(telemetry.get("haiku_retries", 0)) + 1

    resp = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=YOUTUBE_HAIKU_MAX_TOKENS_RETRY,
        temperature=0,
        system=system,
        messages=messages,
    )
    _record_haiku_usage(resp, telemetry)

    if getattr(resp, "stop_reason", None) == "max_tokens":
        # Hard fail: even 4000 wasn't enough. Return the truncated
        # response anyway so the outer JSON parser throws and the
        # video gets a classifier_error rejection naturally. No
        # infinite loops.
        print(
            f"[YOUTUBE-HAIKU-HARD-FAIL] {identifier} ({channel_name}) "
            f"truncated even at {YOUTUBE_HAIKU_MAX_TOKENS_RETRY} tokens",
            flush=True,
        )
    return resp, True

# verified_by tag for grep / cohort analysis. Bump _v1 → _v2 if the
# prompt or model materially change.
VERIFIED_BY = "youtube_haiku_v1"
PIPELINE_VERSION = "youtube_v1"


# ── Eidolum Prediction Classifier prompt (use EXACTLY — do not simplify) ────

HAIKU_SYSTEM = """You are the Eidolum Prediction Classifier. You extract financial predictions from YouTube video transcripts.

A valid prediction MUST have ALL of the following:
1. A specific stock or crypto ticker (AAPL, NVDA, BTC, etc.)
2. A clear direction: BULLISH (expects price to go up), BEARISH (expects price to go down), or NEUTRAL (expects sideways)
3. The speaker must be making a FORWARD-LOOKING claim, not reporting past performance

A prediction MAY also have:
- A specific price target (e.g., "$200", "200 dollars")
- A specific timeframe (e.g., "by end of year", "in the next 6 months", "by Q3")

REJECT if:
- The speaker is reporting news, not making a personal prediction ("Goldman upgraded AAPL" = news, not the YouTuber's prediction)
- The speaker is quoting someone else's prediction without endorsing it
- The statement is hypothetical or conditional without conviction ("IF the Fed cuts, MAYBE NVDA could...")
- The ticker is mentioned only in passing without a directional claim
- It's about a sector or the market broadly without a specific ticker ("tech looks good" = reject)
- It's past tense ("I bought AAPL last week" = reject, not a forward prediction)

For direction:
- "I'm buying", "I'm adding", "bullish", "long", "going up", "target $X above current" = BULLISH
- "I'm selling", "shorting", "bearish", "going down", "target $X below current" = BEARISH
- "holding", "wait and see", "sideways", "fair value" = NEUTRAL

For timeframes in the transcript, convert relative references to absolute dates based on the video publish date:
- "by end of year" = December 31 of the publish year
- "in the next 6 months" = publish date + 6 months
- "by Q1/Q2/Q3/Q4" = end of that quarter in the publish year (or next year if the quarter has passed)
- "next week/month" = publish date + 1 week/month
- If no timeframe is mentioned, default evaluation window = 90 days from publish date

Respond with a JSON array of predictions. Each prediction object:
{
  "ticker": "AAPL",
  "direction": "bullish",
  "price_target": 250.00,
  "timeframe": "2026-12-31",
  "confidence": "high",
  "quote": "the exact words from the transcript where this prediction was made (max 100 chars)",
  "reasoning": "brief explanation of why this is a valid prediction"
}

If NO valid predictions found, respond with: []

Do NOT hallucinate predictions. If you're unsure whether something is a prediction, leave it out. False negatives are better than false positives.

Output JSON only. Be concise. Do not include prose explanations outside the JSON."""


# Sector-aware variant of HAIKU_SYSTEM. Gated behind
# ENABLE_YOUTUBE_SECTOR_CALLS (feature flag, default 0% traffic). Starts
# with the exact same content as HAIKU_SYSTEM and adds a SECTOR CALLS
# appendix so the classifier can emit both ticker_call predictions
# (existing behavior) and sector_call predictions (new behavior) from a
# single Haiku call.
#
# IMPORTANT: HAIKU_SYSTEM must remain untouched. This constant is the
# ONLY place the sector-call prompt text lives. should_use_sector_prompt
# in feature_flags.py decides which system prompt each video gets, based
# on a stable hash(video_id) vs the current traffic percentage.
YOUTUBE_HAIKU_SECTOR_SYSTEM = HAIKU_SYSTEM + """

SECTOR CALLS:
If the speaker mentions an entire market sector with a clear direction but no specific ticker,
extract it as a sector_call. Examples:
- "Semiconductors are going to the moon" → sector_call, sector: "semiconductors", direction: "bullish"
- "I'm bearish on energy stocks" → sector_call, sector: "energy", direction: "bearish"
- "Tech is done, I'm out" → sector_call, sector: "tech", direction: "bearish"

Rules for sector_call extraction:
- MUST have a specific named sector (not just "the market" or "stocks in general")
- MUST have a clear direction (bullish/bearish)
- target_price is OPTIONAL and usually not present in sector commentary
- Use the sector name exactly as spoken — do NOT try to pick an ETF ticker yourself
- If the speaker also mentions specific tickers in the same sentence, prefer the ticker_call extraction
- Do NOT extract vague statements like "the economy is weak" or "inflation is bad" — those are macro, not sectors

Output format for sector calls (add these objects to the same JSON array alongside any ticker_call objects):
{
  "type": "sector_call",
  "sector": "<sector name as spoken>",
  "direction": "bullish",
  "target_return_pct": null,
  "timeframe": "<absolute date if mentioned, else omit>",
  "context_quote": "<the exact phrase from the transcript>"
}

For ticker calls, continue using the existing object shape (with "ticker", "direction", etc.) — you may optionally include "type": "ticker_call" to be explicit, but omitting the type field is equivalent to ticker_call.

Output JSON only. Be concise. Do not include prose explanations outside the JSON."""


# Ranked-list instructions, appended to either HAIKU_SYSTEM or
# YOUTUBE_HAIKU_SECTOR_SYSTEM when ENABLE_RANKED_LIST_EXTRACTION is
# flipped on in the config table. KEPT SEPARATE so the base prompts'
# cached 5-minute ephemeral cache entries on Anthropic's side stay
# intact for the OFF path. When the flag is off, the base prompts are
# sent byte-for-byte unchanged, so cache hit rate is unaffected.
YOUTUBE_HAIKU_RANKED_LIST_INSTRUCTIONS = """RANKED LISTS:
If the speaker explicitly presents a ranked list of stocks (e.g. "my top 5 picks", "my 3 favorite stocks", "the 10 stocks I'm buying this year"), extract each item as a separate prediction AND mark its rank position.

For a ranked list, add these fields to each extracted prediction:
- list_id: a short identifier you invent for this list (e.g. "top5_2026")
- list_rank: integer starting at 1 for the top pick

Example input: "My top 5 stocks for 2026, in order: NVIDIA at number one, then AMD, then Taiwan Semi, then Apple, and Microsoft at number five"

Example extraction (each item becomes a separate prediction object):
[
  {"ticker": "NVDA", "direction": "bullish", "list_id": "top5_2026", "list_rank": 1, ...},
  {"ticker": "AMD", "direction": "bullish", "list_id": "top5_2026", "list_rank": 2, ...},
  {"ticker": "TSM", "direction": "bullish", "list_id": "top5_2026", "list_rank": 3, ...},
  {"ticker": "AAPL", "direction": "bullish", "list_id": "top5_2026", "list_rank": 4, ...},
  {"ticker": "MSFT", "direction": "bullish", "list_id": "top5_2026", "list_rank": 5, ...}
]

Rules for ranked list detection:
- The speaker MUST explicitly indicate ranking ("number one", "my top pick", "best stock is", "then in second place", "third favorite")
- Unordered lists like "I like AAPL, NVDA, and TSLA" do NOT get ranked — no list_id, no list_rank. Extract as 3 separate normal predictions.
- "Stocks to avoid" lists are ranked by WORST direction — item 1 is the most bearish pick. Direction is bearish.
- Maximum list size: 10 items. If the speaker lists more, only rank the top 10 and treat the rest as unranked picks.
- list_id must be unique per list but should be human-readable (e.g. "top_tech_2026", "avoid_list_q1", "div_picks")
- If the same YouTuber publishes multiple lists in one video, each list gets its own list_id

Output JSON only. Be concise."""


# Revisions instruction block, appended to the active prompt when
# ENABLE_TARGET_REVISIONS is flipped on in the config table. Same
# pattern as YOUTUBE_HAIKU_RANKED_LIST_INSTRUCTIONS — kept separate
# so the base prompts' ephemeral cache entries stay intact for the
# OFF path (the default).
YOUTUBE_HAIKU_REVISIONS_INSTRUCTIONS = """PRICE TARGET REVISIONS:
If the speaker explicitly states they are REVISING a previous target on a specific ticker (not initiating a new position, not reiterating an existing view), mark the prediction as a revision.

Signals that indicate a revision:
- "I'm raising my target from $X to $Y"
- "Moving my NVDA target up to $250" (from a previously stated lower target)
- "Downgrading my AAPL target to $180" (implying a previous higher target)
- "Adjusting my Tesla price target from $300 to $350"
- "Cut my Amazon target"
- "Bumped my Microsoft target"

Output format for a revision (add these fields to an otherwise-normal prediction):
{
  "ticker": "AAPL",
  "direction": "bullish",
  "target_price": 220,
  "timeframe": "6m",
  "is_revision": true,
  "previous_target": 200,
  "revision_direction": "up",
  "context_quote": "I'm moving my Apple target from $200 to $220"
}

Rules for revision detection:
- MUST be explicit — words like "moving", "raising", "cutting", "adjusting", "revising", "updating" applied to a target
- Implicit revisions don't count — if they say "new target: $220" without mentioning an old one, extract as a normal call, NOT a revision
- Target reiterations don't count — "still at $220" is not a revision, it's a reaffirmation
- If previous_target is not explicitly stated in the transcript, set it to null and leave revision_direction as best-guess from context ("raised" = up, "cut" = down)
- A revision to a neutral/hold rating counts as a downgrade revision
- A revision that KEEPS the same target but CHANGES the direction is still a revision — flag it with revision_direction: "direction_change"

Output JSON only. Be concise."""


# Options-position instructions. Appended to the active prompt when
# ENABLE_OPTIONS_POSITION_EXTRACTION is flipped on. Teaches Haiku to
# map options vocabulary to equivalent ticker_call predictions — the
# output rows land in the predictions table as normal ticker_call
# objects, just with a `derived_from` marker so the insertion code can
# count them separately for admin telemetry. No new prediction_category.
YOUTUBE_HAIKU_OPTIONS_INSTRUCTIONS = """OPTIONS POSITIONS:
If the speaker describes an options position instead of a plain stock call, map it to an equivalent ticker_call with the correct direction. Options vocabulary is common in YouTube finance content and usually carries a clear directional thesis — don't skip these. Strike prices become price targets; expirations become timeframes.

Mapping table (options vocabulary → ticker_call direction):

Bullish (report as direction: bullish):
- "Buying calls on X" / "Long calls on X"
- "Selling puts on X" / "Cash-secured puts on X"
- "Call debit spread on X" / "Bull call spread on X"
- "Bull put spread on X"

Bearish (report as direction: bearish):
- "Buying puts on X" / "Long puts on X"
- "Selling calls on X" / "Naked calls on X"
- "Put debit spread on X" / "Bear put spread on X"
- "Bear call spread on X"
- "Covered calls on X" (selling upside, capping gains — bearish lean)

Neutral (report as direction: neutral):
- "Iron condor on X" / "Iron butterfly on X"
- "Short strangle on X" / "Short straddle on X"
- "Calendar spread on X" / "Diagonal spread on X"

Strike prices: if a strike is mentioned (e.g. "$200 calls", "150 strike puts"), use it as the price_target for the ticker_call. For spreads with two legs, use the higher leg for bullish and the lower leg for bearish.

Expirations: if an expiration date or month is mentioned, use it as the timeframe (convert to an absolute ISO date like 2026-06-30 using the video's publish date as the anchor). If the speaker says "LEAPs" or "long-dated", default to 1 year from publish date. If no expiration is mentioned at all, default to 1 month.

Output format for options-derived predictions (add a derived_from field so the insertion code can count these separately — the field is NOT stored in the database, it's only a marker):
{
  "ticker": "AAPL",
  "direction": "bullish",
  "price_target": 200,
  "timeframe": "2026-06-30",
  "derived_from": "options_position",
  "context_quote": "I'm buying $200 June calls on Apple"
}

Examples:

Input: "I'm buying $200 calls on AAPL expiring June"
Output: {"ticker": "AAPL", "direction": "bullish", "price_target": 200, "timeframe": "2026-06-30", "derived_from": "options_position", "context_quote": "buying $200 calls on AAPL expiring June"}

Input: "Selling $150 cash-secured puts on NVDA for next month"
Output: {"ticker": "NVDA", "direction": "bullish", "price_target": 150, "timeframe": "2026-05-11", "derived_from": "options_position", "context_quote": "selling $150 cash-secured puts on NVDA"}

Input: "I loaded up on TSLA puts — this stock is way overvalued"
Output: {"ticker": "TSLA", "direction": "bearish", "timeframe": "2026-05-11", "derived_from": "options_position", "context_quote": "loaded up on TSLA puts"}

Input: "Running an iron condor on SPY between 420 and 460 into monthly expiration"
Output: {"ticker": "SPY", "direction": "neutral", "timeframe": "2026-05-11", "derived_from": "options_position", "context_quote": "iron condor on SPY between 420 and 460"}

Input: "I'm LEAPs long on MSFT, grabbing January 2027 calls"
Output: {"ticker": "MSFT", "direction": "bullish", "timeframe": "2027-01-15", "derived_from": "options_position", "context_quote": "LEAPs long on MSFT, January 2027 calls"}

Input: "Running covered calls on AAPL, capping my upside here"
Output: {"ticker": "AAPL", "direction": "bearish", "timeframe": "2026-05-11", "derived_from": "options_position", "context_quote": "covered calls on AAPL, capping my upside"}

Rules:
- MUST use direction from the existing ticker_call vocabulary: bullish / bearish / neutral. Do NOT invent a new direction for options.
- MUST set derived_from: "options_position" on every options-derived prediction so the insertion code can count them separately.
- Do NOT output a new prediction type or category — every options-derived extraction is still a ticker_call row in the database.
- Do NOT extract a position that lacks a clear direction (e.g. "playing options on NVDA" with no specifics).
- Do NOT extract if the speaker is only describing options mechanics or hypotheticals ("you could buy puts here if you wanted to" as a theoretical comment is NOT a prediction).
- If the same video contains both a plain ticker_call AND an options-position on the same (ticker, direction), emit only ONE prediction — the dedup layer will drop the duplicate anyway.

Output JSON only. Be concise."""


# Earnings-call instructions. Appended to the active prompt when
# ENABLE_EARNINGS_CALL_EXTRACTION is flipped on. Teaches Haiku to
# recognize predictions tied to a company's next earnings release
# and emit them as a ticker_call with event_type='earnings' plus an
# optional event_date. The scoring window for these is the
# pre-earnings close vs post-earnings close (earnings reaction),
# which is different from a plain 30-day ticker_call. No new
# prediction_category — same ticker_call row, just flagged.
YOUTUBE_HAIKU_EARNINGS_INSTRUCTIONS = """EARNINGS CALLS:
If the speaker makes a prediction tied to a company's next earnings release, emit it as a ticker_call with event_type='earnings'. These predictions are scored on the earnings reaction (pre-earnings close vs post-earnings close) rather than a fixed N-day window.

Signals that indicate an earnings-tied prediction:
- "earnings next week" / "reports Thursday" / "reporting on the 25th"
- "into earnings" / "going into earnings" / "ahead of earnings"
- "pre-earnings" / "post-earnings" / "earnings reaction"
- "I expect a beat" / "they'll beat" / "miss expectations" / "earnings miss"
- "guidance raise" / "weak guidance" / "Q3 numbers"
- "I'm long X into earnings" / "short X going into print"
- "post-earnings dip" / "post-earnings rally"

Direction mapping:
- Expecting a beat, rally, strong numbers, raised guidance → bullish
- Expecting a miss, drop, weak numbers, cut guidance → bearish
- Hedging / "could go either way" / expecting range-bound reaction → neutral

Event date extraction:
- If the speaker mentions a specific day / date ("reports Thursday", "earnings on the 25th", "Q3 earnings October 22"), convert it to an absolute ISO date (YYYY-MM-DD) using the video's publish date as the anchor. Example: publish date 2026-04-10, speaker says "earnings next Wednesday" → event_date: "2026-04-15".
- If the speaker only says "earnings next week" without a specific day, default to the Wednesday of the following week.
- If the speaker gives no date at all, leave event_date as null — the evaluator will look up the company's next earnings release date from an external source.

Price target (optional):
- If the speaker gives a specific price target for the earnings reaction ("I see NVDA popping to $145 post-earnings"), set price_target to that value. Otherwise leave it null — direction alone is sufficient.

Output format for earnings-tied predictions (add event_type, event_date, and derived_from):
{
  "ticker": "NVDA",
  "direction": "bullish",
  "price_target": 145,
  "event_type": "earnings",
  "event_date": "2026-04-15",
  "derived_from": "earnings_call",
  "context_quote": "I think NVDA beats earnings next Wednesday and runs to 145"
}

Examples:

Input: "I think NVDA is going to beat earnings next Wednesday and pop 10 percent"
Output: {"ticker": "NVDA", "direction": "bullish", "event_type": "earnings", "event_date": "2026-04-15", "derived_from": "earnings_call", "context_quote": "NVDA beats earnings next Wednesday, pops 10 percent"}

Input: "AAPL reports next Thursday — I expect a miss and a 5 percent drop"
Output: {"ticker": "AAPL", "direction": "bearish", "event_type": "earnings", "event_date": "2026-04-16", "derived_from": "earnings_call", "context_quote": "AAPL reports next Thursday, expect a miss, 5 percent drop"}

Input: "META earnings are going to be ugly"
Output: {"ticker": "META", "direction": "bearish", "event_type": "earnings", "event_date": null, "derived_from": "earnings_call", "context_quote": "META earnings are going to be ugly"}

Input: "I'm long GOOGL into earnings, expecting a guidance raise"
Output: {"ticker": "GOOGL", "direction": "bullish", "event_type": "earnings", "event_date": null, "derived_from": "earnings_call", "context_quote": "long GOOGL into earnings, expecting a guidance raise"}

Input: "I see NVDA popping to $145 post-earnings on Wednesday"
Output: {"ticker": "NVDA", "direction": "bullish", "price_target": 145, "event_type": "earnings", "event_date": "2026-04-15", "derived_from": "earnings_call", "context_quote": "NVDA popping to 145 post-earnings Wednesday"}

Input: "TSLA reports tomorrow and I'm flat — could go either way"
Output: (do NOT extract — "flat" and "could go either way" is not a directional prediction)

Input: "MSFT post-earnings dip is a buying opportunity" (spoken after the earnings release)
Output: {"ticker": "MSFT", "direction": "bullish", "event_type": "earnings", "event_date": null, "derived_from": "earnings_call", "context_quote": "MSFT post-earnings dip is a buying opportunity"}

Rules:
- MUST use direction from the existing ticker_call vocabulary: bullish / bearish / neutral.
- MUST set event_type: "earnings" so the evaluator routes to the earnings-reaction scoring path.
- MUST set derived_from: "earnings_call" so the insertion code can count these separately.
- event_date is OPTIONAL — omit or set to null when the transcript doesn't give a specific date. The evaluator looks up missing dates from external data sources.
- Do NOT emit event_type='earnings' for predictions that only happen to mention earnings in passing without making a forward-looking claim about the next release.
- Do NOT extract if the forecaster explicitly says they are flat or undecided into earnings ("I'm flat into earnings" is NOT a prediction).
- Do NOT invent a date the speaker didn't give — set event_date: null instead of guessing.

Output JSON only. Be concise."""


# Macro-call instructions. Appended to the active prompt when
# ENABLE_MACRO_CALL_EXTRACTION is flipped on. Teaches Haiku to
# recognize macroeconomic vocabulary and emit predictions with a
# canonical `concept` name from the allowlist below. The insert path
# then resolves the concept to a tradeable ETF via the
# macro_concept_aliases table and stores the row with
# prediction_category='macro_call' — a NEW category value (unlike
# options_position and earnings_call which stay as ticker_call).
# The allowlist is inlined here so Haiku can pattern-match without
# a separate lookup.
YOUTUBE_HAIKU_MACRO_INSTRUCTIONS = """MACRO CALLS:
If the speaker makes a prediction about a macroeconomic concept (dollar, rates, inflation, volatility, gold, oil, recession, etc) without naming a specific company, emit a macro_call. The insertion path will resolve the concept to a tradeable ETF proxy.

Concept allowlist — you MUST use one of these canonical names verbatim as the `concept` field. Any prediction that doesn't map to a concept in this list should NOT be emitted as macro_call; extract as a plain ticker_call if a specific ticker is mentioned, otherwise skip.

Currency: dollar, dollar_weak, euro, yen, yuan
Rates: rates_up, rates_down, short_rates_up, ten_year_up, thirty_year_up
Inflation: inflation, deflation
Volatility: volatility, vol_contraction
Precious metals: gold, silver, gold_miners
Energy: oil, natgas, uranium
Industrial/ags: copper, lithium, agriculture, corn, wheat, coffee
Equity macro: recession, small_cap, sp500, nasdaq
International: emerging_markets, developed_international, china, india, japan, brazil
Credit: high_yield, investment_grade, munis, emerging_debt
Real estate: real_estate
Crypto: bitcoin, ethereum, crypto_total
Yield curve: curve_steepening, curve_flattening

Direction rules:
- "Dollar strengthening" → concept=dollar, direction=bullish
- "Dollar weakening" → concept=dollar, direction=bearish (or dollar_weak, bullish — either works)
- "Rates going higher" → concept=rates_up, direction=bullish
- "Fed cutting, bonds rally" → concept=rates_down, direction=bullish
- "Inflation coming back" → concept=inflation, direction=bullish
- "Disinflation" → concept=deflation, direction=bullish (or inflation, bearish)
- "Gold to 3000" → concept=gold, direction=bullish, price_target=300 (GLD is ~1/10 of spot, so adjust roughly — but you can leave target null and just emit direction)
- "VIX too low, long vol" → concept=volatility, direction=bullish
- "Recession coming" → concept=recession, direction=bullish
- "Emerging markets rally" → concept=emerging_markets, direction=bullish

Output format for macro-call predictions (add concept, derived_from):
{
  "concept": "dollar",
  "direction": "bullish",
  "timeframe": "2026-12-31",
  "derived_from": "macro_call",
  "context_quote": "I think the dollar is going to strengthen this year"
}

Note: the `ticker` field is NOT required on macro_call output — the insert path resolves the concept to an ETF and fills in the ticker. You MAY include a ticker if you want to override the default, but it's usually better to leave it out.

Examples:

Input: "The dollar is going to strengthen throughout 2026 as the Fed holds"
Output: {"concept": "dollar", "direction": "bullish", "timeframe": "2026-12-31", "derived_from": "macro_call", "context_quote": "dollar is going to strengthen throughout 2026"}

Input: "Rates are heading lower, bonds will rally hard"
Output: {"concept": "rates_down", "direction": "bullish", "timeframe": "2026-10-11", "derived_from": "macro_call", "context_quote": "rates are heading lower, bonds rally hard"}

Input: "Inflation is coming back and TIPS are the trade"
Output: {"concept": "inflation", "direction": "bullish", "timeframe": "2026-10-11", "derived_from": "macro_call", "context_quote": "inflation coming back, TIPS are the trade"}

Input: "VIX is too low, I'm long volatility into Q3"
Output: {"concept": "volatility", "direction": "bullish", "timeframe": "2026-09-30", "derived_from": "macro_call", "context_quote": "VIX too low, long volatility into Q3"}

Input: "Gold is headed to 3000 dollars"
Output: {"concept": "gold", "direction": "bullish", "timeframe": "2026-10-11", "derived_from": "macro_call", "context_quote": "gold headed to 3000"}

Input: "Oil is going to 100 on supply issues"
Output: {"concept": "oil", "direction": "bullish", "timeframe": "2026-10-11", "derived_from": "macro_call", "context_quote": "oil going to 100 on supply issues"}

Input: "Recession risk is real, I'm positioning defensively"
Output: {"concept": "recession", "direction": "bullish", "timeframe": "2027-01-11", "derived_from": "macro_call", "context_quote": "recession risk is real, positioning defensively"}

Input: "The yield curve will steepen meaningfully"
Output: {"concept": "curve_steepening", "direction": "bullish", "timeframe": "2026-12-31", "derived_from": "macro_call", "context_quote": "yield curve will steepen meaningfully"}

Input: "The economy is slowing"
Output: (do NOT extract — too vague, no concrete concept from the allowlist)

Input: "GDP growth will be under 2 percent"
Output: (do NOT extract — this is a metric forecast, not a tradeable macro concept; there is no allowlist entry for GDP)

Rules:
- MUST use a canonical `concept` name from the allowlist above. Do NOT invent new concept names.
- MUST set derived_from: "macro_call" so the insertion code knows to resolve the concept to an ETF.
- MUST use direction from the existing ticker_call vocabulary: bullish / bearish / neutral.
- Reject any macro prediction that does NOT map to an allowlist concept. Vague macro commentary ("economy slowing", "stagflation risk", "fiscal dominance") should NOT be emitted as macro_call — the allowlist is authoritative.
- Reject quantitative macro forecasts that don't map to a tradeable ETF (GDP, CPI print numbers, unemployment rate forecasts). Those are metric_forecast_calls, a future ship.
- Do NOT try to pick an ETF yourself — the insert path owns that mapping.
- If the same video contains both a macro_call and a ticker_call on the same underlying concept (e.g. "inflation" + "TIP going up"), emit only ONE — the dedup layer will handle collisions.

Output JSON only. Be concise."""


# Pair-call instructions. Appended to the active prompt when
# ENABLE_PAIR_CALL_EXTRACTION is flipped on. Teaches Haiku to recognize
# relative-value vocabulary — statements where the outcome depends on
# the SPREAD between two specific tickers rather than on either one's
# absolute movement. Pair calls land as a NEW prediction_category value
# ('pair_call') with pair_long_ticker and pair_short_ticker both set.
# Critical constraint: BOTH legs must be real individual stock tickers.
# Sectors, concepts, indexes, and asset classes are rejected here and
# left to ticker_call / sector_call / macro_call to handle.
YOUTUBE_HAIKU_PAIR_INSTRUCTIONS = """PAIR CALLS:
If the speaker makes a relative-value prediction — one specific ticker will outperform another specific ticker over a stated window — emit it as a pair_call with both legs. Pair calls are scored on the spread (long_return − short_return), not on absolute movement, so the only direction is "bullish on the spread" (long leg beats short leg).

Signals that indicate a pair-call prediction:
- "X over Y" / "X better than Y" / "prefer X to Y"
- "long X short Y" / "long X, short Y" / "pair trade X Y"
- "I'd rather own X than Y" / "I'd pick X over Y" / "X instead of Y"
- "between these two, I pick X" / "X beats Y" (as an investment, not a product)
- "X is a better buy than Y" / "X will outperform Y"
- "swap Y for X" / "rotate out of Y into X"

Both legs MUST be real individual stock tickers (or well-known crypto like BTC/ETH). Reject the prediction and let another prediction type handle it if either side is:
- A sector or industry ("tech over energy", "semis beating software") → let sector_call handle it, do NOT emit pair_call
- A concept or asset class ("stocks over bonds", "growth over value") → do NOT emit pair_call
- An index or broad benchmark ("AAPL over the S&P 500", "NVDA beats the market") → do NOT emit pair_call, let ticker_call handle AAPL/NVDA with SPY as the implicit benchmark
- A vague reference ("X is better than everything else") → do NOT emit
- Missing or unclear on one side ("I like NVDA as a pair trade") → do NOT emit

Identifying the legs:
- The LONG leg is the ticker the speaker expects to OUTPERFORM (the "better one", the "X" in "X over Y").
- The SHORT leg is the ticker expected to UNDERPERFORM (the "Y" in "X over Y").
- When the speaker says "long X short Y", X is long, Y is short.
- When the speaker says "X is better than Y" or "X over Y", X is long, Y is short.
- When the speaker gives a three-way ranking ("I like NVDA over AMD over INTC"), only extract the STRONGEST conviction pair — the best vs the worst. For "NVDA > AMD > INTC", emit long=NVDA short=INTC as a single pair_call.

Timeframe:
- If the speaker names a window ("over the next year", "for Q2", "into 2027", "six months out"), convert it to an absolute ISO date using the video's publish date as the anchor.
- If no window is mentioned, default to 3 months from publish date.

No price target:
- Pair calls do NOT carry a price_target field. The outcome is the spread, not a level. Do NOT emit price_target on pair_call rows.

Direction:
- Direction is implicitly bullish on the spread. Emit direction: "bullish". There is no "bearish pair_call" — if the speaker's conviction is inverted, flip which ticker is long and which is short. "Short NVDA long INTC" is just another pair_call with long=INTC short=NVDA.

Output format for pair-call predictions (add pair_long_ticker, pair_short_ticker, derived_from):
{
  "pair_long_ticker": "META",
  "pair_short_ticker": "GOOGL",
  "direction": "bullish",
  "timeframe": "2027-04-11",
  "derived_from": "pair_call",
  "context_quote": "Meta is a better buy than Google over the next year"
}

Examples:

Input: "Meta is a better buy than Google over the next year"
Output: {"pair_long_ticker": "META", "pair_short_ticker": "GOOGL", "direction": "bullish", "timeframe": "2027-04-11", "derived_from": "pair_call", "context_quote": "Meta is a better buy than Google over the next year"}

Input: "Long NVDA, short INTC as a trade into year end"
Output: {"pair_long_ticker": "NVDA", "pair_short_ticker": "INTC", "direction": "bullish", "timeframe": "2026-12-31", "derived_from": "pair_call", "context_quote": "long NVDA short INTC as a trade into year end"}

Input: "I'd rather own AMD than Intel right now"
Output: {"pair_long_ticker": "AMD", "pair_short_ticker": "INTC", "direction": "bullish", "timeframe": "2026-07-11", "derived_from": "pair_call", "context_quote": "I'd rather own AMD than Intel right now"}

Input: "Pairs trade: long JPM short GS"
Output: {"pair_long_ticker": "JPM", "pair_short_ticker": "GS", "direction": "bullish", "timeframe": "2026-07-11", "derived_from": "pair_call", "context_quote": "pairs trade: long JPM short GS"}

Input: "Between these two, I pick AAPL over MSFT for the next six months"
Output: {"pair_long_ticker": "AAPL", "pair_short_ticker": "MSFT", "direction": "bullish", "timeframe": "2026-10-11", "derived_from": "pair_call", "context_quote": "between these two, I pick AAPL over MSFT for the next six months"}

Input: "I like NVDA over AMD over INTC"
Output: {"pair_long_ticker": "NVDA", "pair_short_ticker": "INTC", "direction": "bullish", "timeframe": "2026-07-11", "derived_from": "pair_call", "context_quote": "I like NVDA over AMD over INTC"}
(three-way ranking → extract the strongest-conviction pair, best vs worst)

Input: "Semiconductors will beat software this year"
Output: (do NOT extract as pair_call — two sectors, not two tickers. Let sector_call handle it.)

Input: "AAPL is better than the S&P 500 over the next year"
Output: (do NOT extract as pair_call — ticker vs index. Let ticker_call handle AAPL with SPY as the implicit benchmark.)

Input: "Stocks are going to beat bonds in 2026"
Output: (do NOT extract — asset classes, not tickers.)

Input: "NVDA is going to rip"
Output: (do NOT extract as pair_call — no comparison leg. Extract as a plain ticker_call.)

Rules:
- MUST set both pair_long_ticker AND pair_short_ticker — neither can be empty or vague.
- MUST use direction: "bullish" (on the spread). No bearish/neutral pair_calls.
- MUST set derived_from: "pair_call".
- MUST NOT emit price_target on a pair_call row — the target is implicit ("long beats short").
- MUST NOT emit pair_call for sector-vs-sector, concept-vs-concept, ticker-vs-index, or asset-class-vs-asset-class comparisons. Reject and let the appropriate prediction type handle it.
- If the same pair (same long, same short) is mentioned twice in the transcript, emit it only once — the dedup layer will drop duplicates anyway.
- Long and short MUST be different tickers. Reject if they're the same symbol.

Output JSON only. Be concise."""


# Binary-event-call instructions. Appended to the active prompt when
# ENABLE_BINARY_EVENT_EXTRACTION is flipped on. Teaches Haiku to
# recognize yes/no-event predictions — a specific discrete event will
# or won't happen by a concrete deadline. Unlike conditional_call
# ("IF X then Y"), binary_event_call only predicts whether the event
# itself occurs; there is no second-order market reaction. Scoring is
# trivially binary: happened = hit, didn't = miss, no data source to
# check = stays pending. Lands as a NEW prediction_category value
# ('binary_event_call'). event_type is REUSED from the earnings_call
# ship (its allowed vocabulary is extended — see the allowlist below).
YOUTUBE_HAIKU_BINARY_EVENT_INSTRUCTIONS = """BINARY EVENT CALLS:
If the speaker makes a yes/no prediction that a specific discrete event will happen by a concrete deadline, emit it as a binary_event_call. These are scored trivially: the event happened or it didn't. No price targets, no tolerance, no partial credit. If the statement also predicts a market reaction to the event ("if the Fed cuts, stocks rally"), that's a conditional_call — NOT a binary_event_call. Binary event calls only ask: did the event itself occur?

event_type allowlist — MUST use one of these canonical values verbatim as the `event_type` field:

- fed_decision       Fed rate moves, QE/QT announcements, FOMC statement outcomes
- corporate_action   Dividends, stock splits, buybacks, spin-offs, capital returns
- mna                Mergers, acquisitions, deal closings, takeover announcements
- ipo                IPO / direct listing / SPAC completion events
- index_inclusion    Addition to / removal from S&P 500, Dow, Nasdaq-100
- economic_declaration   NBER recession call, BLS employment revision, GDP revision
- regulatory         FDA approval, SEC enforcement action, DOJ decision, CMA ruling
- other              Anything else with a clean binary outcome and a deadline

Required fields on every binary_event_call output:

- event_type: one of the allowlist values above
- expected_outcome_text: a short natural-language description of the predicted event (e.g. "Fed cuts rates 50bps at March FOMC", "AAPL announces stock split")
- event_deadline: hard ISO date (YYYY-MM-DD) by which the event must occur — parse named meetings (March FOMC → actual FOMC date), "end of year", "by Q3", etc.
- direction: "bullish" — ALWAYS bullish on the event happening. There is no bearish binary_event_call; for negated events ("Fed will NOT cut"), keep direction=bullish and put the negation into expected_outcome_text ("no rate change at March FOMC").
- derived_from: "binary_event_call"
- ticker: REQUIRED for corporate_action / mna / ipo / index_inclusion / regulatory events tied to a specific company. OPTIONAL (set null) for fed_decision and economic_declaration — those are company-agnostic. For `other`, include a ticker if the event attaches to one.

Output format:
{
  "event_type": "fed_decision",
  "expected_outcome_text": "Fed cuts rates 50bps at the March 2026 FOMC meeting",
  "event_deadline": "2026-03-18",
  "direction": "bullish",
  "derived_from": "binary_event_call",
  "context_quote": "The Fed is going to cut by fifty basis points in March"
}

Examples:

Input: "The Fed will cut rates by 50bps at the March meeting"
Output: {"event_type": "fed_decision", "expected_outcome_text": "Fed cuts 50bps at March FOMC", "event_deadline": "2026-03-18", "direction": "bullish", "derived_from": "binary_event_call", "context_quote": "Fed will cut 50bps at March meeting"}

Input: "Apple is going to announce a stock split by the end of 2026"
Output: {"event_type": "corporate_action", "ticker": "AAPL", "expected_outcome_text": "AAPL announces stock split", "event_deadline": "2026-12-31", "direction": "bullish", "derived_from": "binary_event_call", "context_quote": "Apple will announce a stock split by end of 2026"}

Input: "NVDA will acquire a small AI startup this year"
Output: {"event_type": "mna", "ticker": "NVDA", "expected_outcome_text": "NVDA completes acquisition of an AI startup", "event_deadline": "2026-12-31", "direction": "bullish", "derived_from": "binary_event_call", "context_quote": "NVDA will acquire a small AI startup this year"}

Input: "Stripe is finally going to IPO before end of 2026"
Output: {"event_type": "ipo", "ticker": "STRP", "expected_outcome_text": "Stripe IPO / direct listing completes", "event_deadline": "2026-12-31", "direction": "bullish", "derived_from": "binary_event_call", "context_quote": "Stripe finally going to IPO before end of 2026"}
(ticker may be a placeholder if the company is private — the insert path may reject unknown tickers; this is OK.)

Input: "Tesla gets added to the Dow by end of 2027"
Output: {"event_type": "index_inclusion", "ticker": "TSLA", "expected_outcome_text": "TSLA added to the Dow Jones Industrial Average", "event_deadline": "2027-12-31", "direction": "bullish", "derived_from": "binary_event_call", "context_quote": "Tesla gets added to the Dow by end of 2027"}

Input: "NBER will declare a recession before the end of 2026"
Output: {"event_type": "economic_declaration", "expected_outcome_text": "NBER officially declares a recession", "event_deadline": "2026-12-31", "direction": "bullish", "derived_from": "binary_event_call", "context_quote": "NBER will declare a recession before end of 2026"}

Input: "The FDA will approve that Eli Lilly obesity drug by Q3"
Output: {"event_type": "regulatory", "ticker": "LLY", "expected_outcome_text": "FDA approval for LLY obesity drug", "event_deadline": "2026-09-30", "direction": "bullish", "derived_from": "binary_event_call", "context_quote": "FDA will approve the LLY obesity drug by Q3"}

Input: "The Fed will NOT cut rates at the March meeting — they're holding"
Output: {"event_type": "fed_decision", "expected_outcome_text": "no rate change at March FOMC (Fed holds)", "event_deadline": "2026-03-18", "direction": "bullish", "derived_from": "binary_event_call", "context_quote": "Fed will NOT cut rates at March meeting, holding"}

Input: "Apple will probably have a good year"
Output: (do NOT extract — no concrete event, no deadline, no binary outcome)

Input: "If the Fed cuts 50bps in March, stocks rally 10%"
Output: (do NOT extract as binary_event_call — this is a conditional_call, let that prompt block handle it)

Input: "Something big is coming for NVDA this year"
Output: (do NOT extract — vague, no specific event)

Rules:
- MUST set derived_from: "binary_event_call".
- MUST use direction: "bullish" regardless of whether the event is a "yes" or "no" prediction — flip the framing via expected_outcome_text for negations.
- MUST use an event_type from the allowlist above verbatim.
- MUST provide a concrete event_deadline (ISO YYYY-MM-DD). Reject if the deadline is vague ("soon", "eventually", "this decade").
- MUST NOT emit price_target on binary_event_call rows — the outcome is the event, not a price level.
- MUST NOT emit binary_event_call for statements that also predict a market reaction ("if X then Y") — those are conditional_calls.
- MUST NOT emit binary_event_call for soft / hedgy / vague claims with no checkable outcome.
- ticker is optional for fed_decision and economic_declaration (they're company-agnostic).
- If the same event is mentioned twice in a transcript, emit it once — the dedup layer will collapse duplicates anyway.

Output JSON only. Be concise."""


# Metric-forecast instructions. Appended to the active prompt when
# ENABLE_METRIC_FORECAST_EXTRACTION is flipped on. Teaches Haiku to
# recognize numerical metric predictions — a specific reported value
# for a specific metric at a specific release date. Distinct from
# earnings_call (which predicts price reaction to earnings) and from
# binary_event_call (which predicts yes/no events). Lands as a NEW
# prediction_category='metric_forecast_call'. The metric_type field
# MUST come from the inlined allowlist — unknown metric types are
# rejected, not silently widened.
YOUTUBE_HAIKU_METRIC_FORECAST_INSTRUCTIONS = """METRIC FORECAST CALLS:
If the speaker predicts a specific numerical value for a known reported metric (EPS, revenue, CPI, unemployment, PMI, …), emit it as a metric_forecast_call. These are scored against the actual released value using category-based tolerance (±5% for EPS/revenue/growth, ±0.1pp for rates like CPI/unemployment, ±10% for count metrics like payrolls).

Distinguish carefully:
- "AAPL will report $2.10 EPS next Thursday" → metric_forecast_call (predicts the number)
- "AAPL will pop 10% after earnings" → earnings_call (predicts the price reaction, NOT the number)
- "Fed hikes 25bps in March" → binary_event_call (discrete policy action, yes/no)
- "CPI will come in at 3.2% next month" → metric_forecast_call (predicts the released rate)
- "Inflation is going higher" → macro_call (concept-level bullish, no specific number)

metric_type allowlist — MUST use one of these canonical names verbatim as the `metric_type` field. Unknown metrics (data center revenue, customer satisfaction, churn, etc) are REJECTED — let ticker_call / earnings_call handle those instead.

COMPANY metrics (require a ticker):
  metric_type        format              description
  eps                decimal dollars     next-quarter earnings per share
  revenue            absolute dollars    next-quarter total revenue (e.g. 95000000000 for $95B)
  guidance_eps       decimal dollars     forward EPS guidance issued on the call
  guidance_revenue   absolute dollars    forward revenue guidance
  subscribers        count               subscriber count (services companies)
  same_store_sales   decimal rate        SSS growth rate (e.g. 0.06 for 6%)
  margin             decimal rate        operating or gross margin (e.g. 0.42 for 42%)
  users              count               monthly/daily active users
  free_cash_flow     absolute dollars    quarterly FCF
  growth_yoy         decimal rate        year-over-year growth rate (any category)

MACRO metrics (ticker optional — omit or set null):
  metric_type        format              description
  cpi                decimal rate        headline Consumer Price Index (YoY)
  core_cpi           decimal rate        Core CPI ex food and energy
  pce                decimal rate        PCE inflation
  gdp_growth         decimal rate        quarterly GDP growth rate
  unemployment       decimal rate        unemployment rate (e.g. 0.045 for 4.5%)
  nonfarm_payrolls   count               jobs added (e.g. 250000 for 250K)
  jolts              count               job openings
  pmi_manufacturing  index level         manufacturing PMI (e.g. 48.5)
  pmi_services       index level         services PMI
  retail_sales       decimal rate        retail sales month-over-month
  housing_starts     count               housing starts (annualized)
  ism_manufacturing  index level         ISM manufacturing index

Rules on parsing metric_target:
- Convert all percentages to decimal form: "3.2%" → 0.032, "6 percent growth" → 0.06, "4.5% unemployment" → 0.045.
- Revenue: always absolute dollars. "$95 billion" → 95000000000. "$2B" → 2000000000.
- EPS: decimal dollars. "$5.20 EPS" → 5.20. "$2 and 10 cents" → 2.10.
- Counts: absolute integer. "250K jobs" → 250000. "1.2 million subscribers" → 1200000.
- If the forecaster gives a RANGE ("$5.15 to $5.25"), use the MIDPOINT (5.20).
- If the forecaster just says "a beat" / "a miss" without a number, DO NOT EMIT metric_forecast_call — let earnings_call pick it up.

Required fields on every metric_forecast_call output:
- metric_type: one of the allowlist values above
- metric_target: the predicted numerical value in the natural unit
- metric_release_date: ISO YYYY-MM-DD when the actual value will be released. For company metrics this is usually the next earnings date. For macro metrics it is the scheduled data release. If the forecaster gives no date, default to:
    * company metrics → +90 days from publish date
    * macro metrics → +30 days from publish date
- metric_period: OPTIONAL free-form period label ("Q1_2026", "fiscal_2026", "Jan_2026", "2026-Q2"). Omit if unclear.
- ticker: REQUIRED for company metrics, OPTIONAL for macro metrics (omit or set null)
- direction: "bullish" if the forecaster frames it as a beat, "bearish" for a miss, "neutral" for a pure number prediction with no beat/miss framing. Pure number predictions default to "neutral".
- derived_from: "metric_forecast_call"

Output format:
{
  "ticker": "NVDA",
  "metric_type": "eps",
  "metric_target": 5.20,
  "metric_period": "Q1_2026",
  "metric_release_date": "2026-05-21",
  "direction": "bullish",
  "derived_from": "metric_forecast_call",
  "context_quote": "NVIDIA is going to report five twenty EPS next quarter"
}

Examples:

Input: "NVDA will report $5.20 EPS next Wednesday"
Output: {"ticker": "NVDA", "metric_type": "eps", "metric_target": 5.20, "metric_release_date": "2026-04-15", "direction": "neutral", "derived_from": "metric_forecast_call", "context_quote": "NVDA will report $5.20 EPS next Wednesday"}

Input: "AAPL revenue coming in around $95 billion this quarter"
Output: {"ticker": "AAPL", "metric_type": "revenue", "metric_target": 95000000000, "metric_period": "Q2_2026", "metric_release_date": "2026-05-01", "direction": "neutral", "derived_from": "metric_forecast_call", "context_quote": "AAPL revenue around $95 billion this quarter"}

Input: "Meta's services growing 15% year over year"
Output: {"ticker": "META", "metric_type": "growth_yoy", "metric_target": 0.15, "metric_period": "Q1_2026", "metric_release_date": "2026-04-26", "direction": "bullish", "derived_from": "metric_forecast_call", "context_quote": "Meta services growing 15% year over year"}

Input: "CPI is going to print 3.2% next month"
Output: {"metric_type": "cpi", "metric_target": 0.032, "metric_release_date": "2026-05-13", "direction": "neutral", "derived_from": "metric_forecast_call", "context_quote": "CPI going to print 3.2% next month"}

Input: "Unemployment ticks up to 4.5% in the next jobs report"
Output: {"metric_type": "unemployment", "metric_target": 0.045, "metric_release_date": "2026-05-02", "direction": "bearish", "derived_from": "metric_forecast_call", "context_quote": "unemployment ticks up to 4.5% in the next jobs report"}

Input: "Apple guides for $2.20 EPS next quarter"
Output: {"ticker": "AAPL", "metric_type": "guidance_eps", "metric_target": 2.20, "metric_period": "Q3_2026", "metric_release_date": "2026-08-01", "direction": "bullish", "derived_from": "metric_forecast_call", "context_quote": "Apple guides for $2.20 EPS next quarter"}

Input: "Tesla will report between $0.60 and $0.70 EPS this quarter"
Output: {"ticker": "TSLA", "metric_type": "eps", "metric_target": 0.65, "metric_release_date": "2026-04-24", "direction": "neutral", "derived_from": "metric_forecast_call", "context_quote": "Tesla will report between $0.60 and $0.70 EPS this quarter"}
(range → midpoint)

Input: "Nonfarm payrolls will come in at 200 thousand next Friday"
Output: {"metric_type": "nonfarm_payrolls", "metric_target": 200000, "metric_release_date": "2026-05-02", "direction": "neutral", "derived_from": "metric_forecast_call", "context_quote": "nonfarm payrolls at 200 thousand next Friday"}

Input: "NVIDIA is going to have good earnings"
Output: (do NOT extract as metric_forecast_call — no specific number. Let earnings_call handle as a directional call.)

Input: "They'll report strong numbers eventually"
Output: (do NOT extract — no release date, no specific metric, vague.)

Input: "NVDA data center revenue hits $30 billion"
Output: (do NOT extract — data center revenue is a segment, NOT in the allowlist. Emit as a ticker_call if there's a directional view, otherwise skip.)

Rules:
- MUST set derived_from: "metric_forecast_call".
- MUST use metric_type from the allowlist above verbatim.
- MUST provide metric_target as a number in the natural unit (decimal rate for percentages, absolute dollars for revenue, absolute count for payrolls, decimal dollars for EPS).
- MUST provide metric_release_date — use the default fallback if the forecaster doesn't name one, but NEVER leave it null.
- MUST include ticker for every COMPANY metric. MAY omit ticker for MACRO metrics.
- MUST NOT emit for metrics outside the allowlist — let ticker_call / earnings_call / macro_call handle those.
- MUST NOT emit for vague "good earnings" / "strong numbers" statements without a specific target.
- If the same metric prediction appears twice in a transcript, emit once — the dedup layer collapses duplicates on (metric_type, period, target).

Output JSON only. Be concise."""


# Conditional-call instructions. Appended to the active prompt when
# ENABLE_CONDITIONAL_CALL_EXTRACTION is flipped on. Teaches Haiku to
# recognize "IF trigger THEN outcome" language and emit predictions
# with both the trigger and the outcome parts. The insert path
# writes these as a new prediction_category='conditional_call' row
# with trigger_* columns populated. The evaluator scores them in two
# phases: phase 1 checks whether the trigger fires inside
# trigger_deadline, phase 2 scores the outcome window starting from
# trigger_fired_at.
#
# NEW outcome value: 'unresolved' — written when the trigger
# deadline passes without firing. Excluded from accuracy denominators.
YOUTUBE_HAIKU_CONDITIONAL_INSTRUCTIONS = """CONDITIONAL CALLS:
If the speaker makes an "IF trigger THEN outcome" prediction — where the forecast is contingent on a separate event happening first — emit it as a conditional_call with both parts. The trigger is the precondition; the outcome is the directional forecast that only matters once the trigger has fired.

Signals that indicate a conditional:
- "if X happens, then Y"
- "should X happen, Y will"
- "X is the key — if it breaks, then Y"
- "in the event of X"
- "provided X holds"
- "if X crosses above/below Y, I expect Z"
- "when X reaches Y, Z follows"
- "assuming X, then Y"

Trigger types (required — pick one from this list):
- price_hold: "if NVDA holds $180 support" — ticker stays at/above threshold
- price_break: "if AAPL breaks $170 to the downside" — ticker crosses threshold in stated direction
- economic_data: "if CPI comes in below 3%" — economic release
- fed_decision: "if the Fed cuts 50bps" — FOMC action
- market_event: "if recession is declared", "if VIX spikes above 40" — general market state
- corporate_action: "if Apple announces a stock split" — corporate event
- other: any trigger that doesn't fit above — rare, use sparingly

For price_hold and price_break triggers (the only types auto-resolved in this ship), you MUST extract:
- trigger_ticker: the symbol being watched (may differ from the outcome's ticker)
- trigger_price: the numeric threshold
- trigger_type: "price_hold" or "price_break"

For all other trigger types, the insert path accepts trigger_condition as free text and the evaluator will eventually mark the row 'unresolved' when the deadline passes.

Output format for conditional-call predictions:
{
  "derived_from": "conditional_call",
  "trigger_condition": "Fed cuts rates by 50bps",
  "trigger_type": "fed_decision",
  "trigger_ticker": null,
  "trigger_price": null,
  "trigger_deadline": "2026-07-11",
  "ticker": "IWM",
  "direction": "bullish",
  "price_target": 250,
  "timeframe": "2026-10-11",
  "context_quote": "If the Fed cuts 50bps, small caps rip 20 percent"
}

The "outcome" side uses the normal ticker_call fields: ticker, direction, target_price (if stated), timeframe. The "trigger" side adds the trigger_* fields. If trigger_deadline is not explicitly stated, omit it — the insert path will default to 90 days from the video publish date.

Examples:

Input: "If NVDA holds $180 support, it runs to $220 by summer"
Output: {"derived_from": "conditional_call", "trigger_condition": "NVDA holds $180 support", "trigger_type": "price_hold", "trigger_ticker": "NVDA", "trigger_price": 180, "ticker": "NVDA", "direction": "bullish", "price_target": 220, "timeframe": "2026-08-01", "context_quote": "if NVDA holds 180, runs to 220 by summer"}

Input: "If AAPL breaks $170 I'm out — expect a drop to 150"
Output: {"derived_from": "conditional_call", "trigger_condition": "AAPL closes below $170", "trigger_type": "price_break", "trigger_ticker": "AAPL", "trigger_price": 170, "ticker": "AAPL", "direction": "bearish", "price_target": 150, "timeframe": "2026-10-11", "context_quote": "if AAPL breaks 170, drop to 150"}

Input: "Should the Fed cut 50bps, small caps rip 20 percent"
Output: {"derived_from": "conditional_call", "trigger_condition": "Fed cuts benchmark rate by 50bps in a single meeting", "trigger_type": "fed_decision", "trigger_ticker": null, "trigger_price": null, "ticker": "IWM", "direction": "bullish", "price_target": 250, "timeframe": "2026-10-11", "context_quote": "if Fed cuts 50bps, small caps rip 20 percent"}

Input: "If CPI comes in below 3%, bonds will rally hard"
Output: {"derived_from": "conditional_call", "trigger_condition": "CPI print below 3% YoY", "trigger_type": "economic_data", "trigger_ticker": null, "trigger_price": null, "ticker": "TLT", "direction": "bullish", "timeframe": "2026-07-11", "context_quote": "if CPI below 3 percent, bonds rally hard"}

Input: "If recession is declared by Q2, gold spikes to $3000"
Output: {"derived_from": "conditional_call", "trigger_condition": "US recession declared by end of Q2 2026", "trigger_type": "market_event", "trigger_ticker": null, "trigger_price": null, "trigger_deadline": "2026-06-30", "ticker": "GLD", "direction": "bullish", "price_target": 300, "timeframe": "2026-09-30", "context_quote": "if recession by Q2, gold to 3000"}

Input: "Provided SPY stays above 450, I'm bullish on semis through year-end"
Output: {"derived_from": "conditional_call", "trigger_condition": "SPY holds 450 support", "trigger_type": "price_hold", "trigger_ticker": "SPY", "trigger_price": 450, "ticker": "SOXX", "direction": "bullish", "timeframe": "2026-12-31", "context_quote": "provided SPY above 450, bullish semis through year-end"}

Input: "If VIX spikes above 40, equities are in for a rough few weeks"
Output: {"derived_from": "conditional_call", "trigger_condition": "VIX daily close above 40", "trigger_type": "price_break", "trigger_ticker": "VIX", "trigger_price": 40, "ticker": "SPY", "direction": "bearish", "timeframe": "2026-05-11", "context_quote": "if VIX above 40, equities rough weeks"}

Input: "The market feels toppy — if things go south, it won't be pretty"
Output: (do NOT extract — trigger "things go south" is not testable, and outcome "won't be pretty" isn't a directional call on a specific ticker)

Input: "I'd like to see NVDA consolidate here before taking a position"
Output: (do NOT extract — this is a plan, not a conditional prediction; no trigger with a clear outcome)

Rules:
- MUST set derived_from: "conditional_call".
- MUST include both trigger_condition (free text) AND trigger_type (from the enum list).
- For price_hold / price_break: trigger_ticker and trigger_price are REQUIRED.
- For other trigger types: trigger_ticker and trigger_price should be null.
- The outcome side uses the normal ticker / direction / price_target / timeframe fields — it's a scoreable directional forecast, not a vague mood.
- REJECT conditionals where the trigger isn't testable (e.g. "if things go well", "if the vibes are good").
- REJECT conditionals where the outcome isn't a specific direction on a ticker/concept.
- Do NOT extract a conditional if the speaker is actually making TWO separate standalone predictions that happen to be adjacent.
- trigger_deadline is OPTIONAL. Omit if not stated. Default handling is 90 days from publish date.

Output JSON only. Be concise."""


# ── Transcript fetching ─────────────────────────────────────────────────────

def _build_transcript_api():
    """Construct a YouTubeTranscriptApi instance with optional proxy.

    YouTube aggressively blocks transcript scraping from datacenter IPs
    (Railway, AWS, GCP). Without a residential proxy, every fetch
    returns IpBlocked within a few requests. We support two opt-in
    configurations via env vars:

      WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD
        → uses youtube_transcript_api.proxies.WebshareProxyConfig.
          Webshare offers $3-5/mo residential proxy plans designed
          specifically for YouTube transcript scraping. The library
          author recommends Webshare in the README. retries_when_blocked
          stays at the default 10.

      YT_PROXY_HTTP / YT_PROXY_HTTPS
        → generic proxy URLs for any other provider. The values are
          full URLs including credentials, e.g.
          http://user:pass@proxy.example.com:8080

    If neither pair is set, returns a plain YouTubeTranscriptApi() —
    which works fine when running locally on a residential connection
    but will hit IpBlocked from any datacenter.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    webshare_user = os.getenv("WEBSHARE_PROXY_USERNAME", "").strip()
    webshare_pass = os.getenv("WEBSHARE_PROXY_PASSWORD", "").strip()
    proxy_http = os.getenv("YT_PROXY_HTTP", "").strip()
    proxy_https = os.getenv("YT_PROXY_HTTPS", "").strip()

    if webshare_user and webshare_pass:
        try:
            from youtube_transcript_api.proxies import WebshareProxyConfig
            return YouTubeTranscriptApi(
                proxy_config=WebshareProxyConfig(
                    proxy_username=webshare_user,
                    proxy_password=webshare_pass,
                )
            )
        except ImportError:
            log.warning("[YT-CLF] WebshareProxyConfig import failed — version too old")
    elif proxy_http or proxy_https:
        try:
            from youtube_transcript_api.proxies import GenericProxyConfig
            return YouTubeTranscriptApi(
                proxy_config=GenericProxyConfig(
                    http_url=proxy_http or None,
                    https_url=proxy_https or proxy_http or None,
                )
            )
        except ImportError:
            log.warning("[YT-CLF] GenericProxyConfig import failed — version too old")

    return YouTubeTranscriptApi()


def transcript_proxy_status() -> str:
    """Return a short string describing what proxy mode is configured.
    Used by the channel monitor / backfill startup logging so the
    proxy state is visible without grepping env vars."""
    if os.getenv("WEBSHARE_PROXY_USERNAME") and os.getenv("WEBSHARE_PROXY_PASSWORD"):
        return "webshare"
    if os.getenv("YT_PROXY_HTTP") or os.getenv("YT_PROXY_HTTPS"):
        return "generic"
    return "none (datacenter IPs are typically blocked by YouTube)"


def fetch_transcript(video_id: str) -> tuple[str | None, str | None]:
    """Fetch a YouTube video's auto-captions via youtube-transcript-api.

    Returns (transcript_text, status):
      - (text, "en")            — English transcript fetched
      - (text, "<lang>")        — non-English transcript (still usable; Haiku
                                  speaks dozens of languages so the prompt
                                  works regardless)
      - (None, "no_transcript") — disabled / live stream / age-gated / shorts
                                  with no captions / region-blocked
      - (None, "error: IpBlocked: ...") — datacenter IP block. See
                                  _build_transcript_api() for the proxy
                                  env vars to set.
      - (None, "error: ...")    — other library error

    Does NOT consume YouTube Data API quota — the library scrapes the
    transcript endpoints directly.

    NOTE on API shape: youtube-transcript-api 1.x is INSTANCE-based —
    you create a `YouTubeTranscriptApi()` and call `.fetch(video_id)`,
    which returns an iterable of `FetchedTranscriptSnippet` objects with
    `.text` / `.start` / `.duration` attributes (not dicts). The 0.x
    classmethod API (`get_transcript`) is broken since YouTube changed
    the underlying endpoint format. We require >=1.2 in requirements.txt.
    """
    if not video_id:
        return None, "no_video_id"
    try:
        from youtube_transcript_api import (
            TranscriptsDisabled,
            NoTranscriptFound,
            VideoUnavailable,
        )
    except ImportError:
        return None, "library_missing"

    try:
        api = _build_transcript_api()
        # Prefer English; fall back to any available language. The 1.x
        # API picks the best match given a language priority list.
        try:
            fetched = api.fetch(video_id, languages=["en"])
            lang = "en"
        except NoTranscriptFound:
            # No English captions — let the library pick the default lang
            fetched = api.fetch(video_id)
            lang = getattr(fetched, "language_code", None) or "unknown"

        # Snippets expose .text as an attribute (FetchedTranscriptSnippet
        # objects). Old 0.x returned dicts; we no longer support that.
        parts = []
        for snippet in fetched:
            t = getattr(snippet, "text", None)
            if t is None and isinstance(snippet, dict):
                t = snippet.get("text")
            if t:
                parts.append(t.strip())
        if not parts:
            return None, "empty_transcript"
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if not text:
            return None, "empty_transcript"
        return text, lang

    except TranscriptsDisabled:
        return None, "transcripts_disabled"
    except VideoUnavailable:
        return None, "video_unavailable"
    except NoTranscriptFound:
        return None, "no_transcript"
    except Exception as e:
        # Library raises a long tail of internal errors (XML parse, HTTP
        # 429, age-gate, member-only, etc.). Roll them all into a single
        # tag so we can grep the rejection log without enumerating every
        # exception class.
        return None, f"error: {type(e).__name__}: {str(e)[:120]}"


def chunk_transcript(text: str) -> list[str]:
    """Split a long transcript into overlapping chunks for the classifier.

    Below TRANSCRIPT_CHUNK_THRESHOLD chars: returns [text] unchanged.
    Above: returns ~TRANSCRIPT_CHUNK_SIZE chunks with TRANSCRIPT_CHUNK_OVERLAP
    char overlap so a prediction sentence that spans a chunk boundary
    survives in at least one chunk.
    """
    if not text:
        return []
    if len(text) <= TRANSCRIPT_CHUNK_THRESHOLD:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + TRANSCRIPT_CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - TRANSCRIPT_CHUNK_OVERLAP
    return chunks


# ── Haiku classification ────────────────────────────────────────────────────

def _build_user_prompt(channel_name: str, title: str, publish_date: str, transcript: str) -> str:
    return (
        f"Video title: {title}\n"
        f"Channel: {channel_name}\n"
        f"Published: {publish_date}\n"
        f"Transcript:\n"
        f"{transcript}\n\n"
        f"Extract all valid financial predictions from this transcript. "
        f"Return JSON array only, no other text."
    )


def classify_video(channel_name: str, title: str, publish_date: str,
                   transcript: str,
                   video_id: str | None = None,
                   db=None) -> tuple[list[dict], dict]:
    """Send a (possibly chunked) transcript to Haiku and return parsed predictions.

    Returns (predictions, telemetry):
      predictions — list of validated prediction dicts (may be empty)
      telemetry   — dict with token usage, chunk count, last_status, and
                    optionally an error tag for non-fatal classifier failures

    NEVER raises. On any classifier failure (no key, HTTP error, parse
    error) returns ([], {"error": "<tag>"}). The caller should treat
    empty predictions + an error tag as a transient skip.

    Prompt selection: when a DB session is passed AND the stable hash
    routing for this video_id falls under the current traffic percent
    for ENABLE_YOUTUBE_SECTOR_CALLS, use YOUTUBE_HAIKU_SECTOR_SYSTEM
    (extracts both ticker_call and sector_call objects). Otherwise use
    the unchanged HAIKU_SYSTEM (ticker_call only). telemetry gets a
    prompt_variant key so the caller can aggregate.
    """
    telemetry: dict = {"chunks": 0, "input_tokens": 0, "output_tokens": 0,
                       "last_status": None, "predictions_raw": 0,
                       "prompt_variant": "standard"}
    if not ANTHROPIC_API_KEY:
        telemetry["error"] = "no_api_key"
        return [], telemetry

    chunks = chunk_transcript(transcript or "")
    if not chunks:
        telemetry["error"] = "empty_transcript"
        return [], telemetry

    try:
        import anthropic
    except ImportError:
        telemetry["error"] = "anthropic_sdk_missing"
        return [], telemetry

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Decide which system prompt this video gets. Stable hash routing
    # guarantees retries see the same prompt, and the cached flag read
    # (60s TTL) keeps this cheap in tight batch loops.
    use_sector_prompt = False
    use_ranked_list = False
    use_revisions = False
    use_options = False
    use_earnings = False
    use_macro = False
    use_pair = False
    use_binary_event = False
    use_metric_forecast = False
    use_conditional = False
    if db is not None and video_id:
        try:
            from feature_flags import should_use_sector_prompt
            use_sector_prompt = should_use_sector_prompt(db, video_id)
        except Exception as _e:
            log.warning("[YT-CLF] sector prompt flag check failed: %s", _e)
            use_sector_prompt = False
    if db is not None:
        try:
            from feature_flags import is_ranked_list_extraction_enabled
            use_ranked_list = is_ranked_list_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] ranked-list flag check failed: %s", _e)
            use_ranked_list = False
        try:
            from feature_flags import is_target_revisions_enabled
            use_revisions = is_target_revisions_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] revisions flag check failed: %s", _e)
            use_revisions = False
        try:
            from feature_flags import is_options_extraction_enabled
            use_options = is_options_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] options flag check failed: %s", _e)
            use_options = False
        try:
            from feature_flags import is_earnings_extraction_enabled
            use_earnings = is_earnings_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] earnings flag check failed: %s", _e)
            use_earnings = False
        try:
            from feature_flags import is_macro_extraction_enabled
            use_macro = is_macro_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] macro flag check failed: %s", _e)
            use_macro = False
        try:
            from feature_flags import is_pair_extraction_enabled
            use_pair = is_pair_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] pair flag check failed: %s", _e)
            use_pair = False
        try:
            from feature_flags import is_binary_event_extraction_enabled
            use_binary_event = is_binary_event_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] binary event flag check failed: %s", _e)
            use_binary_event = False
        try:
            from feature_flags import is_metric_forecast_enabled
            use_metric_forecast = is_metric_forecast_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] metric forecast flag check failed: %s", _e)
            use_metric_forecast = False
        try:
            from feature_flags import is_conditional_extraction_enabled
            use_conditional = is_conditional_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] conditional flag check failed: %s", _e)
            use_conditional = False
    base_system = YOUTUBE_HAIKU_SECTOR_SYSTEM if use_sector_prompt else HAIKU_SYSTEM
    # Append optional instruction blocks ONLY when each flag is on. When
    # every flag is off (the default), base_system is sent byte-for-byte
    # unchanged so Anthropic's prompt cache hit rate on the base prompt
    # stays at 100%. Order matters for cache hits: ranked list → revisions
    # → options → earnings → macro → pair → binary_event → metric_forecast,
    # stable across calls with any combination of flags on so extended-
    # prompt cache entries match. (conditional_call slots in between pair
    # and binary_event when it lands; disclosure slots AFTER metric_forecast
    # when that ship lands — the append order leaves room for both.)
    active_system = base_system
    if use_ranked_list:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_RANKED_LIST_INSTRUCTIONS
    if use_revisions:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_REVISIONS_INSTRUCTIONS
    if use_options:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_OPTIONS_INSTRUCTIONS
    if use_earnings:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_EARNINGS_INSTRUCTIONS
    if use_macro:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_MACRO_INSTRUCTIONS
    if use_pair:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_PAIR_INSTRUCTIONS
    if use_conditional:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_CONDITIONAL_INSTRUCTIONS
    if use_binary_event:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_BINARY_EVENT_INSTRUCTIONS
    if use_metric_forecast:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_METRIC_FORECAST_INSTRUCTIONS
    telemetry["prompt_variant"] = "sector" if use_sector_prompt else "standard"
    telemetry["ranked_list_enabled"] = bool(use_ranked_list)
    telemetry["revisions_enabled"] = bool(use_revisions)
    telemetry["options_enabled"] = bool(use_options)
    telemetry["earnings_enabled"] = bool(use_earnings)
    telemetry["macro_enabled"] = bool(use_macro)
    telemetry["pair_enabled"] = bool(use_pair)
    telemetry["binary_event_enabled"] = bool(use_binary_event)
    telemetry["metric_forecast_enabled"] = bool(use_metric_forecast)
    telemetry["conditional_enabled"] = bool(use_conditional)
    print(
        f"[YOUTUBE-HAIKU] video={video_id or '?'} channel={channel_name} "
        f"prompt_variant={telemetry['prompt_variant']} "
        f"ranked_list={'on' if use_ranked_list else 'off'} "
        f"revisions={'on' if use_revisions else 'off'} "
        f"options={'on' if use_options else 'off'} "
        f"earnings={'on' if use_earnings else 'off'} "
        f"macro={'on' if use_macro else 'off'} "
        f"pair={'on' if use_pair else 'off'} "
        f"binary_event={'on' if use_binary_event else 'off'} "
        f"metric_forecast={'on' if use_metric_forecast else 'off'} "
        f"conditional={'on' if use_conditional else 'off'}",
        flush=True,
    )

    all_preds: list[dict] = []
    for i, chunk in enumerate(chunks):
        telemetry["chunks"] += 1
        # System + messages built per-chunk; the cache_control ephemeral
        # wrapper means the retry path reuses the same cached system
        # prompt. The wrapper records tokens + cost from both the first
        # attempt and (if triggered) the retry into telemetry.
        system_block = [
            {
                "type": "text",
                "text": active_system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        messages_block = [
            {
                "role": "user",
                "content": _build_user_prompt(channel_name, title, publish_date, chunk),
            }
        ]
        try:
            resp, _was_retried = call_youtube_haiku_with_retry(
                client,
                system=system_block,
                messages=messages_block,
                video_id=video_id,
                channel_name=channel_name,
                telemetry=telemetry,
            )
        except Exception as e:
            # Anthropic SDK raises typed exceptions for 4xx/5xx — we don't
            # try to discriminate. The spec says: "If Anthropic returns a
            # 400/401/402/429 error, log it and skip the video (do NOT
            # retry in a loop — the next scheduled run will pick it up)."
            # Per the read-body-first feedback, log the full string before
            # theorizing.
            tag = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"[YT-CLF] Haiku error on chunk {i+1}/{len(chunks)} for "
                  f"\"{title[:60]}\": {tag}", flush=True)
            telemetry["error"] = tag[:300]
            telemetry["last_status"] = "exception"
            return [], telemetry

        try:
            content = resp.content[0].text.strip()
        except (AttributeError, IndexError):
            telemetry["error"] = "no_content"
            return [], telemetry

        # Strip markdown fences if Haiku wraps the JSON in them
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as pe:
            print(f"[YT-CLF] Parse error on chunk {i+1}/{len(chunks)} for "
                  f"\"{title[:60]}\": {pe} | raw={content[:200]!r}", flush=True)
            telemetry["error"] = f"parse_error: {str(pe)[:120]}"
            return [], telemetry

        if not isinstance(parsed, list):
            telemetry["error"] = f"non_list_response: {type(parsed).__name__}"
            return [], telemetry

        telemetry["predictions_raw"] += len(parsed)
        all_preds.extend(parsed)

        # 1-second pacing between API calls per the spec
        if i < len(chunks) - 1:
            time.sleep(1.0)

    # Validate and dedupe across chunks
    valid = _validate_and_dedupe_predictions(all_preds)
    if len(valid) > MAX_PREDICTIONS_PER_VIDEO:
        log.warning(
            "[YT-CLF] %s returned %d preds, capping at %d (\"%s\")",
            channel_name, len(valid), MAX_PREDICTIONS_PER_VIDEO, title[:60],
        )
        valid = valid[:MAX_PREDICTIONS_PER_VIDEO]

    telemetry["predictions_validated"] = len(valid)
    return valid, telemetry


# ── Validation ──────────────────────────────────────────────────────────────

_VALID_DIRECTIONS = {"bullish", "bearish", "neutral"}
# Sector calls only support bullish/bearish — neutral doesn't make sense
# at the sector level (a "hold the sector" call is not a prediction).
_SECTOR_VALID_DIRECTIONS = {"bullish", "bearish"}
# Canonical allowlist for binary_event_call event_type values. Kept in
# sync with YOUTUBE_HAIKU_BINARY_EVENT_INSTRUCTIONS above — the prompt
# teaches Haiku the exact same vocabulary and this set enforces it on
# the validator side so unknown event_type values drop on the floor
# instead of contaminating the new prediction_category='binary_event_call'.
# event_type is a REUSED column (originally added for earnings_call);
# 'earnings' itself is intentionally NOT in this set — earnings-tagged
# rows stay as ticker_call with event_type='earnings', they are not
# binary event rows.
_BINARY_EVENT_TYPES = {
    "fed_decision",
    "corporate_action",
    "mna",
    "ipo",
    "index_inclusion",
    "economic_declaration",
    "regulatory",
    "other",
}
# Canonical allowlist for metric_forecast_call metric_type values.
# Kept in sync with YOUTUBE_HAIKU_METRIC_FORECAST_INSTRUCTIONS above —
# the prompt teaches Haiku the exact vocabulary and this set enforces
# it on the validator side. Unknown metric types drop on the floor.
# Split into COMPANY vs MACRO so the insert path can apply the
# ticker-required rule and so the evaluator can route to
# earnings_history lookups (company) vs stubbed resolvers (macro).
_METRIC_FORECAST_COMPANY_TYPES = {
    "eps",
    "revenue",
    "guidance_eps",
    "guidance_revenue",
    "subscribers",
    "same_store_sales",
    "margin",
    "users",
    "free_cash_flow",
    "growth_yoy",
}
_METRIC_FORECAST_MACRO_TYPES = {
    "cpi",
    "core_cpi",
    "pce",
    "gdp_growth",
    "unemployment",
    "nonfarm_payrolls",
    "jolts",
    "pmi_manufacturing",
    "pmi_services",
    "retail_sales",
    "housing_starts",
    "ism_manufacturing",
}
_METRIC_FORECAST_TYPES = _METRIC_FORECAST_COMPANY_TYPES | _METRIC_FORECAST_MACRO_TYPES
# Scoring category buckets — used by _score_metric_forecast in
# jobs/evaluator.py to pick the right tolerance band. Relative metrics
# score on % error of the target; percentage-point metrics score on
# absolute difference in decimal rate; count metrics score on % error
# of the target with a looser band.
_METRIC_RELATIVE_SCORING = {
    # Company metrics that are absolute dollar / integer values — score
    # on percent error of the target.
    "eps", "revenue", "guidance_eps", "guidance_revenue",
    "subscribers", "users", "free_cash_flow",
    # Growth / margin rates — also scored on percent error since a
    # 1pp miss on a 42% margin is smaller than a 1pp miss on 6% SSS.
    "same_store_sales", "margin", "growth_yoy",
}
_METRIC_PERCENTAGE_POINT_SCORING = {
    # Macro rates reported in percentage points — score on absolute
    # decimal-rate difference (0.001 = 0.1pp).
    "cpi", "core_cpi", "pce", "gdp_growth", "unemployment",
    "retail_sales",
}
_METRIC_COUNT_SCORING = {
    # Count / index-level metrics — score on percent error of the
    # target, but with a looser band than _METRIC_RELATIVE_SCORING
    # because these reports are noisy (employment revisions, PMI
    # bounces) and a 10% miss is still a reasonable forecast.
    "nonfarm_payrolls", "jolts", "housing_starts",
    "pmi_manufacturing", "pmi_services", "ism_manufacturing",
}


def _validate_and_dedupe_predictions(raw: list) -> list[dict]:
    """Filter to predictions that look structurally sound and dedupe
    across chunks. Handles both ticker_call and sector_call objects.

    Ticker calls dedupe on (ticker, direction). Sector calls dedupe on
    (sector_lower, direction) and are marked with _kind='sector_call'
    so the caller can route them to the sector insertion path. Ticker
    calls get _kind='ticker_call' for symmetry.

    The classifier occasionally returns the same prediction twice when
    a transcript repeats a take, and chunked transcripts overlap by 2k
    chars so the same sentence may be classified twice.
    """
    seen_tickers: set[tuple[str, str]] = set()
    seen_sectors: set[tuple[str, str]] = set()
    seen_macros: set[tuple[str, str]] = set()
    seen_pairs: set[tuple[str, str]] = set()
    seen_binary_events: set[tuple[str, str]] = set()
    seen_metrics: set[tuple[str, str, str]] = set()
    seen_conditionals: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for p in raw:
        if not isinstance(p, dict):
            continue

        # Pair call branch: derived_from='pair_call' with pair_long_ticker
        # and pair_short_ticker. Both legs must be present, valid ticker
        # shape, and different from each other. Dedupe on
        # (long_upper, short_upper) so repeated mentions collapse.
        # Direction is always bullish on the spread.
        if str(p.get("derived_from") or "").strip().lower() == "pair_call":
            long_t = (p.get("pair_long_ticker") or "").upper().strip().lstrip("$")
            short_t = (p.get("pair_short_ticker") or "").upper().strip().lstrip("$")
            long_t = re.sub(r"[^A-Z0-9]", "", long_t)
            short_t = re.sub(r"[^A-Z0-9]", "", short_t)
            if not long_t or not short_t:
                continue
            if len(long_t) > 5 or len(short_t) > 5:
                continue
            if long_t == short_t:
                continue
            key = (long_t, short_t)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            # Stamp a bullish direction regardless of what Haiku emitted —
            # pair_call has no bearish/neutral variant. Also stamp a
            # placeholder `ticker` so downstream code that touches p["ticker"]
            # (error logging, rejection context, etc.) doesn't KeyError.
            p["direction"] = "bullish"
            p["pair_long_ticker"] = long_t
            p["pair_short_ticker"] = short_t
            p["_kind"] = "pair_call"
            p["_pair_long"] = long_t
            p["_pair_short"] = short_t
            p["_derived_from"] = "pair_call"
            if not p.get("ticker"):
                p["ticker"] = long_t
            out.append(p)
            continue

        # Binary-event call branch: derived_from='binary_event_call'
        # with expected_outcome_text, event_type (from allowlist), and
        # event_deadline. Direction is always bullish (negations live
        # inside expected_outcome_text). ticker is optional for
        # fed_decision / economic_declaration; required for the others
        # but the insert path (not the validator) makes the final call.
        # Dedupe on (event_type, md5(expected_outcome_text_lower)) so
        # duplicate mentions collapse.
        if str(p.get("derived_from") or "").strip().lower() == "binary_event_call":
            raw_evtype = (p.get("event_type") or "").strip().lower()
            if raw_evtype not in _BINARY_EVENT_TYPES:
                continue
            outcome_text = (p.get("expected_outcome_text") or "").strip()
            if not outcome_text or len(outcome_text) > 500:
                continue
            raw_deadline = p.get("event_deadline")
            if not raw_deadline:
                continue
            try:
                from datetime import datetime as _dt
                deadline = _dt.strptime(str(raw_deadline)[:10], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            # Hash the outcome text (lowercased, collapsed whitespace)
            # for a stable dedup key — different wordings of the same
            # event still collide if Haiku happens to reuse the key.
            _norm = re.sub(r"\s+", " ", outcome_text.lower()).strip()
            _digest = hashlib.md5(_norm.encode("utf-8")).hexdigest()[:16]
            key = (raw_evtype, _digest)
            if key in seen_binary_events:
                continue
            seen_binary_events.add(key)
            p["direction"] = "bullish"  # always bullish-on-event-happening
            p["_kind"] = "binary_event_call"
            p["_event_type"] = raw_evtype
            p["_expected_outcome_text"] = outcome_text[:500]
            p["_event_deadline"] = deadline
            p["_outcome_digest"] = _digest
            p["_derived_from"] = "binary_event_call"
            # Normalize ticker if present (may be None for fed_decision
            # and economic_declaration). Stamp a placeholder `ticker`
            # field so downstream logging doesn't KeyError.
            raw_tkr = (p.get("ticker") or "").upper().strip().lstrip("$")
            raw_tkr = re.sub(r"[^A-Z0-9]", "", raw_tkr)
            if raw_tkr and len(raw_tkr) <= 5:
                p["ticker"] = raw_tkr
            else:
                p["ticker"] = f"__event__{raw_evtype}"
            out.append(p)
            continue

        # Metric-forecast branch: derived_from='metric_forecast_call'
        # with metric_type (from allowlist), numeric metric_target, and
        # metric_release_date. Direction is "bullish"/"bearish"/"neutral"
        # — it's a free choice (forecaster may frame as beat or just
        # quote a number). ticker required for company metrics,
        # optional for macro metrics. Dedupe on
        # (metric_type, metric_period_or_release, target-rounded) so
        # repeated mentions of the same forecast collapse.
        if str(p.get("derived_from") or "").strip().lower() == "metric_forecast_call":
            mt = (p.get("metric_type") or "").strip().lower()
            if mt not in _METRIC_FORECAST_TYPES:
                continue
            raw_target = p.get("metric_target")
            try:
                target_num = float(raw_target)
            except (TypeError, ValueError):
                continue
            # Sanity bound — reject absurd values to catch parse errors.
            # Allow negative (e.g. negative EPS losses, negative growth).
            if not (-1e15 < target_num < 1e15):
                continue
            raw_release = p.get("metric_release_date")
            if not raw_release:
                continue
            try:
                from datetime import datetime as _dt
                release = _dt.strptime(str(raw_release)[:10], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            mp = (p.get("metric_period") or "").strip()[:16] or None
            direction = (p.get("direction") or "neutral").strip().lower()
            if direction not in _VALID_DIRECTIONS:
                direction = "neutral"
            # Dedup key: (metric_type, period-or-release-iso, rounded-target).
            # Rounding target to 6 sig figures so "$5.20" and "$5.200001"
            # collapse. Period used when present for company metrics;
            # release_date used for macro metrics.
            period_key = mp or release.isoformat()
            target_key = f"{target_num:.6g}"
            key = (mt, period_key, target_key)
            if key in seen_metrics:
                continue
            seen_metrics.add(key)
            # Normalize ticker (may be absent for macro metrics).
            raw_tkr = (p.get("ticker") or "").upper().strip().lstrip("$")
            raw_tkr = re.sub(r"[^A-Z0-9]", "", raw_tkr)
            if raw_tkr and len(raw_tkr) <= 5:
                p["ticker"] = raw_tkr
            else:
                # Macro metric placeholder so downstream logging
                # doesn't KeyError on p["ticker"]. The insert path
                # rewrites this to a sentinel for storage.
                p["ticker"] = f"__metric__{mt}"
            p["direction"] = direction
            p["_kind"] = "metric_forecast_call"
            p["_metric_type"] = mt
            p["_metric_target"] = target_num
            p["_metric_period"] = mp
            p["_metric_release_date"] = release
            p["_derived_from"] = "metric_forecast_call"
            out.append(p)
            continue

        # Sector call branch: type='sector_call' with sector + direction
        if str(p.get("type") or "").strip().lower() == "sector_call":
            sector_name = (p.get("sector") or "").strip()
            direction = (p.get("direction") or "").strip().lower()
            if not sector_name or direction not in _SECTOR_VALID_DIRECTIONS:
                continue
            key = (sector_name.lower(), direction)
            if key in seen_sectors:
                continue
            seen_sectors.add(key)
            p["sector"] = sector_name
            p["direction"] = direction
            p["_kind"] = "sector_call"
            out.append(p)
            continue

        # Conditional call branch: derived_from='conditional_call' with
        # trigger_condition + trigger_type required. The "outcome" side
        # uses normal ticker/direction/target_price/timeframe fields,
        # so this branch does extra validation on the trigger side
        # and stamps _trigger_* keys for the insert path. Dedup key is
        # (ticker_upper, trigger_condition_lower, direction) since the
        # same ticker can appear in two conditionals with different
        # triggers (e.g. "if SPY holds 450 → AAPL bullish" vs "if Fed
        # cuts → AAPL bullish") and both are legitimately distinct
        # predictions.
        if str(p.get("derived_from") or "").strip().lower() == "conditional_call":
            ticker_val = (p.get("ticker") or "").upper().strip().lstrip("$")
            ticker_val = re.sub(r"[^A-Z0-9]", "", ticker_val)
            direction = (p.get("direction") or "").strip().lower()
            trig_cond = (p.get("trigger_condition") or "").strip()
            trig_type = (p.get("trigger_type") or "").strip().lower()
            if not ticker_val or len(ticker_val) > 5:
                continue
            if direction not in _VALID_DIRECTIONS:
                continue
            if not trig_cond or not trig_type:
                continue
            if trig_type not in (
                "price_hold", "price_break", "economic_data",
                "fed_decision", "market_event", "corporate_action", "other",
            ):
                continue
            trig_ticker = None
            trig_price = None
            if trig_type in ("price_hold", "price_break"):
                raw_tt = (p.get("trigger_ticker") or "").upper().strip().lstrip("$")
                raw_tt = re.sub(r"[^A-Z0-9]", "", raw_tt)
                if not raw_tt or len(raw_tt) > 5:
                    continue  # price triggers require a ticker
                trig_ticker = raw_tt
                raw_tp = p.get("trigger_price")
                try:
                    trig_price = float(raw_tp) if raw_tp is not None else None
                    if trig_price is None or trig_price <= 0:
                        continue  # price triggers require a positive threshold
                except (TypeError, ValueError):
                    continue
            # Dedup by (ticker, trigger_condition.lower(), direction)
            key = (ticker_val, trig_cond.strip().lower()[:200], direction)
            if key in seen_conditionals:
                continue
            seen_conditionals.add(key)
            # Parse optional trigger_deadline as ISO date → datetime.date
            raw_dl = p.get("trigger_deadline")
            trig_deadline = None
            if raw_dl:
                try:
                    from datetime import datetime as _dt
                    trig_deadline = _dt.strptime(
                        str(raw_dl)[:10], "%Y-%m-%d"
                    ).date()
                except (TypeError, ValueError):
                    trig_deadline = None
            p["ticker"] = ticker_val
            p["direction"] = direction
            p["_kind"] = "conditional_call"
            p["_derived_from"] = "conditional_call"
            p["_trigger_condition"] = trig_cond[:500]
            p["_trigger_type"] = trig_type
            p["_trigger_ticker"] = trig_ticker
            p["_trigger_price"] = trig_price
            p["_trigger_deadline"] = trig_deadline
            out.append(p)
            continue

        # Macro call branch: derived_from='macro_call' with a `concept`
        # field. The `ticker` field may be missing — the insert path
        # resolves the concept to a tradeable ETF via macro_concept_aliases.
        # Dedupe on (concept_lower, direction) so duplicate mentions of
        # the same concept/direction across transcript chunks collapse.
        # Dropping this row here when the ticker check below would have
        # rejected it is critical — macro_call predictions are the only
        # kind that legitimately arrive with no ticker.
        if str(p.get("derived_from") or "").strip().lower() == "macro_call":
            concept_name = (p.get("concept") or "").strip().lower()
            direction = (p.get("direction") or "").strip().lower()
            if not concept_name or direction not in _VALID_DIRECTIONS:
                continue
            # Normalize concept to snake_case-ish (spaces → underscores,
            # keep alphanumerics and underscores only)
            concept_name = re.sub(r"[^a-z0-9_]+", "_", concept_name).strip("_")
            if not concept_name:
                continue
            key = (concept_name, direction)
            if key in seen_macros:
                continue
            seen_macros.add(key)
            p["direction"] = direction
            p["_kind"] = "macro_call"
            p["_concept"] = concept_name
            p["_derived_from"] = "macro_call"
            # No ticker yet — insert path will resolve the concept to
            # an ETF via macro_concept_aliases. Stamp a placeholder so
            # the caller can still access p["ticker"] without a KeyError
            # during logging.
            if not p.get("ticker"):
                p["ticker"] = f"__macro__{concept_name}"
            out.append(p)
            continue

        ticker = (p.get("ticker") or "").upper().strip().lstrip("$")
        direction = (p.get("direction") or "").strip().lower()
        if not ticker or not direction:
            continue
        if direction not in _VALID_DIRECTIONS:
            continue
        # Ticker shape: 1-5 alphanumeric chars (BTC, NVDA, GOOGL, BRK.B → BRKB)
        ticker = re.sub(r"[^A-Z0-9]", "", ticker)
        if not ticker or len(ticker) > 5:
            continue
        # Ranked-list metadata: both fields must be present or both absent.
        # Predictions with only one half get _list_error set so the caller
        # can skip them and log a classifier_error. Otherwise the two
        # fields are normalized (list_id → string ≤40 chars, list_rank →
        # int 1-10 capped) and attached to the pred dict for the insert
        # path to pick up. Unrelated to dedup: two rows on the same
        # ticker with different list_rank would dedupe away on (ticker,
        # direction) anyway, which is the intended behavior.
        raw_list_id = p.get("list_id")
        raw_list_rank = p.get("list_rank")
        list_id = None
        list_rank = None
        list_error = None
        has_id = raw_list_id is not None and str(raw_list_id).strip() != ""
        has_rank = raw_list_rank is not None and str(raw_list_rank).strip() != ""
        if has_id != has_rank:
            list_error = "list_fields_mismatched"
        elif has_id and has_rank:
            list_id = re.sub(r"\s+", "_", str(raw_list_id).strip().lower())[:40]
            try:
                list_rank = int(raw_list_rank)
            except (TypeError, ValueError):
                list_rank = None
            if list_rank is None or list_rank < 1:
                list_error = "list_rank_invalid"
            elif list_rank > 10:
                # Hard cap: trim anything beyond top 10. Drop the list
                # metadata entirely for rows past position 10 so they
                # fall through as unranked picks (per spec).
                list_id = None
                list_rank = None
        # Revision metadata: is_revision=true flags this prediction as
        # a target revision. previous_target / revision_direction are
        # free-form hints from Haiku used only for logging — the actual
        # revision_of FK is resolved at insert time by looking up the
        # forecaster's most recent prior prediction on this ticker.
        is_revision = bool(p.get("is_revision"))
        raw_prev = p.get("previous_target")
        prev_target_hint = None
        if raw_prev is not None:
            try:
                prev_target_hint = float(raw_prev)
                if not (0.0 < prev_target_hint < 1_000_000):
                    prev_target_hint = None
            except (TypeError, ValueError):
                prev_target_hint = None
        rev_dir = (p.get("revision_direction") or "").strip().lower() or None
        if rev_dir not in (None, "up", "down", "direction_change"):
            rev_dir = None
        # derived_from marker. Haiku sets this on predictions it mapped
        # from specialized vocabulary. Not stored in the DB — only used
        # by the insert path to route the row and increment the per-run
        # counter for the matching sub-type. Canonical values:
        # 'options_position', 'earnings_call', 'macro_call', 'pair_call',
        # 'binary_event_call', 'metric_forecast_call', 'conditional_call'.
        # pair_call, binary_event_call, metric_forecast_call, and
        # conditional_call rows never reach this branch (they're handled
        # above and skipped via `continue`) but we keep those values in
        # the accepted set for symmetry with future refactors.
        raw_derived = p.get("derived_from")
        derived_from = None
        if raw_derived is not None:
            _rd = str(raw_derived).strip().lower()
            if _rd in (
                "options_position", "earnings_call", "macro_call",
                "pair_call", "binary_event_call", "metric_forecast_call",
                "conditional_call",
            ):
                derived_from = _rd

        # Event metadata for earnings_call (and future event-tied types).
        # Only stamped when derived_from == 'earnings_call' AND Haiku
        # supplied event_type='earnings'. event_date is parsed as ISO
        # YYYY-MM-DD; unparseable values fall through to None so the
        # evaluator's future lookup path handles them.
        event_type_val = None
        event_date_val = None
        if derived_from == "earnings_call":
            raw_evtype = (p.get("event_type") or "").strip().lower()
            if raw_evtype == "earnings":
                event_type_val = "earnings"
            raw_evdate = p.get("event_date")
            if raw_evdate:
                try:
                    from datetime import datetime as _dt
                    event_date_val = _dt.strptime(
                        str(raw_evdate)[:10], "%Y-%m-%d"
                    ).date()
                except (TypeError, ValueError):
                    event_date_val = None
        key = (ticker, direction)
        if key in seen_tickers:
            continue
        seen_tickers.add(key)
        p["ticker"] = ticker
        p["direction"] = direction
        p["_kind"] = "ticker_call"
        p["_list_id"] = list_id
        p["_list_rank"] = list_rank
        if list_error:
            p["_list_error"] = list_error
        p["_is_revision"] = is_revision
        p["_previous_target_hint"] = prev_target_hint
        p["_revision_direction_hint"] = rev_dir
        p["_derived_from"] = derived_from
        p["_event_type"] = event_type_val
        p["_event_date"] = event_date_val
        out.append(p)
    return out


def validate_ticker_in_db(ticker: str, db) -> bool:
    """Verify the ticker exists in ticker_sectors (covers ~12k US stocks).

    This is the per-video safeguard against transcript hallucinations:
    auto-captions transcribe "NVIDIA" as "INVIDIA" or "in video", and
    the classifier may invent a ticker from the malformed string.
    Anything not in ticker_sectors gets dropped.
    """
    if not ticker:
        return False
    try:
        row = db.execute(
            sql_text("SELECT 1 FROM ticker_sectors WHERE ticker = :t LIMIT 1"),
            {"t": ticker.upper()},
        ).first()
        return row is not None
    except Exception:
        # If ticker_sectors is unreadable, fail OPEN — don't drop the
        # prediction over an infrastructure issue.
        return True


# ── Forecaster lookup / creation ────────────────────────────────────────────

def find_or_create_youtube_forecaster(channel_name: str, channel_id: str | None, db):
    """Find a YouTube forecaster by name, or create one with platform='youtube'.

    Mirrors the find_forecaster pattern in news_scraper.py but is tailored
    for YouTube channels: it ALWAYS creates if missing (no alias gating),
    fills in channel_id and channel_url on first sight, and stamps
    platform='youtube' so dashboards can distinguish social-media
    forecasters from institutional analysts.
    """
    from models import Forecaster
    if not channel_name or not channel_name.strip():
        return None
    name = channel_name.strip()

    # 1. Exact name match
    f = db.query(Forecaster).filter(Forecaster.name == name).first()
    if not f:
        # 2. Case-insensitive
        f = db.query(Forecaster).filter(Forecaster.name.ilike(name)).first()
    if f:
        # Backfill channel metadata if it's missing
        changed = False
        if not f.platform:
            f.platform = "youtube"
            changed = True
        if channel_id and not f.channel_id:
            f.channel_id = channel_id
            f.channel_url = f"https://www.youtube.com/channel/{channel_id}"
            changed = True
        if changed:
            db.flush()
        return f

    # 3. Create
    handle_base = re.sub(r"[^a-zA-Z0-9]", "", name).lower()[:30]
    if not handle_base:
        handle_base = f"yt{(channel_id or '')[:10]}".lower() or "ytchannel"
    handle = handle_base
    # Ensure handle is unique
    suffix = 0
    while db.query(Forecaster).filter(Forecaster.handle == handle).first() is not None:
        suffix += 1
        handle = f"{handle_base}{suffix}"
        if suffix > 100:
            handle = f"yt_{(channel_id or 'x')[:8]}_{suffix}"
            break

    f = Forecaster(
        name=name,
        handle=handle,
        platform="youtube",
        channel_id=channel_id,
        channel_url=f"https://www.youtube.com/channel/{channel_id}" if channel_id else None,
    )
    db.add(f)
    db.flush()
    print(f"[YT-CLF] Created forecaster: {name} ({handle})", flush=True)
    return f


# ── Prediction insertion ────────────────────────────────────────────────────

def _parse_evaluation_date(timeframe_str, prediction_date: datetime) -> tuple[datetime, int]:
    """Convert the classifier's timeframe (absolute date string) into an
    evaluation_date and a window_days integer.

    The prompt tells Haiku to emit absolute dates like "2026-12-31". If
    parsing fails or the date is non-positive relative to prediction_date,
    fall back to DEFAULT_EVAL_WINDOW_DAYS days.
    """
    default_eval = prediction_date + timedelta(days=DEFAULT_EVAL_WINDOW_DAYS)
    if not timeframe_str:
        return default_eval, DEFAULT_EVAL_WINDOW_DAYS
    s = str(timeframe_str).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            d = datetime.strptime(s, fmt)
            window = (d - prediction_date).days
            if window <= 0:
                return default_eval, DEFAULT_EVAL_WINDOW_DAYS
            return d, window
        except ValueError:
            continue
    return default_eval, DEFAULT_EVAL_WINDOW_DAYS


def _find_prior_prediction_for_revision(
    db, *, forecaster_id: int, ticker: str,
) -> tuple[int | None, float | None]:
    """Look up the most recent YouTube prediction by this forecaster on
    this ticker to link a revision to. Returns (prior_id, prior_target)
    or (None, None) if no prior exists.

    Flat-chain semantics per spec: we return the IMMEDIATE predecessor
    even if that predecessor is itself a revision. We do NOT walk up the
    chain to find the 'original' — each revision points at the single
    most recent prior, and the full history is a linked list of hops.

    Best-effort: any query failure returns (None, None) and the caller
    inserts the prediction as a standalone call.
    """
    if not forecaster_id or not ticker:
        return None, None
    try:
        row = db.execute(sql_text("""
            SELECT id, target_price
            FROM predictions
            WHERE forecaster_id = :fid
              AND ticker = :ticker
              AND source_type = 'youtube'
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT 1
        """), {"fid": int(forecaster_id), "ticker": ticker.upper()}).first()
    except Exception as _e:
        log.warning("[YT-CLF] revision prior lookup failed: %s", _e)
        return None, None
    if not row:
        return None, None
    prior_id = int(row[0])
    prior_target = float(row[1]) if row[1] is not None else None
    return prior_id, prior_target


def insert_youtube_prediction(
    pred: dict,
    *,
    channel_name: str,
    channel_id: str | None,
    video_id: str,
    video_title: str,
    publish_date: datetime,
    db,
    transcript_snippet: str | None = None,
    stats: dict | None = None,
) -> bool:
    """Insert one classifier-extracted prediction following the
    massive_benzinga.py pattern.

    Returns True on successful db.add(), False on dedup / forecaster
    miss / ticker rejection / validation failure. The caller should
    db.commit() in batches; this function only flushes.

    Behavior:
      - source_type='youtube'
      - verified_by='youtube_haiku_v1'
      - source_url=https://www.youtube.com/watch?v={video_id}
      - source_platform_id=yt_{video_id}_{ticker} (per-video-per-ticker dedup)
      - target_price from classifier (parsed to float, sanity-bounded)
      - entry_price LEFT NULL — the evaluator looks it up at scoring time
      - prediction_date = video publish date
      - evaluation_date = classifier-supplied absolute date or +90 days
      - context = "Channel: <quote> [reasoning]" capped at 500 chars
      - Cross-scraper dedup via prediction_exists_cross_scraper(...)

    Rejection logging: every False return path now writes a row to
    youtube_scraper_rejections so the admin Social Scrapers card can
    surface the funnel breakdown. transcript_snippet/stats are optional
    so existing callers (e.g. youtube_backfill) keep working unchanged.
    """
    from models import Prediction
    from jobs.prediction_validator import prediction_exists_cross_scraper

    def _reject(reason: str, hr: str | None = None) -> bool:
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=video_title,
            video_published_at=publish_date,
            reason=reason,
            haiku_reason=hr,
            haiku_raw=pred,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return False

    ticker = (pred.get("ticker") or "").upper().strip().lstrip("$")
    direction = (pred.get("direction") or "").strip().lower()

    if not ticker:
        return _reject("invalid_ticker")
    if direction not in _VALID_DIRECTIONS:
        return _reject("neutral_or_no_direction", hr=direction or None)

    # Ranked-list metadata (pre-validated by _validate_and_dedupe_predictions).
    # Both-or-neither invariant enforced there: if the validator flagged a
    # mismatch, log the classifier_error and skip the row.
    if pred.get("_list_error"):
        return _reject("classifier_error", hr=pred.get("_list_error"))
    list_id_val = pred.get("_list_id")
    list_rank_val = pred.get("_list_rank")

    # Revision linkage: if Haiku flagged this as a target revision, look
    # up the forecaster's most recent prior prediction on this ticker
    # and set revision_of. We DON'T drop the prediction if no prior is
    # found — first-time calls wrongly tagged as revisions still get
    # inserted as standalone calls, per spec ("better than dropping it").
    # Note: the find_or_create_youtube_forecaster call below is the
    # source of the forecaster_id we need, so the prior lookup happens
    # AFTER we resolve the forecaster.
    revision_of_val: int | None = None

    # Per-video-per-ticker dedup. Same video may produce multiple tickers,
    # but the same (video, ticker) pair should only insert once even if
    # the classifier returns it twice across chunks.
    source_id = f"yt_{video_id}_{ticker}"
    if db.execute(
        sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=ticker)

    # Ticker validation against ticker_sectors
    if not validate_ticker_in_db(ticker, db):
        return _reject("invalid_ticker", hr=ticker)

    # Forecaster
    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    # Resolve the revision_of link if Haiku flagged this as a revision.
    # Flat chain: we link to the IMMEDIATE prior prediction even if it's
    # itself a revision. Missing-prior case (first-time call wrongly
    # tagged as a revision) → insert as standalone, log a note, do NOT
    # drop the prediction.
    if pred.get("_is_revision"):
        prior_id, prior_target = _find_prior_prediction_for_revision(
            db, forecaster_id=forecaster.id, ticker=ticker,
        )
        if prior_id is not None:
            revision_of_val = prior_id
            _rev_dir = pred.get("_revision_direction_hint") or "?"
            _prior_hint = pred.get("_previous_target_hint")
            _new_hint = pred.get("target_price")
            print(
                f"[YOUTUBE-HAIKU] Revision linked: {channel_name} {ticker} "
                f"→ prior_id={prior_id} dir={_rev_dir} "
                f"({_prior_hint} → {_new_hint})",
                flush=True,
            )
        else:
            print(
                f"[YOUTUBE-HAIKU] Revision claimed on {ticker} by "
                f"{channel_name} but no prior prediction found — "
                f"inserting as standalone call",
                flush=True,
            )

    # Cross-scraper dedup (within 24h of the prediction_date)
    if prediction_exists_cross_scraper(ticker, forecaster.id, direction, publish_date, db):
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("cross_scraper_dupe", hr=ticker)

    # Evaluation date / window
    eval_date, window_days = _parse_evaluation_date(pred.get("timeframe"), publish_date)

    # Target price (sanity-bound to [0.5, 100000] same as massive_benzinga)
    target_price = pred.get("price_target")
    if target_price is not None:
        try:
            target_price = float(target_price)
            if not (0.5 < target_price < 100_000):
                target_price = None
        except (ValueError, TypeError):
            target_price = None

    # Build a compact human-readable context
    quote = (pred.get("quote") or "").strip()
    reasoning = (pred.get("reasoning") or "").strip()
    parts = [f"{channel_name}: {direction.capitalize()} on {ticker}"]
    if target_price is not None:
        parts.append(f"target ${target_price:g}")
    if quote:
        parts.append(f"\"{quote[:120]}\"")
    elif reasoning:
        parts.append(reasoning[:120])
    context_str = ". ".join(parts)[:500]

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    # Sector lookup (best-effort, mirrors massive_benzinga)
    sector = None
    try:
        from jobs.sector_lookup import get_sector
        sector = get_sector(ticker, db)
    except Exception:
        sector = None

    # Event metadata: for earnings_call predictions, stamp event_type
    # and event_date so the evaluator can route them to the earnings-
    # reaction scoring path. For plain ticker_call rows both stay NULL.
    event_type_val = pred.get("_event_type")
    event_date_val = pred.get("_event_date")

    db.add(
        Prediction(
            forecaster_id=forecaster.id,
            ticker=ticker,
            direction=direction,
            prediction_date=publish_date,
            evaluation_date=eval_date,
            window_days=window_days,
            target_price=target_price,
            entry_price=None,  # evaluator fills this from price history
            source_url=source_url,
            archive_url=source_url,  # YouTube URLs are permanent — no Wayback needed
            source_type="youtube",
            source_title=(video_title or "")[:500],
            source_platform_id=source_id,
            sector=sector,
            context=context_str,
            exact_quote=(quote or context_str)[:500],
            outcome="pending",
            verified_by=VERIFIED_BY,
            call_type="video_prediction",
            prediction_category="ticker_call",
            list_id=list_id_val,
            list_rank=list_rank_val,
            revision_of=revision_of_val,
            event_type=event_type_val,
            event_date=event_date_val,
        )
    )
    db.flush()
    # Per-run sub-type counters. Options and earnings both land as
    # prediction_category='ticker_call' rows — these counters expose
    # how much of a run's yield came from each specialized prompt block
    # without introducing new categories. Markers are NOT stored in the
    # Prediction row, only read here.
    _derived = pred.get("_derived_from")
    if _derived == "options_position" and stats is not None:
        stats["options_positions_extracted"] = int(
            stats.get("options_positions_extracted", 0)
        ) + 1
    elif _derived == "earnings_call" and stats is not None:
        stats["earnings_calls_extracted"] = int(
            stats.get("earnings_calls_extracted", 0)
        ) + 1
    return True


def insert_youtube_sector_prediction(
    pred: dict,
    *,
    channel_name: str,
    channel_id: str | None,
    video_id: str,
    video_title: str,
    publish_date: datetime,
    db,
    transcript_snippet: str | None = None,
    stats: dict | None = None,
) -> bool:
    """Insert a sector_call prediction.

    Mirrors insert_youtube_prediction but:
      - Resolves the free-form sector name to an ETF ticker via
        feature_flags.map_sector_to_etf
      - Sets prediction_type='sector_call' AND prediction_category='sector_call'
        so the evaluator's existing ETF-vs-SPY spread scorer picks it up
        and the leaderboard can surface sector skill as a separate column
      - target_price is always NULL (sector calls don't use price targets)
      - call_type='sector_call'
      - source_platform_id='yt_<vid>_sector_<canonical>' for dedup

    Returns True on successful insert, False on any rejection. All
    rejection paths log to youtube_scraper_rejections with a specific
    reason tag and increment stats['items_rejected'] via
    log_youtube_rejection.
    """
    from models import Prediction
    from jobs.prediction_validator import prediction_exists_cross_scraper
    from feature_flags import map_sector_to_etf

    def _reject(reason: str, hr: str | None = None) -> bool:
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=video_title,
            video_published_at=publish_date,
            reason=reason,
            haiku_reason=hr,
            haiku_raw=pred,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return False

    sector_name = (pred.get("sector") or "").strip()
    direction = (pred.get("direction") or "").strip().lower()
    if not sector_name:
        return _reject("sector_missing")
    if direction not in ("bullish", "bearish"):
        return _reject("sector_invalid_direction", hr=direction or None)

    etf_ticker = map_sector_to_etf(db, sector_name)
    if not etf_ticker:
        return _reject("sector_etf_unknown", hr=sector_name[:200])

    # Per-video-per-sector dedup. Two separate sectors in the same
    # video insert as separate rows; the same sector mentioned twice
    # collapses to one row.
    canonical = re.sub(r"[^a-z0-9]+", "_", sector_name.lower()).strip("_")[:30]
    source_id = f"yt_{video_id}_sector_{canonical}"
    if db.execute(
        sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=canonical)

    # Forecaster (same find/create as ticker calls)
    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    # Cross-scraper dedup on the mapped ETF
    if prediction_exists_cross_scraper(etf_ticker, forecaster.id, direction, publish_date, db):
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("cross_scraper_dupe", hr=etf_ticker)

    eval_date, window_days = _parse_evaluation_date(pred.get("timeframe"), publish_date)

    quote = (pred.get("context_quote") or pred.get("quote") or "").strip()
    parts = [f"{channel_name}: {direction.capitalize()} on {sector_name} → {etf_ticker}"]
    if quote:
        parts.append(f"\"{quote[:120]}\"")
    context_str = ". ".join(parts)[:500]

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    db.add(
        Prediction(
            forecaster_id=forecaster.id,
            ticker=etf_ticker,
            direction=direction,
            prediction_date=publish_date,
            evaluation_date=eval_date,
            window_days=window_days,
            target_price=None,  # sector calls don't use price targets
            entry_price=None,
            source_url=source_url,
            archive_url=source_url,
            source_type="youtube",
            source_title=(video_title or "")[:500],
            source_platform_id=source_id,
            sector=sector_name,
            context=context_str,
            exact_quote=(quote or context_str)[:500],
            outcome="pending",
            verified_by=VERIFIED_BY,
            call_type="sector_call",
            # Dual-column tagging: prediction_type drives the evaluator's
            # ETF-vs-SPY spread scorer; prediction_category drives the
            # leaderboard's separate-accuracy column.
            prediction_type="sector_call",
            prediction_category="sector_call",
        )
    )
    db.flush()
    if stats is not None:
        stats["sector_calls_extracted"] = int(stats.get("sector_calls_extracted", 0)) + 1
    return True


# ── Macro call insertion ────────────────────────────────────────────────────

# Module-level cache of resolved concept → (primary_etf, direction_bias).
# Populated lazily per monitor run. The monitor process is short-lived
# (12h interval), so letting this grow for the lifetime of one run and
# getting garbage-collected at shutdown is fine. No explicit eviction.
_MACRO_CONCEPT_CACHE: dict[str, tuple[str, str] | None] = {}


def _resolve_macro_concept(db, concept: str) -> tuple[str | None, str | None]:
    """Look up a canonical macro concept in macro_concept_aliases.
    Returns (primary_etf, direction_bias) or (None, None) if the concept
    isn't in the allowlist — which triggers a rejection at the caller.

    Cached per-process so a long classifier run doesn't hit the DB for
    every prediction on the same concept.
    """
    if not concept:
        return None, None
    key = concept.strip().lower()
    if not key:
        return None, None
    if key in _MACRO_CONCEPT_CACHE:
        cached = _MACRO_CONCEPT_CACHE[key]
        if cached is None:
            return None, None
        return cached
    try:
        row = db.execute(sql_text(
            "SELECT primary_etf, direction_bias FROM macro_concept_aliases "
            "WHERE LOWER(concept) = :c LIMIT 1"
        ), {"c": key}).first()
    except Exception as _e:
        log.warning("[YT-CLF] macro concept lookup failed for %s: %s", key, _e)
        return None, None
    if not row:
        _MACRO_CONCEPT_CACHE[key] = None
        return None, None
    primary_etf = (row[0] or "").upper()
    direction_bias = (row[1] or "direct").strip().lower()
    if direction_bias not in ("direct", "inverse"):
        direction_bias = "direct"
    _MACRO_CONCEPT_CACHE[key] = (primary_etf, direction_bias)
    return primary_etf, direction_bias


def insert_youtube_macro_prediction(
    pred: dict,
    *,
    channel_name: str,
    channel_id: str | None,
    video_id: str,
    video_title: str,
    publish_date: datetime,
    db,
    transcript_snippet: str | None = None,
    stats: dict | None = None,
) -> bool:
    """Insert a macro_call prediction.

    Resolves the canonical concept to a tradeable ETF via
    macro_concept_aliases, flips direction if the bias is 'inverse',
    and stores the row as prediction_category='macro_call' (NEW
    category — unlike options/earnings which stay as ticker_call).

    Rejection paths (each logs to youtube_scraper_rejections and
    returns False):
      - missing concept → 'macro_concept_missing'
      - concept not in allowlist → 'macro_concept_not_in_allowlist'
      - invalid direction → 'neutral_or_no_direction'
      - cross-scraper dedup collision → 'cross_scraper_dupe'
      - forecaster create failure → 'forecaster_creation_failed'
    """
    from models import Prediction
    from jobs.prediction_validator import prediction_exists_cross_scraper

    def _reject(reason: str, hr: str | None = None) -> bool:
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=video_title,
            video_published_at=publish_date,
            reason=reason,
            haiku_reason=hr,
            haiku_raw=pred,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return False

    concept = (pred.get("_concept") or pred.get("concept") or "").strip().lower()
    direction = (pred.get("direction") or "").strip().lower()

    if not concept:
        return _reject("macro_concept_missing")
    if direction not in _VALID_DIRECTIONS:
        return _reject("neutral_or_no_direction", hr=direction or None)

    etf_ticker, direction_bias = _resolve_macro_concept(db, concept)
    if not etf_ticker:
        return _reject("macro_concept_not_in_allowlist", hr=concept[:200])

    # Inverse bias flips bullish ↔ bearish before storing. Neutral passes
    # through unchanged (hedging on an inverse-ETF is still hedging).
    stored_direction = direction
    if direction_bias == "inverse":
        if direction == "bullish":
            stored_direction = "bearish"
        elif direction == "bearish":
            stored_direction = "bullish"

    # Per-video-per-concept dedup. Two concepts in the same video insert
    # as separate rows; the same concept mentioned twice collapses via
    # source_platform_id uniqueness.
    canonical = re.sub(r"[^a-z0-9]+", "_", concept).strip("_")[:40]
    source_id = f"yt_{video_id}_macro_{canonical}"
    if db.execute(
        sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=canonical)

    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    if prediction_exists_cross_scraper(
        etf_ticker, forecaster.id, stored_direction, publish_date, db,
    ):
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("cross_scraper_dupe", hr=etf_ticker)

    eval_date, window_days = _parse_evaluation_date(
        pred.get("timeframe"), publish_date,
    )

    # Target price: macro_call usually doesn't carry a price target
    # (forecasters speak in concept terms, not ETF price levels).
    # If Haiku did extract one, sanity-bound it the same way as ticker calls.
    target_price = pred.get("price_target")
    if target_price is not None:
        try:
            target_price = float(target_price)
            if not (0.5 < target_price < 100_000):
                target_price = None
        except (ValueError, TypeError):
            target_price = None

    quote = (pred.get("context_quote") or pred.get("quote") or "").strip()
    parts = [
        f"{channel_name}: {stored_direction.capitalize()} on "
        f"{concept} → {etf_ticker}"
    ]
    if direction_bias == "inverse" and direction != stored_direction:
        parts.append(f"(flipped from {direction} via inverse bias)")
    if quote:
        parts.append(f'"{quote[:120]}"')
    context_str = ". ".join(parts)[:500]

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    db.add(
        Prediction(
            forecaster_id=forecaster.id,
            ticker=etf_ticker,
            direction=stored_direction,
            prediction_date=publish_date,
            evaluation_date=eval_date,
            window_days=window_days,
            target_price=target_price,
            entry_price=None,
            source_url=source_url,
            archive_url=source_url,
            source_type="youtube",
            source_title=(video_title or "")[:500],
            source_platform_id=source_id,
            sector=None,
            context=context_str,
            exact_quote=(quote or context_str)[:500],
            outcome="pending",
            verified_by=VERIFIED_BY,
            call_type="macro_call",
            prediction_category="macro_call",
            macro_concept=concept,
        )
    )
    db.flush()
    if stats is not None:
        stats["macro_calls_extracted"] = int(
            stats.get("macro_calls_extracted", 0)
        ) + 1
    return True


def _pair_call_exists_cross_scraper(
    long_ticker: str, short_ticker: str,
    forecaster_id: int, prediction_date, db,
) -> bool:
    """Pair-call variant of prediction_exists_cross_scraper. Same 24-hour
    window but keyed on the canonical pair identity (long, short,
    forecaster, date) rather than on (ticker, direction) — two separate
    pair calls from the same forecaster with different legs should both
    insert even though they share ticker=long_ticker. Returns True if a
    matching pair row already exists from any scraper."""
    if not (long_ticker and short_ticker and forecaster_id and prediction_date):
        return False
    try:
        from datetime import timedelta
        date_start = prediction_date - timedelta(hours=24)
        date_end = prediction_date + timedelta(hours=24)
        row = db.execute(sql_text("""
            SELECT 1 FROM predictions
            WHERE pair_long_ticker = :long
              AND pair_short_ticker = :short
              AND forecaster_id = :fid
              AND prediction_date BETWEEN :ds AND :de
            LIMIT 1
        """), {
            "long": long_ticker,
            "short": short_ticker,
            "fid": int(forecaster_id),
            "ds": date_start,
            "de": date_end,
        }).first()
    except Exception as _e:
        log.warning("[YT-CLF] pair_call cross-scraper dedup failed: %s", _e)
        return False
    return row is not None


def insert_youtube_pair_prediction(
    pred: dict,
    *,
    channel_name: str,
    channel_id: str | None,
    video_id: str,
    video_title: str,
    publish_date: datetime,
    db,
    transcript_snippet: str | None = None,
    stats: dict | None = None,
) -> bool:
    """Insert a pair_call prediction.

    Stores the row with prediction_category='pair_call' (NEW category)
    and both pair_long_ticker / pair_short_ticker set. The `ticker`
    column is set to the long leg so the existing ticker index still
    covers it. Direction is always bullish on the spread — there is no
    bearish/neutral pair_call. No price target (target is implicit).

    Rejection paths (each logs to youtube_scraper_rejections and
    returns False):
      - missing or invalid long/short leg → 'pair_call_missing_leg'
      - same symbol on both sides → 'pair_call_same_symbol'
      - long leg not in ticker_sectors → 'pair_call_invalid_long'
      - short leg not in ticker_sectors → 'pair_call_invalid_short'
      - per-video pair dedup hit → 'dedup_collision'
      - cross-scraper pair dedup hit → 'cross_scraper_dupe'
      - forecaster create failure → 'forecaster_creation_failed'
    """
    from models import Prediction

    def _reject(reason: str, hr: str | None = None) -> bool:
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=video_title,
            video_published_at=publish_date,
            reason=reason,
            haiku_reason=hr,
            haiku_raw=pred,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return False

    long_ticker = (
        pred.get("_pair_long") or pred.get("pair_long_ticker") or ""
    ).upper().strip().lstrip("$")
    short_ticker = (
        pred.get("_pair_short") or pred.get("pair_short_ticker") or ""
    ).upper().strip().lstrip("$")
    long_ticker = re.sub(r"[^A-Z0-9]", "", long_ticker)
    short_ticker = re.sub(r"[^A-Z0-9]", "", short_ticker)

    if not long_ticker or not short_ticker:
        return _reject("pair_call_missing_leg", hr=f"{long_ticker}/{short_ticker}")
    if long_ticker == short_ticker:
        return _reject("pair_call_same_symbol", hr=long_ticker)

    # Both legs must exist in ticker_sectors — same hallucination guard
    # ticker_call uses. Fail closed on the long leg first so the rejection
    # reason points at the specific side that was bad.
    if not validate_ticker_in_db(long_ticker, db):
        return _reject("pair_call_invalid_long", hr=long_ticker)
    if not validate_ticker_in_db(short_ticker, db):
        return _reject("pair_call_invalid_short", hr=short_ticker)

    # Per-video dedup via a canonical source_platform_id. Two different
    # pairs in the same video insert as separate rows; the same pair
    # mentioned twice collapses.
    source_id = f"yt_{video_id}_pair_{long_ticker}_{short_ticker}"
    if db.execute(
        sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=f"{long_ticker}/{short_ticker}")

    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    # Cross-scraper dedup on (long, short, forecaster, date). Unlike
    # ticker_call this deliberately does NOT use (ticker, direction)
    # because the same forecaster can hold simultaneous pair calls with
    # overlapping long legs (e.g. long NVDA/short INTC and long NVDA/
    # short AMD) and both are independent bets.
    if _pair_call_exists_cross_scraper(
        long_ticker, short_ticker, forecaster.id, publish_date, db,
    ):
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("cross_scraper_dupe", hr=f"{long_ticker}/{short_ticker}")

    eval_date, window_days = _parse_evaluation_date(
        pred.get("timeframe"), publish_date,
    )

    quote = (pred.get("context_quote") or pred.get("quote") or "").strip()
    parts = [f"{channel_name}: Long {long_ticker} / Short {short_ticker}"]
    if quote:
        parts.append(f'"{quote[:120]}"')
    context_str = ". ".join(parts)[:500]

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    db.add(
        Prediction(
            forecaster_id=forecaster.id,
            ticker=long_ticker,  # long leg fills the ticker index slot
            direction="bullish",  # always bullish on the spread
            prediction_date=publish_date,
            evaluation_date=eval_date,
            window_days=window_days,
            target_price=None,  # pair_call has no explicit price target
            entry_price=None,
            source_url=source_url,
            archive_url=source_url,
            source_type="youtube",
            source_title=(video_title or "")[:500],
            source_platform_id=source_id,
            sector=None,
            context=context_str,
            exact_quote=(quote or context_str)[:500],
            outcome="pending",
            verified_by=VERIFIED_BY,
            call_type="pair_call",
            prediction_category="pair_call",
            pair_long_ticker=long_ticker,
            pair_short_ticker=short_ticker,
        )
    )
    db.flush()
    if stats is not None:
        stats["pair_calls_extracted"] = int(
            stats.get("pair_calls_extracted", 0)
        ) + 1
    return True


def _binary_event_exists_cross_scraper(
    event_type: str, outcome_digest: str,
    forecaster_id: int, prediction_date, db,
) -> bool:
    """Binary-event variant of prediction_exists_cross_scraper.

    Dedup key is (event_type, md5(expected_outcome_text), forecaster, date)
    rather than (ticker, direction) because:
      - Two binary events for the same ticker at the same time are
        independent bets (e.g. "AAPL will split AND AAPL will raise
        dividend" should both insert).
      - The outcome digest collapses different wordings of the same
        event into one cross-scraper row.
      - fed_decision / economic_declaration events may carry no ticker
        at all, so a ticker-keyed dedup would over-match.

    Returns True if a matching event row already exists for this
    forecaster within a 24h window, False otherwise.
    """
    if not (event_type and outcome_digest and forecaster_id and prediction_date):
        return False
    try:
        from datetime import timedelta
        date_start = prediction_date - timedelta(hours=24)
        date_end = prediction_date + timedelta(hours=24)
        row = db.execute(sql_text("""
            SELECT 1 FROM predictions
            WHERE prediction_category = 'binary_event_call'
              AND event_type = :et
              AND forecaster_id = :fid
              AND source_platform_id LIKE :digest_like
              AND prediction_date BETWEEN :ds AND :de
            LIMIT 1
        """), {
            "et": event_type,
            "fid": int(forecaster_id),
            "digest_like": f"%_{outcome_digest}",
            "ds": date_start,
            "de": date_end,
        }).first()
    except Exception as _e:
        log.warning("[YT-CLF] binary_event cross-scraper dedup failed: %s", _e)
        return False
    return row is not None


def insert_youtube_binary_event_prediction(
    pred: dict,
    *,
    channel_name: str,
    channel_id: str | None,
    video_id: str,
    video_title: str,
    publish_date: datetime,
    db,
    transcript_snippet: str | None = None,
    stats: dict | None = None,
) -> bool:
    """Insert a binary_event_call prediction.

    Stores the row with prediction_category='binary_event_call' (NEW
    category) and the reused event_type column plus the four new
    binary-event columns (expected_outcome_text, event_deadline,
    event_resolved_at, event_resolution_source). Direction is always
    bullish — negations live inside expected_outcome_text rather than
    as a bearish variant.

    ticker policy:
      - fed_decision / economic_declaration: ticker may be absent;
        we store a sentinel 'EVENT' in the ticker column (because the
        existing NOT NULL constraint requires a value) and leave the
        row's semantic ticker information in expected_outcome_text.
      - Everything else: ticker is required and must pass
        validate_ticker_in_db. Unknown tickers reject.

    Rejection paths (all log to youtube_scraper_rejections):
      - missing expected_outcome_text → 'binary_event_missing_outcome'
      - missing / unparseable event_deadline → 'binary_event_missing_deadline'
      - event_type not in allowlist → 'binary_event_invalid_type'
      - ticker required but invalid → 'binary_event_invalid_ticker'
      - dedup collision → 'dedup_collision'
      - cross-scraper dedup → 'cross_scraper_dupe'
      - forecaster create failure → 'forecaster_creation_failed'
    """
    from models import Prediction

    def _reject(reason: str, hr: str | None = None) -> bool:
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=video_title,
            video_published_at=publish_date,
            reason=reason,
            haiku_reason=hr,
            haiku_raw=pred,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return False

    event_type = (pred.get("_event_type") or pred.get("event_type") or "").strip().lower()
    outcome_text = (pred.get("_expected_outcome_text") or pred.get("expected_outcome_text") or "").strip()
    deadline = pred.get("_event_deadline")
    digest = (pred.get("_outcome_digest") or "").strip().lower()

    if event_type not in _BINARY_EVENT_TYPES:
        return _reject("binary_event_invalid_type", hr=event_type or None)
    if not outcome_text:
        return _reject("binary_event_missing_outcome")
    if not deadline:
        return _reject("binary_event_missing_deadline")

    # Ticker handling: company-anchored event_types require a real
    # ticker; company-agnostic ones allow a sentinel.
    raw_ticker = (pred.get("ticker") or "").upper().strip().lstrip("$")
    raw_ticker = re.sub(r"[^A-Z0-9]", "", raw_ticker)
    is_company_agnostic = event_type in ("fed_decision", "economic_declaration")
    ticker_to_store: str
    if raw_ticker and not raw_ticker.startswith("EVENT") and len(raw_ticker) <= 5:
        if validate_ticker_in_db(raw_ticker, db):
            ticker_to_store = raw_ticker
        elif is_company_agnostic:
            ticker_to_store = "EVENT"
        else:
            return _reject("binary_event_invalid_ticker", hr=raw_ticker)
    elif is_company_agnostic:
        ticker_to_store = "EVENT"
    else:
        return _reject("binary_event_invalid_ticker", hr=raw_ticker or event_type)

    # Per-video dedup via a canonical source_platform_id that embeds
    # the event_type and outcome digest so two different events in the
    # same video insert as separate rows.
    if not digest:
        _norm = re.sub(r"\s+", " ", outcome_text.lower()).strip()
        digest = hashlib.md5(_norm.encode("utf-8")).hexdigest()[:16]
    source_id = f"yt_{video_id}_event_{event_type}_{digest}"
    if db.execute(
        sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=f"{event_type}/{digest}")

    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    if _binary_event_exists_cross_scraper(
        event_type, digest, forecaster.id, publish_date, db,
    ):
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("cross_scraper_dupe", hr=f"{event_type}/{digest}")

    # Evaluation window: eval_date is the deadline itself — the
    # evaluator polls once per day and scores any binary event whose
    # deadline is in the past. window_days is just the delta from
    # prediction_date to deadline for display purposes.
    from datetime import datetime as _dt
    eval_date = _dt.combine(deadline, _dt.min.time())
    window_days = max(1, (eval_date - publish_date).days) if publish_date else 30

    quote = (pred.get("context_quote") or pred.get("quote") or "").strip()
    parts = [f"{channel_name}: {event_type} — {outcome_text[:160]}"]
    if quote:
        parts.append(f'"{quote[:120]}"')
    context_str = ". ".join(parts)[:500]

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    db.add(
        Prediction(
            forecaster_id=forecaster.id,
            ticker=ticker_to_store,
            direction="bullish",  # always bullish on the event happening
            prediction_date=publish_date,
            evaluation_date=eval_date,
            window_days=window_days,
            target_price=None,  # binary events have no price target
            entry_price=None,
            source_url=source_url,
            archive_url=source_url,
            source_type="youtube",
            source_title=(video_title or "")[:500],
            source_platform_id=source_id,
            sector=None,
            context=context_str,
            exact_quote=(quote or context_str)[:500],
            outcome="pending",
            verified_by=VERIFIED_BY,
            call_type="binary_event_call",
            prediction_category="binary_event_call",
            event_type=event_type,
            expected_outcome_text=outcome_text[:2000],
            event_deadline=deadline,
            # event_resolved_at + event_resolution_source stay NULL
            # until the evaluator confirms the outcome (stubbed — see
            # _score_binary_event for the follow-up-ship TODO).
        )
    )
    db.flush()
    if stats is not None:
        stats["binary_events_extracted"] = int(
            stats.get("binary_events_extracted", 0)
        ) + 1
    return True


def _metric_forecast_exists_cross_scraper(
    metric_type: str, period_key: str, forecaster_id: int, prediction_date, db,
) -> bool:
    """Metric-forecast variant of prediction_exists_cross_scraper.

    Dedup key is (metric_type, metric_period|release_date, forecaster,
    date) within a 24h window. The LIKE match on source_platform_id
    keeps cross-scraper dedup cheap without needing a dedicated
    composite index — the source_id encodes the period_key at insert
    time so a matching row prefix means a matching logical forecast.
    """
    if not (metric_type and period_key and forecaster_id and prediction_date):
        return False
    try:
        from datetime import timedelta
        date_start = prediction_date - timedelta(hours=24)
        date_end = prediction_date + timedelta(hours=24)
        row = db.execute(sql_text("""
            SELECT 1 FROM predictions
            WHERE prediction_category = 'metric_forecast_call'
              AND metric_type = :mt
              AND forecaster_id = :fid
              AND source_platform_id LIKE :sid_like
              AND prediction_date BETWEEN :ds AND :de
            LIMIT 1
        """), {
            "mt": metric_type,
            "fid": int(forecaster_id),
            "sid_like": f"%_metric_{metric_type}_{period_key}%",
            "ds": date_start,
            "de": date_end,
        }).first()
    except Exception as _e:
        log.warning("[YT-CLF] metric_forecast cross-scraper dedup failed: %s", _e)
        return False
    return row is not None


def insert_youtube_metric_forecast_prediction(
    pred: dict,
    *,
    channel_name: str,
    channel_id: str | None,
    video_id: str,
    video_title: str,
    publish_date: datetime,
    db,
    transcript_snippet: str | None = None,
    stats: dict | None = None,
) -> bool:
    """Insert a metric_forecast_call prediction.

    Stores the row with prediction_category='metric_forecast_call'
    (NEW category) and the six new metric_* columns populated from the
    validator's stamped fields. Direction is a free choice (bullish /
    bearish / neutral) — the forecaster may frame the prediction as
    a beat, a miss, or a pure number. The scoring path in the
    evaluator uses metric_target vs metric_actual with category-based
    tolerance; direction does NOT enter the scoring calculation.

    ticker policy:
      - Company metrics (eps, revenue, guidance_*, subscribers, etc):
        ticker is REQUIRED and must pass validate_ticker_in_db.
      - Macro metrics (cpi, unemployment, gdp_growth, etc): ticker is
        OPTIONAL. We store a sentinel 'MACRO' in the ticker column
        (existing NOT NULL constraint) and leave the semantic metric
        information in metric_type.

    Rejection paths (all log to youtube_scraper_rejections):
      - metric_type not in allowlist → 'metric_forecast_invalid_type'
      - missing / non-numeric metric_target → 'metric_forecast_invalid_target'
      - missing metric_release_date → 'metric_forecast_missing_release'
      - ticker required but invalid → 'metric_forecast_invalid_ticker'
      - per-video dedup hit → 'dedup_collision'
      - cross-scraper dedup hit → 'cross_scraper_dupe'
      - forecaster create failure → 'forecaster_creation_failed'
    """
    from models import Prediction

    def _reject(reason: str, hr: str | None = None) -> bool:
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=video_title,
            video_published_at=publish_date,
            reason=reason,
            haiku_reason=hr,
            haiku_raw=pred,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return False

    metric_type = (pred.get("_metric_type") or pred.get("metric_type") or "").strip().lower()
    raw_target = pred.get("_metric_target")
    if raw_target is None:
        raw_target = pred.get("metric_target")
    release = pred.get("_metric_release_date")
    period = pred.get("_metric_period") or pred.get("metric_period") or None
    direction = (pred.get("direction") or "neutral").strip().lower()
    if direction not in _VALID_DIRECTIONS:
        direction = "neutral"

    if metric_type not in _METRIC_FORECAST_TYPES:
        return _reject("metric_forecast_invalid_type", hr=metric_type or None)
    try:
        target_num = float(raw_target)
    except (TypeError, ValueError):
        return _reject("metric_forecast_invalid_target", hr=str(raw_target)[:120])
    if not release:
        return _reject("metric_forecast_missing_release", hr=metric_type)

    is_company = metric_type in _METRIC_FORECAST_COMPANY_TYPES

    # Ticker handling. Company metrics require a real ticker; macro
    # metrics fall back to the 'MACRO' sentinel.
    raw_ticker = (pred.get("ticker") or "").upper().strip().lstrip("$")
    raw_ticker = re.sub(r"[^A-Z0-9]", "", raw_ticker)
    ticker_to_store: str
    if raw_ticker and not raw_ticker.startswith("METRIC") and len(raw_ticker) <= 5:
        if validate_ticker_in_db(raw_ticker, db):
            ticker_to_store = raw_ticker
        elif is_company:
            return _reject("metric_forecast_invalid_ticker", hr=raw_ticker)
        else:
            ticker_to_store = "MACRO"
    elif is_company:
        return _reject("metric_forecast_invalid_ticker", hr=metric_type)
    else:
        ticker_to_store = "MACRO"

    # Per-video dedup: canonical source_platform_id embeds metric_type
    # and period_key so two different forecasts in the same video
    # insert as separate rows but the same forecast mentioned twice
    # collapses.
    period_key = (period or release.isoformat()).replace(" ", "_")[:24]
    target_key = f"{target_num:.6g}".replace(".", "p").replace("-", "n")
    source_id = f"yt_{video_id}_metric_{metric_type}_{period_key}_{target_key}"
    if db.execute(
        sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=f"{metric_type}/{period_key}")

    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    if _metric_forecast_exists_cross_scraper(
        metric_type, period_key, forecaster.id, publish_date, db,
    ):
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("cross_scraper_dupe", hr=f"{metric_type}/{period_key}")

    # Eval date is the metric release date; window_days is derived.
    from datetime import datetime as _dt
    eval_date = _dt.combine(release, _dt.min.time())
    window_days = max(1, (eval_date - publish_date).days) if publish_date else 30

    quote = (pred.get("context_quote") or pred.get("quote") or "").strip()
    parts = [f"{channel_name}: {metric_type} {target_num:g}"]
    if period:
        parts.append(f"({period})")
    if quote:
        parts.append(f'"{quote[:120]}"')
    context_str = ". ".join(parts)[:500]

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    db.add(
        Prediction(
            forecaster_id=forecaster.id,
            ticker=ticker_to_store,
            direction=direction,
            prediction_date=publish_date,
            evaluation_date=eval_date,
            window_days=window_days,
            target_price=None,  # metric forecasts have no price target
            entry_price=None,
            source_url=source_url,
            archive_url=source_url,
            source_type="youtube",
            source_title=(video_title or "")[:500],
            source_platform_id=source_id,
            sector=None,
            context=context_str,
            exact_quote=(quote or context_str)[:500],
            outcome="pending",
            verified_by=VERIFIED_BY,
            call_type="metric_forecast_call",
            prediction_category="metric_forecast_call",
            metric_type=metric_type,
            metric_target=target_num,
            metric_period=period,
            metric_release_date=release,
            # metric_actual + metric_error_pct stay NULL until the
            # evaluator fetches the real value.
        )
    )
    db.flush()
    if stats is not None:
        stats["metric_forecasts_extracted"] = int(
            stats.get("metric_forecasts_extracted", 0)
        ) + 1
    return True


# ── Conditional call insertion ──────────────────────────────────────────────
#
# Writes a prediction_category='conditional_call' row with the trigger_*
# columns populated. The "outcome" side (ticker/direction/target_price/
# window_days) is stored exactly like a normal ticker_call so the
# existing scoring path can score it once Phase 1 (trigger check) has
# marked trigger_fired_at. Default trigger_deadline is 90 days from
# the prediction date.


CONDITIONAL_DEFAULT_TRIGGER_DEADLINE_DAYS = 90
CONDITIONAL_DEFAULT_OUTCOME_WINDOW_DAYS = 90


def _conditional_source_id(video_id: str, ticker: str, trigger_condition: str) -> str:
    """Per-video dedup key for conditional_call rows. Two conditionals
    on the same ticker in the same video with different triggers are
    legitimately distinct — we hash the trigger_condition text so they
    each get their own source_platform_id."""
    import hashlib as _hashlib
    trig_hash = _hashlib.md5(
        (trigger_condition or "").strip().lower().encode("utf-8")
    ).hexdigest()[:10]
    return f"yt_{video_id}_cond_{ticker}_{trig_hash}"


def insert_youtube_conditional_prediction(
    pred: dict,
    *,
    channel_name: str,
    channel_id: str | None,
    video_id: str,
    video_title: str,
    publish_date: datetime,
    db,
    transcript_snippet: str | None = None,
    stats: dict | None = None,
) -> bool:
    """Insert a conditional_call prediction.

    Writes prediction_category='conditional_call' with trigger_*
    columns set from pred._trigger_*. Outcome columns (ticker,
    direction, target_price, window_days) get the normal ticker_call
    treatment. outcome='pending' until the evaluator completes
    phase-based scoring.

    Rejection paths (each logs to youtube_scraper_rejections and
    returns False):
      - missing trigger/outcome fields → 'conditional_missing_fields'
      - invalid direction → 'neutral_or_no_direction'
      - dedup collision → 'dedup_collision'
      - forecaster create failure → 'forecaster_creation_failed'
      - cross-scraper dupe → 'cross_scraper_dupe'
    """
    from models import Prediction
    from jobs.prediction_validator import prediction_exists_cross_scraper

    def _reject(reason: str, hr: str | None = None) -> bool:
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=video_title,
            video_published_at=publish_date,
            reason=reason,
            haiku_reason=hr,
            haiku_raw=pred,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return False

    ticker = (pred.get("ticker") or "").upper().strip().lstrip("$")
    direction = (pred.get("direction") or "").strip().lower()
    trig_cond = pred.get("_trigger_condition") or pred.get("trigger_condition") or ""
    trig_type = pred.get("_trigger_type") or pred.get("trigger_type") or ""
    trig_ticker = pred.get("_trigger_ticker")
    trig_price = pred.get("_trigger_price")
    trig_deadline = pred.get("_trigger_deadline")

    if not ticker:
        return _reject("conditional_missing_fields", hr="no ticker")
    if direction not in _VALID_DIRECTIONS:
        return _reject("neutral_or_no_direction", hr=direction or None)
    if not trig_cond or not trig_type:
        return _reject("conditional_missing_fields", hr="no trigger")

    if trig_deadline is None:
        trig_deadline_dt = publish_date + timedelta(
            days=CONDITIONAL_DEFAULT_TRIGGER_DEADLINE_DAYS
        )
    else:
        try:
            trig_deadline_dt = datetime.combine(trig_deadline, datetime.min.time())
        except TypeError:
            trig_deadline_dt = publish_date + timedelta(
                days=CONDITIONAL_DEFAULT_TRIGGER_DEADLINE_DAYS
            )

    source_id = _conditional_source_id(video_id, ticker, trig_cond)
    if db.execute(
        sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=f"{ticker}/{trig_cond[:60]}")

    if not validate_ticker_in_db(ticker, db):
        return _reject("invalid_ticker", hr=ticker)

    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    if prediction_exists_cross_scraper(
        ticker, forecaster.id, direction, publish_date, db,
    ):
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("cross_scraper_dupe", hr=ticker)

    eval_date, window_days = _parse_evaluation_date(
        pred.get("timeframe"), publish_date,
    )
    outcome_window_days = int(window_days) if window_days else CONDITIONAL_DEFAULT_OUTCOME_WINDOW_DAYS

    target_price = pred.get("price_target")
    if target_price is not None:
        try:
            target_price = float(target_price)
            if not (0.5 < target_price < 100_000):
                target_price = None
        except (ValueError, TypeError):
            target_price = None

    sector = None
    try:
        from jobs.sector_lookup import get_sector
        sector = get_sector(ticker, db)
    except Exception:
        sector = None

    quote = (pred.get("context_quote") or pred.get("quote") or "").strip()
    parts = [
        f"{channel_name}: IF {trig_cond[:120]} THEN "
        f"{direction.capitalize()} {ticker}"
    ]
    if target_price is not None:
        parts.append(f"target ${target_price:g}")
    if quote:
        parts.append(f'"{quote[:120]}"')
    context_str = ". ".join(parts)[:500]

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    if trig_ticker:
        trig_ticker = str(trig_ticker).upper().strip().lstrip("$")

    db.add(
        Prediction(
            forecaster_id=forecaster.id,
            ticker=ticker,
            direction=direction,
            prediction_date=publish_date,
            evaluation_date=eval_date,
            window_days=window_days,
            target_price=target_price,
            entry_price=None,
            source_url=source_url,
            archive_url=source_url,
            source_type="youtube",
            source_title=(video_title or "")[:500],
            source_platform_id=source_id,
            sector=sector,
            context=context_str,
            exact_quote=(quote or context_str)[:500],
            outcome="pending",
            verified_by=VERIFIED_BY,
            call_type="conditional_call",
            prediction_category="conditional_call",
            trigger_condition=trig_cond[:500],
            trigger_type=trig_type,
            trigger_ticker=trig_ticker,
            trigger_price=trig_price,
            trigger_deadline=trig_deadline_dt,
            trigger_fired_at=None,
            outcome_window_days=outcome_window_days,
        )
    )
    db.flush()
    if stats is not None:
        stats["conditional_calls_extracted"] = int(
            stats.get("conditional_calls_extracted", 0)
        ) + 1
    return True
