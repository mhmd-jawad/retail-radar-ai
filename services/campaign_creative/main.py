"""
IE3 — Campaign Creative Service.
Owner: Mohammad Farhat.

Receives a PROMOTE RecommendationResult from IE2 and generates a full campaign package:
  - Text copy (Instagram, Facebook, TikTok, headline, ad copy) via Anthropic Claude (direct API)
  - Image generation prompt via Anthropic Claude (direct API)
  - Product image via OpenAI gpt-image-1 → Replicate → Pillow (fallback chain)
  - Writes one campaign row per channel to marketing.campaigns

Port: 8003
Run:
    uvicorn services.campaign_creative.main:app --port 8003 --reload

Environment variables required:
    ANTHROPIC_API_KEY    — Anthropic API key (text copy + image prompt via Claude)
    OPENAI_API_KEY       — OpenAI API key (DALL-E 3 image generation)
    REPLICATE_API_KEY    — Replicate API key (Stable Diffusion fallback)
    DATABASE_URL         — PostgreSQL connection string (default: local)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import anthropic
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from services.decision_intelligence.schemas import RecommendationResult

# ── Load .env from the service directory ─────────────────────────────────────
_SERVICE_DIR = Path(__file__).parent
load_dotenv(_SERVICE_DIR / ".env", override=False)

# ── Static directory (locally generated Pillow images) ───────────────────────
_STATIC_DIR = _SERVICE_DIR / "static"
_STATIC_DIR.mkdir(exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ie3_campaign_creative")

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/retail_radar"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_STORE_CODE = "MAIN"
FALLBACK_IMAGE_URL = "https://placehold.co/1024x1024/FF6B35/FFFFFF?text=Sale+Now"

_REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY") or os.getenv("REPLICATE_API_TOKEN", "")
_OPENAI_IMAGE_API_KEY  = os.getenv("OPENAI_API_KEY", "")
_ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")

_anthropic_client    = anthropic.AsyncAnthropic(api_key=_ANTHROPIC_API_KEY or "not-set")
_openai_image_client = AsyncOpenAI(api_key=_OPENAI_IMAGE_API_KEY or "not-set")
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
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:8082",
        "http://127.0.0.1:8082",
        "http://localhost:8083",
        "http://127.0.0.1:8083",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# Serve locally generated promo images (used when Replicate + imgbb are both unavailable)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

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
    whatsapp_message: str = Field(default='', max_length=160)
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
    # One entry per platform: {platform, success, post_id, post_url, error}
    social_posts: list[dict] = Field(default_factory=list)


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
                    on b.variant_id = v.id and b.store_id = %s and b.tenant_id = v.tenant_id
                left join lateral (
                    select amount
                    from core.prices
                    where variant_id = v.id
                      and tenant_id = v.tenant_id
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
    """
    Rule-based fallback used when OpenRouter is unavailable.
    Uses a deterministic template index (hash of product name % 6) so every
    product consistently gets a structurally different copy — not a cookie-cutter
    repeated across all items.

    Template styles:
      0 — scarcity-first    (stock count leads)
      1 — question opener   (hooks with a question)
      2 — benefit-led       (performance angle first)
      3 — price-drop story  (price narrative)
      4 — occasion/season   (timing angle)
      5 — editorial pick    (curation voice)
    """
    disc       = int(brief.suggested_discount_pct or 0)
    brand      = brief.brand
    name       = brief.product_name
    gender     = brief.gender_target or "athletes"
    cat        = brief.category.lower()
    price      = brief.retail_price_usd
    stock      = brief.current_stock
    brand_tag  = brand.replace(" ", "")
    price_now  = f"${price * (1 - disc / 100):.0f}" if disc else f"${price:.0f}"
    season_word = brief.season or "this season"

    # Deterministic selector — same product always gets same template
    t = sum(ord(c) for c in name) % 6

    # ── Instagram (max 300) ─────────────────────────────────────────────────
    ig = [
        # 0 — scarcity
        f"Only {stock} left. {name} by {brand} — {disc}% OFF right now. "
        f"Grab yours before it sells out. 🖤"
        f" #{brand_tag} #LimitedStock #SportsFashion #SaleNow",
        # 1 — question
        f"Ready to level up your {cat.split()[0]}? {brand}'s {name} just dropped "
        f"{disc}% off. In-store today. 🔥"
        f" #{brand_tag} #NewDrop #SportsFashion #BeirutStyle",
        # 2 — benefit-led
        f"Built for performance. The {name} by {brand} delivers every time. "
        f"Now {disc}% off — {stock} pairs available. 🏆"
        f" #{brand_tag} #SportsFashion #AthleticLife #GameOn",
        # 3 — price story
        f"Price just dropped. {brand} {name}: was full price, now {price_now}. "
        f"This {disc}% off deal won't last. 💰"
        f" #{brand_tag} #SaleAlert #SportsFashion #DealOfTheDay",
        # 4 — seasonal
        f"{season_word.capitalize()} update: {name} by {brand}, {disc}% off. "
        f"Designed for {gender} who move. Limited stock in-store. ☀️"
        f" #{brand_tag} #SportsFashion #SeasonSale #StylePulse",
        # 5 — editorial
        f"This week's pick: {brand} {name}. Clean design, built to last — now at {disc}% off. "
        f"{stock} pairs left. 👀"
        f" #{brand_tag} #EditorsPick #SportsFashion #BeirutFashion",
    ][t]

    # ── Facebook (max 500) ──────────────────────────────────────────────────
    fb = [
        # 0 — scarcity + CTA
        f"Act fast — only {stock} pairs of the {name} by {brand} remain at {disc}% off. "
        f"Whether you're training hard or keeping it casual, this is the one to grab. "
        f"Visit us in-store or order online while stock lasts."
        f" #{brand_tag} #LimitedStock #SportsFashion #SaleNow",
        # 1 — question + story
        f"Been thinking about upgrading your {cat.split()[0]} game? Now's the time. "
        f"We've just dropped {disc}% off the {name} by {brand}. "
        f"Built for {gender}, perfect for everyday performance. Come in-store or shop online."
        f" #{brand_tag} #SportsFashion #BeirutStyle #NewDrop",
        # 2 — product story
        f"The {name} from {brand} isn't just footwear — it's built around how {gender} move and perform. "
        f"Right now it's {disc}% off with {stock} units left. "
        f"Don't let someone else take your size."
        f" #{brand_tag} #AthleticLife #SportsFashion #GameOn",
        # 3 — direct price
        f"Big price drop on the {name} by {brand}. {disc}% off — that's {price_now} today. "
        f"We have {stock} units in stock. Classic style, serious performance, smarter price. "
        f"Stop by one of our locations before they're gone."
        f" #{brand_tag} #DealOfTheDay #SportsFashion #SaleAlert",
        # 4 — seasonal context
        f"{season_word.capitalize()} is here and so is a deal worth talking about. "
        f"{brand}'s {name} is now {disc}% off — perfect for {gender} heading into the new season. "
        f"{stock} pairs available in-store and online. Grab yours today."
        f" #{brand_tag} #SeasonSale #StylePulse #SportsFashion",
        # 5 — editorial
        f"Our team's pick this week: the {name} by {brand}. "
        f"It's on sale at {disc}% off and the {stock} we have won't last long. "
        f"Great {cat}, even better at this price. Head in-store or order now."
        f" #{brand_tag} #EditorsPick #SportsFashion #BeirutFashion",
    ][t]

    # ── TikTok (max 150) ────────────────────────────────────────────────────
    tt = [
        f"POV: {brand} {name} at {disc}% off and only {stock} left 🚨 no cap #{brand_tag}",
        f"asking for a friend: why is {brand}'s {name} {disc}% off rn 🤔 lowkey cop #{brand_tag}",
        f"it's giving performance ✨ {brand} {name} — {disc}% off today only #{brand_tag}",
        f"the {name} price drop just hit different 💸 {disc}% off, {stock} left #{brand_tag} #fyp",
        f"{season_word} era ☀️ {brand} {name} {disc}% off, built for {gender.split()[0]} #{brand_tag}",
        f"lowkey obsessed with this {brand} drop — {name} at {disc}% off, grab it #{brand_tag} #fyp",
    ][t]

    # ── WhatsApp (max 160) — Lebanese-friendly casual ───────────────────────
    wa = [
        f"Mar7aba! 👋 {name} by {brand} — {disc}% off, only {stock} left. Reply with your size to reserve.",
        f"Ahla! Looking for {cat.split()[0]}? {brand} {name} just dropped {disc}% off. DM us your size 🖤",
        f"Yalla, don't miss this: {brand} {name} is {disc}% off today. {stock} pairs in-store. Reply to reserve.",
        f"New deal alert 🚨 {name} by {brand}: now {price_now}. Was full price. Reply SIZE + CITY to hold yours.",
        f"{season_word.capitalize()} drop: {brand} {name}, {disc}% off. {stock} units left. DM us before it's gone!",
        f"This week's pick 👀 {brand} {name} at {disc}% off. Available in-store. Reply your size + city.",
    ][t]

    # ── Headlines (max 60) ──────────────────────────────────────────────────
    hl = [
        f"{disc}% OFF — Only {stock} {name} Left",
        f"{brand} {name} — {disc}% Off Now",
        f"Perform Better. Pay Less. {name} —{disc}%",
        f"Price Drop: {name} by {brand}",
        f"{season_word.capitalize()} Sale: {name} — {disc}% Off",
        f"{brand}'s {name} — Our Pick at {disc}% Off",
    ][t]

    # ── Short / Long copy ───────────────────────────────────────────────────
    short = [
        f"{stock} pairs. {disc}% off. The {name} by {brand} won't wait for you.",
        f"Upgrade your {cat.split()[0]} game — {brand} {name}, {disc}% off today only.",
        f"Performance + style in one. {name} by {brand}, now {disc}% off.",
        f"The {name} just got {disc}% cheaper. {brand} quality at a smarter price.",
        f"{season_word.capitalize()} deal: {brand} {name} at {disc}% off for {gender}.",
        f"Handpicked this week: {brand} {name} at {disc}% off. Limited stock.",
    ][t]

    long_ = [
        # 0
        f"With only {stock} units remaining, the {name} by {brand} is one of those buys you'll regret missing. "
        f"At {disc}% off, it's built for {gender} who train hard and want gear that keeps up. "
        f"Don't wait — grab your size before it's gone.",
        # 1
        f"The {name} by {brand} is built for serious {cat.split()[0]} performance. "
        f"With a {disc}% price drop active right now, there's no better time to invest in your training. "
        f"Available in-store and online while stock lasts.",
        # 2
        f"{brand}'s {name} delivers the kind of performance {gender} demand without compromise. "
        f"We've dropped the price by {disc}% on the {stock} units we have left. "
        f"Built to move, priced to move.",
        # 3
        f"A {disc}% price drop on the {name} by {brand} doesn't come along often. "
        f"This is premium {cat} at a fraction of the original price — {stock} pairs available today. "
        f"Visit us in-store or order online before it sells out.",
        # 4
        f"{season_word.capitalize()} calls for the right gear, and the {name} by {brand} delivers exactly that. "
        f"Designed for {gender}, now {disc}% off with {stock} units in stock. "
        f"Make this your season.",
        # 5
        f"Our team picked the {name} by {brand} this week for a reason: {disc}% off, "
        f"{stock} in stock, and a silhouette that holds up every season. "
        f"Quality {cat} at a price that makes sense.",
    ][t]

    cta_map = [
        ("Grab Yours Before It's Gone", "See All Deals"),
        ("Shop Now — Limited Stock",    "Browse Full Range"),
        ("Get It Before It Sells Out",  "View Full Collection"),
        ("Shop the Price Drop Now",     "See More Deals"),
        ("Shop the Sale Today",         "Explore the Collection"),
        ("Pick Yours Today",            "See What's New"),
    ][t]

    return {
        "instagram_caption": ig[:300],
        "facebook_post":     fb[:500],
        "tiktok_caption":    tt[:150],
        "whatsapp_message":  wa[:160],
        "headline":          hl[:60],
        "ad_copy_short":     short[:150],
        "ad_copy_long":      long_[:400],
        "cta_primary":       cta_map[0],
        "cta_secondary":     cta_map[1],
    }


def _truncate_copy_fields(copy: dict) -> dict:
    limits = {
        "instagram_caption": 300,
        "facebook_post": 500,
        "tiktok_caption": 150,
        "whatsapp_message": 160,
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
        "instagram_caption", "facebook_post", "tiktok_caption", "whatsapp_message",
        "headline", "ad_copy_short", "ad_copy_long",
        "cta_primary", "cta_secondary",
    }
    return required.issubset(copy.keys()) and all(
        isinstance(copy[k], str) and copy[k].strip() for k in required
    )


# ── LLM Prompts ───────────────────────────────────────────────────────────────

_TEXT_SYSTEM_PROMPT = """\
You are a professional retail marketing copywriter for StylePulse, \
a sports fashion retailer in Lebanon selling Adidas and other athletic brands.

