"""
Rescue low-confidence YouTube timestamps by re-running the deterministic
fuzzy matcher over existing `source_verbatim_quote` values.

Why this exists:

The Ship-10 verification (50-row quote→timestamp audit) turned up a
`two_pass` match at confidence 0.60 whose stored timestamp was 122s
off from where the deterministic `normalized_overlap` matcher landed
the same quote. That case — and the population of training-ready
rows with `source_timestamp_confidence < 0.70` whose method is
`two_pass` or `segment_overlap` — is worth re-resolving with the
newer fuzzy paths in `jobs.timestamp_matcher`:
    - normalized_overlap
    - segment_overlap
    - normalized_fuzzy
    - key_phrase_anchor

All four are stdlib-only, so this script is Haiku-free: it needs only
DATABASE_URL and WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD
(for the residential proxy) to run.

Update policy:
    Replace stored (seconds, method, confidence) iff:
        new_conf > old_conf   (strictly greater)
    Equal confidence on a different timestamp is NOT overwritten —
    we only move when the new matcher is strictly more sure.

Usage (from backend/):
    python -m jobs.rescue_low_conf_timestamps                 # dry run
    python -m jobs.rescue_low_conf_timestamps --apply         # write to DB
    python -m jobs.rescue_low_conf_timestamps --apply --limit 5
    python -m jobs.rescue_low_conf_timestamps --apply --delay 0.5
"""
import argparse
import os
import sys
import threading
import time
from collections import OrderedDict, Counter


class FuturesTimeout(Exception):
    pass


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text
from database import BgSessionLocal


TAG = "[rescue-low-conf]"
_YT_VIDEO_ID_LEN = 11
DEFAULT_DELAY = 1.0
TRANSCRIPT_TIMEOUT = 30


def _run_with_timeout(fn, *args, timeout_sec=None, **kwargs):
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
        raise FuturesTimeout(
            f"{fn.__name__} did not complete within {timeout_sec}s"
        )
    if exc[0] is not None:
        raise exc[0]
    return result[0]


def _fetch_with_timeout(video_id, timeout_sec=None):
    from jobs.youtube_classifier import fetch_transcript_with_timestamps
    return _run_with_timeout(
        fetch_transcript_with_timestamps, video_id,
        timeout_sec=timeout_sec or TRANSCRIPT_TIMEOUT,
    )


def _extract_video_id(source_platform_id: str):
    if not source_platform_id or not source_platform_id.startswith("yt_"):
        return None
    candidate = source_platform_id[3:3 + _YT_VIDEO_ID_LEN]
    return candidate if len(candidate) == _YT_VIDEO_ID_LEN else None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Re-resolve low-confidence YouTube timestamps with "
                    "the stdlib-only fuzzy matcher.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to DB. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N videos (0 = all).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help="Seconds between transcript fetches.")
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{TAG} Starting rescue ({mode})", flush=True)

    db = BgSessionLocal()
    try:
        return _run(db, apply=args.apply, limit=args.limit, delay=args.delay)
    finally:
        db.close()


