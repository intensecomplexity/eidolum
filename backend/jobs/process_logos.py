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
        # Quiet failure: caller (bulk_fill or process_all) tracks this via record_attempt
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
    """Process logos for tickers that don't have one yet. Hard 30-minute time budget.

    Phase 2 + 3: filters delisted/foreign tickers and respects logo_attempts cooldown.
    """
    from database import BgSessionLocal
    from jobs._time_budget import TimeBudget, TimeBudgetExceeded

    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    success = 0
    failed = 0
    total = 0

    try:
        if reprocess:
            db.execute(sql_text("DELETE FROM processed_logos"))
            db.commit()
            print("[LogoProcessor] Cleared processed_logos table for reprocessing")

        _ensure_logo_attempts_table(db)

        # Get tickers that need processing — same filters as bulk_fill_missing_logos
        rows = db.execute(sql_text("""
            SELECT DISTINCT p.ticker
            FROM predictions p
            WHERE p.ticker IS NOT NULL AND p.ticker != ''
              AND NOT EXISTS (SELECT 1 FROM processed_logos pl WHERE pl.ticker = p.ticker)
              AND p.ticker NOT LIKE '%.%'
              AND p.ticker IN (
                  SELECT DISTINCT ticker FROM predictions
                  WHERE created_at > NOW() - INTERVAL '2 years'
              )
              AND p.ticker NOT IN (
                  SELECT ticker FROM logo_attempts
                  WHERE last_result IN ('not_found', 'error')
                    AND last_attempted_at > NOW() - INTERVAL '30 days'
              )
            ORDER BY p.ticker
            LIMIT :lim
        """), {"lim": MAX_TICKERS_PER_RUN}).fetchall()

        tickers = [r[0] for r in rows]
        total = len(tickers)

        print(f"[LogoProcessor] Starting run with {total} tickers, 30min budget", flush=True)

        try:
            with TimeBudget(seconds=MAX_BULK_FILL_SECONDS, job_name="LogoProcessor") as budget:
                for i, ticker in enumerate(tickers):
                    budget.check()
                    ok = process_ticker_logo(ticker, db)
                    if ok:
                        success += 1
                        record_attempt(db, ticker, "success")
                    else:
                        failed += 1
                        record_attempt(db, ticker, "not_found")

                    if (i + 1) % 10 == 0:
                        print(
                            f"[LogoProcessor] Progress: {i + 1}/{total} — "
                            f"{success} ok, {failed} failed, remaining budget: {budget.remaining():.0f}s",
                            flush=True,
                        )

                    if (i + 1) % batch_size == 0:
                        time.sleep(rate_limit * batch_size)
                    else:
                        time.sleep(rate_limit)
        except TimeBudgetExceeded:
            print(
                f"[LogoProcessor] Time budget reached, stopped cleanly. "
                f"Processed {success + failed}/{total}, will resume next run.",
                flush=True,
            )

        print(f"[LogoProcessor] Done: {success} processed, {failed} failed out of {total}", flush=True)
        return {"total": total, "success": success, "failed": failed}

    finally:
        if own_db:
            db.close()


def process_new_logos(db=None) -> dict:
    """Process logos for recently added tickers only. Called periodically by worker."""
    return process_all_logos(db, batch_size=20, rate_limit=1.0)


MAX_BULK_FILL_SECONDS = 1800  # 30 minute time budget per run
MAX_TICKERS_PER_RUN = 500     # Phase 2: hard cap so the job can never run away


