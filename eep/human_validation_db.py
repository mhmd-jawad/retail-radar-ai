"""
Human Validation Layer — persistence.

A final human-review stage that runs *after* the system recommendation is
generated. The system recommendation itself (``marketing.recommendations`` /
``marketing.system_decision_latest``) is never modified — every review snapshots
the system decision and its full input context immutably so the data can later be
used as ground-truth labels for retraining and evaluation.

Conventions mirror :mod:`eep.retail_db`: this module reuses ``_connect``,
``_context``, ``_audit`` and the JSON/number helpers from there, is fully
tenant-isolated, and is safe to call from FastAPI background tasks.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from eep.retail_db import (
    DatabaseUnavailable,
    _audit,
    _connect,
    _context,
    _json_dumpable,
    _jsonable,
    _optional_float,
)

logger = logging.getLogger(__name__)

VALID_ACTIONS = ("accept", "override", "reject")
VALID_DECISIONS = ("HOLD", "MARKDOWN", "PROMOTE", "CLEAR")


class ReviewValidationError(ValueError):
    """Raised when a review payload is semantically invalid."""


# ─── Pure helpers (unit-testable without a database) ─────────────────────────

def resolve_final_decision(action: str, system_recommendation: str | None, final_decision: str | None) -> str | None:
    """Return the human ground-truth decision for a review.

    - accept   → the system recommendation
    - override → the supplied alternative
    - reject   → None (declined, no alternative)
    """
    if action == "accept":
        return system_recommendation
    if action == "override":
        return final_decision
    return None


def compute_agreement(action: str) -> tuple[bool, bool]:
    """Return (is_override, agrees_with_system) for a review action."""
    return (action == "override", action == "accept")


def validate_review_payload(
    action: str,
    final_decision: str | None,
    note: str | None,
) -> None:
    """Validate the semantic rules of a review action. Raises ReviewValidationError."""
    if action not in VALID_ACTIONS:
        raise ReviewValidationError(f"action must be one of {VALID_ACTIONS}")
    if action == "override":
        if not final_decision:
            raise ReviewValidationError("final_decision is required when action is 'override'")
        if final_decision not in VALID_DECISIONS:
            raise ReviewValidationError(f"final_decision must be one of {VALID_DECISIONS}")
    if action == "reject" and not (note and note.strip()):
        raise ReviewValidationError("a reason note is required when action is 'reject'")
    if final_decision is not None and final_decision not in VALID_DECISIONS:
        raise ReviewValidationError(f"final_decision must be one of {VALID_DECISIONS}")


# ─── System-decision snapshot lookup ─────────────────────────────────────────

def _fetch_system_snapshot(cur, tenant_id: Any, sku_id: str) -> dict[str, Any]:
    """Read the current system decision + full context for a SKU.

    Returns a dict with the frozen system fields and a ``context_features`` blob
    assembled from input_context, competitor_signals, decision_payload and SHAP.
    """
    cur.execute(
        """
        select sdl.variant_id, sdl.run_id, sdl.recommendation, sdl.confidence,
               sdl.model_version, sdl.rule_override, sdl.fallback_used,
               sdl.requires_human_approval, sdl.suggested_price_usd,
               sdl.suggested_discount_pct, sdl.decision_payload, sdl.input_context,
               sdl.competitor_signals
        from marketing.system_decision_latest sdl
        where sdl.tenant_id = %s and sdl.sku_id = %s
        """,
        (tenant_id, sku_id),
    )
    row = cur.fetchone() or {}

    # SHAP / rule detail from the richer recommendations row, if present.
    cur.execute(
        """
        select id, recommendation, confidence, suggested_price_usd, suggested_discount_pct,
               shap_features_json, rule_override_json, model_version, explanation
        from marketing.recommendations
        where tenant_id = %s and variant_id = %s
        order by generated_at desc
        limit 1
        """,
        (tenant_id, row.get("variant_id")),
    )
    rec = cur.fetchone() or {}

    context_features = {
        "input_context": _jsonable(row.get("input_context")),
        "competitor_signals": _jsonable(row.get("competitor_signals")),
        "decision_payload": _jsonable(row.get("decision_payload")),
        "shap_features": _jsonable(rec.get("shap_features_json")) if rec else None,
        "rule_override_detail": _jsonable(rec.get("rule_override_json")) if rec else None,
        "explanation": rec.get("explanation"),
    }
    model_metadata = {
        "model_version": row.get("model_version") or rec.get("model_version"),
        "rule_override": row.get("rule_override"),
        "fallback_used": bool(row.get("fallback_used")),
        "requires_human_approval": bool(row.get("requires_human_approval")),
    }

    return {
        "variant_id": str(row["variant_id"]) if row.get("variant_id") else None,
        "system_decision_run_id": str(row["run_id"]) if row.get("run_id") else None,
        "recommendation_id": str(rec["id"]) if rec.get("id") else None,
        "system_recommendation": row.get("recommendation") or rec.get("recommendation"),
        "system_confidence": _optional_float(row.get("confidence") if row.get("confidence") is not None else rec.get("confidence")),
        "system_suggested_price_usd": _optional_float(row.get("suggested_price_usd") if row.get("suggested_price_usd") is not None else rec.get("suggested_price_usd")),
        "system_suggested_discount_pct": _optional_float(row.get("suggested_discount_pct") if row.get("suggested_discount_pct") is not None else rec.get("suggested_discount_pct")),
        "model_version": row.get("model_version") or rec.get("model_version"),
        "rule_override": row.get("rule_override"),
        "fallback_used": bool(row.get("fallback_used")),
        "requires_human_approval": bool(row.get("requires_human_approval")),
        "context_features": context_features,
        "model_metadata": model_metadata,
    }


def _serialize_review(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "tenant_id": str(row.get("tenant_id")),
        "sku_id": row.get("sku_id"),
        "variant_id": str(row["variant_id"]) if row.get("variant_id") else None,
        "recommendation_id": str(row["recommendation_id"]) if row.get("recommendation_id") else None,
        "system_decision_run_id": str(row["system_decision_run_id"]) if row.get("system_decision_run_id") else None,
        "system_recommendation": row.get("system_recommendation"),
        "system_confidence": _optional_float(row.get("system_confidence")),
        "system_suggested_price_usd": _optional_float(row.get("system_suggested_price_usd")),
        "system_suggested_discount_pct": _optional_float(row.get("system_suggested_discount_pct")),
        "model_version": row.get("model_version"),
        "rule_override": row.get("rule_override"),
        "fallback_used": bool(row.get("fallback_used")),
        "requires_human_approval": bool(row.get("requires_human_approval")),
        "context_features": _jsonable(row.get("context_features")),
        "model_metadata": _jsonable(row.get("model_metadata")),
        "review_action": row.get("review_action"),
        "final_decision": row.get("final_decision"),
        "final_price_usd": _optional_float(row.get("final_price_usd")),
        "final_discount_pct": _optional_float(row.get("final_discount_pct")),
        "review_note": row.get("review_note"),
        "is_override": bool(row.get("is_override")),
        "agrees_with_system": bool(row.get("agrees_with_system")),
        "reviewer_user_id": str(row["reviewer_user_id"]) if row.get("reviewer_user_id") else None,
        "reviewer_email": row.get("reviewer_email"),
        "reviewer_role": row.get("reviewer_role"),
        "reviewed_via": row.get("reviewed_via"),
        "revision": int(row.get("revision") or 1),
        "reviewed_at": _jsonable(row.get("reviewed_at")),
        "created_at": _jsonable(row.get("created_at")),
        "updated_at": _jsonable(row.get("updated_at")),
        "product_name": row.get("product_name"),
        "brand": row.get("brand"),
        "category": row.get("category"),
    }


def _write_history(
    cur,
    *,
    review_id: str,
    tenant_id: Any,
    revision: int,
    action: str,
    before_state: Any,
    after_state: Any,
    changed_by_user_id: str | None,
    changed_by_email: str | None,
    change_reason: str | None,
) -> None:
    cur.execute(
        """
        insert into marketing.recommendation_review_history (
            review_id, tenant_id, revision, action, before_state, after_state,
            changed_by_user_id, changed_by_email, change_reason
        )
        values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
        """,
        (
            review_id,
            tenant_id,
            revision,
            action,
            json.dumps(_json_dumpable(before_state)) if before_state is not None else None,
            json.dumps(_json_dumpable(after_state)) if after_state is not None else None,
            changed_by_user_id,
            changed_by_email,
            change_reason,
        ),
    )


# ─── Write operations ────────────────────────────────────────────────────────

def create_review(
    *,
    sku_id: str,
    action: str,
    final_decision: str | None,
    final_price_usd: float | None,
    final_discount_pct: float | None,
    note: str | None,
    reviewer: dict[str, Any],
    recommendation_id: str | None = None,
    reviewed_via: str = "web",
    tenant_id: Any | None = None,
) -> dict[str, Any]:
    """Create or replace the current review for a SKU (upsert), with audit + history.

    The system snapshot is read from the live system decision and frozen onto the
    review row. On re-review of the same SKU the row is updated in place, the
    revision is bumped, and an ``updated`` history record is written.
    """
    validate_review_payload(action, final_decision, note)

    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            tid = ctx["tenant_id"]

            snapshot = _fetch_system_snapshot(cur, tid, sku_id)
            system_recommendation = snapshot.get("system_recommendation")
            if not system_recommendation:
                raise KeyError(
                    f"No system recommendation found for SKU {sku_id}. Sync the system decision first."
                )

            resolved_final = resolve_final_decision(action, system_recommendation, final_decision)
            is_override, agrees = compute_agreement(action)

            # Existing current review (for revision + history before_state)
            cur.execute(
                "select * from marketing.recommendation_reviews where tenant_id = %s and sku_id = %s",
                (tid, sku_id),
            )
            existing = cur.fetchone()
            revision = (int(existing["revision"]) + 1) if existing else 1

            variant_id = snapshot.get("variant_id")
            resolved_rec_id = recommendation_id or snapshot.get("recommendation_id")

            params = (
                tid,
                sku_id,
                variant_id,
                resolved_rec_id,
                snapshot.get("system_decision_run_id"),
                system_recommendation,
                snapshot.get("system_confidence"),
                snapshot.get("system_suggested_price_usd"),
                snapshot.get("system_suggested_discount_pct"),
                snapshot.get("model_version"),
                snapshot.get("rule_override"),
                snapshot.get("fallback_used"),
                snapshot.get("requires_human_approval"),
                json.dumps(_json_dumpable(snapshot.get("context_features"))),
                json.dumps(_json_dumpable(snapshot.get("model_metadata"))),
                action,
                resolved_final,
                final_price_usd,
                final_discount_pct,
                note,
                is_override,
                agrees,
                reviewer.get("user_id"),
                reviewer.get("email"),
                reviewer.get("role"),
                reviewed_via,
                revision,
            )

            cur.execute(
                """
                insert into marketing.recommendation_reviews (
                    tenant_id, sku_id, variant_id, recommendation_id, system_decision_run_id,
                    system_recommendation, system_confidence, system_suggested_price_usd,
                    system_suggested_discount_pct, model_version, rule_override, fallback_used,
                    requires_human_approval, context_features, model_metadata,
                    review_action, final_decision, final_price_usd, final_discount_pct, review_note,
                    is_override, agrees_with_system,
                    reviewer_user_id, reviewer_email, reviewer_role, reviewed_via,
                    revision, reviewed_at, updated_at
                )
                values (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, now(), now()
                )
                on conflict (tenant_id, sku_id) do update set
                    variant_id = excluded.variant_id,
                    recommendation_id = excluded.recommendation_id,
                    system_decision_run_id = excluded.system_decision_run_id,
                    system_recommendation = excluded.system_recommendation,
                    system_confidence = excluded.system_confidence,
                    system_suggested_price_usd = excluded.system_suggested_price_usd,
                    system_suggested_discount_pct = excluded.system_suggested_discount_pct,
                    model_version = excluded.model_version,
                    rule_override = excluded.rule_override,
                    fallback_used = excluded.fallback_used,
                    requires_human_approval = excluded.requires_human_approval,
                    context_features = excluded.context_features,
                    model_metadata = excluded.model_metadata,
                    review_action = excluded.review_action,
                    final_decision = excluded.final_decision,
                    final_price_usd = excluded.final_price_usd,
                    final_discount_pct = excluded.final_discount_pct,
                    review_note = excluded.review_note,
                    is_override = excluded.is_override,
                    agrees_with_system = excluded.agrees_with_system,
                    reviewer_user_id = excluded.reviewer_user_id,
                    reviewer_email = excluded.reviewer_email,
                    reviewer_role = excluded.reviewer_role,
                    reviewed_via = excluded.reviewed_via,
                    revision = excluded.revision,
                    reviewed_at = now(),
                    updated_at = now()
                returning *
                """,
                params,
            )
            review = cur.fetchone()
            review_id = str(review["id"])

            _write_history(
                cur,
                review_id=review_id,
                tenant_id=tid,
                revision=revision,
                action="updated" if existing else "created",
                before_state=_serialize_review(existing) if existing else None,
                after_state=_serialize_review(review),
                changed_by_user_id=reviewer.get("user_id"),
                changed_by_email=reviewer.get("email"),
                change_reason=note,
            )
            _audit(
                cur,
                tid,
                "recommendation_review",
                sku_id,
                f"review_{action}",
                _serialize_review(existing) if existing else None,
                _serialize_review(review),
            )

    return _serialize_review(review)


def update_review(
    review_id: str,
    *,
    action: str | None = None,
    final_decision: str | None = None,
    final_price_usd: float | None = None,
    final_discount_pct: float | None = None,
    note: str | None = None,
    reviewer: dict[str, Any] | None = None,
    tenant_id: Any | None = None,
) -> dict[str, Any]:
    """Edit an existing review in place (audit-tracked). The system snapshot stays frozen."""
    reviewer = reviewer or {}
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            tid = ctx["tenant_id"]
            cur.execute(
                "select * from marketing.recommendation_reviews where id = %s and tenant_id = %s",
                (review_id, tid),
            )
            existing = cur.fetchone()
            if not existing:
                raise KeyError(review_id)

            new_action = action or existing["review_action"]
            new_final = final_decision if final_decision is not None else existing["final_decision"]
            new_note = note if note is not None else existing["review_note"]
            validate_review_payload(new_action, new_final if new_action == "override" else new_final, new_note)

            resolved_final = resolve_final_decision(new_action, existing["system_recommendation"], new_final)
            is_override, agrees = compute_agreement(new_action)
            revision = int(existing["revision"]) + 1

            cur.execute(
                """
                update marketing.recommendation_reviews set
                    review_action = %s,
                    final_decision = %s,
                    final_price_usd = %s,
                    final_discount_pct = %s,
                    review_note = %s,
                    is_override = %s,
                    agrees_with_system = %s,
                    reviewer_user_id = coalesce(%s, reviewer_user_id),
                    reviewer_email = coalesce(%s, reviewer_email),
                    reviewer_role = coalesce(%s, reviewer_role),
                    revision = %s,
                    reviewed_at = now(),
                    updated_at = now()
                where id = %s and tenant_id = %s
                returning *
                """,
                (
                    new_action,
                    resolved_final,
                    final_price_usd if final_price_usd is not None else existing["final_price_usd"],
                    final_discount_pct if final_discount_pct is not None else existing["final_discount_pct"],
                    new_note,
                    is_override,
                    agrees,
                    reviewer.get("user_id"),
                    reviewer.get("email"),
                    reviewer.get("role"),
                    revision,
                    review_id,
                    tid,
                ),
            )
            review = cur.fetchone()
            _write_history(
                cur,
                review_id=review_id,
                tenant_id=tid,
                revision=revision,
                action="updated",
                before_state=_serialize_review(existing),
                after_state=_serialize_review(review),
                changed_by_user_id=reviewer.get("user_id"),
                changed_by_email=reviewer.get("email"),
                change_reason=note,
            )
            _audit(
                cur,
                tid,
                "recommendation_review",
                str(existing["sku_id"]),
                "review_edit",
                _serialize_review(existing),
                _serialize_review(review),
            )
    return _serialize_review(review)


# ─── Read operations ─────────────────────────────────────────────────────────

def _select_with_product(where: str) -> str:
    return f"""
        select r.*, p.name as product_name, p.brand, p.category
        from marketing.recommendation_reviews r
        left join core.sku_variants v on v.tenant_id = r.tenant_id and v.sku_id = r.sku_id
        left join core.products p on p.id = v.product_id
        where {where}
    """


def list_reviews(
    tenant_id: Any | None = None,
    *,
    action: str | None = None,
    model_version: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            params: list[Any] = [ctx["tenant_id"]]
            conditions = ["r.tenant_id = %s"]
            if action:
                conditions.append("r.review_action = %s")
                params.append(action)
            if model_version:
                conditions.append("r.model_version = %s")
                params.append(model_version)
            params.extend([limit, offset])
            cur.execute(
                _select_with_product(" and ".join(conditions))
                + " order by r.reviewed_at desc limit %s offset %s",
                params,
            )
            return [_serialize_review(row) for row in cur.fetchall()]


def get_review(review_id: str, tenant_id: Any | None = None) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            cur.execute(
                _select_with_product("r.id = %s and r.tenant_id = %s"),
                (review_id, ctx["tenant_id"]),
            )
            row = cur.fetchone()
            return _serialize_review(row) if row else None


def get_current_review_for_sku(sku_id: str, tenant_id: Any | None = None) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            cur.execute(
                _select_with_product("r.sku_id = %s and r.tenant_id = %s"),
                (sku_id, ctx["tenant_id"]),
            )
            row = cur.fetchone()
            return _serialize_review(row) if row else None


def get_review_history(review_id: str, tenant_id: Any | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            cur.execute(
                """
                select h.*
                from marketing.recommendation_review_history h
                where h.review_id = %s and h.tenant_id = %s
                order by h.revision asc, h.created_at asc
                """,
                (review_id, ctx["tenant_id"]),
            )
            return [
                {
                    "id": int(row["id"]),
                    "review_id": str(row["review_id"]),
                    "revision": int(row["revision"]),
                    "action": row["action"],
                    "before_state": _jsonable(row.get("before_state")),
                    "after_state": _jsonable(row.get("after_state")),
                    "changed_by_email": row.get("changed_by_email"),
                    "change_reason": row.get("change_reason"),
                    "created_at": _jsonable(row.get("created_at")),
                }
                for row in cur.fetchall()
            ]


# ─── Analytics ───────────────────────────────────────────────────────────────

def get_review_analytics(tenant_id: Any | None = None, model_version: str | None = None) -> dict[str, Any]:
    """Acceptance/override/agreement metrics + a weekly trend for the tenant."""
    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            params: list[Any] = [ctx["tenant_id"]]
            extra = ""
            if model_version:
                extra = " and model_version = %s"
                params.append(model_version)

            cur.execute(
                f"""
                select
                    count(*) as total_reviews,
                    count(*) filter (where review_action = 'accept') as accept_count,
                    count(*) filter (where review_action = 'override') as override_count,
                    count(*) filter (where review_action = 'reject') as reject_count,
                    coalesce(round(avg((review_action = 'accept')::int)::numeric, 4), 0) as acceptance_rate,
                    coalesce(round(avg((is_override)::int)::numeric, 4), 0) as override_rate,
                    coalesce(round(avg((agrees_with_system)::int)::numeric, 4), 0) as agreement_rate
                from marketing.recommendation_reviews
                where tenant_id = %s{extra}
                """,
                params,
            )
            totals = cur.fetchone() or {}

            # Per system-decision-class breakdown (from the analytics view)
            cur.execute(
                f"""
                select system_recommendation, model_version, total_reviews,
                       accept_count, override_count, reject_count,
                       acceptance_rate, override_rate, agreement_rate
                from marketing.v_recommendation_review_analytics
                where tenant_id = %s{extra}
                order by system_recommendation
                """,
                params,
            )
            by_decision = [
                {
                    "system_recommendation": row["system_recommendation"],
                    "model_version": row["model_version"],
                    "total_reviews": int(row["total_reviews"]),
                    "accept_count": int(row["accept_count"]),
                    "override_count": int(row["override_count"]),
                    "reject_count": int(row["reject_count"]),
                    "acceptance_rate": _optional_float(row["acceptance_rate"]),
                    "override_rate": _optional_float(row["override_rate"]),
                    "agreement_rate": _optional_float(row["agreement_rate"]),
                }
                for row in cur.fetchall()
            ]

            # Weekly trend over time
            cur.execute(
                f"""
                select date_trunc('week', reviewed_at) as week,
                       count(*) as total_reviews,
                       coalesce(round(avg((review_action = 'accept')::int)::numeric, 4), 0) as acceptance_rate,
                       coalesce(round(avg((is_override)::int)::numeric, 4), 0) as override_rate
                from marketing.recommendation_reviews
                where tenant_id = %s{extra}
                group by 1
                order by 1 asc
                """,
                params,
            )
            trend = [
                {
                    "week": _jsonable(row["week"]),
                    "total_reviews": int(row["total_reviews"]),
                    "acceptance_rate": _optional_float(row["acceptance_rate"]),
                    "override_rate": _optional_float(row["override_rate"]),
                }
                for row in cur.fetchall()
            ]

    return {
        "total_reviews": int(totals.get("total_reviews") or 0),
        "accept_count": int(totals.get("accept_count") or 0),
        "override_count": int(totals.get("override_count") or 0),
        "reject_count": int(totals.get("reject_count") or 0),
        "acceptance_rate": _optional_float(totals.get("acceptance_rate")),
        "override_rate": _optional_float(totals.get("override_rate")),
        "agreement_rate": _optional_float(totals.get("agreement_rate")),
        "by_decision": by_decision,
        "trend": trend,
        "model_version": model_version,
    }


def get_review_analytics_cross_tenant(model_version: str | None = None) -> dict[str, Any]:
    """Admin-only: aggregate human-vs-system metrics across all tenants, by model version."""
    with _connect() as conn:
        with conn.cursor() as cur:
            params: list[Any] = []
            where = ""
            if model_version:
                where = "where model_version = %s"
                params.append(model_version)
            cur.execute(
                f"""
                select coalesce(model_version, 'unknown') as model_version,
                       count(*) as total_reviews,
                       count(*) filter (where review_action = 'accept') as accept_count,
                       count(*) filter (where review_action = 'override') as override_count,
                       count(*) filter (where review_action = 'reject') as reject_count,
                       coalesce(round(avg((review_action = 'accept')::int)::numeric, 4), 0) as acceptance_rate,
                       coalesce(round(avg((is_override)::int)::numeric, 4), 0) as override_rate,
                       coalesce(round(avg((agrees_with_system)::int)::numeric, 4), 0) as agreement_rate
                from marketing.recommendation_reviews
                {where}
                group by coalesce(model_version, 'unknown')
                order by total_reviews desc
                """,
                params,
            )
            by_model = [
                {
                    "model_version": row["model_version"],
                    "total_reviews": int(row["total_reviews"]),
                    "accept_count": int(row["accept_count"]),
                    "override_count": int(row["override_count"]),
                    "reject_count": int(row["reject_count"]),
                    "acceptance_rate": _optional_float(row["acceptance_rate"]),
                    "override_rate": _optional_float(row["override_rate"]),
                    "agreement_rate": _optional_float(row["agreement_rate"]),
                }
                for row in cur.fetchall()
            ]
    totals = {
        "total_reviews": sum(m["total_reviews"] for m in by_model),
        "accept_count": sum(m["accept_count"] for m in by_model),
        "override_count": sum(m["override_count"] for m in by_model),
        "reject_count": sum(m["reject_count"] for m in by_model),
    }
    return {"totals": totals, "by_model_version": by_model}


# ─── Retraining export ───────────────────────────────────────────────────────

def export_training_labels(
    tenant_id: Any | None = None,
    *,
    since: datetime | None = None,
    include_unlabeled: bool = False,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Pull human-reviewed ground-truth labels for retraining from the SQL view.

    When ``tenant_id`` is None, exports across all tenants (admin use). By default
    rows with no ground-truth label (reject-without-alternative) are excluded.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            params: list[Any] = []
            conditions: list[str] = []
            if tenant_id is not None:
                ctx = _context(cur, tenant_id=tenant_id)
                conditions.append("tenant_id = %s")
                params.append(ctx["tenant_id"])
            if not include_unlabeled:
                conditions.append("ground_truth_label is not null")
            if since is not None:
                conditions.append("reviewed_at >= %s")
                params.append(since)
            where = (" where " + " and ".join(conditions)) if conditions else ""
            params.append(limit)
            cur.execute(
                f"""
                select review_id, tenant_id, sku_id, variant_id, context_features,
                       system_recommendation, ground_truth_label, review_action,
                       is_override, agrees_with_system, final_price_usd, final_discount_pct,
                       model_version, rule_override, fallback_used, system_confidence,
                       reviewer_email, reviewed_at
                from marketing.v_recommendation_training_labels
                {where}
                order by reviewed_at desc
                limit %s
                """,
                params,
            )
            rows = cur.fetchall()
    return [
        {
            "review_id": str(row["review_id"]),
            "tenant_id": str(row["tenant_id"]),
            "sku_id": row["sku_id"],
            "variant_id": str(row["variant_id"]) if row.get("variant_id") else None,
            "context_features": _jsonable(row.get("context_features")),
            "system_recommendation": row.get("system_recommendation"),
            "ground_truth_label": row.get("ground_truth_label"),
            "review_action": row.get("review_action"),
            "is_override": bool(row.get("is_override")),
            "agrees_with_system": bool(row.get("agrees_with_system")),
            "final_price_usd": _optional_float(row.get("final_price_usd")),
            "final_discount_pct": _optional_float(row.get("final_discount_pct")),
            "model_version": row.get("model_version"),
            "rule_override": row.get("rule_override"),
            "fallback_used": bool(row.get("fallback_used")),
            "system_confidence": _optional_float(row.get("system_confidence")),
            "reviewer_email": row.get("reviewer_email"),
            "reviewed_at": _jsonable(row.get("reviewed_at")),
        }
        for row in rows
    ]
