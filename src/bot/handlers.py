"""
bakery-social-engine — Telegram Bot handlers.

This is the heart of the human-in-the-loop pipeline:
1. Receives media (photos/videos) + optional captions/voice notes from bakery staff
2. Triggers AI analysis → media processing → sends preview to admin
3. Handles approval callback buttons (publish / schedule / regenerate / discard)
"""

from __future__ import annotations

import json
import logging
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.ai.analyzer import BakeryAnalysis, analyze_media
from src.ai.tts import generate_voiceover
from src.bot.keyboards import (
    approval_keyboard,
    confirm_publish_keyboard,
    schedule_options_keyboard,
)
from src.config import get_settings
from src.db import (
    PostStatus,
    PostType,
    create_post,
    get_post,
    update_post,
)
from src.media.image_editor import process_feed_image
from src.media.video_editor import process_reel
from src.publisher.instagram import publish_media

logger = logging.getLogger(__name__)


# ── Helper: Download Telegram file to local path ─────────────────────────────

async def _download_telegram_file(message: Message, file_id: str, suffix: str) -> Path:
    """Download a file from Telegram to our temp directory."""
    settings = get_settings()
    file = await message.get_bot().get_file(file_id)
    local_path = settings.temp_dir / f"tg_{file.file_unique_id}{suffix}"
    await file.download_to_drive(str(local_path))
    logger.info("Downloaded Telegram file: %s → %s", file_id[:12], local_path.name)
    return local_path


def _is_video(path: Path) -> bool:
    """Check if a file is a video based on MIME type."""
    mime, _ = mimetypes.guess_type(str(path))
    return mime is not None and mime.startswith("video")


# ── /start command ───────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message when the bot is started."""
    await update.message.reply_text(
        "🍰 *Bakery Social Engine* is ready!\n\n"
        "Send me photos or videos of your bakery products and I'll create "
        "viral-ready Instagram content for you.\n\n"
        "📸 Send 1-3 photos for a *Feed Post*\n"
        "🎬 Send a video for a *Reel*\n"
        "🎤 Add a caption or voice note for context\n\n"
        "_Powered by Gemini AI + FFmpeg_",
        parse_mode="Markdown",
    )


# ── /status command ──────────────────────────────────────────────────────────

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot status and stats."""
    await update.message.reply_text(
        "✅ Bot is running\n"
        "🤖 AI Model: gemini-2.5-flash\n"
        "🎙️ TTS: edge-tts\n"
        "📊 Use /help for commands",
    )


# ── /help command ────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help text."""
    await update.message.reply_text(
        "📖 *Commands:*\n\n"
        "/start — Welcome & instructions\n"
        "/status — Check bot status\n"
        "/help — This message\n\n"
        "*How to use:*\n"
        "1️⃣ Send photos or a video of your product\n"
        "2️⃣ Optionally add a caption or voice note\n"
        "3️⃣ Wait for AI to process (~30 seconds)\n"
        "4️⃣ Review and approve the generated content\n"
        "5️⃣ Publish or schedule it!",
        parse_mode="Markdown",
    )


