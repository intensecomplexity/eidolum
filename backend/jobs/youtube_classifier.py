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
    base_system = YOUTUBE_HAIKU_SECTOR_SYSTEM if use_sector_prompt else HAIKU_SYSTEM
    # Append optional instruction blocks ONLY when each flag is on. When
    # every flag is off (the default), base_system is sent byte-for-byte
    # unchanged so Anthropic's prompt cache hit rate on the base prompt
    # stays at 100%. Order matters for cache hits: ranked list → revisions
    # → options → earnings, stable across calls with any combination of
    # flags on so extended-prompt cache entries match.
    active_system = base_system
    if use_ranked_list:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_RANKED_LIST_INSTRUCTIONS
    if use_revisions:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_REVISIONS_INSTRUCTIONS
    if use_options:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_OPTIONS_INSTRUCTIONS
    if use_earnings:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_EARNINGS_INSTRUCTIONS
    telemetry["prompt_variant"] = "sector" if use_sector_prompt else "standard"
    telemetry["ranked_list_enabled"] = bool(use_ranked_list)
    telemetry["revisions_enabled"] = bool(use_revisions)
    telemetry["options_enabled"] = bool(use_options)
    telemetry["earnings_enabled"] = bool(use_earnings)
    print(
        f"[YOUTUBE-HAIKU] video={video_id or '?'} channel={channel_name} "
        f"prompt_variant={telemetry['prompt_variant']} "
        f"ranked_list={'on' if use_ranked_list else 'off'} "
        f"revisions={'on' if use_revisions else 'off'} "
        f"options={'on' if use_options else 'off'} "
        f"earnings={'on' if use_earnings else 'off'}",
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
    out: list[dict] = []
    for p in raw:
        if not isinstance(p, dict):
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
        # by the insert path to increment the per-run counter for the
        # matching sub-type. Canonical values: 'options_position',
        # 'earnings_call'. Unknown values normalize to None.
        raw_derived = p.get("derived_from")
        derived_from = None
        if raw_derived is not None:
            _rd = str(raw_derived).strip().lower()
            if _rd in ("options_position", "earnings_call"):
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
        )
    )
    db.flush()
    # Options-position counter: if Haiku marked this prediction as
    # derived from options vocabulary, bump the per-run counter so
    # scraper_runs.options_positions_extracted reflects how much of
    # the run's ticker_call yield came from the options prompt block.
    # The marker is NOT stored in the Prediction row — we just drop it
    # here after reading.
    if pred.get("_derived_from") == "options_position" and stats is not None:
        stats["options_positions_extracted"] = int(
            stats.get("options_positions_extracted", 0)
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
