"""Verify the May 2026 YouTube expansion candidates against the
YouTube Data API.

For each handle in expansion_candidates_2026_05.CANDIDATES:
  - channels.list?forHandle=<handle>&part=snippet,statistics,contentDetails
    (1 quota unit)
  - If subscriberCount < 50k, drop.
  - playlistItems.list?playlistId=<uploads>&maxResults=1
    (1 quota unit) — use newest video's publishedAt
  - If last upload > 6 months old, drop.
  - If channel title matches an existing TARGET_CHANNELS entry, drop.

Output:
  - JSON file at backend/scripts/expansion_survivors_2026_05.json
  - One line per survivor: name, channel_id, handle, subscribers,
    last_upload_date, category
"""

from __future__ import annotations

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

from scripts.expansion_candidates_2026_05 import CANDIDATES  # noqa: E402

# Pull TARGET_CHANNELS for de-dup. Importing the monitor module loads
# httpx + sqlalchemy etc. — fine for a script run.
from jobs.youtube_channel_monitor import TARGET_CHANNELS  # noqa: E402


API = "https://www.googleapis.com/youtube/v3"
API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not API_KEY:
    print("YOUTUBE_API_KEY is required", file=sys.stderr)
    sys.exit(2)

MIN_SUBS = 50_000
MAX_AGE = timedelta(days=183)  # ~6 months
OUTPUT = HERE / "expansion_survivors_2026_05.json"
NOW = datetime.now(timezone.utc)

# Crude category bucketing — re-uses the section comments from the
# candidates file. Maps line-range slices to a label so survivor output
# stays grouped.
CATEGORIES: list[tuple[int, str]] = [
    (25, "Macro / Economy"),
    (37, "Value / Fundamental"),
    (50, "Trading / Technical"),
    (61, "News / Mainstream"),
    (75, "Personal Finance"),
    (83, "Semis / Hardware"),
    (91, "EV / Auto"),
    (105, "Crypto"),
    (118, "UK / Europe"),
    (133, "India"),
    (138, "Australia / NZ"),
    (144, "Canada"),
    (147, "LatAm / Spain"),
    (151, "Quant"),
    (10**6, "Sector / Specialty"),
]


def _category_for(idx: int) -> str:
    for cutoff, name in CATEGORIES:
        if idx < cutoff:
            return name
    return "Other"


def _fetch_channel(handle: str) -> Optional[dict]:
    """Return the channel resource dict for a handle, or None."""
    r = httpx.get(
        f"{API}/channels",
        params={
            "forHandle": handle,
            "part": "snippet,statistics,contentDetails",
            "key": API_KEY,
        },
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  [HTTP {r.status_code}] {handle}: {r.text[:200]}")
        return None
    items = r.json().get("items") or []
    return items[0] if items else None


def _last_upload(uploads_playlist: str) -> Optional[datetime]:
    """Return publishedAt of the newest video in the uploads playlist."""
    r = httpx.get(
        f"{API}/playlistItems",
        params={
            "playlistId": uploads_playlist,
            "part": "contentDetails",
            "maxResults": 1,
            "key": API_KEY,
        },
        timeout=15,
    )
    if r.status_code != 200:
        return None
    items = r.json().get("items") or []
    if not items:
        return None
    pub = (items[0].get("contentDetails") or {}).get("videoPublishedAt")
    if not pub:
        return None
    try:
        return datetime.strptime(pub[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def main() -> None:
    existing_names = {n.strip().lower() for n in TARGET_CHANNELS}
    survivors: list[dict] = []
    rejected: list[dict] = []
    api_units = 0

    for idx, handle in enumerate(CANDIDATES):
        cat = _category_for(idx)
        print(f"[{idx + 1}/{len(CANDIDATES)}] {handle:<40} ", end="", flush=True)

        chan = _fetch_channel(handle)
        api_units += 1
        if not chan:
            print("✗ not found")
            rejected.append({"handle": handle, "reason": "not_found", "category": cat})
            continue

        title = (chan.get("snippet") or {}).get("title") or ""
        cid = chan.get("id")
        subs_raw = ((chan.get("statistics") or {}).get("subscriberCount")) or "0"
        try:
            subs = int(subs_raw)
        except (TypeError, ValueError):
            subs = 0
        uploads = (
            ((chan.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") or ""
        )

        if title.strip().lower() in existing_names:
            print(f"✗ already in TARGET_CHANNELS ({title})")
            rejected.append({
                "handle": handle, "title": title, "channel_id": cid,
                "reason": "duplicate", "subscribers": subs, "category": cat,
            })
            continue

        if subs < MIN_SUBS:
            print(f"✗ {subs:,} subs ({title})")
            rejected.append({
                "handle": handle, "title": title, "channel_id": cid,
                "reason": "below_sub_floor", "subscribers": subs, "category": cat,
            })
            continue

        last = _last_upload(uploads) if uploads else None
        api_units += 1
        if last is None:
            print(f"✗ no uploads ({title}, {subs:,})")
            rejected.append({
                "handle": handle, "title": title, "channel_id": cid,
                "reason": "no_uploads", "subscribers": subs, "category": cat,
            })
            continue

        age = NOW - last
        if age > MAX_AGE:
            print(f"✗ stale ({title}, last {last.date()})")
            rejected.append({
                "handle": handle, "title": title, "channel_id": cid,
                "reason": "stale", "subscribers": subs,
                "last_upload_date": last.date().isoformat(), "category": cat,
            })
            continue

        print(f"✓ {subs:,} subs, last {last.date()}  ({title})")
        survivors.append({
            "name": title,
            "channel_id": cid,
            "handle": handle,
            "subscribers": subs,
            "last_upload_date": last.date().isoformat(),
            "category": cat,
        })
        # YouTube quota burns are cheap, but pause briefly to be polite.
        time.sleep(0.05)

    OUTPUT.write_text(
        json.dumps(
            {
                "generated_at": NOW.isoformat(),
                "candidates_total": len(CANDIDATES),
                "survivors_total": len(survivors),
                "rejected_total": len(rejected),
                "api_units_used": api_units,
                "survivors": survivors,
                "rejected": rejected,
            },
            indent=2,
        )
    )
    print(
        f"\nDone. {len(survivors)}/{len(CANDIDATES)} survived. "
        f"{api_units} API units used. Output → {OUTPUT}"
    )


if __name__ == "__main__":
    main()