# ── Media ingestion handler ─────────────────────────────────────────────────

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main media ingestion handler.

    Handles:
    - Single/multiple photos
    - Video messages
    - Video notes (round videos)
    - With optional text captions
    """
    message = update.message

    # Show processing indicator
    processing_msg = await message.reply_text(
        "⏳ *Received!* Processing your media...\n"
        "🤖 Running AI analysis with Gemini...",
        parse_mode="Markdown",
    )

    try:
        # ── Collect media files ──
        media_paths: list[Path] = []
        is_video_content = False
        caption_text = message.caption or ""

        if message.photo:
            # Get highest resolution photo
            photo = message.photo[-1]
            path = await _download_telegram_file(message, photo.file_id, ".jpg")
            media_paths.append(path)

        elif message.video:
            path = await _download_telegram_file(message, message.video.file_id, ".mp4")
            media_paths.append(path)
            is_video_content = True

        elif message.video_note:
            path = await _download_telegram_file(message, message.video_note.file_id, ".mp4")
            media_paths.append(path)
            is_video_content = True

        elif message.document:
            doc = message.document
            ext = Path(doc.file_name).suffix if doc.file_name else ".bin"
            path = await _download_telegram_file(message, doc.file_id, ext)
            media_paths.append(path)
            is_video_content = _is_video(path)

        if not media_paths:
            await processing_msg.edit_text("❌ No media found. Please send photos or videos.")
            return

        # ── Check for media group (multiple photos) ──
        # Store in context for media group handling
        if message.media_group_id:
            group_key = f"media_group_{message.media_group_id}"
            if group_key not in context.chat_data:
                context.chat_data[group_key] = {
                    "paths": [],
                    "caption": "",
                    "processing_msg_id": processing_msg.message_id,
                }
            context.chat_data[group_key]["paths"].extend(media_paths)
            if caption_text:
                context.chat_data[group_key]["caption"] = caption_text

            # Schedule delayed processing to collect all group media
            context.job_queue.run_once(
                _process_media_group,
                when=2.0,  # Wait 2s for all group messages to arrive
                data={
                    "group_key": group_key,
                    "chat_id": message.chat_id,
                },
                name=f"group_{message.media_group_id}",
            )
            return

        # ── Single media: process immediately ──
        await _run_pipeline(
            chat_id=message.chat_id,
            media_paths=media_paths,
            caption_text=caption_text,
            is_video=is_video_content,
            processing_msg=processing_msg,
            context=context,
        )

    except Exception as e:
        logger.exception("Error processing media")
        await processing_msg.edit_text(
            f"❌ *Error processing media:*\n`{str(e)[:200]}`",
            parse_mode="Markdown",
        )


async def _process_media_group(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a collected media group after a brief delay."""
    job = context.job
    data = job.data
    group_key = data["group_key"]
    chat_id = data["chat_id"]

    group_data = context.chat_data.get(group_key)
    if not group_data:
        return

    media_paths = group_data["paths"]
    caption_text = group_data["caption"]
    processing_msg_id = group_data["processing_msg_id"]

    # Clean up
    del context.chat_data[group_key]

    # Check if any are videos
    is_video = any(_is_video(p) for p in media_paths)

    try:
        # Get the processing message to edit
        bot = context.bot
        await bot.edit_message_text(
            text=(
                f"⏳ *Processing {len(media_paths)} media files...*\n"
                "🤖 Running AI analysis with Gemini..."
            ),
            chat_id=chat_id,
            message_id=processing_msg_id,
            parse_mode="Markdown",
        )

        await _run_pipeline(
            chat_id=chat_id,
            media_paths=media_paths,
            caption_text=caption_text,
            is_video=is_video,
            processing_msg=None,  # We'll manage messages manually
            context=context,
            processing_msg_id=processing_msg_id,
        )

    except Exception as e:
        logger.exception("Error processing media group")
        await context.bot.edit_message_text(
            text=f"❌ *Error:* `{str(e)[:200]}`",
            chat_id=chat_id,
            message_id=processing_msg_id,
            parse_mode="Markdown",
        )


# ── Voice note handler ──────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice notes — store the transcription context for the next media."""
    message = update.message
    voice = message.voice

    # Download voice note
    path = await _download_telegram_file(message, voice.file_id, ".ogg")

    # Store voice note path for next media message
    context.chat_data["pending_voice"] = str(path)

    await message.reply_text(
        "🎤 Voice note received! Now send your photos/videos and I'll use "
        "this voice context for AI analysis.",
    )


# ── Core Pipeline Runner ────────────────────────────────────────────────────

