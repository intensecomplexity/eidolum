import os
import httpx
import hashlib
from pathlib import Path
from datetime import datetime

ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/archive")
SCREENSHOTONE_KEY = os.getenv("SCREENSHOTONE_KEY", "")


async def take_screenshot(source_url: str, prediction_id: int) -> str | None:
    """
    Take a screenshot of source_url and save it permanently to our server.
    Returns the local path /archive/filename.png or None if failed.
    Screenshots on our server only — no external archive services.
    """
    if not source_url or not SCREENSHOTONE_KEY:
        if not SCREENSHOTONE_KEY:
            print(f"[Archive] No SCREENSHOTONE_KEY set — cannot screenshot prediction {prediction_id}")
        return None

    try:
        filename = f"p{prediction_id}_{hashlib.md5(source_url.encode()).hexdigest()[:10]}.png"
        Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
        filepath = f"{ARCHIVE_DIR}/{filename}"

        if Path(filepath).exists():
            return f"/archive/{filename}"

        # Platform-specific screenshot settings
        delay = 3
        selector = None
        if "x.com" in source_url or "twitter.com" in source_url:
            delay = 4
            selector = "article[data-testid='tweet']"
        elif "reddit.com" in source_url:
            delay = 3
            selector = "shreddit-post,div[data-testid='post-container'],.Post"
        elif "youtube.com" in source_url:
            delay = 5
            selector = "#above-the-fold,#primary-inner"

        params = {
            "access_key": SCREENSHOTONE_KEY,
            "url": source_url,
            "viewport_width": 1200,
            "viewport_height": 800,
            "full_page": "false",
            "format": "png",
            "block_ads": "true",
            "block_cookie_banners": "true",
            "block_trackers": "true",
            "delay": delay,
            "timeout": 25,
            "image_quality": 85,
        }
        if selector:
            params["element_selector"] = selector

        r = httpx.get(
            "https://api.screenshotone.com/take",
            params=params,
            timeout=35,
        )

        if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
            with open(filepath, "wb") as f:
                f.write(r.content)
            size_kb = len(r.content) // 1024
            print(f"[Archive] Saved screenshot for prediction {prediction_id} ({size_kb}KB): {filename}")
            return f"/archive/{filename}"
        elif r.status_code == 402:
            print("[Archive] ScreenshotOne quota exceeded — upgrade plan or wait for reset")
            return None
        elif r.status_code == 422:
            print(f"[Archive] ScreenshotOne could not render {source_url} (page error)")
            return None
        else:
            print(f"[Archive] ScreenshotOne error {r.status_code} for prediction {prediction_id}: {r.text[:100]}")
            return None

    except Exception as e:
        print(f"[Archive] Exception for prediction {prediction_id}: {e}")
        return None
