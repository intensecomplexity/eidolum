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
    classify_video,
    insert_youtube_prediction,
    log_youtube_rejection,
    transcript_proxy_status,
    PIPELINE_VERSION,
    HAIKU_MODEL,
)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

CHANNELS_PER_RUN = 10

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
        return None
    try:
        r = httpx.get(f"{YOUTUBE_API}/search", params={
            "part": "snippet", "q": channel_name, "type": "channel",
            "maxResults": 1, "key": YOUTUBE_API_KEY,
        }, timeout=10)
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
    except Exception:
        pass
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

    # Pick the 10 least recently crawled active channels
    batch_rows = db.execute(sql_text("""
        SELECT channel_name, youtube_channel_id, last_crawled
        FROM youtube_channels
        WHERE is_active = TRUE
        ORDER BY last_crawled ASC NULLS FIRST
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

        # Look back to last crawl, or 7 days for first run
        if last_crawled:
            since = last_crawled.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

        videos = _get_recent_videos(channel_id, since)
        stats["yt_api_units"] += 100

        if not videos:
            db.execute(
                sql_text("UPDATE youtube_channels SET last_crawled = :now WHERE channel_name = :name"),
                {"now": datetime.utcnow(), "name": channel_name},
            )
            db.commit()
            continue

        channel_inserted = 0
        channel_videos = 0
        for video in videos:
            video_id = video.get("id", {}).get("videoId")
            snippet = video.get("snippet", {})
            title = snippet.get("title", "")
            description = snippet.get("description", "")
            publish_date_str = snippet.get("publishedAt", "")
            if not video_id or not title:
                # No usable identifier — log so we can spot a YouTube API
                # response shape change without grepping the worker logs.
                log_youtube_rejection(
                    db,
                    video_id=video_id,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    video_title=title,
                    video_published_at=_parse_publish_date(publish_date_str),
                    reason="no_video_id",
                    haiku_raw=video,
                    stats=stats,
                )
                continue
            stats["videos_seen"] += 1

            # Skip videos already processed by THIS pipeline version. V1
            # rows (pipeline_version IS NULL) are eligible for re-processing.
            already = db.execute(sql_text(
                "SELECT 1 FROM youtube_videos WHERE youtube_video_id = :vid AND pipeline_version = :pv"
            ), {"vid": video_id, "pv": PIPELINE_VERSION}).first()
            if already:
                stats["videos_skipped_already_processed"] += 1
                stats["items_deduped"] += 1
                continue

            # Skip Shorts (best-effort title-based heuristic — duration
            # would require an extra videos.list call)
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

        # Update channel state
        try:
            db.execute(sql_text("""
                UPDATE youtube_channels
                SET last_crawled = :now,
                    total_videos_processed = total_videos_processed + :v,
                    total_predictions_extracted = total_predictions_extracted + :p
                WHERE channel_name = :name
            """), {"now": datetime.utcnow(), "v": channel_videos, "p": channel_inserted, "name": channel_name})
            db.commit()
        except Exception as e:
            print(f"[ChannelMonitor] channel state update error: {e}")
            db.rollback()

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
                    items_deduped = :deduped
                WHERE id = :id
            """), {
                "id": run_id,
                "fetched": int(stats["videos_seen"]),
                "processed": int(items_processed),
                "llm_sent": int(stats["videos_classified"]),
                "inserted": int(stats["predictions_inserted"]),
                "rejected": int(stats["items_rejected"]),
                "deduped": int(stats["items_deduped"]),
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


def _process_one_video(db, channel_name, channel_id, video_id, title, publish_date_str, stats):
    """Fetch transcript → classify → insert. Returns (inserted, transcript_chars, status)."""
    publish_dt = _parse_publish_date(publish_date_str)

    text, transcript_status = fetch_transcript(video_id)
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

    preds, telem = classify_video(channel_name, title, publish_date_str[:10] if publish_date_str else "", text)
    stats["videos_classified"] += 1
    stats["predictions_extracted"] += telem.get("predictions_validated", 0)

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
            )
            if ok:
                inserted += 1
        except Exception as e:
            print(f"[ChannelMonitor] insert error for {video_id} {pred.get('ticker')}: {e}")
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


# ── Per-channel yield tracking ──────────────────────────────────────────────

# A channel is reached-Haiku if classify_video returned a verdict, i.e.
# transcript_status is one of these. classifier_error is intentionally
# excluded — a Haiku outage should not push channels toward auto-prune.
_REACHED_HAIKU_STATUSES = {"ok_inserted", "ok_no_predictions"}


def _update_channel_yield_counters(db, youtube_channel_id, channel_name,
                                    transcript_status, inserted_for_video):
    """Increment per-channel yield counters after a video is processed.

    videos_processed_count: +1 if the video reached Haiku and got a
                            verdict (regardless of how many predictions
                            survived the post-Haiku validation).
    predictions_extracted_count: +1 if at least one prediction from this
                            video was inserted into the predictions
                            table — the only signal that the channel is
                            actually producing usable content.

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
        db.execute(sql_text(f"""
            UPDATE youtube_channels
            SET videos_processed_count = videos_processed_count + 1,
                predictions_extracted_count = predictions_extracted_count + :inc_p
            WHERE {where_clause}
              AND is_active = TRUE
        """), {"cid": youtube_channel_id, "name": channel_name,
               "inc_p": inc_predictions})
        db.commit()
    except Exception as e:
        print(f"[ChannelMonitor] yield counter update failed for "
              f"{channel_name}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


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