async def _run_pipeline(
    chat_id: int,
    media_paths: list[Path],
    caption_text: str,
    is_video: bool,
    context: ContextTypes.DEFAULT_TYPE,
    processing_msg: Message | None = None,
    processing_msg_id: int | None = None,
) -> None:
    """
    Run the full pipeline:
    1. AI analysis
    2. Media processing (video or image)
    3. Send preview + approval keyboard to admin
    """
    settings = get_settings()
    bot = context.bot

    # Helper to update status message
    async def _update_status(text: str) -> None:
        try:
            if processing_msg:
                await processing_msg.edit_text(text, parse_mode="Markdown")
            elif processing_msg_id:
                await bot.edit_message_text(
                    text=text,
                    chat_id=chat_id,
                    message_id=processing_msg_id,
                    parse_mode="Markdown",
                )
        except Exception:
            pass

    # ── Step 1: Determine post type ──
    post_type = PostType.REEL if is_video else PostType.FEED

    # ── Step 2: Create DB record ──
    post_id = await create_post(
        telegram_msg_id=processing_msg.message_id if processing_msg else processing_msg_id,
        chat_id=chat_id,
        post_type=post_type,
        raw_media_paths=[str(p) for p in media_paths],
    )

    # ── Step 3: Check for pending voice context ──
    voice_path = context.chat_data.pop("pending_voice", None)
    if voice_path:
        # Add voice note to media for Gemini analysis
        media_paths.append(Path(voice_path))

    # ── Step 4: AI Analysis ──
    await _update_status(
        "🤖 *Step 1/3:* Analyzing with Gemini AI...\n"
        f"📁 {len(media_paths)} file(s) | 🏷️ {post_type.value}"
    )

    analysis: BakeryAnalysis = await analyze_media(
        media_paths=media_paths,
        context_text=caption_text if caption_text else None,
    )

    # Update DB with AI results
    await update_post(
        post_id,
        category=analysis.category,
        hook_text=analysis.hook_text_overlay,
        voiceover_script=analysis.voiceover_script,
        instagram_caption=analysis.instagram_caption,
        broll_tag=analysis.recommended_broll_tag,
    )

    # ── Step 5: Generate TTS (if enabled) ──
    tts_audio_path = None
    if settings.enable_voiceover and is_video:
        await _update_status(
            "🎙️ *Step 2/3:* Generating voiceover...\n"
            f"📝 Category: `{analysis.category}`"
        )
        tts_audio_path = settings.temp_dir / f"tts_{post_id}.mp3"
        tts_audio_path = await generate_voiceover(
            text=analysis.voiceover_script,
            output_path=tts_audio_path,
        )
        if tts_audio_path:
            await update_post(post_id, tts_audio_path=str(tts_audio_path))

    # ── Step 6: Media Processing ──
    await _update_status(
        "🎬 *Step 3/3:* Processing media...\n"
        f"🏷️ `{analysis.category}` | 💬 _{analysis.hook_text_overlay}_"
    )

    if is_video:
        processed_path = await process_reel(
            input_path=media_paths[0],  # Primary video
            hook_text=analysis.hook_text_overlay,
            broll_tag=analysis.recommended_broll_tag,
            tts_audio_path=tts_audio_path,
        )
    else:
        processed_path = await process_feed_image(
            input_path=media_paths[0],  # Primary photo
            hook_text=analysis.hook_text_overlay,
            category=analysis.category,
        )

    await update_post(post_id, processed_media_path=str(processed_path))

    # ── Step 7: Send preview to admin ──
    admin_chat_id = settings.telegram_admin_chat_id

    preview_caption = (
        f"🍰 *New {post_type.value} Ready!* (#{post_id})\n\n"
        f"📂 Category: `{analysis.category}`\n"
        f"💬 Hook: _{analysis.hook_text_overlay}_\n"
        f"🎬 B-roll: `{analysis.recommended_broll_tag}`\n\n"
        f"📝 *Caption:*\n{analysis.instagram_caption[:500]}\n\n"
        f"───────────────────\n"
        f"🎙️ *Voiceover:*\n_{analysis.voiceover_script}_"
    )

    if is_video:
        await bot.send_video(
            chat_id=admin_chat_id,
            video=open(processed_path, "rb"),
            caption=preview_caption,
            parse_mode="Markdown",
            reply_markup=approval_keyboard(post_id),
            supports_streaming=True,
        )
    else:
        await bot.send_photo(
            chat_id=admin_chat_id,
            photo=open(processed_path, "rb"),
            caption=preview_caption,
            parse_mode="Markdown",
            reply_markup=approval_keyboard(post_id),
        )

    await _update_status(
        f"✅ *Done!* Post #{post_id} sent to admin for approval.\n"
        f"Category: `{analysis.category}`"
    )


# ── Callback Query Handlers (Approval Buttons) ──────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route callback queries from inline keyboard buttons."""
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split(":")

    action = parts[0]

    handlers = {
        "publish": _handle_publish,
        "confirm_publish": _handle_confirm_publish,
        "schedule": _handle_schedule,
        "schedule_time": _handle_schedule_time,
        "regenerate": _handle_regenerate,
        "discard": _handle_discard,
        "back": _handle_back,
    }

    handler = handlers.get(action)
    if handler:
        await handler(query, parts, context)
    else:
        logger.warning("Unknown callback action: %s", action)


async def _handle_publish(query, parts, context) -> None:
    """Show publish confirmation."""
    post_id = int(parts[1])
    await query.edit_message_reply_markup(
        reply_markup=confirm_publish_keyboard(post_id),
    )


