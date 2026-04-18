"""Scheduled worker: backfill source_timestamp_seconds on legacy
YouTube predictions whose timestamp was never resolved.

Runs independently of the channel monitor and the video backfill —
its own APScheduler interval, own DB session, own cursor. Must not
pause, slow, or share state with either existing job.

Per cycle:
  1. SELECT distinct video_ids from predictions where
     source_type='youtube' AND source_timestamp_seconds IS NULL,
     newest-first (most user-visible first), limit = batch_size.
  2. For each video:
       a. Fetch rich transcript (same helper the channel monitor uses).
       b. On unavailable / deleted / private / geo-blocked: stamp
          youtube_backfill_unrecoverable(video_id, reason,
          last_attempted_at) and continue. No infinite retries — the
          SELECT filter excludes rows stamped within the last
          UNRECOVERABLE_RETRY_DAYS.
       c. On available: for each prediction under this video, call
          Qwen to extract a verbatim quote, then run
          match_quote_to_timestamp → UPDATE the row in place.
  3. Commit PER PREDICTION (not per video) — a failure mid-video
     doesn't roll back the already-resolved rows.
  4. Rate-limit to one video/sec so the transcript fetcher's IP pool
     isn't hammered.

The hard gate in youtube_classifier.insert_youtube_prediction does
NOT apply here — this worker only UPDATEs existing rows, never
INSERTs. The visibility filter in services/prediction_visibility.py
picks up the UPDATE automatically because it keys off the NULL check.

Entry points:
    # scheduled batch
    from jobs.youtube_timestamp_backfill import run_timestamp_backfill
    run_timestamp_backfill(batch_size=20)

    # single video, useful for ad-hoc verification
    python -m jobs.youtube_timestamp_backfill --video <VIDEO_ID>

    # small batch dry-run
    python -m jobs.youtube_timestamp_backfill --batch 3 --dry-run
"""
import argparse
import logging
import os
import sys
import time

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text  # noqa: E402

log = logging.getLogger(__name__)
TAG = "[YT-TS-Backfill2]"  # differs from backfill_youtube_timestamps' TAG

DEFAULT_BATCH_SIZE = 20
DEFAULT_RATE_LIMIT_SEC = 1.0
UNRECOVERABLE_RETRY_DAYS = 30

# Transcript-fetch statuses that are TRULY terminal — the captions will
# never come back, so it's safe to stamp youtube_backfill_unrecoverable
# and skip the video for UNRECOVERABLE_RETRY_DAYS.
# Everything else (network ReadTimeout, FuturesTimeout, "error: ...",
# "library_missing", "no_video_id") is treated as transient: log, skip
# this cycle, leave the row NULL so the next cycle re-picks it up.
TERMINAL_TRANSCRIPT_STATUSES = frozenset({
    "no_transcript",
    "transcripts_disabled",
    "video_unavailable",
    "empty_transcript",
})


