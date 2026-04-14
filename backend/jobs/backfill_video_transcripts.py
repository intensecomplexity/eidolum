"""
One-shot backfill: capture video transcripts for YouTube predictions
that were scraped before the evidence-preservation system existed.

Usage (from the backend/ directory):
    python -m jobs.backfill_video_transcripts                  # dry run (default)
    python -m jobs.backfill_video_transcripts --apply          # write to DB
    python -m jobs.backfill_video_transcripts --apply --limit 10
    python -m jobs.backfill_video_transcripts --apply --resume
    python -m jobs.backfill_video_transcripts --apply --delay 5

Pipeline per video:
  1. Fetch the json3 transcript with word-level timing (30s timeout).
  2. Store in video_transcripts with SHA256 hash locked at capture time.
  3. UPDATE predictions.transcript_video_id = video_id for all
     predictions from that video (back-fills the FK link).
  4. Any failure → log, skip, move on.

Processes videos that don't have a transcript stored yet. Idempotent:
ON CONFLICT DO NOTHING on the video_transcripts insert means re-running
doesn't overwrite earlier captures.
"""
import argparse
import json
import os
import sys
import threading
import time


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text
from database import BgSessionLocal


TAG = "[yt-transcript-backfill]"

_YT_VIDEO_ID_LEN = 11
TRANSCRIPT_FETCH_DELAY = 2.0
TRANSCRIPT_TIMEOUT = 30

_PROGRESS_FILE = os.path.join(
    os.path.dirname(__file__), ".backfill_transcripts_progress.json"
)


class FuturesTimeout(Exception):
    pass


def _run_with_timeout(fn, *args, timeout_sec=None, **kwargs):
    """Daemon-thread-based wall-clock timeout. Same pattern as
    backfill_youtube_timestamps.py — ThreadPoolExecutor doesn't work
    here because its __exit__ blocks on shutdown(wait=True)."""
    result = [None]
    exc = [None]

    def _target():
        try:
            result[0] = fn(*args, **kwargs)
        except BaseException as e:
            exc[0] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        raise FuturesTimeout(f"{fn.__name__} did not complete within {timeout_sec}s")
    if exc[0] is not None:
        raise exc[0]
    return result[0]


def _fetch_with_timeout(video_id, timeout_sec=TRANSCRIPT_TIMEOUT):
    from jobs.youtube_classifier import fetch_transcript_with_timestamps
    return _run_with_timeout(
        fetch_transcript_with_timestamps, video_id, timeout_sec=timeout_sec,
    )


def _extract_video_id(source_platform_id: str) -> str | None:
    if not source_platform_id or not source_platform_id.startswith("yt_"):
        return None
    candidate = source_platform_id[3:3 + _YT_VIDEO_ID_LEN]
    if len(candidate) != _YT_VIDEO_ID_LEN:
        return None
    return candidate


def _save_progress(index: int):
    try:
        with open(_PROGRESS_FILE, "w") as f:
            json.dump({"last_completed_index": index}, f)
    except Exception:
        pass


def _load_progress() -> int:
    try:
        with open(_PROGRESS_FILE) as f:
            return json.load(f).get("last_completed_index", -1)
    except Exception:
        return -1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Backfill video_transcripts for existing YouTube predictions.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually write to DB.")
    parser.add_argument("--limit", type=int, default=0, help="Process only N videos.")
    parser.add_argument("--skip-to", type=int, default=0, help="Skip first N videos.")
    parser.add_argument("--resume", action="store_true", help="Resume from progress file.")
    parser.add_argument("--delay", type=float, default=0, help="Seconds between fetches.")
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{TAG} Starting video transcript backfill ({mode})", flush=True)

    skip_to = args.skip_to
    if args.resume:
        saved = _load_progress()
        if saved >= 0:
            skip_to = saved + 1
            print(f"{TAG} Resuming: skip to video index {skip_to}", flush=True)

    if skip_to:
        print(f"{TAG} Skipping first {skip_to} videos", flush=True)

    fetch_delay = args.delay if args.delay > 0 else TRANSCRIPT_FETCH_DELAY

    db = BgSessionLocal()
    try:
        # Disable statement timeout for the whole session (slow WAN UPDATEs).
        try:
            db.execute(sql_text("SET statement_timeout = 0"))
            db.commit()
        except Exception:
            pass
        return _run(db, apply=args.apply, limit=args.limit,
                    skip_to=skip_to, fetch_delay=fetch_delay)
    finally:
        db.close()


