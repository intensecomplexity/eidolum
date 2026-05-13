"""Resumable backfill driver for newly-added YouTube channels.

Walks the channels in expansion_survivors_2026_05.json (or a custom
survivor JSON), fetches each channel's uploads from the past 12 months
via playlistItems.list + videos.list, drops Shorts, then for every
remaining video reuses youtube_channel_monitor._process_one_video to
fetch the transcript (Webshare proxy) and classify (Pavilion / Qwen
2.5 7B LoRA).

State lives in --state-file (default
backend/scripts/.backfill_new_channels_state.json) so a 524 / SIGTERM
re-run picks up where the previous run stopped.

Caps:
  --max-channels N   per-run channel cap (default 20)
  --max-hours H      wall-clock cap, hours (default 6)
  --max-videos-per-channel V   optional safety cap (default unlimited)
  --daily-cap N      max channels *started* per calendar day (default 20)

Usage:
  YOUTUBE_API_KEY=... DATABASE_URL=... CLASSIFIER_BASE_URL=... \
      python3 backend/scripts/backfill_new_channels.py --max-channels 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text as sql_text  # noqa: E402

from database import BgSessionLocal as SessionLocal  # noqa: E402
from jobs.youtube_channel_monitor import (  # noqa: E402
    _fetch_video_durations,
    _is_likely_short,
    _process_one_video,
    _record_processed_video,
    _resolve_channel_id,
    _update_channel_yield_counters,
    YOUTUBE_API,
    YOUTUBE_MIN_DURATION_SECONDS,
)

DEFAULT_STATE_PATH = HERE / ".backfill_new_channels_state.json"
DEFAULT_SURVIVORS = HERE / "expansion_survivors_2026_05.json"

# 12-month lookback by default. PlaylistItems are returned newest-first,
# so we stop paginating once we see a video older than the cutoff.
LOOKBACK = timedelta(days=365)


def _stats_bootstrap() -> dict:
    """Return a stats dict pre-seeded with every counter
    _process_one_video / log_youtube_rejection touches. Missing keys
    blow up the existing helpers, so we shadow run_channel_monitor's
    bootstrap exactly.
    """
    return {
        "channels_checked": 0,
        "videos_seen": 0,
        "videos_classified": 0,
        "videos_skipped_short": 0,
        "videos_skipped_no_transcript": 0,
        "predictions_extracted": 0,
        "yt_api_units": 0,
        "rejections_logged": 0,
        "tickers_resolved": 0,
        "tickers_unresolved": 0,
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
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_create_tokens": 0,
        "total_cache_read_tokens": 0,
        "estimated_cost_usd": 0.0,
        # Backfill-specific telemetry
        "classifier_524s": 0,
        "classifier_errors": 0,
    }


def _load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"[backfill] state file {path} corrupt, starting fresh")
    return {"schema_version": 1, "channels": {}, "daily_starts": {}}


def _save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(path)


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _list_videos_past_year(
    channel_id: str, api_key: str, cutoff: datetime, max_videos: Optional[int],
) -> tuple[list[dict], int]:
    """Paginate uploads playlist newest-first, collecting every video
    published after `cutoff`. Returns (videos, api_units_used).

    Each video dict: {video_id, title, description, published_at}.
    """
    uploads = "UU" + channel_id[2:]
    page_token: Optional[str] = None
    videos: list[dict] = []
    units = 0
    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": uploads,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            r = httpx.get(f"{YOUTUBE_API}/playlistItems", params=params, timeout=20)
        except Exception as e:
            print(f"[backfill] playlistItems error: {e}")
            break
        units += 1
        if r.status_code != 200:
            print(f"[backfill] playlistItems HTTP {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        items = data.get("items") or []
        if not items:
            break
        oldest_in_page: Optional[datetime] = None
        for item in items:
            content = item.get("contentDetails") or {}
            snippet = item.get("snippet") or {}
            vid = content.get("videoId")
            pub = content.get("videoPublishedAt") or snippet.get("publishedAt") or ""
            if not vid or not pub:
                continue
            try:
                pub_dt = datetime.strptime(pub[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            oldest_in_page = pub_dt if oldest_in_page is None else min(oldest_in_page, pub_dt)
            if pub_dt < cutoff:
                continue
            videos.append({
                "video_id": vid,
                "title": snippet.get("title") or "",
                "description": snippet.get("description") or "",
                "published_at": pub,
            })
            if max_videos and len(videos) >= max_videos:
                return videos, units
        # Stop once the page's oldest video is past the cutoff.
        if oldest_in_page is not None and oldest_in_page < cutoff:
            break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return videos, units


def _processed_video_ids(db, channel_name: str) -> set[str]:
    return {
        r[0]
        for r in db.execute(
            sql_text(
                "SELECT youtube_video_id FROM youtube_videos WHERE channel_name = :n"
            ),
            {"n": channel_name},
        ).fetchall()
    }


def _ensure_channel_row(db, name: str, channel_id: str) -> None:
    """INSERT-or-UPDATE the youtube_channels row so the backfill can
    write predictions referencing a real forecaster.
    """
    row = db.execute(
        sql_text(
            "SELECT id, youtube_channel_id FROM youtube_channels "
            "WHERE channel_name = :n"
        ),
        {"n": name},
    ).fetchone()
    if not row:
        db.execute(
            sql_text(
                "INSERT INTO youtube_channels "
                "(channel_name, youtube_channel_id, is_active, catalog_complete) "
                "VALUES (:n, :c, TRUE, FALSE)"
            ),
            {"n": name, "c": channel_id},
        )
        db.commit()
        return
    if not row[1]:
        db.execute(
            sql_text(
                "UPDATE youtube_channels SET youtube_channel_id = :c WHERE id = :i"
            ),
            {"c": channel_id, "i": row[0]},
        )
        db.commit()


def _pick_channels_for_run(
    survivors: list[dict], state: dict, max_channels: int, daily_cap: int,
) -> list[dict]:
    """Skip channels already marked completed. Within the per-day cap,
    return at most max_channels survivors in subscriber-desc order so
    the highest-yield channels backfill first.
    """
    today = _today_utc()
    started_today = state.get("daily_starts", {}).get(today, 0)
    remaining_today = max(0, daily_cap - started_today)
    if remaining_today == 0:
        return []
    quota = min(max_channels, remaining_today)

    pending = []
    for s in sorted(survivors, key=lambda x: -x.get("subscribers", 0)):
        cid = s.get("channel_id")
        if not cid:
            continue
        ch_state = state["channels"].get(cid) or {}
        if ch_state.get("completed_at"):
            continue
        pending.append(s)
        if len(pending) >= quota:
            break
    return pending


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-channels", type=int, default=20)
    p.add_argument("--max-hours", type=float, default=6.0)
    p.add_argument("--max-videos-per-channel", type=int, default=0,
                   help="0 = unlimited (cap is the 12mo lookback)")
    p.add_argument("--daily-cap", type=int, default=20,
                   help="Max channels *started* per calendar day")
    p.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    p.add_argument("--survivors", type=Path, default=DEFAULT_SURVIVORS)
    p.add_argument("--dry-run", action="store_true",
                   help="Enumerate videos but skip transcript+classify")
    args = p.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY required", file=sys.stderr)
        return 2

    if not args.survivors.exists():
        print(f"survivors file not found: {args.survivors}", file=sys.stderr)
        return 2
    payload = json.loads(args.survivors.read_text())
    survivors = payload.get("survivors") or []
    if not survivors:
        print("no survivors in JSON", file=sys.stderr)
        return 1

    state = _load_state(args.state_file)
    targets = _pick_channels_for_run(
        survivors, state, args.max_channels, args.daily_cap,
    )
    if not targets:
        print("[backfill] nothing to do — daily cap reached or all done")
        return 0

    today = _today_utc()
    cutoff = datetime.now(timezone.utc) - LOOKBACK
    run_started = time.monotonic()
    wall_budget = args.max_hours * 3600

    print(
        f"[backfill] {len(targets)} channels picked, "
        f"cutoff={cutoff.date()}, wall budget={args.max_hours}h, "
        f"daily cap={args.daily_cap} (started today={state.get('daily_starts', {}).get(today, 0)})"
    )

    db = SessionLocal()
    stats = _stats_bootstrap()
    grand_videos = 0
    grand_predictions = 0

    try:
        for t in targets:
            if time.monotonic() - run_started > wall_budget:
                print("[backfill] wall-clock budget exhausted before channel start")
                break

            cid = t["channel_id"]
            name = t["name"]
            print(f"\n[backfill] === {name} ({cid}) — {t.get('subscribers', 0):,} subs ===")

            ch_state = state["channels"].setdefault(cid, {})
            if "started_at" not in ch_state:
                ch_state["started_at"] = datetime.now(timezone.utc).isoformat()
                ch_state["name"] = name
                state.setdefault("daily_starts", {})
                state["daily_starts"][today] = state["daily_starts"].get(today, 0) + 1
                _save_state(args.state_file, state)

            _ensure_channel_row(db, name, cid)

            videos, api_units = _list_videos_past_year(
                cid, api_key, cutoff,
                args.max_videos_per_channel or None,
            )
            stats["yt_api_units"] += api_units
            print(f"[backfill]   listed {len(videos)} videos in past 12mo "
                  f"({api_units} api units)")

            if not videos:
                ch_state["completed_at"] = datetime.now(timezone.utc).isoformat()
                ch_state["videos_attempted"] = 0
                ch_state["predictions_inserted"] = 0
                _save_state(args.state_file, state)
                continue

            processed = _processed_video_ids(db, name)
            durations = _fetch_video_durations([v["video_id"] for v in videos])
            stats["yt_api_units"] += 1

            videos_attempted = ch_state.get("videos_attempted", 0)
            predictions_inserted = ch_state.get("predictions_inserted", 0)

            for vinfo in videos:
                if time.monotonic() - run_started > wall_budget:
                    print("[backfill]   wall-clock budget hit, breaking")
                    break
                vid = vinfo["video_id"]
                if vid in processed:
                    continue
                title = vinfo["title"]
                publish = vinfo["published_at"]

                dur = durations.get(vid, 0)
                if 0 < dur < YOUTUBE_MIN_DURATION_SECONDS:
                    stats["videos_skipped_short"] += 1
                    _record_processed_video(
                        db, vid, name, title, vinfo["description"],
                        publish, "shorts_skipped", 0, 0,
                    )
                    db.commit()
                    continue
                if _is_likely_short(title, vid):
                    stats["videos_skipped_short"] += 1
                    _record_processed_video(
                        db, vid, name, title, vinfo["description"],
                        publish, "shorts_skipped", 0, 0,
                    )
                    db.commit()
                    continue

                if args.dry_run:
                    videos_attempted += 1
                    stats["videos_seen"] += 1
                    continue

                stats["videos_seen"] += 1
                videos_attempted += 1

                try:
                    inserted, tchars, status = _process_one_video(
                        db, name, cid, vid, title, publish, stats,
                    )
                except Exception as e:
                    err = str(e)[:200]
                    print(f"[backfill]   {vid} error: {err}")
                    stats["classifier_errors"] += 1
                    if "524" in err:
                        stats["classifier_524s"] += 1
                    db.rollback()
                    continue

                _update_channel_yield_counters(db, cid, name, status, inserted)
                _record_processed_video(
                    db, vid, name, title, vinfo["description"],
                    publish, status, tchars, inserted,
                )
                try:
                    db.commit()
                except Exception as e:
                    print(f"[backfill]   commit err {vid}: {e}")
                    db.rollback()

                if inserted:
                    predictions_inserted += inserted

                ch_state["videos_attempted"] = videos_attempted
                ch_state["predictions_inserted"] = predictions_inserted
                ch_state["last_video_id"] = vid
                ch_state["last_video_published"] = publish
                _save_state(args.state_file, state)

                # Stagger Pavilion calls so a single channel can't
                # monopolize the tunnel.
                time.sleep(0.5)

            # Channel marked complete only if we got through every video
            # without hitting the wall-clock cap.
            if time.monotonic() - run_started <= wall_budget:
                ch_state["completed_at"] = datetime.now(timezone.utc).isoformat()
                ch_state["videos_attempted"] = videos_attempted
                ch_state["predictions_inserted"] = predictions_inserted
                _save_state(args.state_file, state)

            grand_videos += videos_attempted
            grand_predictions += predictions_inserted

    finally:
        db.close()
        _save_state(args.state_file, state)

    elapsed = time.monotonic() - run_started
    print("\n=== backfill run summary ===")
    print(f"  channels picked       : {len(targets)}")
    print(f"  channels completed    : "
          f"{sum(1 for t in targets if state['channels'].get(t['channel_id'], {}).get('completed_at'))}")
    print(f"  videos attempted      : {grand_videos}")
    print(f"  predictions inserted  : {grand_predictions}")
    print(f"  shorts skipped        : {stats['videos_skipped_short']}")
    print(f"  no-transcript         : {stats['videos_skipped_no_transcript']}")
    print(f"  classifier 524s       : {stats['classifier_524s']}")
    print(f"  classifier errors     : {stats['classifier_errors']}")
    print(f"  yt api units          : {stats['yt_api_units']}")
    print(f"  estimated cost usd    : {stats['estimated_cost_usd']:.4f}")
    print(f"  wall elapsed (min)    : {elapsed/60:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
