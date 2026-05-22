"""
IE3 — Campaign Creative Service.
Owner: Mohammad Farhat.

Receives a PROMOTE RecommendationResult from IE2 and generates a full campaign package:
  - Text copy (Instagram, Facebook, TikTok, headline, ad copy) via OpenRouter (Claude)
  - Image generation prompt via OpenRouter (Claude)
  - Product image via Replicate (Stable Diffusion)
  - Writes one campaign row per channel to marketing.campaigns

Port: 8003
Run:
    uvicorn services.campaign_creative.main:app --port 8003 --reload

Environment variables required:
    OPENROUTER_API_KEY   — OpenRouter API key
    REPLICATE_API_KEY    — Replicate API key
    DATABASE_URL         — PostgreSQL connection string (default: local)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from services.decision_intelligence.schemas import RecommendationResult

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ie3_campaign_creative")

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/retail_radar"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_STORE_CODE = "MAIN"
FALLBACK_IMAGE_URL = "https://placehold.co/1024x1024/FF6B35/FFFFFF?text=Sale+Now"

_REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY") or os.getenv("REPLICATE_API_TOKEN", "")
_REPLICATE_MODEL_VERSION = "db21e45d3f7023abc2a46ee38a23973f6dce16bb082a930b0c49861f96d1e5bf"

_OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
if not _OPENROUTER_API_KEY:
    logging.getLogger("ie3_campaign_creative").warning(
        "OPENROUTER_API_KEY is not set — all LLM calls will fail with 401"
    )

_openrouter_client = AsyncOpenAI(
    api_key=_OPENROUTER_API_KEY or "not-set",
    base_url="https://openrouter.ai/api/v1",
)

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="StylePulse AI — IE3 Campaign Creative",
    description="Campaign generation service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class PromotionBrief(BaseModel):
    """Internal brief assembled from product data + RecommendationResult."""
    recommendation_id: Optional[str] = None
    product_name: str
    brand: str
    category: str
    gender_target: Optional[str] = None
    season: Optional[str] = None
    color: Optional[str] = None
    retail_price_usd: float
    suggested_discount_pct: Optional[float] = None
    current_stock: int
    confidence: float
    urgency_level: Literal["high", "medium", "low"]
    upcoming_event: Optional[str] = None


class CampaignPackage(BaseModel):
    """Full campaign output returned to the caller and written to marketing.campaigns."""
    recommendation_id: Optional[str] = None
    instagram_caption: str = Field(max_length=300)
    facebook_post: str = Field(max_length=500)
    tiktok_caption: str = Field(max_length=150)
    headline: str = Field(max_length=60)
    ad_copy_short: str = Field(max_length=150)
    ad_copy_long: str = Field(max_length=400)
    cta_primary: str
    cta_secondary: str
    image_url: str
    image_prompt: str
    tone_used: Literal["urgent", "aspirational", "value_focused"]
    fallback_used: bool = False
    prompt_version: str = "v1.0"


# ── Database helpers (mirrored from eep/retail_db.py pattern) ─────────────────

def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def _import_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise RuntimeError(
            "PostgreSQL driver missing. Install psycopg[binary]."
        ) from exc
    return psycopg, dict_row


@contextmanager
def _connect():
    psycopg, dict_row = _import_psycopg()
    try:
        conn = psycopg.connect(_database_url(), row_factory=dict_row)
    except Exception as exc:
        raise RuntimeError(f"Cannot connect to PostgreSQL: {exc}") from exc
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_tenant_context(cur) -> dict[str, Any]:
    slug = os.environ.get("RETAIL_TENANT_SLUG", DEFAULT_TENANT_SLUG)
    store = os.environ.get("RETAIL_STORE_CODE", DEFAULT_STORE_CODE)
    cur.execute(
        """
        select t.id as tenant_id, s.id as store_id
        from core.tenants t
        join core.stores s on s.tenant_id = t.id
        where t.slug = %s and s.code = %s and s.is_active = true
        """,
        (slug, store),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Tenant/store not found: {slug}/{store}")
    return row


def _fetch_product_data_sync(sku_id: str) -> dict[str, Any] | None:
    """Fetch brand, category, pricing, stock, and variant info for a SKU."""
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _get_tenant_context(cur)
            cur.execute(
                """
                select
                    p.brand,
                    p.category,
                    p.gender_target,
                    p.season,
                    v.id as variant_id,
                    v.color,
                    coalesce(b.quantity_on_hand, 0) as current_stock,
                    coalesce(pr.amount, 0.0)         as retail_price_usd
                from core.sku_variants v
                join core.products p on p.id = v.product_id
                left join core.inventory_balances b
                    on b.variant_id = v.id and b.store_id = %s
                left join lateral (
                    select amount
                    from core.prices
                    where variant_id = v.id
                      and price_type = 'retail'
                      and valid_to is null
                    order by valid_from desc
                    limit 1
                ) pr on true
                where v.tenant_id = %s and v.sku_id = %s
                """,
                (ctx["store_id"], ctx["tenant_id"], sku_id),
            )
            return cur.fetchone()


def _write_campaigns_sync(package: CampaignPackage, sku_id: str) -> None:
    """Write one marketing.campaigns row per channel (instagram, facebook, tiktok)."""
    body_map = {
        "instagram": package.instagram_caption,
        "facebook": package.facebook_post,
        "tiktok": package.tiktok_caption,
    }
    now = datetime.now(tz=timezone.utc)
    ends_at = now + timedelta(days=7)

    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _get_tenant_context(cur)

            # Resolve variant_id for FK reference
            cur.execute(
                "select id from core.sku_variants where tenant_id = %s and sku_id = %s",
                (ctx["tenant_id"], sku_id),
            )
            variant_row = cur.fetchone()
            variant_id = variant_row["id"] if variant_row else None

            for channel in ("instagram", "facebook", "tiktok"):
                # Store copy + image_url together as JSON body so no schema change needed
                body_json = json.dumps({
                    "copy": body_map[channel],
                    "image_url": package.image_url,
                    "image_prompt": package.image_prompt,
                    "cta_primary": package.cta_primary,
                    "cta_secondary": package.cta_secondary,
                })
                cur.execute(
                    """
                    insert into marketing.campaigns
                        (tenant_id, recommendation_id, variant_id, channel,
                         status, headline, body, starts_at, ends_at,
                         created_at, updated_at)
                    values (%s, %s, %s, %s, 'draft', %s, %s, %s, %s, now(), now())
                    """,
                    (
                        ctx["tenant_id"],
                        package.recommendation_id,
                        variant_id,
                        channel,
                        package.headline,
                        body_json,
                        now,
                        ends_at,
                    ),
                )


# ── Business Logic ────────────────────────────────────────────────────────────


def _derive_urgency(confidence: float, current_stock: int) -> Literal["high", "medium", "low"]:
    if current_stock < 20 or confidence > 0.85:
        return "high"
    if current_stock < 50 or confidence > 0.70:
        return "medium"
    return "low"


def _urgency_to_tone(urgency: str) -> Literal["urgent", "aspirational", "value_focused"]:
    return {"high": "urgent", "medium": "aspirational", "low": "value_focused"}[urgency]  # type: ignore[return-value]


def _build_fallback_copy(brief: PromotionBrief) -> dict[str, str]:
    disc = int(brief.suggested_discount_pct or 0)
    brand = brief.brand
    name = brief.product_name
    gender = brief.gender_target or "athletes"
    brand_tag = brand.replace(" ", "")
    return {
        "instagram_caption": (
            f"🔥 {name} by {brand} — {disc}% OFF today only. "
            f"Limited stock. Shop now! #SportsFashion #{brand_tag} #LimitedStock #SaleAlert"
        )[:300],
        "facebook_post": (
            f"Big news! {name} by {brand} is now {disc}% off. "
            f"Limited stock available. Don't miss out — shop now in store or online."
        )[:500],
        "tiktok_caption": (
            f"POV: {brand} just dropped {disc}% off {name} and stock is almost gone 👟🔥 "
            f"no cap #SportsFashion #{brand_tag}"
        )[:150],
        "headline": f"{disc}% OFF — {name} by {brand}"[:60],
        "ad_copy_short": f"Limited stock. {disc}% off {name}. Shop now."[:150],
        "ad_copy_long": (
            f"Don't miss your chance to own the {name} by {brand} at {disc}% off. "
            f"Designed for {gender}. Limited units available — grab yours before it's gone."
        )[:400],
        "cta_primary": "Shop Now",
        "cta_secondary": "View Details",
    }


def _truncate_copy_fields(copy: dict) -> dict:
    limits = {
        "instagram_caption": 300,
        "facebook_post": 500,
        "tiktok_caption": 150,
        "headline": 60,
        "ad_copy_short": 150,
        "ad_copy_long": 400,
    }
    result = dict(copy)
    for key, limit in limits.items():
        if key in result and isinstance(result[key], str):
            result[key] = result[key][:limit]
    return result


def _validate_copy_keys(copy: dict) -> bool:
    required = {
        "instagram_caption", "facebook_post", "tiktok_caption",
        "headline", "ad_copy_short", "ad_copy_long",
        "cta_primary", "cta_secondary",
    }
    return required.issubset(copy.keys()) and all(
        isinstance(copy[k], str) and copy[k].strip() for k in required
    )


# ── LLM Prompts ───────────────────────────────────────────────────────────────

_TEXT_SYSTEM_PROMPT = """\
You are a professional retail marketing copywriter for a sports fashion brand.

