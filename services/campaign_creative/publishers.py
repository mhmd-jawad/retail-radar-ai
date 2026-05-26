"""
IE3 — Social Media Publishers.

Posts campaign packages to Facebook Pages and Instagram Business accounts.

Required environment variables (set in services/campaign_creative/.env):

    Facebook + Instagram (same Meta App):
        FB_PAGE_ACCESS_TOKEN  — long-lived Page access token
        FB_PAGE_ID            — numeric Facebook Page ID
        IG_USER_ID            — Instagram Business account user ID
                                (linked to the Facebook Page above)

    Optional:
        IMGBB_API_KEY         — imgbb.com key; enables public image hosting for
                                locally-generated Pillow images so IG can
                                fetch them. Get one free at https://imgbb.com/

How to get credentials:
    Facebook/Instagram:
        1. Create a Meta App at developers.facebook.com
        2. Add "Pages" and "Instagram Graph API" products
        3. Connect your Facebook Page and Instagram Business account
        4. Generate a long-lived Page Access Token via Graph API Explorer
        5. Find IG_USER_ID: GET /{page-id}?fields=instagram_business_account

NOTE: The image URL must be publicly accessible for Instagram.
      If using a Replicate-generated image, it's already public.
      For Pillow fallback images, set IMGBB_API_KEY for auto-upload.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("ie3_publishers")

_GRAPH_BASE = "https://graph.facebook.com/v20.0"


# ── Image URL validator ───────────────────────────────────────────────────────

async def _validate_image_url(url: str) -> None:
    """
    Validate that *url* is a publicly accessible direct image URL.

    Instagram's /media endpoint requires Meta's servers to download the image
    from this URL.  If the URL is local, a webpage, or unreachable the publish
    step fails with a cryptic "media could not be fetched" error.

    Raises ValueError with a clear message if validation fails.
    """
    if not url.startswith("https://"):
        raise ValueError(
            f"Image URL must start with https:// — got: {url!r}"
        )
    if any(h in url for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1")):
        raise ValueError(
            f"Image URL must be publicly accessible, not a local address: {url!r}"
        )
    # imgbb webpage URL — wrong field was used
    if url.startswith("https://ibb.co/"):
        raise ValueError(
            "Image URL points to an imgbb *webpage* — use the direct image URL "
            f"(https://i.ibb.co/...) instead: {url!r}"
        )
    # placehold.co placeholders can't be fetched by Meta
    if "placehold.co" in url or "placeholder" in url.lower():
        raise ValueError(
            f"Image URL is a placeholder and cannot be fetched by Meta: {url!r}"
        )
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.head(url)
    except Exception as exc:
        raise ValueError(
            f"Image URL is not reachable: {url!r} — {exc}"
        ) from exc
    if resp.status_code != 200:
        raise ValueError(
            f"Image URL returned HTTP {resp.status_code} (expected 200): {url!r}"
        )
    content_type = resp.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise ValueError(
            f"Image URL content-type is {content_type!r} — must be image/png or "
            f"image/jpeg. URL is likely a webpage, not a direct image: {url!r}"
        )


# ── Result model ──────────────────────────────────────────────────────────────

@dataclass
class PublishResult:
    platform: str
    success: bool
    post_id: str = ""
    post_url: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "platform":  self.platform,
            "success":   self.success,
            "post_id":   self.post_id,
            "post_url":  self.post_url,
            "error":     self.error,
        }


# ── Facebook ──────────────────────────────────────────────────────────────────

async def post_to_facebook(caption: str, image_url: str) -> PublishResult:
    """
    Post an image + caption to a Facebook Page.

    API: POST /{page-id}/photos
    Docs: https://developers.facebook.com/docs/graph-api/reference/page/photos/
    """
    token   = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    print(f"[DEBUG publishers] FB token first30={token[:30]!r} len={len(token)}", flush=True)
    logger.info("FB token in use (first30): %s | length: %d", token[:30], len(token))

    if not token or not page_id:
        return PublishResult(
            "facebook", False,
            error="FB_PAGE_ACCESS_TOKEN and FB_PAGE_ID must be set in .env",
        )

    try:
        await _validate_image_url(image_url)
    except ValueError as exc:
        return PublishResult("facebook", False, error=f"Invalid image URL: {exc}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_GRAPH_BASE}/{page_id}/photos",
                params={
                    "access_token": token,
                    "caption":      caption,
                    "url":          image_url,
                },
            )
            data = resp.json()
            if resp.status_code == 200 and "id" in data:
                pid = data["id"]
                return PublishResult(
                    "facebook", True,
                    post_id=pid,
                    post_url=f"https://www.facebook.com/{pid}",
                )
            logger.warning("Facebook API error: %s", data)
            return PublishResult("facebook", False, error=str(data))

    except Exception as exc:
        logger.warning("Facebook post exception: %s", exc)
        return PublishResult("facebook", False, error=str(exc))


# ── Instagram ─────────────────────────────────────────────────────────────────

async def post_to_instagram(caption: str, image_url: str) -> PublishResult:
    """
    Post an image to an Instagram Business account via Meta Graph API.

    Two-step flow:
        1. Create a media container  → returns creation_id
        2. Publish the container     → returns post_id

    Docs: https://developers.facebook.com/docs/instagram-api/reference/ig-user/media
    NOTE: image_url must be a publicly reachable HTTPS URL.
    """
    # Instagram Business API requires the Page access token (not the IGAAN-prefixed token)
    token      = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    ig_user_id = os.getenv("IG_USER_ID", "").strip()

    if not token or not ig_user_id:
        return PublishResult(
            "instagram", False,
            error="FB_PAGE_ACCESS_TOKEN and IG_USER_ID must be set in .env",
        )

    try:
        await _validate_image_url(image_url)
    except ValueError as exc:
        return PublishResult("instagram", False, error=f"Invalid image URL: {exc}")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:

            # Step 1: create container
            r1 = await client.post(
                f"{_GRAPH_BASE}/{ig_user_id}/media",
                params={
                    "access_token": token,
                    "image_url":    image_url,
                    "caption":      caption,
                },
            )
            d1 = r1.json()
            if r1.status_code != 200 or "id" not in d1:
                logger.warning("Instagram container creation failed: %s", d1)
                return PublishResult("instagram", False, error=str(d1))

            creation_id = d1["id"]

            # Step 2: poll until container is ready (status=FINISHED), then publish
            for attempt in range(6):
                await asyncio.sleep(5)
                status_resp = await client.get(
                    f"{_GRAPH_BASE}/{creation_id}",
                    params={"access_token": token, "fields": "status_code"},
                )
                status_data = status_resp.json()
                status_code = status_data.get("status_code", "")
                logger.info("IG container %s status: %s (attempt %d)", creation_id, status_code, attempt + 1)
                if status_code == "ERROR":
                    return PublishResult("instagram", False, error=f"Container error: {status_data}")
                if status_code == "FINISHED":
                    break
            else:
                logger.warning("IG container not ready after 30s, attempting publish anyway")

            # Step 3: publish
            r2 = await client.post(
                f"{_GRAPH_BASE}/{ig_user_id}/media_publish",
                params={
                    "access_token": token,
                    "creation_id":  creation_id,
                },
            )
            d2 = r2.json()
            if r2.status_code == 200 and "id" in d2:
                pid = d2["id"]
                return PublishResult(
                    "instagram", True,
                    post_id=pid,
                    post_url=f"https://www.instagram.com/p/{pid}/",
                )
            logger.warning("Instagram publish failed: %s", d2)
            return PublishResult("instagram", False, error=str(d2))

    except Exception as exc:
        logger.warning("Instagram post exception: %s", exc)
        return PublishResult("instagram", False, error=str(exc))


# ── Orchestrator ──────────────────────────────────────────────────────────────

async def publish_to_all_platforms(
    instagram_caption: str,
    facebook_post: str,
    image_url: str,
) -> list[dict]:
    """
    Fire Facebook and Instagram publishers in parallel.
    Never raises — every error is captured inside the result dict.
    Returns a list of 2 dicts (one per platform).
    """
    results = await asyncio.gather(
        post_to_facebook(facebook_post, image_url),
        post_to_instagram(instagram_caption, image_url),
        return_exceptions=True,
    )

    output: list[dict] = []
    platforms = ["facebook", "instagram"]
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            output.append(PublishResult(platforms[i], False, error=str(r)).to_dict())
        else:
            output.append(r.to_dict())

    return output
