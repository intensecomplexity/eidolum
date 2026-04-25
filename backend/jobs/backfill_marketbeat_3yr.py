"""3-year YouTube backfill for MarketBeat (@marketbeatmedia).

Pulls the channel's full uploads playlist back to the configured cutoff,
filters out shorts and videos already in youtube_videos, then routes each
remaining video through the same _process_one_video helper used by the
live channel monitor. Reuses the existing shorts filter (videos.list
duration check >= 180s), transcript fetcher (with Webshare proxy and
language gate), and Qwen classifier path.

Channel resolution is bypassed: channel_id is hardcoded to the verified
@marketbeatmedia ID so we don't depend on the resolver picking the right
channel from the search.list ranking (there are at least two YouTube
channels titled "MarketBeat").

Idempotent: youtube_videos rows from prior runs are filtered out before
any classifier work, so a second invocation picks up where the first
stopped without re-processing already-classified videos.

Usage (from backend/):
    python -m jobs.backfill_marketbeat_3yr --dry-run
    python -m jobs.backfill_marketbeat_3yr --batch-size 25
    python -m jobs.backfill_marketbeat_3yr --since 2024-01-01 --rate-limit-sleep 1.5

Flags:
    --dry-run             Enumerate, dedup, duration-filter; print
                          counts + estimates; NO transcript fetches,
                          NO Qwen calls, NO DB writes.
    --since YYYY-MM-DD    Cutoff publishedAt (default 2023-04-25,
                          three years before the script's reference date).
    --batch-size N        Progress print + (future) checkpoint cadence
                          (default 25).
    --rate-limit-sleep S  Seconds between Qwen calls; Pavilion is one
                          GPU, queue-bombing it serializes anyway and
                          spikes p99 latency for the live cycle
                          (default 1.0).
    --limit N             Cap total videos processed (debug).
"""
import argparse
import os
import sys
import time
from datetime import datetime

import httpx
from sqlalchemy import text as sql_text

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import BgSessionLocal
from jobs.youtube_channel_monitor import (
    YOUTUBE_API,
    YOUTUBE_API_KEY,
    YOUTUBE_MIN_DURATION_SECONDS,
    _fetch_video_durations,
    _process_one_video,
)

CHANNEL_NAME = "MarketBeat"
CHANNEL_ID = "UCDMRj2UMCY4Jp49Waf_2X9g"
UPLOADS_PLAYLIST = "UU" + CHANNEL_ID[2:]  # = UUDMRj2UMCY4Jp49Waf_2X9g
DEFAULT_SINCE = "2023-04-25"

# Estimates for --dry-run reporting. Sourced from production telemetry:
# - QWEN_PRICE_PER_CALL_USD = 0.0012 in youtube_classifier.py
# - QWEN_AVG_LATENCY_S: rolling median over the last 30 days of
#   [YOUTUBE-QWEN] log lines is ~6.5s per chunk
# - AVG_TRANSCRIPT_CHARS_HEURISTIC: median transcript_chars across all
#   youtube_videos with transcript_status='ok_inserted' or
#   'ok_no_predictions' is ~14k; rounded to 12k as a conservative
#   under-estimate so cost projections don't undershoot
QWEN_COST_PER_CALL = 0.0012
QWEN_AVG_LATENCY_S = 6.5
AVG_TRANSCRIPT_CHARS_HEURISTIC = 12_000
# Long transcripts get chunked at TRANSCRIPT_CHUNK_THRESHOLD = 100_000
# chars in youtube_classifier.py; assume <5% of MarketBeat videos exceed
# that, so cost = videos * 1 chunk on average
AVG_CHUNKS_PER_VIDEO = 1.05


def enumerate_uploads(since_iso: str) -> tuple[list[dict], int]:
    """Paginate through the uploads playlist, yielding every video with
    publishedAt >= since_iso. Returns (videos, api_units_used).

    Each page is one playlistItems.list call (1 quota unit) returning up
    to 50 items. We page until either an item older than `since_iso` is
    seen (ordered newest-first by upload date) or the playlist is
    exhausted.
    """
    if not YOUTUBE_API_KEY:
        print("[BackfillMB] YOUTUBE_API_KEY not set; aborting", flush=True)
        return [], 0

    out: list[dict] = []
    page_token: str | None = None
    api_units = 0
    pages = 0
    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": UPLOADS_PLAYLIST,
            "maxResults": 50,
            "key": YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            r = httpx.get(f"{YOUTUBE_API}/playlistItems", params=params, timeout=15)
        except Exception as e:
            print(f"[BackfillMB] playlistItems exception page={pages}: {e}", flush=True)
            break
        api_units += 1
        pages += 1
        if r.status_code != 200:
            print(
                f"[BackfillMB] playlistItems HTTP {r.status_code} page={pages}: "
                f"{r.text[:200]}",
                flush=True,
            )
            break
        body = r.json()
        items = body.get("items", [])
        if not items:
            break

        oldest_in_page = None
        for it in items:
            sn = it.get("snippet") or {}
            cd = it.get("contentDetails") or {}
            published = sn.get("publishedAt") or cd.get("videoPublishedAt")
            video_id = (cd.get("videoId")
                        or (sn.get("resourceId") or {}).get("videoId"))
            title = sn.get("title") or ""
            if not video_id or not published:
                continue
            oldest_in_page = published
            if published < since_iso:
                continue
            out.append({
                "video_id": video_id,
                "title": title,
                "published_at": published,
            })

        page_token = body.get("nextPageToken")
        if not page_token:
            break
        # Once we've paged into entries older than the cutoff, stop —
        # playlist is upload-date-ordered newest-first.
        if oldest_in_page and oldest_in_page < since_iso:
            break

    return out, api_units


