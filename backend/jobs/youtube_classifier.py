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


# ── Auto-caption spelling fixes ─────────────────────────────────────────────
#
# YouTube's auto-captions consistently butcher a handful of ticker / company
# names that show up often in stock-pick channels. The raw quote is still
# used for timestamp matching and ticker verification (both paths search the
# unmodified transcript), so this fix is applied only to the final value
# written to predictions.source_verbatim_quote — AFTER matching has already
# succeeded. Going forward the stored training data uses the correct names.

_CAPTION_SPELLING_FIXES = {
    'Salana': 'Solana',
    'Invidia': 'Nvidia',
    'Palanteer': 'Palantir',
    'Pallantir': 'Palantir',
    'Palenteer': 'Palantir',
    'palunteer': 'Palantir',
    'kryptos': 'crypto',
    'fizer': 'Pfizer',
    'Chewie': 'Chewy',
}


def _fix_caption_spelling(text: str) -> str:
    """Fix known YouTube auto-caption misspellings in-place."""
    if not text:
        return text
    for wrong, right in _CAPTION_SPELLING_FIXES.items():
        text = re.sub(r'\b' + re.escape(wrong) + r'\b', right, text, flags=re.IGNORECASE)
    return text


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

# ââ Fine-tuned model (Qwen 2.5 7B) on RunPod Serverless ââââââââââââââââââ
# When USE_FINETUNED_MODEL is "true", classify_video calls our self-hosted
# Qwen 2.5 7B LoRA-merged model via RunPod's OpenAI-compatible endpoint
# instead of Anthropic Haiku. Haiku is kept as automatic fallback if the
# RunPod call fails. Cost: ~$0.00019/s on 24GB GPU vs ~$36/mo Haiku.
USE_FINETUNED_MODEL = os.getenv("USE_FINETUNED_MODEL", "false").strip().lower() == "true"
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "").strip()
RUNPOD_ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID", "").strip()
RUNPOD_MODEL_NAME = "/runpod-volume/eidolum-qwen-merged"

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

# ââ RunPod Serverless vLLM call (fine-tuned Qwen 2.5 7B) âââââââââââââââââ

# RunPod pricing for 24GB GPU serverless ($0.00019/s). Rough estimate
# based on typical 3-8 second inference time per video.
RUNPOD_ESTIMATED_COST_PER_CALL = 0.0012  # ~6.3s average * $0.00019/s

def call_runpod_vllm(
    *,
    system_text: str,
    user_text: str,
    video_id: str | None,
    channel_name: str,
    telemetry: dict,
    max_tokens: int = 4096,
) -> str | None:
    """Call the fine-tuned Qwen 2.5 7B model via RunPod Serverless
    OpenAI-compatible endpoint. Returns the raw response text (JSON
    string) or None on failure.

    Uses httpx (already in requirements.txt) with a 120s timeout â
    RunPod Serverless may cold-start a worker if none are active.
    The /openai/v1/chat/completions path returns standard OpenAI
    format so we can extract content directly.
    """
    import httpx

    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("[YT-RUNPOD] Missing RUNPOD_API_KEY or RUNPOD_ENDPOINT_ID", flush=True)
        return None

    url = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": RUNPOD_MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
    }

    identifier = video_id or channel_name
    t0 = time.time()
    try:
        with httpx.Client(timeout=120.0) as http:
            r = http.post(url, json=payload, headers=headers)
        elapsed = time.time() - t0

        if r.status_code != 200:
            print(
                f"[YT-RUNPOD] HTTP {r.status_code} for {identifier} "
                f"({elapsed:.1f}s): {r.text[:300]}",
                flush=True,
            )
            telemetry["runpod_error"] = f"http_{r.status_code}"
            return None

        data = r.json()
        content = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)

        telemetry["input_tokens"] = int(telemetry.get("input_tokens", 0)) + in_tok
        telemetry["output_tokens"] = int(telemetry.get("output_tokens", 0)) + out_tok
        telemetry["estimated_cost_usd"] = (
            float(telemetry.get("estimated_cost_usd", 0.0)) + RUNPOD_ESTIMATED_COST_PER_CALL
        )

        print(
            f"[YT-RUNPOD] {identifier} input={in_tok} output={out_tok} "
            f"elapsed={elapsed:.1f}s est_cost=${RUNPOD_ESTIMATED_COST_PER_CALL:.4f}",
            flush=True,
        )
        return content

    except Exception as e:
        elapsed = time.time() - t0
        tag = f"{type(e).__name__}: {str(e)[:200]}"
        print(
            f"[YT-RUNPOD] Error for {identifier} ({elapsed:.1f}s): {tag}",
            flush=True,
        )
        telemetry["runpod_error"] = tag[:300]
        return None


# verified_by tag for grep / cohort analysis. Bump _v1 â _v2 if the
# prompt or model materially change.
VERIFIED_BY_HAIKU = "youtube_haiku_v1"
VERIFIED_BY_QWEN = "youtube_qwen_v1"
# Legacy alias — insert functions reference this constant; it gets
# overridden per-call via _active_verified_by thread-local below.
VERIFIED_BY = VERIFIED_BY_HAIKU
PIPELINE_VERSION = "youtube_v1"

# ── RunPod vLLM (fine-tuned Qwen 2.5 7B) ────────────────────────────────────

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "").strip()
RUNPOD_ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID", "").strip()
USE_FINETUNED_MODEL = os.getenv("USE_FINETUNED_MODEL", "false").lower() == "true"
RUNPOD_TIMEOUT_SECONDS = 120
RUNPOD_COLD_START_THRESHOLD = 30  # seconds — log a warning above this

# ── YouTube pipeline stats (module-level, reset daily by watchdog) ───────────

class _YTStats:
    """Simple in-memory counters for the daily summary. Reset once per day."""
    __slots__ = (
        "predictions", "errors", "circuit_breaker_trips",
        "total_latency", "classifications", "last_reset_day",
    )
    def __init__(self):
        self.reset()
    def reset(self):
        self.predictions = 0
        self.errors = 0
        self.circuit_breaker_trips = 0
        self.total_latency = 0.0
        self.classifications = 0
        self.last_reset_day = datetime.utcnow().date()
    def maybe_reset_daily(self):
        today = datetime.utcnow().date()
        if today != self.last_reset_day:
            self.reset()
    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.classifications if self.classifications else 0.0

yt_stats = _YTStats()

# Circuit breaker: stop calling RunPod after N consecutive failures in one cycle
RUNPOD_CIRCUIT_BREAKER_THRESHOLD = 3
_runpod_consecutive_failures = 0


def reset_circuit_breaker():
    """Call at the start of each monitor/backfill cycle."""
    global _runpod_consecutive_failures
    _runpod_consecutive_failures = 0


def is_circuit_breaker_tripped() -> bool:
    return _runpod_consecutive_failures >= RUNPOD_CIRCUIT_BREAKER_THRESHOLD


QWEN_SYSTEM_PROMPT = (
    "You are a financial prediction classifier. Given a YouTube transcript excerpt, "
    "extract stock market predictions with: ticker, direction (bullish/bearish), "
    "conviction_level (strong/moderate/hedged), timeframe_category (one of: macro_thesis, "
    "long_term_fundamental, fundamental_quarterly, cyclical_medium, technical_chart, "
    "swing_trade, earnings_cycle, event_binary, options_expiry, crypto_native, "
    "sector_rotation), inferred_timeframe_days (integer), and the verbatim quote. "
    "Return a JSON array of prediction objects. If no predictions found, return []."
)

# RunPod Serverless pricing: ~$0.00076/s active GPU time.
# Average call ~1.5s → ~$0.0012/call.
QWEN_PRICE_PER_CALL_USD = 0.0012


