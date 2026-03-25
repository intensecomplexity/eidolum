import os
import hashlib
from pathlib import Path

ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/archive")


async def archive_prediction(source_url: str, prediction_id: int) -> str | None:
    """Screenshot a URL and store it. Returns the archive path."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=[
                '--no-sandbox', '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ])
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            await page.goto(source_url, wait_until='networkidle', timeout=20000)
            await page.wait_for_timeout(3000)

            # Wait for platform-specific content
            if 'x.com' in source_url or 'twitter.com' in source_url:
                try:
                    await page.wait_for_selector('[data-testid="tweet"]', timeout=8000)
                    tweet = await page.query_selector('[data-testid="tweet"]')
                    if tweet:
                        await tweet.scroll_into_view_if_needed()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

            if 'youtube.com' in source_url:
                try:
                    await page.wait_for_selector('.ytd-video-primary-info-renderer', timeout=8000)
                except Exception:
                    pass

            if 'reddit.com' in source_url:
                try:
                    await page.wait_for_selector('[data-testid="post-container"]', timeout=8000)
                except Exception:
                    pass

            filename = f"p{prediction_id}_{hashlib.md5(source_url.encode()).hexdigest()[:10]}.png"
            Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
            filepath = f"{ARCHIVE_DIR}/{filename}"
            await page.screenshot(path=filepath, full_page=False)
            await browser.close()
            print(f"[Archive] Saved screenshot: {filename}")
            return f"/archive/{filename}"
    except Exception as e:
        print(f"[Archive] Failed for {source_url}: {e}")
        return None
