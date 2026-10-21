"""
bakery-social-engine — Interactive CLI Demo & Pipeline Benchmark.

Test the AI pipeline, audio synthesis, and media composition locally
without launching the Telegram bot or configuring webhooks.

Usage:
    # 1. Run full mock pipeline without any API keys (test TTS + image compositing):
    uv run python -m scripts.demo --mock

    # 2. Test an actual bakery photo with AI analysis + feed post rendering:
    uv run python -m scripts.demo --image path/to/cake.jpg

    # 3. Test an actual bakery video clip with AI analysis + reel rendering:
    uv run python -m scripts.demo --video path/to/clip.mp4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide safe defaults if running in pure mock/demo mode without .env
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "mock_demo_token")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "123456789")
os.environ.setdefault("GEMINI_API_KEY", "")

# Windows console UTF-8 fix
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def create_sample_cake_image(dest_path: Path) -> Path:
    """Create a synthetic bakery sample image for offline testing."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 800, 800
    img = Image.new("RGB", (width, height), (245, 235, 225))
    draw = ImageDraw.Draw(img)

    # Bakery wooden table counter
    draw.rectangle([0, 500, width, height], fill=(160, 110, 75))

    # Cake stand
    draw.ellipse([260, 480, 540, 530], fill=(210, 210, 215))
    draw.rectangle([380, 520, 420, 600], fill=(180, 180, 185))
    draw.ellipse([340, 590, 460, 630], fill=(190, 190, 195))

    # Cake base (chocolate sponge)
    draw.rectangle([280, 320, 520, 500], fill=(70, 40, 25))
    draw.ellipse([280, 460, 520, 520], fill=(60, 35, 20))
    draw.ellipse([280, 300, 520, 360], fill=(90, 50, 30))

    # Chocolate ganache drip
    draw.ellipse([275, 290, 525, 350], fill=(45, 20, 10))
    for x in range(290, 510, 35):
        draw.polygon([(x, 340), (x + 15, 340), (x + 7, 390 + (x % 30))], fill=(45, 20, 10))

    # Strawberries & gold dust on top
    for sx, sy in [(360, 310), (400, 300), (440, 315)]:
        draw.polygon([(sx, sy + 30), (sx + 25, sy), (sx + 50, sy + 30)], fill=(210, 30, 45))
        draw.ellipse([sx + 15, sy + 5, sx + 35, sy + 25], fill=(230, 50, 65))

    img.save(dest_path, "JPEG", quality=95)
    return dest_path