def call_runpod_vllm(
    transcript_chunk: str,
    channel_name: str,
    title: str,
    publish_date: str,
    video_id: str | None = None,
) -> tuple[str, float, float]:
    """Call the fine-tuned Qwen 2.5 7B on RunPod Serverless via vLLM's
    OpenAI-compatible API.

    Returns (raw_text_response, estimated_cost_usd, latency_seconds).
    Raises on ANY failure (timeout, HTTP error, empty response).
    Updates circuit breaker state on success/failure.
    """
    global _runpod_consecutive_failures
    import httpx as _httpx

    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        raise RuntimeError("RUNPOD_API_KEY or RUNPOD_ENDPOINT_ID not set")

    url = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/openai/v1/chat/completions"

    user_msg = (
        f"Video title: {title}\n"
        f"Channel: {channel_name}\n"
        f"Published: {publish_date}\n"
        f"Transcript:\n"
        f"{transcript_chunk}\n\n"
        f"Extract all valid financial predictions from this transcript. "
        f"Return JSON array only, no other text."
    )

    payload = {
        "model": "/runpod-volume/eidolum-qwen-merged",
        "messages": [
            {"role": "system", "content": QWEN_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "max_tokens": 4000,
    }

    identifier = video_id or channel_name
    t0 = time.time()
    try:
        r = _httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {RUNPOD_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=RUNPOD_TIMEOUT_SECONDS,
        )
    except _httpx.TimeoutException:
        _runpod_consecutive_failures += 1
        yt_stats.errors += 1
        raise RuntimeError(
            f"RunPod timeout after {RUNPOD_TIMEOUT_SECONDS}s for {identifier}"
        )
    except Exception:
        _runpod_consecutive_failures += 1
        yt_stats.errors += 1
        raise

    latency = time.time() - t0

    if r.status_code != 200:
        _runpod_consecutive_failures += 1
        yt_stats.errors += 1
        raise RuntimeError(
            f"RunPod HTTP {r.status_code}: {r.text[:300]}"
        )

    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        _runpod_consecutive_failures += 1
        yt_stats.errors += 1
        raise RuntimeError("RunPod returned empty choices")

    content = (choices[0].get("message") or {}).get("content") or ""
    if not content.strip():
        _runpod_consecutive_failures += 1
        yt_stats.errors += 1
        raise RuntimeError("RunPod returned empty content")

    # Success — reset consecutive failure counter
    _runpod_consecutive_failures = 0

    usage = data.get("usage") or {}
    in_tok = usage.get("prompt_tokens", 0)
    out_tok = usage.get("completion_tokens", 0)
    cost = QWEN_PRICE_PER_CALL_USD

    # Cold start detection
    cold_tag = ""
    if latency > RUNPOD_COLD_START_THRESHOLD:
        cold_tag = f" COLD_START={latency:.1f}s"
        print(
            f"[YOUTUBE-QWEN] RunPod cold start detected: {latency:.1f}s "
            f"for {identifier}",
            flush=True,
        )

    print(
        f"[YOUTUBE-QWEN] {identifier} ({channel_name}) "
        f"input={in_tok} output={out_tok} latency={latency:.1f}s "
        f"cost=${cost:.4f}{cold_tag}",
        flush=True,
    )

    yt_stats.total_latency += latency
    yt_stats.classifications += 1

    return content.strip(), cost, latency


# Thread-local override for VERIFIED_BY so insert functions pick up
# the correct tag without changing their signatures.
import threading
_verified_by_local = threading.local()


def _get_active_verified_by() -> str:
    """Return the verified_by tag for the current classify_video call."""
    return getattr(_verified_by_local, "tag", VERIFIED_BY_HAIKU)



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


# Disclosure instructions. Appended to the active prompt when
# ENABLE_DISCLOSURE_EXTRACTION is flipped on. Teaches Haiku to
# recognize PAST-TENSE position statements — what the forecaster
# actually DID with real money, not what they expect the market
# to do. Disclosures land in their own `disclosures` table (NOT
# predictions) and carry follow-through scoring (stock return in
# the 1/3/6/12 months after the disclosed_at date) instead of
# HIT/NEAR/MISS. This is ship #8, the final ship in the new
# prediction type series, and the key to catching real portfolio
# signal buried in casual "I bought / I added / I trimmed" asides.
#
# CRITICAL distinction from the other prompts: disclosure is PAST
# TENSE ("I bought AMD yesterday"); ticker_call is FUTURE TENSE
# ("I'm going to buy AMD"). The disclosure prompt spends most of
# its length hammering this distinction because Haiku otherwise
# blurs them.
YOUTUBE_HAIKU_DISCLOSURE_INSTRUCTIONS = """DISCLOSURES (PAST-TENSE POSITION STATEMENTS):
If the speaker says they already took a position — bought, sold, added, trimmed, started, exited, or is still holding a stock — emit it as a disclosure. Disclosures are NOT predictions. They capture what the forecaster actually DID with real money, which is scored by "follow-through" (did the stock move the right way after they said it?) rather than HIT/NEAR/MISS. The most important signal here is TENSE.

TENSE RULES — read carefully:

Disclosures cover TWO tense patterns, and only these two:

(A) PAST-TENSE transactional actions — the verb describes a completed trade: "I bought 500 AMD today", "we added NVDA this week", "I trimmed META yesterday", "we exited NFLX last Friday", "I sold half my TSLA at 250".

(B) PRESENT or PRESENT-CONTINUOUS ownership statements — the verb describes what the speaker CURRENTLY OWNS: "I still hold AAPL", "we continue to hold ANET", "we own NVDA", "our position in AAPL remains unchanged", "we remain long SPY", "our fund still holds GOOG", "I've been holding AAPL since 2018". Pattern (B) is limited to HOLD / OWN / POSITION-DESCRIBING language only — "we continue to BUY" does NOT qualify because "buy" is a transactional verb and must be past-tense to count. Present-continuous is the pass reserved for the verbs of CONTINUED OWNERSHIP, not continued transacting.

FUTURE TENSE is NOT a disclosure — "I'm going to buy AMD tomorrow", "we will add NVDA on the next dip", "I might pick up some TSLA" all describe intent that hasn't happened yet. Future intent belongs to ticker_call.

CONDITIONAL statements ("if X drops to 180, we buy") are NOT disclosures either — those belong to conditional_call.

The test that matters: has the action ALREADY HAPPENED (past-tense transaction) OR is the position CURRENTLY OWNED (present-continuous hold/own)? If neither, it's not a disclosure — punt to the appropriate prediction type.

Examples of PAST TENSE disclosure language:
- "I bought 500 shares of AMD today"
- "I picked up some NVDA yesterday"
- "I added 5% AAPL to my portfolio this week"
- "I trimmed my TSLA position"
- "I'm out of META, closed the position last Friday"
- "I just started a new position in GOOGL"
- "I loaded up on Intel at $20"
- "I've been holding AAPL since 2018"
- "I sold half my NVDA at $900"

Examples of FUTURE TENSE — do NOT emit as disclosure, let ticker_call handle it:
- "I'm going to buy AMD tomorrow"                → ticker_call (future intent, not past action)
- "I'm planning to add to NVDA on the next dip"  → ticker_call
- "I might pick up some TSLA"                    → ticker_call
- "If it drops 10%, I'm buying"                  → conditional_call (IF/THEN)
- "You should buy AAPL"                          → ticker_call (recommendation, not personal action)
- "AMD is a buy here"                            → ticker_call (recommendation)

Actions (REQUIRED — pick exactly one from this list):
- buy:     fresh purchase ("I bought 500 AMD")
- sell:    full sale (no shares left)
- add:     increased an existing position ("I added 5% NVDA")
- trim:    reduced an existing position (some shares left)
- starter: new position, smaller-than-target size ("starting a position", "dipping a toe in")
- exit:    closed out completely ("I'm out", "closed the position")
- hold:    neither bought nor sold, but affirmed conviction ("still holding AAPL from 2018")

Fields to extract:
- ticker (REQUIRED): the symbol
- action (REQUIRED): from the list above
- size_shares: number of shares if the speaker says one ("500 shares" → 500)
- size_pct: portfolio percentage if given ("5% of portfolio" → 0.05)
- size_qualitative: one of 'small','medium','large','full' if no specific size ("a small position" → small, "a full position" → full)
- entry_price: purchase/sale price if mentioned ("at $180" → 180)
- reasoning_text: why they did it, if explained ("because the chart looks bullish")
- disclosed_at: when they say it happened ("today", "yesterday", "last week") — convert to absolute date using the video's publish date
- derived_from: "disclosure"

At least ONE of size_shares / size_pct / size_qualitative should be set when the size is mentioned. All three can be NULL if the speaker gave no size info.

Output format:
{
  "ticker": "AMD",
  "action": "buy",
  "size_shares": 500,
  "size_pct": null,
  "size_qualitative": null,
  "entry_price": 180,
  "reasoning_text": "chart looks bullish above 180",
  "disclosed_at": "2026-04-11",
  "derived_from": "disclosure",
  "context_quote": "I just bought 500 AMD today at 180"
}

Examples:

Input: "I just bought 500 shares of AMD today"
Output: {"ticker":"AMD","action":"buy","size_shares":500,"disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"I just bought 500 shares of AMD today"}

Input: "Added 5% NVDA to the portfolio this week at 180"
Output: {"ticker":"NVDA","action":"add","size_pct":0.05,"entry_price":180,"disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"added 5% NVDA to the portfolio this week at 180"}

Input: "Starting a small position in GOOGL"
Output: {"ticker":"GOOGL","action":"starter","size_qualitative":"small","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"starting a small position in GOOGL"}

Input: "I trimmed my NVDA yesterday after the big run — locked in some profits"
Output: {"ticker":"NVDA","action":"trim","reasoning_text":"locked in profits after the big run","disclosed_at":"2026-04-10","derived_from":"disclosure","context_quote":"trimmed my NVDA yesterday after the big run"}

Input: "I'm out of META, closed the position last Friday"
Output: {"ticker":"META","action":"exit","disclosed_at":"2026-04-04","derived_from":"disclosure","context_quote":"I'm out of META, closed the position last Friday"}

Input: "Picked up a small starter in PLTR"
Output: {"ticker":"PLTR","action":"starter","size_qualitative":"small","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"picked up a small starter in PLTR"}

Input: "Still long AAPL from 2018, not selling a share"
Output: {"ticker":"AAPL","action":"hold","reasoning_text":"conviction hold since 2018","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"still long AAPL from 2018, not selling a share"}

Input: "I might buy AMD tomorrow if it drops to 170"
Output: (do NOT emit as disclosure — future intent, and conditional. Let conditional_call or ticker_call handle it.)

Input: "I recommend buying NVDA"
Output: (do NOT emit as disclosure — this is a recommendation to others, not a personal action. Let ticker_call handle it.)

Input: "NVDA is my biggest position"
Output: (do NOT emit as disclosure — no action verb, no specific trade. This is portfolio description, not a transaction.)

Plural voice (firms, funds, newsletters, institutional managers):

When the speaker represents a firm, fund, newsletter, or institutional manager, they use first-person PLURAL pronouns ("we", "our", "the fund", "our portfolio") instead of "I". These statements are still disclosures — the speaker is describing what the institution bought, added to, trimmed, exited, or currently holds. The same seven actions apply; only the pronoun changes. Plural voice is EQUALLY valid as singular voice for disclosures. Do not skip these.

Input: "we continue to hold our long term position in Arista"
Output: {"ticker":"ANET","action":"hold","reasoning_text":"long-term position (conviction hold)","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"we continue to hold our long term position in Arista"}

Input: "we own roughly 4% NVDA in the fund"
Output: {"ticker":"NVDA","action":"hold","size_pct":0.04,"disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"we own roughly 4% NVDA in the fund"}

Input: "our position in AAPL remains unchanged this quarter"
Output: {"ticker":"AAPL","action":"hold","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"our position in AAPL remains unchanged this quarter"}

Input: "we added to our TSLA position this week"
Output: {"ticker":"TSLA","action":"add","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"we added to our TSLA position this week"}

Input: "we trimmed our META position at 520 after the run"
Output: {"ticker":"META","action":"trim","entry_price":520,"reasoning_text":"locked in gains after the run","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"we trimmed our META position at 520 after the run"}

Input: "we exited our NFLX position last month"
Output: {"ticker":"NFLX","action":"exit","disclosed_at":"2026-03-11","derived_from":"disclosure","context_quote":"we exited our NFLX position last month"}

Input: "we remain long SPY going into earnings season"
Output: {"ticker":"SPY","action":"hold","reasoning_text":"long SPY into earnings season","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"we remain long SPY going into earnings season"}

Input: "our fund still holds GOOG, not adding at this point"
Output: {"ticker":"GOOG","action":"hold","reasoning_text":"still holds, not adding further","disclosed_at":"2026-04-11","derived_from":"disclosure","context_quote":"our fund still holds GOOG, not adding at this point"}

IMPORTANT — distinguish portfolio ownership from analyst ratings:

Plural voice alone is not a disclosure trigger. The speaker must be describing what the INSTITUTION OWNS, not what the institution RECOMMENDS to others. Analyst-rating language uses "we" the same way but means "our rating is", not "our portfolio".

Input: "we rate AAPL a hold — expect sideways action over the next quarter"
Output: (do NOT emit as disclosure — analyst RATING, not portfolio holding. The firm is recommending HOLD to others, not describing what they own. Let ticker_call handle with direction=neutral.)

Input: "we have a hold rating on NVDA until earnings"
Output: (do NOT emit as disclosure — rating voice, not portfolio voice. Let ticker_call handle.)

The test that separates the two:
- OWNERSHIP voice → disclosure: "we own", "we hold", "we continue to hold", "our position in X", "we remain long", "long-term position in X", "our fund holds X", "still have exposure to X".
- RATING voice → ticker_call: "we rate X a hold", "we have a hold rating on X", "our rating is hold", "X is a hold here", "I have X at a hold".

If unsure, ask: is the speaker describing their own portfolio (disclosure) or their recommendation to others (ticker_call neutral)?

Rules:
- MUST set derived_from: "disclosure".
- MUST use PAST tense. Any future tense or conditional language → reject and let another prediction type handle it.
- MUST pick an action from the allowlist.
- MUST set disclosed_at to an absolute ISO date. "Today" = the video's publish date. "Yesterday" = publish_date − 1 day. "Last week" = publish_date − 7 days.
- MUST set ticker.
- MUST NOT set price_target, direction, timeframe — disclosures have no price target and no explicit direction (direction is implicit in the action).
- If the same disclosure is mentioned twice in a transcript (e.g. the speaker repeats "like I said, I bought AMD today"), emit it once — the dedup layer collapses duplicates on (ticker, action, date).

PRECEDENCE over ticker_call NEUTRAL (critical routing rule):

When a statement describes the speaker's OWN ownership of a position — phrases like "we own", "we hold", "we continue to hold", "our position in X", "our position remains unchanged", "we remain long", "we're still long", "still holding X", "long-term position in X", "our fund holds X", "we still have exposure to X", "I still own X", "I still hold X" — this block CLAIMS OWNERSHIP and emits a disclosure with action=hold. Do NOT emit a ticker_call with direction=neutral for such statements when this block is active. The base-prompt rule that maps "holding" to direction=neutral applies ONLY to analyst-rating voice, not to portfolio-ownership voice.

The OWNERSHIP-vs-RATING test:
  - "we continue to hold our long-term position in ANET" → ownership voice → disclosure with action=hold.
  - "our fund still holds GOOG" → ownership voice → disclosure with action=hold.
  - "we rate ANET a hold" → RATING voice → ticker_call with direction=neutral.
  - "I have AAPL at a hold here, expect sideways action" → RATING voice → ticker_call with direction=neutral.
  - "ANET is a hold in our view" → RATING voice → ticker_call with direction=neutral.

Decision heuristic when ambiguous: does the sentence describe the speaker's CURRENT PORTFOLIO ("we own X", "our position in X is") or does it describe their RECOMMENDATION to others ("we rate X a hold", "X is a hold here")? Portfolio → disclosure. Recommendation → ticker_call. If the speaker is ambiguous about whether they own the position, default to disclosure when the flag is active — portfolio mis-classification (hold vs not-hold) is recoverable via follow-through scoring; ticker_call NEUTRAL mis-classification penalizes real gains/losses and is not recoverable.

Output JSON only. Be concise."""


# Source-timestamp instructions. Ship #9 — the 12th and LAST additive
# instruction block. Applies to every other block's output (ticker_call,
# sector_call, pair_call, conditional_call, binary_event_call,
# metric_forecast_call, disclosure, and plain ticker_call) by asking
# Haiku to include a single new `verbatim_quote` field on every
# prediction emitted. The backend then runs that quote through the
# hybrid timestamp matcher (word-level JSON3 ASR → fuzzy segment
# match → two-pass Haiku → NULL) to resolve it to an integer second
# in the source video for ?t=Ns deep linking.
#
# This block is additive — it doesn't change any previous block's
# output schema, it just appends ONE field. So every other block's
# rules, allowlists, and examples continue to apply verbatim.
YOUTUBE_HAIKU_SOURCE_TIMESTAMP_INSTRUCTIONS = """SOURCE TIMESTAMPS (EXPANDED VERBATIM QUOTES):
For EVERY prediction you emit — regardless of type (ticker_call, sector_call, pair_call, conditional_call, binary_event_call, metric_forecast_call, disclosure) — include an additional `verbatim_quote` field. This quote has TWO jobs: (1) link the prediction back to the exact moment in the video for the timestamp matcher, and (2) preserve enough surrounding context that any pronoun or vague reference inside the prediction statement resolves unambiguously.

Rules for `verbatim_quote`:

1. COPY the exact words the forecaster used, character-for-character from the transcript. Do NOT paraphrase. Do NOT rewrite. Do NOT clean up disfluencies, filler words, or grammar. "I think uh Apple's gonna like probably hit two fifty by year end" stays exactly that — with "uh", "gonna", "like", "probably" all intact.

2. LENGTH: 20 to 60 words. Include ONE OR TWO sentences BEFORE the prediction statement plus the prediction sentence itself. The preceding sentences supply the antecedent for any pronoun ("these stocks", "it", "that name") inside the prediction so a human reading the quote in isolation can unambiguously identify what the forecaster meant. A single naked prediction sentence is no longer acceptable.

3. REFERENCE RESOLUTION IS MANDATORY. Inside the expanded quote, every pronoun and every vague reference ("these stocks", "that ticker", "the name", "this one", "it") must have a concrete antecedent — a specific ticker, company, or sector named earlier in the quote. If the forecaster says "a relief rally in these magnificent stocks could drive a rebound" and NO earlier sentence in the surrounding context names which stocks, REJECT the prediction with rejected=true, reason="unresolvable_reference". Better to drop one prediction than guess the ticker.

4. INCLUDE THE SETUP, NOT JUST THE PUNCHLINE. Good quotes read like "Tesla is so beaten down here, I've been watching it closely. A relief rally in these magnificent stocks could potentially drive a significant rebound." Bad quotes read like "a relief rally in these magnificent stocks" alone — the reader has no idea what's being discussed. Another example: "Let me talk about Apple for a second. I think it hits two fifty by year end based on services growth" is good; "I think it hits two fifty by year end" alone is bad because "it" is unresolved.

5. FIRST STATEMENT WINS when the same prediction is repeated. If the forecaster made the same call twice (e.g. once at 2:15 and again at 18:40), pick the surrounding sentences around the FIRST clear statement. The timestamp matcher will resolve to whichever utterance matches best.

6. For RANGES, include the sentence that names the range plus the setup sentence. For "Tesla had a rough quarter but the numbers are turning. EPS will land between sixty cents and seventy cents next print" the entire two-sentence block is the quote.

7. For REVISIONS, include the sentence that announces the revision plus enough prior context to make the old target unambiguous. "I've been at two hundred on AAPL for a while now. But now I'm moving up to two twenty based on services growth" — the whole two-sentence block.

8. For NEGATED binary events ("Fed will NOT cut"), the quote must make clear WHICH event is being negated. "Everyone expects a cut at the March meeting but I don't see it. They are not cutting in March, no way" — include the setup.

9. For DISCLOSURES (past-tense actions), include the setup sentence that identifies the ticker plus the action statement. "I've been watching AMD all week. Yeah I bought five hundred shares of AMD this morning, great entry point" — the whole block.

CRITICAL: If Haiku paraphrases or invents a quote that isn't in the transcript, the timestamp matcher breaks and the prediction either (a) gets stamped with the wrong timestamp or (b) falls through to NULL. Both outcomes undermine the training data being collected from this feature. COPY THE EXACT WORDS.

EQUALLY CRITICAL: If the context inside the expanded quote does NOT resolve a pronoun or vague reference, REJECT the prediction. Emit an object of the form {"rejected": true, "reason": "unresolvable_reference", "notes": "<what was ambiguous>"} instead of an accepted prediction. The backend will log this to youtube_scraper_rejections and skip the insert. Do not guess the ticker.

Output the quote as a string field alongside the existing fields:
{
  "ticker": "AAPL",
  "direction": "bullish",
  "price_target": 250,
  "timeframe": "2026-12-31",
  "verbatim_quote": "Let me talk about Apple for a second. I think it hits two fifty by end of year, they're gonna crush earnings on services growth."
}

Rejection example (unresolvable reference):
{
  "rejected": true,
  "reason": "unresolvable_reference",
  "notes": "'these stocks' has no antecedent in the surrounding sentences — could not identify which tickers are being discussed."
}

Examples (verbatim_quote field only, for each prediction type, with proper context setup):

ticker_call:
  verbatim_quote: "Let me talk about Apple for a second. I think it hits two fifty by end of year, they're gonna crush earnings on services growth."

sector_call:
  verbatim_quote: "I've been watching the energy complex all quarter. Energy is setting up for a massive run this year, oil's going to one ten."

pair_call:
  verbatim_quote: "Meta and Google are both going to report but they're in very different places. Between Meta and Google I'd take Meta all day — Google is slowing down hard."

conditional_call:
  verbatim_quote: "The Fed meeting is the next big macro catalyst. If the Fed cuts fifty bips in March stocks rally ten percent easy, no question in my mind."

binary_event_call (fed_decision):
  verbatim_quote: "Everyone is arguing about what the Fed does next. The Fed is gonna cut by fifty basis points at the March meeting, I'm confident in that."

binary_event_call (negated):
  verbatim_quote: "Powell has been clear about the data-dependency framing. They are not cutting in March, no way, they're holding rates flat through Q2."

metric_forecast_call (EPS):
  verbatim_quote: "NVIDIA's next print is the one everyone is watching. NVIDIA is gonna report five twenty EPS next quarter, maybe a little higher on data center."

disclosure:
  verbatim_quote: "I've been watching NVDA closely this month. I added five percent NVDA to my portfolio at one eighty this morning."

Rules recap (all predictions, every type):
- MUST include verbatim_quote on every prediction object in the output array.
- MUST copy exact words from the transcript — no paraphrasing, no cleanup.
- MUST be 20-60 words with 1-2 sentences of context BEFORE the prediction.
- MUST make every pronoun in the quote resolvable from the surrounding context.
- MUST pick the FIRST clear statement when the same call is made multiple times.
- MUST emit {"rejected": true, "reason": "unresolvable_reference", ...} when the reference cannot be resolved — do NOT guess the ticker.
- MUST NOT skip the quote — emit "" (empty string) only if the transcript is so garbled the prediction can't be traced to any single utterance (this should be very rare).

Output JSON only. Be concise."""


# Regime-call instructions (ship #12). Appended to the active prompt
# when ENABLE_REGIME_CALL_EXTRACTION is flipped on. Teaches Haiku to
# recognize structural market-phase claims — "no market top yet",
# "bottom is in", "topping process", "correction not bear market",
# "sideways chop" — and emit them as regime_call predictions. Regime
# calls carry NO price target: the claim is about STRUCTURE, not
# magnitude. Scoring is based on drawdown / runup / new-high / new-low
# behavior during the evaluation window rather than final price vs
# target, so "market grinds sideways or up 1% = correct no-top call"
# becomes scoreable in a way ticker_call never could.
YOUTUBE_HAIKU_REGIME_INSTRUCTIONS = """REGIME CALLS (STRUCTURAL MARKET PHASE):
If the speaker makes a structural claim about the market's PHASE — whether a bull market is continuing, topping, rolling over, bottoming, correcting, or consolidating — WITHOUT naming a specific price target, emit it as a regime_call. These claims are scored by what the instrument DOES structurally (drawdown, runup, new highs, new lows) during the window, not by final price vs target.

The problem this prediction type solves: "we're not going to see a market top until later this year" is a real forecaster claim that ticker_call extracts as "bullish SPY" and then scores MISS if SPY grinds sideways +1%. But the forecaster was RIGHT — no top happened. regime_call scores that structurally: small drawdown + any new highs = bull_continuing HIT.

regime_type allowlist — MUST use one of these eight canonical values verbatim:

- bull_continuing    "still in a bull market / no top yet / higher highs ahead / buy the dip / bull is intact"
- bull_starting      "new bull market / new cycle / bottom is in / off to the races / breaking out"
- topping            "forming a top / distribution phase / bull is ending / rolling over / toppy"
- bear_starting      "bear market begins / cycle top confirmed / here comes the decline / crash incoming"
- bear_continuing    "still in a bear / lower lows ahead / more downside / bounce is a head-fake"
- bottoming          "forming a bottom / capitulation / washed out / bear is ending / close to lows"
- correction         "pullback within a bull / healthy correction / not a bear / 10-15% drop max"
- consolidation      "sideways / chopping / trendless / base-building / range-bound"

Required fields on every regime_call output:
- regime_type: one of the allowlist values above
- regime_instrument: the ticker/ETF being claimed about. Default to "SPY" when the speaker says "the market", "stocks", "equities", "the indices". Use "QQQ" for "nasdaq", "tech". Use "IWM" for "small caps", "russell". Use "BTC" for "crypto", "bitcoin". If the speaker names a specific ETF or index, use that.
- timeframe: when the claim should be evaluated. Default to 6 months (longer than ticker_call defaults — regime calls are longer-horizon). If the speaker gives an explicit window ("by year end", "next 3 months"), parse it to an absolute ISO date.
- derived_from: "regime_call"
- direction: DO NOT set explicitly. The insert path derives direction from regime_type (bull_* and bottoming = bullish, bear_* and topping = bearish, correction and consolidation = neutral).
- price_target: DO NOT set. regime_call has no explicit target.

Distinguish carefully from other prediction types:

regime_call vs ticker_call:
- "SPY to $650 by year end"                 → ticker_call (has a specific price target)
- "SPY is going up"                         → ticker_call (directional, no regime language)
- "Still in a bull market, no top yet"      → regime_call, bull_continuing, SPY
- "Market's about to top out"               → regime_call, topping, SPY

regime_call vs macro_call:
- "Dollar weakening"                        → macro_call (macro concept, ETF-mapped)
- "Yield curve steepening"                  → macro_call (macro concept)
- "Equity bull market continues into 2026"  → regime_call, bull_continuing
- "Fed has to pivot"                        → macro_call (policy concept)

regime_call vs individual-stock commentary:
- "NVDA topping out here"                   → ticker_call bearish (individual stock, not a market regime)
- "Apple's in a new bull cycle"             → ticker_call bullish (individual stock, not a market regime)
- "The market is topping"                   → regime_call, topping, SPY
- "Tech is in a new bull run"               → regime_call, bull_starting, QQQ

Output format:
{
  "regime_type": "bull_continuing",
  "regime_instrument": "SPY",
  "timeframe": "2026-10-11",
  "derived_from": "regime_call",
  "context_quote": "we're not going to see a market top until later this year if not in 2026"
}

Examples:

Input: "we're not going to see a market top until later this year if not in 2026"
Output: {"regime_type":"bull_continuing","regime_instrument":"SPY","timeframe":"2026-10-11","derived_from":"regime_call","context_quote":"we're not going to see a market top until later this year if not in 2026"}

Input: "Bottom is in for Bitcoin — this is a new cycle"
Output: {"regime_type":"bull_starting","regime_instrument":"BTC","timeframe":"2026-10-11","derived_from":"regime_call","context_quote":"Bottom is in for Bitcoin — this is a new cycle"}

Input: "The market is in the distribution phase, bull is ending"
Output: {"regime_type":"topping","regime_instrument":"SPY","timeframe":"2026-07-11","derived_from":"regime_call","context_quote":"market is in the distribution phase, bull is ending"}

Input: "Bear market is officially starting — cycle top is confirmed"
Output: {"regime_type":"bear_starting","regime_instrument":"SPY","timeframe":"2026-10-11","derived_from":"regime_call","context_quote":"bear market is officially starting — cycle top is confirmed"}

Input: "More lower lows ahead before this ends"
Output: {"regime_type":"bear_continuing","regime_instrument":"SPY","timeframe":"2026-07-11","derived_from":"regime_call","context_quote":"more lower lows ahead before this ends"}

Input: "Capitulation has happened, we're close to the bottom"
Output: {"regime_type":"bottoming","regime_instrument":"SPY","timeframe":"2026-07-11","derived_from":"regime_call","context_quote":"capitulation has happened, we're close to the bottom"}

Input: "This is a correction in a bull market, not a bear"
Output: {"regime_type":"correction","regime_instrument":"SPY","timeframe":"2026-07-11","derived_from":"regime_call","context_quote":"this is a correction in a bull market, not a bear"}

Input: "Sideways chop for months — no trend either way"
Output: {"regime_type":"consolidation","regime_instrument":"SPY","timeframe":"2026-10-11","derived_from":"regime_call","context_quote":"sideways chop for months — no trend either way"}

Input: "Small caps entering a new bull cycle, watch the Russell"
Output: {"regime_type":"bull_starting","regime_instrument":"IWM","timeframe":"2027-04-11","derived_from":"regime_call","context_quote":"small caps entering a new bull cycle, watch the Russell"}

Input: "NVDA is topping out here"
Output: (do NOT extract as regime_call — individual stock, not a market regime. Let ticker_call handle NVDA with bearish direction.)

Input: "Oil going to $100"
Output: (do NOT extract — specific price, let macro_call or ticker_call handle.)

Input: "SPY to $650 by year end"
Output: (do NOT extract — specific price target, let ticker_call handle.)

Input: "It feels bearish to me"
Output: (do NOT extract — vague sentiment, not a structural claim. Reject.)

Rules:
- MUST set derived_from: "regime_call".
- MUST use regime_type from the allowlist above verbatim.
- MUST NOT set price_target — the claim has no target.
- MUST NOT set direction — the insert path derives it from regime_type.
- MUST set regime_instrument. Default to SPY for "the market"/"stocks"/"equities"; use QQQ for "nasdaq"/"tech sector broadly"; IWM for "small caps"/"russell"; BTC for "crypto"/"bitcoin".
- MUST NOT emit regime_call for individual-stock commentary. "NVDA topping out" is a ticker_call, not a regime_call — regime is a STATEMENT ABOUT THE MARKET'S PHASE, not about a single name.
- MUST NOT emit regime_call when a specific price target is named. Let ticker_call handle anything with a target.
- MUST NOT emit regime_call for macro-concept statements ("dollar weakening", "rates going up", "yield curve steepening"). Let macro_call handle those.
- REJECT vague sentiment with no regime language ("feels bearish", "I don't like this market"). regime_call requires explicit structural phase language.
- Default timeframe is 6 months. Parse explicit windows when given ("by year end" → end of calendar year; "next 3 months" → publish_date + 90 days).
- If the same regime_type/instrument combo is mentioned twice in a transcript, emit once — the dedup layer collapses (regime_type, instrument) per video.

Output JSON only. Be concise."""


# Prediction metadata enrichment (ship #9 rescoped). Appended to the
# active prompt when ENABLE_PREDICTION_METADATA_ENRICHMENT is flipped
# on. Teaches Haiku two classification tasks that modify EVERY
# extracted prediction's JSON shape:
#
#   1. Category-aware timeframe inference. The current default of
#      "3 months when no explicit date" is wrong for macro theses
#      ("M2 ticking up") which operate on 12+ month horizons, and
#      wrong for swing trades ("this week") which operate on 14-day
#      horizons. Haiku classifies the prediction into one of 11
#      categories with a known default. No explicit timeframe AND
#      no category match → REJECT, do not invent a default.
#
#   2. Conviction level classification. "AAPL will hit 250" and
#      "AAPL could maybe see upside" are currently scored identically.
#      This block captures conviction as a label-only field — leaderboard
#      accuracy math is unchanged. The fine-tuned model will learn
#      conviction natively; meanwhile the product team can decide
#      post-launch how to use it in filters.
#
# Neither feature affects direction extraction or price targets.
# Quote guidance lives in the SOURCE_TIMESTAMP block (which is edited
# to request expanded 20-60 word quotes with context) and does NOT
# duplicate here — the two blocks are co-gated by design so metadata
# without timestamps still works.
YOUTUBE_HAIKU_METADATA_ENRICHMENT_INSTRUCTIONS = """PREDICTION METADATA ENRICHMENT:
For EVERY prediction you emit — ticker_call, sector_call, macro_call, pair_call, conditional_call, binary_event_call, metric_forecast_call, regime_call, and disclosure — add THREE new classification fields: inferred_timeframe_days, timeframe_source, and conviction_level (plus timeframe_category when source is a category default). These fields carry extraction-time labels that downstream scoring, display, and fine-tuning depend on.

═══════════════════════════════════════════════════════════
SECTION 1: TIMEFRAME INFERENCE (NO INVENTED DEFAULTS)
═══════════════════════════════════════════════════════════

The prior system stamped every prediction without an explicit timeframe with a 3-month default. That is wrong for many categories:
- "M2 ticking up means higher Bitcoin" is a macro thesis with a 12+ month horizon, NOT a 3-month trade.
- "Scalping TSLA into close" is an intraday call, NOT a 3-month trade.
- "Weekly calls on NVDA" is a 7-day options bet, NOT a 3-month trade.

NEW RULE: every prediction must EITHER carry an explicit timeframe extracted from the speaker's own words, OR match one of 11 categories with a known default window. Predictions that match neither are REJECTED — do NOT invent a default.

DECISION TREE (apply in order):

  1. Did the speaker name an explicit window?
     - "by Friday", "next week", "in 30 days", "by year end", "in Q2",
       a specific date like "March 15 2026".
     → set inferred_timeframe_days to the resolved integer day count
       from the video publish date to the named target, and set
       timeframe_source="explicit". ALSO set timeframe_category by
       mapping the resolved day count to the closest bucket using the
       BUCKET MAPPING table below. (This rule SUPERSEDES any earlier
       instruction or other instruction block that said to leave
       timeframe_category null on explicit-source predictions —
       Ship #13 requires every accepted prediction to carry a
       category for downstream training-data grouping.)

  2. Otherwise, does the statement match one of these 11 categories?

     | Category                 | Signal phrases                                          | Default days |
     |--------------------------|---------------------------------------------------------|-------------:|
     | day_trading              | intraday, today, this session, scalp, day trade         |           1 |
     | options_short            | weekly calls, Friday options, this week's expiration    |           7 |
     | swing_trade              | this week, next week, swing position, short-term swing  |          14 |
     | options_monthly          | monthly options, end of month, front-month expiry       |          30 |
     | technical_chart          | chart pattern, breakout, next leg, technical setup      |          30 |
     | earnings_cycle           | this earnings, next earnings, into earnings, Q1/Q2/Q3/Q4|          90 |
     | fundamental_quarterly    | next quarter, near-term fundamentals                    |          90 |
     | cyclical_medium          | next few months, into year end, second half, into summer|         180 |
     | macro_thesis             | M2, Fed policy, monetary, liquidity cycle, inflation regime |     365 |
     | structural               | bull market, bear market, new cycle, secular trend      |         365 |
     | long_term_fundamental    | long-term hold, multi-year, secular growth              |         365 |

     → set inferred_timeframe_days to the category's default,
       timeframe_source="category_default", and timeframe_category
       to the category name verbatim.

  3. Neither explicit nor category match?
     → REJECT the prediction. Emit
       {"rejected": true, "reason": "no_timeframe_determinable",
        "notes": "<why>"}
       instead of an accepted prediction. Do NOT invent a default.
       The backend counts these under
       scraper_runs.timeframes_rejected.

BUCKET MAPPING (for step 1 explicit timeframes — assign timeframe_category):

When timeframe_source="explicit", map inferred_timeframe_days to a
category using the table below and set timeframe_category to that name:

| inferred_timeframe_days | timeframe_category    |
|------------------------:|-----------------------|
|                    <= 1 | swing_trade           |
|                    <= 7 | options_short         |
|                   <= 21 | swing_trade           |
|                   <= 30 | technical_chart       |
|                   <= 90 | fundamental_quarterly |
|                  <= 180 | cyclical_medium       |
|                  <= 730 | macro_thesis          |
|                   > 730 | long_term_fundamental |

This mapping is purely numeric — pick the row whose upper bound is the
smallest value >= inferred_timeframe_days. Step 2 still uses the signal-
phrase table for category_default predictions; this bucket table only
applies to the explicit branch from step 1.

day_trading is intentionally NOT assigned by the BUCKET MAPPING table
above. It can only come from Haiku explicitly selecting day_trading in
step 2 (the signal-phrase table), which requires the speaker to
explicitly describe an intraday trade with entry and exit within the
same trading session. A numeric horizon of 1 day alone is not enough —
YouTube analysts routinely say "this should bounce today" without
meaning an intraday trade, and those calls belong in swing_trade, not
day_trading. If you find yourself tempted to pick day_trading from the
horizon number alone, pick swing_trade instead.

EXAMPLES (timeframe only):

Input: "I think Apple hits 250 by end of year"
→ inferred_timeframe_days resolved to days-until-December-31 from publish date, timeframe_source="explicit", timeframe_category mapped from days via the BUCKET MAPPING table (e.g. 270 days → "macro_thesis", 60 days → "fundamental_quarterly").

Input: "I'm scalping TSLA into the close today"
→ inferred_timeframe_days=1, timeframe_source="category_default", timeframe_category="day_trading".

Input: "Weekly calls on NVDA for this Friday"
→ inferred_timeframe_days=7, timeframe_source="category_default", timeframe_category="options_short".

Input: "Nice swing setup on AMD this week"
→ inferred_timeframe_days=14, timeframe_source="category_default", timeframe_category="swing_trade".

Input: "AAPL has a cup-and-handle forming, next leg up is coming"
→ inferred_timeframe_days=30, timeframe_source="category_default", timeframe_category="technical_chart".

Input: "NVDA is going to crush earnings this quarter"
→ inferred_timeframe_days=90, timeframe_source="category_default", timeframe_category="earnings_cycle".

Input: "Energy is setting up for a big run into the second half"
→ inferred_timeframe_days=180, timeframe_source="category_default", timeframe_category="cyclical_medium".

Input: "M2 is ticking up, Bitcoin gets a liquidity tailwind"
→ inferred_timeframe_days=365, timeframe_source="category_default", timeframe_category="macro_thesis".

Input: "We're in a new secular bull market for semis"
→ inferred_timeframe_days=365, timeframe_source="category_default", timeframe_category="structural".

Input: "I like AAPL long-term"
→ REJECT. {"rejected": true, "reason": "no_timeframe_determinable", "notes": "'long-term' is vague with no category signal phrase — could be 1 year or 5 years"}.

Input: "Apple is a great business"
→ REJECT. This isn't a prediction at all, but if Haiku were tempted to extract it as bullish AAPL, rejection reason is no_timeframe_determinable.

Input: "TSLA looks good"
→ REJECT. No timeframe, no category match, and not clearly a prediction.

═══════════════════════════════════════════════════════════
SECTION 2: CONVICTION LEVEL CLASSIFICATION
═══════════════════════════════════════════════════════════

The problem: "TSLA will hit $250" and "TSLA could maybe see upside" are currently scored as the same bullish call. They are not the same. Forecasters hedge to avoid accountability. This field captures the hedging so downstream filters and the fine-tuned model can distinguish confident calls from throwaway guesses.

This field does NOT affect direction, target price, or scoring. It is label-only metadata at this stage. Leaderboard accuracy math is unchanged.

Every prediction MUST carry a conviction_level. No NULLs. Default to "unknown" only when truly indeterminable.

CONVICTION VOCABULARY (assign based on the language INSIDE the verbatim quote):

- strong:       definitive, high-confidence language. Signal phrases:
                "will", "is going to", "absolutely", "definitely", "no doubt",
                "mark my words", "I'm calling it", "guaranteed", "lock",
                "100%", "no question", "without a doubt".
- moderate:     confident opinion but softened. Signal phrases:
                "I think", "expect to", "likely", "probably", "believe",
                "my view is", "I see", "should", "looking like".
- hedged:       explicit uncertainty. Signal phrases:
                "could", "might", "maybe", "potentially", "possibly",
                "perhaps", "if things go right", "in my opinion", "I could see".
- hypothetical: conditional framing where the claim is contingent on
                another event. Signal phrases:
                "if X then Y", "in a world where", "assuming",
                "should X happen", "were X to", "provided that".
                Conditional_call predictions are almost always
                hypothetical by construction.
- unknown:      no clear signal from the verbatim quote. Use sparingly —
                assign this only when the sentence genuinely doesn't
                commit to any of the four levels above.

CONVICTION EXAMPLES:

"AAPL is going to hit two fifty by December, mark my words"
  → conviction_level="strong"

"I think NVDA crushes earnings next quarter"
  → conviction_level="moderate"

"TSLA could potentially see upside into year end"
  → conviction_level="hedged"

"If the Fed cuts fifty bips in March, stocks rally ten percent easy"
  → conviction_level="hypothetical"

"The Fed is absolutely going to cut at the March meeting"
  → conviction_level="strong"

"I expect MSFT to report five dollars EPS next print"
  → conviction_level="moderate"

"Maybe ROKU sees a bounce here if the charts hold"
  → conviction_level="hedged"

"Assuming inflation prints cool, bonds rally hard"
  → conviction_level="hypothetical"

═══════════════════════════════════════════════════════════
SECTION 3: COMBINED OUTPUT FORMAT
═══════════════════════════════════════════════════════════

Add the new fields to every accepted prediction object alongside the existing type-specific fields. Example combining all four ship features on one ticker_call:

{
  "ticker": "TSLA",
  "direction": "bullish",
  "price_target": null,
  "verbatim_quote": "Tesla is so beaten down here, I've been watching it closely. A relief rally in these magnificent stocks could potentially drive a significant rebound into the summer.",
  "inferred_timeframe_days": 180,
  "timeframe_source": "category_default",
  "timeframe_category": "cyclical_medium",
  "conviction_level": "hedged",
  "reasoning": "TSLA is the antecedent for 'these magnificent stocks' (resolved). 'Into the summer' from a winter publish = cyclical_medium (~180d). 'Could potentially' is hedged language."
}

Rejection example (unresolvable reference — from the SOURCE_TIMESTAMP block rule):

{
  "rejected": true,
  "reason": "unresolvable_reference",
  "notes": "'these stocks' has no antecedent in the surrounding sentences — could not identify which tickers are being discussed."
}

Rejection example (no determinable timeframe — this block's new rule):

{
  "rejected": true,
  "reason": "no_timeframe_determinable",
  "notes": "'long term' is vague — no explicit window, no category signal phrase strong enough to infer a default."
}

═══════════════════════════════════════════════════════════
RULES RECAP
═══════════════════════════════════════════════════════════

- MUST add inferred_timeframe_days, timeframe_source, and conviction_level to every ACCEPTED prediction object.
- MUST add timeframe_category when timeframe_source="category_default".
- MUST reject with reason="no_timeframe_determinable" when neither explicit nor category works.
- MUST pick conviction from the five-value vocabulary above — no free-text.
- MUST use "unknown" conviction sparingly.
- MUST NOT use inferred_timeframe_days to override direction or target.
- MUST NOT treat conviction as affecting the prediction's scoring — it is label-only metadata captured for fine-tuning.
- Rejections follow the same shape as the SOURCE_TIMESTAMP block's reference-resolution rejections: emit a single object with rejected=true, reason, and notes.

PREDICTION VALIDITY CHECK (mandatory — apply to every candidate):
Before accepting a prediction, verify it is a genuine forward-looking claim. REJECT the prediction (use the standard rejection format) if the quote is ANY of the following:
- A position disclosure with no forward thesis ('I own this stock', 'this is my biggest holding', 'we decided to purchase')
- A description of what already happened ('the stock dropped 12% yesterday', 'revenue was $12.1 billion')
- A research note or watching statement ('I'm going to look into this more', 'keeping an eye on it', 'we'll see')
- Reading data or metrics with no opinion ('intrinsic value is $133', 'PE ratio of 25')
- Conversation filler with no actionable claim ('yeah interesting things happening', 'let's see what happens')

A valid prediction MUST contain a forward-looking directional claim — the speaker expects the price to go up or down, recommends buying or selling, states a price target, or expresses a thesis about future performance with reasoning. If the quote is just commentary, disclosure, or observation without a forward claim, REJECT it.

Output JSON only. Be concise."""


YOUTUBE_HAIKU_VAGUE_TIMEFRAME_INSTRUCTIONS = """VAGUE TIMEFRAME MAPPING (OVERRIDE):
The METADATA_ENRICHMENT block above rejects predictions where the forecaster uses a vague time phrase like "long-term" because it could mean 1 year or 5 years. This block OVERRIDES that rejection for a specific set of conventional finance phrases by mapping them to standard evaluation buckets.

IMPORTANT DISTINCTION:
- Vague time phrase IS present ("long term", "near term", etc.) → MAP to a bucket using the table below. Set timeframe_source="inferred".
- ZERO time signal (no time phrase at all, not even a vague one) → still REJECT with reason="no_timeframe_determinable". This override does NOT create a universal default.

VAGUE PHRASE → BUCKET MAPPING:

| Phrases                                              | inferred_timeframe_days |
|------------------------------------------------------|------------------------:|
| "short term", "near term", "coming weeks"            |                      30 |
| "medium term", "intermediate"                        |                     180 |
| "long term", "long run", "years ahead", "multi-year" |                     365 |
| "very long term", "decade", "generational"           |                    1825 |

When a forecaster uses one of these phrases (case-insensitive, hyphenated or not — "long-term" = "long term"):
  → set inferred_timeframe_days to the mapped value from the table
  → set timeframe_source="inferred"
  → do NOT set timeframe_category (that field is only for category_default)
  → do NOT reject the prediction

EXAMPLES:

Input: "I like AAPL long-term"
→ ACCEPT. inferred_timeframe_days=365, timeframe_source="inferred". (Previously rejected — now mapped.)

Input: "NVDA is a great short-term trade here"
→ ACCEPT. inferred_timeframe_days=30, timeframe_source="inferred".

Input: "Tesla is a generational wealth builder"
→ ACCEPT. inferred_timeframe_days=1825, timeframe_source="inferred".

Input: "I'm bullish medium term on AMD"
→ ACCEPT. inferred_timeframe_days=180, timeframe_source="inferred".

Input: "AAPL looks good" (NO time phrase at all)
→ Still REJECT. No vague phrase present, no category match, no explicit window. reason="no_timeframe_determinable".

Input: "TSLA is interesting" (NO time phrase at all)
→ Still REJECT. Zero time signal.

PRIORITY: This mapping is checked AFTER explicit timeframe resolution (step 1 in the METADATA_ENRICHMENT decision tree) and AFTER category matching (step 2), but BEFORE the final rejection (step 3). If a prediction already resolved via step 1 or step 2, this block does not apply.

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


def fetch_transcript_with_timestamps(video_id: str) -> dict:
    """Fetch a YouTube video's captions with both segment-level and
    (when available) word-level timing data.

    Returns a dict with shape:
      {
        "text":           concatenated transcript text (str), empty on failure
        "lang":           ISO language code of the captions (e.g. "en")
        "status":         "ok" | "no_transcript" | "transcripts_disabled" |
                          "video_unavailable" | "empty_transcript" |
                          "library_missing" | "error: <ClassName>: <msg>"
        "segments":       list of {"start_ms", "duration_ms", "text"} dicts,
                          one per segment from the base XML feed. Always
                          populated when text is non-empty.
        "words":          list of {"start_ms", "text"} word-level entries
                          derived from YouTube's JSON3 ASR format, OR None
                          if the captions are manually-authored (one seg
                          per event) or the JSON3 endpoint refused.
        "has_word_level": bool — True only when `words` is a populated list
                          with at least one entry.
        "is_generated":   bool — whether the captions are auto-ASR
        "fetched_at":     UTC datetime of the fetch
      }

    Strategy:
      1. Call api.list(video_id) to enumerate available transcripts.
      2. Prefer an English caption. Among English tracks, prefer the
         GENERATED (auto-ASR) one because only auto-ASR produces word-
         level timing in JSON3. If only manual is available, use that
         and accept that word-level data won't exist.
      3. Fetch the raw XML via the library's existing path to populate
         segments + text (this preserves backward compat).
      4. Attempt a parallel fetch of the same URL with &fmt=json3 using
         the library's internal HTTP client (so Webshare proxy + cookies
         are inherited). Parse the JSON3 events → word-level list.
      5. On any JSON3 failure, silently fall back: has_word_level=False,
         words=None. segments/text stay populated.

    Does NOT consume YouTube Data API quota — the library scrapes the
    timedtext endpoints directly.
    """
    from datetime import datetime as _dt
    if not video_id:
        return {
            "text": "", "lang": None, "status": "no_video_id",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": False, "fetched_at": _dt.utcnow(),
        }
    try:
        from youtube_transcript_api import (
            TranscriptsDisabled,
            NoTranscriptFound,
            VideoUnavailable,
        )
    except ImportError:
        return {
            "text": "", "lang": None, "status": "library_missing",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": False, "fetched_at": _dt.utcnow(),
        }

    api = _build_transcript_api()

    # Step 1: list available transcripts and pick one.
    chosen_transcript = None
    try:
        tl = api.list(video_id)
        # Collect into a list so we can iterate multiple times.
        available = list(tl)
        # Prefer English, with generated (auto-ASR) first for word-level.
        english = [t for t in available if t.language_code == "en"]
        english_generated = [t for t in english if t.is_generated]
        if english_generated:
            chosen_transcript = english_generated[0]
        elif english:
            chosen_transcript = english[0]
        elif available:
            chosen_transcript = available[0]
    except TranscriptsDisabled:
        return {
            "text": "", "lang": None, "status": "transcripts_disabled",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": False, "fetched_at": _dt.utcnow(),
        }
    except VideoUnavailable:
        return {
            "text": "", "lang": None, "status": "video_unavailable",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": False, "fetched_at": _dt.utcnow(),
        }
    except NoTranscriptFound:
        return {
            "text": "", "lang": None, "status": "no_transcript",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": False, "fetched_at": _dt.utcnow(),
        }
    except Exception as e:
        return {
            "text": "", "lang": None,
            "status": f"error: {type(e).__name__}: {str(e)[:120]}",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": False, "fetched_at": _dt.utcnow(),
        }

    if chosen_transcript is None:
        return {
            "text": "", "lang": None, "status": "no_transcript",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": False, "fetched_at": _dt.utcnow(),
        }

    # Step 2: fetch the XML payload via the library (same as before) to
    # populate segments + text. Use the library's public .fetch() so any
    # retries / proxy logic stays centralized.
    lang = chosen_transcript.language_code or "unknown"
    is_generated = bool(chosen_transcript.is_generated)
    segments: list[dict] = []
    text_parts: list[str] = []
    try:
        fetched = chosen_transcript.fetch()
        for snippet in fetched:
            t = getattr(snippet, "text", None)
            if t is None and isinstance(snippet, dict):
                t = snippet.get("text")
            if not t:
                continue
            start = float(getattr(snippet, "start", 0.0) or 0.0)
            dur = float(getattr(snippet, "duration", 0.0) or 0.0)
            segments.append({
                "start_ms": int(round(start * 1000)),
                "duration_ms": int(round(dur * 1000)),
                "text": t.strip(),
            })
            text_parts.append(t.strip())
    except Exception as e:
        return {
            "text": "", "lang": lang,
            "status": f"error: {type(e).__name__}: {str(e)[:120]}",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": is_generated, "fetched_at": _dt.utcnow(),
        }

    if not text_parts:
        return {
            "text": "", "lang": lang, "status": "empty_transcript",
            "segments": [], "words": None, "has_word_level": False,
            "is_generated": is_generated, "fetched_at": _dt.utcnow(),
        }
    text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()

    # Step 3: try the JSON3 endpoint for word-level data. The library's
    # internal http client has the Webshare proxy attached, so reusing
    # it keeps proxy discipline automatic. chosen_transcript._url is
    # the same timedtext URL the library used above — we just append
    # &fmt=json3 to flip YouTube's response format.
    words = None
    has_word_level = False
    if is_generated:  # only auto-ASR produces word-level data
        try:
            raw_url = getattr(chosen_transcript, "_url", None)
            http_client = getattr(chosen_transcript, "_http_client", None)
            if raw_url and http_client is not None:
                json3_url = raw_url + ("&" if "?" in raw_url else "?") + "fmt=json3"
                resp = http_client.get(json3_url)
                if getattr(resp, "status_code", 0) == 200:
                    import json as _json
                    data = _json.loads(resp.text)
                    events = data.get("events") or []
                    words_out: list[dict] = []
                    for ev in events:
                        ev_start = int(ev.get("tStartMs") or 0)
                        segs = ev.get("segs") or []
                        if not segs:
                            continue
                        # Multi-seg events carry per-word timing. Single-seg
                        # events (manual captions, or auto-ASR on a section
                        # where YouTube didn't provide word splits) are just
                        # treated as one word starting at ev_start.
                        for s in segs:
                            w_text = s.get("utf8") or ""
                            if not w_text or w_text == "\n":
                                continue
                            offset = int(s.get("tOffsetMs") or 0)
                            words_out.append({
                                "start_ms": ev_start + offset,
                                "text": w_text,
                            })
                    if words_out:
                        words = words_out
                        # Only claim word-level if at least SOME events had
                        # multi-segment splits (= actual per-word data).
                        # A purely single-seg JSON3 response means the same
                        # information is in segments already.
                        multi = sum(
                            1 for ev in events
                            if len(ev.get("segs") or []) > 1
                        )
                        has_word_level = multi > 0
        except Exception as _je:
            log.info("[YT-CLF] JSON3 word-level fetch failed for %s: %s", video_id, _je)
            words = None
            has_word_level = False

    return {
        "text": text,
        "lang": lang,
        "status": "ok",
        "segments": segments,
        "words": words,
        "has_word_level": has_word_level,
        "is_generated": is_generated,
        "fetched_at": _dt.utcnow(),
    }


def fetch_transcript(video_id: str) -> tuple[str | None, str | None]:
    """Legacy wrapper over fetch_transcript_with_timestamps that returns
    only (text, status) — preserved so existing callers in youtube_backfill,
    the channel monitor pre-ship-9 path, and any external jobs keep
    working unchanged. When the new ship's timestamp flag is OFF, this
    wrapper is what the monitor calls; when the flag is on, the monitor
    calls the richer fetcher directly to keep word-level data in scope.
    """
    if not video_id:
        return None, "no_video_id"
    result = fetch_transcript_with_timestamps(video_id)
    if not result["text"]:
        return None, result["status"]
    # Status values from the rich fetcher are richer than the legacy tags,
    # but "ok" → lang tag for backward compat with callers that special-case
    # the string "en" vs "error: …".
    status = result["lang"] if result["status"] == "ok" else result["status"]
    return result["text"], status


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


def _classify_video_qwen(
    channel_name: str,
    title: str,
    publish_date: str,
    chunks: list[str],
    *,
    video_id: str | None = None,
    telemetry: dict,
) -> tuple[list[dict], dict] | None:
    """Qwen path: call RunPod vLLM for each chunk, parse JSON, validate.

    Returns (predictions, telemetry) on success, or None if RunPod fails
    (caller should fall through to Haiku).
    """
    _verified_by_local.tag = VERIFIED_BY_QWEN
    telemetry["prompt_variant"] = "qwen_finetuned"

    all_preds: list[dict] = []
    total_cost = 0.0
    total_latency = 0.0

    for i, chunk in enumerate(chunks):
        telemetry["chunks"] += 1

        # Circuit breaker check
        if is_circuit_breaker_tripped():
            tag = (
                f"RunPod circuit breaker tripped — "
                f"{RUNPOD_CIRCUIT_BREAKER_THRESHOLD} consecutive failures, "
                f"skipping chunk {i+1}/{len(chunks)}"
            )
            print(f"[YOUTUBE-QWEN] {tag}", flush=True)
            telemetry["error"] = tag[:300]
            yt_stats.circuit_breaker_trips += 1
            return None

        try:
            raw_text, cost, latency = call_runpod_vllm(
                chunk,
                channel_name=channel_name,
                title=title,
                publish_date=publish_date,
                video_id=video_id,
            )
            total_cost += cost
            total_latency += latency
        except Exception as e:
            tag = f"RunPod error chunk {i+1}/{len(chunks)}: {e}"
            log.warning("[YT-CLF] %s", tag)
            telemetry["error"] = tag[:300]
            print(
                f"[YOUTUBE-QWEN] Classification FAILED video {video_id or '?'}: "
                f"{type(e).__name__}, skipping",
                flush=True,
            )
            # Return None → caller falls back to Haiku (or skips if credits empty)
            return None

        # Strip markdown fences
        content = raw_text
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as pe:
            log.warning(
                "[YT-CLF] Qwen parse error chunk %d/%d: %s | raw=%r",
                i + 1, len(chunks), pe, content[:200],
            )
            telemetry["error"] = f"qwen_parse_error: {str(pe)[:120]}"
            return None

        # Qwen may return a single dict or a list
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            telemetry["error"] = f"qwen_non_list: {type(parsed).__name__}"
            return None

        # Normalize Qwen output to match the fields the validator expects.
        # Qwen outputs: source_verbatim_quote, timeframe_category, inferred_timeframe_days
        # Validator expects: verbatim_quote, timeframe_source
        for p in parsed:
            if isinstance(p, dict):
                # Map source_verbatim_quote → verbatim_quote
                if "source_verbatim_quote" in p and "verbatim_quote" not in p:
                    p["verbatim_quote"] = p["source_verbatim_quote"]
                # The validator rejects predictions without timeframe_source.
                # Qwen was trained on predictions that had both explicit and
                # category-default timeframes, so we mark as "inferred" which
                # the validator accepts at any horizon.
                if "timeframe_source" not in p:
                    p["timeframe_source"] = "inferred"

        telemetry["predictions_raw"] += len(parsed)
        all_preds.extend(parsed)

        if i < len(chunks) - 1:
            time.sleep(0.5)

    telemetry["estimated_cost_usd"] = total_cost

    # Validate using the same validator as Haiku path
    valid = _validate_and_dedupe_predictions(all_preds)
    if len(valid) > MAX_PREDICTIONS_PER_VIDEO:
        log.warning(
            "[YT-CLF] Qwen: %s returned %d preds, capping at %d",
            channel_name, len(valid), MAX_PREDICTIONS_PER_VIDEO,
        )
        valid = valid[:MAX_PREDICTIONS_PER_VIDEO]

    telemetry["predictions_validated"] = len(valid)
    telemetry["latency"] = total_latency
    vby = _get_active_verified_by()
    print(
        f"[YOUTUBE-QWEN] Classified video {video_id or '?'}: "
        f"{len(valid)} predictions extracted, classifier={vby}, "
        f"latency={total_latency:.1f}s, cost=${total_cost:.4f}",
        flush=True,
    )
    yt_stats.predictions += len(valid)
    return valid, telemetry


def classify_video(channel_name: str, title: str, publish_date: str,
                   transcript: str,
                   video_id: str | None = None,
                   db=None) -> tuple[list[dict], dict]:
    """Classify a video transcript and extract financial predictions.

    Model selection (checked once per call):
      - USE_FINETUNED_MODEL=true → try Qwen 2.5 7B on RunPod first.
        If RunPod fails for ANY reason, fall back to Haiku silently.
      - USE_FINETUNED_MODEL=false or unset → Haiku only.

    verified_by tagging:
      - Qwen path:  youtube_qwen_v1
      - Haiku path:  youtube_haiku_v1

    Returns (predictions, telemetry):
      predictions — list of validated prediction dicts (may be empty)
      telemetry   — dict with token usage, chunk count, last_status, and
                    optionally an error tag for non-fatal classifier failures

    NEVER raises. On any classifier failure (no key, HTTP error, parse
    error) returns ([], {"error": "<tag>"}). The caller should treat
    empty predictions + an error tag as a transient skip.
    """
    telemetry: dict = {"chunks": 0, "input_tokens": 0, "output_tokens": 0,
                       "last_status": None, "predictions_raw": 0,
                       "prompt_variant": "standard"}
    chunks = chunk_transcript(transcript or "")
    if not chunks:
        telemetry["error"] = "empty_transcript"
        return [], telemetry

    # ── Qwen path (fine-tuned model on RunPod) ─────────────────────────
    if USE_FINETUNED_MODEL:
        try:
            result = _classify_video_qwen(
                channel_name, title, publish_date, chunks,
                video_id=video_id, telemetry=telemetry,
            )
            if result is not None:
                return result
            # result is None → Qwen failed, fall through to Haiku
        except Exception as e:
            log.warning("[YT-CLF] Qwen path failed, falling back to Haiku: %s", e)
            # Reset telemetry for Haiku retry
            telemetry["chunks"] = 0
            telemetry["predictions_raw"] = 0

    # ── Haiku path (original) ──────────────────────────────────────────
    _verified_by_local.tag = VERIFIED_BY_HAIKU

    if not ANTHROPIC_API_KEY:
        telemetry["error"] = "no_api_key"
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
    use_disclosure = False
    use_regime = False
    use_source_timestamps = False
    use_metadata_enrichment = False
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
        try:
            from feature_flags import is_disclosure_extraction_enabled
            use_disclosure = is_disclosure_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] disclosure flag check failed: %s", _e)
            use_disclosure = False
        try:
            from feature_flags import is_regime_call_extraction_enabled
            use_regime = is_regime_call_extraction_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] regime flag check failed: %s", _e)
            use_regime = False
        try:
            from feature_flags import is_source_timestamps_enabled
            use_source_timestamps = is_source_timestamps_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] source_timestamps flag check failed: %s", _e)
            use_source_timestamps = False
        try:
            from feature_flags import is_prediction_metadata_enrichment_enabled
            use_metadata_enrichment = is_prediction_metadata_enrichment_enabled(db)
        except Exception as _e:
            log.warning("[YT-CLF] metadata_enrichment flag check failed: %s", _e)
            use_metadata_enrichment = False
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
    if use_disclosure:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_DISCLOSURE_INSTRUCTIONS
    if use_regime:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_REGIME_INSTRUCTIONS
    # The SOURCE_TIMESTAMP block asks Haiku to add a verbatim_quote
    # field to every prediction emitted by ANY of the previous blocks
    # (regime_call included), so it must be appended after the
    # category-specific instructions. METADATA_ENRICHMENT (ship #9
    # rescoped) is the 14th and current-last layer — it runs AFTER
    # source_timestamp so extended-prompt cache entries stay stable
    # for users with timestamps=on and metadata=off.
    if use_source_timestamps:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_SOURCE_TIMESTAMP_INSTRUCTIONS
    if use_metadata_enrichment:
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_METADATA_ENRICHMENT_INSTRUCTIONS
        active_system = active_system + "\n\n" + YOUTUBE_HAIKU_VAGUE_TIMEFRAME_INSTRUCTIONS
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
    telemetry["disclosure_enabled"] = bool(use_disclosure)
    telemetry["regime_enabled"] = bool(use_regime)
    telemetry["source_timestamps_enabled"] = bool(use_source_timestamps)
    telemetry["metadata_enrichment_enabled"] = bool(use_metadata_enrichment)
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
        f"conditional={'on' if use_conditional else 'off'} "
        f"disclosure={'on' if use_disclosure else 'off'} "
        f"regime={'on' if use_regime else 'off'} "
        f"timestamps={'on' if use_source_timestamps else 'off'} "
        f"metadata={'on' if use_metadata_enrichment else 'off'}",
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
            tag = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"[YT-CLF] Haiku error on chunk {i+1}/{len(chunks)} for "
                  f"\"\"{title[:60]}\": {tag}", flush=True)
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
        # Ship #9 (rescoped) — rejection handling. Split Haiku's
        # response into accepted entries and explicit rejections. The
        # metadata enrichment prompt block teaches Haiku to emit
        # {"rejected": true, "reason": "...", "notes": "..."} for
        # predictions that fail the no_timeframe_determinable or
        # unresolvable_reference checks. These entries are NOT fed to
        # the validator — instead, they're buffered on telemetry so
        # the channel monitor can log them to youtube_scraper_rejections
        # with full context (channel_id, publish_dt, transcript snippet)
        # that isn't in scope here.
        for _p in parsed:
            if isinstance(_p, dict) and _p.get("rejected") is True:
                telemetry.setdefault("rejections", []).append(_p)
                reason = str(_p.get("reason") or "").strip().lower()
                if reason == "no_timeframe_determinable":
                    telemetry["timeframes_rejected"] = int(
                        telemetry.get("timeframes_rejected", 0)
                    ) + 1
                elif reason == "unresolvable_reference":
                    telemetry["reference_rejected"] = int(
                        telemetry.get("reference_rejected", 0)
                    ) + 1
            else:
                all_preds.append(_p)

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
    seen_disclosures: set[tuple[str, str, str]] = set()
    seen_regimes: set[tuple[str, str]] = set()
    out: list[dict] = []
    for p in raw:
        if not isinstance(p, dict):
            continue

        # Ship #14 — long-horizon acceptance gate. Replaces the Ship #13
        # blanket >3650-day rejection. The new rule:
        #
        #   - timeframe_source IS NULL → reject (Haiku leaked a
        #     degraded prediction without using the rejection format;
        #     happens to BTC-style hallucinations like id=608559 with
        #     window=7669 / src=NULL).
        #   - timeframe_source = 'category_default' AND days > 1825
        #     → reject (category defaults max out at 365; anything past
        #       1825 means the resolver dropped the wrong window onto a
        #       category-tagged row — almost certainly invented).
        #   - timeframe_source IN ('explicit', 'inferred') with ANY days
        #     → ACCEPT. The speaker said it (or a vague-phrase mapping
        #       like "generational" → 1825 fired). Multi-year valuation
        #       theses ("Tesla $500 by 2030", "MSFT 5-10-15 year hold")
        #       are legitimate training data and the leaderboard should
        #       show them.
        #
        # For accepted predictions where days > 1825, mark them
        # _evaluation_deferred so the resolver writes
        # evaluation_deferred=TRUE on the Prediction row. The evaluator
        # then skips them (they stay outcome='pending' until the window
        # actually resolves) and the frontend renders a "Long-term
        # thesis — evaluation pending" badge instead of HIT/NEAR/MISS.
        _ts_src = p.get("timeframe_source")
        _inferred = p.get("inferred_timeframe_days")

        # Reject NULL-source predictions. Rejection sentinels have
        # no timeframe_source by design and are handled upstream in
        # classify_video, but keep the escape defensively in case a
        # sentinel leaks through this path.
        if not _ts_src:
            if not p.get("rejected"):
                continue

        # Reject category_default rows with extreme windows.
        if (
            _ts_src == "category_default"
            and isinstance(_inferred, (int, float))
            and float(_inferred) > 1825
        ):
            continue

        # Mark long-horizon accepted predictions for deferred evaluation.
        if isinstance(_inferred, (int, float)) and float(_inferred) > 1825:
            p["_evaluation_deferred"] = True
            p["_evaluation_deferred_reason"] = "long_horizon_thesis"

        # Ship #9 — source_timestamps. Normalize the verbatim_quote
        # field on EVERY prediction dict BEFORE any branch takes it.
        # All 8 insert functions will look at p["_verbatim_quote"]
        # (via _resolve_source_timestamp) so normalizing once here
        # means each branch below doesn't need its own extraction.
        _raw_vq = p.get("verbatim_quote")
        if isinstance(_raw_vq, str):
            _norm_vq = re.sub(r"\s+", " ", _raw_vq).strip()[:500]
        else:
            _norm_vq = ""
        p["_verbatim_quote"] = _norm_vq or None

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

        # Disclosure branch: derived_from='disclosure' — past-tense
        # position statement. Goes into the disclosures table, NOT
        # predictions. Required fields are ticker and action (from the
        # 7-value allowlist). Dedup key is (ticker_upper, action_lower,
        # disclosed_date) so the same "I bought AMD today" mention
        # repeated in two transcript chunks collapses, but buy + add
        # on the same ticker in the same video stay distinct.
        if str(p.get("derived_from") or "").strip().lower() == "disclosure":
            ticker_val = (p.get("ticker") or "").upper().strip().lstrip("$")
            ticker_val = re.sub(r"[^A-Z0-9]", "", ticker_val)
            action_val = (p.get("action") or "").strip().lower()
            if not ticker_val or len(ticker_val) > 5:
                continue
            if action_val not in ("buy", "sell", "add", "trim", "starter", "exit", "hold"):
                continue
            # disclosed_at: parse ISO date if given, else fall back to
            # the video's publish date (Haiku should have resolved
            # "today"/"yesterday" already but this is a safety net).
            raw_date = p.get("disclosed_at")
            disclosed_date = None
            if raw_date:
                try:
                    from datetime import datetime as _dt
                    disclosed_date = _dt.strptime(
                        str(raw_date)[:10], "%Y-%m-%d"
                    ).date()
                except (TypeError, ValueError):
                    disclosed_date = None
            # Key on the date string (or "unknown") so two disclosures
            # on different days survive. The insert path falls back to
            # publish_date when disclosed_date is None.
            key = (
                ticker_val,
                action_val,
                disclosed_date.isoformat() if disclosed_date else "unknown",
            )
            if key in seen_disclosures:
                continue
            seen_disclosures.add(key)
            p["ticker"] = ticker_val
            p["_kind"] = "disclosure"
            p["_derived_from"] = "disclosure"
            p["_disclosure_action"] = action_val
            p["_disclosed_at_date"] = disclosed_date
            # Size fields: normalize one-of. If the speaker gave a
            # qualitative size, lowercase it. Numeric sizes pass
            # through as-is; the insert path will coerce.
            qual = (p.get("size_qualitative") or "").strip().lower() or None
            if qual and qual not in ("small", "medium", "large", "full"):
                qual = None
            p["_size_qualitative"] = qual
            p["_size_shares"] = p.get("size_shares")
            p["_size_pct"] = p.get("size_pct")
            p["_entry_price"] = p.get("entry_price")
            p["_reasoning_text"] = (p.get("reasoning_text") or None)
            out.append(p)
            continue

        # Regime-call branch: derived_from='regime_call' — structural
        # market-phase claim. No price target, no explicit direction
        # (direction is derived from regime_type at insert time). The
        # validator enforces the 8-value regime_type allowlist and
        # defaults the instrument to SPY. Dedup on
        # (regime_type, regime_instrument) per video so duplicate
        # mentions across transcript chunks collapse.
        if str(p.get("derived_from") or "").strip().lower() == "regime_call":
            regime_type = (p.get("regime_type") or "").strip().lower()
            if regime_type not in (
                "bull_continuing", "bull_starting", "topping",
                "bear_starting", "bear_continuing", "bottoming",
                "correction", "consolidation",
            ):
                continue
            instrument = (p.get("regime_instrument") or "").upper().strip().lstrip("$")
            instrument = re.sub(r"[^A-Z0-9]", "", instrument)
            if not instrument:
                instrument = "SPY"
            if len(instrument) > 5:
                continue
            key = (regime_type, instrument)
            if key in seen_regimes:
                continue
            seen_regimes.add(key)
            # Derive direction from regime_type so the existing ticker
            # index / direction queries still work. bull_* and bottoming
            # are bullish; bear_* and topping are bearish; correction
            # and consolidation are neutral (no directional bet).
            if regime_type in ("bull_continuing", "bull_starting", "bottoming"):
                derived_dir = "bullish"
            elif regime_type in ("bear_continuing", "bear_starting", "topping"):
                derived_dir = "bearish"
            else:
                derived_dir = "neutral"
            p["ticker"] = instrument
            p["direction"] = derived_dir
            p["_kind"] = "regime_call"
            p["_derived_from"] = "regime_call"
            p["_regime_type"] = regime_type
            p["_regime_instrument"] = instrument
            # Ensure no stray price_target sneaks through from a Haiku
            # hallucination — regime_call is always target-free.
            p["price_target"] = None
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


def _resolve_source_timestamp(
    pred: dict,
    transcript_data: dict | None,
    stats: dict | None,
) -> dict:
    """Ship #9 shared helper. Resolves a prediction's verbatim_quote
    to a source_timestamp_seconds / method / confidence triple and
    returns a kwargs dict suitable for splatting into the Prediction
    constructor.

    Contract:
      - When transcript_data is None (flag off, non-YouTube scraper,
        or backfill mode without the rich fetcher), returns {} so the
        caller's existing Prediction(...) construction is unchanged.
      - When transcript_data is a dict but there is no verbatim_quote
        on pred, returns {} — still a no-op, but records the miss in
        stats["timestamps_failed"] so admin diagnostics show the gap.
      - When the matcher returns a real timestamp, returns all four
        source_timestamp_* column values AND increments
        stats["timestamps_matched"].
      - When the matcher returns 'unknown', returns the verbatim quote
        and method='unknown' (so the audit trail is still stored) but
        leaves source_timestamp_seconds=None. Increments
        stats["timestamps_failed"].

    NEVER raises — any internal failure is caught and degraded to a
    silent empty-dict return so the prediction insert is unaffected.
    """
    try:
        if transcript_data is None:
            return {}
        verbatim = pred.get("_verbatim_quote") or pred.get("verbatim_quote")
        if not verbatim or not isinstance(verbatim, str):
            if stats is not None:
                stats["timestamps_failed"] = int(
                    stats.get("timestamps_failed", 0)
                ) + 1
            return {}
        # Import inside the function to avoid a module-load-time cycle
        # if the matcher ever imports back from youtube_classifier.
        from jobs.timestamp_matcher import match_quote_to_timestamp
        seconds, method, confidence = match_quote_to_timestamp(
            verbatim, transcript_data,
        )
        if seconds is not None:
            if stats is not None:
                stats["timestamps_matched"] = int(
                    stats.get("timestamps_matched", 0)
                ) + 1
            return {
                "source_timestamp_seconds": int(seconds),
                "source_timestamp_method": method,
                "source_verbatim_quote": _fix_caption_spelling(verbatim)[:2000],
                "source_timestamp_confidence": float(confidence),
            }
        # Match failed — still store the quote for audit, leave seconds NULL.
        if stats is not None:
            stats["timestamps_failed"] = int(
                stats.get("timestamps_failed", 0)
            ) + 1
        return {
            "source_timestamp_seconds": None,
            "source_timestamp_method": "unknown",
            "source_verbatim_quote": _fix_caption_spelling(verbatim)[:2000],
            "source_timestamp_confidence": 0.0,
        }
    except Exception as _e:
        log.info("[YT-CLF] _resolve_source_timestamp failed: %s", _e)
        if stats is not None:
            stats["timestamps_failed"] = int(
                stats.get("timestamps_failed", 0)
            ) + 1
        return {}


# ── Training completeness gate ────────────────────────────────────────────
#
# Returns the list of NULL required training fields when the inline
# extraction path is active and the prediction would land incomplete.
# Empty list means "OK to insert". Returns immediately (no flag read,
# no work) when transcript_data is None — that path is reserved for
# backfill jobs and non-YouTube scrapers and must never be gated.
#
# The gate is path-aware to the upstream feature flags: timestamp
# fields are only required when ENABLE_SOURCE_TIMESTAMPS is on, and
# metadata fields are only required when
# ENABLE_PREDICTION_METADATA_ENRICHMENT is on. With both flags off the
# gate is a no-op even with REQUIRE_COMPLETE_PREDICTIONS on.

_TRAINING_REQUIRED_TS_FIELDS = (
    "source_timestamp_seconds",
    "source_verbatim_quote",
)
_TRAINING_REQUIRED_META_FIELDS = (
    "timeframe_category",
    "inferred_timeframe_days",
    "conviction_level",
)


def _training_completeness_gaps(
    ts_fields: dict,
    meta_fields: dict,
    transcript_data: dict | None,
    *,
    db,
    stats: dict | None,
    direction: str | None = None,
) -> list[str]:
    """Return [] if the prediction is OK to insert, otherwise the list
    of required training fields that are missing. Increments stats
    counters per missing field so admin diagnostics surface the dominant
    rejection bucket. Never raises — any internal failure degrades to
    a permissive [] return so the existing insert path is unaffected."""
    if transcript_data is None:
        return []
    try:
        from feature_flags import (
            is_require_complete_predictions_enabled,
            is_source_timestamps_enabled,
            is_prediction_metadata_enrichment_enabled,
        )
        if not is_require_complete_predictions_enabled(db):
            return []
        ts_required = bool(is_source_timestamps_enabled(db))
        meta_required = bool(is_prediction_metadata_enrichment_enabled(db))
    except Exception as _e:
        log.warning("[YT-CLF] training-completeness gate flag check failed: %s", _e)
        return []
    missing: list[str] = []
    # Neutral (or empty) direction is not actionable for training — a
    # prediction with no directional claim can't be scored against a
    # price series, so it must not leak into the training population.
    if not direction or str(direction).strip().lower() in ("", "neutral"):
        missing.append("direction_not_actionable")
        if stats is not None:
            stats["neutral_direction_blocked"] = int(
                stats.get("neutral_direction_blocked", 0)
            ) + 1
    if ts_required:
        for f in _TRAINING_REQUIRED_TS_FIELDS:
            if not ts_fields.get(f):
                missing.append(f)
    if meta_required:
        for f in _TRAINING_REQUIRED_META_FIELDS:
            if not meta_fields.get(f):
                missing.append(f)
    if missing:
        # Stdout-visible log so tail/grep can show which fields the
        # classifier is dropping rows on. The full per-row context
        # (ticker, video_id) lands in youtube_scraper_rejections via
        # the caller's _reject(...) path, so a counter-style line here
        # is sufficient for live monitoring.
        log.info("[YT-CLF] gate skip — missing %s", ",".join(missing))
        if stats is not None:
            stats["incomplete_predictions_skipped"] = int(
                stats.get("incomplete_predictions_skipped", 0)
            ) + 1
            for f in missing:
                key = f"skipped_missing_{f}"
                stats[key] = int(stats.get(key, 0)) + 1
    return missing


_VALID_CONVICTION_LEVELS = {
    "strong", "moderate", "hedged", "hypothetical", "unknown",
}
_VALID_TIMEFRAME_SOURCES = {"explicit", "category_default", "inferred"}


def _resolve_metadata_enrichment(
    pred: dict,
    stats: dict | None,
    *,
    publish_date: datetime | None = None,
    default_window_days: int = 90,
    db=None,
) -> tuple[dict, int, datetime | None]:
    """Ship #9 (rescoped) — prediction metadata enrichment resolver.

    Reads the classifier's inferred_timeframe_days / timeframe_source /
    timeframe_category / conviction_level fields and returns a kwargs
    dict suitable for splatting into Prediction(...) PLUS the
    potentially-overridden window_days + evaluation_date.

    Contract:
      - Called from EVERY insert_youtube_* function after the default
        window_days has been computed, BEFORE the Prediction()
        constructor.
      - Returns ({}, default_window_days, default_eval_date) when pred
        carries neither timeframe nor conviction data (flag off, or
        Haiku's response didn't include the new fields yet). The caller
        can unconditionally use the returned values — no conditional
        splat required.
      - When inferred_timeframe_days is present and valid (int, 0-2000
        days), overrides the window and returns a metadata dict with
        inferred_timeframe_days, timeframe_source (if valid), and
        timeframe_category.
      - Conviction_level is validated against the 5-value vocabulary.
        Invalid values silently drop so the insert never fails.
      - Stats counters incremented for timeframes_explicit /
        timeframes_inferred and the conviction_<level> buckets so
        admin diagnostics show the per-run distribution.

    NEVER raises — any internal failure degrades to a pass-through
    return of the defaults so the prediction insert is unaffected.
    """
    fallback_window = int(default_window_days) if default_window_days else DEFAULT_EVAL_WINDOW_DAYS
    fallback_eval = (
        publish_date + timedelta(days=fallback_window)
        if publish_date is not None else None
    )
    try:
        fields: dict = {}
        window_days = fallback_window
        eval_date = fallback_eval

        inferred = pred.get("inferred_timeframe_days")
        # Bug 6: round, not truncate. Haiku occasionally emits 6.9 for
        # "about a week" or 0.99 for "tomorrow", and `int()` was
        # collapsing those into 6 / 0 — the 0 then fell through every
        # tolerance lookup and got the year-long bucket.
        if isinstance(inferred, (int, float)) and 0 < int(round(float(inferred))) <= 2000:
            inferred_int = int(round(float(inferred)))
            fields["inferred_timeframe_days"] = inferred_int
            ts_src = pred.get("timeframe_source")
            if isinstance(ts_src, str) and ts_src in _VALID_TIMEFRAME_SOURCES:
                fields["timeframe_source"] = ts_src
                if stats is not None:
                    key = (
                        "timeframes_explicit" if ts_src == "explicit"
                        else "timeframes_inferred"
                    )
                    stats[key] = int(stats.get(key, 0)) + 1
            tf_cat = pred.get("timeframe_category")
            if isinstance(tf_cat, str) and tf_cat:
                fields["timeframe_category"] = tf_cat[:32]
            # Override window + eval date from the inferred value.
            window_days = inferred_int
            if publish_date is not None:
                eval_date = publish_date + timedelta(days=inferred_int)

        conviction = pred.get("conviction_level")
        if isinstance(conviction, str) and conviction in _VALID_CONVICTION_LEVELS:
            fields["conviction_level"] = conviction
            if stats is not None:
                key = f"conviction_{conviction}"
                stats[key] = int(stats.get(key, 0)) + 1

        # Ship #14 — long-horizon deferred-evaluation marker. The
        # validator stamps _evaluation_deferred=True on accepted preds
        # with explicit/inferred sources whose window is > 1825 days.
        # Pipe it through to the Prediction row so the evaluator skips
        # them and the frontend renders the deferred badge.
        if pred.get("_evaluation_deferred"):
            fields["evaluation_deferred"] = True
            fields["evaluation_deferred_reason"] = (
                pred.get("_evaluation_deferred_reason") or "long_horizon_thesis"
            )

        # Ship #15 — internal-only ticker-verification flag. TRUE if
        # the ticker symbol OR the ticker_sectors.company_name appears
        # (case-insensitive substring) in Haiku's emitted verbatim
        # quote; FALSE if neither does; leave NULL when the check is
        # not applicable (no ticker, no quote, or lookup failure).
        # Non-ticker prediction types (sector, macro, pair, regime)
        # naturally fall through to NULL because pred["ticker"] is not
        # populated for them. Disclosures write to a different table
        # and never reach this code path. Not serialized anywhere.
        ticker_raw = pred.get("ticker")
        quote_raw = pred.get("_verbatim_quote") or pred.get("verbatim_quote")
        if isinstance(ticker_raw, str) and ticker_raw.strip() \
                and isinstance(quote_raw, str) and quote_raw.strip():
            ticker_norm = ticker_raw.strip().upper().lstrip("$")
            quote_lower = quote_raw.lower()
            verified = ticker_norm.lower() in quote_lower
            if not verified and db is not None:
                try:
                    row = db.execute(
                        sql_text(
                            "SELECT company_name FROM ticker_sectors "
                            "WHERE ticker = :t LIMIT 1"
                        ),
                        {"t": ticker_norm},
                    ).first()
                    if row and isinstance(row[0], str) and row[0].strip():
                        if row[0].strip().lower() in quote_lower:
                            verified = True
                except Exception:
                    # Lookup failure is not fatal — leave verified as
                    # False (we confirmed the ticker symbol wasn't in
                    # the quote, which is already a meaningful signal).
                    pass
            fields["ticker_verified_in_transcript"] = bool(verified)

        return fields, window_days, eval_date
    except Exception as _e:
        log.info("[YT-CLF] _resolve_metadata_enrichment failed: %s", _e)
        return {}, fallback_window, fallback_eval


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
    transcript_data: dict | None = None,
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

    # Bug 4: best-effort sanity check against a live spot price. If we can
    # see what the stock costs right now and Haiku's target implies more
    # than the per-window cap (e.g. a 40x move in 90 days), drop the
    # target and let the prediction score direction-only. Failing the
    # spot lookup is fine — the historical evaluator runs the same check
    # later with the locked entry_price as the reference.
    if target_price is not None:
        try:
            from services.target_sanity import sanity_check_target
            from services.price_fetch import is_crypto, fetch_crypto_history
            spot_price = None
            if is_crypto(ticker):
                _hist = fetch_crypto_history(ticker)
                if _hist:
                    # newest date in the history
                    _latest = max((k for k in _hist.keys() if not k.startswith("_")), default=None)
                    if _latest:
                        spot_price = _hist[_latest]
            else:
                try:
                    from jobs.historical_evaluator import _try_finnhub
                    _q = _try_finnhub(ticker)
                    spot_price = _q.get("_current") if _q else None
                except Exception:
                    spot_price = None
            checked = sanity_check_target(spot_price, target_price, window_days)
            if spot_price is not None and checked is None:
                log.info(
                    "[YT-CLF] Bug-4 sanity reject: %s target=%s spot=%s window=%sd → direction-only",
                    ticker, target_price, spot_price, window_days,
                )
                target_price = None
        except Exception as _e:
            log.debug("[YT-CLF] sanity check skipped for %s: %s", ticker, _e)

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

    # Ship #9: resolve source timestamp from Haiku's verbatim quote.
    # No-ops silently when transcript_data is None (flag off or
    # non-monitor caller).
    _ts_fields = _resolve_source_timestamp(pred, transcript_data, stats)
    # Ship #9 rescoped: metadata enrichment — category-inferred
    # window + conviction level. Overrides window_days / eval_date
    # when Haiku emits inferred_timeframe_days; no-ops silently when
    # the flag is off or the pred dict doesn't carry the fields.
    _meta_fields, window_days, eval_date = _resolve_metadata_enrichment(
        pred, stats,
        publish_date=publish_date, default_window_days=window_days,
        db=db,
    )

    # Training completeness gate — drop predictions whose inline
    # extraction left required training fields NULL. No-op when
    # transcript_data is None (backfill / non-YouTube path) or when
    # the upstream feature flags are off.
    _gaps = _training_completeness_gaps(
        _ts_fields, _meta_fields, transcript_data, db=db, stats=stats,
        direction=direction,
    )
    if _gaps:
        return _reject("incomplete_training_fields", hr=",".join(_gaps))

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
            verified_by=_get_active_verified_by(),
            call_type="video_prediction",
            prediction_category="ticker_call",
            list_id=list_id_val,
            list_rank=list_rank_val,
            revision_of=revision_of_val,
            event_type=event_type_val,
            event_date=event_date_val,
            transcript_video_id=(video_id or "")[:11] or None,
            **_ts_fields,
            **_meta_fields,
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
    transcript_data: dict | None = None,
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

    _ts_fields = _resolve_source_timestamp(pred, transcript_data, stats)
    _meta_fields, window_days, eval_date = _resolve_metadata_enrichment(
        pred, stats,
        publish_date=publish_date, default_window_days=window_days,
        db=db,
    )

    # Training completeness gate — drop predictions whose inline
    # extraction left required training fields NULL. No-op when
    # transcript_data is None (backfill / non-YouTube path) or when
    # the upstream feature flags are off.
    _gaps = _training_completeness_gaps(
        _ts_fields, _meta_fields, transcript_data, db=db, stats=stats,
        direction=direction,
    )
    if _gaps:
        return _reject("incomplete_training_fields", hr=",".join(_gaps))

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
            verified_by=_get_active_verified_by(),
            call_type="sector_call",
            # Dual-column tagging: prediction_type drives the evaluator's
            # ETF-vs-SPY spread scorer; prediction_category drives the
            # leaderboard's separate-accuracy column.
            prediction_type="sector_call",
            prediction_category="sector_call",
            transcript_video_id=(video_id or "")[:11] or None,
            **_ts_fields,
            **_meta_fields,
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
    transcript_data: dict | None = None,
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

    _ts_fields = _resolve_source_timestamp(pred, transcript_data, stats)
    _meta_fields, window_days, eval_date = _resolve_metadata_enrichment(
        pred, stats,
        publish_date=publish_date, default_window_days=window_days,
        db=db,
    )

    # Training completeness gate — drop predictions whose inline
    # extraction left required training fields NULL. No-op when
    # transcript_data is None (backfill / non-YouTube path) or when
    # the upstream feature flags are off.
    _gaps = _training_completeness_gaps(
        _ts_fields, _meta_fields, transcript_data, db=db, stats=stats,
        direction=direction,
    )
    if _gaps:
        return _reject("incomplete_training_fields", hr=",".join(_gaps))

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
            verified_by=_get_active_verified_by(),
            call_type="macro_call",
            prediction_category="macro_call",
            macro_concept=concept,
            transcript_video_id=(video_id or "")[:11] or None,
            **_ts_fields,
            **_meta_fields,
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
    transcript_data: dict | None = None,
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

    _ts_fields = _resolve_source_timestamp(pred, transcript_data, stats)
    _meta_fields, window_days, eval_date = _resolve_metadata_enrichment(
        pred, stats,
        publish_date=publish_date, default_window_days=window_days,
        db=db,
    )

    # Training completeness gate — drop predictions whose inline
    # extraction left required training fields NULL. No-op when
    # transcript_data is None (backfill / non-YouTube path) or when
    # the upstream feature flags are off.
    _gaps = _training_completeness_gaps(
        _ts_fields, _meta_fields, transcript_data, db=db, stats=stats,
        direction="bullish",
    )
    if _gaps:
        return _reject("incomplete_training_fields", hr=",".join(_gaps))

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
            verified_by=_get_active_verified_by(),
            call_type="pair_call",
            prediction_category="pair_call",
            pair_long_ticker=long_ticker,
            pair_short_ticker=short_ticker,
            transcript_video_id=(video_id or "")[:11] or None,
            **_ts_fields,
            **_meta_fields,
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
    transcript_data: dict | None = None,
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

    _ts_fields = _resolve_source_timestamp(pred, transcript_data, stats)
    # Binary events: window_days is driven by the event deadline, not by
    # Haiku's inferred_timeframe_days. Use tuple throwaway so the helper
    # still populates conviction + inferred_timeframe_days + timeframe_*
    # columns as label data, but leaves the deadline-derived window
    # untouched.
    _meta_fields, _, _ = _resolve_metadata_enrichment(
        pred, stats,
        publish_date=publish_date, default_window_days=window_days,
        db=db,
    )

    # Training completeness gate — drop predictions whose inline
    # extraction left required training fields NULL. No-op when
    # transcript_data is None (backfill / non-YouTube path) or when
    # the upstream feature flags are off.
    _gaps = _training_completeness_gaps(
        _ts_fields, _meta_fields, transcript_data, db=db, stats=stats,
        direction="bullish",
    )
    if _gaps:
        return _reject("incomplete_training_fields", hr=",".join(_gaps))

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
            verified_by=_get_active_verified_by(),
            call_type="binary_event_call",
            prediction_category="binary_event_call",
            event_type=event_type,
            expected_outcome_text=outcome_text[:2000],
            event_deadline=deadline,
            # event_resolved_at + event_resolution_source stay NULL
            # until the evaluator confirms the outcome (stubbed — see
            # _score_binary_event for the follow-up-ship TODO).
            transcript_video_id=(video_id or "")[:11] or None,
            **_ts_fields,
            **_meta_fields,
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
    transcript_data: dict | None = None,
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

    _ts_fields = _resolve_source_timestamp(pred, transcript_data, stats)
    # Metric forecasts: window_days is driven by the release date, not
    # by Haiku's inferred_timeframe_days. Throw away the helper's
    # window override but keep the metadata columns.
    _meta_fields, _, _ = _resolve_metadata_enrichment(
        pred, stats,
        publish_date=publish_date, default_window_days=window_days,
        db=db,
    )

    # Training completeness gate — drop predictions whose inline
    # extraction left required training fields NULL. No-op when
    # transcript_data is None (backfill / non-YouTube path) or when
    # the upstream feature flags are off.
    _gaps = _training_completeness_gaps(
        _ts_fields, _meta_fields, transcript_data, db=db, stats=stats,
        direction=direction,
    )
    if _gaps:
        return _reject("incomplete_training_fields", hr=",".join(_gaps))

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
            verified_by=_get_active_verified_by(),
            call_type="metric_forecast_call",
            prediction_category="metric_forecast_call",
            metric_type=metric_type,
            metric_target=target_num,
            metric_period=period,
            metric_release_date=release,
            # metric_actual + metric_error_pct stay NULL until the
            # evaluator fetches the real value.
            transcript_video_id=(video_id or "")[:11] or None,
            **_ts_fields,
            **_meta_fields,
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
    transcript_data: dict | None = None,
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

    _ts_fields = _resolve_source_timestamp(pred, transcript_data, stats)
    # Conditional calls: the outcome window is overridable by Haiku's
    # inferred_timeframe_days — it's the Phase 2 scoring window after
    # trigger fire, same semantics as ticker_call.
    _meta_fields, window_days, eval_date = _resolve_metadata_enrichment(
        pred, stats,
        publish_date=publish_date, default_window_days=window_days,
        db=db,
    )
    outcome_window_days = int(window_days) if window_days else outcome_window_days

    # Training completeness gate — drop predictions whose inline
    # extraction left required training fields NULL. No-op when
    # transcript_data is None (backfill / non-YouTube path) or when
    # the upstream feature flags are off.
    _gaps = _training_completeness_gaps(
        _ts_fields, _meta_fields, transcript_data, db=db, stats=stats,
        direction=direction,
    )
    if _gaps:
        return _reject("incomplete_training_fields", hr=",".join(_gaps))

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
            verified_by=_get_active_verified_by(),
            call_type="conditional_call",
            prediction_category="conditional_call",
            trigger_condition=trig_cond[:500],
            trigger_type=trig_type,
            trigger_ticker=trig_ticker,
            trigger_price=trig_price,
            trigger_deadline=trig_deadline_dt,
            trigger_fired_at=None,
            outcome_window_days=outcome_window_days,
            transcript_video_id=(video_id or "")[:11] or None,
            **_ts_fields,
            **_meta_fields,
        )
    )
    db.flush()
    if stats is not None:
        stats["conditional_calls_extracted"] = int(
            stats.get("conditional_calls_extracted", 0)
        ) + 1
    return True


# ── Disclosure insertion (ship #8) ─────────────────────────────────────────
#
# Unlike every other ship in the series, disclosures do NOT land in
# the predictions table. They live in their own `disclosures` table
# with their own scoring concept (follow-through). The insert path
# here is a clean split from insert_youtube_prediction so the type
# separation is enforced at the boundary — if you're editing this
# function and find yourself reaching for a predictions-table field,
# stop and reconsider.


def insert_youtube_disclosure(
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
    transcript_data: dict | None = None,
) -> bool:
    """Insert a disclosure row.

    Writes to the `disclosures` table with the 7-value action enum
    plus size (shares / pct / qualitative), entry_price, reasoning,
    and disclosed_at. follow_through_* stays NULL until the daily
    compute_disclosure_follow_through job fills it in.

    Rejection paths (each logs to youtube_scraper_rejections and
    returns False):
      - missing or unknown action → 'disclosure_invalid_action'
      - missing ticker → 'disclosure_missing_ticker'
      - ticker not in ticker_sectors → 'invalid_ticker'
      - dedup collision on source_platform_id → 'dedup_collision'
      - forecaster create failure → 'forecaster_creation_failed'
    """
    from models import Disclosure

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
    ticker = re.sub(r"[^A-Z0-9]", "", ticker)
    action = (
        pred.get("_disclosure_action")
        or pred.get("action")
        or ""
    ).strip().lower()

    if not ticker or len(ticker) > 5:
        return _reject("disclosure_missing_ticker", hr=ticker or None)
    if action not in ("buy", "sell", "add", "trim", "starter", "exit", "hold"):
        return _reject("disclosure_invalid_action", hr=action or None)

    # disclosed_at: prefer the validator-stamped date, fall back to
    # parsing the raw field, final fallback to the video publish date.
    disclosed_date = pred.get("_disclosed_at_date")
    if not disclosed_date:
        raw_date = pred.get("disclosed_at")
        if raw_date:
            try:
                from datetime import datetime as _dt
                disclosed_date = _dt.strptime(
                    str(raw_date)[:10], "%Y-%m-%d"
                ).date()
            except (TypeError, ValueError):
                disclosed_date = None
    if not disclosed_date:
        disclosed_date = publish_date.date() if publish_date else None
    if not disclosed_date:
        return _reject("disclosure_invalid_action", hr="no date")

    from datetime import datetime as _dt
    disclosed_at_dt = _dt.combine(disclosed_date, _dt.min.time())

    # Dedup key: one row per (video, ticker, action, date). Two
    # different days' disclosures on the same ticker+action survive
    # because the date is in the key; the same disclosure mentioned
    # twice in a single video collapses.
    source_id = f"yt_{video_id}_{ticker}_{action}_{disclosed_date.isoformat()}"
    if db.execute(
        sql_text("SELECT 1 FROM disclosures WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=f"{ticker}/{action}/{disclosed_date}")

    if not validate_ticker_in_db(ticker, db):
        return _reject("invalid_ticker", hr=ticker)

    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    # Coerce size fields defensively — Haiku sometimes returns
    # strings like "500" or "5%" for numeric slots.
    def _to_num(v):
        if v is None:
            return None
        try:
            return float(str(v).replace("%", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    size_shares = _to_num(pred.get("_size_shares") or pred.get("size_shares"))
    size_pct = _to_num(pred.get("_size_pct") or pred.get("size_pct"))
    # Interpret a size_pct > 1 as a percent-not-decimal ("5" → 0.05)
    if size_pct is not None and size_pct > 1:
        size_pct = size_pct / 100.0
    size_qualitative = pred.get("_size_qualitative") or (
        pred.get("size_qualitative") or None
    )
    if isinstance(size_qualitative, str):
        size_qualitative = size_qualitative.strip().lower() or None
    if size_qualitative not in (None, "small", "medium", "large", "full"):
        size_qualitative = None
    entry_price = _to_num(pred.get("_entry_price") or pred.get("entry_price"))
    reasoning = (pred.get("_reasoning_text") or pred.get("reasoning_text") or "")
    reasoning = reasoning.strip()[:2000] if reasoning else None

    _ts_fields = _resolve_source_timestamp(pred, transcript_data, stats)

    db.add(
        Disclosure(
            forecaster_id=forecaster.id,
            ticker=ticker,
            action=action,
            size_shares=size_shares,
            size_pct=size_pct,
            size_qualitative=size_qualitative,
            entry_price=entry_price,
            reasoning_text=reasoning,
            disclosed_at=disclosed_at_dt,
            source_video_id=video_id,
            source_platform_id=source_id,
            transcript_video_id=(video_id or "")[:11] or None,
            **_ts_fields,
        )
    )
    # Bump the cached counter on the forecaster row. Average
    # follow-through stays NULL until the daily job computes it —
    # we intentionally don't touch it here.
    db.execute(
        sql_text(
            "UPDATE forecasters SET disclosure_count = disclosure_count + 1 "
            "WHERE id = :fid"
        ),
        {"fid": int(forecaster.id)},
    )
    db.flush()
    if stats is not None:
        stats["disclosures_extracted"] = int(
            stats.get("disclosures_extracted", 0)
        ) + 1
    return True


# ── Regime call insertion (ship #12) ───────────────────────────────────────
#
# regime_call rows land in the predictions table with
# prediction_category='regime_call' and the regime_type / regime_instrument
# columns populated. Unlike every prior type they have NO price target —
# the claim is structural, not magnitude-based. Scoring is computed by
# the evaluator's drawdown/runup/new-high rule set, not by comparing a
# final price to a target. direction is derived from regime_type so the
# existing (ticker, direction) indexes still cover these rows without
# special cases in query code.


REGIME_TYPES_ALLOWED = (
    "bull_continuing",
    "bull_starting",
    "topping",
    "bear_starting",
    "bear_continuing",
    "bottoming",
    "correction",
    "consolidation",
)

REGIME_DEFAULT_WINDOW_DAYS = 180  # 6 months — regime claims are longer-horizon


def _regime_call_exists_cross_scraper(
    regime_type: str, regime_instrument: str,
    forecaster_id: int, prediction_date, db,
) -> bool:
    """Cross-scraper dedup for regime calls. Key is
    (regime_type, regime_instrument, forecaster, date) within a 24h
    window. Two distinct regime_types on the same instrument from the
    same forecaster on the same day are both legitimate — e.g. a
    forecaster could say "SPY is consolidating AND small caps are
    starting a new bull". The dedup only collapses literal repeats."""
    if not (regime_type and regime_instrument and forecaster_id and prediction_date):
        return False
    try:
        from datetime import timedelta
        date_start = prediction_date - timedelta(hours=24)
        date_end = prediction_date + timedelta(hours=24)
        row = db.execute(sql_text("""
            SELECT 1 FROM predictions
            WHERE prediction_category = 'regime_call'
              AND regime_type = :rt
              AND regime_instrument = :ri
              AND forecaster_id = :fid
              AND prediction_date BETWEEN :ds AND :de
            LIMIT 1
        """), {
            "rt": regime_type,
            "ri": regime_instrument,
            "fid": int(forecaster_id),
            "ds": date_start,
            "de": date_end,
        }).first()
    except Exception as _e:
        log.warning("[YT-CLF] regime_call cross-scraper dedup failed: %s", _e)
        return False
    return row is not None


def insert_youtube_regime_prediction(
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
    """Insert a regime_call prediction.

    Stores the row with prediction_category='regime_call' and the
    two required regime_* metadata columns. direction is derived from
    regime_type (bull_* and bottoming = bullish, bear_* and topping =
    bearish, correction and consolidation = neutral). target_price
    stays NULL. Evaluation date defaults to publish_date + 6 months
    when the speaker doesn't give an explicit window.

    Rejection paths (each logs to youtube_scraper_rejections):
      - regime_type not in allowlist → 'regime_invalid_type'
      - regime_instrument invalid / too long → 'regime_invalid_instrument'
      - per-video dedup hit → 'dedup_collision'
      - cross-scraper dupe → 'cross_scraper_dupe'
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

    regime_type = (
        pred.get("_regime_type") or pred.get("regime_type") or ""
    ).strip().lower()
    if regime_type not in REGIME_TYPES_ALLOWED:
        return _reject("regime_invalid_type", hr=regime_type or None)

    instrument = (
        pred.get("_regime_instrument") or pred.get("regime_instrument") or "SPY"
    ).upper().strip().lstrip("$")
    instrument = re.sub(r"[^A-Z0-9]", "", instrument)
    if not instrument or len(instrument) > 5:
        return _reject("regime_invalid_instrument", hr=instrument or None)

    # Derive direction from regime_type (validator already stamped it
    # but we re-derive defensively so calling insert() with a raw
    # classifier output also works).
    if regime_type in ("bull_continuing", "bull_starting", "bottoming"):
        direction = "bullish"
    elif regime_type in ("bear_continuing", "bear_starting", "topping"):
        direction = "bearish"
    else:
        direction = "neutral"

    # Per-video dedup via canonical source_platform_id.
    source_id = f"yt_{video_id}_regime_{regime_type}_{instrument}"
    if db.execute(
        sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
        {"sid": source_id},
    ).first():
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("dedup_collision", hr=f"{regime_type}/{instrument}")

    # Validate the instrument against ticker_sectors. SPY/QQQ/IWM/BTC
    # are all in the sector table so this is a cheap sanity check.
    if not validate_ticker_in_db(instrument, db):
        return _reject("regime_invalid_instrument", hr=instrument)

    forecaster = find_or_create_youtube_forecaster(channel_name, channel_id, db)
    if not forecaster:
        return _reject("forecaster_creation_failed")

    if _regime_call_exists_cross_scraper(
        regime_type, instrument, forecaster.id, publish_date, db,
    ):
        if stats is not None:
            stats["items_deduped"] = int(stats.get("items_deduped", 0)) + 1
        return _reject("cross_scraper_dupe", hr=f"{regime_type}/{instrument}")

    # Evaluation window: prefer Haiku's timeframe if given, otherwise
    # default to publish_date + 6 months. Regime claims are longer-
    # horizon than ticker_call so 180 days is the right floor.
    eval_date, window_days = _parse_evaluation_date(
        pred.get("timeframe"), publish_date,
    )
    if not window_days or window_days < 60:
        from datetime import timedelta
        eval_date = publish_date + timedelta(days=REGIME_DEFAULT_WINDOW_DAYS)
        window_days = REGIME_DEFAULT_WINDOW_DAYS

    quote = (pred.get("context_quote") or pred.get("quote") or "").strip()
    _label = regime_type.replace("_", " ").title()
    parts = [f"{channel_name}: {_label} on {instrument}"]
    if quote:
        parts.append(f'"{quote[:140]}"')
    context_str = ". ".join(parts)[:500]

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    # Sector lookup (best-effort) — SPY/QQQ/IWM normally resolve to
    # "ETF" or a broad classification, which is fine for display.
    sector = None
    try:
        from jobs.sector_lookup import get_sector
        sector = get_sector(instrument, db)
    except Exception:
        sector = None

    # Ship #9 (rescoped): metadata enrichment for regime_call.
    # Regime uses its own default window (6 months) driven by the
    # evaluator's drawdown/runup math, so we throw away the helper's
    # window override but still populate conviction + timeframe
    # label columns.
    _meta_fields, _, _ = _resolve_metadata_enrichment(
        pred, stats,
        publish_date=publish_date, default_window_days=window_days,
        db=db,
    )

    # NOTE: regime predictions intentionally skip the training
    # completeness gate — they don't go through inline source-timestamp
    # extraction (no transcript_data plumbed into this signature) and
    # have no verbatim_quote in their schema. Extending timestamps to
    # regime is a separate ship that needs prompt verification.

    db.add(
        Prediction(
            forecaster_id=forecaster.id,
            ticker=instrument,
            direction=direction,
            prediction_date=publish_date,
            evaluation_date=eval_date,
            window_days=window_days,
            target_price=None,  # regime_call has no explicit target
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
            verified_by=_get_active_verified_by(),
            call_type="regime_call",
            prediction_category="regime_call",
            regime_type=regime_type,
            regime_instrument=instrument,
            # regime_max_drawdown / regime_max_runup / regime_new_highs
            # / regime_new_lows stay NULL until the evaluator scores.
            **_meta_fields,
        )
    )
    db.flush()
    if stats is not None:
        stats["regime_calls_extracted"] = int(
            stats.get("regime_calls_extracted", 0)
        ) + 1
    return True
