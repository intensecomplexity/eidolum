"""
Platform-specific proof archiver.
YouTube → thumbnail saved locally (free, always works)
Twitter/X → ScreenshotOne screenshot of tweet element
Reddit → ScreenshotOne screenshot of post
"""
import os
import re
import httpx
import hashlib
from pathlib import Path

ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/archive")
SCREENSHOTONE_KEY = os.getenv("SCREENSHOTONE_KEY", "")


def _extract_video_id(url: str) -> str | None:
    match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None


async def save_youtube_proof(source_url: str, prediction_id: int) -> str | None:
    """Save YouTube video thumbnail. Free, no API key needed."""
    video_id = _extract_video_id(source_url)
    if not video_id:
        return None

    Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
    filename = f"p{prediction_id}_yt_{video_id}.jpg"
    filepath = f"{ARCHIVE_DIR}/{filename}"

    if Path(filepath).exists():
        return f"/archive/{filename}"

    for quality in ["maxresdefault", "hqdefault", "mqdefault"]:
        thumb_url = f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"
        try:
            r = httpx.get(thumb_url, timeout=10, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 5000:
                with open(filepath, "wb") as f:
                    f.write(r.content)
                print(f"[Archive] YouTube thumbnail saved for prediction {prediction_id}: {filename}")
                return f"/archive/{filename}"
        except Exception:
            continue

    return None


async def save_twitter_screenshot(source_url: str, prediction_id: int) -> str | None:
    """Screenshot a tweet via ScreenshotOne."""
    if not SCREENSHOTONE_KEY:
        return None

    filename = f"p{prediction_id}_tw_{hashlib.md5(source_url.encode()).hexdigest()[:10]}.png"
    filepath = f"{ARCHIVE_DIR}/{filename}"
    Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)

    if Path(filepath).exists():
        return f"/archive/{filename}"

    params = {
        "access_key": SCREENSHOTONE_KEY,
        "url": source_url,
        "viewport_width": 600,
        "viewport_height": 400,
        "full_page": "false",
        "format": "png",
        "block_ads": "true",
        "block_cookie_banners": "true",
        "block_trackers": "true",
        "delay": 4,
        "timeout": 30,
        "image_quality": 85,
        "element_selector": "article[data-testid='tweet']",
    }

    try:
        r = httpx.get("https://api.screenshotone.com/take", params=params, timeout=35)
        if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
            with open(filepath, "wb") as f:
                f.write(r.content)
            print(f"[Archive] Tweet screenshot saved for prediction {prediction_id}")
            return f"/archive/{filename}"
        elif r.status_code == 402:
            print("[Archive] ScreenshotOne quota exceeded")
        else:
            print(f"[Archive] ScreenshotOne error {r.status_code} for prediction {prediction_id}")
        return None
    except Exception as e:
        print(f"[Archive] Tweet screenshot exception: {e}")
        return None


async def save_reddit_screenshot(source_url: str, prediction_id: int) -> str | None:
    """Screenshot a Reddit post via ScreenshotOne."""
    if not SCREENSHOTONE_KEY:
        return None

    filename = f"p{prediction_id}_rd_{hashlib.md5(source_url.encode()).hexdigest()[:10]}.png"
    filepath = f"{ARCHIVE_DIR}/{filename}"
    Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)

    if Path(filepath).exists():
        return f"/archive/{filename}"

    params = {
        "access_key": SCREENSHOTONE_KEY,
        "url": source_url,
        "viewport_width": 900,
        "viewport_height": 600,
        "full_page": "false",
        "format": "png",
        "block_ads": "true",
        "block_cookie_banners": "true",
        "delay": 3,
        "timeout": 25,
        "image_quality": 85,
    }

    try:
        r = httpx.get("https://api.screenshotone.com/take", params=params, timeout=35)
        if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
            with open(filepath, "wb") as f:
                f.write(r.content)
            print(f"[Archive] Reddit screenshot saved for prediction {prediction_id}")
            return f"/archive/{filename}"
        else:
            print(f"[Archive] ScreenshotOne Reddit error {r.status_code}")
        return None
    except Exception as e:
        print(f"[Archive] Reddit screenshot exception: {e}")
        return None


async def take_screenshot(source_url: str, prediction_id: int) -> str | None:
    """
    Route to the right archiver based on platform.
    YouTube → thumbnail (free, always works)
    Twitter/X → ScreenshotOne tweet screenshot
    Reddit → ScreenshotOne post screenshot
    """
    if not source_url:
        return None

    if "youtube.com" in source_url or "youtu.be" in source_url:
        return await save_youtube_proof(source_url, prediction_id)
    elif "x.com" in source_url or "twitter.com" in source_url:
        return await save_twitter_screenshot(source_url, prediction_id)
    elif "reddit.com" in source_url:
        return await save_reddit_screenshot(source_url, prediction_id)
    else:
        # Generic: try twitter-style screenshot
        return await save_twitter_screenshot(source_url, prediction_id)
