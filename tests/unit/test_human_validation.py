"""Unit tests for the Human Validation Layer (eep.human_validation_db).

Pure-logic helpers are tested directly. The DB write path (create_review) is
tested against a fake psycopg cursor so we can assert — without a live database —
that the system recommendation is frozen onto the review, that override/agreement
signals are derived correctly, that a history row is written, and that every query
is tenant-scoped.
"""

from __future__ import annotations

import contextlib

import pytest

from eep import human_validation_db as hv
from eep.human_validation_db import (
    ReviewValidationError,
    compute_agreement,
    resolve_final_decision,
    validate_review_payload,
)


# ─── Pure helpers ────────────────────────────────────────────────────────────

def test_resolve_final_decision_accept_uses_system():
    assert resolve_final_decision("accept", "MARKDOWN", None) == "MARKDOWN"
    # accept ignores any supplied alternative
    assert resolve_final_decision("accept", "HOLD", "CLEAR") == "HOLD"


def test_resolve_final_decision_override_uses_alternative():
    assert resolve_final_decision("override", "HOLD", "CLEAR") == "CLEAR"


def test_resolve_final_decision_reject_is_none():
    assert resolve_final_decision("reject", "PROMOTE", None) is None


def test_compute_agreement():
    assert compute_agreement("accept") == (False, True)
    assert compute_agreement("override") == (True, False)
    assert compute_agreement("reject") == (False, False)


def test_validate_override_requires_final_decision():
    with pytest.raises(ReviewValidationError):
        validate_review_payload("override", None, "looks wrong")


def test_validate_override_rejects_bad_decision():
    with pytest.raises(ReviewValidationError):
        validate_review_payload("override", "DISCOUNT", None)


def test_validate_reject_requires_note():
    with pytest.raises(ReviewValidationError):
        validate_review_payload("reject", None, None)
    with pytest.raises(ReviewValidationError):
        validate_review_payload("reject", None, "   ")


def test_validate_unknown_action():
    with pytest.raises(ReviewValidationError):
        validate_review_payload("maybe", None, None)


def test_validate_accept_is_permissive():
    # Should not raise.
    validate_review_payload("accept", None, None)
    validate_review_payload("override", "CLEAR", None)
    validate_review_payload("reject", None, "stock already sold through")


# ─── Fake DB harness for create_review ───────────────────────────────────────

class FakeCursor:
    def __init__(self, responses):
        self._responses = list(responses)
        self.executed: list[tuple[str, tuple]] = []
        self._last = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        # Pop a queued response when the query is a SELECT/RETURNING (i.e. fetched).
        self._last = self._responses.pop(0) if self._responses else None

    def fetchone(self):
        return self._last

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _install_fake_db(monkeypatch, responses):
    cur = FakeCursor(responses)

    @contextlib.contextmanager
    def fake_connect():
        yield FakeConn(cur)

    context_calls: list[object] = []

    def fake_context(_cur, tenant_id=None, **_kwargs):
        context_calls.append(tenant_id)
        return {"tenant_id": tenant_id or "default-tenant", "store_id": "store-1"}

    audit_calls: list[tuple] = []

    def fake_audit(_cur, tenant_id, entity_type, entity_id, action, before, after):
        audit_calls.append((tenant_id, entity_type, entity_id, action))

    monkeypatch.setattr(hv, "_connect", fake_connect)
    monkeypatch.setattr(hv, "_context", fake_context)
    monkeypatch.setattr(hv, "_audit", fake_audit)
    return cur, context_calls, audit_calls


_SYSTEM_ROW = {
    "variant_id": "11111111-1111-1111-1111-111111111111",
    "run_id": "22222222-2222-2222-2222-222222222222",
    "recommendation": "MARKDOWN",
    "confidence": 0.82,
    "model_version": "catboost_v6",
    "rule_override": None,
    "fallback_used": False,
    "requires_human_approval": True,
    "suggested_price_usd": 85.0,
    "suggested_discount_pct": 15.0,
    "decision_payload": {"recommendation": "MARKDOWN"},
    "input_context": {"days_since_launch": 40, "current_stock": 12},
    "competitor_signals": {"price_gap_pct": 0.1, "num_competitors_tracked": 3},
}

_REC_ROW = {
    "id": "33333333-3333-3333-3333-333333333333",
    "recommendation": "MARKDOWN",
    "confidence": 0.82,
    "suggested_price_usd": 85.0,
    "suggested_discount_pct": 15.0,
    "shap_features_json": [{"feature_name": "price_gap_pct", "shap_value": 0.4}],
    "rule_override_json": None,
    "model_version": "catboost_v6",
    "explanation": "Competitors are cheaper; markdown to stay competitive.",
}


