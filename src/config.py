"""
bakery-social-engine — Configuration via Pydantic Settings.

All secrets and tunables are loaded from .env / environment variables.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
DATA_DIR = PROJECT_ROOT / "data"
TEMP_DIR = DATA_DIR / "tmp"

# Ensure runtime directories exist
DATA_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    """Central configuration loaded from .env file at project root."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Telegram ─────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(..., description="Telegram Bot API token")
    telegram_admin_chat_id: int = Field(..., description="Chat ID of admin for approvals")

    # ── Google Gemini ────────────────────────────────────────────────────
    gemini_api_key: str = Field(..., description="Google AI Gemini API key")
    gemini_model: str = Field("gemini-3.5-flash-lite", description="Gemini model name")

    # ── Meta / Instagram ─────────────────────────────────────────────────
    meta_access_token: str = Field("", description="Meta Graph API long-lived token")
    instagram_business_account_id: str = Field("", description="Instagram Business Account ID")

    # ── Cloudinary ───────────────────────────────────────────────────────
    cloudinary_cloud_name: str = Field("", description="Cloudinary cloud name")
    cloudinary_api_key: str = Field("", description="Cloudinary API key")
    cloudinary_api_secret: str = Field("", description="Cloudinary API secret")

    # ── TTS ───────────────────────────────────────────────────────────────
    tts_provider: str = Field("edge-tts", description="TTS provider: edge-tts | elevenlabs | sarvam")
    edge_tts_voice: str = Field("gu-IN-DhwaniNeural", description="Edge TTS voice identifier")
    enable_voiceover: bool = Field(True, description="Enable/disable TTS voiceover on reels")

    # ── App ───────────────────────────────────────────────────────────────
    database_url: str = Field(
        f"sqlite+aiosqlite:///{DATA_DIR / 'bakery.db'}",
        description="SQLite database URL",
    )
    log_level: str = Field("INFO", description="Logging level")
    default_schedule_hour: int = Field(18, description="Default scheduled post hour (24h)")
    default_schedule_minute: int = Field(0, description="Default scheduled post minute")

    # ── Asset paths (derived) ────────────────────────────────────────────
    @property
    def backgrounds_dir(self) -> Path:
        return ASSETS_DIR / "backgrounds"

    @property
    def broll_dir(self) -> Path:
        return ASSETS_DIR / "broll"

    @property
    def fonts_dir(self) -> Path:
        return ASSETS_DIR / "fonts"

    @property
    def music_dir(self) -> Path:
        return ASSETS_DIR / "music"

    @property
    def overlays_dir(self) -> Path:
        return ASSETS_DIR / "overlays"

    @property
    def temp_dir(self) -> Path:
        return TEMP_DIR


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton — call this everywhere instead of constructing Settings()."""
    return Settings()
