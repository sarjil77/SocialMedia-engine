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
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.config import get_settings

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
FEED_SIZE = (1080, 1080)      # Instagram feed square
STORY_SIZE = (1080, 1920)     # Instagram story / reel cover
SHADOW_OFFSET = (12, 12)
SHADOW_BLUR = 25
SHADOW_COLOR = (0, 0, 0, 100)


def _get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Load the best available font from assets/fonts/."""
    settings = get_settings()
    font_dir = settings.fonts_dir

    candidates = [
        font_dir / "Montserrat-ExtraBold.ttf",
        font_dir / "Montserrat-Bold.ttf",
        font_dir / "Poppins-Bold.ttf",
    ] if bold else [
        font_dir / "Montserrat-Regular.ttf",
        font_dir / "Poppins-Regular.ttf",
    ]

    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)

    logger.warning("No custom font found, using Pillow default")
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _pick_background(category: str | None = None) -> Optional[Path]:
    """Pick a background image from assets/backgrounds/."""
    settings = get_settings()
    bg_dir = settings.backgrounds_dir

    backgrounds = list(bg_dir.glob("*.jpg")) + list(bg_dir.glob("*.png"))
    if not backgrounds:
        logger.warning("No background images found in %s", bg_dir)
        return None

    # TODO: Category-based selection logic
    return random.choice(backgrounds)


def _create_drop_shadow(
    image: Image.Image,
    offset: tuple[int, int] = SHADOW_OFFSET,
    blur: int = SHADOW_BLUR,
    color: tuple[int, int, int, int] = SHADOW_COLOR,
) -> Image.Image:
    """Create a realistic drop shadow for a transparent PNG."""
    # Use the alpha channel of the original as shadow shape
    if image.mode == "RGBA":
        alpha = image.split()[3]
        shadow_shape = Image.new("RGBA", image.size, color)
        shadow_shape.putalpha(alpha)
    else:
        shadow_shape = Image.new("RGBA", image.size, color)

    # Apply blur
    shadow_shape = shadow_shape.filter(ImageFilter.GaussianBlur(blur))

    # Create canvas with space for shadow
    canvas_w = image.width + abs(offset[0]) + blur * 2
    canvas_h = image.height + abs(offset[1]) + blur * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # Paste shadow offset
    sx = blur + max(0, offset[0])
    sy = blur + max(0, offset[1])
    canvas.paste(shadow_shape, (sx, sy))

    # Paste original on top
    ix = blur + max(0, -offset[0])
    iy = blur + max(0, -offset[1])
    canvas.paste(image, (ix, iy), image if image.mode == "RGBA" else None)

    return canvas


async def remove_background(input_path: Path, output_path: Path | None = None) -> Path:
    """
    Remove background from a product photo using rembg.
    Returns path to the PNG with transparent background.
    """
    # Import rembg lazily (heavy model loading)
    from rembg import remove as rembg_remove

    settings = get_settings()
    if output_path is None:
        output_path = settings.temp_dir / f"nobg_{uuid.uuid4().hex[:8]}.png"

    logger.info("Removing background from: %s", input_path.name)

    input_image = Image.open(input_path)
    result = rembg_remove(input_image)
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
    Composite a product photo (with transparent background) onto a luxury
    template background with drop shadow, typography, and brand watermark.

    Args:
        product_path: Path to PNG with transparent background.
        hook_text: Text to overlay on the image.
        category: Product category for background selection.
        output_size: Output dimensions (default: 1080×1080 feed square).
        output_path: Where to save the final image.

    Returns:
        Path to the composited image.
    """
    settings = get_settings()
    if output_path is None:
        output_path = settings.temp_dir / f"composite_{uuid.uuid4().hex[:8]}.jpg"

    # ── Step 1: Background ──
    bg_path = _pick_background(category)
    if bg_path:
        canvas = Image.open(bg_path).convert("RGBA")
        canvas = canvas.resize(output_size, Image.LANCZOS)
        logger.info("Using background: %s", bg_path.name)
    else:
        # Elegant gradient fallback
        canvas = _create_gradient_background(output_size, category)
        logger.info("Using gradient fallback background")

    # ── Step 2: Product with shadow ──
    product = Image.open(product_path).convert("RGBA")

    # Scale product to fit ~65% of canvas width
    max_product_w = int(output_size[0] * 0.65)
    max_product_h = int(output_size[1] * 0.55)
    product.thumbnail((max_product_w, max_product_h), Image.LANCZOS)

    # Add drop shadow
    product_with_shadow = _create_drop_shadow(product)

    # Center the product (slightly above center for text space)
    px = (canvas.width - product_with_shadow.width) // 2
    py = int((canvas.height - product_with_shadow.height) * 0.35)
    canvas.paste(product_with_shadow, (px, py), product_with_shadow)

    # ── Step 3: Typography ──
    draw = ImageDraw.Draw(canvas)

    # Hook text — bold, centered, bottom third
    font = _get_font(56)
    text_bbox = draw.textbbox((0, 0), hook_text, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_x = (canvas.width - text_w) // 2
    text_y = int(canvas.height * 0.78)

    # Text shadow for readability
    draw.text((text_x + 2, text_y + 2), hook_text, fill=(0, 0, 0, 150), font=font)
    draw.text((text_x, text_y), hook_text, fill="white", font=font)

    # ── Step 4: Brand watermark ──
    logo_path = settings.overlays_dir / "logo.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((120, 120), Image.LANCZOS)
        # Bottom-right corner with padding
        lx = canvas.width - logo.width - 30
        ly = canvas.height - logo.height - 30
        canvas.paste(logo, (lx, ly), logo)
        logger.info("Brand watermark applied")
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
