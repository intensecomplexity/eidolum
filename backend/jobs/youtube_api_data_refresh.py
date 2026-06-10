"""
youtube_api_data_refresh.py — rolling 30-day refresh of the YouTube Data API
metadata stored in youtube_channels / youtube_videos (compliance: stored API
data is refreshed or deleted on a rolling 30-day basis).

Logic:
  - youtube_videos: rows whose metadata_refreshed_at is older than 30 days are
    re-fetched via videos.list (part=snippet, 50 ids per 1-unit call). Found
    rows get their title / description / publish_date updated; rows missing
    from the API response (video deleted or made private) get their stored
    API metadata blanked. The dedup row itself stays (the pipeline needs the
    video ID to avoid reprocessing).
  - youtube_channels: same treatment via channels.list (part=statistics).
    subscriber_count is the only API-sourced display field here —
    channel_name comes from the TARGET_CHANNELS code seed list and
    youtube_channel_id is the pipeline join key, so neither is rewritten.
  - Scope is API-sourced metadata ONLY. Predictions, transcripts, and
    evaluation data are never touched.

Quota: every batch call costs 1 unit. The run is hard-capped by
YT_REFRESH_MAX_UNITS_PER_RUN (default 100 units/day — 3000 videos via
videos.list plus channel batches, far under the 10K daily quota).

Kill switch: ENABLE_YT_METADATA_REFRESH env var, default true.

Requires metadata_refreshed_at TIMESTAMPTZ on both tables — applied as a
manual DDL (RUN_STARTUP_DDL=false in prod), backfilled from each row's
existing processed_at / last_crawled so the first runs spread naturally.
"""
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import text as sql_text

from database import BgSessionLocal

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
TAG = "[yt_metadata_refresh]"

STALE_DAYS = 30
BATCH = 50  # videos.list / channels.list take up to 50 ids per 1-unit call
UNAVAILABLE_TITLE = "(video unavailable)"


def _enabled() -> bool:
    return os.getenv("ENABLE_YT_METADATA_REFRESH", "true").strip().lower() in ("1", "true", "yes")


def _max_videos() -> int:
    return int(os.getenv("YT_REFRESH_MAX_VIDEOS_PER_RUN", "3000"))


def _max_units() -> int:
    return int(os.getenv("YT_REFRESH_MAX_UNITS_PER_RUN", "100"))


