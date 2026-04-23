"""
Unit tests for the IE2 hard rules engine.

 Covers all 6 rules:
  - rule_dead_stock_clear
  - rule_low_stock_protection
  - rule_margin_floor_protection
  - rule_recent_discount_protection
  - rule_calendar_event_nudge
  - rule_obvious_markdown_nudge
  - run_rules orchestration (priority / blocking / nudge behaviour)
"""

import pytest
from services.decision_intelligence.rules.engine import (
    rule_dead_stock_clear,
    rule_low_stock_protection,
    rule_margin_floor_protection,
    rule_recent_discount_protection,
    rule_calendar_event_nudge,
    rule_obvious_markdown_nudge,
    run_rules,
)

# ── Shared base feature dict ───────────────────────────────────────────────────

def base() -> dict:
    return {
        "sku_id": "TEST-001",
        "category": "footwear",
        "brand": "Adidas",
        "total_qty": 50,
        "days_of_supply": 60,
        "current_margin_pct": 45.0,
        "days_since_last_discount": 30,
        "days_since_launch": 90,
        "season_sell_through_pct": 0.35,
        "retail_price_usd": 100.0,
        "cost_price_usd": 55.0,
        "seasonality_score": 1.0,
        "event_proximity_score": 0.0,
        "suggested_discount_pct": 15,
    }


# ── rule_dead_stock_clear ──────────────────────────────────────────────────────

class TestDeadStockClear:
    def test_fires_when_all_conditions_met(self):
        f = base()
        f.update(days_of_supply=130, season_sell_through_pct=0.10, days_since_launch=70)
        result = rule_dead_stock_clear(f)
        assert result["fired"] is True
        assert result["action"] == "CLEAR"
        assert result["override_strength"] == "absolute"

    def test_does_not_fire_when_dos_below_threshold(self):
        f = base()
        f.update(days_of_supply=100, season_sell_through_pct=0.10, days_since_launch=70)
        result = rule_dead_stock_clear(f)
        assert result["fired"] is False

    def test_boundary_exactly_120_dos(self):
        f = base()
        f.update(days_of_supply=120, season_sell_through_pct=0.10, days_since_launch=70)
        # DOS must be strictly > 120
        result = rule_dead_stock_clear(f)
        assert result["fired"] is False

    def test_does_not_fire_when_sell_through_high(self):
        f = base()
        f.update(days_of_supply=130, season_sell_through_pct=0.40, days_since_launch=70)
        result = rule_dead_stock_clear(f)
        assert result["fired"] is False


# ── rule_low_stock_protection ─────────────────────────────────────────────────

class TestLowStockProtection:
    def test_fires_on_low_qty(self):
        f = base()
        f["total_qty"] = 10
        result = rule_low_stock_protection(f)
        assert result["fired"] is True
        assert result["action"] == "HOLD"
        assert "MARKDOWN" in result.get("blocks", [])

    def test_fires_on_low_dos(self):
        f = base()
        f["days_of_supply"] = 5
        result = rule_low_stock_protection(f)
        assert result["fired"] is True

    def test_does_not_fire_when_stock_adequate(self):
        f = base()  # qty=50, dos=60 — both above thresholds
        result = rule_low_stock_protection(f)
        assert result["fired"] is False

    def test_boundary_qty_exactly_15(self):
        f = base()
        f["total_qty"] = 15
        # qty < 15 is the condition, so 15 should NOT fire
        result = rule_low_stock_protection(f)
        assert result["fired"] is False


# ── rule_margin_floor_protection ──────────────────────────────────────────────

class TestMarginFloorProtection:
    def test_fires_when_margin_below_floor(self):
        f = base()
        f["current_margin_pct"] = 30.0
        result = rule_margin_floor_protection(f)
        assert result["fired"] is True
        assert "MARKDOWN" in result.get("blocks", [])

    def test_fires_when_post_markdown_margin_below_floor(self):
        f = base()
        f.update(current_margin_pct=40.0, retail_price_usd=100.0,
                 cost_price_usd=65.0, suggested_discount_pct=15)
        # post-markdown price = 85, margin = (85-65)/85 = 23.5% < 35%
        result = rule_margin_floor_protection(f)
        assert result["fired"] is True

    def test_does_not_fire_when_margin_safe(self):
        f = base()
        f.update(current_margin_pct=50.0, retail_price_usd=100.0,
                 cost_price_usd=40.0, suggested_discount_pct=15)
        # post-markdown = 85, margin = (85-40)/85 = 52.9% > 35%
        result = rule_margin_floor_protection(f)
        assert result["fired"] is False


