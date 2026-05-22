"""
Unit tests for IE3 — Campaign Creative Service.

Tests are fully offline: all external calls (OpenRouter, Replicate, PostgreSQL)
are mocked so no API keys or database are needed.

Run:
    pytest tests/unit/test_campaign_creative.py -v
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from services.campaign_creative.main import (
    app,
    _derive_urgency,
    _urgency_to_tone,
    _build_fallback_copy,
    _validate_copy_keys,
    _truncate_copy_fields,
    PromotionBrief,
    CampaignPackage,
)


# ── Shared fixtures ────────────────────────────────────────────────────────────

PROMOTE_PAYLOAD: dict[str, Any] = {
    "sku_id": "ADI-PRED-EDGE-42",
    "product_name": "Adidas Predator Edge Football Boot",
    "recommendation": "PROMOTE",
    "confidence": 0.91,
    "explanation": "Strong seasonality, competitors out of stock, good margin buffer.",
    "shap_top5": [
        {
            "feature_name": "seasonality_score",
            "feature_value": 1.2,
            "shap_value": 0.31,
            "direction": "increases_probability",
            "explanation": "Peak season",
        },
        {
            "feature_name": "price_gap_pct",
            "feature_value": 0.08,
            "shap_value": 0.22,
            "direction": "increases_probability",
            "explanation": "Slightly above market",
        },
        {
            "feature_name": "current_margin_pct",
            "feature_value": 48.0,
            "shap_value": 0.18,
            "direction": "decreases_probability",
            "explanation": "Good margin",
        },
        {
            "feature_name": "days_of_supply",
            "feature_value": 18.0,
            "shap_value": 0.15,
            "direction": "increases_probability",
            "explanation": "Low stock",
        },
        {
            "feature_name": "model_baseline",
            "feature_value": "PROMOTE",
            "shap_value": 0.05,
            "direction": "increases_probability",
            "explanation": "Base signal",
        },
    ],
    "suggested_discount_pct": 15.0,
    "model_version": "rules_v1",
    "processing_time_ms": 120,
    "requires_human_approval": True,
}

MOCK_TEXT_COPY: dict[str, str] = {
    "instagram_caption": "🔥 Adidas Predator Edge is 15% OFF — limited stock! #SportsFashion #Adidas #Football #SaleAlert",
    "facebook_post": "Big drop! Adidas Predator Edge Football Boot is now 15% off. Grab yours before it sells out!",
    "tiktok_caption": "POV: Adidas just dropped 15% off the Predator Edge 👟🔥 no cap #Adidas #Football",
    "headline": "15% OFF — Predator Edge by Adidas",
    "ad_copy_short": "Limited stock. 15% off the Adidas Predator Edge. Shop now.",
    "ad_copy_long": "The Adidas Predator Edge Football Boot is engineered for elite performance. At 15% off, this is your moment. Limited stock — don't miss it.",
    "cta_primary": "Shop Now",
    "cta_secondary": "View Details",
}

MOCK_IMAGE_PROMPT = (
    "Adidas Predator Edge football boot on a dramatic stadium pitch at night, "
    "floodlights, bold red and black palette, dynamic motion blur, sale banner overlay"
)

MOCK_IMAGE_URL = "https://replicate.delivery/pbxt/mock-image-output.png"


@pytest.fixture
def mock_db():
    """Patches both DB functions so no PostgreSQL is needed."""
    with (
        patch(
            "services.campaign_creative.main._fetch_product_data_sync",
            return_value={
                "brand": "Adidas",
                "category": "football_boots",
                "gender_target": "male",
                "season": "winter",
                "color": "black/red",
                "retail_price_usd": 149.99,
                "cost_price_usd": 72.00,
                "current_stock": 14,
            },
        ),
        patch(
            "services.campaign_creative.main._write_campaigns_sync",
            return_value=None,
        ),
    ):
        yield


@pytest.fixture
def mock_llm_success():
    """Patches OpenRouter to return valid text copy + image prompt."""
    text_response = MagicMock()
    text_response.choices = [MagicMock()]
    text_response.choices[0].message.content = json.dumps(MOCK_TEXT_COPY)

    image_response = MagicMock()
    image_response.choices = [MagicMock()]
    image_response.choices[0].message.content = MOCK_IMAGE_PROMPT

    async def _create(**kwargs):
        # Return image prompt response for the shorter max_tokens call
        if kwargs.get("max_tokens", 1200) <= 200:
            return image_response
        return text_response

    with patch(
        "services.campaign_creative.main._openrouter_client"
    ) as mock_client:
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=_create)
        yield mock_client


@pytest.fixture
def mock_replicate_success():
    """Patches Replicate httpx calls to return a fake image URL."""
    poll_succeeded = {
        "status": "succeeded",
        "output": [MOCK_IMAGE_URL],
    }

    async def _httpx_post(*args, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "id": "mock-prediction-id",
            "urls": {"get": "https://api.replicate.com/v1/predictions/mock-prediction-id"},
            "status": "starting",
        }
        return resp

    async def _httpx_get(*args, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = poll_succeeded
        return resp

    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=False)
    mock_async_client.post = AsyncMock(side_effect=_httpx_post)
    mock_async_client.get = AsyncMock(side_effect=_httpx_get)

    with (
        patch("services.campaign_creative.main.httpx.AsyncClient", return_value=mock_async_client),
        patch("services.campaign_creative.main._REPLICATE_API_KEY", "test-key-mock"),
    ):
        yield


# ── Pure unit tests (no HTTP) ──────────────────────────────────────────────────

class TestDeriveUrgency:
    def test_high_when_confidence_above_085(self):
        assert _derive_urgency(0.91, 100) == "high"

    def test_high_when_stock_below_20(self):
        assert _derive_urgency(0.50, 15) == "high"

    def test_medium_when_confidence_above_070(self):
        assert _derive_urgency(0.75, 60) == "medium"

    def test_medium_when_stock_below_50(self):
        assert _derive_urgency(0.60, 45) == "medium"

    def test_low_otherwise(self):
        assert _derive_urgency(0.55, 80) == "low"

    def test_stock_below_20_overrides_low_confidence(self):
        assert _derive_urgency(0.30, 5) == "high"


class TestUrgencyToTone:
    def test_high_maps_to_urgent(self):
        assert _urgency_to_tone("high") == "urgent"

    def test_medium_maps_to_aspirational(self):
        assert _urgency_to_tone("medium") == "aspirational"

    def test_low_maps_to_value_focused(self):
        assert _urgency_to_tone("low") == "value_focused"


class TestFallbackCopy:
    def setup_method(self):
        self.brief = PromotionBrief(
            product_name="Adidas Predator Edge Football Boot",
            brand="Adidas",
            category="football_boots",
            retail_price_usd=149.99,
            suggested_discount_pct=15.0,
            current_stock=14,
            confidence=0.91,
            urgency_level="high",
            gender_target="male",
        )

    def test_all_required_keys_present(self):
        copy = _build_fallback_copy(self.brief)
        assert _validate_copy_keys(copy)

    def test_instagram_within_limit(self):
        copy = _build_fallback_copy(self.brief)
        assert len(copy["instagram_caption"]) <= 300

    def test_facebook_within_limit(self):
        copy = _build_fallback_copy(self.brief)
        assert len(copy["facebook_post"]) <= 500

    def test_tiktok_within_limit(self):
        copy = _build_fallback_copy(self.brief)
        assert len(copy["tiktok_caption"]) <= 150

    def test_headline_within_limit(self):
        copy = _build_fallback_copy(self.brief)
        assert len(copy["headline"]) <= 60

    def test_brand_appears_in_copy(self):
        copy = _build_fallback_copy(self.brief)
        assert "Adidas" in copy["instagram_caption"]
        assert "Adidas" in copy["facebook_post"]


class TestValidateCopyKeys:
    def test_returns_true_for_complete_copy(self):
        assert _validate_copy_keys(MOCK_TEXT_COPY) is True

    def test_returns_false_when_key_missing(self):
        incomplete = {k: v for k, v in MOCK_TEXT_COPY.items() if k != "tiktok_caption"}
        assert _validate_copy_keys(incomplete) is False

    def test_returns_false_when_value_empty(self):
        bad = {**MOCK_TEXT_COPY, "headline": ""}
        assert _validate_copy_keys(bad) is False


class TestTruncateCopyFields:
    def test_truncates_instagram_to_300(self):
        long_copy = {**MOCK_TEXT_COPY, "instagram_caption": "x" * 400}
        result = _truncate_copy_fields(long_copy)
        assert len(result["instagram_caption"]) == 300

    def test_does_not_shorten_already_short_fields(self):
        result = _truncate_copy_fields({**MOCK_TEXT_COPY})
        assert result["headline"] == MOCK_TEXT_COPY["headline"]


# ── FastAPI endpoint tests ─────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


async def test_generate_campaign_happy_path(
    client, mock_db, mock_llm_success, mock_replicate_success
):
    resp = await client.post("/campaign/generate", json=PROMOTE_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()

    # All required fields present
    for field in (
        "instagram_caption", "facebook_post", "tiktok_caption",
        "headline", "ad_copy_short", "ad_copy_long",
        "cta_primary", "cta_secondary", "image_url", "image_prompt",
        "tone_used", "fallback_used", "prompt_version",
    ):
        assert field in data, f"Missing field: {field}"

    # Length constraints
    assert len(data["instagram_caption"]) <= 300
    assert len(data["facebook_post"]) <= 500
    assert len(data["tiktok_caption"]) <= 150
    assert len(data["headline"]) <= 60
    assert len(data["ad_copy_short"]) <= 150
    assert len(data["ad_copy_long"]) <= 400

    # Correct tone for confidence=0.91 (→ urgency=high → urgent)
    assert data["tone_used"] == "urgent"

    # Image came from mocked Replicate
    assert data["image_url"] == MOCK_IMAGE_URL
    assert data["fallback_used"] is False
    assert data["prompt_version"] == "v1.0"


async def test_generate_campaign_rejects_non_promote(client):
    payload = {**PROMOTE_PAYLOAD, "recommendation": "HOLD"}
    resp = await client.post("/campaign/generate", json=payload)
    assert resp.status_code == 400
    assert "PROMOTE" in resp.json()["detail"]


async def test_generate_campaign_rejects_markdown(client):
    payload = {**PROMOTE_PAYLOAD, "recommendation": "MARKDOWN"}
    resp = await client.post("/campaign/generate", json=payload)
    assert resp.status_code == 400


async def test_generate_campaign_rejects_clear(client):
    payload = {**PROMOTE_PAYLOAD, "recommendation": "CLEAR"}
    resp = await client.post("/campaign/generate", json=payload)
    assert resp.status_code == 400


async def test_generate_campaign_uses_fallback_when_llm_fails(
    client, mock_db, mock_replicate_success
):
    """When OpenRouter fails both attempts, fallback templates are used and fallback_used=True."""
    with patch(
        "services.campaign_creative.main._openrouter_client"
    ) as mock_client:
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("OpenRouter timeout")
        )
        resp = await client.post("/campaign/generate", json=PROMOTE_PAYLOAD)

    assert resp.status_code == 200
    data = resp.json()
    assert data["fallback_used"] is True
    # Fallback copy still returns valid non-empty fields
    assert data["headline"]
    assert data["instagram_caption"]


async def test_generate_campaign_uses_fallback_image_when_replicate_fails(
    client, mock_db, mock_llm_success
):
    """When Replicate fails, fallback image URL is used and fallback_used=True."""
    with patch(
        "services.campaign_creative.main.httpx.AsyncClient"
    ) as mock_httpx:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.post = AsyncMock(side_effect=Exception("Replicate down"))
        mock_httpx.return_value = instance

        resp = await client.post("/campaign/generate", json=PROMOTE_PAYLOAD)

    assert resp.status_code == 200
    data = resp.json()
    assert data["fallback_used"] is True
    assert "placehold.co" in data["image_url"]


async def test_generate_campaign_db_failure_still_returns_package(
    client, mock_llm_success, mock_replicate_success
):
    """DB errors are non-fatal — the package is still returned to the caller."""
    with (
        patch(
            "services.campaign_creative.main._fetch_product_data_sync",
            side_effect=Exception("DB connection refused"),
        ),
        patch(
            "services.campaign_creative.main._write_campaigns_sync",
            side_effect=Exception("DB write failed"),
        ),
    ):
        resp = await client.post("/campaign/generate", json=PROMOTE_PAYLOAD)

    assert resp.status_code == 200
    data = resp.json()
    assert data["headline"]  # package still assembled with defaults


async def test_generate_campaign_invalid_json_from_llm_triggers_retry_then_fallback(
    client, mock_db, mock_replicate_success
):
    """LLM returns non-JSON → retry → still fails → fallback templates used."""
    with patch(
        "services.campaign_creative.main._openrouter_client"
    ) as mock_client:
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        bad_response = MagicMock()
        bad_response.choices = [MagicMock()]
        bad_response.choices[0].message.content = "Sure! Here is your copy: not json at all"
        mock_client.chat.completions.create = AsyncMock(return_value=bad_response)

        resp = await client.post("/campaign/generate", json=PROMOTE_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json()["fallback_used"] is True
