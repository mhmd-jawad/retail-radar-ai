"""
Unit tests for the ad promotion / pricing directive analyzer
(stylepulse/analyzers/promotions.py).

All tests are offline. datetime.now() is patched so seasonal multipliers
are deterministic regardless of when the suite runs.

Month constants used:
  month=5 (May)  → seasonal_mult=1.15 for "other" category  (triggers PROMOTE)
  month=1 (Jan)  → seasonal_mult=0.70 for "other" category  (below PROMOTE threshold)

Run:
    pytest tests/unit/test_promotions_analyzer.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stylepulse.analyzers import promotions


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
def month_may(monkeypatch):
    """Patch promotions.datetime so current_month=5 (seasonal_mult=1.15)."""
    mock_dt = MagicMock()
    mock_dt.now.return_value.month = 5
    monkeypatch.setattr("stylepulse.analyzers.promotions.datetime", mock_dt)


@pytest.fixture
def month_january(monkeypatch):
    """Patch promotions.datetime so current_month=1 (seasonal_mult=0.70)."""
    mock_dt = MagicMock()
    mock_dt.now.return_value.month = 1
    monkeypatch.setattr("stylepulse.analyzers.promotions.datetime", mock_dt)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _product(sku_id, brand="Nike", name="Test Product", category="other", retail_price=100.0):
    return {
        "sku_id": sku_id,
        "brand": brand,
        "product_name": name,
        "system_category": category,
        "retail_price_usd": retail_price,
    }


def _inv_sku(
    sku_id,
    dos=50,
    dos_status="healthy",
    margin_pct=45.0,
    current_stock=100,
    value_at_cost_usd=5_000.0,
):
    return {
        "sku_id": sku_id,
        "days_of_supply": dos,
        "dos_status": dos_status,
        "margin_pct": margin_pct,
        "current_stock": current_stock,
        "value_at_cost_usd": value_at_cost_usd,
    }


def _comp_sku(
    sku_id,
    position="at_market",
    competitors_oos=0,
    num_competitors=3,
    price_gap_pct=0,
):
    return {
        "sku_id": sku_id,
        "position": position,
        "competitors_out_of_stock": competitors_oos,
        "num_competitors": num_competitors,
        "price_gap_pct": price_gap_pct,
    }


def _analyze(
    sku_id="SKU-1",
    dos=50,
    dos_status="healthy",
    margin=45.0,
    position="at_market",
    current_stock=100,
    category="other",
    pricing_power_skus=None,
    cash_tight=False,
    critical_stockout=0,
    underpriced=0,
    value_at_cost_usd=5_000.0,
):
    """Run promotions.analyze() with a single SKU and return the result."""
    product = _product(sku_id, category=category)
    inv_sku = _inv_sku(sku_id, dos=dos, dos_status=dos_status, margin_pct=margin,
                       current_stock=current_stock, value_at_cost_usd=value_at_cost_usd)
    comp_sku = _comp_sku(sku_id, position=position)

    opportunities = [{"sku_id": s, "type": "pricing_power"} for s in (pricing_power_skus or [])]

    inventory_results = {
        "sku_analysis": [inv_sku],
        "metrics": {"critical_stockout_skus": critical_stockout},
    }
    competitor_results = {
        "sku_positioning": [comp_sku],
        "opportunities": opportunities,
        "market_overview": {"products_underpriced": underpriced},
    }
    if cash_tight:
        financial_results = {
            "alerts": [{"type": "cash_runway_critical", "severity": "high", "message": "Critical runway"}]
        }
    else:
        financial_results = {"alerts": []}

    return promotions.analyze([product], inventory_results, competitor_results, financial_results)


# ── CLEARANCE ──────────────────────────────────────────────────────────────────

class TestClearance:
    def test_dead_dos_status_routes_to_clearance(self, month_january):
        result = _analyze(dos=200, dos_status="dead", margin=20)
        assert len(result["clearance"]) == 1
        assert result["clearance"][0]["sku_id"] == "SKU-1"

    def test_high_dos_and_low_margin_routes_to_clearance(self, month_january):
        # dos > DOS_DEAD(180) AND margin < MARGIN_FLOOR(35)
        result = _analyze(dos=200, dos_status="excess", margin=20)
        assert len(result["clearance"]) == 1

    def test_clearance_discount_is_always_50_pct(self, month_january):
        result = _analyze(dos=200, dos_status="dead", margin=20)
        assert result["clearance"][0]["recommended_discount_pct"] == 50

    def test_clearance_priority_immediate_when_cash_tight(self, month_january):
        result = _analyze(dos=200, dos_status="dead", margin=20, cash_tight=True)
        assert result["clearance"][0]["priority"] == "immediate"

    def test_clearance_priority_this_week_when_not_cash_tight(self, month_january):
        result = _analyze(dos=200, dos_status="dead", margin=20, cash_tight=False)
        assert result["clearance"][0]["priority"] == "this_week"

    def test_clearance_not_triggered_for_healthy_dos_good_margin(self, month_january):
        result = _analyze(dos=50, dos_status="healthy", margin=45)
        assert len(result["clearance"]) == 0

    def test_clearance_value_at_cost_included(self, month_january):
        result = _analyze(dos=200, dos_status="dead", margin=20, value_at_cost_usd=3_000.0)
        assert result["clearance"][0]["value_at_cost_usd"] == 3_000.0


# ── MARKDOWN ──────────────────────────────────────────────────────────────────

class TestMarkdown:
    def test_light_markdown_for_dos_90_to_120(self, month_january):
        # DOS in [90, 120) → light_markdown, 15%
        result = _analyze(dos=100, dos_status="excess", margin=40)
        assert len(result["markdown"]) == 1
        md = result["markdown"][0]
        assert md["recommended_discount_pct"] == 15
        assert md["markdown_tier"] == "light_markdown"

    def test_moderate_markdown_for_dos_120_to_150(self, month_january):
        result = _analyze(dos=130, dos_status="excess", margin=40)
        assert len(result["markdown"]) == 1
        md = result["markdown"][0]
        assert md["recommended_discount_pct"] == 25
        assert md["markdown_tier"] == "moderate_markdown"

    def test_deep_markdown_for_dos_150_to_180(self, month_january):
        result = _analyze(dos=160, dos_status="excess", margin=40)
        assert len(result["markdown"]) == 1
        md = result["markdown"][0]
        assert md["recommended_discount_pct"] == 35
        assert md["markdown_tier"] == "deep_markdown"

    def test_markdown_priority_this_week_for_dos_above_150(self, month_january):
        result = _analyze(dos=160, dos_status="excess", margin=40)
        assert result["markdown"][0]["priority"] == "this_week"

    def test_markdown_priority_this_month_for_dos_below_150(self, month_january):
        result = _analyze(dos=100, dos_status="excess", margin=40)
        assert result["markdown"][0]["priority"] == "this_month"

    def test_markdown_not_triggered_below_dos_90(self, month_january):
        result = _analyze(dos=60, dos_status="healthy", margin=40)
        assert len(result["markdown"]) == 0

    def test_markdown_not_triggered_when_margin_at_or_below_critical(self, month_january):
        # margin <= MARGIN_CRITICAL(25) → markdown condition fails
        result = _analyze(dos=100, dos_status="excess", margin=25)
        assert len(result["markdown"]) == 0

    def test_pricing_power_sku_not_marked_down(self, month_january):
        # SKU in pricing_power → markdown skipped, routed to hold
        result = _analyze(
            sku_id="SKU-PP",
            dos=100,
            dos_status="excess",
            margin=40,
            pricing_power_skus=["SKU-PP"],
        )
        assert len(result["markdown"]) == 0
        assert any(h["sku_id"] == "SKU-PP" for h in result["hold_pricing"])

    def test_markdown_post_discount_margin_recorded(self, month_january):
        result = _analyze(dos=100, dos_status="excess", margin=40.0)
        md = result["markdown"][0]
        # post_markdown_margin = margin - (discount_pct * margin/100) = 40 - (15 * 0.4) = 40 - 6 = 34
        assert md["post_markdown_margin_pct"] == pytest.approx(34.0, abs=0.1)


# ── HOLD PRICING ──────────────────────────────────────────────────────────────

class TestHoldPricing:
    def test_hold_for_pricing_power_sku(self, month_january):
        result = _analyze(
            sku_id="SKU-H",
            dos=80,
            dos_status="healthy",
            margin=45.0,
            pricing_power_skus=["SKU-H"],
        )
        assert any(h["sku_id"] == "SKU-H" for h in result["hold_pricing"])
        assert len(result["markdown"]) == 0

    def test_hold_for_healthy_dos_and_margin_at_market(self, month_january):
        result = _analyze(
            dos=60,
            dos_status="healthy",
            margin=50.0,
            position="at_market",
        )
        assert len(result["hold_pricing"]) == 1
        assert result["hold_pricing"][0]["sku_id"] == "SKU-1"

    def test_hold_for_below_market_position(self, month_january):
        result = _analyze(
            dos=60,
            dos_status="healthy",
            margin=50.0,
            position="below_market",
        )
        assert len(result["hold_pricing"]) == 1

    def test_no_hold_when_position_is_premium(self, month_january):
        # premium position + margin below MARGIN_HEALTHY (45) → fails HOLD condition
        result = _analyze(
            dos=60,
            dos_status="healthy",
            margin=40.0,
            position="premium",
        )
        assert len(result["hold_pricing"]) == 0

    def test_no_hold_when_margin_below_healthy(self, month_january):
        # margin < MARGIN_HEALTHY(45) → HOLD condition fails (not pricing_power either)
        result = _analyze(
            dos=60,
            dos_status="healthy",
            margin=40.0,
            position="at_market",
        )
        assert len(result["hold_pricing"]) == 0

    def test_hold_reason_mentions_pricing_power(self, month_january):
        result = _analyze(
            sku_id="SKU-PP",
            dos=80,
            dos_status="healthy",
            margin=45.0,
            pricing_power_skus=["SKU-PP"],
        )
        hold = result["hold_pricing"][0]
        assert "pricing power" in hold["reason"].lower() or "out of stock" in hold["reason"].lower()


# ── PROMOTE ────────────────────────────────────────────────────────────────────

class TestPromote:
    def test_promote_when_seasonal_opportunity_and_good_dos_margin(self, month_may):
        # dos=50 (avoids markdown), margin=40 (avoids hold), month=5 (seasonal=1.15)
        result = _analyze(
            dos=50,
            dos_status="healthy",
            margin=40.0,
            position="premium",
        )
        assert len(result["promote"]) == 1
        assert result["promote"][0]["sku_id"] == "SKU-1"

    def test_feature_placement_when_margin_above_healthy(self, month_may):
        # margin > MARGIN_HEALTHY(45) → feature_placement
        result = _analyze(dos=50, dos_status="healthy", margin=50.0, position="premium")
        assert result["promote"][0]["recommended_action"] == "feature_placement"

    def test_bundle_deal_when_margin_at_floor(self, month_may):
        # margin == MARGIN_FLOOR(35) → bundle_deal (not > MARGIN_HEALTHY)
        result = _analyze(dos=50, dos_status="healthy", margin=35.0, position="premium")
        assert result["promote"][0]["recommended_action"] == "bundle_deal"

    def test_bundle_deal_when_margin_between_floor_and_healthy(self, month_may):
        # MARGIN_FLOOR(35) <= margin < MARGIN_HEALTHY(45) → bundle_deal
        result = _analyze(dos=50, dos_status="healthy", margin=40.0, position="premium")
        assert result["promote"][0]["recommended_action"] == "bundle_deal"

    def test_no_promote_when_dos_too_low(self, month_may):
        # dos <= 20 → PROMOTE condition (dos > 20) fails
        result = _analyze(dos=15, dos_status="healthy", margin=40.0, position="premium")
        assert len(result["promote"]) == 0

    def test_no_promote_in_low_season_month(self, month_january):
        # month=1, seasonal_mult=0.70 < 1.10 → never promotes
        result = _analyze(dos=50, dos_status="healthy", margin=40.0, position="premium")
        assert len(result["promote"]) == 0

    def test_no_promote_when_margin_below_floor(self, month_may):
        # margin < MARGIN_FLOOR(35) → PROMOTE condition fails
        result = _analyze(dos=50, dos_status="healthy", margin=20.0, position="premium")
        assert len(result["promote"]) == 0

    def test_promote_seasonal_multiplier_stored(self, month_may):
        result = _analyze(dos=50, dos_status="healthy", margin=40.0, position="premium")
        assert result["promote"][0]["seasonal_multiplier"] == pytest.approx(1.15)

    def test_promote_priority_is_this_week(self, month_may):
        result = _analyze(dos=50, dos_status="healthy", margin=40.0, position="premium")
        assert result["promote"][0]["priority"] == "this_week"


# ── Summary counts ────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_counts_match_list_lengths(self, month_january):
        # Two products: one clearance, one markdown
        products = [_product("S1"), _product("S2")]
        inv_skus = [
            _inv_sku("S1", dos=200, dos_status="dead", margin_pct=20),
            _inv_sku("S2", dos=100, dos_status="excess", margin_pct=40),
        ]
        comp_skus = [_comp_sku("S1"), _comp_sku("S2")]

        result = promotions.analyze(
            products,
            {"sku_analysis": inv_skus, "metrics": {"critical_stockout_skus": 0}},
            {"sku_positioning": comp_skus, "opportunities": [], "market_overview": {"products_underpriced": 0}},
            {"alerts": []},
        )
        s = result["summary"]
        assert s["clearance_count"] == len(result["clearance"])
        assert s["markdown_count"] == len(result["markdown"])
        assert s["hold_count"] == len(result["hold_pricing"])
        assert s["promote_count"] == len(result["promote"])

    def test_total_clearance_value_is_sum_of_clearance_skus(self, month_january):
        result = _analyze(dos=200, dos_status="dead", margin=20, value_at_cost_usd=4_000.0)
        assert result["summary"]["total_clearance_value_usd"] == pytest.approx(4_000.0)

    def test_result_contains_all_required_keys(self, month_january):
        result = _analyze()
        for key in ("hold_pricing", "promote", "markdown", "clearance",
                    "seasonal_actions", "directives", "summary"):
            assert key in result


# ── Directives ────────────────────────────────────────────────────────────────

class TestDirectives:
    def test_clearance_directive_included_when_clearance_exists(self, month_january):
        result = _analyze(dos=200, dos_status="dead", margin=20)
        categories = [d["category"] for d in result["directives"]]
        assert "inventory" in categories

    def test_financial_directive_is_first_when_critical_alert(self, month_january):
        product = _product("S1")
        inv_sku = _inv_sku("S1", dos=200, dos_status="dead", margin_pct=20)
        comp_sku = _comp_sku("S1")
        financial_results = {
            "alerts": [{"type": "cash_runway_critical", "severity": "high", "message": "Only 1 month runway!"}]
        }
        result = promotions.analyze(
            [product],
            {"sku_analysis": [inv_sku], "metrics": {"critical_stockout_skus": 0}},
            {"sku_positioning": [comp_sku], "opportunities": [], "market_overview": {"products_underpriced": 0}},
            financial_results,
        )
        assert result["directives"][0]["category"] == "financial"

    def test_directives_is_list(self, month_january):
        result = _analyze()
        assert isinstance(result["directives"], list)

    def test_critical_stockout_directive_included(self, month_january):
        result = _analyze(critical_stockout=3)
        categories = [d["category"] for d in result["directives"]]
        assert "supply_chain" in categories

    def test_markdown_directive_included_when_markdowns_exist(self, month_january):
        result = _analyze(dos=100, dos_status="excess", margin=40)
        categories = [d["category"] for d in result["directives"]]
        assert "pricing" in categories


# ── Seasonal actions ──────────────────────────────────────────────────────────

class TestSeasonalActions:
    def test_seasonal_actions_returned_for_next_three_months(self, month_may):
        result = _analyze()
        # month=5 → next 3 months are 6, 7, 8 → 3 entries (no Lebanon events for month 5)
        assert len(result["seasonal_actions"]) == 3

    def test_peak_demand_in_august_when_running_in_may(self, month_may):
        result = _analyze()
        signals = {a["month"]: a["signal"] for a in result["seasonal_actions"]}
        assert signals.get("August") == "peak_demand"

    def test_slow_period_in_february_when_running_in_january(self, month_january):
        result = _analyze()
        signals = {a["month"]: a["signal"] for a in result["seasonal_actions"]}
        assert signals.get("February") == "slow_period"
