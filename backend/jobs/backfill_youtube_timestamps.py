"""
One-shot backfill: resolve source_timestamp_seconds for existing YouTube
predictions that were scraped before ENABLE_SOURCE_TIMESTAMPS was turned on.

Usage (from the backend/ directory):
    python -m jobs.backfill_youtube_timestamps              # dry run (default)
    python -m jobs.backfill_youtube_timestamps --apply      # write to DB
    python -m jobs.backfill_youtube_timestamps --limit 5    # first 5 videos only
    python -m jobs.backfill_youtube_timestamps --apply --limit 10
    python -m jobs.backfill_youtube_timestamps --apply --resume  # pick up where we left off
    python -m jobs.backfill_youtube_timestamps --apply --skip-to 24  # skip first 24 videos
    python -m jobs.backfill_youtube_timestamps --apply --delay 5  # 5s between fetches

Pipeline per prediction (Path B only):
  1. Fetch transcript with word-level timing for the video (30s timeout).
  2. Send transcript + prediction details to Haiku — Haiku extracts the
     exact verbatim quote from the transcript where the prediction was made.
  3. Match Haiku's verbatim quote against the transcript via the 4-path
     timestamp matcher to resolve a precise second offset.
  4. Any failure (no transcript / no quote / no match) → skip the
     prediction. NO Path A fallback — template text matching produces
     low-quality timestamps that are useless for training data.

Respects Webshare proxy config for transcript fetches (inherited from
fetch_transcript_with_timestamps). Does NOT check the
ENABLE_SOURCE_TIMESTAMPS feature flag — that's the whole point.
"""
import argparse
import json
import os
import sys
import threading
import time


class FuturesTimeout(Exception):
    """Raised by _run_with_timeout when the wrapped call exceeds timeout_sec."""
    pass

# Allow running as `python -m jobs.backfill_youtube_timestamps` from backend/.
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text
from database import BgSessionLocal


# ── Constants ─────────────────────────────────────────────────────────────────

TAG = "[yt-ts-backfill]"

# YouTube video IDs are always exactly 11 characters (base64url).
_YT_VIDEO_ID_LEN = 11

# Rate-limit: seconds between consecutive transcript fetches.
TRANSCRIPT_FETCH_DELAY = 2.0

# Commit batch size.
COMMIT_BATCH = 50

# Transcript fetch timeout (seconds). Kills hung proxy connections.
TRANSCRIPT_TIMEOUT = 30

# Haiku pricing (mirror of youtube_classifier.py constants).
HAIKU_PRICE_INPUT_PER_M = 1.00
HAIKU_PRICE_OUTPUT_PER_M = 5.00

# Progress file for --resume.
_PROGRESS_FILE = os.path.join(os.path.dirname(__file__), ".backfill_ts_progress.json")

# Focused prompt for Path B. Much cheaper than the full classifier — we
# only need the verbatim quote for ONE prediction, not full extraction.
_PATHB_SYSTEM = """You are a quote-extraction assistant. You will be given a YouTube transcript and a specific financial prediction that was previously extracted from it. Your job is to find the EXACT verbatim quote from the transcript where the prediction was made.

Rules:
1. COPY the exact words from the transcript — no paraphrasing, no cleanup.
2. Include 1-2 sentences BEFORE the prediction sentence for context (20-60 words total).
3. Every pronoun in the quote must have a resolvable antecedent within the quote.
4. Return ONLY a JSON object: {"verbatim_quote": "..."}
5. If you cannot find the prediction in the transcript, return: {"verbatim_quote": null}
6. Output JSON only. No other text."""


# ── Timeout helper ───────────────────────────────────────────────────────────
#
# signal.alarm() does NOT reliably interrupt urllib3 socket poll() — urllib3
# catches EINTR internally and silently retries, so SIGALRM gets swallowed
# and the process hangs forever. ThreadPoolExecutor.result(timeout=...)
# returns control to the caller on timeout; the worker thread leaks (it's
# still stuck in the poll, but the OS will eventually clean it up when the
# socket times out at the kernel level or the main process exits).

