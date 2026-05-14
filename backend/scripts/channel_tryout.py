"""Channel tryout — 5-video dry-run test for candidate YouTube channels.

For each handle:
  1. Resolve via channels.list?forHandle
  2. Fetch 15 most-recent uploads
  3. videos.list for durations; drop Shorts (≤60s) and keep first 5
  4. For each of the 5: fetch transcript via Webshare-proxied
     youtube-transcript-api → chunk → call_runpod_vllm → parse JSON
  5. Verdict: PASS if any video produced ≥1 prediction, else REJECT

Writes nothing to youtube_videos / predictions / rejections — the
production classify_video path is intentionally skipped because it
applies the timestamp-matcher gate that rejects predictions wholesale
on auto-captioned transcripts. For tryout we want raw "did the
classifier extract anything", which is `call_runpod_vllm` + JSON parse.

Usage:
  python3 backend/scripts/channel_tryout.py @handle1 @handle2 ...
  python3 backend/scripts/channel_tryout.py --from-file path/to/handles.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from jobs.youtube_classifier import (  # noqa: E402
    chunk_transcript,
    call_runpod_vllm,
    fetch_transcript_with_timestamps,
)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

API_KEY = (
    os.environ.get("YOUTUBE_DATA_API_KEY")
    or os.environ.get("YOUTUBE_API_KEY")
)
if not API_KEY:
    print("YOUTUBE_DATA_API_KEY (or YOUTUBE_API_KEY) required", file=sys.stderr)
    sys.exit(2)

SHORT_DURATION_CAP = 60       # seconds — drop Shorts
VIDEOS_TO_TEST_PER_CHANNEL = 5
VIDEOS_TO_FETCH = 15          # pull more than we need so Shorts-filter doesn't starve us
SAMPLE_PREDS_PER_CHANNEL = 5  # how many sample preds to surface in output


def _iso_duration_to_seconds(s: str) -> int:
    import re as _re
    if not s or not s.startswith("PT"):
        return 0
    m = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return 0
    h, mn, sc = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mn * 60 + sc


def _resolve_handle(handle: str) -> Optional[dict]:
    """channels.list?forHandle → snippet+statistics+contentDetails."""
    h = handle if handle.startswith("@") else "@" + handle
    r = httpx.get(
        f"{YOUTUBE_API}/channels",
        params={
            "forHandle": h,
            "part": "snippet,statistics,contentDetails",
            "key": API_KEY,
        },
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  channels.list HTTP {r.status_code}: {r.text[:150]}")
        return None
    items = r.json().get("items") or []
    return items[0] if items else None


def _recent_videos(uploads_playlist: str, n: int = VIDEOS_TO_FETCH) -> list[dict]:
    """playlistItems.list → most-recent N videos."""
    r = httpx.get(
        f"{YOUTUBE_API}/playlistItems",
        params={
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": n,
            "key": API_KEY,
        },
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  playlistItems.list HTTP {r.status_code}: {r.text[:150]}")
        return []
    out = []
    for it in r.json().get("items") or []:
        snip = it.get("snippet") or {}
        cd = it.get("contentDetails") or {}
        vid = cd.get("videoId")
        if not vid:
            continue
        out.append({
            "video_id": vid,
            "title": snip.get("title") or "",
            "published_at": cd.get("videoPublishedAt") or snip.get("publishedAt") or "",
        })
    return out


def _video_durations(video_ids: list[str]) -> dict[str, int]:
    if not video_ids:
        return {}
    r = httpx.get(
        f"{YOUTUBE_API}/videos",
        params={
            "part": "contentDetails",
            "id": ",".join(video_ids[:50]),
            "key": API_KEY,
        },
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  videos.list HTTP {r.status_code}: {r.text[:150]}")
        return {}
    out = {}
    for it in r.json().get("items") or []:
        vid = it.get("id")
        dur = (it.get("contentDetails") or {}).get("duration") or ""
        out[vid] = _iso_duration_to_seconds(dur)
    return out


def _strip_md_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _classify_video_raw(
    video_id: str, title: str, publish: str, channel_name: str,
) -> tuple[int, list[dict], str]:
    """Fetch transcript → chunk → call Pavilion per chunk → parse → count.
    Returns (prediction_count, predictions, status_tag).
    No DB writes, no production gates applied.
    """
    rich = {}
    text = ""
    for _ in range(2):
        rich = fetch_transcript_with_timestamps(video_id)
        text = rich.get("text") or ""
        if text:
            break
        time.sleep(1)
    if not text:
        return 0, [], f"no_transcript:{rich.get('status', 'unknown')}"
    lang = rich.get("lang")
    chunks = chunk_transcript(text, lang=lang)

    preds: list[dict] = []
    chunk_status = "ok"
    for i, chunk in enumerate(chunks):
        try:
            raw_text, _cost, _lat = call_runpod_vllm(
                chunk, channel_name=channel_name, title=title,
                publish_date=publish[:10], video_id=video_id,
            )
        except Exception as e:
            chunk_status = f"chunk_{i+1}_err:{type(e).__name__}"
            continue
        content = _strip_md_fences(raw_text)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            chunk_status = f"chunk_{i+1}_parse_err"
            continue
        if isinstance(parsed, dict):
            parsed = [parsed]
        if isinstance(parsed, list):
            for p in parsed:
                if isinstance(p, dict) and p.get("ticker"):
                    preds.append(p)
    return len(preds), preds, chunk_status


def _format_sample(p: dict) -> str:
    ticker = p.get("ticker") or "?"
    direction = p.get("direction") or "?"
    quote = (
        p.get("source_verbatim_quote")
        or p.get("verbatim_quote")
        or p.get("quote")
        or ""
    )
    quote = quote.strip().replace("\n", " ")
    if len(quote) > 100:
        quote = quote[:97] + "..."
    return f"{ticker} {direction} — {quote}" if quote else f"{ticker} {direction}"


def tryout_channel(handle: str) -> dict:
    print(f"\n=== {handle} ===")
    t0 = time.monotonic()
    chan = _resolve_handle(handle)
    if not chan:
        print("  not found")
        return {
            "handle": handle, "verdict": "NOT_FOUND",
            "videos_tested": 0, "videos_with_prediction": 0,
            "total_predictions": 0, "sample_predictions": [],
        }
    cid = chan.get("id")
    name = (chan.get("snippet") or {}).get("title") or ""
    subs_raw = (chan.get("statistics") or {}).get("subscriberCount") or "0"
    subs = int(subs_raw) if subs_raw.isdigit() else 0
    uploads = (
        ((chan.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        or ""
    )
    print(f"  resolved → {name} ({cid}, {subs:,} subs)")
    if not uploads:
        return {
            "handle": handle, "channel_id": cid, "channel_name": name,
            "subscriber_count": subs, "verdict": "NO_UPLOADS_PLAYLIST",
            "videos_tested": 0, "videos_with_prediction": 0,
            "total_predictions": 0, "sample_predictions": [],
        }

    recent = _recent_videos(uploads, VIDEOS_TO_FETCH)
    durations = _video_durations([v["video_id"] for v in recent])
    keep: list[dict] = []
    for v in recent:
        d = durations.get(v["video_id"], 0)
        if 0 < d <= SHORT_DURATION_CAP:
            continue
        keep.append(v)
        if len(keep) >= VIDEOS_TO_TEST_PER_CHANNEL:
            break
    print(f"  pulled {len(recent)} recent → keeping {len(keep)} non-Shorts")
    if not keep:
        return {
            "handle": handle, "channel_id": cid, "channel_name": name,
            "subscriber_count": subs, "verdict": "NO_TESTABLE_VIDEOS",
            "videos_tested": 0, "videos_with_prediction": 0,
            "total_predictions": 0, "sample_predictions": [],
        }

    total_preds = 0
    videos_with_pred = 0
    all_preds: list[dict] = []
    per_video: list[dict] = []
    for i, v in enumerate(keep, 1):
        v_t0 = time.monotonic()
        n, preds, status = _classify_video_raw(
            v["video_id"], v["title"], v["published_at"], name,
        )
        v_elapsed = time.monotonic() - v_t0
        print(f"    [{i}/{len(keep)}] {v['video_id']} ({v['title'][:50]:<50}) "
              f"→ {n} preds in {v_elapsed:.1f}s ({status})")
        total_preds += n
        if n > 0:
            videos_with_pred += 1
            all_preds.extend(preds)
        per_video.append({
            "video_id": v["video_id"],
            "title": v["title"],
            "published_at": v["published_at"],
            "predictions": n,
            "status": status,
            "elapsed_s": round(v_elapsed, 1),
        })

    elapsed = time.monotonic() - t0
    verdict = "PASS" if videos_with_pred >= 1 else "REJECT"
    samples = [_format_sample(p) for p in all_preds[:SAMPLE_PREDS_PER_CHANNEL]]
    print(f"  → verdict {verdict} | {videos_with_pred}/{len(keep)} videos had ≥1 "
          f"pred | {total_preds} total preds | {elapsed:.1f}s")
    return {
        "handle": handle,
        "channel_id": cid,
        "channel_name": name,
        "subscriber_count": subs,
        "videos_tested": len(keep),
        "videos_with_prediction": videos_with_pred,
        "total_predictions": total_preds,
        "verdict": verdict,
        "sample_predictions": samples,
        "per_video": per_video,
        "elapsed_seconds": round(elapsed, 1),
    }


def _try_mount() -> bool:
    """Best-effort remount of /mnt/g via passwordless sudo (only if
    SUDO_PASSWORD is in env). Caller still has to verify accessibility.
    """
    pw = os.environ.get("SUDO_PASSWORD")
    if not pw:
        return False
    import subprocess
    p = subprocess.run(
        ["sudo", "-S", "mount", "-t", "drvfs", "G:", "/mnt/g"],
        input=pw + "\n", capture_output=True, text=True, timeout=15,
    )
    return p.returncode == 0


def write_result(out_path: Path, payload: dict) -> None:
    """Drive-only write. One remount retry. Fail loudly if Drive is gone."""
    def _drive_ready():
        return out_path.parent.exists()

    if not _drive_ready():
        print(f"\n[write] {out_path.parent} not accessible — trying one remount")
        _try_mount()
        if not _drive_ready():
            # Fail loudly. Per the user's SACRED PATH rule, no local fallback.
            print("\n" + "=" * 70, file=sys.stderr)
            print("FATAL: Drive output path is detached:", file=sys.stderr)
            print(f"  {out_path}", file=sys.stderr)
            print("\nMount manually:", file=sys.stderr)
            print("  sudo mount -t drvfs G: /mnt/g", file=sys.stderr)
            print("\nThe collected tryout payload is printed below (json),", file=sys.stderr)
            print("save it manually if needed so the classifier calls aren't", file=sys.stderr)
            print("wasted:", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            print(json.dumps(payload, indent=2))
            sys.exit(3)
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\n[write] wrote {out_path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("handles", nargs="*", help="@handle args (positional)")
    p.add_argument("--from-file", type=Path,
                   help="JSON file with a top-level 'handles' list")
    p.add_argument("--out", type=Path,
                   default=Path("/mnt/g/My Drive/eidolum.prompts/_done/2026-05-14-channel-tryout-result.json"),
                   help="Drive output path")
    args = p.parse_args()

    handles: list[str] = list(args.handles)
    if args.from_file:
        loaded = json.loads(args.from_file.read_text())
        handles.extend(loaded.get("handles", []))
    handles = [h if h.startswith("@") else f"@{h}" for h in handles]
    if not handles:
        print("no handles provided", file=sys.stderr)
        return 2

    print(f"[tryout] testing {len(handles)} candidates")
    results = [tryout_channel(h) for h in handles]
    payload = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "videos_per_channel": VIDEOS_TO_TEST_PER_CHANNEL,
        "results": results,
    }
    write_result(args.out, payload)

    print("\n=== one-liner summary ===")
    for r in results:
        v = r.get("verdict", "?")
        name = r.get("channel_name") or r.get("handle")
        n_pred = r.get("total_predictions", 0)
        n_vids = r.get("videos_with_prediction", 0)
        tested = r.get("videos_tested", 0)
        subs = r.get("subscriber_count", 0)
        print(f"  {v:<10}  {name:<32} {n_vids}/{tested} vids w/ pred, "
              f"{n_pred} total preds  ({subs:,} subs)")

    n_pass = sum(1 for r in results if r.get("verdict") == "PASS")
    print(f"\nfinal: {n_pass}/{len(results)} channels PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
