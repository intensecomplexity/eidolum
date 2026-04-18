"""One-video transcript fetcher — called as a subprocess by
grounding_wide_window_sweep.py.

Contract:
    argv[1] = YouTube video_id (11 chars)
    stdout  = JSON: {"status": str, "text": str, "segments": [...]}
    exit 0 on any outcome (including fetch errors) — the JSON status
    field carries the outcome. Any unhandled crash exits non-zero;
    parent treats that as a helper crash.

Why a subprocess: `fetch_transcript_with_timestamps` ultimately calls
into urllib3 → OpenSSL, which can block in a C-level recv() that
Python threads cannot interrupt. A subprocess CAN be killed via
subprocess.run(timeout=...) → SIGKILL, releasing its sockets cleanly.
No leaked threads, no accumulating Webshare connections.

Every import is lazy so a fast Python startup time dominates.
"""
from __future__ import annotations

import json
import os
import sys

# Allow `python3 backend/scripts/_sweep_fetch_one.py <vid>` from any CWD.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    if len(sys.argv) != 2:
        sys.stdout.write(json.dumps({
            "status": "usage_error",
            "text": "",
            "segments": [],
        }))
        return 2
    vid = sys.argv[1]
    try:
        from jobs.youtube_classifier import fetch_transcript_with_timestamps
        r = fetch_transcript_with_timestamps(vid)
    except Exception as e:
        r = {
            "status": f"exception:{type(e).__name__}",
            "text": "",
            "segments": [],
        }
    # Trim to what the sweep actually consumes. Drop non-JSON-safe
    # fields (datetimes) and the huge word-level list we don't use
    # in the ±60s window path.
    out = {
        "status": (r or {}).get("status") or "",
        "text": (r or {}).get("text") or "",
        "segments": (r or {}).get("segments") or [],
    }
    # default=str catches anything stray (datetime fragments) without
    # killing the whole write.
    sys.stdout.write(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