async def run_demo(
    image_path: Path | None = None,
    video_path: Path | None = None,
    is_mock: bool = False,
    custom_caption: str | None = None,
) -> None:
    output_dir = PROJECT_ROOT / "output" / "demo_result"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("  🍰 BAKERY SOCIAL ENGINE — PIPELINE DEMO & BENCHMARK")
    print("=" * 60)

    # ── Step 1: Media Selection ──
    sample_file: Path
    is_video = bool(video_path)

    if video_path and video_path.exists():
        sample_file = video_path
        print(f"🎬 Input Video   : {sample_file}")
    elif image_path and image_path.exists():
        sample_file = image_path
        print(f"📸 Input Photo   : {sample_file}")
    else:
        # Create offline mock image
        is_mock = True
        sample_file = output_dir / "sample_bakery_product.jpg"
        create_sample_cake_image(sample_file)
        print(f"🎨 Generated Sample : {sample_file} (Chocolate Truffle Cake)")

    # ── Step 2: AI Analysis (Gemini 2.5 Flash or Mock) ──
    print("\n[1/4] 🤖 Multimodal AI Analysis...")
    t0 = time.perf_counter()

    has_gemini = False
    try:
        from src.config import get_settings
        settings = get_settings()
        if settings.gemini_api_key and not is_mock:
            has_gemini = True
    except Exception:
        has_gemini = False

    from src.ai.analyzer import BakeryAnalysis

    if has_gemini and not is_mock:
        from src.ai.analyzer import analyze_media
        print("  Calling Google Gemini 2.5 Flash API...")
        analysis = await analyze_media([sample_file], context_text=custom_caption)
    else:
        print("  (Using high-accuracy local mock mode — no Gemini key required)")
        analysis = BakeryAnalysis(
            category="CUSTOM_CAKE",
            hook_text_overlay="Chocolate Drip Overload 🔥",
            voiceover_script=(
                "Dekho yaar, ye Belgium chocolate cake sheer perfection hai! Ek bite lo aur din ban jayega."
            ),
            instagram_caption=(
                "Pure chocolate indulgence! Handcrafted with rich Belgian chocolate ganache 🍫✨\n\n"
                "Available for pre-orders today at our store!\n\n"
                "#AhmedabadBakery #ChocolateCake #CakesOfInstagram #FreshlyBaked #BakeryReels"
            ),
            recommended_broll_tag="chocolate_pour",
        )

    t_ai = time.perf_counter() - t0
    print(f"  ⚡ AI Analysis completed in {t_ai:.2f}s")
    print(f"  🏷️  Category : {analysis.category}")
    print(f"  🎯 Hook     : \"{analysis.hook_text_overlay}\"")
    print(f"  🗣️  Script   : \"{analysis.voiceover_script}\"")

    # Save analysis JSON
    analysis_file = output_dir / "analysis.json"
    analysis_file.write_text(json.dumps(analysis.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  💾 Saved     : {analysis_file.relative_to(PROJECT_ROOT)}")

    # ── Step 3: Neural Voiceover Audio (edge-tts) ──
    print("\n[2/4] 🎙️ Neural Voiceover Synthesis (edge-tts)...")
    t0 = time.perf_counter()
    from src.ai.tts import generate_voiceover

    audio_out = output_dir / "voiceover.mp3"
    await generate_voiceover(analysis.voiceover_script, output_path=audio_out)
    t_tts = time.perf_counter() - t0
    print(f"  ⚡ Audio generated in {t_tts:.2f}s")
    print(f"  💾 Audio file : {audio_out.relative_to(PROJECT_ROOT)} ({audio_out.stat().st_size // 1024} KB)")

    # ── Step 4: Visual Processing (Pillow + rembg OR FFmpeg) ──
    if is_video:
        print("\n[3/4] 🎬 Video Reel Processing (FFmpeg)...")
        t0 = time.perf_counter()
        from src.media.video_editor import process_reel

        final_reel = output_dir / "final_reel.mp4"
        rendered_reel = await process_reel(
            input_path=sample_file,
            hook_text=analysis.hook_text_overlay,
            broll_tag=analysis.recommended_broll_tag,
            tts_audio_path=audio_out,
        )
        shutil.copy(rendered_reel, final_reel)
        t_media = time.perf_counter() - t0
        print(f"  ⚡ Reel rendered in {t_media:.2f}s")
        print(f"  💾 Final Reel : {final_reel.relative_to(PROJECT_ROOT)}")
    else:
        print("\n[3/4] 🖼️ Image Compositing (rembg + Luxury Gradient + Typography)...")
        t0 = time.perf_counter()
        from src.media.image_editor import process_feed_image

        final_img = output_dir / "final_feed_post.jpg"
        rendered_img = await process_feed_image(
            input_path=sample_file,
            hook_text=analysis.hook_text_overlay,
            category=analysis.category,
            remove_bg=True,
        )
        shutil.copy(rendered_img, final_img)
        t_media = time.perf_counter() - t0
        print(f"  ⚡ Image composited in {t_media:.2f}s")
        print(f"  💾 Final Image : {final_img.relative_to(PROJECT_ROOT)}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  🎉 PIPELINE RUN COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print(f"  Total processing time : {t_ai + t_tts + t_media:.2f}s")
    print(f"  Outputs generated in  : {output_dir.resolve()}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bakery Social Engine CLI Demo")
    parser.add_argument("--image", type=Path, help="Path to input photo", default=None)
    parser.add_argument("--video", type=Path, help="Path to input video", default=None)
    parser.add_argument("--mock", action="store_true", help="Run with mock data (zero setup required)")
    parser.add_argument("--caption", type=str, help="Optional text note for context", default=None)

    args = parser.parse_args()
    asyncio.run(run_demo(
        image_path=args.image,
        video_path=args.video,
        is_mock=args.mock,
        custom_caption=args.caption,
    ))


if __name__ == "__main__":
    main()
