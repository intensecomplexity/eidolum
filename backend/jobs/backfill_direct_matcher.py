"""
Direct matcher backfill — resolves source_timestamp_seconds for YouTube
predictions that ALREADY have a source_verbatim_quote in the DB but no
timestamp, by skipping the Haiku quote-extraction step entirely and
feeding the existing quote directly to the fuzzy matcher.

Usage (from backend/):
    python -m jobs.backfill_direct_matcher              # dry run
    python -m jobs.backfill_direct_matcher --apply      # write to DB
    python -m jobs.backfill_direct_matcher --apply --limit 10
    python -m jobs.backfill_direct_matcher --apply --delay 2

Why this script exists (context for future readers):

backfill_youtube_timestamps.py (the original ship #9 backfill) ALWAYS
re-asks Haiku to extract a verbatim quote from the transcript for each
prediction, even when the prediction already has source_verbatim_quote
set in the database. On legacy data, Haiku's second-pass quote
extraction fails ~95% of the time — most predictions get skipped with
"Haiku returned no quote" before the matcher ever runs. That's a lot
of API spend on rows that can't be rescued by that pipeline.

This script targets the subset of predictions where the ORIGINAL
classifier DID extract a verbatim quote but the ORIGINAL matcher
couldn't place it in the transcript (ie Mode B failures: has quote,
no timestamp). For those rows we already know exactly what to search
for — just fetch the transcript and run match_quote_to_timestamp on
the existing quote with the new fuzzy fallback paths. Zero Haiku
calls, zero API cost, no dependency on ANTHROPIC_API_KEY. Only needs
DATABASE_URL and WEBSHARE_PROXY_* (for the residential-proxy
transcript fetch).

Runs safely in parallel with backfill_youtube_timestamps.py — the
candidate SELECT filters source_timestamp_seconds IS NULL, so any
row the other backfill resolves first simply drops out of the
candidate set on the next SELECT and won't be re-processed.
"""
import argparse
import os
import sys
import threading
import time

from collections import OrderedDict


class FuturesTimeout(Exception):
    """Raised by _run_with_timeout when the wrapped call exceeds timeout_sec."""
    pass


# Allow running as `python -m jobs.backfill_direct_matcher` from backend/.
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text
from database import BgSessionLocal


# ── Constants ─────────────────────────────────────────────────────────────────

TAG = "[direct-matcher]"

# YouTube video IDs are always exactly 11 characters (base64url).
_YT_VIDEO_ID_LEN = 11

# Default delay between transcript fetches (seconds).
DEFAULT_DELAY = 1.0

# Transcript fetch timeout (seconds). Kills hung proxy connections the same
# way backfill_youtube_timestamps.py does.
TRANSCRIPT_TIMEOUT = 30


# ── Timeout helper ───────────────────────────────────────────────────────────
#
# Mirror of backfill_youtube_timestamps.py's _run_with_timeout: daemon thread
# with t.join(timeout). Soft timeout — the worker thread leaks on timeout but
# control reliably returns to the main thread, which is what we care about.

def _run_with_timeout(fn, *args, timeout_sec=None, **kwargs):
    """Run fn(*args, **kwargs) with a hard wall-clock timeout.
    Returns the result on success, raises FuturesTimeout on timeout,
    or re-raises any exception thrown by fn."""
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


def _fetch_with_timeout(video_id, timeout_sec=None):
    """Wrapper around fetch_transcript_with_timestamps with a wall-clock
    timeout. Import is lazy so the sys.path shim above has time to apply."""
    from jobs.youtube_classifier import fetch_transcript_with_timestamps
    return _run_with_timeout(
        fetch_transcript_with_timestamps, video_id,
        timeout_sec=timeout_sec or TRANSCRIPT_TIMEOUT,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_video_id(source_platform_id: str) -> str | None:
    """Extract the 11-char YouTube video ID from any source_platform_id
    format. All formats start with 'yt_' followed by the 11-char ID."""
    if not source_platform_id or not source_platform_id.startswith("yt_"):
        return None
    candidate = source_platform_id[3:3 + _YT_VIDEO_ID_LEN]
    if len(candidate) != _YT_VIDEO_ID_LEN:
        return None
    return candidate


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Direct-matcher backfill for YouTube predictions "
                    "that already have a source_verbatim_quote.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write to DB. Default is dry-run.",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Process only the first N unique videos (0 = all).",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help="Seconds between consecutive transcript fetches (default 1).",
    )
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{TAG} Starting direct-matcher backfill ({mode})", flush=True)
    if args.limit:
        print(f"{TAG} Video limit: {args.limit}", flush=True)

    db = BgSessionLocal()
    try:
        return _run(
            db, apply=args.apply, limit=args.limit, delay=args.delay,
        )
    finally:
        db.close()