def filter_already_processed(db, video_ids: list[str]) -> set[str]:
    """Return the subset of video_ids that already have rows in
    youtube_videos. Used to dedup before running expensive work.
    """
    if not video_ids:
        return set()
    rows = db.execute(
        sql_text(
            "SELECT youtube_video_id FROM youtube_videos "
            "WHERE youtube_video_id = ANY(:ids)"
        ),
        {"ids": video_ids},
    ).fetchall()
    return {r[0] for r in rows}


def filter_shorts(video_ids: list[str]) -> tuple[set[str], int]:
    """Batch-fetch durations and return (kept_ids, api_units). Videos
    with 0 < duration < YOUTUBE_MIN_DURATION_SECONDS are dropped.
    Videos with unknown duration (videos.list miss) are kept — same
    behavior as the live cycle.
    """
    kept: set[str] = set()
    api_units = 0
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        durations = _fetch_video_durations(batch)
        api_units += 1
        for vid in batch:
            dur = durations.get(vid, 0)
            if 0 < dur < YOUTUBE_MIN_DURATION_SECONDS:
                continue
            kept.add(vid)
    return kept, api_units


def run(args: argparse.Namespace) -> int:
    started_at = time.time()
    print(
        f"[BackfillMB] channel={CHANNEL_NAME} ({CHANNEL_ID}) "
        f"since={args.since} dry_run={args.dry_run} "
        f"batch_size={args.batch_size} rate_limit_sleep={args.rate_limit_sleep}s",
        flush=True,
    )

    print("[BackfillMB] enumerating uploads playlist...", flush=True)
    videos, enum_units = enumerate_uploads(args.since)
    if args.limit:
        videos = videos[:args.limit]
    print(
        f"[BackfillMB] enumerated {len(videos)} videos with publishedAt >= "
        f"{args.since} ({enum_units} playlistItems API units)",
        flush=True,
    )
    if not videos:
        print("[BackfillMB] nothing to do", flush=True)
        return 0

    db = BgSessionLocal()
    try:
        all_ids = [v["video_id"] for v in videos]
        already_done = filter_already_processed(db, all_ids)
        net_new_ids = [vid for vid in all_ids if vid not in already_done]
        print(
            f"[BackfillMB] dedup: {len(already_done)} already in youtube_videos, "
            f"{len(net_new_ids)} candidates remain",
            flush=True,
        )

        if not net_new_ids:
            print("[BackfillMB] all candidates already processed; done", flush=True)
            return 0

        print("[BackfillMB] fetching durations to filter shorts...", flush=True)
        kept_ids, dur_units = filter_shorts(net_new_ids)
        shorts_filtered = len(net_new_ids) - len(kept_ids)
        print(
            f"[BackfillMB] {shorts_filtered} videos dropped as shorts (<{YOUTUBE_MIN_DURATION_SECONDS}s); "
            f"{len(kept_ids)} kept ({dur_units} videos.list API units)",
            flush=True,
        )

        kept_videos = [v for v in videos if v["video_id"] in kept_ids]

        if args.dry_run:
            n = len(kept_videos)
            est_chars = n * AVG_TRANSCRIPT_CHARS_HEURISTIC
            est_chunks = n * AVG_CHUNKS_PER_VIDEO
            est_cost_usd = est_chunks * QWEN_COST_PER_CALL
            est_qwen_secs = est_chunks * QWEN_AVG_LATENCY_S
            est_sleep_secs = n * args.rate_limit_sleep
            est_runtime_secs = est_qwen_secs + est_sleep_secs
            print()
            print("=" * 60)
            print("DRY-RUN ESTIMATES")
            print("=" * 60)
            print(f"  Videos to classify:        {n:>8}")
            print(f"  Est transcript chars:      {est_chars:>12,} ({AVG_TRANSCRIPT_CHARS_HEURISTIC:,} per video heuristic)")
            print(f"  Est Qwen calls (chunked):  {est_chunks:>10,.0f}")
            print(f"  Est Qwen cost:             ${est_cost_usd:>9,.2f} (@ ${QWEN_COST_PER_CALL}/call)")
            print(f"  Est Qwen wall time:        {est_qwen_secs:>8,.0f}s ({est_qwen_secs/60:.1f} min)")
            print(f"  Est rate-limit sleep:      {est_sleep_secs:>8,.0f}s")
            print(f"  Est total runtime:         {est_runtime_secs:>8,.0f}s ({est_runtime_secs/3600:.2f} h)")
            print()
            print(f"  YouTube API units used:    {enum_units + dur_units:>8} (read-only)")
            print(f"  Elapsed enumeration:       {time.time() - started_at:>8.1f}s")
            print("=" * 60)
            print("Re-run without --dry-run to begin classification.")
            print("Recommended: settle the multi-prediction truncation question first;")
            print("a backfill done now captures 1 prediction/video and would need")
            print("full re-processing post-fix.")
            print("=" * 60)
            return 0

        # ── Wet run ─────────────────────────────────────────────────────
        # Canonical counter set — must match the live-cycle stats dict in
        # youtube_channel_monitor.py:894-998 so _process_one_video and the
        # insert_*_prediction helpers can increment any counter without
        # raising KeyError. The previous short list missed
        # 'predictions_inserted' (incremented on every successful insert),
        # which silently lost predictions on videos that classified to
        # >= 1 row — the script's outer try/except swallowed the KeyError.
        stats: dict = {
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
            "items_rejected": 0,
            "items_deduped": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_create_tokens": 0,
            "total_cache_read_tokens": 0,
            "estimated_cost_usd": 0.0,
            "haiku_retries_count": 0,
            "sector_calls_extracted": 0,
            "options_positions_extracted": 0,
            "earnings_calls_extracted": 0,
            "macro_calls_extracted": 0,
            "pair_calls_extracted": 0,
            "binary_events_extracted": 0,
            "metric_forecasts_extracted": 0,
            "conditional_calls_extracted": 0,
            "disclosures_extracted": 0,
            "timestamps_matched": 0,
            "timestamps_failed": 0,
            "regime_calls_extracted": 0,
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

        n_total = len(kept_videos)
        n_inserted = 0
        n_done = 0
        for v in kept_videos:
            video_id = v["video_id"]
            title = v["title"]
            publish_iso = v["published_at"]
            try:
                inserted, _chars, _status = _process_one_video(
                    db, CHANNEL_NAME, CHANNEL_ID, video_id, title, publish_iso, stats,
                )
                n_inserted += inserted
            except Exception as e:
                print(
                    f"[BackfillMB] _process_one_video raised for {video_id}: "
                    f"{type(e).__name__}: {str(e)[:200]}",
                    flush=True,
                )
            n_done += 1
            if n_done % args.batch_size == 0:
                elapsed = time.time() - started_at
                rate = n_done / elapsed if elapsed > 0 else 0.0
                print(
                    f"[BackfillMB] progress: {n_done}/{n_total} processed "
                    f"({n_inserted} preds inserted, {stats['classifier_errors']} "
                    f"classifier errors, ${stats['estimated_cost_usd']:.2f} spent, "
                    f"{rate:.2f} vid/s, "
                    f"eta {(n_total - n_done) / max(rate, 1e-9):.0f}s)",
                    flush=True,
                )
            if args.rate_limit_sleep > 0 and n_done < n_total:
                time.sleep(args.rate_limit_sleep)

        elapsed = time.time() - started_at
        print()
        print("=" * 60)
        print(f"BACKFILL COMPLETE — channel={CHANNEL_NAME}")
        print(f"  Processed:               {n_done}/{n_total}")
        print(f"  Predictions inserted:    {n_inserted}")
        print(f"  Classifier errors:       {stats['classifier_errors']}")
        print(f"  No-transcript skips:     {stats['videos_skipped_no_transcript']}")
        print(f"  Total Qwen cost:         ${stats['estimated_cost_usd']:.2f}")
        print(f"  Wall time:               {elapsed:.0f}s ({elapsed/3600:.2f} h)")
        print("=" * 60)
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Enumerate + dedup + duration-filter only; print estimates")
    ap.add_argument("--since", default=DEFAULT_SINCE,
                    help=f"Cutoff publishedAt YYYY-MM-DD (default {DEFAULT_SINCE})")
    ap.add_argument("--batch-size", type=int, default=25,
                    help="Progress print cadence (default 25)")
    ap.add_argument("--rate-limit-sleep", type=float, default=1.0,
                    help="Seconds between classify_video calls (default 1.0)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap total videos processed (debug; 0 = no cap)")
    args = ap.parse_args()

    try:
        datetime.strptime(args.since, "%Y-%m-%d")
    except ValueError:
        print(f"[BackfillMB] --since must be YYYY-MM-DD, got {args.since!r}",
              flush=True)
        return 2

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