def _run(db, *, apply, limit, skip_to, fetch_delay):
    from jobs.video_transcript_store import ensure_video_transcripts_table, capture_transcript
    ensure_video_transcripts_table(db)

    # Find distinct video_ids from YouTube predictions that don't yet
    # have a transcript stored.
    rows = db.execute(sql_text("""
        SELECT DISTINCT SUBSTRING(p.source_platform_id FROM 4 FOR 11) as vid
        FROM predictions p
        WHERE p.verified_by = 'youtube_haiku_v1'
          AND p.source_platform_id IS NOT NULL
          AND SUBSTRING(p.source_platform_id FROM 4 FOR 11) NOT IN (
              SELECT video_id FROM video_transcripts
          )
        ORDER BY vid
    """)).fetchall()

    video_ids = [r[0] for r in rows if r[0] and len(r[0]) == 11]
    total = len(video_ids)
    print(f"{TAG} Candidates: {total} videos needing transcript capture", flush=True)

    if total == 0:
        print(f"{TAG} Nothing to do.", flush=True)
        return 0

    if limit:
        video_ids = video_ids[:skip_to + limit]

    stats = {
        "fetched": 0, "stored": 0, "already": 0, "failed": 0, "timed_out": 0,
    }

    for vid_idx, video_id in enumerate(video_ids):
        if vid_idx < skip_to:
            continue

        print(f"\n{TAG} [{vid_idx}/{len(video_ids)}] video={video_id}", flush=True)

        if vid_idx > skip_to:
            time.sleep(fetch_delay)

        try:
            transcript_data = _fetch_with_timeout(video_id, timeout_sec=TRANSCRIPT_TIMEOUT)
        except FuturesTimeout:
            print(f"{TAG}   TIMEOUT ({TRANSCRIPT_TIMEOUT}s), skipping", flush=True)
            stats["timed_out"] += 1
            _save_progress(vid_idx)
            continue
        except Exception as e:
            print(f"{TAG}   fetch error: {type(e).__name__}: {str(e)[:120]}", flush=True)
            stats["failed"] += 1
            _save_progress(vid_idx)
            continue

        status = transcript_data.get("status", "unknown")
        text = transcript_data.get("text", "")
        if status != "ok" or not text:
            print(f"{TAG}   transcript status={status}, skipping", flush=True)
            stats["failed"] += 1
            _save_progress(vid_idx)
            continue

        stats["fetched"] += 1

        if not apply:
            print(f"{TAG}   DRY RUN: would store {len(text)} chars", flush=True)
            _save_progress(vid_idx)
            continue

        # Look up channel/title/publish_date from any prediction on this
        # video. Wrapped in try/except because the LIKE 'yt_{vid}_%' scan
        # can trip the 30s statement_timeout on slow WAN connections; a
        # single metadata lookup failure must not kill the whole run.
        channel_name = None
        video_title = None
        publish_date = None
        try:
            db.execute(sql_text("SET LOCAL statement_timeout = 0"))
            meta = db.execute(sql_text("""
                SELECT f.name, p.source_title, p.prediction_date
                FROM predictions p
                JOIN forecasters f ON f.id = p.forecaster_id
                WHERE p.source_platform_id LIKE :prefix
                LIMIT 1
            """), {"prefix": f"yt_{video_id}_%"}).first()
            if meta:
                channel_name, video_title, publish_date = meta[0], meta[1], meta[2]
            db.commit()
        except Exception as _e:
            print(f"{TAG}   metadata lookup failed (proceeding with NULLs): "
                  f"{type(_e).__name__}: {str(_e)[:120]}", flush=True)
            try:
                db.rollback()
            except Exception:
                pass

        ok = False
        try:
            ok = capture_transcript(
                db,
                video_id=video_id,
                channel_name=channel_name,
                video_title=video_title,
                video_publish_date=publish_date,
                transcript_text=text,
                transcript_format="json3",
            )
        except Exception as _e:
            print(f"{TAG}   capture_transcript raised: {_e}", flush=True)
            try:
                db.rollback()
            except Exception:
                pass

        if ok:
            stats["stored"] += 1
            print(f"{TAG}   stored ({len(text)} chars)", flush=True)
        else:
            stats["already"] += 1
            print(f"{TAG}   already present or store failed (no-op)", flush=True)

        # Back-fill the FK on all predictions from this video.
        try:
            db.execute(sql_text("SET LOCAL statement_timeout = 0"))
            db.execute(sql_text("""
                UPDATE predictions
                SET transcript_video_id = :vid
                WHERE source_platform_id LIKE :prefix
                  AND transcript_video_id IS NULL
            """), {"vid": video_id, "prefix": f"yt_{video_id}_%"})
            db.commit()
        except Exception as _e:
            print(f"{TAG}   FK backfill failed: "
                  f"{type(_e).__name__}: {str(_e)[:120]}", flush=True)
            try:
                db.rollback()
            except Exception:
                pass

        _save_progress(vid_idx)

    print(f"\n{TAG} ── Summary ──", flush=True)
    print(f"{TAG}   Fetched:      {stats['fetched']}", flush=True)
    print(f"{TAG}   Stored:       {stats['stored']}", flush=True)
    print(f"{TAG}   Already had:  {stats['already']}", flush=True)
    print(f"{TAG}   Failed:       {stats['failed']}", flush=True)
    print(f"{TAG}   Timed out:    {stats['timed_out']}", flush=True)

    if not apply:
        print(f"\n{TAG} DRY RUN — no DB writes. Pass --apply to commit.", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