async def _handle_confirm_publish(query, parts, context) -> None:
    """Execute the actual publish to Instagram."""
    post_id = int(parts[1])
    post = await get_post(post_id)

    if not post:
        await query.edit_message_caption(caption="❌ Post not found.")
        return

    await query.edit_message_caption(
        caption=f"⏳ *Publishing post #{post_id} to Instagram...*",
        parse_mode="Markdown",
    )

    try:
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

        await query.edit_message_caption(
            caption=(
                f"✅ *Published to Instagram!*\n\n"
                f"📱 Post #{post_id}\n"
                f"🆔 Media ID: `{result['media_id']}`"
            ),
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.exception("Publishing failed for post #%d", post_id)
        await update_post(post_id, status=PostStatus.FAILED, error_message=str(e))
        await query.edit_message_caption(
            caption=f"❌ *Publishing failed:*\n`{str(e)[:300]}`",
            parse_mode="Markdown",
        )


async def _handle_schedule(query, parts, context) -> None:
    """Show schedule time options."""
    post_id = int(parts[1])
    await query.edit_message_reply_markup(
        reply_markup=schedule_options_keyboard(post_id),
    )


async def _handle_schedule_time(query, parts, context) -> None:
    """Schedule the post for a specific time."""
    # parts = ["schedule_time", "HH:MM", post_id]
    time_str = parts[1] + ":" + parts[2]  # "18:00"
    post_id = int(parts[3])

    hour, minute = map(int, time_str.split(":"))

    # Calculate next occurrence of the specified time (IST)
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime.now(ist)
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled <= now:
        scheduled += timedelta(days=1)

    scheduled_utc = scheduled.astimezone(timezone.utc)

    await update_post(
        post_id,
        status=PostStatus.SCHEDULED,
        scheduled_at=scheduled_utc.isoformat(),
    )

    await query.edit_message_caption(
        caption=(
            f"📅 *Post #{post_id} Scheduled!*\n\n"
            f"⏰ Publishing at: {scheduled.strftime('%I:%M %p IST, %d %b %Y')}\n"
            f"_Will be published automatically._"
        ),
        parse_mode="Markdown",
    )

    logger.info("Post #%d scheduled for %s", post_id, scheduled_utc.isoformat())


async def _handle_regenerate(query, parts, context) -> None:
    """Regenerate the AI copy for the post."""
    post_id = int(parts[1])
    post = await get_post(post_id)

    if not post:
        await query.edit_message_caption(caption="❌ Post not found.")
        return

    await query.edit_message_caption(
        caption=f"🔄 *Regenerating copy for post #{post_id}...*",
        parse_mode="Markdown",
    )

    try:
        raw_paths = json.loads(post["raw_media_paths"]) if post["raw_media_paths"] else []
        media_paths = [Path(p) for p in raw_paths]

        # Re-run AI analysis
        analysis = await analyze_media(media_paths=media_paths)

        # Update DB
        await update_post(
            post_id,
            category=analysis.category,
            hook_text=analysis.hook_text_overlay,
            voiceover_script=analysis.voiceover_script,
            instagram_caption=analysis.instagram_caption,
            broll_tag=analysis.recommended_broll_tag,
        )

        preview_caption = (
            f"🔄 *Regenerated Copy for #{post_id}*\n\n"
            f"📂 Category: `{analysis.category}`\n"
            f"💬 Hook: _{analysis.hook_text_overlay}_\n\n"
            f"📝 *Caption:*\n{analysis.instagram_caption[:500]}\n\n"
            f"🎙️ *Voiceover:*\n_{analysis.voiceover_script}_"
        )

        await query.edit_message_caption(
            caption=preview_caption,
            parse_mode="Markdown",
            reply_markup=approval_keyboard(post_id),
        )

    except Exception as e:
        logger.exception("Regeneration failed for post #%d", post_id)
        await query.edit_message_caption(
            caption=f"❌ *Regeneration failed:*\n`{str(e)[:300]}`",
            parse_mode="Markdown",
            reply_markup=approval_keyboard(post_id),
        )


async def _handle_discard(query, parts, context) -> None:
    """Discard the post."""
    post_id = int(parts[1])
    await update_post(post_id, status=PostStatus.DISCARDED)

    await query.edit_message_caption(
        caption=f"❌ Post #{post_id} discarded.",
    )
    logger.info("Post #%d discarded", post_id)


async def _handle_back(query, parts, context) -> None:
    """Go back to the main approval keyboard."""
    post_id = int(parts[1])
    post = await get_post(post_id)

    if post:
        await query.edit_message_reply_markup(
            reply_markup=approval_keyboard(post_id),
        )


# ── Register all handlers ───────────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    """Register all bot handlers with the Application."""
    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("help", help_command))

    # Media ingestion (photos, videos, documents)
    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL,
            handle_media,
        )
    )

    # Voice notes
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Callback queries (inline keyboard buttons)
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("All bot handlers registered")
