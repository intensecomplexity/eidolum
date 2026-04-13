"""
YouTube Channel Monitor for Eidolum — V2 (Transcript-based, INSERTS PREDICTIONS)

What changed from V1:
  - V1 ran Sonnet on the title + first 1000 chars of the description
    only. It logged what it would create but never inserted. The signal
    in titles alone was very thin.
  - V2 fetches the auto-generated TRANSCRIPT for every new video and
    classifies the full body of the speech via Haiku. Real predictions
    live in the spoken text, not the title. V2 inserts predictions
    directly into the predictions table via insert_youtube_prediction
    in jobs.youtube_classifier (which mirrors the massive_benzinga
    insertion pattern: source_platform_id dedup, cross-scraper dedup,
    sector resolution).

What still works the same:
  - Same 45-channel TARGET_CHANNELS seed list
  - Same youtube_channels and youtube_videos bookkeeping tables
  - Same rotation: 10 channels per 12h run, oldest-first
  - Same YouTube Data API quota budget: 1 search call per channel +
    one channel-id resolution per first-time channel

Schedule: every 12 hours via worker.py. The historical backfill job
(backend/jobs/youtube_backfill.py) is registered separately and runs
every 4h to chew through each channel's full upload history.

Why Haiku and not Groq: see the docstring in youtube_classifier.py.
The TL;DR is that this pipeline runs 12h cadence on long transcripts,
not 6h cadence on tweets — Groq's free-tier TPM ceiling would be more
constraining here than Haiku's billing risk.
"""
import os
import time
import json
import httpx
from datetime import datetime, timedelta

from sqlalchemy import text as sql_text

from jobs.youtube_classifier import (
    fetch_transcript,
    fetch_transcript_with_timestamps,
    classify_video,
    insert_youtube_prediction,
    insert_youtube_sector_prediction,
    insert_youtube_macro_prediction,
    insert_youtube_pair_prediction,
    insert_youtube_binary_event_prediction,
    insert_youtube_metric_forecast_prediction,
    insert_youtube_conditional_prediction,
    insert_youtube_disclosure,
    insert_youtube_regime_prediction,
    log_youtube_rejection,
    transcript_proxy_status,
    PIPELINE_VERSION,
    HAIKU_MODEL,
)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

CHANNELS_PER_RUN = 999  # Process all active channels each cycle (was 10)
MAX_VIDEOS_PER_CHANNEL = int(os.getenv("YOUTUBE_MAX_VIDEOS_PER_CHANNEL", "50"))
DAILY_QUOTA_LIMIT = 10_000  # YouTube Data API v3 free tier

# Videos shorter than this are skipped before the transcript fetch.
# YouTube Shorts are definitionally ≤60s; the 180s floor also catches
# short news clips / teasers that almost never contain real predictions
# and burn Webshare bandwidth + Haiku tokens for no yield. Duration is
# pulled from a single videos.list batch call per channel (~1 quota unit).
YOUTUBE_MIN_DURATION_SECONDS = 180  # 3 minutes

TARGET_CHANNELS = [
    # TIER 1: Value/Fundamental Analysis
    "Joseph Carlson", "The Plain Bagel", "Aswath Damodaran", "Sven Carlin",
    "Patrick Boyle", "Ben Felix", "The Money Guy Show", "New Money",
    "Everything Money", "The Swedish Investor", "Unrivaled Investing",
    "Hamish Hodder", "Marko WhiteBoard Finance", "Parkev Tatevosian CFA",
    "Chris Invests", "Damien Talks Money", "Chip Stock Investor",
    "The Investor Channel", "Morningstar", "Rob Berger",
    # TIER 2: Stock Pick / Equity Analysis
    "Financial Education", "Learn to Invest", "Investors Grow",
    "The Popular Investor", "Dividend Data", "Dividendology",
    "PPCIAN", "Stock Compounder", "Meet Kevin", "Graham Stephan",
    "Andrei Jikh", "Minority Mindset", "Tom Nash", "Nanalyze",
    "Fast Graphs", "PensionCraft", "The Long-Term Investor",
    "DIY Investing", "The Financial Tortoise", "Stock Moe",
    "The Quality Investor", "Ales World of Stocks",
    "The Patient Investor", "Rational Investing with Cameron Stewart",
    "The Compounding Investor",
]


