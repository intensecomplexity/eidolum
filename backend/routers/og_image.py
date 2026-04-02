"""
Dynamic Open Graph image generator for forecaster pages.
Returns a 1200x630 PNG with forecaster name, accuracy, and stats.
Uses Pillow. Cached 24 hours per forecaster.
"""
import io
import math
import time
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from models import Forecaster
from rate_limit import limiter

router = APIRouter()

_og_cache: dict[int, tuple] = {}  # fid -> (bytes, timestamp)
_OG_TTL = 86400  # 24 hours

# Colors
BG = (13, 15, 19)
GOLD = (212, 168, 67)
WHITE = (228, 228, 231)
MUTED = (139, 143, 154)
GREEN = (52, 211, 153)
RED = (248, 113, 113)
YELLOW = (251, 191, 36)
DARK_SURFACE = (22, 24, 29)

W, H = 1200, 630


def _draw_ring(draw, cx, cy, radius, pct, color, bg_color=(30, 32, 40), width=8):
    """Draw an accuracy ring (arc) at the given position."""
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.arc(bbox, 0, 360, fill=bg_color, width=width)
    if pct > 0:
        end_angle = -90 + (pct / 100) * 360
        draw.arc(bbox, -90, end_angle, fill=color, width=width)


def _generate_og(f: Forecaster) -> bytes:
    """Generate a 1200x630 PNG OG image for a forecaster."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Gold border (2px)
    draw.rectangle([0, 0, W - 1, H - 1], outline=GOLD, width=2)

    # Try to load a font, fall back to default
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_acc = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        font_brand = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    except Exception:
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large
        font_acc = font_large
        font_brand = font_large

    acc = float(f.accuracy_score or 0)
    total = f.total_predictions or 0
    hits = f.correct_predictions or 0
    name = f.name or "Unknown"
    firm = getattr(f, "firm", None) or ""

    # Eidolum brand (top left)
    draw.text((40, 30), "EIDOLUM", fill=GOLD, font=font_brand)

    # Accuracy ring (right side)
    ring_cx, ring_cy = 950, 280
    ring_radius = 100
    ring_color = GREEN if acc >= 60 else YELLOW if acc >= 40 else RED
    _draw_ring(draw, ring_cx, ring_cy, ring_radius, min(acc, 100), ring_color, width=12)

    # Accuracy text in ring center
    acc_text = f"{acc:.1f}%"
    try:
        bbox = draw.textbbox((0, 0), acc_text, font=font_acc)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = 200, 60
    draw.text((ring_cx - tw // 2, ring_cy - th // 2 - 5), acc_text, fill=ring_color, font=font_acc)

    # "accuracy" label below ring
    draw.text((ring_cx - 42, ring_cy + ring_radius + 15), "accuracy", fill=MUTED, font=font_small)

    # Forecaster name (left side, vertically centered)
    draw.text((60, 180), name, fill=WHITE, font=font_large)

    # Firm
    if firm:
        draw.text((60, 240), firm, fill=MUTED, font=font_medium)

    # Stats row
    stats_y = 320
    stats_text = f"{total} predictions"
    if hits > 0:
        stats_text += f"  |  {hits} HITs"
    draw.text((60, stats_y), stats_text, fill=MUTED, font=font_small)

    # Subtitle
    draw.text((60, stats_y + 40), "Verified against real market data", fill=(90, 94, 106), font=font_small)

    # Dark bar at bottom
    draw.rectangle([0, H - 60, W, H], fill=DARK_SURFACE)
    draw.text((60, H - 48), "Track every prediction. See who was right.", fill=MUTED, font=font_small)
    draw.text((W - 200, H - 48), "eidolum.com", fill=GOLD, font=font_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get("/og-image/forecaster/{forecaster_id}")
@limiter.limit("30/minute")
def og_image(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    cached = _og_cache.get(forecaster_id)
    if cached and (time.time() - cached[1]) < _OG_TTL:
        return Response(content=cached[0], media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        return Response(content=b"", status_code=404)

    png = _generate_og(f)
    _og_cache[forecaster_id] = (png, time.time())
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})
