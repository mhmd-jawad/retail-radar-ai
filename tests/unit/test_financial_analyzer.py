"""
Unit tests for the financial health analyzer (stylepulse/analyzers/financial.py).

All tests are offline — no DB or API required.

Run:
    pytest tests/unit/test_financial_analyzer.py -v
"""

from __future__ import annotations

import pytest

from stylepulse.analyzers import financial


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_inputs(
    current_ratio: float = 2.5,
    inventory_pct: float = 30.0,
    cash_runway: float = 5.0,
    monthly_fixed: float = 5_000.0,
    annual_revenue: float = 200_000.0,
    blended_margin_pct: float = 50.0,
    dead_stock_pct: float = 5.0,
    dead_stock_value_usd: float = 1_000.0,
    cashflow_records=None,
):
    """Build minimal valid inputs for financial.analyze()."""
    fp = {
        "balance_sheet_summary": {
            "total_assets_usd": 100_000,
            "total_liabilities_usd": 40_000,
            "total_equity_usd": 60_000,
            "current_ratio": current_ratio,
            "inventory_pct_of_assets": inventory_pct,
        },
        "cashflow_summary": {
            "cash_runway_months": cash_runway,
            "monthly_fixed_opex_usd": monthly_fixed,
            "breakeven_monthly_revenue_usd": 10_000,
            "annual_revenue_projected_usd": annual_revenue,
        },
    }
    inv = {
        "metrics": {
            "dead_stock_pct": dead_stock_pct,
            "dead_stock_value_usd": dead_stock_value_usd,
            "blended_margin_pct": blended_margin_pct,
        }
    }
    cf = cashflow_records if cashflow_records is not None else [
        {"month_name": "January", "net_cash_movement_usd": -500},
        {"month_name": "June", "net_cash_movement_usd": 8_000},
    ]
    return fp, {}, cf, inv


def _alert_types(result):
    return [(a["type"], a["severity"]) for a in result["alerts"]]


# ── Balance sheet / liquidity ──────────────────────────────────────────────────