Generate copy ONLY based on the product info provided.
Do NOT invent features, specs, or prices not given to you.

Adapt tone based on urgency_level:
- high: scarcity language — "Only X left", "This week only", "Almost gone"
- medium: aspirational — "Made for your best performance", "Level up"
- low: value-focused — "Quality that lasts", "Worth every penny"

Platform rules:
- instagram_caption: max 300 chars, end with exactly 4 relevant hashtags
- facebook_post: max 500 chars, friendly and engaging
- tiktok_caption: max 150 chars, Gen-Z tone, trendy, use emojis, \
casual language like "no cap", "it's giving", "lowkey"
- headline: max 60 chars, punchy and bold
- ad_copy_short: max 150 chars, one strong sentence
- ad_copy_long: max 400 chars, benefit-driven, tell a story
- cta_primary: strong action, max 10 words
- cta_secondary: softer action, max 10 words

Return ONLY a JSON object with these exact keys:
instagram_caption, facebook_post, tiktok_caption,
headline, ad_copy_short, ad_copy_long,
cta_primary, cta_secondary

No markdown. No explanation. Raw JSON only."""

_TEXT_RETRY_SUFFIX = (
    "\n\nReturn ONLY valid JSON. No markdown. No extra text. "
    "Strictly follow character limits."
)

_IMAGE_SYSTEM_PROMPT = """\
You are a creative director for a sports fashion brand.
Generate a unique, vivid image generation prompt for a product ad.

