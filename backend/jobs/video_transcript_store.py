"""
Evidence preservation: store the full YouTube transcript at scrape time.

Why: if a forecaster deletes their video, we still have an immutable
record of what they said, when we captured it, and a SHA256 hash
locked at capture time. The verbatim quote on each prediction can
be verified against the stored transcript at any point in the future
without depending on YouTube being available.

One row per video_id, not per prediction — many predictions can come
from the same video. First capture wins (ON CONFLICT DO NOTHING).

The capture function never raises to the caller. Any storage failure
degrades to a logged warning so the prediction pipeline is unaffected.
"""
import hashlib
import logging

from sqlalchemy import text as sql_text

log = logging.getLogger(__name__)

TAG = "[transcript-store]"


def ensure_video_transcripts_table(db) -> None:
    """Idempotent DDL. Safe to call at startup or lazily before first use.
    The worker.py startup block also runs this, but calling it here
    means the helper is self-sufficient for ad-hoc scripts."""
    try:
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS video_transcripts (
                id SERIAL PRIMARY KEY,
                video_id VARCHAR(11) NOT NULL UNIQUE,
                channel_name TEXT,
                video_title TEXT,
                video_publish_date TIMESTAMPTZ,
                transcript_text TEXT NOT NULL,
                transcript_format VARCHAR(20) DEFAULT 'json3',
                sha256_hash VARCHAR(64) NOT NULL,
                captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                video_url TEXT GENERATED ALWAYS AS
                    ('https://www.youtube.com/watch?v=' || video_id) STORED
            )
        """))
        db.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_video_transcripts_video_id "
            "ON video_transcripts(video_id)"
        ))
        db.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_video_transcripts_captured_at "
            "ON video_transcripts(captured_at)"
        ))
        db.commit()
    except Exception as e:
        log.warning(f"{TAG} ensure_table failed: {type(e).__name__}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def compute_sha256(text: str) -> str:
    """Stable SHA256 of the transcript text as UTF-8."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def capture_transcript(
    db,
    *,
    video_id: str,
    channel_name: str | None,
    video_title: str | None,
    video_publish_date,
    transcript_text: str,
    transcript_format: str = "json3",
) -> bool:
    """Store the full transcript for a video. Idempotent — ON CONFLICT
    DO NOTHING so re-running the backfill or re-scraping the same video
    doesn't overwrite the first capture (which is what 'captured_at'
    attests to).

    Returns True on successful insert, False on conflict or failure.
    NEVER raises — any error is logged and swallowed so the prediction
    pipeline can't be broken by transcript storage.
    """
    if not video_id or not transcript_text:
        return False
    try:
        sha = compute_sha256(transcript_text)
        result = db.execute(sql_text("""
            INSERT INTO video_transcripts (
                video_id, channel_name, video_title, video_publish_date,
                transcript_text, transcript_format, sha256_hash
            ) VALUES (
                :vid, :ch, :title, :pub, :txt, :fmt, :sha
            )
            ON CONFLICT (video_id) DO NOTHING
        """), {
            "vid": video_id[:11],
            "ch": (channel_name or "")[:500] or None,
            "title": (video_title or "")[:500] or None,
            "pub": video_publish_date,
            "txt": transcript_text,
            "fmt": transcript_format[:20],
            "sha": sha,
        })
        db.commit()
        return result.rowcount > 0
    except Exception as e:
        log.warning(f"{TAG} capture failed for video_id={video_id}: "
                    f"{type(e).__name__}: {str(e)[:200]}")
        try:
            db.rollback()
        except Exception:
            pass
        return False


def excerpt_around_quote(transcript_text: str, quote: str, window: int = 250) -> str:
    """Return a ~window*2 char excerpt centered on the quote's position
    in the transcript. Falls back to the first window*2 chars if the
    quote isn't found via substring search."""
    if not transcript_text:
        return ""
    if not quote:
        return transcript_text[: window * 2]
    # Try exact substring first (works for most cases since Haiku's
    # verbatim_quote is copied from the transcript).
    idx = transcript_text.find(quote[:100])  # first 100 chars of quote
    if idx < 0:
        # Fall back to a normalized lowercase search.
        lower = transcript_text.lower()
        idx = lower.find(quote[:100].lower())
    if idx < 0:
        return transcript_text[: window * 2]
    start = max(0, idx - window)
    end = min(len(transcript_text), idx + len(quote) + window)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(transcript_text) else ""
    return prefix + transcript_text[start:end] + suffix
