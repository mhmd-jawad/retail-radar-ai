"""
Integration tests for the full PROMOTE decision pipeline.

Tests the flow:
    EEP /recommend/full
        → _recommend_single() returns PROMOTE
        → /recommend/full looks up campaign_creative in the report
        → returns unified response

IE2 (_recommend_single) and the report builder are mocked.
No real database, no real model inference, no real HTTP calls.

Run:
    pytest tests/integration/test_promote_pipeline.py -v
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from eep.main import app
from services.decision_intelligence.schemas import RecommendationResult, SHAPFeature

# ── Fixtures ───────────────────────────────────────────────────────────────────

_PROMOTE_RESULT = RecommendationResult(
    sku_id="ADI-PROMO-001",
    product_name="Adidas Predator Edge Football Boot",
    recommendation="PROMOTE",
    confidence=0.91,
    explanation="Strong seasonality, competitors out of stock, good margin buffer.",
    shap_top5=[
        SHAPFeature(
            feature_name="seasonality_score",
            feature_value=1.2,
            shap_value=0.31,
            direction="increases_probability",
            explanation="Peak season — high demand expected.",
        ),
        SHAPFeature(
            feature_name="current_margin_pct",
            feature_value=48.0,
            shap_value=0.18,
            direction="decreases_probability",
            explanation="Strong margin — room to run promotion.",
        ),
    ],
    rule_override=None,
    fallback_used=False,
    model_version="mlflow_export:retail_radar_decision_model_v6",
    processing_time_ms=45,
    requires_human_approval=True,
    suggested_discount_pct=None,
    margin_after_action_pct=48.0,
    generated_at=datetime(2026, 4, 27, 10, 0, 0),
)

_HOLD_RESULT = RecommendationResult(
    sku_id="ADI-HOLD-001",
    product_name="Adidas Hold Product",
    recommendation="HOLD",
    confidence=0.80,
    explanation="Healthy inventory — no action required.",
    shap_top5=[
        SHAPFeature(
            feature_name="days_of_supply",
            feature_value=60.0,
            shap_value=0.25,
            direction="decreases_probability",
            explanation="60 days of stock remaining.",
        )
    ],
    rule_override=None,
    fallback_used=False,
    model_version="mlflow_export:retail_radar_decision_model_v6",
    processing_time_ms=30,
    requires_human_approval=True,
    generated_at=datetime(2026, 4, 27, 10, 0, 0),
)

_VALID_IE2_REQUEST_DICT = {
    "sku_id": "ADI-PROMO-001",
    "product_name": "Adidas Predator Edge Football Boot",
    "brand": "Adidas",
    "category": "football_boots",
    "retail_price_usd": 150.0,
    "cost_price_usd": 78.0,
    "current_stock": 30,
    "initial_stock": 60,
    "days_since_launch": 120,
    "days_since_last_discount": 90,
    "days_at_current_price": 14,
    "competitor_signals": None,
}

_REPORT_WITH_CREATIVE = {
    "metadata": {"generated_at": "2026-04-27T10:00:00"},
    "inventory": {"metrics": {}},
    "competitor": {"market_overview": {}},
    "promotions": {
        "summary": {},
        "promote": [
            {
                "sku_id": "ADI-PROMO-001",
                "creative": {
                    "headline": "Score Big This Season",
                    "body_copy": "Limited stock — don't miss the Predator Edge.",
                    "cta": "Shop Now",
                    "image_url": "https://example.com/promo.jpg",
                },
            }
        ],
    },
    "financial": {
        "cashflow_health": {"cash_runway_months": 6.0},
        "balance_sheet_health": {"inventory_pct_of_assets": 0.30},
        "profitability": {"blended_margin_pct": 45.0},
    },
}

_REPORT_WITHOUT_CREATIVE = {
    **_REPORT_WITH_CREATIVE,
    "promotions": {"summary": {}, "promote": []},
}


# ── PROMOTE decision pipeline ─────────────────────────────────────────────────

class TestPromotePipeline:
    def test_promote_response_is_200(self):
        with patch("eep.main._recommend_single", return_value=_PROMOTE_RESULT), \
             patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT), \
             patch("eep.main.build_frontend_report", return_value=_REPORT_WITH_CREATIVE), \
             patch("eep.main.report_overview", return_value={"sku_count": 5, "shop_count": 2}):
            with TestClient(app) as client:
                r = client.post("/recommend/full", json={"sku_id": "ADI-PROMO-001"})
        assert r.status_code == 200

    def test_promote_ie2_result_in_response(self):
        with patch("eep.main._recommend_single", return_value=_PROMOTE_RESULT), \
             patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT), \
             patch("eep.main.build_frontend_report", return_value=_REPORT_WITH_CREATIVE), \
             patch("eep.main.report_overview", return_value={"sku_count": 5, "shop_count": 2}):
            with TestClient(app) as client:
                r = client.post("/recommend/full", json={"sku_id": "ADI-PROMO-001"})
        body = r.json()
        assert "ie2_result" in body
        assert body["ie2_result"]["recommendation"] == "PROMOTE"

    def test_promote_campaign_creative_is_returned(self):
        """When a PROMOTE SKU has a creative in the report, it must appear in the response."""
        with patch("eep.main._recommend_single", return_value=_PROMOTE_RESULT), \
             patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT), \
             patch("eep.main.build_frontend_report", return_value=_REPORT_WITH_CREATIVE), \
             patch("eep.main.report_overview", return_value={"sku_count": 5, "shop_count": 2}):
            with TestClient(app) as client:
                r = client.post("/recommend/full", json={"sku_id": "ADI-PROMO-001"})
        body = r.json()
        assert body["campaign_creative"] is not None
        assert body["campaign_creative"]["headline"] == "Score Big This Season"
        assert body["campaign_creative"]["cta"] == "Shop Now"

    def test_promote_status_is_complete(self):
        with patch("eep.main._recommend_single", return_value=_PROMOTE_RESULT), \
             patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT), \
             patch("eep.main.build_frontend_report", return_value=_REPORT_WITH_CREATIVE), \
             patch("eep.main.report_overview", return_value={"sku_count": 5, "shop_count": 2}):
            with TestClient(app) as client:
                r = client.post("/recommend/full", json={"sku_id": "ADI-PROMO-001"})
        assert r.json()["status"] == "complete"

    def test_promote_requires_human_approval_is_true(self):
        with patch("eep.main._recommend_single", return_value=_PROMOTE_RESULT), \
             patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT), \
             patch("eep.main.build_frontend_report", return_value=_REPORT_WITH_CREATIVE), \
             patch("eep.main.report_overview", return_value={"sku_count": 5, "shop_count": 2}):
            with TestClient(app) as client:
                r = client.post("/recommend/full", json={"sku_id": "ADI-PROMO-001"})
        # requires_human_approval is in the ie2_result sub-object
        assert r.json()["ie2_result"]["requires_human_approval"] is True


# ── Non-PROMOTE decisions ──────────────────────────────────────────────────────

class TestNonPromotePipeline:
    def test_hold_decision_campaign_creative_is_none(self):
        """HOLD SKU has no creative in the report → campaign_creative must be None."""
        with patch("eep.main._recommend_single", return_value=_HOLD_RESULT), \
             patch("eep.main.prepare_ie2_request", return_value={
                 **_VALID_IE2_REQUEST_DICT,
                 "sku_id": "ADI-HOLD-001",
                 "product_name": "Adidas Hold Product",
             }), \
             patch("eep.main.build_frontend_report", return_value=_REPORT_WITHOUT_CREATIVE), \
             patch("eep.main.report_overview", return_value={"sku_count": 5, "shop_count": 2}):
            with TestClient(app) as client:
                r = client.post("/recommend/full", json={"sku_id": "ADI-HOLD-001"})
        body = r.json()
        assert r.status_code == 200
        assert body["campaign_creative"] is None
        assert body["ie2_result"]["recommendation"] == "HOLD"

    def test_promote_with_no_creative_in_report_returns_none(self):
        """PROMOTE decision but no creative in report → campaign_creative is None, not an error."""
        with patch("eep.main._recommend_single", return_value=_PROMOTE_RESULT), \
             patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT), \
             patch("eep.main.build_frontend_report", return_value=_REPORT_WITHOUT_CREATIVE), \
             patch("eep.main.report_overview", return_value={"sku_count": 5, "shop_count": 2}):
            with TestClient(app) as client:
                r = client.post("/recommend/full", json={"sku_id": "ADI-PROMO-001"})
        body = r.json()
        assert r.status_code == 200
        assert body["campaign_creative"] is None
        # ie2_result should still have the PROMOTE recommendation
        assert body["ie2_result"]["recommendation"] == "PROMOTE"


# ── Response shape invariants ─────────────────────────────────────────────────

class TestFullResponseShape:
    @pytest.fixture(autouse=True)
    def _patches(self):
        with patch("eep.main._recommend_single", return_value=_PROMOTE_RESULT), \
             patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT), \
             patch("eep.main.build_frontend_report", return_value=_REPORT_WITH_CREATIVE), \
             patch("eep.main.report_overview", return_value={"sku_count": 5, "shop_count": 2}):
            with TestClient(app) as c:
                self._response = c.post("/recommend/full", json={"sku_id": "ADI-PROMO-001"})

    def test_response_has_sku_id(self):
        assert "sku_id" in self._response.json()

    def test_response_has_ie2_result(self):
        body = self._response.json()
        assert "ie2_result" in body
        ie2 = body["ie2_result"]
        assert "recommendation" in ie2
        assert "confidence" in ie2

    def test_response_has_campaign_creative_key(self):
        assert "campaign_creative" in self._response.json()

    def test_response_has_status_key(self):
        assert "status" in self._response.json()