def _run(db, *, apply: bool, limit: int, delay: float) -> int:
    try:
        db.execute(sql_text("SET statement_timeout = 0"))
        db.commit()
    except Exception as _e:
        print(f"{TAG} WARNING: could not disable statement_timeout: {_e}",
              flush=True)

    # ── 1. Candidate set: training-ready rows with conf < 0.70 ──────────
    rows = db.execute(sql_text("""
        SELECT id, source_platform_id, source_verbatim_quote, ticker,
               prediction_date,
               source_timestamp_seconds   AS old_ts,
               source_timestamp_method    AS old_method,
               source_timestamp_confidence AS old_conf
        FROM predictions
        WHERE verified_by = 'youtube_haiku_v1'
          AND excluded_from_training = FALSE
          AND source_timestamp_seconds IS NOT NULL
          AND source_timestamp_confidence < 0.70
          AND timeframe_category IS NOT NULL
          AND source_verbatim_quote IS NOT NULL
          AND conviction_level IS NOT NULL
          AND inferred_timeframe_days IS NOT NULL
          AND direction IN ('bullish', 'bearish')
        ORDER BY source_platform_id, id
    """)).fetchall()

    if not rows:
        print(f"{TAG} No candidates.")
        return 0

    video_groups: "OrderedDict[str, list]" = OrderedDict()
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
        print(f"{TAG} Skipped {skipped_bad_id} rows with unparseable "
              f"source_platform_id", flush=True)

    from jobs.timestamp_matcher import match_quote_to_timestamp

    stats = {
        "videos_processed": 0,
        "videos_no_transcript": 0,
        "videos_timed_out": 0,
        "rescued": 0,            # strictly higher conf → will/did write
        "unchanged_no_match": 0, # matcher returned None
        "unchanged_not_improved": 0,  # new_conf <= old_conf
        "matcher_errors": 0,
        "written": 0,
    }
    transitions: Counter = Counter()   # (old_method, new_method) pairs
    rescued_same_ts = 0
    rescued_diff_ts = 0
    big_ts_deltas = []   # list of (id, ticker, old_ts, new_ts, old_method, new_method, old_conf, new_conf)

    items = list(video_groups.items())
    if limit:
        items = items[:limit]

    for vid_idx, (video_id, preds) in enumerate(items):
        print(f"\n{TAG} [{vid_idx+1}/{len(items)}] video={video_id} "
              f"predictions={len(preds)}", flush=True)

        if vid_idx > 0:
            time.sleep(delay)

        try:
            transcript_data = _fetch_with_timeout(
                video_id, timeout_sec=TRANSCRIPT_TIMEOUT,
            )
        except FuturesTimeout:
            print(f"{TAG}   Transcript TIMEOUT. Skipping {len(preds)} preds.",
                  flush=True)
            stats["videos_timed_out"] += 1
            continue
        except Exception as e:
            print(f"{TAG}   Transcript error: {type(e).__name__}: {e}",
                  flush=True)
            stats["videos_no_transcript"] += 1
            continue

        status = transcript_data.get("status", "unknown")
        text_payload = transcript_data.get("text", "")
        if status != "ok" or not text_payload:
            print(f"{TAG}   Transcript failed: status={status}. "
                  f"Skipping {len(preds)} preds.", flush=True)
            stats["videos_no_transcript"] += 1
            continue

        has_words = transcript_data.get("has_word_level", False)
        seg_count = len(transcript_data.get("segments", []))
        print(f"{TAG}   Transcript OK: {len(text_payload)} chars, "
              f"{seg_count} segments, word_level="
              f"{'yes' if has_words else 'no'}", flush=True)

        stats["videos_processed"] += 1

        updates_this_video = []
        for pred in preds:
            pid = pred.id
            ticker = pred.ticker or "?"
            quote = pred.source_verbatim_quote or ""
            old_ts = int(pred.old_ts)
            old_method = pred.old_method or "unknown"
            old_conf = float(pred.old_conf or 0.0)

            try:
                new_ts, new_method, new_conf = match_quote_to_timestamp(
                    quote, transcript_data, enable_two_pass=False,
                )
            except Exception as e:
                print(f"{TAG}   id={pid:>7d} {ticker:>6s} matcher error: "
                      f"{type(e).__name__}: {str(e)[:120]}", flush=True)
                stats["matcher_errors"] += 1
                continue

            if new_ts is None:
                stats["unchanged_no_match"] += 1
                print(f"{TAG}   id={pid:>7d} {ticker:>6s} NO MATCH "
                      f"(keep old: {old_method} conf={old_conf:.2f} "
                      f"t={old_ts}s)", flush=True)
                continue

            new_conf = float(new_conf)
            new_ts_i = int(new_ts)

            if new_conf > old_conf:
                stats["rescued"] += 1
                transitions[(old_method, new_method)] += 1
                delta = new_ts_i - old_ts
                if new_ts_i == old_ts:
                    rescued_same_ts += 1
                    marker = "=ts"
                else:
                    rescued_diff_ts += 1
                    marker = f"Δ{delta:+d}s"
                    if abs(delta) > 30:
                        big_ts_deltas.append((
                            pid, ticker, old_ts, new_ts_i,
                            old_method, new_method, old_conf, new_conf,
                        ))
                print(f"{TAG}   id={pid:>7d} {ticker:>6s} RESCUE  "
                      f"{old_method}@{old_conf:.2f} → "
                      f"{new_method}@{new_conf:.2f}  "
                      f"t={old_ts}s→{new_ts_i}s ({marker})", flush=True)
                updates_this_video.append({
                    "id": pid,
                    "seconds": new_ts_i,
                    "method": new_method,
                    "confidence": new_conf,
                })
            else:
                stats["unchanged_not_improved"] += 1
                print(f"{TAG}   id={pid:>7d} {ticker:>6s} keep  "
                      f"{old_method}@{old_conf:.2f} ≥ "
                      f"{new_method}@{new_conf:.2f}", flush=True)

        # ── Commit after each video ──────────────────────────────────
        if apply and updates_this_video:
            written_this_video = 0
            for u in updates_this_video:
                try:
                    db.execute(sql_text("""
                        UPDATE predictions SET
                            source_timestamp_seconds    = :seconds,
                            source_timestamp_method     = :method,
                            source_timestamp_confidence = :confidence
                        WHERE id = :id
                    """), u)
                    db.commit()
                    written_this_video += 1
                except Exception as _uerr:
                    print(f"{TAG}   UPDATE failed for id={u.get('id')}: "
                          f"{type(_uerr).__name__}: {str(_uerr)[:120]}",
                          flush=True)
                    try:
                        db.rollback()
                    except Exception:
                        pass
            stats["written"] += written_this_video
            if written_this_video:
                print(f"{TAG}   Committed {written_this_video} updates "
                      f"(running total: {stats['written']})", flush=True)

    # ── Summary ────────────────────────────────────────────────────────
    print(f"\n{TAG} ── Summary ──")
    print(f"{TAG}   Videos processed:       {stats['videos_processed']}")
    print(f"{TAG}   Videos no transcript:   {stats['videos_no_transcript']}")
    print(f"{TAG}   Videos timed out:       {stats['videos_timed_out']}")
    print(f"{TAG}   Rescued (new > old):    {stats['rescued']}")
    print(f"{TAG}      - same timestamp:    {rescued_same_ts}")
    print(f"{TAG}      - different ts:      {rescued_diff_ts}")
    print(f"{TAG}   Unchanged (no match):   {stats['unchanged_no_match']}")
    print(f"{TAG}   Unchanged (not better): {stats['unchanged_not_improved']}")
    print(f"{TAG}   Matcher errors:         {stats['matcher_errors']}")
    print(f"{TAG}   Total written to DB:    {stats['written']}")

    if transitions:
        print(f"\n{TAG}   Method transitions (old → new, rescued only):")
        for (om, nm), n in transitions.most_common():
            print(f"{TAG}     {om:<22} → {nm:<22}  n={n}")

    if big_ts_deltas:
        print(f"\n{TAG}   Rescued rows with |Δts| > 30s (likely fix-ups):")
        print(f"{TAG}     {'id':>7} {'tkr':<6} {'old_ts':>7} "
              f"{'new_ts':>7} {'Δs':>6}  {'old':<20} → {'new':<20}  conf")
        for (pid, tkr, ots, nts, om, nm, oc, nc) in big_ts_deltas:
            print(f"{TAG}     {pid:>7d} {tkr:<6} {ots:>7} {nts:>7} "
                  f"{nts-ots:>+6d}  {str(om)[:20]:<20} → "
                  f"{str(nm)[:20]:<20}  {oc:.2f}→{nc:.2f}")

    if not apply:
        print(f"\n{TAG} DRY RUN — no DB writes. Pass --apply to commit.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
