"""One-off backfill: re-run match_quote_to_timestamp on YouTube predictions
that landed with source_timestamp_seconds <= 2 and confidence >= 0.99 via
method=word_level — the population most likely hit by the misanchoring bug
fixed by the first-distinctive-token anchor change.

DRY-RUN by default. Pass --commit to actually UPDATE predictions.

Usage:
  cd backend && python3 scripts/rematch_low_timestamps.py
  cd backend && python3 scripts/rematch_low_timestamps.py --commit
  cd backend && python3 scripts/rematch_low_timestamps.py --limit 10

Transcript source: video_transcripts is plain text only (the
'transcript_format' column says 'json3' but the body is just the
concatenated text — no word-level timing was ever cached). This script
therefore re-fetches the JSON3 word-timed transcript live via the same
youtube_transcript_api + Webshare proxy the classifier uses. That is
quota-free (the timedtext endpoint doesn't count against Data API
quota), but does require WEBSHARE_PROXY_USERNAME/PASSWORD to be set.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Optional

# Resolve `import jobs.timestamp_matcher`.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.abspath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import psycopg2  # noqa: E402

from jobs.timestamp_matcher import match_quote_to_timestamp  # noqa: E402


CANDIDATE_QUERY = """
  SELECT id, source_url, source_platform_id, source_verbatim_quote,
         source_timestamp_seconds AS old_ts
  FROM predictions
  WHERE source_type = 'youtube'
    AND source_timestamp_method = 'word_level'
    AND source_timestamp_confidence >= 0.99
    AND source_timestamp_seconds <= 2
    AND source_timestamp_seconds IS NOT NULL
    AND source_verbatim_quote IS NOT NULL
    AND created_at > NOW() - INTERVAL '180 days'
  ORDER BY id DESC