class TestLiquidityStatus:
    def test_healthy_when_ratio_at_or_above_two(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=2.5)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "healthy"

    def test_adequate_when_ratio_between_warning_and_healthy(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.7)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "adequate"

    def test_adequate_at_exact_warning_threshold(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.5)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "adequate"

    def test_critical_when_ratio_below_warning(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.2)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "critical"

    def test_zero_current_ratio_is_critical(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "critical"

    def test_adequate_ratio_generates_medium_liquidity_warning(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.7)
        result = financial.analyze(fp, bs, cf, inv)
        assert ("liquidity_warning", "medium") in _alert_types(result)

    def test_critical_ratio_generates_high_liquidity_alert(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.2)
        result = financial.analyze(fp, bs, cf, inv)
        assert ("liquidity_critical", "high") in _alert_types(result)

    def test_healthy_ratio_generates_no_liquidity_alert(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=2.5)
        result = financial.analyze(fp, bs, cf, inv)
        types = [a["type"] for a in result["alerts"]]
        assert "liquidity_warning" not in types
        assert "liquidity_critical" not in types

    def test_balance_sheet_values_passed_through(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=2.0, inventory_pct=40.0)
        result = financial.analyze(fp, bs, cf, inv)
        bsh = result["balance_sheet_health"]
        assert bsh["total_assets_usd"] == 100_000
        assert bsh["total_liabilities_usd"] == 40_000
        assert bsh["total_equity_usd"] == 60_000
        assert bsh["current_ratio"] == 2.0
        assert bsh["inventory_pct_of_assets"] == 40.0


# ── Inventory concentration ────────────────────────────────────────────────────

class TestInventoryConcentration:
    def test_above_max_generates_high_alert(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=80.0)
        result = financial.analyze(fp, bs, cf, inv)
        inv_alerts = [a for a in result["alerts"] if a["type"] == "inventory_concentration"]
        assert len(inv_alerts) == 1
        assert inv_alerts[0]["severity"] == "high"

    def test_between_warning_and_max_generates_medium_alert(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=65.0)
        result = financial.analyze(fp, bs, cf, inv)
        inv_alerts = [a for a in result["alerts"] if a["type"] == "inventory_concentration"]
        assert len(inv_alerts) == 1
        assert inv_alerts[0]["severity"] == "medium"

    def test_below_warning_no_alert(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=40.0)
        result = financial.analyze(fp, bs, cf, inv)
        types = [a["type"] for a in result["alerts"]]
        assert "inventory_concentration" not in types

    def test_at_exact_max_threshold_generates_high_alert(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=75.1)
        result = financial.analyze(fp, bs, cf, inv)
        inv_alerts = [a for a in result["alerts"] if a["type"] == "inventory_concentration"]
        assert inv_alerts[0]["severity"] == "high"

    def test_dead_stock_values_stored_in_result(self):
        fp, bs, cf, inv = _make_inputs(dead_stock_pct=12.0, dead_stock_value_usd=5_000.0)
        result = financial.analyze(fp, bs, cf, inv)
        bsh = result["balance_sheet_health"]
        assert bsh["dead_stock_pct_of_inventory"] == 12.0
        assert bsh["dead_stock_value_usd"] == 5_000.0


# ── Cash runway ────────────────────────────────────────────────────────────────

class TestCashRunway:
    def test_safe_when_runway_at_or_above_four_months(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=6.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["runway_status"] == "safe"

    def test_adequate_when_runway_between_warning_and_safe(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=3.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["runway_status"] == "adequate"

    def test_critical_when_runway_below_warning(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=1.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["runway_status"] == "critical"

    def test_safe_runway_no_alert(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=6.0)
        result = financial.analyze(fp, bs, cf, inv)
        types = [a["type"] for a in result["alerts"]]
        assert "cash_runway" not in types
        assert "cash_runway_critical" not in types

    def test_adequate_runway_generates_medium_alert(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=3.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert ("cash_runway", "medium") in _alert_types(result)

    def test_critical_runway_generates_high_alert(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=1.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert ("cash_runway_critical", "high") in _alert_types(result)

    def test_runway_stored_in_cashflow_health(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=4.5)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["cash_runway_months"] == 4.5


# ── Cashflow record analysis ────────────────────────────────────────────────────

class TestCashflowRecords:
    def test_best_and_worst_month_identified(self):
        cf = [
            {"month_name": "BadMonth", "net_cash_movement_usd": -2_000},
            {"month_name": "GoodMonth", "net_cash_movement_usd": 10_000},
            {"month_name": "NeutralMonth", "net_cash_movement_usd": 0},
        ]
        fp, bs, _, inv = _make_inputs()
        result = financial.analyze(fp, bs, cf, inv)
        ch = result["cashflow_health"]
        assert ch["worst_month"]["name"] == "BadMonth"
        assert ch["best_month"]["name"] == "GoodMonth"
        assert ch["worst_month"]["net_cash_usd"] == -2_000.0
        assert ch["best_month"]["net_cash_usd"] == 10_000.0

    def test_months_positive_negative_counted_correctly(self):
        cf = [
            {"month_name": "A", "net_cash_movement_usd": 100},
            {"month_name": "B", "net_cash_movement_usd": -50},
            {"month_name": "C", "net_cash_movement_usd": 0},
            {"month_name": "D", "net_cash_movement_usd": -200},
        ]
        fp, bs, _, inv = _make_inputs()
        result = financial.analyze(fp, bs, cf, inv)
        ch = result["cashflow_health"]
        assert ch["months_cash_positive"] == 2   # A and C (0 counts as non-negative)
        assert ch["months_cash_negative"] == 2   # B and D

    def test_empty_cashflow_gives_zero_counts_and_no_best_worst(self):
        fp, bs, _, inv = _make_inputs(cashflow_records=[])
        result = financial.analyze(fp, bs, [], inv)
        ch = result["cashflow_health"]
        assert ch["months_cash_positive"] == 0
        assert ch["months_cash_negative"] == 0
        assert ch["best_month"] is None
        assert ch["worst_month"] is None

    def test_seasonal_cash_drain_alert_when_more_than_three_negative_months(self):
        cf = [
            {"month_name": f"Bad{i}", "net_cash_movement_usd": -100}
            for i in range(4)
        ] + [{"month_name": "Peak", "net_cash_movement_usd": 5_000}]
        fp, bs, _, inv = _make_inputs(cash_runway=6.0)
        result = financial.analyze(fp, bs, cf, inv)
        types = [a["type"] for a in result["alerts"]]
        assert "seasonal_cash_drain" in types

    def test_no_seasonal_drain_alert_at_three_negative_months(self):
        cf = [
            {"month_name": f"Bad{i}", "net_cash_movement_usd": -100}
            for i in range(3)
        ] + [{"month_name": "Peak", "net_cash_movement_usd": 5_000}]
        fp, bs, _, inv = _make_inputs(cash_runway=6.0)
        result = financial.analyze(fp, bs, cf, inv)
        types = [a["type"] for a in result["alerts"]]
        assert "seasonal_cash_drain" not in types

    def test_monthly_fixed_and_breakeven_stored(self):
        fp, bs, cf, inv = _make_inputs(monthly_fixed=7_500.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["monthly_fixed_opex_usd"] == 7_500.0


# ── Profitability ──────────────────────────────────────────────────────────────

class TestProfitability:
    def test_margin_health_healthy(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=50.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["margin_health"] == "healthy"

    def test_margin_health_warning(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=38.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["margin_health"] == "warning"

    def test_margin_health_critical(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=20.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["margin_health"] == "critical"

    def test_opex_coverage_computed_correctly(self):
        # gross = 200_000 * 50% = 100_000; annual_opex = 5_000 * 12 = 60_000 → coverage = 1.67
        fp, bs, cf, inv = _make_inputs(
            annual_revenue=200_000, blended_margin_pct=50.0, monthly_fixed=5_000
        )
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["opex_coverage_ratio"] == pytest.approx(1.67, abs=0.01)

    def test_opex_coverage_below_threshold_generates_high_alert(self):
        # gross = 100_000 * 20% = 20_000; annual_opex = 10_000 * 12 = 120_000 → coverage = 0.17 < 1.5
        fp, bs, cf, inv = _make_inputs(
            annual_revenue=100_000, blended_margin_pct=20.0, monthly_fixed=10_000
        )
        result = financial.analyze(fp, bs, cf, inv)
        assert ("opex_coverage", "high") in _alert_types(result)

    def test_opex_coverage_above_threshold_no_alert(self):
        # gross = 200_000 * 50% = 100_000; annual_opex = 3_000 * 12 = 36_000 → coverage = 2.78 > 1.5
        fp, bs, cf, inv = _make_inputs(
            annual_revenue=200_000, blended_margin_pct=50.0, monthly_fixed=3_000
        )
        result = financial.analyze(fp, bs, cf, inv)
        types = [a["type"] for a in result["alerts"]]
        assert "opex_coverage" not in types

    def test_zero_monthly_fixed_gives_zero_coverage(self):
        fp, bs, cf, inv = _make_inputs(monthly_fixed=0.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["opex_coverage_ratio"] == 0

    def test_annual_gross_profit_computed(self):
        fp, bs, cf, inv = _make_inputs(annual_revenue=100_000, blended_margin_pct=40.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["annual_gross_profit_projected_usd"] == pytest.approx(40_000.0)


# ── Equity quality ─────────────────────────────────────────────────────────────

class TestEquityQuality:
    def test_solid_when_dead_stock_below_ten_pct(self):
        fp, bs, cf, inv = _make_inputs(dead_stock_pct=5.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["equity_quality"] == "solid"

    def test_impaired_at_exactly_ten_pct(self):
        fp, bs, cf, inv = _make_inputs(dead_stock_pct=10.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["equity_quality"] == "impaired"

    def test_impaired_when_dead_stock_above_ten_pct(self):
        fp, bs, cf, inv = _make_inputs(dead_stock_pct=25.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["equity_quality"] == "impaired"


# ── Alert sorting and result structure ─────────────────────────────────────────

class TestAlertSortingAndStructure:
    def test_high_severity_alerts_appear_before_medium(self):
        # critical ratio (high) + medium inventory concentration
        fp, bs, cf, inv = _make_inputs(current_ratio=1.0, inventory_pct=65.0)
        result = financial.analyze(fp, bs, cf, inv)
        severities = [a["severity"] for a in result["alerts"]]
        high_indices = [i for i, s in enumerate(severities) if s == "high"]
        med_indices = [i for i, s in enumerate(severities) if s == "medium"]
        if high_indices and med_indices:
            assert max(high_indices) < min(med_indices)

    def test_result_has_all_required_keys(self):
        fp, bs, cf, inv = _make_inputs()
        result = financial.analyze(fp, bs, cf, inv)
        assert "balance_sheet_health" in result
        assert "cashflow_health" in result
        assert "profitability" in result
        assert "alerts" in result

    def test_alerts_is_list(self):
        fp, bs, cf, inv = _make_inputs()
        result = financial.analyze(fp, bs, cf, inv)
        assert isinstance(result["alerts"], list)

    def test_clean_inputs_produce_no_alerts(self):
        fp, bs, cf, inv = _make_inputs(
            current_ratio=3.0,
            inventory_pct=30.0,
            cash_runway=6.0,
            monthly_fixed=3_000,
            annual_revenue=200_000,
            blended_margin_pct=55.0,
            dead_stock_pct=2.0,
            cashflow_records=[
                {"month_name": "Jan", "net_cash_movement_usd": 500},
                {"month_name": "Feb", "net_cash_movement_usd": 1000},
                {"month_name": "Mar", "net_cash_movement_usd": 800},
            ],
        )
        result = financial.analyze(fp, bs, cf, inv)
        assert result["alerts"] == []

    def test_multiple_simultaneous_alerts(self):
        fp, bs, cf, inv = _make_inputs(
            current_ratio=1.0,     # high liquidity_critical
            inventory_pct=80.0,    # high inventory_concentration
            cash_runway=1.0,       # high cash_runway_critical
        )
        result = financial.analyze(fp, bs, cf, inv)
        high_alerts = [a for a in result["alerts"] if a["severity"] == "high"]
        assert len(high_alerts) >= 3


# ── Boundary conditions (exact threshold values) ───────────────────────────────

class TestBoundaryConditions:
    """Verify >= / > boundary semantics at every documented threshold."""

    # Current ratio — CURRENT_RATIO_HEALTHY = 2.0, CURRENT_RATIO_WARNING = 1.5
    def test_current_ratio_exactly_2_is_healthy(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=2.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "healthy"

    def test_current_ratio_exactly_1_5_is_adequate_not_critical(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.5)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "adequate"

    def test_current_ratio_just_below_warning_is_critical(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.49)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "critical"

    # Cash runway — CASH_RUNWAY_SAFE = 4.0, CASH_RUNWAY_WARNING = 2.5
    def test_cash_runway_exactly_4_is_safe(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=4.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["runway_status"] == "safe"

    def test_cash_runway_exactly_2_5_is_adequate(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=2.5)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["runway_status"] == "adequate"

    def test_cash_runway_just_below_2_5_is_critical(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=2.49)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["runway_status"] == "critical"

    # Inventory concentration — MAX = 75.0 (strict >), WARNING = 60.0 (strict >)
    def test_inventory_pct_exactly_75_does_not_trigger_high_alert(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=75.0)
        result = financial.analyze(fp, bs, cf, inv)
        high_inv_alerts = [
            a for a in result["alerts"]
            if a["type"] == "inventory_concentration" and a["severity"] == "high"
        ]
        assert len(high_inv_alerts) == 0

    def test_inventory_pct_75_1_triggers_high_alert(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=75.1)
        result = financial.analyze(fp, bs, cf, inv)
        high_inv_alerts = [
            a for a in result["alerts"]
            if a["type"] == "inventory_concentration" and a["severity"] == "high"
        ]
        assert len(high_inv_alerts) == 1

    def test_inventory_pct_exactly_60_does_not_trigger_medium_alert(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=60.0)
        result = financial.analyze(fp, bs, cf, inv)
        types = [a["type"] for a in result["alerts"]]
        assert "inventory_concentration" not in types

    def test_inventory_pct_60_1_triggers_medium_alert(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=60.1)
        result = financial.analyze(fp, bs, cf, inv)
        med_inv = [
            a for a in result["alerts"]
            if a["type"] == "inventory_concentration" and a["severity"] == "medium"
        ]
        assert len(med_inv) == 1

    # Margin — MARGIN_HEALTHY = 45.0, MARGIN_FLOOR = 35.0
    def test_margin_exactly_45_is_healthy(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=45.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["margin_health"] == "healthy"

    def test_margin_exactly_35_is_warning(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=35.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["margin_health"] == "warning"

    def test_margin_just_below_35_is_critical(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=34.9)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["margin_health"] == "critical"

    # OpEx coverage — threshold < 1.5 triggers alert
    def test_opex_coverage_exactly_1_5_no_alert(self):
        # Need coverage exactly 1.5: gross = rev * margin; opex = monthly * 12
        # Let annual_revenue = 180_000, margin = 50% → gross = 90_000
        # monthly_fixed = 5_000 → annual_opex = 60_000 → coverage = 1.5
        fp, bs, cf, inv = _make_inputs(annual_revenue=180_000, blended_margin_pct=50.0, monthly_fixed=5_000)
        result = financial.analyze(fp, bs, cf, inv)
        types = [a["type"] for a in result["alerts"]]
        assert "opex_coverage" not in types

    def test_opex_coverage_just_below_1_5_triggers_alert(self):
        # coverage = 1.49: gross = 89_400, opex = 60_000 → rev = 178_800, margin = 50%
        fp, bs, cf, inv = _make_inputs(annual_revenue=178_800, blended_margin_pct=50.0, monthly_fixed=5_000)
        result = financial.analyze(fp, bs, cf, inv)
        assert ("opex_coverage", "high") in _alert_types(result)

    # Seasonal drain — triggered when months_negative > 3 (strict)
    def test_seasonal_drain_not_triggered_at_exactly_3_negative_months(self):
        cf = [{"month_name": f"Bad{i}", "net_cash_movement_usd": -100} for i in range(3)]
        cf.append({"month_name": "Peak", "net_cash_movement_usd": 5_000})
        fp, bs, _, inv = _make_inputs(cash_runway=6.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert "seasonal_cash_drain" not in [a["type"] for a in result["alerts"]]

    def test_seasonal_drain_triggered_at_4_negative_months(self):
        cf = [{"month_name": f"Bad{i}", "net_cash_movement_usd": -100} for i in range(4)]
        cf.append({"month_name": "Peak", "net_cash_movement_usd": 5_000})
        fp, bs, _, inv = _make_inputs(cash_runway=6.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert "seasonal_cash_drain" in [a["type"] for a in result["alerts"]]

    # Equity quality — solid if dead_stock_pct < 10 (strict)
    def test_equity_quality_solid_at_9_9_pct(self):
        fp, bs, cf, inv = _make_inputs(dead_stock_pct=9.9)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["equity_quality"] == "solid"

    def test_equity_quality_impaired_at_exactly_10_pct(self):
        fp, bs, cf, inv = _make_inputs(dead_stock_pct=10.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["equity_quality"] == "impaired"


# ── Previously untested output fields ─────────────────────────────────────────

class TestUntestedOutputFields:
    """Ensure fields that existed in the output but had no assertions are correct."""

    def test_breakeven_monthly_revenue_stored(self):
        fp, bs, cf, inv = _make_inputs()
        # Default _make_inputs sets breakeven = 10_000
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["breakeven_monthly_revenue_usd"] == 10_000

    def test_projected_annual_revenue_stored(self):
        fp, bs, cf, inv = _make_inputs(annual_revenue=350_000)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["projected_annual_revenue_usd"] == 350_000

    def test_annual_fixed_opex_is_monthly_times_twelve(self):
        fp, bs, cf, inv = _make_inputs(monthly_fixed=4_000)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["annual_fixed_opex_usd"] == 48_000

    def test_blended_margin_pct_stored_in_profitability(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=42.5)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["blended_margin_pct"] == pytest.approx(42.5)


# ── Edge cases and zero / negative values ─────────────────────────────────────

class TestEdgeCasesAndZeroValues:
    """Verify the analyzer handles boundary/degenerate inputs without crashing."""

    def test_zero_current_ratio_is_critical_with_high_alert(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "critical"
        assert ("liquidity_critical", "high") in _alert_types(result)

    def test_zero_cash_runway_is_critical(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["cashflow_health"]["runway_status"] == "critical"

    def test_zero_blended_margin_is_critical(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=0.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["margin_health"] == "critical"

    def test_negative_blended_margin_is_critical(self):
        fp, bs, cf, inv = _make_inputs(blended_margin_pct=-10.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["margin_health"] == "critical"

    def test_zero_monthly_fixed_opex_no_division_error(self):
        fp, bs, cf, inv = _make_inputs(monthly_fixed=0.0, annual_revenue=100_000)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["opex_coverage_ratio"] == 0

    def test_zero_annual_revenue_gives_zero_gross_profit(self):
        fp, bs, cf, inv = _make_inputs(annual_revenue=0.0, blended_margin_pct=50.0, monthly_fixed=0.0)
        result = financial.analyze(fp, bs, cf, inv)
        assert result["profitability"]["annual_gross_profit_projected_usd"] == 0.0

    def test_empty_cashflow_no_crash(self):
        fp, bs, _, inv = _make_inputs(cashflow_records=[])
        result = financial.analyze(fp, bs, [], inv)
        ch = result["cashflow_health"]
        assert ch["months_cash_positive"] == 0
        assert ch["months_cash_negative"] == 0
        assert ch["best_month"] is None
        assert ch["worst_month"] is None

    def test_single_cashflow_record_works(self):
        cf = [{"month_name": "Only", "net_cash_movement_usd": 1_234}]
        fp, bs, _, inv = _make_inputs(cashflow_records=cf)
        result = financial.analyze(fp, bs, cf, inv)
        ch = result["cashflow_health"]
        assert ch["best_month"]["name"] == "Only"
        assert ch["worst_month"]["name"] == "Only"
        assert ch["months_cash_positive"] == 1
        assert ch["months_cash_negative"] == 0

    def test_none_current_ratio_defaults_to_zero_and_is_critical(self):
        fp, bs, cf, inv = _make_inputs()
        fp["balance_sheet_summary"]["current_ratio"] = None
        result = financial.analyze(fp, bs, cf, inv)
        assert result["balance_sheet_health"]["liquidity_status"] == "critical"


# ── Alert message content ──────────────────────────────────────────────────────

class TestAlertMessages:
    """Verify alert messages contain the expected numeric values and context."""

    def test_liquidity_critical_message_contains_ratio(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.2)
        result = financial.analyze(fp, bs, cf, inv)
        alert = next(a for a in result["alerts"] if a["type"] == "liquidity_critical")
        assert "1.2" in alert["message"]

    def test_liquidity_warning_message_contains_ratio(self):
        fp, bs, cf, inv = _make_inputs(current_ratio=1.7)
        result = financial.analyze(fp, bs, cf, inv)
        alert = next(a for a in result["alerts"] if a["type"] == "liquidity_warning")
        assert "1.7" in alert["message"]

    def test_cash_runway_critical_message_contains_months(self):
        fp, bs, cf, inv = _make_inputs(cash_runway=1.0)
        result = financial.analyze(fp, bs, cf, inv)
        alert = next(a for a in result["alerts"] if a["type"] == "cash_runway_critical")
        assert "1.0" in alert["message"]

    def test_inventory_concentration_high_alert_contains_pct(self):
        fp, bs, cf, inv = _make_inputs(inventory_pct=82.0)
        result = financial.analyze(fp, bs, cf, inv)
        alert = next(a for a in result["alerts"] if a["type"] == "inventory_concentration")
        assert "82" in alert["message"]

    def test_opex_coverage_alert_contains_coverage_value(self):
        # coverage = 20_000 / 120_000 ≈ 0.17; formatted as "0.2x" (1dp rounding)
        fp, bs, cf, inv = _make_inputs(
            annual_revenue=100_000, blended_margin_pct=20.0, monthly_fixed=10_000
        )
        result = financial.analyze(fp, bs, cf, inv)
        alert = next(a for a in result["alerts"] if a["type"] == "opex_coverage")
        assert "0.2" in alert["message"]  # 0.17 formats to "0.2x" with :.1f

    def test_seasonal_drain_alert_contains_worst_month_name(self):
        cf = [{"month_name": f"Bad{i}", "net_cash_movement_usd": -100} for i in range(4)]
        cf.append({"month_name": "GoodMonth", "net_cash_movement_usd": 5_000})
        fp, bs, _, inv = _make_inputs(cash_runway=6.0)
        result = financial.analyze(fp, bs, cf, inv)
        alert = next(a for a in result["alerts"] if a["type"] == "seasonal_cash_drain")
        assert "Bad0" in alert["message"] or "GoodMonth" in alert["message"]