def _ensure_logo_attempts_table(db) -> None:
    """Create logo_attempts table if it doesn't exist. Idempotent."""
    try:
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS logo_attempts (
                ticker VARCHAR(20) PRIMARY KEY,
                last_attempted_at TIMESTAMP DEFAULT NOW(),
                attempt_count INTEGER DEFAULT 1,
                last_result VARCHAR(20)
            )
        """))
        db.commit()
    except Exception as e:
        print(f"[LogoBulkFill] Could not ensure logo_attempts table: {e}", flush=True)
        db.rollback()


def record_attempt(db, ticker: str, result: str) -> None:
    """Record a logo fetch attempt. result is 'success', 'not_found', or 'error'."""
    try:
        db.execute(sql_text("""
            INSERT INTO logo_attempts (ticker, last_attempted_at, attempt_count, last_result)
            VALUES (:t, NOW(), 1, :r)
            ON CONFLICT (ticker) DO UPDATE SET
                last_attempted_at = NOW(),
                attempt_count = logo_attempts.attempt_count + 1,
                last_result = :r
        """), {"t": ticker, "r": result})
        db.commit()
    except Exception:
        db.rollback()


def bulk_fill_missing_logos(db=None, rate_limit: float = 0.15) -> dict:
    """Fast bulk fill: process tickers missing logos, ordered by prediction count.

    Phase 2: query filters delisted (no activity in 2 years) and foreign listings.
    Phase 3: skips tickers attempted in last 30 days that previously failed.
    Phase 5: hard 30-minute time budget via the TimeBudget helper.

    Capped at MAX_TICKERS_PER_RUN per run; resumes on next interval.
    """
    from database import BgSessionLocal
    from jobs._time_budget import TimeBudget, TimeBudgetExceeded

    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    success = 0
    failed = 0
    total = 0

    try:
        _ensure_logo_attempts_table(db)

        # Phase 2 + Phase 3 query: active tickers, no foreign listings,
        # not failed-and-cooling-down.
        rows = db.execute(sql_text("""
            SELECT p.ticker, COUNT(*) as cnt
            FROM predictions p
            WHERE p.ticker IS NOT NULL AND p.ticker != ''
              AND NOT EXISTS (SELECT 1 FROM processed_logos pl WHERE pl.ticker = p.ticker)
              AND p.ticker NOT LIKE '%.%'
              AND p.ticker IN (
                  SELECT DISTINCT ticker FROM predictions
                  WHERE created_at > NOW() - INTERVAL '2 years'
              )
              AND p.ticker NOT IN (
                  SELECT ticker FROM logo_attempts
                  WHERE last_result IN ('not_found', 'error')
                    AND last_attempted_at > NOW() - INTERVAL '30 days'
              )
            GROUP BY p.ticker
            ORDER BY cnt DESC
            LIMIT :lim
        """), {"lim": MAX_TICKERS_PER_RUN}).fetchall()

        tickers = [r[0] for r in rows]
        total = len(tickers)

        if total == 0:
            print("[LogoBulkFill] No active tickers need logos right now", flush=True)
            return {"total": 0, "success": 0, "failed": 0}

        print(
            f"[LogoBulkFill] Starting run with {total} tickers, 30min budget "
            f"(top: {', '.join(t for t in tickers[:10])})",
            flush=True,
        )

        try:
            with TimeBudget(seconds=MAX_BULK_FILL_SECONDS, job_name="LogoBulkFill") as budget:
                for i, ticker in enumerate(tickers):
                    budget.check()  # raises TimeBudgetExceeded when over budget

                    ok = process_ticker_logo(ticker, db)
                    if ok:
                        success += 1
                        record_attempt(db, ticker, "success")
                    else:
                        failed += 1
                        record_attempt(db, ticker, "not_found")

                    if (i + 1) % 50 == 0:
                        print(
                            f"[LogoBulkFill] Progress: {i + 1}/{total} — "
                            f"{success} ok, {failed} failed, "
                            f"remaining budget: {budget.remaining():.0f}s",
                            flush=True,
                        )

                    time.sleep(rate_limit)
        except TimeBudgetExceeded:
            print(
                f"[LogoBulkFill] Time budget reached, stopped cleanly. "
                f"Processed {success + failed}/{total}, will resume next run.",
                flush=True,
            )

        print(
            f"[LogoBulkFill] DONE: {success} processed, {failed} failed out of {total}",
            flush=True,
        )
        return {"total": total, "success": success, "failed": failed}

    finally:
        if own_db:
            db.close()
