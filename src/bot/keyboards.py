"""
bakery-social-engine — Inline keyboard layouts for Telegram approval flow.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def approval_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """
    Approval keyboard shown to admin after media processing.

    Buttons:
    - ✅ Publish Now
    - 📅 Schedule 6 PM
    - 🔄 Regenerate Copy
    - ❌ Discard
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Publish Now",
                    callback_data=f"publish:{post_id}",
                ),
                InlineKeyboardButton(
                    "📅 Schedule 6 PM",
                    callback_data=f"schedule:{post_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔄 Regenerate Copy",
                    callback_data=f"regenerate:{post_id}",
                ),
                InlineKeyboardButton(
                    "❌ Discard",
                    callback_data=f"discard:{post_id}",
                ),
            ],
        ]
    )


def confirm_publish_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Confirmation before publishing."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes, Publish!",
                    callback_data=f"confirm_publish:{post_id}",
                ),
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=f"back:{post_id}",
                ),
            ],
        ]
    )


def schedule_options_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Schedule time picker."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🕕 6:00 PM", callback_data=f"schedule_time:18:00:{post_id}"),
                InlineKeyboardButton("🕘 9:00 AM", callback_data=f"schedule_time:09:00:{post_id}"),
            ],
            [
                InlineKeyboardButton("🕛 12:00 PM", callback_data=f"schedule_time:12:00:{post_id}"),
                InlineKeyboardButton("🕘 9:00 PM", callback_data=f"schedule_time:21:00:{post_id}"),
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data=f"back:{post_id}"),
            ],
        ]
    )
