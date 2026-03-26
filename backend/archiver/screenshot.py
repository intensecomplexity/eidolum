import os
import httpx
import hashlib
from pathlib import Path
from datetime import datetime

ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/archive")
SCREENSHOTONE_KEY = os.getenv("SCREENSHOTONE_KEY", "")


async def archive_prediction(source_url: str, prediction_id: int) -> str | None:
    """Take a screenshot of source URL and store it as proof."""
    if not source_url:
        return None
    try:
        filename = f"p{prediction_id}_{hashlib.md5(source_url.encode()).hexdigest()[:10]}.png"
        Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
        filepath = f"{ARCHIVE_DIR}/{filename}"

        if SCREENSHOTONE_KEY:
            # Use ScreenshotOne API (free tier: 100 screenshots/month)
            params = {
                "access_key": SCREENSHOTONE_KEY,
                "url": source_url,
                "viewport_width": 1280,
                "viewport_height": 800,
                "full_page": "false",
                "format": "png",
                "block_ads": "true",
                "block_cookie_banners": "true",
                "delay": 2,
            }
            r = httpx.get(
                "https://api.screenshotone.com/take",
                params=params,
                timeout=30,
            )
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                with open(filepath, "wb") as f:
                    f.write(r.content)
                print(f"[Archive] Screenshot saved: {filename}")
                return f"/archive/{filename}"
            else:
                print(f"[Archive] ScreenshotOne error {r.status_code}: {r.text[:200]}")
                return None
        else:
            # Fallback: use web.archive.org (free, no API key)
            save_url = f"https://web.archive.org/save/{source_url}"
            r = httpx.get(save_url, timeout=30, follow_redirects=True)
            if r.status_code in (200, 302, 301):
                wayback_url = f"https://web.archive.org/web/{source_url}"
                print(f"[Archive] Saved to Wayback Machine: {wayback_url}")
                return wayback_url
            else:
                print(f"[Archive] Wayback save failed: {r.status_code}")
                return None
    except Exception as e:
        print(f"[Archive] Failed for {source_url}: {e}")
        return None
