"""
bakery-social-engine — Meta Graph API Instagram publisher.

Handles:
- Uploading media to Cloudinary for public URL
- Creating Instagram media containers (Reels / Feed)
- Publishing containers to the Instagram Business account
- Status polling for async uploads
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import cloudinary
import cloudinary.uploader
import httpx

from src.config import get_settings
from src.db import PostType

logger = logging.getLogger(__name__)

# ── Meta Graph API base ─────────────────────────────────────────────────────
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


def _configure_cloudinary() -> None:
    """Configure cloudinary SDK from settings."""
    settings = get_settings()
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


async def upload_to_cloudinary(
    file_path: Path,
    resource_type: str = "auto",
) -> str:
    """
    Upload a file to Cloudinary and return its public URL.

    The Meta Graph API requires media to be at a publicly accessible URL,
    so we use Cloudinary as a temporary hosting layer.

    Args:
        file_path: Local path to the media file.
        resource_type: "image", "video", or "auto".

    Returns:
        Public URL of the uploaded file.
    """
    _configure_cloudinary()

    logger.info("Uploading to Cloudinary: %s", file_path.name)

    # Run the blocking upload in a thread pool
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: cloudinary.uploader.upload(
            str(file_path),
            resource_type=resource_type,
            folder="bakery-social-engine",
            overwrite=True,
            unique_filename=True,
        ),
    )

    public_url = result["secure_url"]
    logger.info("Cloudinary upload complete: %s", public_url)
    return public_url


async def create_ig_container(
    media_url: str,
    caption: str,
    post_type: PostType = PostType.FEED,
) -> str:
    """
    Create an Instagram media container via the Meta Graph API.

    Args:
        media_url: Public URL of the media (from Cloudinary).
        caption: Instagram caption text.
        post_type: FEED, REEL, or STORY.

    Returns:
        Container creation ID.
    """
    settings = get_settings()
    account_id = settings.instagram_business_account_id
    access_token = settings.meta_access_token

    if not account_id or not access_token:
        raise ValueError(
            "META_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID must be set in .env"
        )

    url = f"{GRAPH_API_BASE}/{account_id}/media"

    params = {
        "caption": caption,
        "access_token": access_token,
    }

    if post_type == PostType.REEL:
        params["media_type"] = "REELS"
        params["video_url"] = media_url
    elif post_type == PostType.STORY:
        # Stories use image_url or video_url based on content
        if media_url.endswith((".mp4", ".mov")):
            params["media_type"] = "STORIES"
            params["video_url"] = media_url
        else:
            params["media_type"] = "STORIES"
            params["image_url"] = media_url
    else:
        # Feed post (image)
        params["image_url"] = media_url

    logger.info("Creating IG container (type=%s)...", post_type.value)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, params=params)
        response.raise_for_status()
        data = response.json()

    container_id = data["id"]
    logger.info("Container created: %s", container_id)
    return container_id


async def check_container_status(container_id: str) -> dict:
    """
    Check the status of an Instagram media container.
    For video/reels, Meta processes them asynchronously.

    Returns:
        Dict with 'status_code' (e.g., 'FINISHED', 'IN_PROGRESS', 'ERROR')
        and optionally 'status' with error details.
    """
    settings = get_settings()
    access_token = settings.meta_access_token

    url = f"{GRAPH_API_BASE}/{container_id}"
    params = {
        "fields": "status_code,status",
        "access_token": access_token,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


async def publish_container(container_id: str) -> str:
    """
    Publish a finished media container to Instagram.

    Args:
        container_id: The container ID from create_ig_container.

    Returns:
        The published Instagram media ID.
    """
    settings = get_settings()
    account_id = settings.instagram_business_account_id
    access_token = settings.meta_access_token

    url = f"{GRAPH_API_BASE}/{account_id}/media_publish"
    params = {
        "creation_id": container_id,
        "access_token": access_token,
    }

    logger.info("Publishing container %s to Instagram...", container_id)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, params=params)
        response.raise_for_status()
        data = response.json()

    media_id = data["id"]
    logger.info("Published to Instagram! Media ID: %s", media_id)
    return media_id


async def publish_media(
    file_path: Path,
    caption: str,
    post_type: PostType = PostType.FEED,
    max_poll_attempts: int = 30,
    poll_interval: float = 5.0,
) -> dict:
    """
    Full publish pipeline:
    1. Upload to Cloudinary
    2. Create IG container
    3. Poll until ready (for videos/reels)
    4. Publish

    Args:
        file_path: Local path to the final processed media.
        caption: Instagram caption.
        post_type: FEED, REEL, or STORY.
        max_poll_attempts: Max times to check container status.
        poll_interval: Seconds between status checks.

    Returns:
        Dict with cloudinary_url, container_id, and media_id.
    """
    # Step 1: Upload to Cloudinary
    resource_type = "video" if post_type == PostType.REEL else "image"
    cloudinary_url = await upload_to_cloudinary(file_path, resource_type=resource_type)

    # Step 2: Create container
    container_id = await create_ig_container(cloudinary_url, caption, post_type)

    # Step 3: Poll for readiness (especially for videos)
    if post_type == PostType.REEL:
        logger.info("Polling container status (video processing)...")
        for attempt in range(max_poll_attempts):
            await asyncio.sleep(poll_interval)
            status = await check_container_status(container_id)
            status_code = status.get("status_code", "UNKNOWN")

            logger.info(
                "Container %s status: %s (attempt %d/%d)",
                container_id, status_code, attempt + 1, max_poll_attempts,
            )

            if status_code == "FINISHED":
                break
            elif status_code == "ERROR":
                error_msg = status.get("status", {})
                raise RuntimeError(f"Instagram container processing failed: {error_msg}")
        else:
            raise TimeoutError(
                f"Container {container_id} did not finish processing after "
                f"{max_poll_attempts * poll_interval}s"
            )

    # Step 4: Publish
    media_id = await publish_container(container_id)

    return {
        "cloudinary_url": cloudinary_url,
        "container_id": container_id,
        "media_id": media_id,
    }