# ── rule_recent_discount_protection ──────────────────────────────────────────

class TestRecentDiscountProtection:
    def test_fires_when_discount_too_recent(self):
        f = base()
        f["days_since_last_discount"] = 10
        result = rule_recent_discount_protection(f)
        assert result["fired"] is True
        assert "MARKDOWN" in result.get("blocks", [])

    def test_boundary_exactly_21_days(self):
        f = base()
        f["days_since_last_discount"] = 21
        # < 21 is the condition, so 21 should NOT fire
        result = rule_recent_discount_protection(f)
        assert result["fired"] is False

    def test_does_not_fire_when_old_enough(self):
        f = base()
        f["days_since_last_discount"] = 30
        result = rule_recent_discount_protection(f)
        assert result["fired"] is False


# ── rule_calendar_event_nudge ─────────────────────────────────────────────────

class TestCalendarEventNudge:
    def test_nudges_promote_near_event(self):
        # Rule fires based on current month — make features clearly in an event month
        f = base()
        f["seasonality_score"] = 1.3
        result = rule_calendar_event_nudge(f)
        # Rule is month-dependent; just verify return shape is valid
        assert "fired" in result
        assert result.get("override_strength") == "soft"
        if result["fired"]:
            assert "PROMOTE" in result.get("nudge_toward", [])

    def test_soft_rule_never_forces(self):
        f = base()
        result = rule_calendar_event_nudge(f)
        assert result.get("override_strength") == "soft"
        assert result.get("action") is None


# ── run_rules orchestration ───────────────────────────────────────────────────

class TestObviousMarkdownNudge:
    def test_nudges_markdown_when_signals_align(self):
        f = base()
        f.update(
            days_of_supply=70,
            current_margin_pct=46.0,
            price_gap_pct=0.18,
            competitors_on_sale=3,
            days_since_last_discount=35,
            season_sell_through_pct=0.25,
        )
        result = rule_obvious_markdown_nudge(f)
        assert result["fired"] is True
        assert result["override_strength"] == "soft"
        assert "MARKDOWN" in result.get("nudge_toward", [])

    def test_does_not_fire_when_recent_discount_still_active(self):
        f = base()
        f.update(
            days_of_supply=70,
            current_margin_pct=46.0,
            price_gap_pct=0.18,
            competitors_on_sale=3,
            days_since_last_discount=10,
            season_sell_through_pct=0.25,
        )
        result = rule_obvious_markdown_nudge(f)
        assert result["fired"] is False


class TestRunRules:
    def test_absolute_rule_short_circuits(self):
        f = base()
        f.update(days_of_supply=150, season_sell_through_pct=0.05,
                 days_since_launch=80)
        result = run_rules(f)
        assert result["hard_override"] is True
        assert result["forced_action"] == "CLEAR"

    def test_strong_rule_blocks_markdown_and_forces_hold(self):
        f = base()
        f["total_qty"] = 10  # low stock → forced HOLD (strong, not absolute)
        result = run_rules(f)
        assert "MARKDOWN" in result["blocked_actions"]
        assert result["forced_action"] == "HOLD"
        # hard_override=True because a strong rule forced an action
        assert result["hard_override"] is True

    def test_soft_nudge_does_not_force(self):
        f = base()
        f["event_proximity_score"] = 0.9
        result = run_rules(f)
        assert result["hard_override"] is False
        assert "PROMOTE" in result["nudges"]
        assert result["forced_action"] is None

    def test_markdown_soft_nudge_is_included(self):
        f = base()
        f.update(
            days_of_supply=70,
            current_margin_pct=46.0,
            price_gap_pct=0.18,
            competitors_on_sale=3,
            days_since_last_discount=35,
            season_sell_through_pct=0.25,
        )
        result = run_rules(f)
        assert result["hard_override"] is False
        assert "MARKDOWN" in result["nudges"]
        assert result["forced_action"] is None

    def test_healthy_sku_no_rules_fire(self):
        f = base()
        result = run_rules(f)
        assert result["hard_override"] is False
        assert result["forced_action"] is None
        assert result["blocked_actions"] == []
