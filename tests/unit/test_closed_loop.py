"""
Unit tests for the closed-loop outcome tracking system.

Covers two modules:
  - eep/outcome_tracking.py   : snapshot_decision(), measure_outcome(),
                                 _derive_predicted_lift(), get_all_outcomes(),
                                 get_accuracy(), measure_all_due()
  - services/telegram_assistant/outcome_tracking.py : format_closed_loop_summary(),
                                                       now_utc()

All tests are offline — every DB call is monkeypatched, no API keys required.

Run:
    pytest tests/unit/test_closed_loop.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from eep import outcome_tracking
from eep.retail_db import DatabaseUnavailable


# ── _derive_predicted_lift ─────────────────────────────────────────────────────

class TestDerivePredictedLift:
    def test_promote_uses_confidence_times_thirty(self):
        result = outcome_tracking._derive_predicted_lift("PROMOTE", 0.85, None)
        assert result == pytest.approx(25.5)

    def test_promote_at_high_confidence(self):
        result = outcome_tracking._derive_predicted_lift("PROMOTE", 1.0, None)
        assert result == pytest.approx(30.0)

    def test_markdown_with_explicit_discount(self):
        result = outcome_tracking._derive_predicted_lift("MARKDOWN", 0.8, 20.0)
        assert result == pytest.approx(13.0)

    def test_markdown_without_discount_defaults_to_ten_pct(self):
        result = outcome_tracking._derive_predicted_lift("MARKDOWN", 0.8, None)
        # default discount = 10.0 → 10 * 0.65 = 6.5
        assert result == pytest.approx(6.5)

    def test_clear_always_eighty_pct(self):
        result = outcome_tracking._derive_predicted_lift("CLEAR", 0.5, None)
        assert result == 80.0

    def test_hold_always_zero(self):
        result = outcome_tracking._derive_predicted_lift("HOLD", 0.9, None)
        assert result == 0.0

    def test_unknown_decision_type_returns_zero(self):
        result = outcome_tracking._derive_predicted_lift("UNKNOWN", 0.9, None)
        assert result == 0.0


# ── snapshot_decision ──────────────────────────────────────────────────────────

class TestSnapshotDecision:
    def _patch_helpers(self, monkeypatch, *, data_available=True, stock=20,
                       velocity=1.5, total_revenue=200.0, avg_price=100.0,
                       confidence=0.80, discount=15.0, snapshot_id=42):
        monkeypatch.setattr(
            outcome_tracking, "query_velocity_window",
            lambda *a, **kw: {
                "velocity_daily": velocity,
                "total_revenue": total_revenue,
                "avg_unit_price": avg_price,
                "data_available": data_available,
            },
        )
        monkeypatch.setattr(
            outcome_tracking, "get_current_stock_for_variant",
            lambda *a, **kw: stock,
        )
        monkeypatch.setattr(
            outcome_tracking, "get_recommendation_by_id",
            lambda *a, **kw: {
                "confidence": confidence,
                "explanation": "Strong seasonal",
                "suggested_discount_pct": discount,
                "suggested_price_usd": 95.0,
            },
        )
        inserted = {}
        def _insert(data, tenant_id=None):
            inserted.update(data)
            return snapshot_id
        monkeypatch.setattr(outcome_tracking, "insert_decision_snapshot", _insert)
        return inserted

    def test_returns_snapshot_id(self, monkeypatch):
        self._patch_helpers(monkeypatch)
        result = outcome_tracking.snapshot_decision(
            sku_id="SKU-1", variant_id="var-1",
            decision_type="PROMOTE", recommendation_id="rec-1",
            cost_price_usd=50.0, tenant_id="tenant-a",
        )
        assert result == 42

    def test_status_tracking_when_data_available(self, monkeypatch):
        inserted = self._patch_helpers(monkeypatch, data_available=True)
        outcome_tracking.snapshot_decision(
            sku_id="SKU-1", variant_id="var-1",
            decision_type="PROMOTE", recommendation_id="rec-1",
            cost_price_usd=50.0,
        )
        assert inserted["status"] == "tracking"

    def test_status_insufficient_data_when_no_sales(self, monkeypatch):
        inserted = self._patch_helpers(monkeypatch, data_available=False)
        outcome_tracking.snapshot_decision(
            sku_id="SKU-1", variant_id="var-1",
            decision_type="PROMOTE", recommendation_id="rec-1",
            cost_price_usd=50.0,
        )
        assert inserted["status"] == "insufficient_data"

    def test_returns_none_when_db_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            outcome_tracking, "query_velocity_window",
            lambda *a, **kw: (_ for _ in ()).throw(DatabaseUnavailable("DB down")),
        )
        result = outcome_tracking.snapshot_decision(
            sku_id="SKU-1", variant_id="var-1",
            decision_type="PROMOTE", recommendation_id=None,
            cost_price_usd=50.0,
        )
        assert result is None

    def test_skips_recommendation_lookup_when_no_rec_id(self, monkeypatch):
        rec_calls = []
        monkeypatch.setattr(
            outcome_tracking, "query_velocity_window",
            lambda *a, **kw: {"velocity_daily": 1.0, "total_revenue": 70, "avg_unit_price": 10, "data_available": True},
        )
        monkeypatch.setattr(
            outcome_tracking, "get_current_stock_for_variant",
            lambda *a, **kw: 10,
        )
        monkeypatch.setattr(
            outcome_tracking, "get_recommendation_by_id",
            lambda *a, **kw: rec_calls.append(1) or {},
        )
        inserted = {}
        monkeypatch.setattr(outcome_tracking, "insert_decision_snapshot", lambda d, **kw: inserted.update(d) or 1)

        outcome_tracking.snapshot_decision(
            sku_id="SKU-1", variant_id="var-1",
            decision_type="HOLD", recommendation_id=None,
            cost_price_usd=50.0,
        )
        assert rec_calls == []
        assert inserted["ie2_confidence"] == 0.0

    def test_baseline_dos_computed_from_velocity_and_stock(self, monkeypatch):
        inserted = self._patch_helpers(monkeypatch, velocity=2.0, stock=20, data_available=True)
        outcome_tracking.snapshot_decision(
            sku_id="SKU-1", variant_id="var-1",
            decision_type="PROMOTE", recommendation_id="rec-1",
            cost_price_usd=50.0,
        )
        # dos = 20 / 2.0 = 10.0
        assert inserted["baseline_dos"] == pytest.approx(10.0)

    def test_check_dates_set_seven_and_fourteen_days_out(self, monkeypatch):
        inserted = self._patch_helpers(monkeypatch)
        outcome_tracking.snapshot_decision(
            sku_id="SKU-1", variant_id="var-1",
            decision_type="PROMOTE", recommendation_id="rec-1",
            cost_price_usd=50.0,
        )
        delta_7 = inserted["check_7d_at"] - inserted["approved_at"]
        delta_14 = inserted["check_14d_at"] - inserted["approved_at"]
        assert abs(delta_7.total_seconds() - 7 * 86400) < 2
        assert abs(delta_14.total_seconds() - 14 * 86400) < 2

    def test_baseline_margin_computed_from_avg_price_and_cost(self, monkeypatch):
        inserted = self._patch_helpers(
            monkeypatch, avg_price=100.0, data_available=True
        )
        outcome_tracking.snapshot_decision(
            sku_id="SKU-1", variant_id="var-1",
            decision_type="PROMOTE", recommendation_id="rec-1",
            cost_price_usd=60.0,   # margin = (100-60)/100 * 100 = 40%
        )
        assert inserted["baseline_margin_pct"] == pytest.approx(40.0)


# ── measure_outcome ────────────────────────────────────────────────────────────

class TestMeasureOutcome:
    _approved_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def _make_snapshot(self, decision_type="PROMOTE", baseline_vel=2.0,
                       baseline_rev=140.0, predicted_lift=20.0, confidence=0.8):
        return {
            "id": 1,
            "variant_id": "var-1",
            "approved_at": self._approved_at,
            "decision_type": decision_type,
            "baseline_velocity_daily": baseline_vel,
            "baseline_revenue_7d": baseline_rev,
            "predicted_lift_pct": predicted_lift,
            "ie2_confidence": confidence,
            "ie2_explanation": "Test",
        }

    def _patch(self, monkeypatch, snapshot, actual_vel=3.0, actual_rev=180.0,
               actual_units=21, avg_price=10.0, data_available=True,
               measurement_id=7):
        monkeypatch.setattr(
            outcome_tracking, "get_snapshot_by_id",
            lambda *a, **kw: snapshot,
        )
        monkeypatch.setattr(
            outcome_tracking, "query_velocity_window",
            lambda *a, **kw: {
                "velocity_daily": actual_vel,
                "total_revenue": actual_rev,
                "total_units": actual_units,
                "avg_unit_price": avg_price,
                "data_available": data_available,
            },
        )
        inserted = {}
        monkeypatch.setattr(
            outcome_tracking, "insert_outcome_measurement",
            lambda d, **kw: inserted.update(d) or measurement_id,
        )
        status_updates = []
        monkeypatch.setattr(
            outcome_tracking, "update_snapshot_status",
            lambda snap_id, status, **kw: status_updates.append(status),
        )
        monkeypatch.setattr(
            outcome_tracking, "_generate_narrative",
            lambda *a, **kw: {"narrative": "Good result.", "verified_lift_pct": 50.0, "verified_revenue_delta": 40.0},
        )
        return inserted, status_updates

    def test_velocity_lift_computed_correctly(self, monkeypatch):
        snap = self._make_snapshot(baseline_vel=2.0)
        inserted, _ = self._patch(monkeypatch, snap, actual_vel=3.0)
        outcome_tracking.measure_outcome(1, 7)
        # lift = (3-2)/2 * 100 = 50%
        assert inserted["velocity_lift_pct"] == pytest.approx(50.0)

    def test_revenue_delta_for_7d_window(self, monkeypatch):
        snap = self._make_snapshot(baseline_rev=100.0)
        inserted, _ = self._patch(monkeypatch, snap, actual_rev=80.0)
        outcome_tracking.measure_outcome(1, 7)
        # delta = 80 - (100 * 7/7) = -20
        assert inserted["revenue_delta_usd"] == pytest.approx(-20.0)

    def test_revenue_delta_normalised_for_14d_window(self, monkeypatch):
        snap = self._make_snapshot(baseline_rev=100.0)
        inserted, _ = self._patch(monkeypatch, snap, actual_rev=250.0)
        outcome_tracking.measure_outcome(1, 14)
        # delta = 250 - (100 * 14/7) = 250 - 200 = 50
        assert inserted["revenue_delta_usd"] == pytest.approx(50.0)

    def test_accuracy_score_computed(self, monkeypatch):
        snap = self._make_snapshot(baseline_vel=2.0, predicted_lift=20.0)
        inserted, _ = self._patch(monkeypatch, snap, actual_vel=2.5)
        outcome_tracking.measure_outcome(1, 7)
        # actual_lift = (2.5-2)/2*100 = 25%, predicted=20%
        # accuracy = max(0, 1 - |20-25|/max(|20|,1)) = 1 - 5/20 = 0.75
        assert inserted["accuracy_score"] == pytest.approx(0.75)

    def test_campaign_roi_computed_for_promote(self, monkeypatch):
        snap = self._make_snapshot(decision_type="PROMOTE", baseline_rev=100.0)
        inserted, _ = self._patch(monkeypatch, snap, actual_rev=200.0)
        outcome_tracking.measure_outcome(1, 7)
        # revenue_delta = 200 - 100 = 100; roi = 100 - 25 = 75
        assert inserted["campaign_roi_usd"] == pytest.approx(75.0)

    def test_campaign_roi_is_none_for_markdown(self, monkeypatch):
        snap = self._make_snapshot(decision_type="MARKDOWN", baseline_rev=100.0)
        inserted, _ = self._patch(monkeypatch, snap, actual_rev=200.0)
        outcome_tracking.measure_outcome(1, 7)
        assert inserted.get("campaign_roi_usd") is None

    def test_status_updated_to_measured_7d_for_7d_window(self, monkeypatch):
        snap = self._make_snapshot()
        _, status_updates = self._patch(monkeypatch, snap)
        outcome_tracking.measure_outcome(1, 7)
        assert status_updates == ["measured_7d"]

    def test_status_updated_to_completed_for_14d_window(self, monkeypatch):
        snap = self._make_snapshot()
        _, status_updates = self._patch(monkeypatch, snap)
        outcome_tracking.measure_outcome(1, 14)
        assert status_updates == ["completed"]

    def test_no_data_available_returns_early(self, monkeypatch):
        snap = self._make_snapshot()
        inserted, _ = self._patch(monkeypatch, snap, data_available=False)
        result = outcome_tracking.measure_outcome(1, 7)
        assert result["data_available"] is False
        assert inserted.get("data_available") is False

    def test_raises_value_error_when_snapshot_not_found(self, monkeypatch):
        monkeypatch.setattr(
            outcome_tracking, "get_snapshot_by_id",
            lambda *a, **kw: None,
        )
        with pytest.raises(ValueError, match="not found"):
            outcome_tracking.measure_outcome(999, 7)

    def test_approved_at_as_string_is_parsed(self, monkeypatch):
        snap = self._make_snapshot()
        snap["approved_at"] = "2026-01-01T12:00:00+00:00"
        inserted, _ = self._patch(monkeypatch, snap)
        result = outcome_tracking.measure_outcome(1, 7)
        assert result["data_available"] is True

    def test_measurement_id_returned(self, monkeypatch):
        snap = self._make_snapshot()
        inserted, _ = self._patch(monkeypatch, snap, measurement_id=99)
        result = outcome_tracking.measure_outcome(1, 7)
        assert result["measurement_id"] == 99


# ── Accuracy score edge cases ──────────────────────────────────────────────────

class TestAccuracyScoreEdgeCases:
    def test_accuracy_capped_at_zero_not_negative(self, monkeypatch):
        snap = {
            "id": 1,
            "variant_id": "var-1",
            "approved_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "decision_type": "PROMOTE",
            "baseline_velocity_daily": 1.0,
            "baseline_revenue_7d": 70.0,
            "predicted_lift_pct": 5.0,
            "ie2_confidence": 0.5,
            "ie2_explanation": "test",
        }
        monkeypatch.setattr(outcome_tracking, "get_snapshot_by_id", lambda *a, **kw: snap)
        inserted = {}
        monkeypatch.setattr(outcome_tracking, "query_velocity_window",
            lambda *a, **kw: {"velocity_daily": 100.0, "total_revenue": 700, "total_units": 700,
                               "avg_unit_price": 1.0, "data_available": True})
        monkeypatch.setattr(outcome_tracking, "insert_outcome_measurement",
            lambda d, **kw: inserted.update(d) or 1)
        monkeypatch.setattr(outcome_tracking, "update_snapshot_status", lambda *a, **kw: None)
        monkeypatch.setattr(outcome_tracking, "_generate_narrative",
            lambda *a, **kw: {"narrative": None, "verified_lift_pct": None, "verified_revenue_delta": None})

        outcome_tracking.measure_outcome(1, 7)
        assert inserted["accuracy_score"] >= 0.0

    def test_velocity_lift_is_none_when_baseline_zero(self, monkeypatch):
        snap = {
            "id": 1,
            "variant_id": "var-1",
            "approved_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "decision_type": "HOLD",
            "baseline_velocity_daily": 0.0,
            "baseline_revenue_7d": 0.0,
            "predicted_lift_pct": 0.0,
            "ie2_confidence": 0.5,
            "ie2_explanation": "",
        }
        monkeypatch.setattr(outcome_tracking, "get_snapshot_by_id", lambda *a, **kw: snap)
        inserted = {}
        monkeypatch.setattr(outcome_tracking, "query_velocity_window",
            lambda *a, **kw: {"velocity_daily": 2.0, "total_revenue": 140, "total_units": 14,
                               "avg_unit_price": 10.0, "data_available": True})
        monkeypatch.setattr(outcome_tracking, "insert_outcome_measurement",
            lambda d, **kw: inserted.update(d) or 1)
        monkeypatch.setattr(outcome_tracking, "update_snapshot_status", lambda *a, **kw: None)
        monkeypatch.setattr(outcome_tracking, "_generate_narrative",
            lambda *a, **kw: {"narrative": None, "verified_lift_pct": None, "verified_revenue_delta": None})

        outcome_tracking.measure_outcome(1, 7)
        assert inserted.get("velocity_lift_pct") is None


# ── get_all_outcomes / get_accuracy / measure_all_due ─────────────────────────

class TestTopLevelHelpers:
    def test_get_all_outcomes_returns_empty_on_db_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            outcome_tracking, "get_all_snapshots_for_tenant",
            lambda **kw: (_ for _ in ()).throw(DatabaseUnavailable("offline")),
        )
        result = outcome_tracking.get_all_outcomes(tenant_id="t1")
        assert result == []

    def test_get_accuracy_returns_empty_on_db_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            outcome_tracking, "get_portfolio_accuracy",
            lambda *a, **kw: (_ for _ in ()).throw(DatabaseUnavailable("offline")),
        )
        result = outcome_tracking.get_accuracy(tenant_id="t1")
        assert result == {"avg_accuracy": None, "decision_count": 0, "by_type": {}}

    def test_measure_all_due_counts_correctly(self, monkeypatch):
        due_snaps = [
            {"id": 1, "window_days": 7},
            {"id": 2, "window_days": 14},
        ]
        monkeypatch.setattr(
            outcome_tracking, "get_due_snapshots_for_tenant",
            lambda **kw: due_snaps,
        )
        call_args = []
        def fake_measure(snap_id, window_days, tenant_id=None):
            call_args.append((snap_id, window_days))
            return {"data_available": True}
        monkeypatch.setattr(outcome_tracking, "measure_outcome", fake_measure)

        result = outcome_tracking.measure_all_due(tenant_id="t1")
        assert result["measured"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert call_args == [(1, 7), (2, 14)]

    def test_measure_all_due_counts_skipped_when_no_data(self, monkeypatch):
        monkeypatch.setattr(
            outcome_tracking, "get_due_snapshots_for_tenant",
            lambda **kw: [{"id": 1, "window_days": 7}],
        )
        monkeypatch.setattr(
            outcome_tracking, "measure_outcome",
            lambda *a, **kw: {"data_available": False},
        )
        result = outcome_tracking.measure_all_due()
        assert result["skipped"] == 1
        assert result["measured"] == 0

    def test_measure_all_due_counts_errors(self, monkeypatch):
        monkeypatch.setattr(
            outcome_tracking, "get_due_snapshots_for_tenant",
            lambda **kw: [{"id": 1, "window_days": 7}],
        )
        monkeypatch.setattr(
            outcome_tracking, "measure_outcome",
            lambda *a, **kw: (_ for _ in ()).throw(ValueError("snapshot not found")),
        )
        result = outcome_tracking.measure_all_due()
        assert result["errors"] == 1
        assert result["measured"] == 0

    def test_measure_all_due_returns_empty_on_db_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            outcome_tracking, "get_due_snapshots_for_tenant",
            lambda **kw: (_ for _ in ()).throw(DatabaseUnavailable("offline")),
        )
        result = outcome_tracking.measure_all_due()
        assert result == {"measured": 0, "skipped": 0, "errors": 0, "results": []}


# ── format_closed_loop_summary (telegram assistant) ───────────────────────────

class TestFormatClosedLoopSummary:
    """Tests for the pure formatting function in services/telegram_assistant/outcome_tracking.py."""

    @pytest.fixture(autouse=True)
    def import_formatter(self):
        from services.telegram_assistant.outcome_tracking import format_closed_loop_summary, now_utc
        self.format = format_closed_loop_summary
        self.now_utc = now_utc

    def _summary(self, tracking=1, measured_7d=2, completed=3, due_checks=0,
                 avg_accuracy=None, recent=None):
        return {
            "tracking": tracking,
            "measured_7d": measured_7d,
            "completed": completed,
            "due_checks": due_checks,
            "avg_accuracy": avg_accuracy,
            "recent": recent or [],
        }

    def test_contains_tracking_count(self):
        text = self.format(self._summary(tracking=5))
        assert "5" in text

    def test_avg_accuracy_none_shows_not_enough_data(self):
        text = self.format(self._summary(avg_accuracy=None))
        assert "not enough" in text.lower()

    def test_avg_accuracy_formatted_as_percentage(self):
        text = self.format(self._summary(avg_accuracy=0.85))
        assert "85%" in text

    def test_good_lift_shows_good_call_verdict(self):
        recent = [{
            "decision_type": "PROMOTE",
            "brand": "Nike",
            "product_name": "Air Max",
            "sku_id": "SKU-1",
            "measurements": [{
                "window_days": 7,
                "velocity_lift_pct": 15.0,
                "revenue_delta_usd": 200.0,
                "data_available": True,
            }],
        }]
        text = self.format(self._summary(recent=recent))
        assert "Good call" in text

    def test_negative_lift_shows_below_target_verdict(self):
        recent = [{
            "decision_type": "MARKDOWN",
            "brand": "Adidas",
            "product_name": "Boost",
            "sku_id": "SKU-2",
            "measurements": [{
                "window_days": 7,
                "velocity_lift_pct": -10.0,
                "revenue_delta_usd": -50.0,
                "data_available": True,
            }],
        }]
        text = self.format(self._summary(recent=recent))
        assert "Below target" in text

    def test_neutral_lift_shows_neutral_verdict(self):
        recent = [{
            "decision_type": "PROMOTE",
            "brand": "Puma",
            "product_name": "Speed",
            "sku_id": "SKU-3",
            "measurements": [{
                "window_days": 7,
                "velocity_lift_pct": 2.0,
                "revenue_delta_usd": 10.0,
                "data_available": True,
            }],
        }]
        text = self.format(self._summary(recent=recent))
        assert "Neutral" in text

    def test_no_sales_data_message(self):
        recent = [{
            "decision_type": "PROMOTE",
            "brand": "Reebok",
            "product_name": "Classic",
            "sku_id": "SKU-4",
            "measurements": [{
                "window_days": 7,
                "velocity_lift_pct": None,
                "revenue_delta_usd": None,
                "data_available": False,
            }],
        }]
        text = self.format(self._summary(recent=recent))
        assert "no sales data" in text.lower()

    def test_no_measurements_shows_tracking(self):
        recent = [{
            "decision_type": "HOLD",
            "brand": "Vans",
            "product_name": "Old Skool",
            "sku_id": "SKU-5",
            "measurements": [],
        }]
        text = self.format(self._summary(recent=recent))
        assert "tracking" in text.lower()

    def test_ends_with_next_step_hint(self):
        text = self.format(self._summary())
        assert "Next step" in text


# ── now_utc ────────────────────────────────────────────────────────────────────

class TestNowUtc:
    def test_returns_timezone_aware_datetime(self):
        from services.telegram_assistant.outcome_tracking import now_utc
        dt = now_utc()
        assert dt.tzinfo is not None
        assert dt.tzinfo == timezone.utc

    def test_returns_recent_time(self):
        from services.telegram_assistant.outcome_tracking import now_utc
        before = datetime.now(timezone.utc)
        result = now_utc()
        after = datetime.now(timezone.utc)
        assert before <= result <= after