def _review_row(**overrides):
    row = {
        "id": "44444444-4444-4444-4444-444444444444",
        "tenant_id": "tenant-a",
        "sku_id": "SKU-1",
        "variant_id": _SYSTEM_ROW["variant_id"],
        "recommendation_id": _REC_ROW["id"],
        "system_decision_run_id": _SYSTEM_ROW["run_id"],
        "system_recommendation": "MARKDOWN",
        "system_confidence": 0.82,
        "system_suggested_price_usd": 85.0,
        "system_suggested_discount_pct": 15.0,
        "model_version": "catboost_v6",
        "rule_override": None,
        "fallback_used": False,
        "requires_human_approval": True,
        "context_features": {"input_context": _SYSTEM_ROW["input_context"]},
        "model_metadata": {"model_version": "catboost_v6"},
        "review_action": "accept",
        "final_decision": "MARKDOWN",
        "final_price_usd": None,
        "final_discount_pct": None,
        "review_note": None,
        "is_override": False,
        "agrees_with_system": True,
        "reviewer_user_id": "user-1",
        "reviewer_email": "owner@shop.com",
        "reviewer_role": "shop",
        "reviewed_via": "web",
        "revision": 1,
        "reviewed_at": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


REVIEWER = {"user_id": "user-1", "email": "owner@shop.com", "role": "shop"}


def test_create_review_accept_freezes_system_and_is_tenant_scoped(monkeypatch):
    # Responses in query order: system_decision_latest, recommendations,
    # existing-review (none), insert ... returning *.
    cur, context_calls, audit_calls = _install_fake_db(
        monkeypatch,
        [dict(_SYSTEM_ROW), dict(_REC_ROW), None, _review_row()],
    )

    result = hv.create_review(
        sku_id="SKU-1",
        action="accept",
        final_decision=None,
        final_price_usd=None,
        final_discount_pct=None,
        note=None,
        reviewer=REVIEWER,
        tenant_id="tenant-a",
    )

    # System recommendation is frozen onto the review (never overwritten).
    assert result["system_recommendation"] == "MARKDOWN"
    assert result["final_decision"] == "MARKDOWN"
    assert result["is_override"] is False
    assert result["agrees_with_system"] is True
    # Context features captured for retraining.
    assert "input_context" in result["context_features"]
    # Tenant flowed into the DB context.
    assert "tenant-a" in context_calls
    # Audit + history were written (history is the insert with 'review_history').
    assert any(action == "review_accept" for *_, action in audit_calls)
    assert any("recommendation_review_history" in sql for sql, _ in cur.executed)


def test_create_review_override_sets_override_and_label(monkeypatch):
    review = _review_row(
        review_action="override",
        final_decision="CLEAR",
        is_override=True,
        agrees_with_system=False,
        review_note="Aged stock — clear it.",
    )
    _install_fake_db(monkeypatch, [dict(_SYSTEM_ROW), dict(_REC_ROW), None, review])

    result = hv.create_review(
        sku_id="SKU-1",
        action="override",
        final_decision="CLEAR",
        final_price_usd=None,
        final_discount_pct=None,
        note="Aged stock — clear it.",
        reviewer=REVIEWER,
        tenant_id="tenant-a",
    )

    assert result["review_action"] == "override"
    assert result["final_decision"] == "CLEAR"          # ground-truth label = human choice
    assert result["system_recommendation"] == "MARKDOWN"  # original preserved
    assert result["is_override"] is True
    assert result["agrees_with_system"] is False


def test_create_review_requires_existing_system_decision(monkeypatch):
    # No system_decision_latest row and no recommendation → cannot review.
    _install_fake_db(monkeypatch, [{}, {}, None, None])
    with pytest.raises(KeyError):
        hv.create_review(
            sku_id="SKU-NOPE",
            action="accept",
            final_decision=None,
            final_price_usd=None,
            final_discount_pct=None,
            note=None,
            reviewer=REVIEWER,
            tenant_id="tenant-a",
        )


def test_create_review_validates_before_touching_db(monkeypatch):
    cur, *_ = _install_fake_db(monkeypatch, [dict(_SYSTEM_ROW), dict(_REC_ROW), None, _review_row()])
    with pytest.raises(ReviewValidationError):
        hv.create_review(
            sku_id="SKU-1",
            action="reject",
            final_decision=None,
            final_price_usd=None,
            final_discount_pct=None,
            note=None,  # reject requires a note
            reviewer=REVIEWER,
            tenant_id="tenant-a",
        )
    # Validation must happen before any query runs.
    assert cur.executed == []