def _run_with_timeout(fn, *args, timeout_sec=None, **kwargs):
    """Run fn(*args, **kwargs) with a hard wall-clock timeout.
    Returns the result on success, raises FuturesTimeout on timeout,
    or re-raises any exception thrown by fn.

    Uses a plain daemon thread (NOT ThreadPoolExecutor) because
    ThreadPoolExecutor.__exit__ calls shutdown(wait=True) which blocks
    waiting for the stuck worker — defeating the timeout entirely.
    Daemon threads don't hold up the process and aren't waited on,
    so control reliably returns to the caller after timeout_sec."""
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
    """Wrapper around fetch_transcript_with_timestamps with a timeout."""
    from jobs.youtube_classifier import fetch_transcript_with_timestamps
    return _run_with_timeout(
        fetch_transcript_with_timestamps, video_id,
        timeout_sec=timeout_sec or TRANSCRIPT_TIMEOUT,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_video_id(source_platform_id: str) -> str | None:
    """Extract the 11-char YouTube video ID from any source_platform_id format.

    All formats start with 'yt_' followed by the 11-char video ID:
      yt_{video_id}_{ticker}
      yt_{video_id}_sector_{canonical}
      yt_{video_id}_pair_{long}_{short}
      etc.
    """
    if not source_platform_id or not source_platform_id.startswith("yt_"):
        return None
    candidate = source_platform_id[3:3 + _YT_VIDEO_ID_LEN]
    if len(candidate) != _YT_VIDEO_ID_LEN:
        return None
    return candidate


def _call_haiku_for_quote(client, transcript_text: str, row) -> str | None:
    """Path B: focused Haiku call to extract verbatim quote for one prediction."""
    ticker = getattr(row, "ticker", "?")
    direction = getattr(row, "direction", "?")
    context = getattr(row, "context", "") or ""
    exact_quote = getattr(row, "exact_quote", "") or ""

    user_msg = (
        f"Prediction details:\n"
        f"  Ticker: {ticker}\n"
        f"  Direction: {direction}\n"
        f"  Context: {context[:500]}\n"
        f"  Extracted quote: {exact_quote[:500]}\n\n"
        f"Transcript:\n{transcript_text[:80_000]}\n\n"
        f"Find the exact verbatim quote from the transcript where this "
        f"prediction was made. Return JSON only."
    )

    try:
        # Haiku call wrapped in the same 30s wall-clock timeout so a
        # hung Anthropic connection can't stall the loop.
        resp = _run_with_timeout(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            temperature=0,
            system=_PATHB_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            timeout_sec=TRANSCRIPT_TIMEOUT,
        )
        text = resp.content[0].text.strip() if resp.content else ""
        # Strip markdown code fences (```json ... ```) that Haiku often wraps.
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]  # remove ```json line
            if text.endswith("```"):
                text = text[:-3].strip()
        # Track tokens for cost reporting.
        usage = resp.usage if hasattr(resp, "usage") else None
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0

        parsed = json.loads(text)
        quote = parsed.get("verbatim_quote")
        return quote, in_tok, out_tok
    except Exception as e:
        print(f"{TAG}   Path B Haiku error: {type(e).__name__}: {e}")
        return None, 0, 0


def _save_progress(index: int):
    """Write the last completed video index to disk."""
    try:
        with open(_PROGRESS_FILE, "w") as f:
            json.dump({"last_completed_index": index}, f)
    except Exception:
        pass


def _load_progress() -> int:
    """Read last completed video index, or -1 if no progress file."""
    try:
        with open(_PROGRESS_FILE) as f:
            return json.load(f).get("last_completed_index", -1)
    except Exception:
        return -1


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Backfill source_timestamp_seconds for existing YouTube predictions.",
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
        "--skip-to", type=int, default=0,
        help="Skip the first N videos (0-indexed). Use to resume after a crash.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Read progress file and skip to last_completed_index + 1.",
    )
    parser.add_argument(
        "--delay", type=float, default=0,
        help="Override transcript fetch delay (seconds). Default uses built-in 2s.",
    )
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{TAG} Starting YouTube timestamp backfill ({mode})")
    if args.limit:
        print(f"{TAG} Video limit: {args.limit}")

    skip_to = args.skip_to
    if args.resume:
        saved = _load_progress()
        if saved >= 0:
            skip_to = saved + 1
            print(f"{TAG} Resuming from progress file: skipping to video index {skip_to}")
        else:
            print(f"{TAG} No progress file found, starting from beginning")

    if skip_to:
        print(f"{TAG} Skipping first {skip_to} videos")

    fetch_delay = args.delay if args.delay > 0 else TRANSCRIPT_FETCH_DELAY

    db = BgSessionLocal()
    try:
        return _run(
            db, apply=args.apply, limit=args.limit,
            skip_to=skip_to, fetch_delay=fetch_delay,
        )
    finally:
        db.close()


