"""
YouTube Historical Backfill (Eidolum)

Walks each active YouTube channel's full upload history, oldest videos
first, and runs each through the same transcript → Haiku → predictions
pipeline used by the live channel monitor (jobs.youtube_classifier).

Why oldest-first: the evaluator can immediately score historical
predictions against known historical price data, so the leaderboard
populates faster. Newest-first would leave the score column 'pending'
on every backfilled prediction until the evaluation date arrives.

Pacing:
  - 50 videos per channel per run (the spec's per-run cap)
  - 4-hour cadence (registered in worker.py)
  - In total: 45 channels × 50 videos × 6 runs/day = 13,500 videos/day
    backfill capacity, well above the typical channel's video count
  - YouTube Data API quota: one playlistItems.list call per page (1
    unit) for the initial enumeration, ~20 calls per channel for a
    1,000-video channel ⇒ ~900 units one-time across all channels.
    Subsequent runs cost 0 quota for enumeration (cursor cached in
    youtube_channels.backfill_cursor JSON).

Resume strategy:
  - First run for a channel: enumerate ALL upload IDs via the channel's
    uploads playlist (cheap, paginated), reverse to oldest-first, store
    the full list and next_idx=0 in youtube_channels.backfill_cursor.
  - Subsequent runs: load cursor, process videos[next_idx:next_idx+50],
    increment next_idx. Persist after each video so a crash mid-batch
    only loses the in-flight item.
  - When next_idx >= len(videos), set phase='complete' and never list
    again. New videos uploaded after enumeration are picked up by the
    regular channel monitor's recent-videos search.

The backfill is INDEPENDENT of the regular monitor — they share the
youtube_videos dedup table so neither one re-processes a video the
other has already done.
"""
import os
import json
import time
import httpx
from datetime import datetime, timedelta

from sqlalchemy import text as sql_text

from jobs.youtube_classifier import (
    fetch_transcript,
    classify_video,
    insert_youtube_prediction,
    transcript_proxy_status,
    PIPELINE_VERSION,
    HAIKU_MODEL,
)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

VIDEOS_PER_CHANNEL_PER_RUN = 50

# Per-channel quota guard: enumeration of an extremely long upload
# history (some channels have 5000+ videos) shouldn't be allowed to
# eat the whole daily quota in one shot.
MAX_LIST_PAGES_PER_CHANNEL = 60  # 60 pages × 50 items = 3000 videos cap

# Historical age cap. Videos older than this are dropped during
# enumeration AND skipped at processing time (defensive layer for
# cursors that were enumerated before this cap shipped — they still
# hold pre-cap video IDs and need to drain past them on the way to
# the in-window region of the upload history).
YOUTUBE_BACKFILL_MAX_AGE_DAYS = 1095  # 3 years