Rules:
- Every prompt must be visually different — vary backgrounds, \
lighting, composition, color schemes
- Match the brand's vibe (Adidas=modern, Nike=bold, Puma=edgy)
- Match urgency: high=dramatic, medium=energetic, low=clean minimal
- Always include: product description, background style, \
lighting mood, color palette, any text overlays needed
- Make it suitable for social media ads
- Max 100 words

Return ONLY the image prompt text. Nothing else."""


def _text_user_message(brief: PromotionBrief) -> str:
    return (
        f"Product: {brief.product_name}\n"
        f"Brand: {brief.brand}\n"
        f"Category: {brief.category}\n"
        f"Target: {brief.gender_target or 'unisex'}\n"
        f"Season: {brief.season or 'all-season'}\n"
        f"Color: {brief.color or 'N/A'}\n"
        f"Price: ${brief.retail_price_usd:.2f}\n"
        f"Discount: {int(brief.suggested_discount_pct or 0)}%\n"
        f"Stock remaining: {brief.current_stock} units\n"
        f"Urgency: {brief.urgency_level}\n"
        f"Upcoming event: {brief.upcoming_event or 'none'}"
    )


def _image_user_message(brief: PromotionBrief) -> str:
    return (
        f"Product: {brief.product_name}\n"
        f"Brand: {brief.brand}\n"
        f"Color: {brief.color or 'N/A'}\n"
        f"Urgency: {brief.urgency_level}\n"
        f"Discount: {int(brief.suggested_discount_pct or 0)}%\n"
        f"Platform: Instagram and TikTok ad"
    )


# ── LLM Callers ───────────────────────────────────────────────────────────────


async def _call_openrouter_text(brief: PromotionBrief, retry: bool = False) -> dict[str, str]:
    system = _TEXT_SYSTEM_PROMPT + (_TEXT_RETRY_SUFFIX if retry else "")
    response = await asyncio.wait_for(
        _openrouter_client.chat.completions.create(
            model="anthropic/claude-3.5-sonnet",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _text_user_message(brief)},
            ],
            temperature=0.7,
            max_tokens=1200,
        ),
        timeout=8.0,
    )
    raw = (response.choices[0].message.content or "").strip()
    # Strip markdown code fences if the model wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    return json.loads(raw)


async def _call_openrouter_image_prompt(brief: PromotionBrief) -> str:
    response = await asyncio.wait_for(
        _openrouter_client.chat.completions.create(
            model="anthropic/claude-3.5-sonnet",
            messages=[
                {"role": "system", "content": _IMAGE_SYSTEM_PROMPT},
                {"role": "user", "content": _image_user_message(brief)},
            ],
            temperature=0.9,
            max_tokens=200,
        ),
        timeout=5.0,
    )
    return (response.choices[0].message.content or "").strip()


async def _generate_image(image_prompt: str) -> str:
    """Call Replicate REST API directly — avoids the replicate SDK's Pydantic v1 dependency."""
    if not _REPLICATE_API_KEY:
        raise RuntimeError("REPLICATE_API_KEY is not set")

    headers = {
        "Authorization": f"Token {_REPLICATE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "version": _REPLICATE_MODEL_VERSION,
        "input": {
            "prompt": image_prompt,
            "width": 1024,
            "height": 1024,
            "num_outputs": 1,
            "guidance_scale": 7.5,
            "num_inference_steps": 50,
        },
    }

    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.post(
            "https://api.replicate.com/v1/predictions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        prediction = resp.json()
        poll_url = prediction["urls"]["get"]

        deadline = asyncio.get_running_loop().time() + 60.0
        while True:
            await asyncio.sleep(1.5)
            poll = await client.get(poll_url, headers=headers)
            poll.raise_for_status()
            data = poll.json()
            state = data.get("status")
            if state == "succeeded":
                return data["output"][0]
            if state in ("failed", "canceled"):
                raise RuntimeError(f"Replicate prediction {state}: {data.get('error')}")
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("Replicate polling timed out")


# ── FastAPI Endpoints ─────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "healthy", "service": "ie3_campaign_creative"}


@app.post("/campaign/generate", response_model=CampaignPackage)
async def generate_campaign(recommendation: RecommendationResult):
    """
    Generate a full campaign package for a PROMOTE recommendation.

    Flow:
      1. Gate: only PROMOTE decisions proceed
      2. DB lookup: fetch brand, category, stock, price for the SKU
      3. In parallel: generate text copy + image prompt via OpenRouter (Claude)
      4. Generate product image via Replicate (Stable Diffusion)
      5. Assemble CampaignPackage
      6. Write one row per channel to marketing.campaigns
      7. Return CampaignPackage
    """

    # ── Step 0: gate ──────────────────────────────────────────────────────────
    if recommendation.recommendation != "PROMOTE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Campaign generation is only available for PROMOTE decisions. "
                f"Got: {recommendation.recommendation}"
            ),
        )

    # ── Step 1: product data from DB ──────────────────────────────────────────
    product_data: dict[str, Any] = {}
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_fetch_product_data_sync, recommendation.sku_id),
            timeout=3.0,
        )
        if result:
            product_data = dict(result)
    except Exception as exc:
        logger.warning(
            "DB lookup failed for sku_id=%s — continuing with defaults. Error: %s",
            recommendation.sku_id,
            exc,
        )

    brand = product_data.get("brand") or "Unknown"
    category = product_data.get("category") or "footwear"
    gender_target = product_data.get("gender_target")
    season = product_data.get("season")
    color = product_data.get("color")
    retail_price_usd = float(product_data.get("retail_price_usd") or 0.0)
    current_stock = int(product_data.get("current_stock") or 50)  # neutral default when DB unavailable

    urgency = _derive_urgency(recommendation.confidence, current_stock)

    brief = PromotionBrief(
        recommendation_id=None,  # TODO: populate once IE2 writes to marketing.recommendations first
        product_name=recommendation.product_name,
        brand=brand,
        category=category,
        gender_target=gender_target,
        season=season,
        color=color,
        retail_price_usd=retail_price_usd,
        suggested_discount_pct=recommendation.suggested_discount_pct,
        current_stock=current_stock,
        confidence=recommendation.confidence,
        urgency_level=urgency,
    )

    fallback_used = False

    # ── Steps 2 & 3 in parallel: text copy + image prompt ────────────────────

    async def _get_text_copy() -> tuple[dict[str, str], bool]:
        """Returns (copy_dict, used_fallback)."""
        try:
            raw = await _call_openrouter_text(brief)
            if not _validate_copy_keys(raw):
                raise ValueError("Response missing required copy keys")
            return _truncate_copy_fields(raw), False
        except Exception as exc:
            logger.warning(
                "Text copy attempt 1 failed for sku=%s: %s — retrying",
                recommendation.sku_id, exc,
            )
        try:
            raw = await _call_openrouter_text(brief, retry=True)
            if not _validate_copy_keys(raw):
                raise ValueError("Response missing required copy keys on retry")
            return _truncate_copy_fields(raw), False
        except Exception as exc:
            logger.warning(
                "Text copy retry failed for sku=%s: %s — using fallback templates",
                recommendation.sku_id, exc,
            )
            return _build_fallback_copy(brief), True

    async def _get_image_prompt() -> str:
        try:
            return await _call_openrouter_image_prompt(brief)
        except Exception as exc:
            logger.warning(
                "Image prompt generation failed for sku=%s: %s — using fallback prompt",
                recommendation.sku_id, exc,
            )
            disc = int(brief.suggested_discount_pct or 0)
            return f"{brand} {brief.product_name} sports ad, {disc}% off sale"

    (text_copy, copy_fallback), image_prompt = await asyncio.gather(
        _get_text_copy(),
        _get_image_prompt(),
    )
    if copy_fallback:
        fallback_used = True

    # ── Step 4: generate image via Replicate ──────────────────────────────────
    image_url = FALLBACK_IMAGE_URL
    try:
        image_url = await _generate_image(image_prompt)
    except Exception as exc:
        logger.warning(
            "Replicate image generation failed for sku=%s: %s — using fallback image",
            recommendation.sku_id, exc,
        )
        fallback_used = True

    # ── Step 5: assemble CampaignPackage ─────────────────────────────────────
    package = CampaignPackage(
        recommendation_id=brief.recommendation_id,
        instagram_caption=text_copy["instagram_caption"],
        facebook_post=text_copy["facebook_post"],
        tiktok_caption=text_copy["tiktok_caption"],
        headline=text_copy["headline"],
        ad_copy_short=text_copy["ad_copy_short"],
        ad_copy_long=text_copy["ad_copy_long"],
        cta_primary=text_copy["cta_primary"],
        cta_secondary=text_copy["cta_secondary"],
        image_url=image_url,
        image_prompt=image_prompt,
        tone_used=_urgency_to_tone(urgency),
        fallback_used=fallback_used,
        prompt_version="v1.0",
    )

    # ── Step 6: write to DB (non-blocking — errors are logged, not raised) ────
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_write_campaigns_sync, package, recommendation.sku_id),
            timeout=3.0,
        )
        logger.info(
            "Campaigns written to DB for sku=%s channels=instagram,facebook,tiktok",
            recommendation.sku_id,
        )
    except Exception as exc:
        logger.error(
            "DB write failed for sku=%s: %s — package still returned to caller",
            recommendation.sku_id, exc,
        )

    return package
