"""
IE3 — Promotional Image Generator.

Generates a 1080×1080 brand-styled ad image using Pillow as a
high-quality fallback when Replicate (Stable Diffusion) is unavailable.

Each brand has its own color palette; urgency level adjusts the mood text.
"""

from __future__ import annotations

import io
import sys
import textwrap
from typing import Optional

# ── Brand color palettes ──────────────────────────────────────────────────────

_BRAND_PALETTES: dict[str, dict] = {
    "adidas": {"bg": (0, 0, 0),        "primary": (255, 255, 255), "accent": (255, 107, 53)},
    "nike":   {"bg": (20, 20, 20),     "primary": (255, 255, 255), "accent": (255, 69, 0)},
    "puma":   {"bg": (245, 166, 35),   "primary": (0, 0, 0),       "accent": (30, 30, 30)},
    "reebok": {"bg": (10, 36, 99),     "primary": (255, 255, 255), "accent": (220, 50, 50)},
    "new balance": {"bg": (35, 35, 35),"primary": (255, 255, 255), "accent": (200, 200, 200)},
    "default":{"bg": (26, 26, 46),     "primary": (255, 255, 255), "accent": (255, 107, 53)},
}

# ── Font helpers ──────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False):
    """Try to load a TrueType font; fall back to Pillow's built-in bitmap font."""
    from PIL import ImageFont

    if sys.platform == "win32":
        import os
        win_fonts = r"C:\Windows\Fonts"
        candidates = (
            [os.path.join(win_fonts, f) for f in ("arialbd.ttf", "calibrib.ttf", "verdanab.ttf")]
            if bold else
            [os.path.join(win_fonts, f) for f in ("arial.ttf", "calibri.ttf", "verdana.ttf")]
        )
    else:
        # Linux / Docker — install fonts-liberation in the Dockerfile
        candidates = (
            [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            ]
            if bold else
            [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]
        )

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue

    # Pillow built-in bitmap font (last resort — small but always available)
    return ImageFont.load_default()


def _text_width(draw, text: str, font) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except AttributeError:
        return len(text) * (font.size // 2 if hasattr(font, "size") else 8)


def _centered_x(draw, text: str, font, canvas_w: int) -> int:
    return (canvas_w - _text_width(draw, text, font)) // 2


# ── Main generator ────────────────────────────────────────────────────────────

def generate_promo_image(
    product_name: str,
    brand: str,
    discount_pct: float,
    retail_price_usd: float,
    urgency_level: str,
    current_stock: int,
    color: Optional[str] = None,
) -> bytes:
    """
    Generate a 1080×1080 promotional ad image.
    Returns raw PNG bytes.

    Layout:
        ┌────────────────────────────────┐
        │ [BRAND]           accent strip │
        │                               │
        │        ╔══════════╗           │
        │        ║   15%    ║  accent   │
        │        ║   OFF    ║  circle   │
        │        ╚══════════╝           │
        │  ─────────────────────────    │
        │  Product Name (wrapped)       │
        │  Urgency / value line         │
        │  Now $X  (was $Y)             │
        │                               │
        │     StylePulse · Lebanon      │
        └────────────────────────────────┘
    """
    from PIL import Image, ImageDraw

    brand_key = (brand or "").lower().strip()
    # Try exact match first, then first word
    palette = (
        _BRAND_PALETTES.get(brand_key)
        or _BRAND_PALETTES.get(brand_key.split()[0] if brand_key else "default")
        or _BRAND_PALETTES["default"]
    )

    bg      = palette["bg"]
    primary = palette["primary"]
    accent  = palette["accent"]

    W, H = 1080, 1080
    img  = Image.new("RGB", (W, H), color=bg)
    draw = ImageDraw.Draw(img)

    # ── Subtle background gradient (lighter centre) ───────────────────────────
    for i in range(0, H, 2):
        lift = int(14 * (1 - abs(i - H / 2) / (H / 2)))
        band = tuple(min(255, c + lift) for c in bg)
        draw.rectangle([(0, i), (W, i + 1)], fill=band)

    # ── Border strips ─────────────────────────────────────────────────────────
    draw.rectangle([(0, 0),      (W, 14)],     fill=accent)
    draw.rectangle([(0, H - 14), (W, H)],      fill=accent)
    draw.rectangle([(0, 0),      (14, H)],     fill=accent)
    draw.rectangle([(W - 14, 0), (W, H)],      fill=accent)

    # ── Brand name (top-left) ─────────────────────────────────────────────────
    font_brand = _load_font(60, bold=True)
    draw.text((50, 35), (brand or "").upper(), font=font_brand, fill=accent)

    # ── Discount circle ───────────────────────────────────────────────────────
    cx, cy, r = W // 2, 370, 270
    # Outer glow (slightly larger, semi-transparent look via lighter colour)
    glow = tuple(min(255, c + 40) for c in accent)
    draw.ellipse([(cx - r - 12, cy - r - 12), (cx + r + 12, cy + r + 12)], fill=glow)
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=accent)

    disc = int(discount_pct or 0)

    font_pct  = _load_font(190, bold=True)
    font_off  = _load_font(80,  bold=True)

    pct_text = f"{disc}%"
    pw = _text_width(draw, pct_text, font_pct)
    ow = _text_width(draw, "OFF",     font_off)

    draw.text(((W - pw) // 2, cy - 170), pct_text, font=font_pct, fill=bg)
    draw.text(((W - ow) // 2, cy + 60),  "OFF",     font=font_off, fill=bg)

    # ── Divider ───────────────────────────────────────────────────────────────
    draw.rectangle([(60, 685), (W - 60, 690)], fill=primary)

    # ── Product name (centred, wrapped) ──────────────────────────────────────
    font_prod = _load_font(54, bold=True)
    lines = textwrap.wrap(product_name, width=26)
    y = 710
    for line in lines[:2]:
        draw.text((_centered_x(draw, line, font_prod, W), y), line,
                  font=font_prod, fill=primary)
        y += 68

    # ── Urgency / value sub-line ──────────────────────────────────────────────
    font_sub = _load_font(34)
    sub_map = {
        "high":   f"Only {current_stock} units left · Ends Soon",
        "medium": f"Level up your game · {brand} quality",
        "low":    "Quality gear · Smart price · StylePulse",
    }
    sub_text = sub_map.get(urgency_level, sub_map["low"])
    draw.text((_centered_x(draw, sub_text, font_sub, W), y + 16),
              sub_text, font=font_sub, fill=accent)

    # ── Price line ────────────────────────────────────────────────────────────
    if retail_price_usd > 0 and disc > 0:
        font_price = _load_font(42, bold=True)
        discounted  = retail_price_usd * (1 - disc / 100)
        price_text  = f"Now ${discounted:.0f}   ·   was ${retail_price_usd:.0f}"
        draw.text((_centered_x(draw, price_text, font_price, W), y + 70),
                  price_text, font=font_price, fill=primary)

    # ── Store footer ──────────────────────────────────────────────────────────
    font_store  = _load_font(36, bold=True)
    store_label = "StylePulse · Sports Fashion Lebanon"
    draw.text((_centered_x(draw, store_label, font_store, W), H - 60),
              store_label, font=font_store, fill=primary)

    # ── Serialize ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