def _ensure_tables(db):
    """Create / migrate the YouTube tracking tables.

    youtube_channels — one row per channel, plus state for the backfill
                       job (backfill_cursor JSON, is_active flag,
                       subscriber_count, last_crawled).
    youtube_videos   — dedup tracker. pipeline_version distinguishes
                       videos processed by the V1 (title-only) flow
                       from V2 (transcript-based) so V1 rows can be
                       re-processed once after the migration.
    """
    try:
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS youtube_channels (
                id SERIAL PRIMARY KEY,
                channel_name TEXT NOT NULL,
                youtube_channel_id TEXT,
                last_crawled TIMESTAMP,
                backfill_cursor TEXT,
                total_videos_processed INTEGER DEFAULT 0,
                total_predictions_extracted INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS youtube_videos (
                id SERIAL PRIMARY KEY,
                youtube_video_id TEXT UNIQUE NOT NULL,
                channel_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                publish_date TIMESTAMP,
                predictions_extracted INTEGER DEFAULT 0,
                processed_at TIMESTAMP DEFAULT NOW()
            )
        """))
        # Idempotent column adds for V2 (safe to re-run)
        for ddl in (
            "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS subscriber_count INTEGER",
            "ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS catalog_complete BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS pipeline_version TEXT",
            "ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS transcript_status TEXT",
            "ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS transcript_chars INTEGER",
        ):
            try:
                db.execute(sql_text(ddl))
            except Exception as e:
                print(f"[ChannelMonitor] migration step skipped: {e}")
        db.commit()
    except Exception:
        db.rollback()


def _resolve_channel_id(channel_name: str) -> str | None:
    """Look up YouTube channel ID by name. Costs 100 API units."""
    if not YOUTUBE_API_KEY:
        print(f"[ChannelMonitor] resolve skipped for {channel_name!r}: "
              f"no YOUTUBE_API_KEY")
        return None
    try:
        r = httpx.get(f"{YOUTUBE_API}/search", params={
            "part": "snippet", "q": channel_name, "type": "channel",
            "maxResults": 1, "key": YOUTUBE_API_KEY,
        }, timeout=10)
        if r.status_code != 200:
            print(f"[ChannelMonitor] resolve failed for {channel_name!r}: "
                  f"HTTP {r.status_code} {r.text[:200]}")
            return None
        items = r.json().get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
        print(f"[ChannelMonitor] resolve returned 0 results for "
              f"{channel_name!r}")
    except Exception as e:
        print(f"[ChannelMonitor] resolve error for {channel_name!r}: {e}")
    return None


def _get_recent_videos(channel_id: str, since: str) -> list:
    """Get recent videos from a channel via search.list. Costs 100 API units.

    The search endpoint returns up to 10 videos per call ordered by date.
    Anything older than `since` is filtered out server-side via
    publishedAfter, so we're not wasting quota on already-processed videos.
    """
    if not YOUTUBE_API_KEY:
        return []
    try:
        r = httpx.get(f"{YOUTUBE_API}/search", params={
            "part": "snippet", "channelId": channel_id, "type": "video",
            "order": "date", "maxResults": 10, "publishedAfter": since,
            "key": YOUTUBE_API_KEY,
        }, timeout=10)
        if r.status_code == 403:
            print("[ChannelMonitor] YouTube API quota exceeded")
            return []
        if r.status_code != 200:
            print(f"[ChannelMonitor] search.list HTTP {r.status_code}: {r.text[:200]}")
            return []
        return r.json().get("items", [])
    except Exception as e:
        print(f"[ChannelMonitor] search.list error: {e}")
        return []


def _is_likely_short(title: str, video_id: str) -> bool:
    """Best-effort filter for YouTube Shorts before we burn a transcript
    fetch on them. Shorts are <60s and rarely contain real predictions.
    The search endpoint doesn't return duration, so we use title hints.
    """
    if not title:
        return False
    t = title.lower()
    return "#shorts" in t or "shorts" in t and len(title) < 30


def _parse_iso_duration(s: str) -> int:
    """Parse an ISO 8601 duration like PT2M30S / PT1H5M / PT45S into
    seconds. Returns 0 on any parse failure. YouTube videos.list
    contentDetails.duration is always in this format."""
    if not s or not isinstance(s, str) or not s.startswith("PT"):
        return 0
    import re as _re
    m = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return 0
    h, mn, sc = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mn * 60 + sc


def _fetch_video_durations(video_ids: list[str]) -> dict[str, int]:
    """Batch videos.list call to pull duration_seconds per video. Returns
    an empty dict on any failure (callers treat 0/missing as "unknown"
    and fall through to the title heuristic). Costs 1 YouTube Data API
    quota unit per batch of up to 50 IDs — a ~1% increase over the
    existing per-channel search.list spend.
    """
    if not video_ids or not YOUTUBE_API_KEY:
        return {}
    out: dict[str, int] = {}
    try:
        r = httpx.get(f"{YOUTUBE_API}/videos", params={
            "part": "contentDetails",
            "id": ",".join(video_ids[:50]),
            "key": YOUTUBE_API_KEY,
        }, timeout=10)
        if r.status_code != 200:
            print(f"[ChannelMonitor] videos.list HTTP {r.status_code}: {r.text[:200]}")
            return {}
        for it in r.json().get("items", []):
            vid = it.get("id")
            dur = (it.get("contentDetails") or {}).get("duration") or ""
            out[vid] = _parse_iso_duration(dur)
    except Exception as e:
        print(f"[ChannelMonitor] videos.list error: {e}")
    return out


def _get_catalog_videos(
    channel_id: str, channel_name: str, db,
) -> tuple[list[dict], int, bool]:
    """Fetch unseen videos from a channel's full uploads playlist.

    Uses playlistItems.list (1 unit per page of 50 items) instead of
    search.list (100 units per page of 10). Paginates through the
    playlist until either MAX_VIDEOS_PER_CHANNEL unseen videos are
    collected or the playlist is exhausted.

    Returns (unseen_videos, api_units_used, catalog_exhausted).
    catalog_exhausted is True when we reached the end of the playlist
    and found fewer unseen videos than MAX_VIDEOS_PER_CHANNEL — meaning
    every video in the channel has been processed.
    """
    if not YOUTUBE_API_KEY:
        return [], 0, False

    # Derive uploads playlist ID from channel ID (UC... → UU...)
    uploads_playlist = "UU" + channel_id[2:]

    # Pre-load already-processed video IDs for this channel
    processed = {
        r[0]
        for r in db.execute(
            sql_text(
                "SELECT youtube_video_id FROM youtube_videos "
                "WHERE channel_name = :name"
            ),
            {"name": channel_name},
        ).fetchall()
    }

    unseen: list[dict] = []
    page_token: str | None = None
    api_units = 0
    playlist_exhausted = False

    while len(unseen) < MAX_VIDEOS_PER_CHANNEL:
        params: dict = {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": 50,
            "key": YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            r = httpx.get(
                f"{YOUTUBE_API}/playlistItems", params=params, timeout=15,
            )
        except Exception as e:
            print(f"[ChannelMonitor] playlistItems error for "
                  f"{channel_name}: {e}")
            break

        api_units += 1  # playlistItems.list costs 1 unit

        if r.status_code == 403:
            print(f"[ChannelMonitor] YouTube API quota exceeded during "
                  f"catalog fetch for {channel_name}")
            break
        if r.status_code == 404:
            print(f"[ChannelMonitor] uploads playlist not found for "
                  f"{channel_name} ({uploads_playlist})")
            break
        if r.status_code != 200:
            print(f"[ChannelMonitor] playlistItems HTTP {r.status_code} "
                  f"for {channel_name}: {r.text[:200]}")
            break

        data = r.json()
        items = data.get("items", [])

        for item in items:
            video_id = (item.get("contentDetails") or {}).get("videoId")
            if not video_id:
                continue
            if video_id in processed:
                continue
            snippet = item.get("snippet", {})
            unseen.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": (
                    (item.get("contentDetails") or {}).get("videoPublishedAt")
                    or snippet.get("publishedAt", "")
                ),
            })
            if len(unseen) >= MAX_VIDEOS_PER_CHANNEL:
                break

        page_token = data.get("nextPageToken")
        if not page_token:
            playlist_exhausted = True
            break

    catalog_complete = playlist_exhausted and len(unseen) < MAX_VIDEOS_PER_CHANNEL
    return unseen, api_units, catalog_complete


_DISCOVERY_QUERIES = [
    "stock market analysis", "stock picks 2026", "investment portfolio",
    "dividend investing", "growth stocks analysis", "value investing stocks",
]


def _discover_new_channels(db, max_new: int = 5) -> int:
    """Auto-discover finance channels when all active channels are
    catalog_complete. Searches YouTube for finance-themed channels,
    filters by subscriber count and activity, seeds the best matches.

    Returns the number of newly seeded channels.
    """
    if not YOUTUBE_API_KEY:
        return 0

    existing_ids = {
        r[0] for r in db.execute(sql_text(
            "SELECT youtube_channel_id FROM youtube_channels "
            "WHERE youtube_channel_id IS NOT NULL"
        )).fetchall()
    }

    candidates: list[tuple[str, str, int]] = []  # (channel_id, name, subs)
    for query in _DISCOVERY_QUERIES:
        if len(candidates) >= max_new * 3:
            break
        try:
            r = httpx.get(f"{YOUTUBE_API}/search", params={
                "part": "snippet", "q": query, "type": "channel",
                "maxResults": 10, "key": YOUTUBE_API_KEY,
                "relevanceLanguage": "en",
            }, timeout=10)
            if r.status_code != 200:
                continue
            for item in r.json().get("items", []):
                cid = item.get("snippet", {}).get("channelId")
                cname = item.get("snippet", {}).get("title", "")
                if cid and cid not in existing_ids:
                    candidates.append((cid, cname, 0))
                    existing_ids.add(cid)
        except Exception:
            continue

    # Fetch stats for candidates to filter by subs + video count
    seeded = 0
    for cid, cname, _ in candidates[:max_new * 2]:
        if seeded >= max_new:
            break
        try:
            r = httpx.get(f"{YOUTUBE_API}/channels", params={
                "part": "statistics,contentDetails", "id": cid,
                "key": YOUTUBE_API_KEY,
            }, timeout=10)
            if r.status_code != 200:
                continue
            items = r.json().get("items", [])
            if not items:
                continue
            stats_data = items[0].get("statistics", {})
            subs = int(stats_data.get("subscriberCount", 0))
            vids = int(stats_data.get("videoCount", 0))
            if subs < 10_000 or vids < 50:
                continue
        except Exception:
            continue

        try:
            db.execute(sql_text(
                "INSERT INTO youtube_channels "
                "(channel_name, youtube_channel_id, is_active, catalog_complete) "
                "VALUES (:name, :cid, TRUE, FALSE) "
                "ON CONFLICT DO NOTHING"
            ), {"name": cname, "cid": cid})
            db.commit()
            seeded += 1
            print(f"[ChannelMonitor] DISCOVERED: {cname} ({cid}) "
                  f"subs={subs} videos={vids}", flush=True)
        except Exception:
            db.rollback()

    if seeded:
        print(f"[ChannelMonitor] DISCOVERED {seeded} new channels", flush=True)
    return seeded


def run_channel_monitor(db=None):
    """Main entry point. Runs every 12h via worker.py."""
    if not YOUTUBE_API_KEY:
        print("[ChannelMonitor] YOUTUBE_API_KEY not set — skipping")
        return
    if not ANTHROPIC_API_KEY:
        print("[ChannelMonitor] ANTHROPIC_API_KEY not set — skipping")
        return

    # Surface every transcript-proxy-related env var the classifier checks,
    # presence-only and length-only (never the value). If the proxy banner
    # below says proxy=none even though Webshare is "set" in Railway, the
    # log lines here will tell you whether the env var name is misspelled
    # vs. genuinely missing — that exact diagnosis is what shipped this
    # debug block in the first place (the deployed worker turned out to
    # have EBSHARE_PROXY_USERNAME, missing the leading W, and my code's
    # os.getenv('WEBSHARE_PROXY_USERNAME') quietly returned empty).
    _proxy_env_keys = [
        "WEBSHARE_PROXY_USERNAME",
        "WEBSHARE_PROXY_PASSWORD",
        "YT_PROXY_HTTP",
        "YT_PROXY_HTTPS",
    ]
    for k in _proxy_env_keys:
        v = os.getenv(k, "")
        print(
            f"[ChannelMonitor] env {k}: present={bool(v)} length={len(v)}",
            flush=True,
        )

    print(
        f"[ChannelMonitor] V2 (transcript-based) starting | classifier={HAIKU_MODEL} "
        f"pipeline={PIPELINE_VERSION} proxy={transcript_proxy_status()}",
        flush=True,
    )

    from database import BgSessionLocal
    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    try:
        _ensure_tables(db)
        _run_inner(db)
    except Exception as e:
        print(f"[ChannelMonitor] Error: {e}")
        import traceback; traceback.print_exc()
        # If _run_inner crashed before its finalize block, the scraper_runs
        # row is stuck at 'running' forever. Mark any recent running row
        # as 'error' so the dashboard reflects reality.
        try:
            db.execute(sql_text(
                "UPDATE scraper_runs SET status = 'error', finished_at = NOW(), "
                "error_message = :msg "
                "WHERE source = 'youtube' AND status = 'running' "
                "AND started_at > NOW() - INTERVAL '1 hour'"
            ), {"msg": f"_run_inner crash: {str(e)[:400]}"})
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        if own_db:
            db.close()


def _seed_target_channels(db):
    """Make sure every TARGET_CHANNELS entry exists in youtube_channels.

    Idempotent: rows added by prior runs are left alone. New entries
    inherit is_active=TRUE from the column default.
    """
    existing_names = {
        r[0] for r in db.execute(
            sql_text("SELECT channel_name FROM youtube_channels")
        ).fetchall()
    }
    inserted = 0
    for name in TARGET_CHANNELS:
        if name in existing_names:
            continue
        db.execute(
            sql_text("INSERT INTO youtube_channels (channel_name) VALUES (:n)"),
            {"n": name},
        )
        inserted += 1
    if inserted:
        db.commit()
        print(f"[ChannelMonitor] Seeded {inserted} new channels")


def _run_inner(db):
    _seed_target_channels(db)

    # Auto-discover new channels when all active channels have been
    # fully processed. Uses YouTube search to find finance channels
    # with >10K subs and >50 videos, then seeds up to 5 per cycle.
    try:
        _incomplete = int(db.execute(sql_text(
            "SELECT COUNT(*) FROM youtube_channels "
            "WHERE is_active = TRUE AND catalog_complete = FALSE"
        )).scalar() or 0)
        if _incomplete == 0:
            _discover_new_channels(db)
    except Exception:
        pass

    # Prune the YouTube rejection log to last 7 days, mirroring the
    # x_scraper_rejections cleanup at the top of run_x_scraper. Best-effort:
    # never block the scrape on this.
    try:
        db.execute(sql_text(
            "DELETE FROM youtube_scraper_rejections "
            "WHERE rejected_at < NOW() - INTERVAL '7 days'"
        ))
        db.commit()
    except Exception as e:
        print(f"[ChannelMonitor] rejection cleanup failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    # Auto-heal zombie scraper_runs rows left by prior crashes. A row
    # stuck in 'running' for >30 minutes is certainly dead — _run_inner
    # never takes that long on a healthy batch. Best-effort cleanup.
    try:
        zombies = db.execute(sql_text(
            "UPDATE scraper_runs SET status = 'timeout', finished_at = NOW(), "
            "error_message = 'Auto-healed zombie: running > 30 min' "
            "WHERE source = 'youtube' AND status = 'running' "
            "AND started_at < NOW() - INTERVAL '30 minutes' "
            "RETURNING id"
        )).fetchall()
        if zombies:
            db.commit()
            print(f"[ChannelMonitor] Healed {len(zombies)} zombie scraper_runs "
                  f"row(s): {[r[0] for r in zombies]}", flush=True)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    # Open a scraper_runs row so the admin Social Scrapers card can show
    # last-run funnel counts. Best-effort, mirrors the X scraper pattern.
    run_id: int | None = None
    try:
        run_id = db.execute(sql_text(
            "INSERT INTO scraper_runs (source, started_at, status) "
            "VALUES ('youtube', NOW(), 'running') RETURNING id"
        )).scalar()
        db.commit()
    except Exception as e:
        print(f"[ChannelMonitor] scraper_runs insert failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    # Pick the 10 least recently crawled active channels.
    # LEFT JOIN youtube_channel_meta so that channels the admin has manually
    # deactivated via /admin/youtube-channels are skipped, and so that the
    # iteration order respects tier (1=highest priority first). Channels
    # without a meta row yet (e.g. newly seeded via TARGET_CHANNELS that
    # haven't produced predictions yet) get tier=4 by default via COALESCE.
    batch_rows = db.execute(sql_text("""
        SELECT yc.channel_name, yc.youtube_channel_id, yc.last_crawled
        FROM youtube_channels yc
        LEFT JOIN youtube_channel_meta m ON m.channel_id = yc.youtube_channel_id
        WHERE yc.is_active = TRUE
          AND (m.active IS NULL OR m.active = TRUE)
        ORDER BY COALESCE(m.tier, 4) ASC, yc.last_crawled ASC NULLS FIRST
        LIMIT :lim
    """), {"lim": CHANNELS_PER_RUN}).fetchall()

    print(f"[ChannelMonitor] Processing {len(batch_rows)} channels")

    # Run-level stats. The first block is the legacy free-form keys used
    # in stdout logging since V1; the second block is the symmetric
    # schema used by scraper_runs (matches the X scraper). Both stay in
    # sync because the new keys are derived from the legacy ones at the
    # finalize step.
    stats = {
        "channels_checked": 0,
        "videos_seen": 0,
        "videos_skipped_already_processed": 0,
        "videos_skipped_short": 0,
        "videos_skipped_no_transcript": 0,
        "videos_classified": 0,
        "predictions_extracted": 0,
        "predictions_inserted": 0,
        "classifier_errors": 0,
        "yt_api_units": 0,
        # Cross-scraper symmetric counters — incremented inside
        # log_youtube_rejection / insert_youtube_prediction.
        "items_rejected": 0,
        "items_deduped": 0,
        # LLM cost/usage aggregates written to scraper_runs at finalize.
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_create_tokens": 0,
        "total_cache_read_tokens": 0,
        "estimated_cost_usd": 0.0,
        # Count of classify_video calls that hit stop_reason=='max_tokens'
        # on the first 800-token attempt and fell through to the 4000-
        # token retry. Populated from telem["haiku_retries"].
        "haiku_retries_count": 0,
        # Per-run sector_call counter — incremented inside
        # insert_youtube_sector_prediction. Written to
        # scraper_runs.sector_calls_extracted at finalize. Stays at 0
        # when ENABLE_YOUTUBE_SECTOR_CALLS flag is off (default).
        "sector_calls_extracted": 0,
        # Per-run options-position counter — incremented inside
        # insert_youtube_prediction when the pred dict carries
        # _derived_from='options_position'. Written to
        # scraper_runs.options_positions_extracted at finalize.
        # Stays at 0 when ENABLE_OPTIONS_POSITION_EXTRACTION is off.
        "options_positions_extracted": 0,
        # Per-run earnings_call counter — same pattern, incremented
        # inside insert_youtube_prediction when pred._derived_from ==
        # 'earnings_call'. Stays at 0 when ENABLE_EARNINGS_CALL_EXTRACTION
        # is off.
        "earnings_calls_extracted": 0,
        # Per-run macro_call counter — incremented inside
        # insert_youtube_macro_prediction after successful resolution
        # and insertion. Stays at 0 when ENABLE_MACRO_CALL_EXTRACTION
        # is off.
        "macro_calls_extracted": 0,
        # Per-run pair_call counter — incremented inside
        # insert_youtube_pair_prediction after both legs validate and
        # the row inserts. Stays at 0 when ENABLE_PAIR_CALL_EXTRACTION
        # is off.
        "pair_calls_extracted": 0,
        # Per-run binary_event_call counter — incremented inside
        # insert_youtube_binary_event_prediction after the row inserts.
        # Stays at 0 when ENABLE_BINARY_EVENT_EXTRACTION is off. Note
        # that counted rows all stay outcome='pending' indefinitely
        # until the follow-up ship plumbs in real data resolvers.
        "binary_events_extracted": 0,
        # Per-run metric_forecast_call counter — incremented inside
        # insert_youtube_metric_forecast_prediction after the row
        # inserts. Stays at 0 when ENABLE_METRIC_FORECAST_EXTRACTION
        # is off. Company metrics resolve via earnings_history (FMP);
        # macro metrics stay pending until follow-up data-source work.
        "metric_forecasts_extracted": 0,
        # Per-run conditional_call counter — incremented inside
        # insert_youtube_conditional_prediction. Stays 0 when
        # ENABLE_CONDITIONAL_CALL_EXTRACTION is off.
        "conditional_calls_extracted": 0,
        # Per-run disclosure counter — incremented inside
        # insert_youtube_disclosure. Stays 0 when
        # ENABLE_DISCLOSURE_EXTRACTION is off. Unlike every other
        # counter in this dict, the rows counted here do NOT live
        # in the predictions table — they live in `disclosures`.
        "disclosures_extracted": 0,
        # Ship #9 source-timestamp telemetry. Both stay 0 when the
        # flag is off; when it's on, every prediction (across every
        # type) goes through timestamp_matcher and lands in one of
        # these two counters depending on whether a real second was
        # resolved (matched) or source_timestamp_seconds stayed NULL
        # (failed).
        "timestamps_matched": 0,
        "timestamps_failed": 0,
        # Per-run regime_call counter — incremented inside
        # insert_youtube_regime_prediction. Stays 0 when
        # ENABLE_REGIME_CALL_EXTRACTION is off. Ship #12.
        "regime_calls_extracted": 0,
        # Ship #9 (rescoped) — prediction metadata enrichment.
        # timeframes_explicit counts accepted preds where Haiku
        # parsed an explicit timeframe; timeframes_inferred counts
        # accepted preds where the window came from a category
        # default; timeframes_rejected counts rejections with
        # reason='no_timeframe_determinable'; reference_rejected
        # counts rejections with reason='unresolvable_reference'.
        # Conviction counters break down the conviction_level
        # distribution per run. All stay 0 when
        # ENABLE_PREDICTION_METADATA_ENRICHMENT is off.
        "timeframes_explicit": 0,
        "timeframes_inferred": 0,
        "timeframes_rejected": 0,
        "reference_rejected": 0,
        "conviction_strong": 0,
        "conviction_moderate": 0,
        "conviction_hedged": 0,
        "conviction_hypothetical": 0,
        "conviction_unknown": 0,
    }

    for row in batch_rows:
        channel_name, channel_id, last_crawled = row[0], row[1], row[2]
        stats["channels_checked"] += 1

        # Resolve channel ID if missing (one-time per channel, costs 100 units)
        if not channel_id:
            channel_id = _resolve_channel_id(channel_name)
            stats["yt_api_units"] += 100
            if channel_id:
                db.execute(
                    sql_text("UPDATE youtube_channels SET youtube_channel_id = :cid WHERE channel_name = :name"),
                    {"cid": channel_id, "name": channel_name},
                )
                db.commit()
                print(f"[ChannelMonitor] Resolved {channel_name} → {channel_id}")
            else:
                print(f"[ChannelMonitor] Could not resolve channel: {channel_name}")
                db.execute(
                    sql_text("UPDATE youtube_channels SET last_crawled = :now WHERE channel_name = :name"),
                    {"now": datetime.utcnow(), "name": channel_name},
                )
                db.commit()
                continue

        # Full-catalog mode: paginate the channel's uploads playlist
        # via playlistItems.list (1 unit/page) instead of search.list
        # (100 units/page). Returns only unseen videos (pre-filtered
        # against youtube_videos).
        unseen, api_units, catalog_exhausted = _get_catalog_videos(
            channel_id, channel_name, db,
        )
        stats["yt_api_units"] += api_units

        total_in_db = len({
            r[0] for r in db.execute(sql_text(
                "SELECT youtube_video_id FROM youtube_videos "
                "WHERE channel_name = :name"
            ), {"name": channel_name}).fetchall()
        })
        print(
            f"[ChannelMonitor] channel={channel_name} "
            f"total_processed={total_in_db} unseen={len(unseen)} "
            f"catalog_complete={catalog_exhausted}",
            flush=True,
        )

        if not unseen:
            db.execute(
                sql_text("UPDATE youtube_channels SET last_crawled = :now WHERE channel_name = :name"),
                {"now": datetime.utcnow(), "name": channel_name},
            )
            if catalog_exhausted:
                db.execute(sql_text(
                    "UPDATE youtube_channels SET catalog_complete = TRUE "
                    "WHERE channel_name = :name"
                ), {"name": channel_name})
            db.commit()
            continue

        # Batch-fetch durations so the loop can skip Shorts before
        # burning a transcript fetch + Haiku call.
        _batch_vids = [v["video_id"] for v in unseen]
        video_durations = _fetch_video_durations(_batch_vids)
        if _batch_vids:
            stats["yt_api_units"] += 1

        channel_inserted = 0
        channel_videos = 0
        for vinfo in unseen:
            video_id = vinfo["video_id"]
            title = vinfo["title"]
            description = vinfo["description"]
            publish_date_str = vinfo["published_at"]
            if not video_id or not title:
                continue
            stats["videos_seen"] += 1

            # Skip videos under YOUTUBE_MIN_DURATION_SECONDS. Duration is
            # already batched via _fetch_video_durations above; 0 means
            # "unknown" and falls through to the title heuristic.
            dur_seconds = video_durations.get(video_id, 0)
            if 0 < dur_seconds < YOUTUBE_MIN_DURATION_SECONDS:
                stats["videos_skipped_short"] += 1
                _record_processed_video(
                    db, video_id, channel_name, title, description,
                    publish_date_str, "shorts_skipped", 0, 0,
                )
                log_youtube_rejection(
                    db,
                    video_id=video_id,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    video_title=title,
                    video_published_at=_parse_publish_date(publish_date_str),
                    reason="shorts_skipped",
                    haiku_reason=f"duration_seconds={dur_seconds}",
                    stats=stats,
                )
                continue

            # Skip Shorts (best-effort title-based heuristic — fallback
            # when videos.list didn't return a duration)
            if _is_likely_short(title, video_id):
                stats["videos_skipped_short"] += 1
                _record_processed_video(db, video_id, channel_name, title, description, publish_date_str, "shorts_skipped", 0, 0)
                log_youtube_rejection(
                    db,
                    video_id=video_id,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    video_title=title,
                    video_published_at=_parse_publish_date(publish_date_str),
                    reason="shorts_skipped",
                    stats=stats,
                )
                continue

            channel_videos += 1
            inserted_for_video, transcript_chars, transcript_status = _process_one_video(
                db, channel_name, channel_id, video_id, title, publish_date_str, stats,
            )
            if inserted_for_video > 0:
                channel_inserted += inserted_for_video

            # Per-channel auto-prune counter update. Only counts videos
            # that reached Haiku and got a verdict (ok_inserted /
            # ok_no_predictions); transcript failures and classifier
            # errors are excluded so transient infrastructure problems
            # cannot push a channel toward false-positive deactivation.
            _update_channel_yield_counters(
                db, channel_id, channel_name,
                transcript_status, inserted_for_video,
            )

            _record_processed_video(
                db, video_id, channel_name, title, description, publish_date_str,
                transcript_status, transcript_chars, inserted_for_video,
            )
            try:
                db.commit()
            except Exception as e:
                print(f"[ChannelMonitor] commit error after {video_id}: {e}")
                db.rollback()

            time.sleep(0.5)

        # Update channel state + catalog_complete flag
        try:
            _cat = "TRUE" if (catalog_exhausted and len(unseen) < MAX_VIDEOS_PER_CHANNEL) else "FALSE"
            db.execute(sql_text(f"""
                UPDATE youtube_channels
                SET last_crawled = :now,
                    total_videos_processed = total_videos_processed + :v,
                    total_predictions_extracted = total_predictions_extracted + :p,
                    catalog_complete = {_cat}
                WHERE channel_name = :name
            """), {"now": datetime.utcnow(), "v": channel_videos, "p": channel_inserted, "name": channel_name})
            db.commit()
        except Exception as e:
            print(f"[ChannelMonitor] channel state update error: {e}")
            db.rollback()

        # Mirror per-channel scrape stats into youtube_channel_meta so the
        # /admin/youtube-channels page shows the same last-run counts as
        # the scraper's canonical youtube_channels table.
        _upsert_meta_stats(
            db,
            channel_id=channel_id,
            channel_name=channel_name,
            videos_found=channel_videos,
            predictions_extracted=channel_inserted,
        )

        time.sleep(1)

    # Finalize scraper_runs row. Best-effort: any failure here is logged
    # and ignored — the run already happened. Keys map to the symmetric
    # X scraper schema:
    #   items_fetched   = videos_seen
    #   items_processed = videos that yielded a usable transcript
    #                     (videos_seen − no_transcript − shorts)
    #   items_llm_sent  = videos_classified
    #   items_inserted  = predictions_inserted
    #   items_rejected  = rows written to youtube_scraper_rejections
    #   items_deduped   = videos_skipped_already_processed + insert-time dedup
    items_processed = max(
        0,
        stats["videos_seen"]
        - stats["videos_skipped_no_transcript"]
        - stats["videos_skipped_short"],
    )
    if run_id is not None:
        try:
            db.execute(sql_text("""
                UPDATE scraper_runs
                SET finished_at = NOW(),
                    status = 'ok',
                    items_fetched = :fetched,
                    items_processed = :processed,
                    items_llm_sent = :llm_sent,
                    items_inserted = :inserted,
                    items_rejected = :rejected,
                    items_deduped = :deduped,
                    total_input_tokens = :in_tok,
                    total_output_tokens = :out_tok,
                    total_cache_create_tokens = :cc_tok,
                    total_cache_read_tokens = :cr_tok,
                    estimated_cost_usd = :cost,
                    haiku_retries_count = :retries,
                    sector_calls_extracted = :sector_calls,
                    options_positions_extracted = :options_positions,
                    earnings_calls_extracted = :earnings_calls,
                    macro_calls_extracted = :macro_calls,
                    pair_calls_extracted = :pair_calls,
                    binary_events_extracted = :binary_events,
                    metric_forecasts_extracted = :metric_forecasts,
                    conditional_calls_extracted = :conditional_calls,
                    disclosures_extracted = :disclosures,
                    timestamps_matched = :timestamps_matched,
                    timestamps_failed = :timestamps_failed,
                    regime_calls_extracted = :regime_calls,
                    timeframes_explicit = :tf_explicit,
                    timeframes_inferred = :tf_inferred,
                    timeframes_rejected = :tf_rejected,
                    reference_rejected = :ref_rejected,
                    conviction_strong = :conv_strong,
                    conviction_moderate = :conv_moderate,
                    conviction_hedged = :conv_hedged,
                    conviction_hypothetical = :conv_hypothetical,
                    conviction_unknown = :conv_unknown
                WHERE id = :id
            """), {
                "id": run_id,
                "fetched": int(stats["videos_seen"]),
                "processed": int(items_processed),
                "llm_sent": int(stats["videos_classified"]),
                "inserted": int(stats["predictions_inserted"]),
                "rejected": int(stats["items_rejected"]),
                "deduped": int(stats["items_deduped"]),
                "in_tok": int(stats.get("total_input_tokens", 0)),
                "out_tok": int(stats.get("total_output_tokens", 0)),
                "cc_tok": int(stats.get("total_cache_create_tokens", 0)),
                "cr_tok": int(stats.get("total_cache_read_tokens", 0)),
                "cost": round(float(stats.get("estimated_cost_usd", 0.0)), 4),
                "retries": int(stats.get("haiku_retries_count", 0)),
                "sector_calls": int(stats.get("sector_calls_extracted", 0)),
                "options_positions": int(stats.get("options_positions_extracted", 0)),
                "earnings_calls": int(stats.get("earnings_calls_extracted", 0)),
                "macro_calls": int(stats.get("macro_calls_extracted", 0)),
                "pair_calls": int(stats.get("pair_calls_extracted", 0)),
                "binary_events": int(stats.get("binary_events_extracted", 0)),
                "metric_forecasts": int(stats.get("metric_forecasts_extracted", 0)),
                "conditional_calls": int(stats.get("conditional_calls_extracted", 0)),
                "disclosures": int(stats.get("disclosures_extracted", 0)),
                "timestamps_matched": int(stats.get("timestamps_matched", 0)),
                "timestamps_failed": int(stats.get("timestamps_failed", 0)),
                "regime_calls": int(stats.get("regime_calls_extracted", 0)),
                "tf_explicit": int(stats.get("timeframes_explicit", 0)),
                "tf_inferred": int(stats.get("timeframes_inferred", 0)),
                "tf_rejected": int(stats.get("timeframes_rejected", 0)),
                "ref_rejected": int(stats.get("reference_rejected", 0)),
                "conv_strong": int(stats.get("conviction_strong", 0)),
                "conv_moderate": int(stats.get("conviction_moderate", 0)),
                "conv_hedged": int(stats.get("conviction_hedged", 0)),
                "conv_hypothetical": int(stats.get("conviction_hypothetical", 0)),
                "conv_unknown": int(stats.get("conviction_unknown", 0)),
            })
            db.commit()
        except Exception as e:
            print(f"[ChannelMonitor] scraper_runs finalize failed: {e}")
            try:
                db.rollback()
            except Exception:
                pass

    # Legacy DONE summary (kept for backwards compat with anything grepping
    # the worker logs).
    print(
        f"[ChannelMonitor] DONE: {stats['channels_checked']} channels checked, "
        f"{stats['videos_seen']} videos seen "
        f"({stats['videos_skipped_already_processed']} already processed, "
        f"{stats['videos_skipped_short']} shorts, "
        f"{stats['videos_skipped_no_transcript']} no transcript), "
        f"{stats['videos_classified']} classified, "
        f"{stats['predictions_inserted']} predictions inserted, "
        f"{stats['classifier_errors']} classifier errors, "
        f"~{stats['yt_api_units']} YouTube API units used",
        flush=True,
    )

    # Symmetric 4-line summary matching the [X-SCRAPER] format so both
    # scrapers are equally debuggable from worker stdout.
    print(f"[YOUTUBE-SCRAPER] RUN COMPLETE:", flush=True)
    print(
        f"  Channels: {stats['channels_checked']} checked",
        flush=True,
    )
    print(
        f"  Videos: {stats['videos_seen']} fetched, "
        f"{items_processed} with transcript, "
        f"{stats['videos_skipped_no_transcript']} no-transcript, "
        f"{stats['videos_skipped_short']} shorts",
        flush=True,
    )
    print(
        f"  Haiku ({HAIKU_MODEL}): {stats['videos_classified']} sent, "
        f"{stats['predictions_extracted']} predictions extracted",
        flush=True,
    )
    print(
        f"  INSERTED: {stats['predictions_inserted']} | "
        f"Deduped: {stats['items_deduped']} | "
        f"Rejected: {stats['items_rejected']} | "
        f"Errors: {stats['classifier_errors']}",
        flush=True,
    )
    _estimated_remaining = max(0, DAILY_QUOTA_LIMIT - stats["yt_api_units"])
    print(
        f"[ChannelMonitor] QUOTA: {stats['yt_api_units']} units this run, "
        f"~{_estimated_remaining} estimated remaining today",
        flush=True,
    )

    # 5% retry-rate warning. If Haiku is truncating often enough that
    # >5% of classified videos need the 800→4000 retry path, the
    # 800-token first-attempt cap from the cheapening commit is no
    # longer the right trade-off and should be raised. The wrapper
    # already writes [YOUTUBE-HAIKU-RETRY] lines per occurrence; this
    # is the aggregate signal.
    _retries = int(stats.get("haiku_retries_count", 0))
    _llm_sent = int(stats.get("videos_classified", 0))
    if _retries > 0 and _llm_sent > 0:
        _retry_rate = _retries / _llm_sent
        if _retry_rate > 0.05:
            print(
                f"[YOUTUBE-MONITOR] WARNING: Haiku retry rate "
                f"{_retry_rate:.1%} ({_retries}/{_llm_sent}) exceeds "
                f"5% threshold. Consider raising max_tokens first-"
                f"attempt cap from 800.",
                flush=True,
            )


def _process_one_video(db, channel_name, channel_id, video_id, title, publish_date_str, stats):
    """Fetch transcript → classify → insert. Returns (inserted, transcript_chars, status)."""
    publish_dt = _parse_publish_date(publish_date_str)

    # Ship #9: check the source-timestamps flag once per video. When
    # on, fetch with the rich path so transcript_data (segments + words
    # + has_word_level) stays in scope through classify → insert. When
    # off, use the legacy text-only fetcher to stay byte-for-byte
    # identical to pre-ship behavior.
    use_ts = False
    try:
        from feature_flags import is_source_timestamps_enabled
        use_ts = is_source_timestamps_enabled(db)
    except Exception:
        use_ts = False

    transcript_data: dict | None = None
    if use_ts:
        rich = fetch_transcript_with_timestamps(video_id)
        if rich.get("status") == "ok" and rich.get("text"):
            transcript_data = rich
            text = rich["text"]
            transcript_status = rich.get("lang") or "ok"
        else:
            text = None
            transcript_status = rich.get("status") or "no_transcript"
    else:
        text, transcript_status = fetch_transcript(video_id)

    # Evidence preservation (ship #13) — store the full transcript with
    # a SHA256 hash at capture time. Safe to call every run: ON CONFLICT
    # DO NOTHING means the first capture wins. Failure is swallowed so
    # the prediction pipeline is never blocked by storage issues.
    if text:
        try:
            from jobs.video_transcript_store import capture_transcript
            capture_transcript(
                db,
                video_id=video_id,
                channel_name=channel_name,
                video_title=title,
                video_publish_date=publish_dt,
                transcript_text=text,
                transcript_format="json3" if use_ts else "text",
            )
        except Exception as _e:
            print(f"[ChannelMonitor] transcript capture failed for {video_id}: {_e}", flush=True)

    if not text:
        stats["videos_skipped_no_transcript"] += 1
        print(f"[ChannelMonitor] {channel_name}: no transcript for {video_id} ({transcript_status})")
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=title,
            video_published_at=publish_dt,
            reason="no_transcript",
            haiku_reason=transcript_status,
            stats=stats,
        )
        return 0, 0, transcript_status or "no_transcript"

    transcript_chars = len(text)
    transcript_snippet = text[:500]

    # Default publish date if YouTube didn't return one
    if not publish_dt:
        publish_dt = datetime.utcnow()

    preds, telem = classify_video(
        channel_name, title,
        publish_date_str[:10] if publish_date_str else "",
        text, video_id=video_id, db=db,
    )
    stats["videos_classified"] += 1
    stats["predictions_extracted"] += telem.get("predictions_validated", 0)

    # Ship #9 (rescoped) — drain Haiku's explicit rejection entries.
    # The metadata_enrichment prompt block teaches Haiku to emit
    # {"rejected": true, "reason": "no_timeframe_determinable" |
    # "unresolvable_reference", "notes": "..."} for predictions that
    # fail the new rejection checks. classify_video buffered these on
    # telemetry["rejections"] with full per-rejection context; log
    # each to youtube_scraper_rejections here where we have the
    # channel_id / publish_dt / transcript_snippet context classify_video
    # doesn't. Counter totals (timeframes_rejected + reference_rejected)
    # flow into scraper_runs via stats so the admin diagnostics panel
    # can show the per-run distribution.
    for _rej in telem.get("rejections", []) or []:
        _reason = str(_rej.get("reason") or "haiku_rejection").strip().lower()[:50]
        _notes = _rej.get("notes")
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=title,
            video_published_at=publish_dt,
            reason=_reason or "haiku_rejection",
            haiku_reason=(str(_notes)[:500] if _notes else None),
            haiku_raw=_rej,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        if _reason == "no_timeframe_determinable":
            stats["timeframes_rejected"] = int(stats.get("timeframes_rejected", 0)) + 1
        elif _reason == "unresolvable_reference":
            stats["reference_rejected"] = int(stats.get("reference_rejected", 0)) + 1

    # Aggregate per-call token + cost telemetry into the run-level
    # stats dict. Finalize writes these to scraper_runs so the admin
    # card can render cost-per-run and cache-hit ratio. haiku_retries
    # is incremented once per chunk that triggered the 800→4000 retry
    # path inside call_youtube_haiku_with_retry.
    stats["total_input_tokens"] = int(stats.get("total_input_tokens", 0)) + int(telem.get("input_tokens", 0) or 0)
    stats["total_output_tokens"] = int(stats.get("total_output_tokens", 0)) + int(telem.get("output_tokens", 0) or 0)
    stats["total_cache_create_tokens"] = int(stats.get("total_cache_create_tokens", 0)) + int(telem.get("cache_create", 0) or 0)
    stats["total_cache_read_tokens"] = int(stats.get("total_cache_read_tokens", 0)) + int(telem.get("cache_read", 0) or 0)
    stats["estimated_cost_usd"] = float(stats.get("estimated_cost_usd", 0.0)) + float(telem.get("estimated_cost_usd", 0.0) or 0.0)
    stats["haiku_retries_count"] = int(stats.get("haiku_retries_count", 0)) + int(telem.get("haiku_retries", 0) or 0)

    if telem.get("error"):
        stats["classifier_errors"] += 1
        err_tag = telem.get("error") or "unknown"
        print(
            f"[ChannelMonitor] {channel_name}: classifier error on {video_id} — "
            f"{err_tag[:200]}"
        )
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=title,
            video_published_at=publish_dt,
            reason="classifier_error",
            haiku_reason=err_tag[:200],
            haiku_raw=telem,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return 0, transcript_chars, f"classifier_error"

    if not preds:
        log_youtube_rejection(
            db,
            video_id=video_id,
            channel_id=channel_id,
            channel_name=channel_name,
            video_title=title,
            video_published_at=publish_dt,
            reason="haiku_no_predictions",
            haiku_raw=telem,
            transcript_snippet=transcript_snippet,
            stats=stats,
        )
        return 0, transcript_chars, "ok_no_predictions"

    inserted = 0
    for pred in preds:
        try:
            kind = pred.get("_kind")
            # Route to the correct insert path based on the validator's
            # _kind stamp. Plain ticker_call (the vast majority, and 100%
            # of rows when every ship flag is off) takes the existing
            # path unchanged.
            if kind == "sector_call":
                ok = insert_youtube_sector_prediction(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                    transcript_data=transcript_data,
                )
            elif kind == "macro_call":
                ok = insert_youtube_macro_prediction(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                    transcript_data=transcript_data,
                )
            elif kind == "pair_call":
                ok = insert_youtube_pair_prediction(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                    transcript_data=transcript_data,
                )
            elif kind == "binary_event_call":
                ok = insert_youtube_binary_event_prediction(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                    transcript_data=transcript_data,
                )
            elif kind == "metric_forecast_call":
                ok = insert_youtube_metric_forecast_prediction(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                    transcript_data=transcript_data,
                )
            elif kind == "conditional_call":
                ok = insert_youtube_conditional_prediction(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                    transcript_data=transcript_data,
                )
            elif kind == "disclosure":
                # Disclosures land in the `disclosures` table, NOT
                # predictions. The ok count still feeds `inserted`
                # below so the scraper_runs counters are consistent,
                # but the per-type counter is
                # stats["disclosures_extracted"], not
                # stats["predictions_inserted"].
                ok = insert_youtube_disclosure(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                    transcript_data=transcript_data,
                )
            elif kind == "regime_call":
                ok = insert_youtube_regime_prediction(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                )
            else:
                ok = insert_youtube_prediction(
                    pred,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    video_id=video_id,
                    video_title=title,
                    publish_date=publish_dt,
                    db=db,
                    transcript_snippet=transcript_snippet,
                    stats=stats,
                    transcript_data=transcript_data,
                )
            if ok:
                inserted += 1
        except Exception as e:
            _key = (
                pred.get("ticker") or pred.get("sector")
                or pred.get("_concept")
                or (
                    f"{pred.get('_pair_long')}/{pred.get('_pair_short')}"
                    if pred.get("_pair_long") else None
                )
                or (
                    f"event:{pred.get('_event_type')}"
                    if pred.get("_event_type") else None
                )
                or (
                    f"metric:{pred.get('_metric_type')}"
                    if pred.get("_metric_type") else None
                )
                or "?"
            )
            print(f"[ChannelMonitor] insert error for {video_id} {_key}: {e}")
            db.rollback()

    stats["predictions_inserted"] += inserted

    if inserted > 0:
        url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"[ChannelMonitor] {channel_name}: \"{title[:80]}\" → {inserted} predictions ({url})")
        for p in preds[:5]:
            tgt = f", target=${p.get('price_target')}" if p.get('price_target') else ""
            print(f"[ChannelMonitor]   → {p.get('ticker')}: {p.get('direction').upper()}{tgt}")

    return inserted, transcript_chars, "ok_inserted" if inserted > 0 else "ok_no_predictions"


def _parse_publish_date(s: str):
    if not s:
        return None
    # YouTube returns 2026-04-09T13:21:18Z
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


# ── Per-channel yield tracking + auto-prune ─────────────────────────────────

# A channel is reached-Haiku if classify_video returned a verdict, i.e.
# transcript_status is one of these. classifier_error is intentionally
# excluded — a Haiku outage should not push channels toward auto-prune.
_REACHED_HAIKU_STATUSES = {"ok_inserted", "ok_no_predictions"}

# Auto-prune threshold: a channel that's processed this many videos
# without producing a single inserted prediction gets soft-deactivated.
# Pruned channels can be manually re-enabled from the admin panel.
AUTO_PRUNE_VIDEO_THRESHOLD = 5


def _update_channel_yield_counters(db, youtube_channel_id, channel_name,
                                    transcript_status, inserted_for_video):
    """Increment per-channel yield counters after a video is processed,
    and auto-deactivate the channel if it crosses the zero-yield threshold.

    videos_processed_count: +1 if the video reached Haiku and got a
                            verdict (regardless of how many predictions
                            survived the post-Haiku validation).
    predictions_extracted_count: +1 if at least one prediction from this
                            video was inserted into the predictions
                            table — the only signal that the channel is
                            actually producing usable content.

    Auto-prune trigger: after the increment, if videos_processed_count
    >= AUTO_PRUNE_VIDEO_THRESHOLD AND predictions_extracted_count == 0,
    the channel is soft-deactivated via _deactivate_channel().

    Best-effort: a write failure must NEVER break the scrape loop. The
    counters resync from youtube_videos on the next worker boot via the
    backfill in main.py / worker.py.
    """
    if transcript_status not in _REACHED_HAIKU_STATUSES:
        return

    if not youtube_channel_id:
        # Older channels may have NULL youtube_channel_id; fall back to
        # channel_name. Both columns are populated for live monitor runs.
        where_clause = "channel_name = :name"
    else:
        where_clause = "youtube_channel_id = :cid"

    inc_predictions = 1 if (inserted_for_video or 0) > 0 else 0
    try:
        # RETURNING the post-update counts so we can decide to prune
        # in the same round-trip without a follow-up SELECT.
        row = db.execute(sql_text(f"""
            UPDATE youtube_channels
            SET videos_processed_count = videos_processed_count + 1,
                predictions_extracted_count = predictions_extracted_count + :inc_p
            WHERE {where_clause}
              AND is_active = TRUE
            RETURNING videos_processed_count, predictions_extracted_count,
                      youtube_channel_id, channel_name
        """), {"cid": youtube_channel_id, "name": channel_name,
               "inc_p": inc_predictions}).first()
        db.commit()
    except Exception as e:
        print(f"[ChannelMonitor] yield counter update failed for "
              f"{channel_name}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return

    if not row:
        # Channel was already inactive (or row missing) — nothing to prune.
        return

    new_videos = int(row[0] or 0)
    new_preds = int(row[1] or 0)
    cid = row[2]
    cname = row[3] or channel_name

    if new_videos >= AUTO_PRUNE_VIDEO_THRESHOLD and new_preds == 0:
        _deactivate_channel(
            db, youtube_channel_id=cid, channel_name=cname,
            videos_processed=new_videos, predictions_extracted=new_preds,
            reason="auto_pruned_zero_yield",
        )


def _deactivate_channel(db, *, youtube_channel_id, channel_name,
                         videos_processed, predictions_extracted,
                         reason="auto_pruned_zero_yield"):
    """Soft-deactivate a YouTube channel. Sets is_active=FALSE and stamps
    deactivated_at + deactivation_reason. The row stays in the table
    forever; predictions, video metadata, and rejection logs are
    untouched. Pruned channels can be manually reactivated from the
    admin panel (clearing the counters for a fresh chance).

    The WHERE clause includes is_active = TRUE so a re-deactivation race
    is a no-op. The audit_log table requires admin_user_id NOT NULL and
    is therefore left to the manual reactivate endpoint, where a real
    admin user is in scope; auto-prunes are observable via the [YOUTUBE-
    MONITOR] stdout line and the deactivated_at column.
    """
    try:
        db.execute(sql_text("""
            UPDATE youtube_channels
            SET is_active = FALSE,
                deactivated_at = NOW(),
                deactivation_reason = :reason
            WHERE youtube_channel_id = :cid
              AND is_active = TRUE
        """), {"cid": youtube_channel_id, "reason": reason})
        db.commit()
        print(
            f"[YOUTUBE-MONITOR] Auto-deactivated channel {channel_name} "
            f"({youtube_channel_id}): {videos_processed} videos processed, "
            f"{predictions_extracted} predictions extracted",
            flush=True,
        )
    except Exception as e:
        print(f"[ChannelMonitor] deactivate_channel failed for "
              f"{channel_name}: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    # Mirror the deactivation into youtube_channel_meta (so the admin
    # page shows the same state) AND write an audit_log row so the
    # action is visible in the Audit Log tab.
    _deactivate_meta_and_log(
        db, youtube_channel_id=youtube_channel_id, channel_name=channel_name,
        videos_processed=videos_processed,
        predictions_extracted=predictions_extracted,
        reason=reason,
    )


def _record_processed_video(db, video_id, channel_name, title, description, publish_str,
                            transcript_status, transcript_chars, prediction_count):
    """Insert / update the youtube_videos dedup row.

    Uses ON CONFLICT (youtube_video_id) DO UPDATE so V1 rows (without
    pipeline_version) get re-stamped with V2 once they're re-processed.
    """
    try:
        db.execute(sql_text("""
            INSERT INTO youtube_videos
                (youtube_video_id, channel_name, title, description, publish_date,
                 predictions_extracted, pipeline_version, transcript_status, transcript_chars)
            VALUES (:vid, :ch, :title, :desc, :pub, :pcount, :pv, :ts, :tc)
            ON CONFLICT (youtube_video_id) DO UPDATE SET
                pipeline_version = EXCLUDED.pipeline_version,
                transcript_status = EXCLUDED.transcript_status,
                transcript_chars = EXCLUDED.transcript_chars,
                predictions_extracted = EXCLUDED.predictions_extracted,
                processed_at = NOW()
        """), {
            "vid": video_id,
            "ch": channel_name,
            "title": (title or "")[:500],
            "desc": (description or "")[:2000],
            "pub": _parse_publish_date(publish_str),
            "pcount": prediction_count,
            "pv": PIPELINE_VERSION,
            "ts": transcript_status,
            "tc": transcript_chars,
        })
    except Exception as e:
        print(f"[ChannelMonitor] _record_processed_video error: {e}")
        db.rollback()


# ── youtube_channel_meta bridge helpers ─────────────────────────────────────

def _upsert_meta_stats(db, *, channel_id, channel_name, videos_found,
                       predictions_extracted):
    """UPSERT per-channel scrape stats into youtube_channel_meta.

    Keyed by forecaster_id (the admin layer's source of truth). The
    forecaster is looked up by channel_id first, then falling back to
    name match, matching the find_or_create_youtube_forecaster logic in
    jobs/youtube_classifier.py.

    Best-effort: never breaks the scrape loop. If no forecaster exists
    yet (channel has never produced a prediction), the meta row is
    skipped — it will be backfilled on the next run after
    insert_youtube_prediction creates the forecaster.
    """
    if not channel_id:
        return
    try:
        row = db.execute(sql_text("""
            SELECT id FROM forecasters
            WHERE platform = 'youtube'
              AND (channel_id = :cid OR name = :name)
            ORDER BY (channel_id = :cid) DESC
            LIMIT 1
        """), {"cid": channel_id, "name": channel_name}).first()
        if not row:
            return
        fid = row[0]
        db.execute(sql_text("""
            INSERT INTO youtube_channel_meta
                (forecaster_id, channel_id, tier, active, added_date,
                 last_scraped_at, last_scrape_videos_found,
                 last_scrape_predictions_extracted,
                 total_videos_scraped, total_predictions_extracted)
            VALUES (:fid, :cid, 4, TRUE, NOW(), NOW(), :v, :p, :v, :p)
            ON CONFLICT (forecaster_id) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                last_scraped_at = NOW(),
                last_scrape_videos_found = EXCLUDED.last_scrape_videos_found,
                last_scrape_predictions_extracted = EXCLUDED.last_scrape_predictions_extracted,
                total_videos_scraped = youtube_channel_meta.total_videos_scraped
                                       + EXCLUDED.last_scrape_videos_found,
                total_predictions_extracted = youtube_channel_meta.total_predictions_extracted
                                              + EXCLUDED.last_scrape_predictions_extracted
        """), {"fid": fid, "cid": channel_id,
               "v": int(videos_found or 0),
               "p": int(predictions_extracted or 0)})
        db.commit()
    except Exception as e:
        print(f"[ChannelMonitor] meta stats upsert failed for "
              f"{channel_name}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def _deactivate_meta_and_log(db, *, youtube_channel_id, channel_name,
                              videos_processed, predictions_extracted,
                              reason="auto_pruned_zero_yield"):
    """Mirror the youtube_channels auto-prune into youtube_channel_meta
    and write an audit_log row. The audit_log write uses the super admin
    as admin_user_id because audit_log.admin_user_id is NOT NULL — the
    auto-prune is a system action but has to borrow an existing admin
    row to satisfy the FK. Best-effort: never breaks the scrape loop.
    """
    if not youtube_channel_id:
        return
    forecaster_id = None
    try:
        row = db.execute(sql_text("""
            UPDATE youtube_channel_meta
            SET active = FALSE,
                deactivated_at = NOW(),
                deactivation_reason = :reason
            WHERE channel_id = :cid AND active = TRUE
            RETURNING forecaster_id
        """), {"cid": youtube_channel_id, "reason": reason}).first()
        db.commit()
        if row:
            forecaster_id = int(row[0])
    except Exception as e:
        print(f"[ChannelMonitor] meta deactivate failed for "
              f"{channel_name}: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    # Audit log — best-effort. Skip if we can't find a super admin row.
    try:
        super_email = os.getenv("SUPER_ADMIN_EMAIL", "nimrodryder@gmail.com")
        admin_row = db.execute(sql_text(
            "SELECT id, email FROM users WHERE email = :e LIMIT 1"
        ), {"e": super_email}).first()
        if not admin_row:
            return
        details = json.dumps({
            "channel_id": youtube_channel_id,
            "name": channel_name,
            "videos_processed": int(videos_processed or 0),
            "predictions": int(predictions_extracted or 0),
            "reason": reason,
        })
        db.execute(sql_text("""
            INSERT INTO audit_log
                (admin_user_id, admin_email, action, target_type, target_id,
                 details, created_at)
            VALUES (:uid, :email, 'youtube_channel_auto_pruned',
                    'youtube_channel_meta', :tid, :details, NOW())
        """), {
            "uid": int(admin_row[0]),
            "email": admin_row[1] or super_email,
            "tid": forecaster_id,
            "details": details,
        })
        db.commit()
    except Exception as e:
        print(f"[ChannelMonitor] meta audit log write failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def fetch_channel_now(channel_id: str):
    """One-shot fetch of a single YouTube channel. Used by the
    /admin/youtube-channels/{id}/fetch-now endpoint to bypass the normal
    12h monitor schedule.

    Runs in-process (the endpoint invokes this from a daemon thread for
    fire-and-forget semantics). Creates its own DB session from
    BgSessionLocal so it's safe to call outside a request scope.

    Resolves the channel_id against the scraper's canonical
    youtube_channels table, then runs the same transcript → classify →
    insert flow as the regular batch loop but only for that one channel.
    """
    if not channel_id:
        return
    if not YOUTUBE_API_KEY or not ANTHROPIC_API_KEY:
        print(f"[ChannelMonitor] fetch_channel_now skipped for "
              f"{channel_id}: missing API keys")
        return

    from database import BgSessionLocal
    db = BgSessionLocal()
    try:
        _ensure_tables(db)
        row = db.execute(sql_text("""
            SELECT channel_name, youtube_channel_id, last_crawled
            FROM youtube_channels
            WHERE youtube_channel_id = :cid
            LIMIT 1
        """), {"cid": channel_id}).first()
        if not row:
            # Fall back to forecaster lookup so admins can fetch a channel
            # that exists as a forecaster but isn't in youtube_channels yet.
            f_row = db.execute(sql_text("""
                SELECT name FROM forecasters
                WHERE channel_id = :cid AND platform = 'youtube'
                LIMIT 1
            """), {"cid": channel_id}).first()
            if not f_row:
                print(f"[ChannelMonitor] fetch_channel_now: no channel "
                      f"found for {channel_id}")
                return
            channel_name = f_row[0]
            # Seed a youtube_channels row so regular monitor runs pick it up
            db.execute(sql_text("""
                INSERT INTO youtube_channels (channel_name, youtube_channel_id)
                VALUES (:name, :cid)
                ON CONFLICT DO NOTHING
            """), {"name": channel_name, "cid": channel_id})
            db.commit()
            last_crawled = None
        else:
            channel_name, _cid, last_crawled = row[0], row[1], row[2]

        stats = {
            "channels_checked": 1, "videos_seen": 0,
            "videos_skipped_already_processed": 0,
            "videos_skipped_short": 0, "videos_skipped_no_transcript": 0,
            "videos_classified": 0, "predictions_extracted": 0,
            "predictions_inserted": 0, "classifier_errors": 0,
            "yt_api_units": 0, "items_rejected": 0, "items_deduped": 0,
        }

        if last_crawled:
            since = last_crawled.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            since = (datetime.utcnow() - timedelta(days=7)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")

        videos = _get_recent_videos(channel_id, since)
        if not videos:
            print(f"[ChannelMonitor] fetch_channel_now: no new videos "
                  f"for {channel_name}")
            return

        # Batch-fetch durations so fetch_channel_now respects the same
        # YOUTUBE_MIN_DURATION_SECONDS floor as the main monitor loop.
        _fcn_vids = [
            (v.get("id") or {}).get("videoId")
            for v in videos
            if (v.get("id") or {}).get("videoId")
        ]
        video_durations = _fetch_video_durations(_fcn_vids)
        if _fcn_vids:
            stats["yt_api_units"] += 1

        channel_inserted = 0
        channel_videos = 0
        for video in videos:
            video_id = video.get("id", {}).get("videoId")
            snippet = video.get("snippet", {})
            title = snippet.get("title", "")
            description = snippet.get("description", "")
            publish_date_str = snippet.get("publishedAt", "")
            if not video_id or not title:
                continue
            stats["videos_seen"] += 1

            already = db.execute(sql_text(
                "SELECT 1 FROM youtube_videos "
                "WHERE youtube_video_id = :vid AND pipeline_version = :pv"
            ), {"vid": video_id, "pv": PIPELINE_VERSION}).first()
            if already:
                continue

            dur_seconds = video_durations.get(video_id, 0)
            if 0 < dur_seconds < YOUTUBE_MIN_DURATION_SECONDS:
                stats["videos_skipped_short"] += 1
                _record_processed_video(
                    db, video_id, channel_name, title, description,
                    publish_date_str, "shorts_skipped", 0, 0,
                )
                log_youtube_rejection(
                    db,
                    video_id=video_id,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    video_title=title,
                    video_published_at=_parse_publish_date(publish_date_str),
                    reason="shorts_skipped",
                    haiku_reason=f"duration_seconds={dur_seconds}",
                    stats=stats,
                )
                continue

            if _is_likely_short(title, video_id):
                continue

            channel_videos += 1
            inserted, tchars, tstatus = _process_one_video(
                db, channel_name, channel_id, video_id, title,
                publish_date_str, stats,
            )
            if inserted > 0:
                channel_inserted += inserted
            _update_channel_yield_counters(
                db, channel_id, channel_name, tstatus, inserted,
            )
            _record_processed_video(
                db, video_id, channel_name, title, description,
                publish_date_str, tstatus, tchars, inserted,
            )
            try:
                db.commit()
            except Exception:
                db.rollback()
            time.sleep(0.5)

        try:
            db.execute(sql_text("""
                UPDATE youtube_channels
                SET last_crawled = :now,
                    total_videos_processed = total_videos_processed + :v,
                    total_predictions_extracted = total_predictions_extracted + :p
                WHERE youtube_channel_id = :cid
            """), {"now": datetime.utcnow(), "v": channel_videos,
                   "p": channel_inserted, "cid": channel_id})
            db.commit()
        except Exception:
            db.rollback()

        _upsert_meta_stats(
            db, channel_id=channel_id, channel_name=channel_name,
            videos_found=channel_videos, predictions_extracted=channel_inserted,
        )

        print(f"[ChannelMonitor] fetch_channel_now DONE for {channel_name}: "
              f"{channel_videos} videos, {channel_inserted} predictions",
              flush=True)
    except Exception as e:
        print(f"[ChannelMonitor] fetch_channel_now error: {e}")
        import traceback; traceback.print_exc()
    finally:
        db.close()
