"""
bakery-social-engine — SQLite database layer.

Tracks every post through its lifecycle:
  DRAFT → APPROVED → UPLOADING → PUBLISHED / FAILED / DISCARDED
"""

from __future__ import annotations

import aiosqlite
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "bakery.db"


class PostStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    UPLOADING = "UPLOADING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DISCARDED = "DISCARDED"


class PostType(str, Enum):
    REEL = "REEL"
    FEED = "FEED"
    STORY = "STORY"


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_msg_id INTEGER,
    chat_id         INTEGER,
    post_type       TEXT NOT NULL DEFAULT 'FEED',
    category        TEXT,
    status          TEXT NOT NULL DEFAULT 'DRAFT',

    -- AI-generated content
    hook_text       TEXT,
    voiceover_script TEXT,
    instagram_caption TEXT,
    broll_tag       TEXT,

    -- File paths
    raw_media_paths TEXT,          -- JSON array of local file paths
    processed_media_path TEXT,     -- Final rendered file path
    tts_audio_path  TEXT,

    -- Publishing
    cloudinary_url  TEXT,
    ig_container_id TEXT,
    ig_media_id     TEXT,
    scheduled_at    TEXT,          -- ISO timestamp for scheduled posts
    published_at    TEXT,          -- ISO timestamp when actually published

    -- Meta
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON posts(scheduled_at);
"""


async def init_db() -> None:
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)


async def create_post(
    *,
    telegram_msg_id: int | None = None,
    chat_id: int | None = None,
    post_type: PostType = PostType.FEED,
    category: str | None = None,
    raw_media_paths: list[str] | None = None,
) -> int:
    """Insert a new draft post and return its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO posts (telegram_msg_id, chat_id, post_type, category, raw_media_paths, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_msg_id,
                chat_id,
                post_type.value,
                category,
                json.dumps(raw_media_paths or []),
                PostStatus.DRAFT.value,
            ),
        )
        await db.commit()
        post_id = cursor.lastrowid
        logger.info("Created post #%d (type=%s)", post_id, post_type.value)
        return post_id


async def update_post(post_id: int, **fields: Any) -> None:
    """Update arbitrary fields on a post row."""
    if not fields:
        return

    # Serialize lists/dicts to JSON strings
    for key, val in fields.items():
        if isinstance(val, (list, dict)):
            fields[key] = json.dumps(val)
        elif isinstance(val, Enum):
            fields[key] = val.value

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values())
    values.append(datetime.now(timezone.utc).isoformat())  # updated_at
    values.append(post_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE posts SET {set_clause}, updated_at = ? WHERE id = ?",
            values,
        )
        await db.commit()
    logger.debug("Updated post #%d: %s", post_id, list(fields.keys()))


async def get_post(post_id: int) -> Optional[dict]:
    """Fetch a single post by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)


async def get_posts_by_status(status: PostStatus) -> list[dict]:
    """Fetch all posts with a given status."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM posts WHERE status = ? ORDER BY created_at DESC",
            (status.value,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_due_scheduled_posts() -> list[dict]:
    """Fetch scheduled posts whose scheduled_at is in the past (ready to publish)."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM posts WHERE status = ? AND scheduled_at <= ?",
            (PostStatus.SCHEDULED.value, now),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
