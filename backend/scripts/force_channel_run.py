#!/usr/bin/env python3
"""One-shot single-channel driver for the YouTube channel monitor.

Imports the real `_process_one_video` + helpers from
`backend/jobs/youtube_channel_monitor.py` and runs them over a single
channel's fresh uploads. Lives OUTSIDE the worker scheduler so it:
- never touches the 12h `channel_monitor` APScheduler job,
- never creates a `scraper_runs` row (that's `_run_inner`'s job), and
- never acquires any lock (YouTube uses `_standalone`, not `_guarded`).

Purpose: validate the INSERT half of the 11-ship pipeline. The
classifier half is already proven by `flag_smoke_test.py` — this script
proves that when Haiku emits a non-ticker_call dict on a real transcript,
`_process_one_video` routes it to the right `insert_youtube_*` function
and the row lands in the DB with the expected columns populated.

Usage:
    export ANTHROPIC_API_KEY=...
    export DATABASE_PUBLIC_URL=...
    export WEBSHARE_PROXY_USERNAME=...
    export WEBSHARE_PROXY_PASSWORD=...
    export YOUTUBE_API_KEY=...
    python backend/scripts/force_channel_run.py \\
        --channel-id UChBVf9YnourrEDTsbbwJPRA --max-videos 3

Cost cap: $0.50 hard / 100K cumulative input tokens. The script checks
stats["total_input_tokens"] between every video and aborts if exceeded.

Dedup: the script honours the same `youtube_videos` dedup the real
monitor uses — videos already processed under the current
`PIPELINE_VERSION` are skipped so re-running the script does not
re-classify or re-insert anything. If the channel has zero new videos,
the script exits with `NEED CHANNEL: <reason>` per the task spec.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _fatal(msg: str, code: int = 2) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(code)


for _k in ("ANTHROPIC_API_KEY", "DATABASE_PUBLIC_URL",
           "WEBSHARE_PROXY_USERNAME", "WEBSHARE_PROXY_PASSWORD",
           "YOUTUBE_API_KEY"):
    if not os.getenv(_k):
        _fatal(f"{_k} not set in env")

# Let database.py pick up the public URL for local use.
os.environ["DATABASE_URL"] = os.environ["DATABASE_PUBLIC_URL"]


from sqlalchemy import text as sql_text  # noqa: E402

from database import BgSessionLocal  # noqa: E402
from jobs.youtube_channel_monitor import (  # noqa: E402
    _ensure_tables,
    _fetch_video_durations,
    _get_recent_videos,
    _is_likely_short,
    _process_one_video,
    _record_processed_video,
    _update_channel_yield_counters,
    _upsert_meta_stats,
    YOUTUBE_MIN_DURATION_SECONDS,
)
from jobs.youtube_classifier import PIPELINE_VERSION  # noqa: E402


COST_CAP_USD = 0.50
TOKEN_CAP_INPUT = 100_000


_CATEGORY_QUERIES = {
    "pair_call":            "SELECT COUNT(*) FROM predictions WHERE prediction_category='pair_call'",
    "binary_event_call":    "SELECT COUNT(*) FROM predictions WHERE prediction_category='binary_event_call'",
    "metric_forecast_call": "SELECT COUNT(*) FROM predictions WHERE prediction_category='metric_forecast_call'",
    "regime_call":          "SELECT COUNT(*) FROM predictions WHERE prediction_category='regime_call'",
    "conditional_call":     "SELECT COUNT(*) FROM predictions WHERE prediction_category='conditional_call'",
    "macro_call":           "SELECT COUNT(*) FROM predictions WHERE macro_concept IS NOT NULL",
    "event_earnings":       "SELECT COUNT(*) FROM predictions WHERE event_type='earnings'",
    "event_options":        "SELECT COUNT(*) FROM predictions WHERE prediction_type='options'",
    "target_revisions":     "SELECT COUNT(*) FROM predictions WHERE revision_of IS NOT NULL",
    "ranked_list":          "SELECT COUNT(*) FROM predictions WHERE list_id IS NOT NULL",
    "source_timestamps":    "SELECT COUNT(*) FROM predictions WHERE source_timestamp_seconds IS NOT NULL",
    "metadata_enrichment":  "SELECT COUNT(*) FROM predictions WHERE conviction_level IS NOT NULL",
    "disclosures_total":    "SELECT COUNT(*) FROM disclosures",
    "predictions_total":    "SELECT COUNT(*) FROM predictions",
}


def _snapshot(db) -> dict[str, int]:
    out: dict[str, int] = {}
    for label, q in _CATEGORY_QUERIES.items():
        try:
            out[label] = int(db.execute(sql_text(q)).scalar() or 0)
        except Exception as e:
            print(f"  [snapshot] {label}: ERROR {e}")
            out[label] = -1
            db.rollback()
    return out


def _delta(before: dict[str, int], after: dict[str, int]) -> list[tuple[str, int, int, int]]:
    rows: list[tuple[str, int, int, int]] = []
    for k in _CATEGORY_QUERIES:
        b, a = before.get(k, 0), after.get(k, 0)
        rows.append((k, b, a, a - b))
    return rows


def run(channel_id: str, max_videos: int) -> int:
    t_start = time.time()
    db = BgSessionLocal()
    try:
        _ensure_tables(db)

        row = db.execute(sql_text("""
            SELECT channel_name, last_crawled, is_active
            FROM youtube_channels
            WHERE youtube_channel_id = :cid
            LIMIT 1
        """), {"cid": channel_id}).first()
        if not row:
            print(f"NEED CHANNEL: {channel_id} not in youtube_channels")
            return 2
        channel_name, last_crawled, is_active = row[0], row[1], row[2]

        if is_active is not None and not is_active:
            print(f"NEED CHANNEL: {channel_name} has is_active=false "
                  f"(auto-pruned or manually deactivated)")
            return 2

        since_dt = last_crawled or (datetime.utcnow() - timedelta(days=7))
        since = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        print(f"[force-run] channel={channel_name} id={channel_id} "
              f"since={since} (last_crawled={last_crawled})", flush=True)

        videos = _get_recent_videos(channel_id, since) or []
        print(f"[force-run] YouTube API returned {len(videos)} videos "
              f"since {since}", flush=True)
        if not videos:
            print(f"NEED CHANNEL: {channel_name} has no videos since {since} "
                  f"(7-day fallback applied if last_crawled was null)")
            return 3

        videos = videos[:max_videos]
        video_ids = [
            (v.get("id") or {}).get("videoId")
            for v in videos
            if (v.get("id") or {}).get("videoId")
        ]
        durations = _fetch_video_durations(video_ids)

        print("\n=== BEFORE snapshot ===")
        before = _snapshot(db)
        for k, v in before.items():
            print(f"  {k:25s} {v}")

        stats: dict = {
            "channels_checked": 1, "videos_seen": 0,
            "videos_skipped_already_processed": 0,
            "videos_skipped_short": 0, "videos_skipped_no_transcript": 0,
            "videos_classified": 0, "predictions_extracted": 0,
            "predictions_inserted": 0, "classifier_errors": 0,
            "yt_api_units": 1 if video_ids else 0,
            "items_rejected": 0, "items_deduped": 0,
            "sector_calls_extracted": 0,
            "options_positions_extracted": 0,
            "earnings_calls_extracted": 0,
            "macro_calls_extracted": 0,
            "pair_calls_extracted": 0,
            "binary_events_extracted": 0,
            "metric_forecasts_extracted": 0,
            "conditional_calls_extracted": 0,
            "disclosures_extracted": 0,
            "regime_calls_extracted": 0,
            "total_input_tokens": 0, "total_output_tokens": 0,
            "total_cache_create_tokens": 0, "total_cache_read_tokens": 0,
            "estimated_cost_usd": 0.0, "haiku_retries_count": 0,
            "timestamps_matched": 0, "timestamps_failed": 0,
            "timeframes_explicit": 0, "timeframes_inferred": 0,
            "timeframes_rejected": 0, "reference_rejected": 0,
            "conviction_strong": 0, "conviction_moderate": 0,
            "conviction_hedged": 0, "conviction_hypothetical": 0,
            "conviction_unknown": 0,
        }

        aborted = False
        channel_videos = 0
        channel_inserted = 0
        processed_video_ids: list[str] = []

        print(f"\n=== Processing up to {max_videos} videos ===")
        for i, video in enumerate(videos, 1):
            video_id = (video.get("id") or {}).get("videoId")
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
                print(f"  [{i}/{len(videos)}] {video_id} SKIP: already in youtube_videos")
                stats["videos_skipped_already_processed"] += 1
                continue

            dur_seconds = durations.get(video_id, 0)
            if 0 < dur_seconds < YOUTUBE_MIN_DURATION_SECONDS:
                print(f"  [{i}/{len(videos)}] {video_id} SKIP: too short ({dur_seconds}s)")
                stats["videos_skipped_short"] += 1
                continue
            if _is_likely_short(title, video_id):
                print(f"  [{i}/{len(videos)}] {video_id} SKIP: title looks like a Short")
                continue

            if stats["total_input_tokens"] > TOKEN_CAP_INPUT:
                print(f"  [{i}/{len(videos)}] ABORT: cumulative input tokens "
                      f"{stats['total_input_tokens']} exceeds cap {TOKEN_CAP_INPUT}")
                aborted = True
                break
            if stats["estimated_cost_usd"] > COST_CAP_USD:
                print(f"  [{i}/{len(videos)}] ABORT: estimated cost "
                      f"${stats['estimated_cost_usd']:.4f} exceeds cap ${COST_CAP_USD}")
                aborted = True
                break

            print(f"  [{i}/{len(videos)}] {video_id} PROCESSING: "
                  f"\"{title[:80]}\" ({dur_seconds}s)", flush=True)
            channel_videos += 1
            t0 = time.time()
            inserted, tchars, tstatus = _process_one_video(
                db, channel_name, channel_id, video_id, title,
                publish_date_str, stats,
            )
            elapsed = int((time.time() - t0) * 1000)
            channel_inserted += inserted
            processed_video_ids.append(video_id)

            print(f"      -> inserted={inserted} status={tstatus} "
                  f"transcript_chars={tchars} elapsed={elapsed}ms "
                  f"cum_input_tok={stats['total_input_tokens']} "
                  f"cum_cost=${stats['estimated_cost_usd']:.4f}", flush=True)

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
            videos_found=channel_videos,
            predictions_extracted=channel_inserted,
        )

        print("\n=== AFTER snapshot ===")
        after = _snapshot(db)
        for k, v in after.items():
            print(f"  {k:25s} {v}")

        print("\n=== DELTA table ===")
        print(f"  {'category':25s} {'before':>8s} {'after':>8s} {'delta':>8s}")
        total_new_category_delta = 0
        for label, b, a, d in _delta(before, after):
            marker = " <==" if d > 0 else ""
            print(f"  {label:25s} {b:>8d} {a:>8d} {d:>+8d}{marker}")
            if d > 0 and label not in ("predictions_total", "metadata_enrichment",
                                        "source_timestamps"):
                total_new_category_delta += d

        print("\n=== per-flag stats (equivalent to scraper_runs row) ===")
        interesting = [
            "videos_classified", "predictions_extracted", "predictions_inserted",
            "classifier_errors",
            "sector_calls_extracted", "options_positions_extracted",
            "earnings_calls_extracted", "macro_calls_extracted",
            "pair_calls_extracted", "binary_events_extracted",
            "metric_forecasts_extracted", "conditional_calls_extracted",
            "disclosures_extracted", "regime_calls_extracted",
            "timestamps_matched", "timestamps_failed",
            "timeframes_explicit", "timeframes_inferred", "timeframes_rejected",
            "reference_rejected",
            "conviction_strong", "conviction_moderate", "conviction_hedged",
            "total_input_tokens", "total_output_tokens",
            "total_cache_create_tokens", "total_cache_read_tokens",
            "estimated_cost_usd", "haiku_retries_count",
        ]
        for k in interesting:
            if k in stats:
                print(f"  {k:32s} {stats[k]}")

        if processed_video_ids:
            print("\n=== first 5 inserted predictions from this run ===")
            q = sql_text("""
                SELECT id, ticker, direction, prediction_category, event_type,
                       macro_concept, pair_long_ticker, pair_short_ticker,
                       regime_type, trigger_condition, target_price,
                       window_days, time_horizon, source_url, created_at
                FROM predictions
                WHERE video_id = ANY(:vids)
                  AND created_at > :t0
                ORDER BY id DESC
                LIMIT 5
            """)
            rows = db.execute(q, {
                "vids": processed_video_ids,
                "t0": datetime.fromtimestamp(t_start),
            }).fetchall()
            for r in rows:
                print(f"  id={r[0]} ticker={r[1]} dir={r[2]} cat={r[3]} "
                      f"event={r[4]} macro={r[5]} pair={r[6]}/{r[7]} "
                      f"regime={r[8]} trig={str(r[9])[:60]!r} tgt={r[10]} "
                      f"window_days={r[11]} horizon={r[12]}")
            if rows:
                print("\n=== frontend eyeball URLs ===")
                for r in rows:
                    print(f"  https://eidolum.com/prediction/{r[0]}")

            print("\n=== disclosures from this run ===")
            drows = db.execute(sql_text("""
                SELECT id, ticker, action, reasoning_text, disclosed_at
                FROM disclosures
                WHERE video_id = ANY(:vids)
                  AND created_at > :t0
                ORDER BY id DESC LIMIT 5
            """), {
                "vids": processed_video_ids,
                "t0": datetime.fromtimestamp(t_start),
            }).fetchall()
            for r in drows:
                print(f"  id={r[0]} ticker={r[1]} action={r[2]} "
                      f"reason={str(r[3])[:80]!r} disclosed_at={r[4]}")

            print("\n=== rejections from this run (sample) ===")
            rej = db.execute(sql_text("""
                SELECT rejection_reason, haiku_reason
                FROM youtube_scraper_rejections
                WHERE video_id = ANY(:vids)
                ORDER BY rejected_at DESC LIMIT 10
            """), {"vids": processed_video_ids}).fetchall()
            for r in rej:
                print(f"  [{r[0]}] {str(r[1])[:140]}")

        elapsed_sec = int(time.time() - t_start)
        print("\n=== VERDICT ===")
        ran_classifier = stats.get("videos_classified", 0) > 0
        any_inserted = stats.get("predictions_inserted", 0) > 0
        any_new_category_stat = any(stats.get(k, 0) > 0 for k in (
            "pair_calls_extracted", "binary_events_extracted",
            "metric_forecasts_extracted", "macro_calls_extracted",
            "regime_calls_extracted", "conditional_calls_extracted",
            "disclosures_extracted", "options_positions_extracted",
            "earnings_calls_extracted",
        ))

        if any_new_category_stat and total_new_category_delta > 0:
            verdict = "GREEN"
            note = "new-category prediction landed in the DB. Insert path works."
        elif ran_classifier and any_inserted and not any_new_category_stat:
            verdict = "YELLOW"
            note = ("Classifier fired, inserted plain ticker_call rows, but "
                    "produced ZERO new-category rows. Either this channel's "
                    "content didn't contain the relevant signals, the "
                    "rejection filter caught them, or the insert path dropped "
                    "them. Inspect rejections above.")
        elif ran_classifier and not any_inserted:
            verdict = "YELLOW"
            note = ("Classifier fired on real transcript but Haiku rejected "
                    "every candidate (see rejections above). Nothing reached "
                    "the insert path. Try a different channel with more "
                    "concrete forward-looking content.")
        elif not ran_classifier:
            verdict = "RED"
            note = ("Classifier never fired. All videos were skipped "
                    "(already-processed / short / no-transcript).")
        else:
            verdict = "GREY"
            note = "Indeterminate — review stats above."

        print(f"  {verdict}: {note}")
        print(f"  elapsed_sec={elapsed_sec} channel={channel_name} "
              f"channel_inserted={channel_inserted} "
              f"cost_usd=${stats['estimated_cost_usd']:.4f} "
              f"aborted={aborted}")

        return 0 if verdict == "GREEN" else 1

    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel-id", required=True)
    ap.add_argument("--max-videos", type=int, default=3)
    args = ap.parse_args()
    return run(args.channel_id, args.max_videos)


if __name__ == "__main__":
    sys.exit(main())