"""


def extract_video_id(source_platform_id: str | None, source_url: str | None) -> Optional[str]:
    """yt_{VIDEO_ID}_{TICKER} or a YouTube URL → 11-char video ID."""
    if source_platform_id and source_platform_id.startswith("yt_") and len(source_platform_id) >= 14:
        candidate = source_platform_id[3:14]
        if len(candidate) == 11:
            return candidate
    if source_url:
        # Cover ?v= and youtu.be/ forms.
        import re
        m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", source_url)
        if m:
            return m.group(1)
        m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", source_url)
        if m:
            return m.group(1)
    return None


def fetch_live_transcript(video_id: str, api) -> Optional[dict]:
    """Re-fetch the JSON3 word-timed transcript via the Webshare-proxied
    youtube_transcript_api. Returns the {words, segments, has_word_level}
    dict the matcher consumes, or None on any failure."""
    try:
        tl = api.list(video_id)
        available = list(tl)
        english = [t for t in available if t.language_code == "en"]
        eng_gen = [t for t in english if t.is_generated]
        chosen = eng_gen[0] if eng_gen else (english[0] if english else (available[0] if available else None))
        if chosen is None:
            return None
        fetched = chosen.fetch()
        segments: list[dict] = []
        for snippet in fetched:
            t = getattr(snippet, "text", None)
            if not t and isinstance(snippet, dict):
                t = snippet.get("text")
            if not t:
                continue
            start = float(getattr(snippet, "start", 0.0) or 0.0)
            dur = float(getattr(snippet, "duration", 0.0) or 0.0)
            segments.append({
                "start_ms": int(round(start * 1000)),
                "duration_ms": int(round(dur * 1000)),
                "text": t.strip(),
            })
        words: list[dict] = []
        has_word_level = False
        if getattr(chosen, "is_generated", False):
            raw_url = getattr(chosen, "_url", None)
            http = getattr(chosen, "_http_client", None)
            if raw_url and http is not None:
                json3_url = raw_url + ("&" if "?" in raw_url else "?") + "fmt=json3"
                resp = http.get(json3_url)
                if getattr(resp, "status_code", 0) == 200:
                    data = json.loads(resp.text)
                    events = data.get("events") or []
                    for ev in events:
                        s = int(ev.get("tStartMs") or 0)
                        for seg in (ev.get("segs") or []):
                            w = seg.get("utf8") or ""
                            if not w or w == "\n":
                                continue
                            off = int(seg.get("tOffsetMs") or 0)
                            words.append({"start_ms": s + off, "text": w})
                    multi = sum(1 for ev in events if len(ev.get("segs") or []) > 1)
                    has_word_level = multi > 0
        return {
            "words": words if has_word_level else None,
            "segments": segments,
            "has_word_level": has_word_level,
        }
    except Exception as e:
        print(f"  [fetch] {video_id} failed: {type(e).__name__}: {str(e)[:100]}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-anchor low-timestamp YouTube predictions.")
    ap.add_argument("--commit", action="store_true",
                    help="Actually UPDATE the rows. Without this, dry-run only.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap on rows to process (debugging).")
    ap.add_argument("--min-shift", type=int, default=3,
                    help="Minimum |new_ts - old_ts| in seconds to qualify as a shift.")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_PUBLIC_URL or DATABASE_URL must be set in env.", file=sys.stderr)
        return 2

    ws_user = os.environ.get("WEBSHARE_PROXY_USERNAME")
    ws_pass = os.environ.get("WEBSHARE_PROXY_PASSWORD")
    if not (ws_user and ws_pass):
        print("WEBSHARE_PROXY_USERNAME/PASSWORD must be set "
              "(re-fetch via datacenter IP is blocked by YouTube).",
              file=sys.stderr)
        return 2

    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import WebshareProxyConfig
    api = YouTubeTranscriptApi(
        proxy_config=WebshareProxyConfig(
            proxy_username=ws_user, proxy_password=ws_pass,
        )
    )

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(CANDIDATE_QUERY)
    rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f"Candidates: {len(rows)} rows "
          f"(method=word_level, conf>=0.99, ts<=2, last 180d)")
    print(f"Mode: {'COMMIT' if args.commit else 'DRY-RUN'}")
    print(f"Min shift: {args.min_shift}s\n")

    shifted: list[tuple[int, int, int, str, str]] = []
    skipped_no_video = 0
    skipped_no_transcript = 0
    skipped_no_word_level = 0
    skipped_no_match = 0
    unchanged = 0

    for row_idx, (pred_id, source_url, spi, quote, old_ts) in enumerate(rows, start=1):
        vid = extract_video_id(spi, source_url)
        if not vid:
            skipped_no_video += 1
            continue
        td = fetch_live_transcript(vid, api)
        if td is None:
            skipped_no_transcript += 1
            continue
        if not td.get("has_word_level"):
            skipped_no_word_level += 1
            continue
        new_seconds, method, conf = match_quote_to_timestamp(
            quote, td, enable_two_pass=False, video_id=vid,
        )
        if new_seconds is None:
            skipped_no_match += 1
            continue
        shift = new_seconds - int(old_ts)
        if abs(shift) < args.min_shift:
            unchanged += 1
            continue
        shifted.append((pred_id, int(old_ts), int(new_seconds),
                        (quote or "")[:60], vid))
        print(f"  [{row_idx}/{len(rows)}] id={pred_id} vid={vid} "
              f"old={old_ts}s new={new_seconds}s shift={shift:+d}s  "
              f"quote={(quote or '')[:60]!r}")
        if args.commit:
            cur.execute(
                """UPDATE predictions
                       SET source_timestamp_seconds = %s,
                           source_timestamp_method = 'word_level_rematched_v2'
                     WHERE id = %s""",
                (int(new_seconds), int(pred_id)),
            )

    if args.commit:
        conn.commit()

    print("\n=== Summary ===")
    print(f"  scanned:                {len(rows)}")
    print(f"  shifted (>= {args.min_shift}s):       {len(shifted)}")
    print(f"  unchanged (< {args.min_shift}s):     {unchanged}")
    print(f"  skipped (no video_id):  {skipped_no_video}")
    print(f"  skipped (no transcript):{skipped_no_transcript}")
    print(f"  skipped (no word-level):{skipped_no_word_level}")
    print(f"  skipped (no match):     {skipped_no_match}")
    if shifted:
        shifts = [new - old for (_id, old, new, _q, _v) in shifted]
        abs_shifts = [abs(s) for s in shifts]
        print(f"  shift |median|: {int(statistics.median(abs_shifts))}s")
        print(f"  shift |mean|:   {int(statistics.mean(abs_shifts))}s")
        print(f"  shift max:      {max(abs_shifts)}s")
        print(f"\n  Sample shifts (first 5):")
        for pid, o, n, q, v in shifted[:5]:
            print(f"    id={pid} vid={v} {o}s → {n}s  quote={q!r}")
    if not args.commit:
        print("\n  DRY-RUN — no rows updated. Re-run with --commit to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