Your job: generate realistic, platform-native ad copy for a product \
that has been flagged for promotion by the pricing engine.

You are given structured data about the product from the store's live inventory:
- Product name, brand, category, gender target
- Current retail price (USD) and suggested discount %
- Units remaining in stock
- Urgency level: high / medium / low
- Upcoming calendar event if any (e.g. Eid, Black Friday)

TONE RULES — adapt strictly based on urgency_level:
- high   → scarcity language: "Only X left", "Ends soon", FOMO-driven
- medium → aspirational: performance, lifestyle, confidence, leveling up
- low    → value-focused: quality, smart purchase, worth every penny

PLATFORM RULES:
- instagram_caption : max 300 chars — punchy opener + 4 relevant hashtags
- facebook_post     : max 500 chars — friendly, conversational, engaging — include 3–4 relevant hashtags at the end
- tiktok_caption    : max 150 chars — Gen-Z tone, emojis, casual ("no cap", \
"it's giving", "lowkey obsessed")
- whatsapp_message  : max 160 chars — personal, direct, Lebanese market (English). \
Feel like a friend texting. Can open with "Mar7aba", "Ahla", or "Yalla". \
End with a clear action: "Reply with your size", "DM to reserve", or "Available in-store today".
- headline          : max 60 chars  — bold, punchy, one strong idea
- ad_copy_short     : max 150 chars — one powerful benefit sentence
- ad_copy_long      : max 400 chars — story-driven, 2-3 sentences, benefit-led
- cta_primary       : max 10 words  — strong action ("Shop Now Before It's Gone")
- cta_secondary     : max 10 words  — softer action ("See Full Collection")

