#!/usr/bin/env python3
"""
generate_og_image.py — produce frontend/public/og-image.png (1200x630).

Brand palette pulled from tailwind.config.js + index.css (2026-06-02):
    bg          #0d0f13   (tailwind colors.bg)
    accent gold #D4A843   (tailwind colors.accent)
    cream       #F1ECDF   (used as surface-2 in light theme + body copy)
    HIT green   #22c55e   (tailwind colors.positive)
    NEAR yellow #eab308   (warning-band, matches gold-adjacent NEAR usage)
    MISS red    #ef4444   (tailwind colors.negative)

Fonts:
    Wordmark / tagline / "Truth is the only currency"  —  DejaVu Serif Bold + Book
    Body copy / pillar dots / eidolum.com               —  DejaVu Sans Book + Bold

DejaVu is the only serif installed on the build host (no Cormorant /
Playfair / Garamond). Once we ship a project-controlled font, replace
the path constants below. The script bakes the PNG into
frontend/public/og-image.png so social shares render immediately.
"""
from PIL import Image, ImageDraw, ImageFont
import os

# ─── canvas + palette ────────────────────────────────────────────────────
W, H = 1200, 630
BG          = (13, 15, 19)      # #0d0f13
ACCENT      = (212, 168, 67)    # #D4A843
ACCENT_DIM  = (212, 168, 67, 36)   # ~14% — divider line
GRID_GOLD   = (212, 168, 67, 13)   # ~5%  — grid pattern
CREAM       = (241, 236, 223)   # #F1ECDF
CREAM_DIM   = (241, 236, 223, 153)  # 60% — bottom eidolum.com
HIT_GREEN   = (34, 197, 94)     # #22c55e
NEAR_YELL   = (234, 179, 8)     # #eab308
MISS_RED    = (239, 68, 68)     # #ef4444


# ─── fonts (with graceful fallback) ──────────────────────────────────────
FONT_PATHS = {
    "serif_bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf",
    ],
    "serif_book": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
    ],
    "sans_book": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ],
    "sans_bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ],
}


def font(role: str, size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS[role]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    raise RuntimeError(
        f"no truetype font for role={role!r}; install fonts-dejavu-core"
    )


# ─── helpers ─────────────────────────────────────────────────────────────
def text_size(draw, text, fnt):
    """Return (w, h) for `text` rendered with `fnt`."""
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    return r - l, b - t


def draw_centered(draw, text, fnt, y, color, x_anchor_w=W, letter_spacing=0):
    """Draw `text` horizontally centered on `x_anchor_w`-wide canvas at
    baseline `y`. If letter_spacing > 0, render glyph-by-glyph and offset."""
    if letter_spacing <= 0:
        w, _ = text_size(draw, text, fnt)
        draw.text(((x_anchor_w - w) // 2, y), text, font=fnt, fill=color)
        return
    # measure with spacing
    glyph_widths = []
    for ch in text:
        gw, _ = text_size(draw, ch, fnt)
        glyph_widths.append(gw)
    total = sum(glyph_widths) + letter_spacing * (len(text) - 1)
    x = (x_anchor_w - total) // 2
    for ch, gw in zip(text, glyph_widths):
        draw.text((x, y), ch, font=fnt, fill=color)
        x += gw + letter_spacing


# ─── render ──────────────────────────────────────────────────────────────
def render() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    # grid overlay on its own RGBA layer so the 13/255 alpha actually composites
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdr = ImageDraw.Draw(grid)
    GRID_SPACING = 60
    for x in range(0, W + 1, GRID_SPACING):
        gdr.line([(x, 0), (x, H)], fill=GRID_GOLD, width=1)
    for y in range(0, H + 1, GRID_SPACING):
        gdr.line([(0, y), (W, y)], fill=GRID_GOLD, width=1)
    img = Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")

    draw = ImageDraw.Draw(img, "RGBA")

    # 1. EIDOLUM wordmark — large serif, gold, ~8px tracking
    word_font = font("serif_bold", 96)
    draw_centered(draw, "EIDOLUM", word_font, y=70, color=ACCENT,
                  letter_spacing=10)

    # 2. divider line — 1px gold low opacity, ~400px wide, centered
    div_y = 195
    draw.line([(W // 2 - 200, div_y), (W // 2 + 200, div_y)],
              fill=ACCENT_DIM, width=1)

    # 3. headline tagline
    tag_font = font("serif_book", 52)
    draw_centered(draw, "Who should you actually listen to?", tag_font,
                  y=222, color=ACCENT)

    # 4. body copy — two lines, cream, sans
    body_font = font("sans_book", 26)
    body_line_1 = "Every Wall Street analyst and fintwit forecaster on one"
    body_line_2 = "leaderboard, scored against reality."
    draw_centered(draw, body_line_1, body_font, y=325, color=CREAM)
    draw_centered(draw, body_line_2, body_font, y=363, color=CREAM)

    # 5. pillar row: green/yellow/red dot + label, cream text, ~14px dots
    pillar_font = font("sans_bold", 22)
    pillar_y = 440
    pillars = [("HIT", HIT_GREEN), ("NEAR", NEAR_YELL), ("MISS", MISS_RED)]
    # compute total width for centering
    dot_d = 14
    dot_gap = 12           # px between dot and label
    pillar_gap = 90        # px between pillar groups
    pieces = []
    for label, _ in pillars:
        lw, _ = text_size(draw, label, pillar_font)
        pieces.append(dot_d + dot_gap + lw)
    total_w = sum(pieces) + pillar_gap * (len(pillars) - 1)
    x = (W - total_w) // 2
    for (label, color), pw in zip(pillars, pieces):
        # dot — render slightly offset down so it sits on the cap-line baseline
        dot_y = pillar_y + 8
        draw.ellipse((x, dot_y, x + dot_d, dot_y + dot_d), fill=color)
        # label
        draw.text((x + dot_d + dot_gap, pillar_y), label,
                  font=pillar_font, fill=CREAM)
        x += pw + pillar_gap

    # 6. "Truth is the only currency." — serif, gold
    truth_font = font("serif_book", 32)
    draw_centered(draw, "Truth is the only currency.", truth_font,
                  y=520, color=ACCENT)

    # 7. eidolum.com — tiny, cream-dim, very bottom
    url_font = font("sans_book", 16)
    draw_centered(draw, "eidolum.com", url_font, y=585, color=CREAM_DIM)

    return img


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "public", "og-image.png")
    out = os.path.normpath(out)
    img = render()
    img.save(out, format="PNG", optimize=True)
    sz = os.path.getsize(out)
    print(f"wrote {out}  ({sz:,} bytes, {img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
