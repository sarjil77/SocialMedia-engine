"""
bakery-social-engine — Main Entrypoint.

Starts:
1. Telegram Bot (polling mode)
2. APScheduler for processing scheduled posts
3. Optional FastAPI health/webhook server

Usage:
    uv run python -m src.main
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from src.bot.handlers import register_handlers
from src.config import get_settings
from src.db import (
    PostStatus,
    PostType,
    get_due_scheduled_posts,
    init_db,
    update_post,
)
from src.publisher.instagram import publish_media

# ── Logging setup ────────────────────────────────────────────────────────────


def _setup_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s │ %(levelname)-8s │ %(name)-30s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)


# ── Scheduled Post Processor ────────────────────────────────────────────────


async def process_scheduled_posts() -> None:
    """
    Check for scheduled posts that are due and publish them.
    Runs on a periodic schedule via APScheduler.
    """
    logger = logging.getLogger("scheduler")

    try:
        due_posts = await get_due_scheduled_posts()
        if not due_posts:
            return

        logger.info("Found %d scheduled post(s) due for publishing", len(due_posts))

        for post in due_posts:
            post_id = post["id"]
            try:
                logger.info("Publishing scheduled post #%d...", post_id)
                await update_post(post_id, status=PostStatus.UPLOADING)

                post_type = PostType(post["post_type"])
                result = await publish_media(
                    file_path=Path(post["processed_media_path"]),
                    caption=post["instagram_caption"],
                    post_type=post_type,
                )

                await update_post(
                    post_id,
                    status=PostStatus.PUBLISHED,
                    cloudinary_url=result["cloudinary_url"],
                    ig_container_id=result["container_id"],
                    ig_media_id=result["media_id"],
                    published_at=datetime.now(timezone.utc).isoformat(),
                )

                logger.info("✅ Scheduled post #%d published successfully!", post_id)

            except Exception as e:
                logger.exception("Failed to publish scheduled post #%d", post_id)
                await update_post(
                    post_id,
                    status=PostStatus.FAILED,
                    error_message=str(e),
                )

    except Exception as e:
        logger.exception("Error in scheduled post processor: %s", e)


# ── Main ─────────────────────────────────────────────────────────────────────


async def main() -> None:
    """Start all services."""
    _setup_logging()
    logger = logging.getLogger("main")

    settings = get_settings()

    logger.info("═══════════════════════════════════════════")
    logger.info("  🍰 Bakery Social Engine — Starting Up")
    logger.info("═══════════════════════════════════════════")
    logger.info("  AI Model  : %s", settings.gemini_model)
    logger.info("  TTS       : %s (%s)", settings.tts_provider, settings.edge_tts_voice)
    logger.info("  Voiceover : %s", "Enabled" if settings.enable_voiceover else "Disabled")
    logger.info("  Schedule  : %02d:%02d daily", settings.default_schedule_hour, settings.default_schedule_minute)
    logger.info("═══════════════════════════════════════════")

    # ── Initialize database ──
    await init_db()

    # ── Set up APScheduler ──
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        process_scheduled_posts,
        "interval",
        minutes=1,
        id="scheduled_post_processor",
        name="Process scheduled posts",
        misfire_grace_time=60,
    )
    scheduler.start()
    logger.info("📅 Scheduler started (checking every 60s for due posts)")

    # ── Build Telegram Bot Application ──
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Register all handlers
    register_handlers(app)

    # ── Start polling ──
    logger.info("🤖 Starting Telegram bot (polling mode)...")
    logger.info("   Send /start to the bot to begin!")

    # Initialize and start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )

    logger.info("✅ Bot is running! Press Ctrl+C to stop.")

    # Keep running until interrupted
    try:
        # Block forever — bot polling runs in background
        stop_event = asyncio.Event()
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received...")
    finally:
        logger.info("Shutting down...")
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("👋 Bakery Social Engine stopped. Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