RULES:
- Do NOT invent specs, features, or prices not given to you
- Do NOT mention cost price or margin
- Always write in English (Lebanese market, English-dominant retail)
- Keep every output brand-safe and athletic lifestyle appropriate
- Each output must feel realistic and native to its platform — \
not copy-pasted across channels

Return ONLY a raw JSON object with these exact keys:
instagram_caption, facebook_post, tiktok_caption, whatsapp_message,
headline, ad_copy_short, ad_copy_long, cta_primary, cta_secondary

No markdown. No explanation. Raw JSON only."""

_TEXT_RETRY_SUFFIX = (
    "\n\nReturn ONLY valid JSON. No markdown. No extra text. "
    "Strictly follow character limits."
)

_IMAGE_SYSTEM_PROMPT = """\
You are a creative director writing image prompts for DALL-E 3 to generate \
square (1024×1024) retail promotional ads for Instagram and TikTok.

DALL-E 3 understands natural language — write a vivid scene description, NOT \
a token list.

Requirements:
- Include a clear SALE visual element as a graphic shape — a bold red corner \
  ribbon, a gold circular badge, or a price-tag silhouette. Do NOT include \
  readable text in the image (DALL-E renders text inaccurately); use shapes \
  and colors to convey the sale mood instead
- Describe the product prominently: exact name, colorway, and category
- Set the scene: background style, lighting mood, color palette, composition
- Match brand identity: Adidas = sleek/minimalist/three-stripe, \
  Nike = bold/dynamic/swoosh, Puma = edgy/streetwear, \
  New Balance = clean/heritage
