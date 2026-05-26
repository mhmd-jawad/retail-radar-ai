"""
Integration tests for the EEP service routes.

Uses FastAPI TestClient with mocked IE2 and database calls.
No real PostgreSQL, no real CatBoost model inference.

Run:
    pytest tests/integration/test_eep_pipeline.py -v
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from eep.main import app
from services.decision_intelligence.schemas import RecommendationResult, SHAPFeature

# ── Shared fixtures ────────────────────────────────────────────────────────────

_FAKE_RESULT = RecommendationResult(
    sku_id="SKU-TEST-001",
    product_name="Test Product",
    recommendation="HOLD",
    confidence=0.85,
    explanation="Healthy inventory, no action required.",
    shap_top5=[
        SHAPFeature(
            feature_name="days_of_supply",
            feature_value=60.0,
            shap_value=0.30,
            direction="decreases_probability",
            explanation="60 days of supply — well stocked.",
        )
    ],
    rule_override=None,
    fallback_used=False,
    model_version="test_v1",
    processing_time_ms=12,
    requires_human_approval=True,
    generated_at=datetime(2026, 4, 27, 10, 0, 0),
)

_VALID_IE2_REQUEST_DICT = {
    "sku_id": "SKU-TEST-001",
    "product_name": "Test Product",
    "brand": "Adidas",
    "category": "footwear",
    "retail_price_usd": 100.0,
    "cost_price_usd": 55.0,
    "current_stock": 50,
    "initial_stock": 100,
    "days_since_launch": 180,
    "days_since_last_discount": 60,
    "days_at_current_price": 30,
    "competitor_signals": None,
}


@pytest.fixture(scope="module")
def client():
    """TestClient with all external calls mocked out."""
    with (
        patch("eep.main._recommend_single", return_value=_FAKE_RESULT) as mock_ie2,
        patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT),
        patch("eep.main.build_frontend_report", return_value={
            "metadata": {"generated_at": "2026-04-27T10:00:00"},
            "inventory": {"metrics": {}},
            "competitor": {"market_overview": {}},
            "promotions": {"summary": {}, "promote": []},
            "financial": {
                "cashflow_health": {"cash_runway_months": 6.0},
                "balance_sheet_health": {"inventory_pct_of_assets": 0.30},
                "profitability": {"blended_margin_pct": 45.0},
            },
        }),
        patch("eep.main.report_overview", return_value={"sku_count": 10, "shop_count": 3}),
    ):
        with TestClient(app) as c:
            c._mock_ie2 = mock_ie2
            yield c


# ── Health endpoint ────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_has_status_healthy(self, client):
        r = client.get("/health")
        assert r.json()["status"] == "healthy"

    def test_health_has_service_name(self, client):
        r = client.get("/health")
        assert r.json()["service"] == "eep"


class TestMetricsEndpoint:
    def test_metrics_returns_prometheus_text(self, client):
        client.get("/health")
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "eep_http_requests_total" in r.text


# ── Single recommend ───────────────────────────────────────────────────────────

class TestSingleRecommend:
    def test_recommend_returns_200(self, client):
        r = client.post("/recommend/SKU-TEST-001", json={})
        assert r.status_code == 200

    def test_recommend_response_has_recommendation_key(self, client):
        r = client.post("/recommend/SKU-TEST-001", json={})
        body = r.json()
        assert "recommendation" in body

    def test_recommend_response_has_confidence(self, client):
        r = client.post("/recommend/SKU-TEST-001", json={})
        body = r.json()
        assert "confidence" in body
        assert 0.0 <= body["confidence"] <= 1.0

    def test_recommend_response_has_sku_id(self, client):
        r = client.post("/recommend/SKU-TEST-001", json={})
        body = r.json()
        assert "sku_id" in body
        assert body["sku_id"] == "SKU-TEST-001"

    def test_recommend_response_recommendation_is_valid(self, client):
        r = client.post("/recommend/SKU-TEST-001", json={})
        assert r.json()["recommendation"] in ("HOLD", "MARKDOWN", "PROMOTE", "CLEAR")

    def test_recommend_with_empty_body(self, client):
        """Body is optional — route must accept an empty POST."""
        r = client.post("/recommend/SKU-TEST-001")
        assert r.status_code == 200

    def test_recommend_passes_sku_id_to_prepare(self, client):
        """prepare_ie2_request must be called with the path sku_id."""
        with patch("eep.main.prepare_ie2_request", return_value=_VALID_IE2_REQUEST_DICT) as mock_prepare:
            client.post("/recommend/SPECIFIC-SKU", json={})
            mock_prepare.assert_called_once()
            assert mock_prepare.call_args[0][0] == "SPECIFIC-SKU"

    def test_recommend_strips_competitor_match_metadata_before_ie2(self, client):
        captured = {}
        request_with_metadata = {
            **_VALID_IE2_REQUEST_DICT,
            "competitor_signals": {
                "sku_id": "SKU-TEST-001",
                "competitor_min_price": 90.0,
                "competitor_avg_price": 95.0,
                "price_gap_pct": 0.10,
                "competitors_on_sale_count": 1,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 2,
                "cheapest_competitor_name": "Competitor",
                "price_trend_direction": "STABLE",
                "data_freshness_hours": 2.0,
                "confidence_score": 0.95,
                "fallback_used": False,
                "fallback_reason": None,
                "timestamp": "2026-04-27T10:00:00",
                "match_type": "similar_product",
                "match_score": 0.72,
            },
        }

        def fake_recommend(request_model):
            captured["competitor_signals"] = request_model.competitor_signals
            return _FAKE_RESULT

        with (
            patch("eep.main.prepare_ie2_request", return_value=request_with_metadata),
            patch("eep.main._recommend_single", side_effect=fake_recommend),
        ):
            r = client.post("/recommend/SKU-TEST-001", json={})

        assert r.status_code == 200
        assert captured["competitor_signals"] is not None
        assert not hasattr(captured["competitor_signals"], "match_type")

    def test_recommend_adds_provided_signal_metadata_for_audit(self, client):
        captured = {}
        request_with_provided_signals = {
            **_VALID_IE2_REQUEST_DICT,
            "competitor_signals": {
                "sku_id": "SKU-TEST-001",
                "competitor_min_price": 90.0,
                "competitor_avg_price": 95.0,
                "price_gap_pct": 0.10,
                "competitors_on_sale_count": 1,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 2,
                "cheapest_competitor_name": "Competitor",
                "price_trend_direction": "STABLE",
                "data_freshness_hours": 2.0,
                "confidence_score": 0.95,
                "fallback_used": False,
                "fallback_reason": None,
                "timestamp": "2026-04-27T10:00:00",
            },
        }

        def fake_observe(competitor_signals):
            captured["match_type"] = competitor_signals["match_type"]

        with (
            patch("eep.main.prepare_ie2_request", wraps=__import__("eep.frontend_bridge", fromlist=["prepare_ie2_request"]).prepare_ie2_request),
            patch("eep.main.observe_competitor_match", side_effect=fake_observe),
            patch("eep.main._recommend_single", return_value=_FAKE_RESULT),
        ):
            r = client.post("/recommend/SKU-TEST-001", json=request_with_provided_signals)

        assert r.status_code == 200
        assert captured["match_type"] == "provided_signals"


# ── Batch recommend ────────────────────────────────────────────────────────────

class TestBatchRecommend:
    def test_batch_returns_200(self, client):
        payload = {"items": [{"sku_id": "SKU-TEST-001"}, {"sku_id": "SKU-TEST-002"}]}
        r = client.post("/recommend/batch", json=payload)
        assert r.status_code == 200

    def test_batch_response_is_list(self, client):
        payload = {"items": [{"sku_id": "SKU-TEST-001"}, {"sku_id": "SKU-TEST-002"}]}
        r = client.post("/recommend/batch", json=payload)
        assert isinstance(r.json(), list)

    def test_batch_response_length_matches_input(self, client):
        payload = {"items": [{"sku_id": "SKU-A"}, {"sku_id": "SKU-B"}, {"sku_id": "SKU-C"}]}
        r = client.post("/recommend/batch", json=payload)
        assert len(r.json()) == 3

    def test_batch_empty_items_returns_400(self, client):
        r = client.post("/recommend/batch", json={"items": []})
        assert r.status_code == 400

    def test_batch_missing_items_key_returns_400(self, client):
        r = client.post("/recommend/batch", json={"sku_ids": ["SKU-A"]})
        assert r.status_code == 400

    def test_batch_item_missing_sku_id_returns_400(self, client):
        r = client.post("/recommend/batch", json={"items": [{"name": "no-sku-id"}]})
        assert r.status_code == 400


# ── Full recommendation ────────────────────────────────────────────────────────

class TestFullRecommendation:
    def test_full_returns_200(self, client):
        r = client.post("/recommend/full", json={"sku_id": "SKU-TEST-001"})
        assert r.status_code == 200

    def test_full_response_has_ie2_result(self, client):
        r = client.post("/recommend/full", json={"sku_id": "SKU-TEST-001"})
        body = r.json()
        assert "ie2_result" in body
        assert body["ie2_result"]["recommendation"] in ("HOLD", "MARKDOWN", "PROMOTE", "CLEAR")

    def test_full_response_has_status_complete(self, client):
        r = client.post("/recommend/full", json={"sku_id": "SKU-TEST-001"})
        assert r.json()["status"] == "complete"

    def test_full_response_has_sku_id(self, client):
        r = client.post("/recommend/full", json={"sku_id": "SKU-TEST-001"})
        assert r.json()["sku_id"] == "SKU-TEST-001"

    def test_full_missing_sku_id_returns_400(self, client):
        r = client.post("/recommend/full", json={})
        assert r.status_code == 400

    def test_full_campaign_creative_is_none_when_no_report_match(self, client):
        """Report has no PROMOTE entry for this SKU → campaign_creative is None."""
        r = client.post("/recommend/full", json={"sku_id": "SKU-NO-CREATIVE"})
        assert r.json()["campaign_creative"] is None


# ── Dashboard summary ──────────────────────────────────────────────────────────

class TestDashboardSummary:
    def test_dashboard_returns_200(self, client):
        r = client.get("/dashboard/summary")
        assert r.status_code == 200

    def test_dashboard_has_inventory_key(self, client):
        r = client.get("/dashboard/summary")
        assert "inventory" in r.json()

    def test_dashboard_has_financial_key(self, client):
        r = client.get("/dashboard/summary")
        assert "financial" in r.json()
