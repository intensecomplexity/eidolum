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
                   transcript: str) -> tuple[list[dict], dict]:
    """Send a (possibly chunked) transcript to Haiku and return parsed predictions.

    Returns (predictions, telemetry):
      predictions — list of validated prediction dicts (may be empty)
      telemetry   — dict with token usage, chunk count, last_status, and
                    optionally an error tag for non-fatal classifier failures

    NEVER raises. On any classifier failure (no key, HTTP error, parse
    error) returns ([], {"error": "<tag>"}). The caller should treat
    empty predictions + an error tag as a transient skip.
    """
    telemetry: dict = {"chunks": 0, "input_tokens": 0, "output_tokens": 0,
                       "last_status": None, "predictions_raw": 0}
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

    all_preds: list[dict] = []
    for i, chunk in enumerate(chunks):
        telemetry["chunks"] += 1
        try:
            resp = client.messages.create(
                model=HAIKU_MODEL,
                # 800-token cap balances cost (~5x smaller output budget
                # than the old 2000) against head-room for high-yield
                # videos that legitimately return 10+ predictions. Even
                # at 15 predictions per video (MAX_PREDICTIONS_PER_VIDEO),
                # each prediction object serializes to ~50 output tokens,
                # so 800 leaves buffer for long "reasoning" strings.
                max_tokens=800,
                temperature=0,
                system=[
                    {
                        "type": "text",
                        "text": HAIKU_SYSTEM,
                        # Ephemeral cache: subsequent chunks within the
                        # same run hit the cache, dropping per-call input
                        # cost on the ~3,300-token system prompt.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": _build_user_prompt(channel_name, title, publish_date, chunk),
                    }
                ],
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

        usage = getattr(resp, "usage", None)
        if usage:
            telemetry["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
            telemetry["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
            if cache_read or cache_create:
                telemetry.setdefault("cache_read", 0)
                telemetry.setdefault("cache_create", 0)
                telemetry["cache_read"] += cache_read
                telemetry["cache_create"] += cache_create

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


def _validate_and_dedupe_predictions(raw: list) -> list[dict]:
    """Filter to predictions that look structurally sound and dedupe by
    (ticker, direction). The classifier occasionally returns the same
    prediction twice when a transcript repeats a take, and chunked
    transcripts will overlap by 2k chars so the same sentence may be
    classified twice."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for p in raw:
        if not isinstance(p, dict):
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
        key = (ticker, direction)
        if key in seen:
            continue
        seen.add(key)
        p["ticker"] = ticker
        p["direction"] = direction
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
        )
    )
    db.flush()
    return True
