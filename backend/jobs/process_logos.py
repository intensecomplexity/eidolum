"""
Logo processing pipeline — downloads, strips backgrounds, normalizes, stores in DB.

Usage:
    from jobs.process_logos import process_all_logos, process_ticker_logo
    process_all_logos(db)              # batch: all tickers missing logos
    process_ticker_logo("AAPL", db)    # single ticker
"""
import io
import time
import httpx
from PIL import Image
from sqlalchemy import text as sql_text

# ── Logo sources (tried in order, all free) ──────────────────────────────────
def _logo_urls(ticker: str) -> list[str]:
    t = ticker.upper()
    return [
        f"https://financialmodelingprep.com/image-stock/{t}.png",
        f"https://images.financialmodelingprep.com/symbol/{t}.png",
        f"https://storage.googleapis.com/iexcloud-hl37opg/api/logos/{t}.png",
    ]


# ── Image processing ─────────────────────────────────────────────────────────
def _rgb_distance(a, b):
    """Euclidean distance between two RGB tuples."""
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def _detect_bg_color(img: Image.Image):
    """Sample 8 points (corners + edge midpoints) to detect background color.
    Returns the median RGB or None if samples are too inconsistent."""
    w, h = img.size
    samples = [
        img.getpixel((1, 1)),                # top-left
        img.getpixel((w - 2, 1)),            # top-right
        img.getpixel((1, h - 2)),            # bottom-left
        img.getpixel((w - 2, h - 2)),        # bottom-right
        img.getpixel((w // 2, 1)),           # top-center
        img.getpixel((w // 2, h - 2)),       # bottom-center
        img.getpixel((1, h // 2)),           # left-center
        img.getpixel((w - 2, h // 2)),       # right-center
    ]

    # All samples must be opaque
    opaque = [s for s in samples if s[3] > 200]
    if len(opaque) < 5:
        return None  # image already has transparency

    # Check if opaque samples are similar (within RGB distance 30)
    ref = opaque[0][:3]
    matching = [s for s in opaque if _rgb_distance(s[:3], ref) < 30]
    if len(matching) < 5:
        return None  # samples too varied, no consistent background

    # Return average of matching samples
    n = len(matching)
    return tuple(sum(s[i] for s in matching) // n for i in range(3))


def _strip_background(img: Image.Image) -> Image.Image:
    """Remove solid background color from logo image."""
    img = img.convert("RGBA")
    w, h = img.size
    if w < 4 or h < 4:
        return img

    # Detect background color from border samples
    bg = _detect_bg_color(img)

    # Also check for known problematic backgrounds even if detection fails
    if bg is None:
        # Try: is this a dark-background image? Sample just the corners
        corners = [img.getpixel((1, 1)), img.getpixel((w-2, 1)),
                   img.getpixel((1, h-2)), img.getpixel((w-2, h-2))]
        opaque_corners = [c for c in corners if c[3] > 200]
        if len(opaque_corners) >= 3:
            avg = tuple(sum(c[i] for c in opaque_corners) // len(opaque_corners) for i in range(3))
            if all(v < 30 for v in avg):       # near-black
                bg = avg
            elif all(v > 225 for v in avg):    # near-white
                bg = avg
        if bg is None:
            return img

    # Determine removal threshold — more aggressive for black/white backgrounds
    is_dark = all(v < 30 for v in bg)
    is_light = all(v > 225 for v in bg)
    threshold = 50 if (is_dark or is_light) else 40

    # Count how many pixels match the background
    data = list(img.getdata())
    bg_count = sum(
        1 for px in data
        if px[3] > 200 and _rgb_distance(px[:3], bg) < threshold
    )
    bg_ratio = bg_count / len(data)

    if bg_ratio < 0.20:
        return img  # background is less than 20%, probably not a solid bg

    # Replace background pixels with transparent
    new_data = []
    for px in data:
        if px[3] > 200 and _rgb_distance(px[:3], bg) < threshold:
            new_data.append((0, 0, 0, 0))
        else:
            new_data.append(px)
    img.putdata(new_data)
    return img


def _normalize(img: Image.Image, target: int = 128) -> Image.Image:
    """Resize and center on a transparent canvas."""
    img = _strip_background(img)

    # Crop to content (remove fully transparent borders)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    # Resize to fit within target with padding
    inner = int(target * 0.82)
    img.thumbnail((inner, inner), Image.LANCZOS)

    canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    offset = ((target - img.width) // 2, (target - img.height) // 2)
    canvas.paste(img, offset, img)
    return canvas


def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Download + process single ticker ─────────────────────────────────────────
def process_ticker_logo(ticker: str, db, force: bool = False) -> bool:
    """Download, process, and store a logo for one ticker. Returns True on success."""
    ticker = ticker.upper()

    # Skip if already processed (unless force)
    if not force:
        exists = db.execute(sql_text(
            "SELECT 1 FROM processed_logos WHERE ticker = :t"
        ), {"t": ticker}).first()
        if exists:
            return True

    # Try each source
    client = httpx.Client(timeout=10, follow_redirects=True,
                          headers={"User-Agent": "Eidolum/1.0 (logo processor)"})
    raw_bytes = None
    for url in _logo_urls(ticker):
        try:
            resp = client.get(url)
            if resp.status_code == 200 and len(resp.content) > 100:
                # Verify it's a valid image
                try:
                    Image.open(io.BytesIO(resp.content)).verify()
                    raw_bytes = resp.content
                    break
                except Exception:
                    continue
        except Exception:
            continue
    client.close()

    if not raw_bytes:
        print(f"[LogoProcessor] {ticker}: no image found from any source")
        return False

    # Process
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        processed = _normalize(img)
        png_bytes = _to_png_bytes(processed)
    except Exception as e:
        print(f"[LogoProcessor] {ticker}: Pillow processing failed: {e}")
        return False

    # Store in DB
    try:
        db.execute(sql_text("""
            INSERT INTO processed_logos (ticker, image_data, processed_at)
            VALUES (:t, :img, NOW())
            ON CONFLICT (ticker) DO UPDATE SET image_data = :img, processed_at = NOW()
        """), {"t": ticker, "img": png_bytes})
        db.commit()
        return True
    except Exception as e:
        print(f"[LogoProcessor] {ticker}: DB insert failed: {e}")
        db.rollback()
        return False


# ── Batch process all tickers ────────────────────────────────────────────────
def process_all_logos(db=None, batch_size: int = 50, rate_limit: float = 0.5, reprocess: bool = False) -> dict:
    """Process logos for all tickers that don't have one yet (or all if reprocess=True)."""
    from database import BgSessionLocal
    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    try:
        if reprocess:
            db.execute(sql_text("DELETE FROM processed_logos"))
            db.commit()
            print("[LogoProcessor] Cleared processed_logos table for reprocessing")

        # Get all tickers that need processing
        rows = db.execute(sql_text("""
            SELECT DISTINCT p.ticker
            FROM predictions p
            WHERE p.ticker IS NOT NULL AND p.ticker != ''
              AND NOT EXISTS (SELECT 1 FROM processed_logos pl WHERE pl.ticker = p.ticker)
            ORDER BY p.ticker
        """)).fetchall()

        tickers = [r[0] for r in rows]
        total = len(tickers)
        success = 0
        failed = 0

        print(f"[LogoProcessor] {total} tickers to process")

        for i, ticker in enumerate(tickers):
            ok = process_ticker_logo(ticker, db)
            if ok:
                success += 1
            else:
                failed += 1

            if (i + 1) % 10 == 0:
                print(f"[LogoProcessor] {i + 1}/{total} — {success} ok, {failed} failed")

            # Rate limit
            if (i + 1) % batch_size == 0:
                time.sleep(rate_limit * batch_size)
            else:
                time.sleep(rate_limit)

        print(f"[LogoProcessor] Done: {success} processed, {failed} failed out of {total}")
        return {"total": total, "success": success, "failed": failed}

    finally:
        if own_db:
            db.close()


def process_new_logos(db=None) -> dict:
    """Process logos for recently added tickers only. Called periodically by worker."""
    return process_all_logos(db, batch_size=20, rate_limit=1.0)