def _parse_published(s: str):
    """'2024-01-05T14:00:00Z' -> naive-UTC datetime (columns are TIMESTAMP)."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _api_get(resource: str, params: dict):
    """One 1-unit batch call. Returns (items, ok). Logs the response body on
    any non-200 so quota/auth failures are diagnosable from the worker log."""
    try:
        r = httpx.get(f"{YOUTUBE_API}/{resource}", params={**params, "key": YOUTUBE_API_KEY}, timeout=20)
        if r.status_code != 200:
            print(f"{TAG} {resource} HTTP {r.status_code}: {r.text[:300]}")
            return [], False
        return r.json().get("items", []), True
    except Exception as e:
        print(f"{TAG} {resource} error: {e}")
        return [], False


def _refresh_videos(db, budget: dict, counts: dict):
    rows = db.execute(sql_text(f"""
        SELECT youtube_video_id FROM youtube_videos
         WHERE metadata_refreshed_at IS NULL
            OR metadata_refreshed_at < NOW() - INTERVAL '{STALE_DAYS} days'
         ORDER BY metadata_refreshed_at ASC NULLS FIRST
         LIMIT :lim
    """), {"lim": min(_max_videos(), budget["units"] * BATCH)}).fetchall()
    ids = [r[0] for r in rows]
    counts["videos_due"] = len(ids)

    for i in range(0, len(ids), BATCH):
        if budget["units"] <= 0:
            break
        chunk = ids[i:i + BATCH]
        items, ok = _api_get("videos", {"part": "snippet", "id": ",".join(chunk)})
        budget["units"] -= 1
        if not ok:
            counts["api_errors"] += 1
            break  # quota/auth problem — stop burning calls this run
        found = {it["id"]: it.get("snippet") or {} for it in items}
        for vid in chunk:
            sn = found.get(vid)
            if sn is not None:
                db.execute(sql_text("""
                    UPDATE youtube_videos
                       SET title = :t, description = :d, publish_date = COALESCE(:p, publish_date),
                           metadata_refreshed_at = NOW()
                     WHERE youtube_video_id = :vid
                """), {"t": sn.get("title") or UNAVAILABLE_TITLE, "d": sn.get("description"),
                       "p": _parse_published(sn.get("publishedAt")), "vid": vid})
                counts["videos_refreshed"] += 1
            else:
                # Deleted/private upstream: blank the stored API metadata,
                # keep the dedup row so the pipeline doesn't reprocess.
                db.execute(sql_text("""
                    UPDATE youtube_videos
                       SET title = :t, description = NULL, metadata_refreshed_at = NOW()
                     WHERE youtube_video_id = :vid
                """), {"t": UNAVAILABLE_TITLE, "vid": vid})
                counts["videos_unavailable"] += 1
        db.commit()


def _refresh_channels(db, budget: dict, counts: dict):
    rows = db.execute(sql_text(f"""
        SELECT youtube_channel_id FROM youtube_channels
         WHERE youtube_channel_id IS NOT NULL
           AND (metadata_refreshed_at IS NULL
                OR metadata_refreshed_at < NOW() - INTERVAL '{STALE_DAYS} days')
         ORDER BY metadata_refreshed_at ASC NULLS FIRST
    """)).fetchall()
    ids = [r[0] for r in rows]
    counts["channels_due"] = len(ids)

    for i in range(0, len(ids), BATCH):
        if budget["units"] <= 0:
            break
        chunk = ids[i:i + BATCH]
        items, ok = _api_get("channels", {"part": "statistics", "id": ",".join(chunk)})
        budget["units"] -= 1
        if not ok:
            counts["api_errors"] += 1
            break
        found = {it["id"]: it.get("statistics") or {} for it in items}
        for cid in chunk:
            st = found.get(cid)
            if st is not None:
                subs = st.get("subscriberCount")
                db.execute(sql_text("""
                    UPDATE youtube_channels
                       SET subscriber_count = :s, metadata_refreshed_at = NOW()
                     WHERE youtube_channel_id = :cid
                """), {"s": int(subs) if subs is not None else None, "cid": cid})
                counts["channels_refreshed"] += 1
            else:
                db.execute(sql_text("""
                    UPDATE youtube_channels
                       SET subscriber_count = NULL, metadata_refreshed_at = NOW()
                     WHERE youtube_channel_id = :cid
                """), {"cid": cid})
                counts["channels_unavailable"] += 1
        db.commit()


def run_youtube_api_data_refresh(max_videos: int | None = None, max_units: int | None = None) -> dict:
    counts = {"videos_due": 0, "videos_refreshed": 0, "videos_unavailable": 0,
              "channels_due": 0, "channels_refreshed": 0, "channels_unavailable": 0,
              "api_errors": 0, "units_used": 0, "skipped": None}
    if not _enabled():
        counts["skipped"] = "ENABLE_YT_METADATA_REFRESH is off"
        print(f"{TAG} skipped: kill switch off")
        return counts
    if not YOUTUBE_API_KEY:
        counts["skipped"] = "no YOUTUBE_API_KEY"
        print(f"{TAG} skipped: no YOUTUBE_API_KEY")
        return counts

    if max_videos is not None:
        os.environ["YT_REFRESH_MAX_VIDEOS_PER_RUN"] = str(max_videos)
    total_units = max_units if max_units is not None else _max_units()
    budget = {"units": total_units}

    db = BgSessionLocal()
    try:
        _refresh_channels(db, budget, counts)
        _refresh_videos(db, budget, counts)
    finally:
        db.close()

    counts["units_used"] = total_units - budget["units"]
    print(f"{TAG} done: {counts}")
    return counts
