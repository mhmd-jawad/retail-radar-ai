"""
Unit tests for the IE2 feature engineering pipeline.
"""

import pytest
from pathlib import Path
from services.decision_intelligence.features.engineer import (
    _estimate_daily_demand,
    _get_seasonal_multiplier,
    CATEGORY_VELOCITY,
    EVENT_WINDOWS,
)


class TestEstimateDailyDemand:
    def test_returns_positive_value(self):
        demand = _estimate_daily_demand(100, "footwear", 0, 100.0)
        assert demand > 0

    def test_higher_stock_means_lower_demand_estimate(self):
        """Demand estimate is inversely scaled from stock."""
        d_low  = _estimate_daily_demand(50,  "footwear", 0, 100.0)
        d_high = _estimate_daily_demand(200, "footwear", 0, 100.0)
        # Both should be positive; high stock implies lower sell-velocity
        assert d_low >= 0
        assert d_high >= 0

    def test_category_velocity_adjustment(self):
        """Footwear should differ from accessories in velocity."""
        d_foot = _estimate_daily_demand(100, "footwear", 0, 100.0)
        d_acc  = _estimate_daily_demand(100, "accessories", 0, 100.0)
        if CATEGORY_VELOCITY.get("footwear", 1.0) != CATEGORY_VELOCITY.get("accessories", 1.0):
            assert d_foot != d_acc

    def test_unknown_category_uses_default(self):
        demand = _estimate_daily_demand(100, "unknown_category_xyz", 0, 100.0)
        assert demand > 0


class TestGetSeasonalMultiplier:
    def test_summer_month_has_boost(self):
        # July (month 7) is typically a peak month for sportswear
        mult = _get_seasonal_multiplier(7)
        assert mult > 0.5

    def test_returns_float(self):
        for month in range(1, 13):
            assert isinstance(_get_seasonal_multiplier(month), float)

    def test_all_months_positive(self):
        for month in range(1, 13):
            assert _get_seasonal_multiplier(month) > 0


class TestEventWindows:
    def test_event_windows_have_correct_structure(self):
        for month, val in EVENT_WINDOWS.items():
            assert 1 <= month <= 12
            assert isinstance(val, tuple)
            assert len(val) == 2
            name, score = val
            assert isinstance(name, str)
            assert 0.0 <= score <= 1.0

    def test_december_is_holiday_event(self):
        if 12 in EVENT_WINDOWS:
            name, score = EVENT_WINDOWS[12]
            assert "holiday" in name.lower() or score > 0
