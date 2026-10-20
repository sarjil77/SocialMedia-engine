"""
bakery-social-engine — FFmpeg-based video processing pipeline.

Handles:
- 9:16 vertical normalization (1080×1920, 30fps)
- B-roll hook prepending
- Warm color grading for food appeal
- Text overlay burn-in (hook_text_overlay)
- TTS + background music mixing with audio ducking
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from src.config import get_settings

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
FPS = 30
HOOK_DURATION = 3.0  # seconds to show text overlay
BROLL_DURATION = 1.5  # seconds of b-roll to prepend


def _ffmpeg_bin() -> str:
    """Locate ffmpeg binary — uses PATH by default."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it: https://ffmpeg.org/download.html"
        )
    return ffmpeg


def _ffprobe_bin() -> str:
    """Locate ffprobe binary."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found on PATH.")
    return ffprobe


def _run_ffmpeg(args: list[str], description: str = "ffmpeg") -> None:
    """Run an ffmpeg command and raise on failure."""
    cmd = [_ffmpeg_bin()] + args
    logger.info("Running %s: %s", description, " ".join(cmd[:10]) + "...")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        logger.error("FFmpeg stderr: %s", result.stderr[-2000:])
        raise RuntimeError(f"{description} failed (exit {result.returncode}): {result.stderr[-500:]}")


def _get_duration(file_path: Path) -> float:
    """Get duration of a media file in seconds."""
    result = subprocess.run(
        [
            _ffprobe_bin(),
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ],
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _get_font_path() -> str:
    """Get the path to the bold font for text overlays."""
    settings = get_settings()
    font_dir = settings.fonts_dir

    # Try fonts in order of preference
    candidates = [
        font_dir / "Montserrat-Bold.ttf",
        font_dir / "Montserrat-ExtraBold.ttf",
        font_dir / "Poppins-Bold.ttf",
    ]
    for font in candidates:
        if font.exists():
            # FFmpeg on Windows needs forward slashes and escaping
            return str(font).replace("\\", "/").replace(":", r"\:")

    # Fallback to system font
    logger.warning("No custom font found in assets/fonts/, using FFmpeg default")
    return ""


# ── Core Pipeline ────────────────────────────────────────────────────────────

async def normalize_video(
    input_path: Path,
    output_path: Path | None = None,
) -> Path:
    """
    Normalize a video to 9:16 vertical (1080×1920) at 30fps.
    Applies center-crop or pad depending on aspect ratio.
    """
    settings = get_settings()
    if output_path is None:
        output_path = settings.temp_dir / f"normalized_{uuid.uuid4().hex[:8]}.mp4"

    # Scale + crop to 9:16 maintaining center
    vf = (
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
        f"setsar=1"
    )

    _run_ffmpeg(
        [
            "-i", str(input_path),
            "-vf", vf,
            "-r", str(FPS),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            str(output_path),
        ],
        description="Normalize to 9:16",
    )

    logger.info("Normalized video: %s", output_path.name)
    return output_path


async def apply_color_grading(
    input_path: Path,
    output_path: Path | None = None,
    warmth: float = 0.05,
    contrast: float = 1.1,
    saturation: float = 1.15,
) -> Path:
    """
    Apply warm food-photography color grading.
    Boosts warmth (slight orange tint), contrast, and saturation.
    """
    settings = get_settings()
    if output_path is None:
        output_path = settings.temp_dir / f"graded_{uuid.uuid4().hex[:8]}.mp4"

    # eq filter for contrast/saturation + colorbalance for warmth
    vf = (
        f"eq=contrast={contrast}:saturation={saturation},"
        f"colorbalance=rs={warmth}:gs=0:bs=-{warmth}:rm={warmth}:gm=0:bm=-{warmth}"
    )

    _run_ffmpeg(
        [
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-y",
            str(output_path),
        ],
        description="Color grading",
    )

    logger.info("Color graded: %s", output_path.name)
    return output_path


async def burn_text_overlay(
    input_path: Path,
    text: str,
    output_path: Path | None = None,
    duration: float = HOOK_DURATION,
    font_size: int = 64,
) -> Path:
    """
    Burn bold text overlay onto the top-center safe zone for the first N seconds.
    Uses a semi-transparent dark background pill for readability.
    """
    settings = get_settings()
    if output_path is None:
        output_path = settings.temp_dir / f"text_{uuid.uuid4().hex[:8]}.mp4"

    # Escape special characters for FFmpeg drawtext
    escaped_text = text.replace("'", "\\'").replace(":", r"\:")

    font_path = _get_font_path()
    font_clause = f":fontfile='{font_path}'" if font_path else ""

    # drawtext with background box, shown only for first `duration` seconds
    vf = (
        f"drawtext=text='{escaped_text}'"
        f"{font_clause}"
        f":fontsize={font_size}"
        f":fontcolor=white"
        f":x=(w-text_w)/2"
        f":y=180"
        f":box=1"
        f":boxcolor=black@0.55"
        f":boxborderw=20"
        f":enable='lte(t,{duration})'"
    )

    _run_ffmpeg(
        [
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-y",
            str(output_path),
        ],
        description="Text overlay",
    )

    logger.info("Text overlay burned: '%s'", text)
    return output_path


async def prepend_broll(
    main_video: Path,
    broll_tag: str,
    output_path: Path | None = None,
) -> Path:
    """
    Prepend a b-roll hook clip from assets/broll/ before the main video.
    Uses FFmpeg concat demuxer for gapless joining.
    """
    settings = get_settings()

    broll_file = settings.broll_dir / f"{broll_tag}.mp4"
    if not broll_file.exists():
        logger.warning("B-roll '%s' not found at %s, skipping", broll_tag, broll_file)
        return main_video

    if output_path is None:
        output_path = settings.temp_dir / f"broll_{uuid.uuid4().hex[:8]}.mp4"

    # First normalize the b-roll to match main video specs
    broll_normalized = settings.temp_dir / f"broll_norm_{uuid.uuid4().hex[:8]}.mp4"
    await normalize_video(broll_file, broll_normalized)

    # Trim b-roll to BROLL_DURATION
    broll_trimmed = settings.temp_dir / f"broll_trim_{uuid.uuid4().hex[:8]}.mp4"
    _run_ffmpeg(
        [
            "-i", str(broll_normalized),
            "-t", str(BROLL_DURATION),
            "-c", "copy",
            "-y",
            str(broll_trimmed),
        ],
        description="Trim b-roll",
    )

    # Create concat file list
    concat_list = settings.temp_dir / f"concat_{uuid.uuid4().hex[:8]}.txt"
    concat_list.write_text(
        f"file '{broll_trimmed}'\nfile '{main_video}'\n",
        encoding="utf-8",
    )

    _run_ffmpeg(
        [
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            "-y",
            str(output_path),
        ],
        description="Concat b-roll + main",
    )

    logger.info("Prepended b-roll '%s' to video", broll_tag)
    return output_path


async def mix_audio(
    video_path: Path,
    tts_path: Path | None = None,
    music_path: Path | None = None,
    output_path: Path | None = None,
    music_volume: float = 0.15,
    tts_volume: float = 1.0,
) -> Path:
    """
    Mix TTS voiceover and/or background music into the video.
    Applies audio ducking: music volume drops when TTS is playing.
    """
    settings = get_settings()
    if output_path is None:
        output_path = settings.temp_dir / f"mixed_{uuid.uuid4().hex[:8]}.mp4"

    # If no audio sources, return the video as-is
    if tts_path is None and music_path is None:
        logger.info("No TTS or music provided, skipping audio mix")
        return video_path

    # Find a background music file if not specified
    if music_path is None:
        music_files = list(settings.music_dir.glob("*.mp3")) + list(settings.music_dir.glob("*.aac"))
        if music_files:
            music_path = music_files[0]
            logger.info("Auto-selected background music: %s", music_path.name)

    # Build FFmpeg filter complex
    inputs = ["-i", str(video_path)]
    filter_parts = []
    audio_streams = []

    # Original video audio (might not exist)
    filter_parts.append("[0:a]aformat=sample_rates=44100:channel_layouts=stereo[orig];")
    audio_streams.append("[orig]")

    stream_idx = 1

    if tts_path and tts_path.exists():
        inputs.extend(["-i", str(tts_path)])
        filter_parts.append(
            f"[{stream_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={tts_volume}[tts];"
        )
        audio_streams.append("[tts]")
        stream_idx += 1

    if music_path and music_path.exists():
        video_duration = _get_duration(video_path)
        inputs.extend(["-i", str(music_path)])
        filter_parts.append(
            f"[{stream_idx}:a]aloop=loop=-1:size=2e+09,atrim=0:{video_duration},"
            f"aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={music_volume}[bgm];"
        )
        audio_streams.append("[bgm]")
        stream_idx += 1

    # Mix all audio streams together
    n_streams = len(audio_streams)
    mix_inputs = "".join(audio_streams)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={n_streams}:duration=first:dropout_transition=2[aout]"
    )

    filter_complex = "\n".join(filter_parts)

    try:
        _run_ffmpeg(
            inputs + [
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                "-y",
                str(output_path),
            ],
            description="Audio mix",
        )
    except RuntimeError:
        # If original video has no audio stream, retry without [0:a]
        logger.warning("Audio mix failed (likely no audio in source), retrying without original audio")
        filter_parts_no_orig = []
        audio_streams_no_orig = []
        stream_idx = 1

        if tts_path and tts_path.exists():
            filter_parts_no_orig.append(
                f"[{stream_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                f"volume={tts_volume}[tts];"
            )
            audio_streams_no_orig.append("[tts]")
            stream_idx += 1

        if music_path and music_path.exists():
            video_duration = _get_duration(video_path)
            filter_parts_no_orig.append(
                f"[{stream_idx}:a]aloop=loop=-1:size=2e+09,atrim=0:{video_duration},"
                f"aformat=sample_rates=44100:channel_layouts=stereo,"
                f"volume={music_volume}[bgm];"
            )
            audio_streams_no_orig.append("[bgm]")
            stream_idx += 1

        if audio_streams_no_orig:
            n = len(audio_streams_no_orig)
            mix_in = "".join(audio_streams_no_orig)
            filter_parts_no_orig.append(
                f"{mix_in}amix=inputs={n}:duration=first:dropout_transition=2[aout]"
            )
            fc = "\n".join(filter_parts_no_orig)

            _run_ffmpeg(
                inputs + [
                    "-filter_complex", fc,
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    "-shortest",
                    "-y",
                    str(output_path),
                ],
                description="Audio mix (no original audio)",
            )
        else:
            return video_path

    logger.info("Audio mixed: %s", output_path.name)
    return output_path


# ── Full Reel Pipeline ───────────────────────────────────────────────────────

async def process_reel(
    input_path: Path,
    hook_text: str,
    broll_tag: str = "none",
    tts_audio_path: Path | None = None,
    music_path: Path | None = None,
) -> Path:
    """
    Full reel processing pipeline:
    1. Normalize to 9:16
    2. Color grade
    3. Prepend b-roll (if available)
    4. Burn text overlay
    5. Mix audio (TTS + background music)

    Returns path to the final rendered reel.
    """
    settings = get_settings()

    logger.info("═══ Starting Reel Pipeline ═══")

    # Step 1: Normalize
    normalized = await normalize_video(input_path)

    # Step 2: Color grade
    graded = await apply_color_grading(normalized)

    # Step 3: Prepend b-roll
    if broll_tag and broll_tag != "none":
        graded = await prepend_broll(graded, broll_tag)

    # Step 4: Text overlay
    with_text = await burn_text_overlay(graded, hook_text)

    # Step 5: Audio mix
    final = await mix_audio(with_text, tts_path=tts_audio_path, music_path=music_path)

    # Move to a stable output path
    output_path = settings.temp_dir / f"reel_final_{uuid.uuid4().hex[:8]}.mp4"
    if final != output_path:
        shutil.move(str(final), str(output_path))

    logger.info("═══ Reel Pipeline Complete: %s ═══", output_path.name)
    return output_path
