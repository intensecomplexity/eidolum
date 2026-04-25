"""Re-classify YouTube videos the Pavilion classifier never finished.

A row "needs re-classification" iff:
  1. it exists in youtube_videos (transcript was fetchable, video crawled)
  2. no row in predictions points at it (no successful classification)
  3. no row in youtube_scraper_rejections has a TERMINAL rejection_reason
     for it — i.e. the classifier got a clean shot and emitted nothing
     or nothing-valid.

Terminal reasons (excluded from candidate set):
  haiku_no_predictions         classifier said no predictions
  invalid_ticker               classifier output had invalid ticker
  missing_source_timestamp     classifier output missing timestamp field
  incomplete_training_fields   classifier output missing required field
  no_timeframe_determinable    classifier rejected itself (no timeframe)
  unresolvable_reference       classifier rejected itself (vague ref)
  shorts_skipped               pre-classifier filter (re-running won't help)
  no_transcript                pre-classifier filter (re-running mostly won't help)

Transient/infrastructure reasons (INCLUDED — classifier never got a real shot):
  classifier_error             Anthropic credit-balance blackout (Apr 19-25)
                               OR any post-PR#2 Qwen-side failure
  qwen_exception               Pavilion HTTP / parse error
  classifier_misconfigured     missing CLASSIFIER_BASE_URL / CF_ACCESS_*
  classifier_circuit_open      breaker tripped from prior failures
  (no rejection at all)        orphan video — never even logged

Routes each candidate through the live-cycle _process_one_video helper
— same shorts filter (won't trip on already-passed-shorts videos),
transcript fetcher (re-fetched from YouTube; transcripts are immutable
but the proxy may have been misbehaving on the original fetch), Qwen
classifier path, and prediction insert routing across all _kind
branches.

Idempotent against youtube_videos: re-runs filter out videos that were
successfully classified or terminally rejected on the prior run, so
interrupted runs auto-resume on re-launch.

Channel filter: only youtube_channels.is_active=TRUE channels are
considered. SMB Capital and any future sync-deactivated channels stay
excluded automatically.

Cost: $0/call marginal — the Pavilion GPU is sunk cost. The internal
telemetry continues to log $0.0012 per Qwen call for attribution
inside scraper_runs.estimated_cost_usd; that dollar value is not real
spend.

Usage (from backend/):
    python -m jobs.backfill_untouched_videos --dry-run
    python -m jobs.backfill_untouched_videos --batch-size 50
    python -m jobs.backfill_untouched_videos --channel "Heresy Financial"
    python -m jobs.backfill_untouched_videos --since 2026-04-19 --rate-limit-sleep 1.5

Flags:
    --dry-run             Report counts + breakdown by state + top
                          channels + est runtime; no Qwen calls, no
                          DB writes, no transcript fetches.
    --since YYYY-MM-DD    Optional: only consider videos with
                          youtube_videos.publish_date >= since
                          (default: no cutoff — entire history).
    --channel NAME        Process only one channel (debug).
    --batch-size N        Progress print cadence (default 25).
    --rate-limit-sleep S  Seconds between Qwen calls (default 1.0).
                          Pavilion is one GPU; share politely with
                          the live cycle (which fires hourly).
    --limit N             Cap total videos processed (debug; 0 = no
                          cap).
"""
import argparse
import os
import sys
import time
from collections import Counter
from datetime import datetime

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text

from database import BgSessionLocal
from jobs.youtube_channel_monitor import _process_one_video


# Rejection reasons that mark a video as terminally classified — i.e.
# Qwen got a clean look at the transcript and produced nothing usable.
# Re-classifying these would just re-produce the same verdict, so
# they're excluded from the candidate set.
TERMINAL_REJECTION_REASONS = (
    "haiku_no_predictions",
    "invalid_ticker",
    "missing_source_timestamp",
    "incomplete_training_fields",
    "no_timeframe_determinable",
    "unresolvable_reference",
    "shorts_skipped",
    "no_transcript",
)

