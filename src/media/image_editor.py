"""
bakery-social-engine — Image processing (Feed / Story mode).

Handles:
- Background removal via rembg
- Compositing product onto luxury template backgrounds
- Drop shadow generation
- Bold minimal typography
- Brand logo watermark
"""

from __future__ import annotations

import logging
import random
import re
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.config import get_settings

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
FEED_SIZE = (1080, 1080)      # Instagram feed square
STORY_SIZE = (1080, 1920)     # Instagram story / reel cover
SHADOW_OFFSET = (0, 8)
SHADOW_BLUR = 20
SHADOW_COLOR = (0, 0, 0, 90)


def _clean_text_for_pil(text: str) -> str:
    """Strip emoji characters that cause unrendered [] boxes in FreeType."""
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff\U00002600-\U000027BF\U00002300-\U000023FF"
        "\U00002B50-\U00002B55\U0000200D\U0000FE0F]",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def _get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Load the best available font from assets/fonts/."""
    settings = get_settings()
    font_dir = settings.fonts_dir

    if bold:
        candidates = [
            font_dir / "Montserrat-ExtraBold.ttf",
            font_dir / "Montserrat-Bold.ttf",
            font_dir / "Poppins-Bold.ttf",
        ]
    else:
        candidates = [
            font_dir / "Montserrat-Regular.ttf",
            font_dir / "Montserrat-Bold.ttf",
            font_dir / "Poppins-Regular.ttf",
        ]

    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue

    for ttf in font_dir.glob("*.ttf"):
        try:
            return ImageFont.truetype(str(ttf), size)
        except Exception:
            continue

    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _pick_background(category: str | None = None) -> Optional[Path]:
    """Pick a high-end commercial background image from assets/backgrounds/."""
    settings = get_settings()
    bg_dir = settings.backgrounds_dir

    if category == "CUSTOM_CAKE":
        preferred = ["marble_dark_luxury.jpg", "marble_white_clean.jpg", "rustic_wood_warm.jpg"]
    elif category == "DAILY_SNACK":
        preferred = ["rustic_wood_warm.jpg", "marble_white_clean.jpg", "marble_dark_luxury.jpg"]
    elif category == "FESTIVAL_SPECIAL":
        preferred = ["marble_dark_luxury.jpg", "rustic_wood_warm.jpg"]
    else:
        preferred = ["marble_dark_luxury.jpg", "rustic_wood_warm.jpg", "marble_white_clean.jpg"]

    for name in preferred:
        path = bg_dir / name
        if path.exists():
            return path

    backgrounds = list(bg_dir.glob("*.jpg")) + list(bg_dir.glob("*.png"))
    if not backgrounds:
        logger.warning("No background images found in %s", bg_dir)
        return None

    return random.choice(backgrounds)


def _create_drop_shadow(
    image: Image.Image,
    offset: tuple[int, int] = SHADOW_OFFSET,
    blur: int = SHADOW_BLUR,
    color: tuple[int, int, int, int] = SHADOW_COLOR,
) -> Image.Image:
    """Create a subtle ambient drop shadow for edge blending."""
    if image.mode == "RGBA":
        alpha = image.split()[3]
        shadow_shape = Image.new("RGBA", image.size, color)
        shadow_shape.putalpha(alpha)
    else:
        shadow_shape = Image.new("RGBA", image.size, color)

    shadow_shape = shadow_shape.filter(ImageFilter.GaussianBlur(blur))

    canvas_w = image.width + abs(offset[0]) + blur * 2
    canvas_h = image.height + abs(offset[1]) + blur * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    sx = blur + max(0, offset[0])
    sy = blur + max(0, offset[1])
    canvas.paste(shadow_shape, (sx, sy))

    ix = blur + max(0, -offset[0])
    iy = blur + max(0, -offset[1])
    canvas.paste(image, (ix, iy), image if image.mode == "RGBA" else None)

    return canvas


def _create_tabletop_contact_shadow(
    product_w: int,
    product_h: int,
) -> tuple[Image.Image, int, int]:
    """
    Generate realistic multi-stage ground contact shadow for the tabletop.
    Returns: (shadow_image, offset_x_rel, offset_y_rel)
    """
    shadow_w = int(product_w * 1.15)
    shadow_h = max(35, int(product_w * 0.25))
    pad = 40
    total_w = shadow_w + pad * 2
    total_h = shadow_h + pad * 2

    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Stage 1: Soft diffuse ambient cast shadow
    bbox_soft = [pad, pad, pad + shadow_w, pad + shadow_h]
    draw.ellipse(bbox_soft, fill=(0, 0, 0, 110))

    # Stage 2: Sharp ambient occlusion contact shadow directly under base
    inner_w = int(shadow_w * 0.75)
    inner_h = int(shadow_h * 0.45)
    cx, cy = pad + shadow_w // 2, pad + shadow_h // 2
    bbox_sharp = [cx - inner_w // 2, cy - inner_h // 2, cx + inner_w // 2, cy + inner_h // 2]
    draw.ellipse(bbox_sharp, fill=(0, 0, 0, 190))

    canvas = canvas.filter(ImageFilter.GaussianBlur(16))
    return canvas, -(pad + (shadow_w - product_w) // 2), -(pad + shadow_h // 2)


async def remove_background(input_path: Path, output_path: Path | None = None) -> Path:
    """
    Remove background from a product photo using rembg.
    Returns path to the PNG with transparent background.
    """
    from rembg import new_session
    from rembg import remove as rembg_remove

    settings = get_settings()
    if output_path is None:
        output_path = settings.temp_dir / f"nobg_{uuid.uuid4().hex[:8]}.png"

    logger.info("Removing background from: %s (using u2netp)", input_path.name)

    session = new_session("u2netp")
    input_image = Image.open(input_path)
    result = rembg_remove(input_image, session=session)
    result.save(str(output_path), "PNG")

    logger.info("Background removed: %s", output_path.name)
    return output_path


async def composite_product_image(
    product_path: Path,
    hook_text: str,
    category: str | None = None,
    output_size: tuple[int, int] = FEED_SIZE,
    output_path: Path | None = None,
) -> Path:
    """
    Composite product onto a luxury photography template with realistic contact shadows,
    cinematic lighting vignette, and bold modern bakery typography.
    """
    settings = get_settings()
    if output_path is None:
        output_path = settings.temp_dir / f"composite_{uuid.uuid4().hex[:8]}.jpg"

    # ── Step 1: Background ──
    bg_path = _pick_background(category)
    if bg_path:
        canvas = Image.open(bg_path).convert("RGBA")
        canvas = canvas.resize(output_size, Image.LANCZOS)
        logger.info("Using luxury background: %s", bg_path.name)
    else:
        canvas = _create_gradient_background(output_size, category)
        logger.info("Using gradient fallback background")

    # ── Step 2: Realistic Table Grounding ──
    product = Image.open(product_path).convert("RGBA")

    # Scale product to fit naturally on table (~62% width)
    max_w = int(output_size[0] * 0.62)
    max_h = int(output_size[1] * 0.52)
    product.thumbnail((max_w, max_h), Image.LANCZOS)

    # Position on countertop: base sits firmly at ~73% height
    py_bottom = int(canvas.height * 0.73)
    py = py_bottom - product.height
    px = (canvas.width - product.width) // 2

    # Draw tabletop ground contact shadow
    shadow_img, rel_x, rel_y = _create_tabletop_contact_shadow(product.width, product.height)
    shadow_x = px + rel_x
    shadow_y = py_bottom + rel_y
    canvas.paste(shadow_img, (shadow_x, shadow_y), shadow_img)

    # Draw product ambient edge shadow
    body_shadow = _create_drop_shadow(product, offset=(0, 6), blur=16, color=(0, 0, 0, 80))
    canvas.paste(body_shadow, (px - 16, py - 10), body_shadow)

    # Paste actual sharp product on top
    canvas.paste(product, (px, py), product)

    # ── Step 3: Cinematic Bottom Vignette Gradient (for readable text) ──
    vignette = Image.new("RGBA", output_size, (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    vignette_start = int(canvas.height * 0.68)
    for y in range(vignette_start, canvas.height):
        progress = (y - vignette_start) / (canvas.height - vignette_start)
        alpha = int(230 * (progress ** 1.3))
        vdraw.line([(0, y), (canvas.width, y)], fill=(10, 8, 12, alpha))
    canvas = Image.alpha_composite(canvas, vignette)

    # ── Step 4: Luxury Typography & Badges ──
    draw = ImageDraw.Draw(canvas)

    # Top Badge (Artisanal Pill Badge with clean ASCII bullet)
    category_labels = {
        "CUSTOM_CAKE": "SIGNATURE CUSTOM CREATION",
        "DAILY_SNACK": "FRESH FROM THE OVEN",
        "FESTIVAL_SPECIAL": "LIMITED FESTIVAL SPECIAL",
    }
    raw_label = category_labels.get(category, "ARTISANAL BAKERY CREATION")
    badge_label = f"•  {raw_label}  •"
    badge_font = _get_font(21, bold=True)
    bb = draw.textbbox((0, 0), badge_label, font=badge_font)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    bx = (canvas.width - bw) // 2
    by = 50
    pad_x, pad_y = 24, 10
    draw.rounded_rectangle(
        [bx - pad_x, by - pad_y, bx + bw + pad_x, by + bh + pad_y],
        radius=20,
        fill=(16, 12, 14, 190),
        outline=(212, 175, 55, 220),
        width=1,
    )
    draw.text((bx, by), badge_label, fill=(240, 225, 195), font=badge_font)

    # Main Headline (Cleaned Hook Text without emoji box gltich)
    clean_hook = _clean_text_for_pil(hook_text).upper()
    if not clean_hook:
        clean_hook = "HANDCRAFTED DELIGHT"

    title_font = _get_font(44, bold=True)
    tb = draw.textbbox((0, 0), clean_hook, font=title_font)
    tw = tb[2] - tb[0]
    if tw > canvas.width - 120:
        title_font = _get_font(36, bold=True)
        tb = draw.textbbox((0, 0), clean_hook, font=title_font)
        tw = tb[2] - tb[0]

    tx = (canvas.width - tw) // 2
    ty = int(canvas.height * 0.83)

    # Title shadow + text
    draw.text((tx + 2, ty + 2), clean_hook, fill=(0, 0, 0, 200), font=title_font)
    draw.text((tx, ty), clean_hook, fill="white", font=title_font)

    # Sub-tagline / CTA
    cta_text = "Handcrafted Fresh Daily • DM or WhatsApp to Pre-Order"
    cta_font = _get_font(22, bold=False)
    cb = draw.textbbox((0, 0), cta_text, font=cta_font)
    cw = cb[2] - cb[0]
    cx = (canvas.width - cw) // 2
    cy = ty + (tb[3] - tb[1]) + 16
    draw.text((cx, cy), cta_text, fill=(225, 205, 175), font=cta_font)

    # ── Step 5: Brand watermark ──
    logo_path = settings.overlays_dir / "logo.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((110, 110), Image.LANCZOS)
        lx = canvas.width - logo.width - 35
        ly = 45
        canvas.paste(logo, (lx, ly), logo)
    else:
        logger.debug("No logo.png found in overlays/, skipping watermark")

    # ── Save ──
    final = canvas.convert("RGB")
    final.save(str(output_path), "JPEG", quality=95)

    logger.info("Composite image saved: %s", output_path.name)
    return output_path



def _create_gradient_background(
    size: tuple[int, int],
    category: str | None = None,
) -> Image.Image:
    """Create an elegant gradient background as fallback."""
    # Category-based color schemes
    palettes = {
        "DAILY_SNACK": [(45, 30, 20), (80, 55, 35)],       # Warm chocolate brown
        "CUSTOM_CAKE": [(30, 15, 40), (60, 25, 70)],        # Rich plum / royal purple
        "FESTIVAL_SPECIAL": [(50, 15, 15), (90, 30, 20)],   # Deep festive red
    }
    colors = palettes.get(category, [(25, 25, 30), (50, 45, 55)])

    img = Image.new("RGBA", size)
    draw = ImageDraw.Draw(img)

    for y in range(size[1]):
        ratio = y / size[1]
        r = int(colors[0][0] + (colors[1][0] - colors[0][0]) * ratio)
        g = int(colors[0][1] + (colors[1][1] - colors[0][1]) * ratio)
        b = int(colors[0][2] + (colors[1][2] - colors[0][2]) * ratio)
        draw.line([(0, y), (size[0], y)], fill=(r, g, b, 255))

    return img


# ── Full Feed Pipeline ───────────────────────────────────────────────────────

async def process_feed_image(
    input_path: Path,
    hook_text: str,
    category: str | None = None,
    remove_bg: bool = True,
) -> Path:
    """
    Full feed image processing pipeline:
    1. Remove background (if cluttered)
    2. Composite onto luxury template
    3. Add typography + watermark

    Returns path to the final composited image.
    """
    logger.info("═══ Starting Feed Image Pipeline ═══")

    if remove_bg:
        product_path = await remove_background(input_path)
    else:
        product_path = input_path

    output = await composite_product_image(
        product_path=product_path,
        hook_text=hook_text,
        category=category,
    )

    logger.info("═══ Feed Image Pipeline Complete: %s ═══", output.name)
    return output