def ensure_unrecoverable_table(db) -> None:
    """Idempotent DDL. Records video_ids whose transcripts are
    unfetchable so we don't re-try them for UNRECOVERABLE_RETRY_DAYS."""
    try:
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS youtube_backfill_unrecoverable (
                video_id VARCHAR(11) PRIMARY KEY,
                reason TEXT,
                last_attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                attempt_count INTEGER NOT NULL DEFAULT 1
            )
        """))
        db.commit()
    except Exception as e:
        log.warning("%s ensure_unrecoverable_table failed: %s", TAG, e)
        try:
            db.rollback()
        except Exception:
            pass


def _select_video_ids_to_process(db, batch_size: int) -> list[str]:
    """Newest-first distinct video_ids extracted from source_url.

    Excludes videos marked unrecoverable within
    UNRECOVERABLE_RETRY_DAYS. Uses a POSIX-class regex so the path
    works on any YouTube URL shape (watch?v=XXX, watch?v=XXX&t=...,
    etc.).
    """
    rows = db.execute(sql_text(f"""
        SELECT vid FROM (
            SELECT substring(source_url FROM 'v=([A-Za-z0-9_-]{{11}})') AS vid,
                   MAX(prediction_date) AS newest_pred
            FROM predictions
            WHERE source_type = 'youtube'
              AND source_timestamp_seconds IS NULL
              AND source_url LIKE '%v=%'
            GROUP BY substring(source_url FROM 'v=([A-Za-z0-9_-]{{11}})')
        ) q
        WHERE vid IS NOT NULL
          AND vid NOT IN (
              SELECT video_id FROM youtube_backfill_unrecoverable
              WHERE last_attempted_at > NOW() - INTERVAL '{int(UNRECOVERABLE_RETRY_DAYS)} days'
          )
        ORDER BY newest_pred DESC NULLS LAST
        LIMIT :lim
    """), {"lim": int(batch_size)}).fetchall()
    return [r[0] for r in rows if r[0]]


def _load_preds_for_video(db, video_id: str) -> list:
    """Pull every NULL-ts prediction whose source_url carries this
    video_id. Returns a lightweight row-like object with the fields
    _build_quote_user_msg needs."""
    rows = db.execute(sql_text("""
        SELECT id, ticker, direction, context, exact_quote,
               source_verbatim_quote, source_platform_id
        FROM predictions
        WHERE source_type = 'youtube'
          AND source_timestamp_seconds IS NULL
          AND source_url LIKE '%v=' || :vid || '%'
    """), {"vid": video_id}).fetchall()
    out = []
    for r in rows:
        out.append(_PredRow(
            id=r[0], ticker=r[1], direction=r[2],
            context=r[3], exact_quote=r[4],
            source_verbatim_quote=r[5],
            source_platform_id=r[6],
        ))
    return out


class _PredRow:
    """Minimal row object exposing the attributes _build_quote_user_msg
    and _call_qwen_for_quote look up via getattr."""
    __slots__ = ("id", "ticker", "direction", "context", "exact_quote",
                 "source_verbatim_quote", "source_platform_id")

    def __init__(self, id, ticker, direction, context, exact_quote,
                 source_verbatim_quote, source_platform_id):
        self.id = id
        self.ticker = ticker
        self.direction = direction
        self.context = context
        self.exact_quote = exact_quote
        self.source_verbatim_quote = source_verbatim_quote
        self.source_platform_id = source_platform_id


def _mark_unrecoverable(db, video_id: str, reason: str) -> None:
    try:
        db.execute(sql_text("""
            INSERT INTO youtube_backfill_unrecoverable
              (video_id, reason, last_attempted_at, attempt_count)
            VALUES (:vid, :r, NOW(), 1)
            ON CONFLICT (video_id) DO UPDATE SET
              reason = EXCLUDED.reason,
              last_attempted_at = NOW(),
              attempt_count = youtube_backfill_unrecoverable.attempt_count + 1
        """), {"vid": video_id, "r": (reason or "unknown")[:200]})
        db.commit()
    except Exception as e:
        log.warning("%s mark_unrecoverable failed for %s: %s", TAG, video_id, e)
        try:
            db.rollback()
        except Exception:
            pass


def _apply_update(db, pred_id: int, seconds: int, method: str,
                  confidence: float, verbatim_quote: str,
                  *, dry_run: bool) -> bool:
    if dry_run:
        log.info("%s [DRY] id=%s → seconds=%s method=%s conf=%.2f",
                 TAG, pred_id, seconds, method, confidence)
        return True
    try:
        db.execute(sql_text("""
            UPDATE predictions
            SET source_timestamp_seconds = :s,
                source_timestamp_method = :m,
                source_timestamp_confidence = :c,
                source_verbatim_quote = COALESCE(source_verbatim_quote, :q)
            WHERE id = :pid
              AND source_timestamp_seconds IS NULL
        """), {"s": int(seconds), "m": (method or "unknown")[:32],
               "c": float(confidence or 0.0),
               "q": (verbatim_quote or "")[:2000],
               "pid": int(pred_id)})
        db.commit()
        return True
    except Exception as e:
        log.warning("%s UPDATE failed for id=%s: %s", TAG, pred_id, e)
        try:
            db.rollback()
        except Exception:
            pass
        return False


def backfill_one_video(db, video_id: str, *, dry_run: bool = False) -> dict:
    """Process a single video. Returns per-video stats dict."""
    from jobs.backfill_youtube_timestamps import (
        _fetch_with_timeout, _call_qwen_for_quote,
    )
    from jobs.timestamp_matcher import match_quote_to_timestamp

    stats = {
        "video_id": video_id, "preds": 0,
        "updated": 0, "match_failed": 0, "no_quote": 0,
        "unrecoverable": False, "error": None,
    }
    preds = _load_preds_for_video(db, video_id)
    stats["preds"] = len(preds)
    if not preds:
        return stats

    # ── Transcript fetch (same helper as the channel monitor) ──
    # Only TERMINAL statuses (see TERMINAL_TRANSCRIPT_STATUSES) stamp the
    # unrecoverable table. Network / timeout / transient library errors
    # leave the row NULL — the next cycle will re-pick it up.
    try:
        transcript = _fetch_with_timeout(video_id)
    except Exception as e:
        reason = f"fetch_exception:{type(e).__name__}"
        log.info("%s %s transient fetch error, will retry: %s",
                 TAG, video_id, reason)
        stats["error"] = reason
        return stats

    status = (transcript or {}).get("status") or ""
    text = (transcript or {}).get("text") or ""
    if status in TERMINAL_TRANSCRIPT_STATUSES or (status == "ok" and not text.strip()):
        terminal_reason = status or "empty"
        _mark_unrecoverable(db, video_id, terminal_reason)
        stats["unrecoverable"] = True
        stats["error"] = terminal_reason
        return stats
    if status != "ok":
        log.info("%s %s transient transcript status, will retry: %s",
                 TAG, video_id, status)
        stats["error"] = status
        return stats

    # ── Per-prediction quote extraction + timestamp match ──
    # Qwen only — Haiku credit balance is currently too low (see
    # reference_anthropic_api_billing memory). Qwen is serverless
    # and auto-scales, so per-prediction calls are safe.
    for row in preds:
        try:
            quote, reason, _cost = _call_qwen_for_quote(text, row)
        except Exception as e:
            log.info("%s id=%s Qwen quote call failed: %s",
                     TAG, row.id, type(e).__name__)
            stats["no_quote"] += 1
            continue

        if not quote or not isinstance(quote, str):
            log.info(
                "%s qwen_null pred_id=%s video=%s ticker=%s reason=%s",
                TAG, row.id, video_id, row.ticker,
                reason or "qwen_returned_null",
            )
            stats["no_quote"] += 1
            continue

        try:
            seconds, method, confidence = match_quote_to_timestamp(
                quote, transcript, enable_two_pass=False,
            )
        except Exception as e:
            log.info("%s id=%s matcher error: %s",
                     TAG, row.id, type(e).__name__)
            stats["match_failed"] += 1
            continue

        if seconds is None:
            stats["match_failed"] += 1
            continue

        if _apply_update(db, row.id, seconds, method, confidence,
                         quote, dry_run=dry_run):
            stats["updated"] += 1

    return stats


def run_timestamp_backfill(
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
    dry_run: bool = False,
    single_video: str | None = None,
) -> dict:
    """Entry point used by the APScheduler job and CLI."""
    # Kill-switch for emergency pauses (e.g. Qwen hallucination incidents).
    # Default on — explicit "false"/"0"/"no"/"off" disables. Flip via
    # `railway variables --set ENABLE_YT_TIMESTAMP_BACKFILL=false`.
    _enabled = os.getenv("ENABLE_YT_TIMESTAMP_BACKFILL", "true").strip().lower()
    if _enabled in ("false", "0", "no", "off"):
        log.info("%s paused via ENABLE_YT_TIMESTAMP_BACKFILL=%s — skipping cycle",
                 TAG, _enabled)
        return {"videos_scanned": 0, "paused": True}
    from database import BgSessionLocal
    db = BgSessionLocal()
    try:
        ensure_unrecoverable_table(db)
        if single_video:
            vids = [single_video]
        else:
            vids = _select_video_ids_to_process(db, batch_size)

        totals = {
            "videos_scanned": 0,
            "videos_updated": 0,
            "videos_unrecoverable": 0,
            "preds_updated": 0,
            "preds_match_failed": 0,
            "preds_no_quote": 0,
        }
        if not vids:
            log.info("%s no videos queued for backfill", TAG)
            return totals

        log.info("%s starting cycle — %d video(s) queued", TAG, len(vids))
        for vid in vids:
            r = backfill_one_video(db, vid, dry_run=dry_run)
            totals["videos_scanned"] += 1
            if r["unrecoverable"]:
                totals["videos_unrecoverable"] += 1
            if r["updated"] > 0:
                totals["videos_updated"] += 1
            totals["preds_updated"] += r["updated"]
            totals["preds_match_failed"] += r["match_failed"]
            totals["preds_no_quote"] += r["no_quote"]
            log.info(
                "%s %s: preds=%d updated=%d no_quote=%d match_failed=%d "
                "unrecoverable=%s",
                TAG, vid, r["preds"], r["updated"], r["no_quote"],
                r["match_failed"], r["unrecoverable"],
            )
            if rate_limit_sec > 0:
                time.sleep(rate_limit_sec)

        log.info("%s cycle complete — %s", TAG, totals)
        return totals
    finally:
        db.close()


# ── CLI entry point ─────────────────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--video", type=str, default=None,
                        help="process a single video_id")
    parser.add_argument("--dry-run", action="store_true",
                        help="do not commit UPDATEs")
    parser.add_argument("--rate-limit", type=float,
                        default=DEFAULT_RATE_LIMIT_SEC)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if not args.verbose else logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    totals = run_timestamp_backfill(
        batch_size=args.batch,
        rate_limit_sec=args.rate_limit,
        dry_run=args.dry_run,
        single_video=args.video,
    )
    print(totals)


if __name__ == "__main__":
    _cli()