# Some videos have a youtube_videos row with NO rejection log entry but a
# transcript_status that already encodes the terminal classifier verdict
# or a pre-classifier filter outcome. Drill-down on 2026-04-25 showed
# 8,782 of 14,074 such "never_classified" rows fall in this bucket
# (62.4%). Excluding them at SELECT time avoids re-classifying videos
# the classifier already finished cleanly. transcript_status values
# starting with "error" (e.g. "error: RetryError ... /sorry/index ...")
# are also pre-classifier transcript-fetch failures and excluded.
TERMINAL_TRANSCRIPT_STATUSES = (
    "ok_no_predictions",       # classifier ran, said no predictions
    "shorts_skipped",          # pre-classifier duration filter
    "no_transcript",           # pre-classifier transcript fetch failure
    "transcripts_disabled",    # YouTube disabled transcripts on the video
)


# Estimated per-call latency for runtime projection. Sourced from the
# rolling median of [YOUTUBE-QWEN] log latency lines over the last 30
# days. Update when the Pavilion GPU mix or model changes.
QWEN_AVG_LATENCY_S = 6.5


def _build_candidate_sql(*, since: str | None, channel: str | None,
                         limit: int) -> tuple[str, dict]:
    """Build the candidate-selection SQL + bind params.

    The state column tags each row's most recent state for the dry-run
    breakdown: 'never_classified' when no rejection log entry exists,
    otherwise the most recent rejection_reason for that video.
    """
    where_extra = []
    params: dict = {
        "terminal": list(TERMINAL_REJECTION_REASONS),
        "terminal_status": list(TERMINAL_TRANSCRIPT_STATUSES),
    }
    if since:
        where_extra.append("AND yv.publish_date >= :since_date")
        params["since_date"] = since
    if channel:
        where_extra.append("AND yv.channel_name = :channel_name")
        params["channel_name"] = channel
    if limit and limit > 0:
        params["row_limit"] = limit
        limit_clause = "LIMIT :row_limit"
    else:
        limit_clause = ""

    sql = f"""
        SELECT
            yv.youtube_video_id,
            yv.channel_name,
            yc.youtube_channel_id,
            yv.title,
            yv.publish_date,
            COALESCE(r.rejection_reason, 'never_classified') AS state
        FROM youtube_videos yv
        JOIN youtube_channels yc ON yc.channel_name = yv.channel_name
        LEFT JOIN LATERAL (
            SELECT rejection_reason
            FROM youtube_scraper_rejections
            WHERE video_id = yv.youtube_video_id
            ORDER BY rejected_at DESC
            LIMIT 1
        ) r ON TRUE
        WHERE yc.is_active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM predictions p
              WHERE p.transcript_video_id = yv.youtube_video_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM youtube_scraper_rejections rt
              WHERE rt.video_id = yv.youtube_video_id
                AND rt.rejection_reason = ANY(:terminal)
          )
          AND COALESCE(yv.transcript_status, '') <> ALL(:terminal_status)
          AND COALESCE(yv.transcript_status, '') NOT LIKE 'error:%'
          {chr(10).join(where_extra)}
        ORDER BY yv.publish_date DESC NULLS LAST
        {limit_clause}
    """
    return sql, params


def _print_dry_run_report(rows: list[dict], rate_limit_sleep: float) -> None:
    n = len(rows)
    by_state = Counter(r["state"] for r in rows)
    by_channel = Counter(r["channel_name"] for r in rows)

    est_qwen_secs = n * QWEN_AVG_LATENCY_S
    est_sleep_secs = n * rate_limit_sleep
    est_total_secs = est_qwen_secs + est_sleep_secs

    print()
    print("=" * 64)
    print("DRY-RUN REPORT — backfill_untouched_videos")
    print("=" * 64)
    print(f"  Total candidate videos:     {n:>10,}")
    print()
    print(f"  Breakdown by state:")
    for state, count in by_state.most_common():
        print(f"    {state:<32} {count:>8,}  ({count*100/n:.1f}%)" if n else f"    {state:<32} {count:>8,}")
    print()
    print(f"  Top 10 channels by candidate count:")
    for ch, count in by_channel.most_common(10):
        print(f"    {ch[:40]:<42} {count:>6,}")
    print()
    print(f"  Est Qwen wall time:         {est_qwen_secs:>10,.0f}s "
          f"({est_qwen_secs/3600:.2f} h)")
    print(f"  Est rate-limit sleep:       {est_sleep_secs:>10,.0f}s "
          f"({est_sleep_secs/3600:.2f} h)")
    print(f"  Est total runtime:          {est_total_secs:>10,.0f}s "
          f"({est_total_secs/3600:.2f} h)")
    print()
    print(f"  Marginal cost:              $0.00  (Pavilion GPU is sunk cost;")
    print(f"                                      telemetry $0.0012/call is")
    print(f"                                      attribution-only, not real)")
    print("=" * 64)
    print("Re-run without --dry-run to begin classification.")
    print("=" * 64)


