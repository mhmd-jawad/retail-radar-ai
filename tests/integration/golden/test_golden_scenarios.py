"""
Golden scenario integration tests for IE2 Decision Intelligence.

These 6 scenarios represent the canonical real-world cases that the
recommendation engine must handle correctly. Tests are deterministic since
the v1 engine is rules-based (no stochastic CatBoost yet).

Run:
    pytest tests/integration/golden/ -v
"""

import pytest
from services.decision_intelligence.rules.engine import run_rules


# ── Helper ─────────────────────────────────────────────────────────────────────

def base_features(**overrides) -> dict:
    defaults = {
        "sku_id": "GOLDEN-001",
        "category": "footwear",
        "brand": "Adidas",
        "total_qty": 50,
        "days_of_supply": 60,
        "current_margin_pct": 45.0,
        "retail_price_usd": 100.0,
        "cost_price_usd": 55.0,
        "days_since_last_discount": 45,
        "days_since_launch": 90,
        "season_sell_through_pct": 0.40,
        "seasonality_score": 1.0,
        "event_proximity_score": 0.0,
        "price_gap_pct": 0.0,
        "competitors_on_sale": 0,
        "competitors_out_of_stock": 0,
        "suggested_discount_pct": 15,
    }
    defaults.update(overrides)
    return defaults


# ── Scenario 1: Healthy SKU — no action needed ────────────────────────────────

class TestScenario1HealthySku:
    """Healthy SKU: 60 DOS, 45% margin, 40% sell-through — expect HOLD."""

    def test_no_hard_override(self):
        f = base_features()
        result = run_rules(f)
        assert result["hard_override"] is False

    def test_no_blocked_actions(self):
        f = base_features()
        result = run_rules(f)
        assert result["blocked_actions"] == []

    def test_no_forced_action(self):
        f = base_features()
        result = run_rules(f)
        assert result["forced_action"] is None


# ── Scenario 2: Dead stock clear ──────────────────────────────────────────────

class TestScenario2DeadStock:
    """Dead stock: 150 DOS, 8% sell-through, 80 days since launch — expect CLEAR."""

    def test_forces_clear(self):
        f = base_features(
            days_of_supply=150,
            season_sell_through_pct=0.08,
            days_since_launch=80,
        )
        result = run_rules(f)
        assert result["hard_override"] is True
        assert result["forced_action"] == "CLEAR"

    def test_override_is_absolute(self):
        f = base_features(
            days_of_supply=150,
            season_sell_through_pct=0.08,
            days_since_launch=80,
        )
        result = run_rules(f)
        rule = result["rules_fired"][0]
        assert rule["override_strength"] == "absolute"


# ── Scenario 3: Low stock — protect from markdown ────────────────────────────

class TestScenario3LowStock:
    """Low stock: 12 units, 8 DOS — expect HOLD forced, MARKDOWN blocked."""

    def test_markdown_is_blocked(self):
        f = base_features(total_qty=12, days_of_supply=8)
        result = run_rules(f)
        assert "MARKDOWN" in result["blocked_actions"]

    def test_hold_is_forced(self):
        f = base_features(total_qty=12, days_of_supply=8)
        result = run_rules(f)
        assert result["forced_action"] == "HOLD"

    def test_not_absolute_strength(self):
        """Low stock is a strong rule, not absolute — CLEAR can still override it."""
        f = base_features(total_qty=12, days_of_supply=8)
        result = run_rules(f)
        if result["rules_fired"]:
            fired_rule = next(
                (r for r in result["rules_fired"] if r["rule_id"] == "LOW_STOCK_PROTECTION"),
                None,
            )
            if fired_rule:
                assert fired_rule["override_strength"] == "strong"


# ── Scenario 4: Margin below floor — block markdown ──────────────────────────

class TestScenario4MarginFloor:
    """Thin margin: 28% margin — MARKDOWN must be blocked."""

    def test_markdown_blocked_on_low_margin(self):
        f = base_features(current_margin_pct=28.0)
        result = run_rules(f)
        assert "MARKDOWN" in result["blocked_actions"]


# ── Scenario 5: Recent discount — too soon to markdown again ─────────────────

class TestScenario5RecentDiscount:
    """Discounted 7 days ago — MARKDOWN must be blocked."""

    def test_markdown_blocked_after_recent_discount(self):
        f = base_features(days_since_last_discount=7)
        result = run_rules(f)
        assert "MARKDOWN" in result["blocked_actions"]


# ── Scenario 6: Event nudge — promote during Eid season ──────────────────────

class TestScenario6EventNudge:
    """Calendar event nudge — soft, never forces a hard override."""

    def test_nudge_does_not_force_hard_override(self):
        """Calendar nudge is always soft — never produces a hard override."""
        f = base_features(event_proximity_score=0.9)
        result = run_rules(f)
        # Even if the nudge fires, it must never force a hard override
        # (soft rule cannot force an action)
        fired_soft = [r for r in result["rules_fired"]
                      if r["rule_id"] == "CALENDAR_EVENT_NUDGE"]
        for r in fired_soft:
            assert r["override_strength"] == "soft"
            assert r.get("action") is None

    def test_nudge_rule_is_always_soft(self):
        from services.decision_intelligence.rules.engine import rule_calendar_event_nudge
        f = base_features()
        result = rule_calendar_event_nudge(f)
        assert result["override_strength"] == "soft"