def _run(db, *, apply: bool, limit: int,
         skip_to: int, fetch_delay: float) -> int:
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
    rows = db.execute(sql_text("""
        SELECT id, source_platform_id, context, exact_quote, quote_context,
               ticker, direction
        FROM predictions
        WHERE verified_by = 'youtube_haiku_v1'
          AND source_timestamp_seconds IS NULL
          AND excluded_from_training = FALSE
          AND source_platform_id IS NOT NULL
        ORDER BY source_platform_id, id
    """)).fetchall()

    if not rows:
        print(f"{TAG} No candidates found. Nothing to do.")
        return 0

    # Group by video_id.
    from collections import OrderedDict
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

    print(f"{TAG} Candidates: {total_preds} predictions across {total_videos} unique videos")
    if skipped_bad_id:
        print(f"{TAG} Skipped {skipped_bad_id} rows with unparseable source_platform_id")

    # ── Cost estimate (one Haiku call per prediction) ─────────────────────
    avg_transcript_tokens = 8_000  # conservative average
    avg_output_tokens = 80
    max_cost = total_preds * (
        (avg_transcript_tokens * HAIKU_PRICE_INPUT_PER_M / 1_000_000)
        + (avg_output_tokens * HAIKU_PRICE_OUTPUT_PER_M / 1_000_000)
    )
    print(f"{TAG} Cost estimate: ~${max_cost:.2f} for {total_preds} Haiku calls")

    # ── Lazy imports ──────────────────────────────────────────────────────
    from jobs.timestamp_matcher import match_quote_to_timestamp

    # Anthropic client for Path B (lazy, only if needed).
    _anthropic_client = None

    def _get_client():
        nonlocal _anthropic_client
        if _anthropic_client is None:
            import anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            if not api_key:
                print(f"{TAG} WARNING: ANTHROPIC_API_KEY not set. Path B disabled.")
                return None
            _anthropic_client = anthropic.Anthropic(api_key=api_key)
        return _anthropic_client

    # ── 2. Process each video ─────────────────────────────────────────────
    stats = {
        "videos_processed": 0,
        "videos_skipped_no_transcript": 0,
        "videos_timed_out": 0,
        "resolved": 0,
        "haiku_calls": 0,
        "haiku_timed_out": 0,
        "haiku_input_tokens": 0,
        "haiku_output_tokens": 0,
        "failed": 0,
        "written": 0,
    }

    videos_to_process = list(video_groups.items())
    if limit:
        videos_to_process = videos_to_process[:skip_to + limit]

    for vid_idx, (video_id, preds) in enumerate(videos_to_process):
        # Skip already-processed videos.
        if vid_idx < skip_to:
            continue

        print(f"\n{TAG} [{vid_idx}/{len(videos_to_process)}] "
              f"video={video_id}  predictions={len(preds)}", flush=True)

        # Fetch transcript with timing data + wall-clock timeout guard.
        if vid_idx > skip_to:
            time.sleep(fetch_delay)

        try:
            transcript_data = _fetch_with_timeout(video_id, timeout_sec=TRANSCRIPT_TIMEOUT)
        except FuturesTimeout:
            print(f"{TAG}   Transcript TIMEOUT ({TRANSCRIPT_TIMEOUT}s). Skipping {len(preds)} predictions.", flush=True)
            stats["videos_timed_out"] += 1
            stats["failed"] += len(preds)
            _save_progress(vid_idx)
            continue
        except Exception as e:
            print(f"{TAG}   Transcript error: {type(e).__name__}: {e}. Skipping.", flush=True)
            stats["videos_skipped_no_transcript"] += 1
            stats["failed"] += len(preds)
            _save_progress(vid_idx)
            continue

        status = transcript_data.get("status", "unknown")
        text = transcript_data.get("text", "")

        if status != "ok" or not text:
            print(f"{TAG}   Transcript failed: status={status}. Skipping {len(preds)} predictions.", flush=True)
            stats["videos_skipped_no_transcript"] += 1
            stats["failed"] += len(preds)
            _save_progress(vid_idx)
            continue

        has_words = transcript_data.get("has_word_level", False)
        seg_count = len(transcript_data.get("segments", []))
        print(f"{TAG}   Transcript OK: {len(text)} chars, {seg_count} segments, "
              f"word_level={'yes' if has_words else 'no'}", flush=True)

        stats["videos_processed"] += 1

        updates_this_video = []
        for pred in preds:
            pid = pred.id
            ticker = pred.ticker or "?"

            client = _get_client()
            if client is None:
                stats["failed"] += 1
                print(f"{TAG}   id={pid:>7d} {ticker:>6s} skipped (no API key)", flush=True)
                continue

            # Haiku extracts the verbatim quote from the transcript.
            try:
                quote, in_tok, out_tok = _call_haiku_for_quote(client, text, pred)
            except FuturesTimeout:
                stats["failed"] += 1
                stats["haiku_timed_out"] += 1
                print(f"{TAG}   id={pid:>7d} {ticker:>6s} Haiku TIMEOUT ({TRANSCRIPT_TIMEOUT}s)", flush=True)
                continue
            stats["haiku_calls"] += 1
            stats["haiku_input_tokens"] += in_tok
            stats["haiku_output_tokens"] += out_tok

            if not quote or not isinstance(quote, str) or len(quote.strip()) < 10:
                stats["failed"] += 1
                print(f"{TAG}   id={pid:>7d} {ticker:>6s} Haiku returned no quote", flush=True)
                continue

            # Run the Haiku-extracted quote through the matcher.
            seconds, method, confidence = match_quote_to_timestamp(
                quote.strip(), transcript_data,
            )

            if seconds is None:
                stats["failed"] += 1
                print(f"{TAG}   id={pid:>7d} {ticker:>6s} matcher could not place quote", flush=True)
                continue

            stats["resolved"] += 1
            updates_this_video.append({
                "id": pid,
                "seconds": int(seconds),
                "method": method,
                "quote": quote.strip()[:2000],
                "confidence": float(confidence),
            })
            print(f"{TAG}   id={pid:>7d} {ticker:>6s} resolved  "
                  f"method={method}  conf={confidence:.2f}  t={seconds}s", flush=True)

        # ── Commit after each video (incremental progress) ────────
        if apply and updates_this_video:
            written_this_video = 0
            for u in updates_this_video:
                try:
                    db.execute(sql_text("""
                        UPDATE predictions SET
                            source_timestamp_seconds = :seconds,
                            source_timestamp_method  = :method,
                            source_verbatim_quote    = :quote,
                            source_timestamp_confidence = :confidence
                        WHERE id = :id
                    """), u)
                    db.commit()
                    written_this_video += 1
                except Exception as _uerr:
                    # Statement timeout, connection drop, deadlock, etc.
                    # Rollback and continue — one failed UPDATE must not
                    # kill the whole backfill. The prediction stays NULL
                    # and will be re-picked up on the next run.
                    print(f"{TAG}   UPDATE failed for id={u.get('id')}: "
                          f"{type(_uerr).__name__}: {str(_uerr)[:150]}", flush=True)
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    stats["failed"] += 1
                    stats["resolved"] -= 1  # we counted it as resolved earlier, now revert
            stats["written"] += written_this_video
            if written_this_video:
                print(f"{TAG}   Committed {written_this_video} updates "
                      f"(total written: {stats['written']})", flush=True)

        _save_progress(vid_idx)

    # ── 3. Summary ────────────────────────────────────────────────────────
    haiku_cost = (
        (stats["haiku_input_tokens"] * HAIKU_PRICE_INPUT_PER_M / 1_000_000)
        + (stats["haiku_output_tokens"] * HAIKU_PRICE_OUTPUT_PER_M / 1_000_000)
    )

    print(f"\n{TAG} ── Summary ──")
    print(f"{TAG}   Videos processed:     {stats['videos_processed']}")
    print(f"{TAG}   Videos no transcript: {stats['videos_skipped_no_transcript']}")
    print(f"{TAG}   Videos timed out:     {stats['videos_timed_out']}")
    print(f"{TAG}   Resolved (Path B):    {stats['resolved']}")
    print(f"{TAG}   Haiku calls:          {stats['haiku_calls']}")
    print(f"{TAG}   Haiku timeouts:       {stats['haiku_timed_out']}")
    print(f"{TAG}   Haiku cost:           ${haiku_cost:.4f}")
    print(f"{TAG}   Failed (no timestamp):{stats['failed']}")
    print(f"{TAG}   Total written to DB:  {stats['written']}")

    if not apply:
        print(f"\n{TAG} DRY RUN — no DB writes. Pass --apply to commit.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
