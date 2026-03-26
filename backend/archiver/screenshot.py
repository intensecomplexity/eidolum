"""
Proof-first archiver. No screenshot = no prediction. Ever.

YouTube → thumbnail saved locally (free, always works)
Twitter/X → ScreenshotOne screenshot of tweet element
Reddit → ScreenshotOne screenshot of post

If proof cannot be obtained, the prediction is never saved.
"""
import os
import re
import httpx
import hashlib
import asyncio
from pathlib import Path
from datetime import datetime

ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/archive")
SCREENSHOTONE_KEY = os.getenv("SCREENSHOTONE_KEY", "")


def log_archive_status():
    """Print archive capability status on startup."""
    if SCREENSHOTONE_KEY:
        print("[Archive] ScreenshotOne configured — all platforms can be archived")
    else:
        print("[Archive] WARNING: No SCREENSHOTONE_KEY — Twitter/Reddit predictions will be rejected (no proof possible)")
    print("[Archive] YouTube thumbnails always available (free)")


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
            return f"/archive/{filename}"
        elif r.status_code == 402:
            print("[Archive] ScreenshotOne quota exceeded")
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
            return f"/archive/{filename}"
        return None
    except Exception as e:
        print(f"[Archive] Reddit screenshot exception: {e}")
        return None


async def take_screenshot(source_url: str, prediction_id: int) -> str | None:
    """Route to the right archiver based on URL."""
    if not source_url:
        return None

    if "youtube.com" in source_url or "youtu.be" in source_url:
        return await save_youtube_proof(source_url, prediction_id)
    elif "x.com" in source_url or "twitter.com" in source_url:
        return await save_twitter_screenshot(source_url, prediction_id)
    elif "reddit.com" in source_url:
        return await save_reddit_screenshot(source_url, prediction_id)
    else:
        return await save_twitter_screenshot(source_url, prediction_id)


def archive_proof_sync(source_url: str, prediction_id: int = 0) -> str | None:
    """Synchronous wrapper around take_screenshot. Used by save_with_proof."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(take_screenshot(source_url, prediction_id))
    finally:
        loop.close()
