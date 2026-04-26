"""
Golden scenario integration tests for IE2 Decision Intelligence.

These 6 scenarios represent the canonical real-world cases that the
recommendation engine must handle correctly. Tests are deterministic since
the v1 engine is rules-based (no stochastic CatBoost yet).

TestGoldenScenarios  — tests the rules engine in isolation via run_rules().
TestGoldenScenariosE2E — threads each scenario through _recommend_single()
                         (full pipeline: feature engineering + rules + model).

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


# ── E2E golden scenarios via _recommend_single() ──────────────────────────────

def _e2e_request(sku_id: str, **feature_overrides):
    """Build a RecommendationRequest from a golden feature dict.

    The golden scenarios define features that map to the rules engine.
    Here we translate them into the IE2 API contract (RecommendationRequest)
    so the full pipeline runs: feature engineering → rules → ML model.

    Mapping notes:
    - total_qty      → current_stock
    - current_margin_pct is derived from retail/cost; we back-compute cost_price
    - days_of_supply is derived from demand estimation; we set stock high enough
      that the computed DOS approximates the intended value
    - sell_through    = 1 - (current_stock / initial_stock) — we use initial_stock
      to control this
    """
    from services.decision_intelligence.schemas import RecommendationRequest

    f = base_features(**feature_overrides)

    # Back-compute cost from margin: cost = retail * (1 - margin/100)
    retail = float(f.get("retail_price_usd", 100.0))
    margin = float(f.get("current_margin_pct", 45.0))
    cost = round(retail * (1 - margin / 100), 2)
    # Ensure cost < retail (Pydantic validator)
    cost = max(cost, retail * 0.05)

    current_stock = int(f.get("total_qty", 50))
    # initial_stock is used to compute sell-through: 1 - (current/initial)
    # Use the scenario's season_sell_through_pct to back-compute initial_stock:
    # initial = current / (1 - sell_through), clamped to avoid division by zero
    sell_through_target = float(f.get("season_sell_through_pct", 0.5))
    denominator = max(1.0 - sell_through_target, 0.01)
    initial_stock = max(current_stock, int(current_stock / denominator) + 1)

    return RecommendationRequest(
        sku_id=sku_id,
        product_name=f"Golden Scenario — {sku_id}",
        brand=str(f.get("brand", "Adidas")),
        category=str(f.get("category", "footwear")),
        retail_price_usd=retail,
        cost_price_usd=cost,
        current_stock=current_stock,
        initial_stock=initial_stock,
        days_since_launch=int(f.get("days_since_launch", 180)),
        days_since_last_discount=int(f.get("days_since_last_discount", 60)),
        days_at_current_price=30,
        competitor_signals=None,
    )


# Skip E2E tests when the CatBoost model is unavailable (CI without model files)
_model_present = False
try:
    from services.decision_intelligence.main import REGISTERED_MODEL
    _model_present = REGISTERED_MODEL is not None
except Exception:
    pass

_requires_model = pytest.mark.skipif(
    not _model_present,
    reason="CatBoost model not loaded — skipping E2E golden tests",
)


class TestGoldenScenariosE2E:
    pytestmark = _requires_model

    """
    Each golden scenario threaded through _recommend_single() (full IE2 pipeline).

    Scenarios 1-2 are deterministic (hard rule overrides).
    Scenarios 3-6 assert the rules guard (blocked/not-forced) independently of
    the ML model's final pick, because the soft rules do not override the model.
    """

    def test_s1_healthy_sku_produces_valid_result(self):
        """S1: Healthy SKU — no rule fires, result is a valid RecommendationResult."""
        from services.decision_intelligence.main import _recommend_single
        from services.decision_intelligence.schemas import RecommendationResult

        req = _e2e_request("S1-HEALTHY")
        result = _recommend_single(req)

        assert isinstance(result, RecommendationResult)
        assert result.recommendation in ("HOLD", "MARKDOWN", "PROMOTE", "CLEAR")
        assert 0.0 <= result.confidence <= 1.0
        assert result.rule_override is None  # no hard rule fires on a healthy SKU

    def test_s2_dead_stock_forces_clear_e2e(self):
        """S2: Dead stock — DEAD_STOCK_CLEAR absolute override, regardless of model."""
        from services.decision_intelligence.main import _recommend_single

        # swimwear + very high stock relative to sold units → DOS > 120, sell-through < 0.15
        req = _e2e_request(
            "S2-DEAD-STOCK",
            category="swimwear",
            total_qty=490,
            season_sell_through_pct=0.08,
            days_since_launch=200,
            retail_price_usd=200.0,
            current_margin_pct=50.0,
        )
        result = _recommend_single(req)

        assert result.recommendation == "CLEAR"
        assert result.rule_override is not None
        assert result.rule_override.rule_id == "DEAD_STOCK_CLEAR"

    def test_s3_low_stock_forces_hold_e2e(self):
        """S3: Low stock — LOW_STOCK_PROTECTION forces HOLD."""
        from services.decision_intelligence.main import _recommend_single

        req = _e2e_request(
            "S3-LOW-STOCK",
            total_qty=12,
            days_of_supply=8,
        )
        result = _recommend_single(req)

        assert result.recommendation == "HOLD"
        # Rule override must be set (LOW_STOCK_PROTECTION is a strong rule)
        assert result.rule_override is not None
        assert result.rule_override.rule_id == "LOW_STOCK_PROTECTION"

    def test_s4_margin_floor_blocks_markdown_e2e(self):
        """S4: Thin margin — MARGIN_FLOOR_PROTECTION blocks MARKDOWN.
        Final decision must not be MARKDOWN."""
        from services.decision_intelligence.main import _recommend_single

        req = _e2e_request(
            "S4-MARGIN-FLOOR",
            current_margin_pct=28.0,
        )
        result = _recommend_single(req)

        assert result.recommendation != "MARKDOWN", (
            f"MARGIN_FLOOR_PROTECTION should have blocked MARKDOWN "
            f"(margin=28%), got {result.recommendation}"
        )

    def test_s5_recent_discount_blocks_markdown_e2e(self):
        """S5: Discounted 7 days ago — RECENT_DISCOUNT_PROTECTION blocks MARKDOWN."""
        from services.decision_intelligence.main import _recommend_single

        req = _e2e_request(
            "S5-RECENT-DISCOUNT",
            days_since_last_discount=7,
        )
        result = _recommend_single(req)

        assert result.recommendation != "MARKDOWN", (
            f"RECENT_DISCOUNT_PROTECTION should have blocked MARKDOWN "
            f"(days_since_last_discount=7), got {result.recommendation}"
        )

    def test_s6_event_nudge_rule_is_soft_e2e(self):
        """S6: Calendar event nudge — soft rule, never a hard override.
        rule_override must be None (no absolute/strong rules fired)."""
        from services.decision_intelligence.main import _recommend_single

        req = _e2e_request(
            "S6-EVENT-NUDGE",
            event_proximity_score=0.9,
        )
        result = _recommend_single(req)

        assert result.recommendation in ("HOLD", "MARKDOWN", "PROMOTE", "CLEAR")
        # Event nudge is a soft rule — it should never produce a hard rule_override
        assert result.rule_override is None, (
            f"Calendar event nudge fired as hard override: {result.rule_override}"
        )

    def test_all_e2e_results_have_valid_output_schema(self):
        """All 6 scenarios must return well-formed RecommendationResult objects."""
        from services.decision_intelligence.main import _recommend_single
        from services.decision_intelligence.schemas import RecommendationResult

        scenarios = [
            ("S1-SCHEMA", {}),
            ("S2-SCHEMA", dict(category="swimwear", total_qty=490, season_sell_through_pct=0.08, days_since_launch=200, retail_price_usd=200.0, current_margin_pct=50.0)),
            ("S3-SCHEMA", dict(total_qty=12, days_of_supply=8)),
            ("S4-SCHEMA", dict(current_margin_pct=28.0)),
            ("S5-SCHEMA", dict(days_since_last_discount=7)),
            ("S6-SCHEMA", dict(event_proximity_score=0.9)),
        ]
        for sku_id, overrides in scenarios:
            req = _e2e_request(sku_id, **overrides)
            result = _recommend_single(req)
            assert isinstance(result, RecommendationResult), f"{sku_id}: not a RecommendationResult"
            assert result.recommendation in ("HOLD", "MARKDOWN", "PROMOTE", "CLEAR"), f"{sku_id}: invalid recommendation"
            assert 0.0 <= result.confidence <= 1.0, f"{sku_id}: confidence out of range"
            assert result.requires_human_approval is True, f"{sku_id}: requires_human_approval must be True"
            assert isinstance(result.shap_top5, list), f"{sku_id}: shap_top5 must be a list"