def run_youtube_backfill(db=None):
    """Main entry point. Runs every 4h via worker.py."""
    if not YOUTUBE_API_KEY:
        print("[YT-Backfill] YOUTUBE_API_KEY not set — skipping")
        return
    if not ANTHROPIC_API_KEY:
        print("[YT-Backfill] ANTHROPIC_API_KEY not set — skipping")
        return

    print(
        f"[YT-Backfill] Starting | classifier={HAIKU_MODEL} pipeline={PIPELINE_VERSION} "
        f"proxy={transcript_proxy_status()}",
        flush=True,
    )

    from database import BgSessionLocal
    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    try:
        _run_inner(db)
    except Exception as e:
        print(f"[YT-Backfill] Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        if own_db:
            db.close()


def _run_inner(db):
    rows = db.execute(sql_text("""
        SELECT channel_name, youtube_channel_id, backfill_cursor
        FROM youtube_channels
        WHERE is_active = TRUE
          AND youtube_channel_id IS NOT NULL
        ORDER BY (backfill_cursor IS NULL) DESC, channel_name
    """)).fetchall()

    if not rows:
        print("[YT-Backfill] No active channels with resolved IDs")
        return

    print(f"[YT-Backfill] {len(rows)} active channels with resolved IDs")

    total_processed = 0
    total_inserted = 0
    total_quota = 0
    cutoff = datetime.utcnow() - timedelta(days=YOUTUBE_BACKFILL_MAX_AGE_DAYS)

    for row in rows:
        channel_name, channel_id, cursor_json = row[0], row[1], row[2]

        cursor = _load_cursor(cursor_json)
        if cursor.get("phase") == "complete":
            continue

        # Phase 1: enumerate uploads playlist (one-time per channel)
        if cursor.get("phase") != "processing":
            print(f"[YT-Backfill] {channel_name}: enumerating uploads playlist...")
            try:
                video_ids, list_quota = _enumerate_uploads(channel_id)
            except Exception as e:
                print(f"[YT-Backfill] {channel_name}: enumeration failed: {e}")
                continue
            total_quota += list_quota
            if not video_ids:
                print(f"[YT-Backfill] {channel_name}: 0 videos found, marking complete")
                cursor = {"phase": "complete", "videos": [], "next_idx": 0}
                _save_cursor(db, channel_name, cursor)
                continue
            # Reverse — playlistItems is newest-first, we want oldest-first
            video_ids = list(reversed(video_ids))
            cursor = {"phase": "processing", "videos": video_ids, "next_idx": 0,
                      "enumerated_at": datetime.utcnow().isoformat()}
            _save_cursor(db, channel_name, cursor)
            print(f"[YT-Backfill] {channel_name}: enumerated {len(video_ids)} videos "
                  f"({list_quota} units), phase=processing")

        # Phase 2: process the next batch
        videos = cursor.get("videos") or []
        next_idx = int(cursor.get("next_idx") or 0)
        end_idx = min(next_idx + VIDEOS_PER_CHANNEL_PER_RUN, len(videos))

        if next_idx >= len(videos):
            print(f"[YT-Backfill] {channel_name}: complete ({len(videos)} videos)")
            cursor["phase"] = "complete"
            _save_cursor(db, channel_name, cursor)
            continue

        batch = videos[next_idx:end_idx]
        print(f"[YT-Backfill] {channel_name}: processing videos "
              f"{next_idx + 1}-{end_idx}/{len(videos)}")

        # Fetch metadata for the batch in ONE videos.list call (1 quota
        # unit per call, max 50 IDs per call). Cheaper than 50 single
        # search.list calls and gives us title + publish_date directly.
        meta = _fetch_video_metadata(batch)
        total_quota += 1  # one videos.list call per batch

        channel_inserted = 0
        for vid in batch:
            m = meta.get(vid) or {}
            title = m.get("title") or ""
            publish_str = m.get("published_at") or ""

            # 3-year cap defensive layer. Enumeration filters new
            # cursors at creation time, but cursors created before this
            # cap shipped still hold pre-cap video IDs at the head of
            # the oldest-first list. Skip them silently so the cursor
            # can drain past them on the way to the in-window region.
            publish_dt = _parse_publish_date(publish_str)
            if publish_dt and publish_dt < cutoff:
                print(
                    f"[YOUTUBE-BACKFILL] Skipping {vid} from {channel_name}: "
                    f"published {publish_str or 'unknown'}, older than "
                    f"{YOUTUBE_BACKFILL_MAX_AGE_DAYS // 365} year cap"
                )
                continue

            # Skip Shorts cheaply
            if m.get("duration_seconds") and m.get("duration_seconds") < 60:
                _record_skipped(db, vid, channel_name, title, "shorts_skipped")
                continue

            # Skip if already in youtube_videos with this pipeline version
            already = db.execute(sql_text(
                "SELECT 1 FROM youtube_videos WHERE youtube_video_id = :vid AND pipeline_version = :pv"
            ), {"vid": vid, "pv": PIPELINE_VERSION}).first()
            if already:
                continue

            inserted, transcript_chars, transcript_status = _process_one_video(
                db, channel_name, channel_id, vid, title, publish_str
            )
            channel_inserted += inserted
            total_inserted += inserted
            total_processed += 1

            _record_processed_video(
                db, vid, channel_name, title, "", publish_str,
                transcript_status, transcript_chars, inserted,
            )
            try:
                db.commit()
            except Exception as e:
                print(f"[YT-Backfill] commit error after {vid}: {e}")
                db.rollback()
            time.sleep(0.5)

        # Advance cursor
        cursor["next_idx"] = end_idx
        if end_idx >= len(videos):
            cursor["phase"] = "complete"
        _save_cursor(db, channel_name, cursor)
        print(f"[YT-Backfill] {channel_name}: batch done, {channel_inserted} predictions inserted "
              f"(progress {end_idx}/{len(videos)}, phase={cursor['phase']})")

    print(
        f"[YT-Backfill] DONE: {total_processed} videos processed, "
        f"{total_inserted} predictions inserted, ~{total_quota} YouTube API units used",
        flush=True,
    )


# ── YouTube Data API helpers ────────────────────────────────────────────────

def _enumerate_uploads(channel_id: str) -> tuple[list[str], int]:
    """Page through the channel's uploads playlist and collect every video ID.

    Steps:
      1. channels.list to get the uploads playlist ID for this channel
         (1 quota unit)
      2. playlistItems.list paginated through the uploads playlist
         (1 quota unit per page, 50 items per page)
    Returns (video_ids_in_playlist_order, quota_units_used).
    The list is in YouTube's natural newest-first order — caller flips it.

    Age cap: pages come back newest-first, and items within a page are
    also newest-first, so the FIRST video older than the cutoff means
    every subsequent item / page is even older. We stop the pagination
    immediately on hitting that boundary. Adding 'snippet' to the part
    parameter does NOT change quota cost — playlistItems.list is 1 unit
    per call regardless of how many parts you ask for.
    """
    units = 0
    cutoff = datetime.utcnow() - timedelta(days=YOUTUBE_BACKFILL_MAX_AGE_DAYS)
    # Get the uploads playlist ID
    r = httpx.get(f"{YOUTUBE_API}/channels", params={
        "part": "contentDetails", "id": channel_id, "key": YOUTUBE_API_KEY,
    }, timeout=15)
    units += 1
    if r.status_code == 403:
        print(f"[YT-Backfill] channels.list quota exceeded: {r.text[:200]}")
        return [], units
    if r.status_code != 200:
        print(f"[YT-Backfill] channels.list HTTP {r.status_code}: {r.text[:200]}")
        return [], units
    items = r.json().get("items", [])
    if not items:
        return [], units
    uploads_playlist = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads_playlist:
        return [], units

    video_ids: list[str] = []
    page_token = None
    pages = 0
    hit_age_cap = False
    while pages < MAX_LIST_PAGES_PER_CHANNEL:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": 50,
            "key": YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token
        r = httpx.get(f"{YOUTUBE_API}/playlistItems", params=params, timeout=15)
        units += 1
        if r.status_code == 403:
            print(f"[YT-Backfill] playlistItems.list quota exceeded after {pages} pages")
            break
        if r.status_code != 200:
            print(f"[YT-Backfill] playlistItems.list HTTP {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        for it in data.get("items", []):
            pub_str = (it.get("snippet") or {}).get("publishedAt", "")
            pub_dt = _parse_publish_date(pub_str)
            if pub_dt and pub_dt < cutoff:
                hit_age_cap = True
                break
            vid = (it.get("contentDetails") or {}).get("videoId")
            if vid:
                video_ids.append(vid)
        if hit_age_cap:
            print(
                f"[YT-Backfill] hit {YOUTUBE_BACKFILL_MAX_AGE_DAYS}-day cap "
                f"after {pages + 1} pages, stopping enumeration "
                f"({len(video_ids)} in-window videos collected)"
            )
            break
        page_token = data.get("nextPageToken")
        pages += 1
        if not page_token:
            break

    return video_ids, units


def _fetch_video_metadata(video_ids: list[str]) -> dict:
    """Batch videos.list call. Returns {video_id: {title, published_at, duration_seconds}}."""
    if not video_ids:
        return {}
    out: dict = {}
    try:
        r = httpx.get(f"{YOUTUBE_API}/videos", params={
            "part": "snippet,contentDetails",
            "id": ",".join(video_ids[:50]),
            "key": YOUTUBE_API_KEY,
        }, timeout=15)
        if r.status_code != 200:
            return {}
        for it in r.json().get("items", []):
            vid = it.get("id")
            snippet = it.get("snippet", {}) or {}
            content = it.get("contentDetails", {}) or {}
            out[vid] = {
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "duration_seconds": _parse_iso_duration(content.get("duration", "")),
            }
    except Exception as e:
        print(f"[YT-Backfill] videos.list error: {e}")
    return out


def _parse_iso_duration(s: str) -> int:
    """ISO-8601 PT#H#M#S → seconds. Returns 0 on parse failure."""
    if not s or not s.startswith("PT"):
        return 0
    import re as _re
    h = m = sec = 0
    mh = _re.search(r"(\d+)H", s)
    mm = _re.search(r"(\d+)M", s)
    ms = _re.search(r"(\d+)S", s)
    if mh: h = int(mh.group(1))
    if mm: m = int(mm.group(1))
    if ms: sec = int(ms.group(1))
    return h * 3600 + m * 60 + sec


# ── Per-video pipeline ──────────────────────────────────────────────────────

def _process_one_video(db, channel_name, channel_id, video_id, title, publish_str):
    """Identical control flow to channel_monitor._process_one_video,
    but inlined here so the backfill doesn't import the monitor (avoids
    circular import + lets each job evolve independently)."""
    text, transcript_status = fetch_transcript(video_id)
    if not text:
        return 0, 0, transcript_status or "no_transcript"
    transcript_chars = len(text)

    publish_dt = _parse_publish_date(publish_str) or datetime.utcnow()

    preds, telem = classify_video(
        channel_name, title,
        publish_str[:10] if publish_str else "",
        text, video_id=video_id, db=db,
    )
    if telem.get("error"):
        print(f"[YT-Backfill] {channel_name}: classifier error on {video_id} — {telem.get('error')[:200]}")
        return 0, transcript_chars, "classifier_error"

    if not preds:
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
            )
            if ok:
                inserted += 1
        except Exception as e:
            print(f"[YT-Backfill] insert error for {video_id} {pred.get('ticker')}: {e}")
            db.rollback()
    if inserted > 0:
        url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"[YT-Backfill] {channel_name}: \"{title[:80]}\" → {inserted} predictions ({url})")
    return inserted, transcript_chars, "ok_inserted" if inserted > 0 else "ok_no_predictions"