def run(args: argparse.Namespace) -> int:
    started_at = time.time()
    print(
        f"[BackfillUT] dry_run={args.dry_run} since={args.since!r} "
        f"channel={args.channel!r} batch_size={args.batch_size} "
        f"rate_limit_sleep={args.rate_limit_sleep}s limit={args.limit}",
        flush=True,
    )

    sql, params = _build_candidate_sql(
        since=args.since, channel=args.channel, limit=args.limit,
    )

    db = BgSessionLocal()
    try:
        result = db.execute(sql_text(sql), params)
        rows = [dict(r._mapping) for r in result.fetchall()]
        print(f"[BackfillUT] candidate query returned {len(rows)} rows", flush=True)

        if not rows:
            print("[BackfillUT] nothing to do — every active-channel video is "
                  "either classified or terminally rejected", flush=True)
            return 0

        if args.dry_run:
            _print_dry_run_report(rows, args.rate_limit_sleep)
            return 0

        # ── Wet run ─────────────────────────────────────────────────────
        stats: dict = {}
        for k in (
            "videos_classified", "videos_skipped_no_transcript",
            "predictions_extracted", "classifier_errors",
            "items_rejected", "haiku_retries_count",
            "total_input_tokens", "total_output_tokens",
            "total_cache_create_tokens", "total_cache_read_tokens",
            "estimated_cost_usd", "timeframes_rejected", "reference_rejected",
        ):
            stats[k] = 0

        n_total = len(rows)
        n_inserted = 0
        n_done = 0
        for r in rows:
            video_id = r["youtube_video_id"]
            channel_name = r["channel_name"]
            channel_id = r["youtube_channel_id"]
            title = r["title"] or ""
            publish_date_str = (
                r["publish_date"].isoformat() if r["publish_date"] else ""
            )
            try:
                inserted, _chars, _status = _process_one_video(
                    db, channel_name, channel_id, video_id, title,
                    publish_date_str, stats,
                )
                n_inserted += inserted
            except Exception as e:
                print(
                    f"[BackfillUT] _process_one_video raised for {video_id} "
                    f"({channel_name}): {type(e).__name__}: {str(e)[:200]}",
                    flush=True,
                )
            n_done += 1
            if n_done % args.batch_size == 0:
                elapsed = time.time() - started_at
                rate = n_done / elapsed if elapsed > 0 else 0.0
                eta = (n_total - n_done) / max(rate, 1e-9)
                print(
                    f"[BackfillUT] progress: {n_done}/{n_total} processed "
                    f"({n_inserted} preds inserted, "
                    f"{stats['classifier_errors']} classifier errors, "
                    f"{rate:.2f} vid/s, eta {eta/60:.1f}min)",
                    flush=True,
                )
            if args.rate_limit_sleep > 0 and n_done < n_total:
                time.sleep(args.rate_limit_sleep)

        elapsed = time.time() - started_at
        print()
        print("=" * 64)
        print("BACKFILL COMPLETE — backfill_untouched_videos")
        print(f"  Processed:               {n_done}/{n_total}")
        print(f"  Predictions inserted:    {n_inserted}")
        print(f"  Classifier errors:       {stats['classifier_errors']}")
        print(f"  No-transcript skips:     {stats['videos_skipped_no_transcript']}")
        print(f"  Wall time:               {elapsed:.0f}s "
              f"({elapsed/3600:.2f} h)")
        print(f"  Marginal cost:           $0.00 (Pavilion sunk)")
        print("=" * 64)
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts + estimates only; no DB writes")
    ap.add_argument("--since", default=None,
                    help="Cutoff publish_date YYYY-MM-DD (default: no cutoff)")
    ap.add_argument("--channel", default=None,
                    help="Process only one channel by name (debug)")
    ap.add_argument("--batch-size", type=int, default=25,
                    help="Progress print cadence (default 25)")
    ap.add_argument("--rate-limit-sleep", type=float, default=1.0,
                    help="Seconds between Qwen calls (default 1.0)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap total videos processed (0 = no cap)")
    args = ap.parse_args()

    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"[BackfillUT] --since must be YYYY-MM-DD, got {args.since!r}",
                  flush=True)
            return 2

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