def _run(db, *, apply: bool, limit: int, delay: float) -> int:
    # Disable statement timeout for this long-running session.
    # BgSessionLocal's on-connect hook sets it to 30s which trips on
    # slow WAN UPDATE round-trips from WSL to Railway. We don't need
    # the safety rail here — the loop handles row-level failures
    # gracefully and each UPDATE targets a single row by PK.
    try:
        db.execute(sql_text("SET statement_timeout = 0"))
        db.commit()
    except Exception as _e:
        print(f"{TAG} WARNING: could not disable statement_timeout: {_e}", flush=True)

    # ── 1. Query candidates ───────────────────────────────────────────────
    # Rows with a verbatim quote already in the DB but no resolved
    # timestamp. length > 10 filters out trivial / empty strings that
    # would obviously fail the matcher anyway.
    rows = db.execute(sql_text("""
        SELECT id, source_platform_id, source_verbatim_quote, ticker,
               prediction_date
        FROM predictions
        WHERE verified_by = 'youtube_haiku_v1'
          AND excluded_from_training = FALSE
          AND source_verbatim_quote IS NOT NULL
          AND length(source_verbatim_quote) > 10
          AND source_timestamp_seconds IS NULL
          AND source_platform_id IS NOT NULL
        ORDER BY source_platform_id, id
    """)).fetchall()

    if not rows:
        print(f"{TAG} No candidates found. Nothing to do.")
        return 0

    # Group by video_id so we fetch each transcript at most once.
    video_groups: OrderedDict[str, list] = OrderedDict()
    skipped_bad_id = 0
    for r in rows:
        vid = _extract_video_id(r.source_platform_id)
        if not vid:
            skipped_bad_id += 1
            continue
        video_groups.setdefault(vid, []).append(r)

    total_preds = sum(len(preds) for preds in video_groups.values())
    total_videos = len(video_groups)
    print(
        f"{TAG} Candidates: {total_preds} predictions across "
        f"{total_videos} unique videos",
        flush=True,
    )
    if skipped_bad_id:
        print(
            f"{TAG} Skipped {skipped_bad_id} rows with unparseable "
            f"source_platform_id",
            flush=True,
        )

    # Lazy import — keeps module-load-time lean and lets the sys.path
    # shim above apply before we touch jobs.* modules.
    from jobs.timestamp_matcher import match_quote_to_timestamp

    stats: dict = {
        "videos_processed": 0,
        "videos_skipped_no_transcript": 0,
        "videos_timed_out": 0,
        "resolved": 0,
        "failed": 0,
        "written": 0,
        "methods": {},
    }

    videos_to_process = list(video_groups.items())
    if limit:
        videos_to_process = videos_to_process[:limit]

    for vid_idx, (video_id, preds) in enumerate(videos_to_process):
        print(
            f"\n{TAG} [{vid_idx}/{len(videos_to_process)}] "
            f"video={video_id} predictions={len(preds)}",
            flush=True,
        )

        # Rate-limit between videos. Skip the delay on the first one so
        # --limit 1 runs don't sit idle.
        if vid_idx > 0:
            time.sleep(delay)

        # Fetch transcript with word-level timing (same entry point as
        # the original backfill). Wall-clock bounded so a hung proxy
        # can't stall the loop.
        try:
            transcript_data = _fetch_with_timeout(
                video_id, timeout_sec=TRANSCRIPT_TIMEOUT,
            )
        except FuturesTimeout:
            print(
                f"{TAG}   Transcript TIMEOUT ({TRANSCRIPT_TIMEOUT}s). "
                f"Skipping {len(preds)} predictions.",
                flush=True,
            )
            stats["videos_timed_out"] += 1
            stats["failed"] += len(preds)
            continue
        except Exception as e:
            print(
                f"{TAG}   Transcript error: {type(e).__name__}: {e}. "
                f"Skipping.",
                flush=True,
            )
            stats["videos_skipped_no_transcript"] += 1
            stats["failed"] += len(preds)
            continue

        status = transcript_data.get("status", "unknown")
        text = transcript_data.get("text", "")
        if status != "ok" or not text:
            print(
                f"{TAG}   Transcript failed: status={status}. "
                f"Skipping {len(preds)} predictions.",
                flush=True,
            )
            stats["videos_skipped_no_transcript"] += 1
            stats["failed"] += len(preds)
            continue

        has_words = transcript_data.get("has_word_level", False)
        seg_count = len(transcript_data.get("segments", []))
        print(
            f"{TAG}   Transcript OK: {len(text)} chars, {seg_count} "
            f"segments, word_level={'yes' if has_words else 'no'}",
            flush=True,
        )

        # Evidence preservation (ship #13) — idempotent via ON CONFLICT
        # DO NOTHING inside capture_transcript. Uses the first prediction
        # in the group for publish_date metadata since they're all from
        # the same video.
        try:
            from jobs.video_transcript_store import capture_transcript
            first = preds[0]
            capture_transcript(
                db,
                video_id=video_id,
                channel_name=None,
                video_title=None,
                video_publish_date=getattr(first, "prediction_date", None),
                transcript_text=text,
                transcript_format="json3",
            )
        except Exception as _e:
            print(f"{TAG}   transcript capture failed: {_e}", flush=True)

        stats["videos_processed"] += 1

        updates_this_video = []
        for pred in preds:
            pid = pred.id
            ticker = pred.ticker or "?"
            quote = pred.source_verbatim_quote or ""
            if len(quote) < 10:
                # Defensive — SELECT already filters these but belt-and-
                # braces so a race with the original backfill can't feed
                # us an empty string mid-run.
                stats["failed"] += 1
                print(
                    f"{TAG}   id={pid:>7d} {ticker:>6s} quote too short, skipping",
                    flush=True,
                )
                continue

            # Run matcher with the existing DB quote. enable_two_pass=False
            # keeps this script strictly API-free — the new fuzzy fallback
            # paths (normalized_overlap, segment_overlap, normalized_fuzzy,
            # key_phrase_anchor) are all stdlib so no ANTHROPIC_API_KEY is
            # required.
            try:
                seconds, method, confidence = match_quote_to_timestamp(
                    quote, transcript_data, enable_two_pass=False,
                )
            except Exception as e:
                print(
                    f"{TAG}   id={pid:>7d} {ticker:>6s} matcher error: "
                    f"{type(e).__name__}: {str(e)[:150]}",
                    flush=True,
                )
                stats["failed"] += 1
                continue

            if seconds is None:
                stats["failed"] += 1
                print(
                    f"{TAG}   id={pid:>7d} {ticker:>6s} no match",
                    flush=True,
                )
                continue

            stats["resolved"] += 1
            stats["methods"][method] = stats["methods"].get(method, 0) + 1
            updates_this_video.append({
                "id": pid,
                "seconds": int(seconds),
                "method": method,
                "confidence": float(confidence),
                "tvid": video_id[:11],
            })
            print(
                f"{TAG}   id={pid:>7d} {ticker:>6s} resolved  "
                f"method={method}  conf={confidence:.2f}  t={seconds}s",
                flush=True,
            )

        # ── Commit after each video (incremental progress) ────────
        # Does NOT touch source_verbatim_quote — the existing DB value
        # is exactly what we searched for, so re-writing it would be a
        # no-op at best and an accidental corruption at worst.
        if apply and updates_this_video:
            written_this_video = 0
            for u in updates_this_video:
                try:
                    db.execute(sql_text("""
                        UPDATE predictions SET
                            source_timestamp_seconds = :seconds,
                            source_timestamp_method  = :method,
                            source_timestamp_confidence = :confidence,
                            transcript_video_id      = :tvid
                        WHERE id = :id
                          AND source_timestamp_seconds IS NULL
                    """), u)
                    db.commit()
                    written_this_video += 1
                except Exception as _uerr:
                    # Statement timeout, connection drop, deadlock, etc.
                    # Rollback and continue — one failed UPDATE must not
                    # kill the whole backfill. The row stays NULL and
                    # will be re-picked up on the next run.
                    print(
                        f"{TAG}   UPDATE failed for id={u.get('id')}: "
                        f"{type(_uerr).__name__}: {str(_uerr)[:150]}",
                        flush=True,
                    )
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    stats["failed"] += 1
                    stats["resolved"] -= 1  # undo the earlier increment
            stats["written"] += written_this_video
            if written_this_video:
                print(
                    f"{TAG}   Committed {written_this_video} updates "
                    f"(total written: {stats['written']})",
                    flush=True,
                )

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{TAG} ── Summary ──")
    print(f"{TAG}   Videos processed:     {stats['videos_processed']}")
    print(f"{TAG}   Videos no transcript: {stats['videos_skipped_no_transcript']}")
    print(f"{TAG}   Videos timed out:     {stats['videos_timed_out']}")
    print(f"{TAG}   Resolved:             {stats['resolved']}")
    print(f"{TAG}   Failed (no match):    {stats['failed']}")
    print(f"{TAG}   Total written to DB:  {stats['written']}")
    print(f"{TAG}   Methods:              {stats['methods']}")

    if not apply:
        print(f"\n{TAG} DRY RUN — no DB writes. Pass --apply to commit.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
