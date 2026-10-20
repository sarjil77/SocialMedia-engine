"""
bakery-social-engine — Gemini 2.5 Flash multimodal analyzer.

Accepts raw bakery photos/videos + optional text context and returns
a structured JSON analysis for content generation.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from src.ai.prompts import BAKERY_ANALYZER_SYSTEM_PROMPT, BAKERY_ANALYZER_USER_TEMPLATE
from src.config import get_settings

logger = logging.getLogger(__name__)


# ── Pydantic schema for structured output ────────────────────────────────────

class BakeryAnalysis(BaseModel):
    """Strict schema returned by Gemini for every media analysis."""

    category: str = Field(
        ...,
        description="One of: DAILY_SNACK, CUSTOM_CAKE, FESTIVAL_SPECIAL",
    )
    hook_text_overlay: str = Field(
        ...,
        description="3-6 word punchy hook for text overlay",
    )
    voiceover_script: str = Field(
        ...,
        description="10-second conversational voiceover script",
    )
    instagram_caption: str = Field(
        ...,
        description="Engaging Instagram caption with CTA and hashtags",
    )
    recommended_broll_tag: str = Field(
        ...,
        description="B-roll tag from predefined set or 'none'",
    )


def _get_client() -> genai.Client:
    """Create a Gemini client using the configured API key."""
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def _load_media_part(file_path: Path) -> types.Part:
    """Load a local file as a Gemini Part with proper MIME type."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type is None:
        # Fallback based on extension
        ext = file_path.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

    data = file_path.read_bytes()
    return types.Part.from_bytes(data=data, mime_type=mime_type)


async def analyze_media(
    media_paths: list[Path],
    context_text: Optional[str] = None,
) -> BakeryAnalysis:
    """
    Send media files + optional context to Gemini 2.5 Flash and get
    structured BakeryAnalysis back.

    Args:
        media_paths: List of local file paths (photos or videos).
        context_text: Optional caption or transcribed voice note text.

    Returns:
        BakeryAnalysis with all fields populated by the AI.
    """
    settings = get_settings()
    client = _get_client()

    # Build the user prompt with context
    context_note = ""
    if context_text:
        context_note = f"Staff note / voice caption: \"{context_text}\""
    else:
        context_note = "No additional context was provided by the staff."

    user_prompt = BAKERY_ANALYZER_USER_TEMPLATE.format(context_note=context_note)

    # Build content parts: media files + text prompt
    parts: list[types.Part] = []
    for path in media_paths:
        p = Path(path)
        if p.exists():
            parts.append(_load_media_part(p))
            logger.info("Loaded media: %s (%s)", p.name, p.suffix)
        else:
            logger.warning("Media file not found, skipping: %s", p)

    parts.append(types.Part.from_text(text=user_prompt))

    logger.info(
        "Sending %d media file(s) to %s for analysis...",
        len(parts) - 1,  # subtract the text part
        settings.gemini_model,
    )

    # Call Gemini with structured JSON output
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(
            system_instruction=BAKERY_ANALYZER_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=BakeryAnalysis,
            temperature=0.8,
            max_output_tokens=1024,
        ),
    )

    # Parse the response
    raw_text = response.text.strip()
    logger.debug("Gemini raw response: %s", raw_text[:500])

    try:
        data = json.loads(raw_text)
        analysis = BakeryAnalysis(**data)
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Failed to parse Gemini response: %s\nRaw: %s", e, raw_text)
        raise ValueError(f"Gemini returned invalid JSON: {e}") from e

    logger.info(
        "Analysis complete — category=%s, hook='%s', broll=%s",
        analysis.category,
        analysis.hook_text_overlay,
        analysis.recommended_broll_tag,
    )
    return analysis
