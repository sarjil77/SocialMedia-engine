"""
bakery-social-engine — Text-to-Speech wrapper.

Currently supports edge-tts (free, no API key).
Designed to be swappable with ElevenLabs / Sarvam AI stubs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import edge_tts

from src.config import get_settings

logger = logging.getLogger(__name__)


async def generate_voiceover(
    text: str,
    output_path: Path,
    voice: str | None = None,
) -> Path:
    """
    Generate a TTS audio file from the given text.

    Args:
        text: The voiceover script to synthesize.
        output_path: Where to save the .mp3 file.
        voice: Override voice identifier. Defaults to config.

    Returns:
        Path to the generated audio file.
    """
    settings = get_settings()

    if not settings.enable_voiceover:
        logger.info("Voiceover disabled in config, skipping TTS")
        return None

    provider = settings.tts_provider.lower()

    if provider == "edge-tts":
        return await _generate_edge_tts(text, output_path, voice)
    elif provider == "elevenlabs":
        return await _generate_elevenlabs_stub(text, output_path, voice)
    elif provider == "sarvam":
        return await _generate_sarvam_stub(text, output_path, voice)
    else:
        raise ValueError(f"Unknown TTS provider: {provider}")


async def _generate_edge_tts(
    text: str,
    output_path: Path,
    voice: str | None = None,
) -> Path:
    """Generate audio using Microsoft Edge TTS (free, neural voices)."""
    settings = get_settings()
    voice = voice or settings.edge_tts_voice

    logger.info("Generating TTS via edge-tts (voice=%s, %d chars)", voice, len(text))

    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(str(output_path))

    logger.info("TTS audio saved: %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1024)
    return output_path


async def _generate_elevenlabs_stub(
    text: str,
    output_path: Path,
    voice: str | None = None,
) -> Path:
    """
    Stub for ElevenLabs API integration.
    TODO: Implement with httpx + ElevenLabs REST API.
    """
    logger.warning("ElevenLabs TTS is not yet implemented — falling back to edge-tts")
    return await _generate_edge_tts(text, output_path, voice)


async def _generate_sarvam_stub(
    text: str,
    output_path: Path,
    voice: str | None = None,
) -> Path:
    """
    Stub for Sarvam AI TTS integration.
    TODO: Implement with Sarvam API client.
    """
    logger.warning("Sarvam AI TTS is not yet implemented — falling back to edge-tts")
    return await _generate_edge_tts(text, output_path, voice)


# ── Utility: List available edge-tts voices ──────────────────────────────────

async def list_edge_voices(language_filter: str = "gu") -> list[dict]:
    """List available edge-tts voices, optionally filtered by language code."""
    voices = await edge_tts.list_voices()
    if language_filter:
        voices = [v for v in voices if v["Locale"].startswith(language_filter)]
    return voices
