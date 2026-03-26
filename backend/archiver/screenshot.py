"""
Free unlimited proof system using styled HTML evidence cards.
No external screenshot services needed.

YouTube → thumbnail + styled evidence card (free, always works)
Twitter/X → Nitter fetch + styled tweet card (free, no auth)
Reddit → JSON API + styled post card (free, no auth)
"""
import os
import re
import httpx
import hashlib
import asyncio
from pathlib import Path
from datetime import datetime

ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/archive")


def log_archive_status():
    print("[Archive] HTML evidence cards enabled — YouTube/Twitter/Reddit (free, unlimited)")


def _extract_video_id(url: str) -> str | None:
    match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None


async def archive_twitter(source_url: str, prediction_id: int,
                          exact_quote: str, forecaster_name: str,
                          prediction_date: str) -> str | None:
    """Save Twitter proof as a styled HTML card."""
    Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
    filename = f"p{prediction_id}_tw_{hashlib.md5(source_url.encode()).hexdigest()[:8]}.html"
    filepath = f"{ARCHIVE_DIR}/{filename}"

    if Path(filepath).exists():
        return f"/archive/{filename}"

    handle_match = re.search(r'x\.com/([^/]+)/status/(\d+)', source_url)
    if not handle_match:
        handle_match = re.search(r'twitter\.com/([^/]+)/status/(\d+)', source_url)
    handle = handle_match.group(1) if handle_match else "unknown"
    tweet_id = handle_match.group(2) if handle_match else "unknown"

    # Try fetching from nitter
    tweet_html_content = ""
    for instance in ["https://nitter.privacydev.net", "https://nitter.poast.org", "https://nitter.net"]:
        try:
            r = httpx.get(f"{instance}/{handle}/status/{tweet_id}",
                          headers={"User-Agent": "Mozilla/5.0 (compatible; eidolum-archiver/1.0)"},
                          timeout=8, follow_redirects=True)
            if r.status_code == 200 and "tweet-content" in r.text:
                content_match = re.search(r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>', r.text, re.DOTALL)
                if content_match:
                    tweet_html_content = content_match.group(1).strip()
                break
        except Exception:
            continue

    display_text = tweet_html_content if tweet_html_content else (exact_quote or "")
    date_str = prediction_date[:10] if prediction_date else ""
    initial = forecaster_name[0].upper() if forecaster_name else "?"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Eidolum Proof</title>
<style>
body{{margin:0;padding:20px;background:#000;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
.card{{background:#000;border:1px solid #2f3336;border-radius:12px;padding:16px;max-width:550px;color:#e7e9ea}}
.header{{display:flex;align-items:center;gap:10px;margin-bottom:12px}}
.avatar{{width:40px;height:40px;border-radius:50%;background:#1d9bf0;display:flex;align-items:center;justify-content:center;color:white;font-weight:bold;font-size:16px}}
.name{{font-weight:700;font-size:15px}}.username{{color:#71767b;font-size:14px}}
.content{{font-size:15px;line-height:1.5;margin-bottom:12px;white-space:pre-wrap}}
.footer{{color:#71767b;font-size:13px;border-top:1px solid #2f3336;padding-top:10px}}
.x-logo{{color:#e7e9ea;font-weight:bold;font-size:18px}}
.archived{{background:#1a1a2e;border:1px solid #00c896;border-radius:6px;padding:6px 10px;font-size:11px;color:#00c896;margin-top:10px;display:inline-block}}
a{{color:#1d9bf0;text-decoration:none}}
</style></head><body>
<div class="card">
<div class="header"><div class="avatar">{initial}</div><div><div class="name">{forecaster_name}</div><div class="username">@{handle}</div></div><div style="margin-left:auto" class="x-logo">𝕏</div></div>
<div class="content">{display_text}</div>
<div class="footer">{date_str} · <a href="{source_url}" target="_blank">View original ↗</a></div>
<div class="archived">Archived by Eidolum · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>
</div></body></html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[Archive] Twitter proof card: {filename}")
    return f"/archive/{filename}"


async def archive_youtube(source_url: str, prediction_id: int,
                          exact_quote: str, forecaster_name: str,
                          prediction_date: str) -> str | None:
    """Save YouTube proof: thumbnail + styled evidence card."""
    video_id = _extract_video_id(source_url)
    if not video_id:
        return None

    Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)

    # Save thumbnail
    thumb_filename = f"p{prediction_id}_yt_thumb_{video_id}.jpg"
    thumb_filepath = f"{ARCHIVE_DIR}/{thumb_filename}"
    thumb_saved = Path(thumb_filepath).exists()

    if not thumb_saved:
        for quality in ["maxresdefault", "hqdefault", "mqdefault"]:
            try:
                r = httpx.get(f"https://img.youtube.com/vi/{video_id}/{quality}.jpg",
                              timeout=8, follow_redirects=True)
                if r.status_code == 200 and len(r.content) > 5000:
                    with open(thumb_filepath, "wb") as f:
                        f.write(r.content)
                    thumb_saved = True
                    break
            except Exception:
                continue

    ts_match = re.search(r'[?&]t=(\d+)s?', source_url)
    timestamp_sec = int(ts_match.group(1)) if ts_match else None
    time_str = f"{timestamp_sec // 60}:{timestamp_sec % 60:02d}" if timestamp_sec else ""
    date_str = prediction_date[:10] if prediction_date else ""

    html_filename = f"p{prediction_id}_yt_{video_id}.html"
    html_filepath = f"{ARCHIVE_DIR}/{html_filename}"

    thumb_tag = f'<div style="position:relative"><img src="/archive/{thumb_filename}" style="width:100%;display:block" alt="Video thumbnail">'
    if time_str:
        thumb_tag += f'<div style="position:absolute;bottom:8px;right:8px;background:rgba(0,0,0,0.85);color:#fff;padding:3px 8px;border-radius:4px;font-size:13px;font-weight:600">{time_str}</div>'
    thumb_tag += '</div>'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Eidolum Proof</title>
<style>
body{{margin:0;padding:20px;background:#0a0a0a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
.card{{background:#111;border:1px solid #222;border-radius:12px;overflow:hidden;max-width:600px;color:#e8e8e6}}
.body{{padding:16px}}.channel{{color:#00c896;font-weight:600;font-size:13px;margin-bottom:8px}}
.quote{{font-size:15px;line-height:1.6;border-left:3px solid #00c896;padding-left:12px;margin:12px 0;font-style:italic;color:#ccc}}
.meta{{color:#666;font-size:12px;margin-top:12px}}
.archived{{background:#0d2018;border:1px solid #00c896;border-radius:6px;padding:5px 10px;font-size:11px;color:#00c896;margin-top:10px;display:inline-block}}
a{{color:#00c896;text-decoration:none}}
</style></head><body>
<div class="card">
{thumb_tag if thumb_saved else ""}
<div class="body">
<div class="channel">▶ <span style="color:#FF0000;font-weight:bold">YouTube</span> · {forecaster_name}</div>
<div class="quote">"{exact_quote or ""}"</div>
<div class="meta">Said on {date_str}{f" · at {time_str}" if time_str else ""} · <a href="{source_url}" target="_blank">Watch ↗</a></div>
<div class="archived">Archived by Eidolum · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>
</div></div></body></html>"""

    with open(html_filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[Archive] YouTube evidence card: {html_filename}")
    return f"/archive/{html_filename}"


async def archive_reddit(source_url: str, prediction_id: int,
                         exact_quote: str, forecaster_name: str,
                         prediction_date: str) -> str | None:
    """Save Reddit proof via JSON API + styled card."""
    Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
    filename = f"p{prediction_id}_rd_{hashlib.md5(source_url.encode()).hexdigest()[:8]}.html"
    filepath = f"{ARCHIVE_DIR}/{filename}"

    if Path(filepath).exists():
        return f"/archive/{filename}"

    post_title = post_body = post_author = subreddit = score = ""
    try:
        r = httpx.get(source_url.rstrip("/") + ".json?limit=1",
                      headers={"User-Agent": "eidolum-archiver/1.0"}, timeout=8, follow_redirects=True)
        if r.status_code == 200:
            d = r.json()[0]["data"]["children"][0]["data"]
            post_title = d.get("title", "")
            post_body = d.get("selftext", "")[:1000]
            post_author = d.get("author", "")
            subreddit = d.get("subreddit", "")
            score = str(d.get("score", ""))
    except Exception:
        pass

    display_title = post_title or (exact_quote or "")[:200]
    display_body = post_body or exact_quote or ""
    display_author = post_author or forecaster_name
    date_str = prediction_date[:10] if prediction_date else ""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Eidolum Proof</title>
<style>
body{{margin:0;padding:20px;background:#0a0a0a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
.card{{background:#1a1a1b;border:1px solid #343536;border-radius:4px;max-width:600px;color:#d7dadc;overflow:hidden}}
.main{{padding:12px 16px}}
.meta{{font-size:12px;color:#818384;margin-bottom:8px}}
.sub{{color:#d7dadc;font-weight:700}}.title{{font-size:18px;font-weight:500;margin-bottom:8px;line-height:1.3}}
.body{{font-size:14px;line-height:1.5;border-left:2px solid #343536;padding-left:10px;margin:8px 0;max-height:300px;overflow:hidden}}
.footer{{font-size:12px;color:#818384;padding:6px 0;border-top:1px solid #343536;margin-top:8px}}
.archived{{background:#0d1a0d;border:1px solid #00c896;border-radius:4px;padding:4px 8px;font-size:11px;color:#00c896;margin-top:8px;display:inline-block}}
a{{color:#4fbdff;text-decoration:none}}
</style></head><body>
<div class="card"><div class="main">
<div class="meta">u/{display_author}{f' in <span class="sub">r/{subreddit}</span>' if subreddit else ""} · {date_str}{f" · {score} points" if score else ""}</div>
<div class="title">{display_title}</div>
{f'<div class="body">{display_body}</div>' if display_body and display_body != display_title else ""}
<div class="footer"><a href="{source_url}" target="_blank">View original ↗</a> <span style="color:#FF4500;margin-left:8px">● Reddit</span></div>
<div class="archived">Archived by Eidolum · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>
</div></div></body></html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[Archive] Reddit evidence card: {filename}")
    return f"/archive/{filename}"


async def take_screenshot(source_url: str, prediction_id: int,
                          exact_quote: str = "", forecaster_name: str = "",
                          prediction_date: str = "") -> str | None:
    """Main entry point — routes to platform-specific archiver."""
    if not source_url:
        return None
    if "youtube.com" in source_url or "youtu.be" in source_url:
        return await archive_youtube(source_url, prediction_id, exact_quote, forecaster_name, prediction_date)
    elif "x.com" in source_url or "twitter.com" in source_url:
        return await archive_twitter(source_url, prediction_id, exact_quote, forecaster_name, prediction_date)
    elif "reddit.com" in source_url:
        return await archive_reddit(source_url, prediction_id, exact_quote, forecaster_name, prediction_date)
    return None


def archive_proof_sync(source_url: str, prediction_id: int = 0,
                       exact_quote: str = "", forecaster_name: str = "",
                       prediction_date: str = "") -> str | None:
    """Synchronous wrapper for save_with_proof."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            take_screenshot(source_url, prediction_id, exact_quote, forecaster_name, prediction_date)
        )
    finally:
        loop.close()
