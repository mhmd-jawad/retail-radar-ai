from datetime import datetime, timedelta, timezone

from eep import outcome_tracking


def test_snapshot_decision_passes_tenant_to_all_db_helpers(monkeypatch):
    calls: list[tuple[str, object]] = []

    def fake_velocity(variant_id, window_start, window_end, tenant_id=None):
        calls.append(("velocity", tenant_id))
        return {
            "velocity_daily": 0,
            "total_revenue": 0,
            "avg_unit_price": 0,
            "data_available": False,
        }

    def fake_stock(variant_id, tenant_id=None):
        calls.append(("stock", tenant_id))
        return 12

    def fake_recommendation(recommendation_id, tenant_id=None):
        calls.append(("recommendation", tenant_id))
        return {
            "confidence": 0.7,
            "explanation": "test",
            "suggested_discount_pct": 15,
            "suggested_price_usd": 85,
        }

    def fake_insert(data, tenant_id=None):
        calls.append(("insert", tenant_id))
        return 42

    monkeypatch.setattr(outcome_tracking, "query_velocity_window", fake_velocity)
    monkeypatch.setattr(outcome_tracking, "get_current_stock_for_variant", fake_stock)
    monkeypatch.setattr(outcome_tracking, "get_recommendation_by_id", fake_recommendation)
    monkeypatch.setattr(outcome_tracking, "insert_decision_snapshot", fake_insert)

    snapshot_id = outcome_tracking.snapshot_decision(
        sku_id="SKU-1",
        variant_id="variant-1",
        decision_type="MARKDOWN",
        recommendation_id="rec-1",
        cost_price_usd=40,
        tenant_id="tenant-a",
    )

    assert snapshot_id == 42
    assert calls == [
        ("velocity", "tenant-a"),
        ("stock", "tenant-a"),
        ("recommendation", "tenant-a"),
        ("insert", "tenant-a"),
    ]


def test_measure_outcome_passes_tenant_to_read_write_helpers(monkeypatch):
    approved_at = datetime.now(timezone.utc) - timedelta(days=8)
    calls: list[tuple[str, object]] = []

    def fake_snapshot(snapshot_id, tenant_id=None):
        calls.append(("snapshot", tenant_id))
        return {
            "id": snapshot_id,
            "variant_id": "variant-1",
            "approved_at": approved_at,
            "decision_type": "PROMOTE",
            "baseline_velocity_daily": 1,
            "baseline_revenue_7d": 70,
            "predicted_lift_pct": 20,
            "ie2_confidence": 0.8,
            "ie2_explanation": "test",
        }

    def fake_velocity(variant_id, window_start, window_end, tenant_id=None):
        calls.append(("velocity", tenant_id))
        return {
            "velocity_daily": 2,
            "total_revenue": 140,
            "total_units": 14,
            "avg_unit_price": 10,
            "data_available": True,
        }

    def fake_insert(data, tenant_id=None):
        calls.append(("insert", tenant_id))
        return 7

    def fake_update(snapshot_id, status, tenant_id=None):
        calls.append(("update", tenant_id))

    monkeypatch.setattr(outcome_tracking, "get_snapshot_by_id", fake_snapshot)
    monkeypatch.setattr(outcome_tracking, "query_velocity_window", fake_velocity)
    monkeypatch.setattr(outcome_tracking, "insert_outcome_measurement", fake_insert)
    monkeypatch.setattr(outcome_tracking, "update_snapshot_status", fake_update)
    monkeypatch.setattr(
        outcome_tracking,
        "_generate_narrative",
        lambda *args, **kwargs: {"narrative": None, "verified_lift_pct": None, "verified_revenue_delta": None},
    )

    result = outcome_tracking.measure_outcome(42, 7, tenant_id="tenant-a")

    assert result["measurement_id"] == 7
    assert calls == [
        ("snapshot", "tenant-a"),
        ("velocity", "tenant-a"),
        ("insert", "tenant-a"),
        ("update", "tenant-a"),
    ]


def test_outcome_read_wrappers_pass_tenant(monkeypatch):
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        outcome_tracking,
        "get_snapshots_for_variant",
        lambda variant_id, tenant_id=None: calls.append(("snapshots", tenant_id)) or [],
    )
    monkeypatch.setattr(
        outcome_tracking,
        "get_portfolio_accuracy",
        lambda decision_type=None, tenant_id=None: calls.append(("accuracy", tenant_id)) or {},
    )

    outcome_tracking.get_outcomes_for_sku("variant-1", tenant_id="tenant-a")
    outcome_tracking.get_accuracy("PROMOTE", tenant_id="tenant-a")

    assert calls == [("snapshots", "tenant-a"), ("accuracy", "tenant-a")]