# ── Cursor / record helpers ─────────────────────────────────────────────────

def _load_cursor(cursor_json) -> dict:
    if not cursor_json:
        return {}
    try:
        return json.loads(cursor_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _save_cursor(db, channel_name: str, cursor: dict):
    try:
        db.execute(sql_text(
            "UPDATE youtube_channels SET backfill_cursor = :c WHERE channel_name = :n"
        ), {"c": json.dumps(cursor), "n": channel_name})
        db.commit()
    except Exception as e:
        print(f"[YT-Backfill] cursor save error for {channel_name}: {e}")
        db.rollback()


def _record_skipped(db, video_id, channel_name, title, status):
    try:
        db.execute(sql_text("""
            INSERT INTO youtube_videos
                (youtube_video_id, channel_name, title, predictions_extracted,
                 pipeline_version, transcript_status, transcript_chars)
            VALUES (:vid, :ch, :title, 0, :pv, :ts, 0)
            ON CONFLICT (youtube_video_id) DO UPDATE SET
                pipeline_version = EXCLUDED.pipeline_version,
                transcript_status = EXCLUDED.transcript_status,
                processed_at = NOW()
        """), {"vid": video_id, "ch": channel_name,
               "title": (title or "")[:500], "pv": PIPELINE_VERSION, "ts": status})
        db.commit()
    except Exception as e:
        print(f"[YT-Backfill] _record_skipped error: {e}")
        db.rollback()


def _record_processed_video(db, video_id, channel_name, title, description,
                            publish_str, transcript_status, transcript_chars, prediction_count):
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
            "vid": video_id, "ch": channel_name,
            "title": (title or "")[:500], "desc": (description or "")[:2000],
            "pub": _parse_publish_date(publish_str),
            "pcount": prediction_count, "pv": PIPELINE_VERSION,
            "ts": transcript_status, "tc": transcript_chars,
        })
    except Exception as e:
        print(f"[YT-Backfill] _record_processed_video error: {e}")
        db.rollback()


def _parse_publish_date(s: str):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None
