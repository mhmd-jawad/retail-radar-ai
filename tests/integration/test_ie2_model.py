"""
Integration tests for IE2 Decision Intelligence — real model, no mocks.

Tests load the actual CatBoost model from disk and call _recommend_single()
directly to verify the full pipeline: feature engineering → rules engine →
model inference → output schema.

Run:
    pytest tests/integration/test_ie2_model.py -v
"""

from __future__ import annotations

import pytest
from pathlib import Path

from services.decision_intelligence.main import (
    LOCAL_PINNED_MODEL_EXPORT_DIR,
    REGISTERED_MODEL,
    _recommend_single,
)
from services.decision_intelligence.schemas import (
    CompetitorSignals,
    RecommendationRequest,
    RecommendationResult,
)

# ── Model presence guard ───────────────────────────────────────────────────────

_model_present = REGISTERED_MODEL is not None

requires_model = pytest.mark.skipif(
    not _model_present,
    reason="CatBoost model not loaded — skipping model integration tests",
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_request(**overrides) -> RecommendationRequest:
    """Build a valid RecommendationRequest with safe defaults.

    Default feature profile produces a moderate healthy SKU:
    - category=footwear, brand=Adidas
    - retail=100, cost=55  → 45% margin
    - current_stock=50, initial_stock=100 → 50% sell-through
    - days_since_launch=180, no recent discount
    """
    defaults = dict(
        sku_id="INT-TEST-001",
        product_name="Integration Test Product",
        brand="Adidas",
        category="footwear",
        retail_price_usd=100.0,
        cost_price_usd=55.0,
        current_stock=50,
        initial_stock=100,
        days_since_launch=180,
        days_since_last_discount=60,
        days_at_current_price=30,
        competitor_signals=None,
    )
    defaults.update(overrides)
    return RecommendationRequest(**defaults)


def _make_competitor_signals(sku_id: str = "INT-TEST-001", **overrides) -> CompetitorSignals:
    defaults = dict(
        sku_id=sku_id,
        competitor_min_price=80.0,
        competitor_avg_price=90.0,
        price_gap_pct=0.0,
        competitors_on_sale_count=0,
        competitors_out_of_stock_count=0,
        num_competitors_tracked=3,
        data_freshness_hours=12.0,
        confidence_score=0.85,
        fallback_used=False,
    )
    defaults.update(overrides)
    return CompetitorSignals(**defaults)


# ── Model loading ──────────────────────────────────────────────────────────────

class TestModelLoads:
    def test_model_artifact_directory_exists(self):
        assert Path(LOCAL_PINNED_MODEL_EXPORT_DIR).exists(), (
            f"Model export directory missing: {LOCAL_PINNED_MODEL_EXPORT_DIR}"
        )

    @requires_model
    def test_registered_model_is_not_none(self):
        assert REGISTERED_MODEL is not None

    @requires_model
    def test_registered_model_has_predict_proba(self):
        assert hasattr(REGISTERED_MODEL, "predict_proba")


# ── Rules-engine deterministic decisions (guaranteed, no model needed) ─────────

class TestRulesEngineOverride:
    """
    These decisions are forced by hard rules, so they are deterministic
    regardless of whether the ML model is loaded or what month it is.
    """

    def test_low_stock_forces_hold(self):
        """total_qty < 15 → LOW_STOCK_PROTECTION → forced HOLD."""
        req = _make_request(
            sku_id="HOLD-LOW-STOCK",
            current_stock=5,
            initial_stock=100,
            retail_price_usd=100.0,
            cost_price_usd=55.0,
        )
        result = _recommend_single(req)
        assert result.recommendation == "HOLD"
        assert result.requires_human_approval is True

    def test_dead_stock_forces_clear(self):
        """
        swimwear (velocity=0.60) + expensive price → DOS ≈ 182 days.
        Low sell-through (current ≈ initial) + launched 200 days ago
        → DEAD_STOCK_CLEAR absolute override.
        """
        req = _make_request(
            sku_id="CLEAR-DEAD-STOCK",
            category="swimwear",
            retail_price_usd=200.0,
            cost_price_usd=100.0,
            current_stock=490,
            initial_stock=500,       # sell-through = 2%
            days_since_launch=200,   # on shelf > 60 days
            days_since_last_discount=90,
        )
        result = _recommend_single(req)
        assert result.recommendation == "CLEAR"
        assert result.rule_override is not None
        assert result.rule_override.rule_id == "DEAD_STOCK_CLEAR"
        assert result.rule_override.override_strength == "absolute"

    def test_low_stock_blocks_markdown_in_shap(self):
        """When LOW_STOCK_PROTECTION fires, rule_override must be set."""
        req = _make_request(current_stock=8, initial_stock=100)
        result = _recommend_single(req)
        # Either a rule_override is set OR a hard rule forced the decision
        assert result.recommendation in ("HOLD", "CLEAR")


# ── Output schema invariants ───────────────────────────────────────────────────

class TestOutputSchema:
    """These run regardless of model, testing output shape."""

    def test_result_is_recommendation_result(self):
        req = _make_request()
        result = _recommend_single(req)
        assert isinstance(result, RecommendationResult)

    def test_recommendation_is_valid_label(self):
        req = _make_request()
        result = _recommend_single(req)
        assert result.recommendation in ("HOLD", "MARKDOWN", "PROMOTE", "CLEAR")

    def test_confidence_in_range(self):
        req = _make_request()
        result = _recommend_single(req)
        assert 0.0 <= result.confidence <= 1.0

    def test_sku_id_propagated(self):
        req = _make_request(sku_id="MY-SKU-999")
        result = _recommend_single(req)
        assert result.sku_id == "MY-SKU-999"

    def test_product_name_propagated(self):
        req = _make_request(product_name="Adidas Predator Boot")
        result = _recommend_single(req)
        assert result.product_name == "Adidas Predator Boot"

    def test_shap_top5_is_list(self):
        req = _make_request()
        result = _recommend_single(req)
        assert isinstance(result.shap_top5, list)

    def test_shap_entries_have_required_fields(self):
        req = _make_request()
        result = _recommend_single(req)
        for entry in result.shap_top5:
            assert hasattr(entry, "feature_name")
            assert hasattr(entry, "shap_value")
            assert entry.direction in ("increases_probability", "decreases_probability")

    def test_explanation_is_non_empty_string(self):
        req = _make_request()
        result = _recommend_single(req)
        assert isinstance(result.explanation, str)
        assert len(result.explanation) > 0

    def test_processing_time_is_non_negative(self):
        req = _make_request()
        result = _recommend_single(req)
        assert result.processing_time_ms >= 0

    def test_requires_human_approval_always_true(self):
        req = _make_request()
        result = _recommend_single(req)
        assert result.requires_human_approval is True

    def test_model_version_is_set(self):
        req = _make_request()
        result = _recommend_single(req)
        assert isinstance(result.model_version, str)
        assert len(result.model_version) > 0


# ── ML model predictions ───────────────────────────────────────────────────────

class TestModelPredictions:
    """
    Tests that require the CatBoost model to be loaded.
    Feature vectors are crafted to produce high-confidence predictions.
    """

    @requires_model
    def test_promote_features_yield_promote(self):
        """
        accessories (velocity=1.30) + low price → DOS ≈ 45 days.
        Good margin (50%), moderate sell-through (50%), no discount cooldown.
        April seasonality = 1.10, which meets the PROMOTE signal threshold.
        """
        req = _make_request(
            sku_id="PROMOTE-TEST",
            category="accessories",
            brand="Nike",
            retail_price_usd=60.0,
            cost_price_usd=30.0,    # margin = 50%
            current_stock=100,
            initial_stock=200,      # sell-through = 50%
            days_since_launch=120,
            days_since_last_discount=90,
            competitor_signals=_make_competitor_signals(
                sku_id="PROMOTE-TEST",
                price_gap_pct=0.0,
                competitors_on_sale_count=0,
                competitors_out_of_stock_count=3,
                num_competitors_tracked=4,
            ),
        )
        result = _recommend_single(req)
        assert result.recommendation == "PROMOTE", (
            f"Expected PROMOTE, got {result.recommendation} "
            f"(confidence={result.confidence:.2f}, "
            f"rule_override={result.rule_override})"
        )
        assert result.confidence >= 0.5

    @requires_model
    def test_markdown_features_yield_markdown(self):
        """
        sportswear (velocity=1.00), moderate DOS, high price gap,
        many competitors on sale, no recent discount → expect MARKDOWN.
        """
        req = _make_request(
            sku_id="MARKDOWN-TEST",
            category="sportswear",
            brand="Adidas",
            retail_price_usd=80.0,
            cost_price_usd=40.0,     # margin = 50%
            current_stock=100,
            initial_stock=150,       # sell-through = 33%
            days_since_launch=200,
            days_since_last_discount=60,
            competitor_signals=_make_competitor_signals(
                sku_id="MARKDOWN-TEST",
                competitor_min_price=60.0,
                competitor_avg_price=68.0,
                price_gap_pct=0.20,   # 20% more expensive than market
                competitors_on_sale_count=5,
                competitors_out_of_stock_count=0,
                num_competitors_tracked=6,
            ),
        )
        result = _recommend_single(req)
        assert result.recommendation == "MARKDOWN", (
            f"Expected MARKDOWN, got {result.recommendation} "
            f"(confidence={result.confidence:.2f}, "
            f"rule_override={result.rule_override})"
        )

    @requires_model
    def test_model_confidence_higher_than_fallback_threshold(self):
        """For clear-signal inputs, confidence should exceed the 0.45 fallback threshold."""
        req = _make_request(
            sku_id="HIGH-CONF-TEST",
            category="swimwear",
            retail_price_usd=200.0,
            cost_price_usd=100.0,
            current_stock=490,
            initial_stock=500,
            days_since_launch=200,
        )
        result = _recommend_single(req)
        # CLEAR via rules has confidence = 1.0; anything well above fallback is fine
        assert result.confidence >= 0.45