- Match urgency: high = bold red-and-black palette, dramatic studio lighting, \
  "Limited Stock" urgency feel; medium = vibrant outdoor energy; \
  low = clean white studio with soft shadows
- If an event is provided (Ramadan, Back-to-School, Summer Sale, etc.), \
  weave thematic visuals into the background
- Style: photorealistic retail advertising photography, premium quality, \
  professional product shot, Instagram square format
- Max 130 words

Return ONLY the image prompt. No explanation, no JSON, no extra text."""


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
    disc = int(brief.suggested_discount_pct or 0)
    sale_price = brief.retail_price_usd * (1 - disc / 100)
    return (
        f"Product: {brief.product_name}\n"
        f"Brand: {brief.brand}\n"
        f"Category: {brief.category}\n"
        f"Color: {brief.color or 'N/A'}\n"
        f"Target audience: {brief.gender_target or 'unisex'}\n"
        f"Original price: ${brief.retail_price_usd:.2f}\n"
        f"Discount: {disc}% OFF — Sale price: ${sale_price:.2f}\n"
        f"Stock remaining: {brief.current_stock} units\n"
        f"Urgency level: {brief.urgency_level}\n"
        f"Season / upcoming event: {brief.upcoming_event or brief.season or 'none'}\n"
        f"Platform: Instagram & TikTok square ad"
    )


# ── LLM Callers ───────────────────────────────────────────────────────────────


async def _call_anthropic_text(brief: PromotionBrief, retry: bool = False) -> dict[str, str]:
    """Generate all ad copy using Anthropic Claude directly."""
    system = _TEXT_SYSTEM_PROMPT + (_TEXT_RETRY_SUFFIX if retry else "")
    response = await asyncio.wait_for(
        _anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": _text_user_message(brief)}],
        ),
        timeout=15.0,
    )
    block = next((b for b in response.content if b.type == "text"), None)
    raw = block.text.strip() if block else ""
    # Strip markdown code fences if the model wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    return json.loads(raw)


async def _call_anthropic_image_prompt(brief: PromotionBrief) -> str:
    """Generate a DALL-E 3 image prompt using Anthropic Claude directly."""
    response = await asyncio.wait_for(
        _anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=_IMAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _image_user_message(brief)}],
        ),
        timeout=10.0,
    )
    block = next((b for b in response.content if b.type == "text"), None)
    return block.text.strip() if block else ""


async def _generate_image_openai(image_prompt: str) -> str:
    """Generate a promotional image using OpenAI gpt-image-1 via direct HTTP."""
    if not _OPENAI_IMAGE_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    import base64

    enhanced_prompt = (
        f"{image_prompt}. "
        "Professional social media advertisement, high-end retail photography style, "
        "clean modern layout, vibrant brand colors, "
        "1:1 square format, Instagram-ready, premium quality product shot."
    )

    # Call the OpenAI API directly with httpx — the SDK always injects
    # response_format which gpt-image-1 does not accept.
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {_OPENAI_IMAGE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-image-1",
                "prompt": enhanced_prompt,
                "size": "1024x1024",
                "quality": "high",
                "n": 1,
            },
        )

    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI image API error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    b64 = data.get("data", [{}])[0].get("b64_json")
    if not b64:
        raise RuntimeError(f"gpt-image-1 returned no image data: {data}")

    img_bytes = base64.b64decode(b64)
    return await _upload_imgbb(img_bytes)


async def _generate_image_replicate(image_prompt: str) -> str:
    """Call Replicate REST API for Stable Diffusion image generation."""
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


async def _upload_imgbb(img_bytes: bytes) -> str:
    """Upload raw PNG bytes to imgbb.com and return a permanent public direct-image URL.

    imgbb returns two URL flavours:
      data["url"]          → https://i.ibb.co/<id>/filename.png  (direct image)
      data["url_viewer"]   → https://ibb.co/<id>                (webpage — do NOT use)

    Instagram's /media endpoint requires a direct image URL, so we use
    data["image"]["url"] which is unambiguously the raw file URL.
    """
    import base64
    api_key = os.getenv("IMGBB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("IMGBB_API_KEY not set")
    b64 = base64.b64encode(img_bytes).decode()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.imgbb.com/1/upload",
            data={"key": api_key, "image": b64},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # Prefer data["image"]["url"] — always https://i.ibb.co/... (direct file)
        return data["image"]["url"]


async def _generate_image_pillow(brief: PromotionBrief) -> str:
    """
    Generate a branded promo image with Pillow and upload to ImgBB.
    ImgBB upload is mandatory — Instagram requires a public HTTPS image URL.
    Raises RuntimeError if ImgBB key is missing or upload fails.
    """
    from services.campaign_creative.image_gen import generate_promo_image

    img_bytes = await asyncio.to_thread(
        generate_promo_image,
        brief.product_name,
        brief.brand,
        float(brief.suggested_discount_pct or 0),
        float(brief.retail_price_usd),
        brief.urgency_level,
        int(brief.current_stock),
        brief.color,
    )

    # ImgBB upload is required — Instagram needs a direct public URL
    return await _upload_imgbb(img_bytes)


async def _generate_image_full(
    image_prompt: str, brief: PromotionBrief
) -> tuple[str, bool]:
    """
    Generate a promo image and upload to ImgBB for a direct public URL.

    Chain: OpenAI DALL-E 3 → Replicate → Pillow (all upload to ImgBB).
    Returns (image_url, fallback_used) where image_url is always a
    direct public https://i.ibb.co/... URL.
    Raises RuntimeError if no public URL can be obtained.
    """
    # ── 1. OpenAI DALL-E 3 ────────────────────────────────────────────────────
    if _OPENAI_IMAGE_API_KEY:
        try:
            url = await _generate_image_openai(image_prompt)
            logger.info("OpenAI image generated for sku=%s", brief.product_name)
            return url, False
        except Exception as exc:
            logger.warning(
                "OpenAI image failed for sku=%s: %s — trying Replicate",
                brief.product_name, exc,
            )

    # ── 2. Replicate (Stable Diffusion) ───────────────────────────────────────
    try:
        url = await _generate_image_replicate(image_prompt)
        return url, False
    except Exception as exc:
        logger.warning(
            "Replicate failed for sku=%s: %s — falling back to Pillow+ImgBB",
            brief.product_name, exc,
        )

    # ── 3. Pillow + ImgBB (last resort — raises if ImgBB unavailable) ─────────
    url = await _generate_image_pillow(brief)
    return url, True


# ── FastAPI Endpoints ─────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "healthy", "service": "ie3_campaign_creative"}


@app.get("/debug/env")
def debug_env():
    tok = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
    return {"token_first30": tok[:30], "token_length": len(tok), "token_last4": tok[-4:] if tok else ""}


# ── Facebook: get Page ID helper ──────────────────────────────────────────────

@app.get("/meta/pages")
async def get_facebook_pages():
    """
    Returns the list of Facebook Pages the current token has access to.
    Use this to find your FB_PAGE_ID.

    Open in browser: http://localhost:8003/meta/pages
    Then copy the 'id' value and paste it as FB_PAGE_ID in .env
    """
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="FB_PAGE_ACCESS_TOKEN not set in .env")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://graph.facebook.com/v20.0/me/accounts",
            params={"access_token": token, "fields": "id,name,category,instagram_business_account"},
        )
    data = resp.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data


# ── Instagram (Meta) OAuth helpers ───────────────────────────────────────────

@app.get("/instagram/auth")
async def instagram_auth_start():
    """
    Step 1: open http://localhost:8003/instagram/auth in your browser.
    Redirects you to Meta's login + Instagram Business consent screen.

    Before using this, set in .env:
      META_APP_ID       — from developers.facebook.com → Your App → Settings → Basic
      META_APP_SECRET   — same page
    """
    from fastapi.responses import RedirectResponse
    import urllib.parse

    app_id = os.getenv("META_APP_ID", "").strip()
    if not app_id:
        raise HTTPException(
            status_code=400,
            detail="META_APP_ID not set in .env — get it from developers.facebook.com → Your App → Settings → Basic",
        )
    params = {
        "client_id":     app_id,
        "redirect_uri":  "http://localhost:8003/instagram/callback",
        "scope":         "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement",
        "response_type": "code",
        "state":         "stylepulse_ie3",
    }
    url = "https://www.facebook.com/v20.0/dialog/oauth?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@app.get("/instagram/callback")
async def instagram_callback(code: str = "", error: str = "", error_reason: str = ""):
    """
    Step 2: Meta redirects here after the user grants access.
    Exchanges the code for a long-lived user token, then fetches your
    Page token and Instagram User ID, and displays everything to copy.

    Redirect URL to paste in Meta Developer portal:
        http://localhost:8003/instagram/callback
    """
    from fastapi.responses import HTMLResponse

    if error:
        return HTMLResponse(f"<h2>Meta auth error</h2><pre>{error}: {error_reason}</pre>", status_code=400)
    if not code:
        return HTMLResponse("<h2>No code received from Meta</h2>", status_code=400)

    app_id     = os.getenv("META_APP_ID", "").strip()
    app_secret = os.getenv("META_APP_SECRET", "").strip()

    if not app_id or not app_secret:
        return HTMLResponse("<h2>META_APP_ID / META_APP_SECRET not set in .env</h2>", status_code=400)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Exchange code for short-lived token
        r1 = await client.get(
            "https://graph.facebook.com/v20.0/oauth/access_token",
            params={
                "client_id":     app_id,
                "client_secret":  app_secret,
                "redirect_uri":  "http://localhost:8003/instagram/callback",
                "code":          code,
            },
        )
        token_data = r1.json()
        if "access_token" not in token_data:
            return HTMLResponse(f"<h2>Short-lived token failed</h2><pre>{token_data}</pre>", status_code=400)

        short_token = token_data["access_token"]

        # Exchange for long-lived token (60-day)
        r2 = await client.get(
            "https://graph.facebook.com/v20.0/oauth/access_token",
            params={
                "grant_type":        "fb_exchange_token",
                "client_id":         app_id,
                "client_secret":     app_secret,
                "fb_exchange_token": short_token,
            },
        )
        ll_data    = r2.json()
        ll_token   = ll_data.get("access_token", short_token)
        expires_in = ll_data.get("expires_in", "unknown")

        # Get pages + linked IG account
        r3 = await client.get(
            "https://graph.facebook.com/v20.0/me/accounts",
            params={
                "access_token": ll_token,
                "fields":       "id,name,access_token,instagram_business_account",
            },
        )
        pages = r3.json().get("data", [])

    rows = ""
    for p in pages:
        ig_id  = (p.get("instagram_business_account") or {}).get("id", "—")
        rows  += f"""
        <tr>
          <td style="padding:6px 12px">{p.get('name')}</td>
          <td style="padding:6px 12px;font-weight:bold;color:#ff6b35">{p.get('id')}</td>
          <td style="padding:6px 12px;font-weight:bold;color:#0af">{ig_id}</td>
          <td style="padding:6px 12px;font-size:11px;word-break:break-all">{p.get('access_token','')[:60]}…</td>
        </tr>"""

    html = f"""
    <html><body style="font-family:monospace;padding:2rem;background:#111;color:#eee">
    <h2 style="color:#ff6b35">✅ Meta tokens received!</h2>

    <h3>Long-lived user token (expires in {expires_in}s)</h3>
    <p>Paste as <b>FB_PAGE_ACCESS_TOKEN</b> in .env:</p>
    <textarea rows="3" cols="100" style="background:#222;color:#0f0;padding:.5rem">{ll_token}</textarea>

    <h3 style="margin-top:1.5rem">Your Pages + Instagram accounts</h3>
    <table border="0" cellspacing="0" style="background:#1a1a1a;border-collapse:collapse">
      <tr style="background:#333">
        <th style="padding:6px 12px">Page name</th>
        <th style="padding:6px 12px">FB_PAGE_ID</th>
        <th style="padding:6px 12px">IG_USER_ID</th>
        <th style="padding:6px 12px">Page access_token (paste as FB_PAGE_ACCESS_TOKEN if posting to that page)</th>
      </tr>
      {rows}
    </table>

    <p style="margin-top:1.5rem;color:#aaa">After updating .env, restart uvicorn.</p>
    </body></html>
    """
    return HTMLResponse(html)


@app.post("/campaign/generate", response_model=CampaignPackage)
async def generate_campaign(recommendation: RecommendationResult):
    """
    Generate and publish a full campaign for a PROMOTE recommendation.

    Flow:
      1. Gate: only PROMOTE decisions proceed
      2. DB lookup: fetch brand, category, stock, price for the SKU
      3. In parallel: generate text copy + image prompt via OpenRouter (Claude)
      4. Generate promo image (OpenAI gpt-image-1 → Replicate → Pillow)
      5. Upload image to ImgBB — obtain direct public URL
      6. Validate image URL is publicly accessible
      7. Publish to Instagram and Facebook
      8. Write campaign to DB
      9. Return CampaignPackage — HTTP 400 if image or both publishes fail
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

    # Pull upcoming_event from the recommendation's SHAP features if tagged
    upcoming_event: Optional[str] = None
    for feat in recommendation.shap_top5:
        if "event" in feat.feature_name.lower() and feat.shap_value > 0:
            upcoming_event = feat.explanation
            break

    brief = PromotionBrief(
        recommendation_id=None,  # populated once IE2 writes to marketing.recommendations first
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
        upcoming_event=upcoming_event,
    )

    fallback_used = False

    # ── Steps 2 & 3 in parallel: text copy + image prompt ────────────────────

    async def _get_text_copy() -> tuple[dict[str, str], bool]:
        """Returns (copy_dict, used_fallback)."""
        try:
            raw = await _call_anthropic_text(brief)
            if not _validate_copy_keys(raw):
                raise ValueError("Response missing required copy keys")
            return _truncate_copy_fields(raw), False
        except Exception as exc:
            logger.warning(
                "Text copy attempt 1 failed for sku=%s: %s — retrying",
                recommendation.sku_id, exc,
            )
        try:
            raw = await _call_anthropic_text(brief, retry=True)
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
            return await _call_anthropic_image_prompt(brief)
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

    # ── Step 4: generate image + upload to ImgBB ──────────────────────────────
    try:
        image_url, img_fallback = await _generate_image_full(image_prompt, brief)
    except Exception as exc:
        logger.error("Image generation failed for sku=%s: %s", recommendation.sku_id, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image generation failed: {exc}",
        )
    if img_fallback:
        fallback_used = True

    # ── Step 5: assemble CampaignPackage ─────────────────────────────────────
    package = CampaignPackage(
        recommendation_id=brief.recommendation_id,
        instagram_caption=text_copy["instagram_caption"],
        facebook_post=text_copy["facebook_post"],
        tiktok_caption=text_copy["tiktok_caption"],
        whatsapp_message=text_copy.get("whatsapp_message", ""),
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

    # ── Step 7: publish to Instagram + Facebook (both required) ──────────────
    from services.campaign_creative.publishers import publish_to_all_platforms

    try:
        social_posts = await asyncio.wait_for(
            publish_to_all_platforms(
                package.instagram_caption,
                package.facebook_post,
                package.image_url,
            ),
            timeout=90.0,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Social publishing failed: {exc}",
        )

    # Log each result and collect failures
    failures: list[str] = []
    for r in social_posts:
        if r["success"]:
            logger.info(
                "Published to %s for sku=%s post_id=%s",
                r["platform"], recommendation.sku_id, r["post_id"],
            )
        else:
            logger.error(
                "Publish to %s FAILED for sku=%s: %s",
                r["platform"], recommendation.sku_id, r["error"],
            )
            failures.append(f"{r['platform']}: {r['error']}")

    if failures:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Campaign generated but social publishing failed",
                "image_url": package.image_url,
                "failures": failures,
            },
        )

    return package.model_copy(update={"social_posts": social_posts})
