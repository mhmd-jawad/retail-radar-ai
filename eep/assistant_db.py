"""
Retailer assistant tool query functions.

Synchronous DB queries (same _connect() pattern as retail_db.py) that back
the 14 Claude tool calls exposed via POST /chat.  Each function is scoped
to a single tenant_id — no cross-tenant data ever appears.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from eep.retail_db import _connect, DatabaseUnavailable


# ── helpers ────────────────────────────────────────────────────────────────────

def _f(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _i(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _normalize_value(v: Any) -> Any:
    """Convert Decimal/date/datetime to JSON-serialisable types."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {k: _normalize_value(v) for k, v in dict(row).items()}


# ── competitor list (used for system prompt) ───────────────────────────────────

def get_competitor_list(tenant_id: str) -> list[str]:
    """Return shop codes of active competitors tracked by this tenant."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tc.shop_code
                    FROM intel.tenant_competitors tc
                    WHERE tc.tenant_id = %s::uuid AND tc.is_active = true
                    ORDER BY tc.shop_code
                    """,
                    (tenant_id,),
                )
                rows = cur.fetchall()
        return [r["shop_code"] for r in rows]
    except Exception:
        return []


# ── inventory ──────────────────────────────────────────────────────────────────

def get_inventory_overview(tenant_id: str) -> dict[str, Any]:
    """Total SKU count, units on hand, inventory value, low-stock and dead-stock lists."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    sv.sku_id,
                    p.name  AS product_name,
                    p.brand,
                    p.category,
                    COALESCE(SUM(ib.quantity_on_hand), 0)::int AS current_stock,
                    sv.cost_price_usd,
                    sv.reorder_point,
                    COALESCE(pr.amount, 0) AS retail_price_usd
                FROM core.sku_variants sv
                JOIN core.products p ON sv.product_id = p.id
                LEFT JOIN core.inventory_balances ib ON ib.variant_id = sv.id
                LEFT JOIN LATERAL (
                    SELECT amount FROM core.prices
                    WHERE variant_id = sv.id
                      AND price_type = 'retail'
                      AND valid_to IS NULL
                    LIMIT 1
                ) pr ON true
                WHERE sv.tenant_id = %s::uuid
                  AND sv.status = 'active'
                  AND p.status = 'active'
                GROUP BY sv.id, sv.sku_id, p.name, p.brand, p.category,
                         sv.cost_price_usd, sv.reorder_point, pr.amount
                ORDER BY current_stock ASC
                """,
                (tenant_id,),
            )
            items = [_row_to_dict(r) for r in cur.fetchall()]

    total_sku_count = len(items)
    total_units = sum(_i(i.get("current_stock")) for i in items)
    total_value = round(
        sum(_f(i.get("current_stock")) * _f(i.get("cost_price_usd")) for i in items), 2
    )
    low_stock = [
        {
            "sku_id": i["sku_id"],
            "product_name": i["product_name"],
            "brand": i["brand"],
            "units": _i(i["current_stock"]),
            "reorder_point": _i(i.get("reorder_point")),
            "retail_price_usd": _f(i.get("retail_price_usd")),
        }
        for i in items
        if 0 < _i(i.get("current_stock")) <= max(_i(i.get("reorder_point") or 5), 5)
    ][:10]
    dead_stock = sorted(
        [
            {
                "sku_id": i["sku_id"],
                "product_name": i["product_name"],
                "brand": i["brand"],
                "units": _i(i["current_stock"]),
                "value_usd": round(_f(i["current_stock"]) * _f(i.get("cost_price_usd")), 2),
            }
            for i in items
            if _i(i.get("current_stock")) > 30 and _f(i.get("retail_price_usd")) == 0
        ],
        key=lambda x: x["value_usd"],
        reverse=True,
    )[:10]

    result: dict[str, Any] = {
        "total_sku_count": total_sku_count,
        "total_units": total_units,
        "total_inventory_value_usd": total_value,
        "low_stock_count": len(low_stock),
        "low_stock_skus": low_stock,
        "dead_stock_count": len(dead_stock),
        "dead_stock_skus": dead_stock,
    }

    dead_value = sum(d["value_usd"] for d in dead_stock)
    if total_value > 0 and dead_value / total_value > 0.15:
        result["proactive_insight"] = (
            f"Dead stock is {dead_value / total_value * 100:.0f}% "
            f"(${dead_value:,.0f}) of inventory value — consider a markdown bundle."
        )
    elif len(low_stock) >= 5:
        result["proactive_insight"] = (
            f"{len(low_stock)} SKUs are at or below their reorder point. "
            "Prioritise reorders."
        )

    return result


def get_stockout_days(tenant_id: str) -> list[dict[str, Any]]:
    """Days until stockout for low-stock SKUs, based on 30-day velocity."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH recent_velocity AS (
                    SELECT sv.id AS variant_id,
                           COALESCE(SUM(ti.quantity)::float / 30.0, 0) AS daily_velocity
                    FROM core.sku_variants sv
                    LEFT JOIN core.inventory_movements ti ON ti.variant_id = sv.id
                        AND ti.movement_type = 'sale'
                        AND ti.created_at >= now() - interval '30 days'
                    WHERE sv.tenant_id = %s::uuid AND sv.status = 'active'
                    GROUP BY sv.id
                )
                SELECT sv.sku_id,
                       p.name                                          AS product_name,
                       p.brand,
                       COALESCE(SUM(ib.quantity_on_hand), 0)::int     AS units_on_hand,
                       ROUND(rv.daily_velocity::numeric, 2)            AS daily_velocity,
                       CASE WHEN rv.daily_velocity > 0
                            THEN ROUND(
                                COALESCE(SUM(ib.quantity_on_hand), 0) / rv.daily_velocity
                            )::int
                            ELSE NULL
                       END                                             AS days_until_stockout,
                       sv.reorder_point
                FROM core.sku_variants sv
                JOIN core.products p ON p.id = sv.product_id
                LEFT JOIN core.inventory_balances ib ON ib.variant_id = sv.id
                LEFT JOIN recent_velocity rv ON rv.variant_id = sv.id
                WHERE sv.tenant_id = %s::uuid AND sv.status = 'active'
                GROUP BY sv.id, sv.sku_id, p.name, p.brand, sv.reorder_point, rv.daily_velocity
                HAVING COALESCE(SUM(ib.quantity_on_hand), 0) <= GREATEST(sv.reorder_point, 5)
                   AND COALESCE(SUM(ib.quantity_on_hand), 0) > 0
                ORDER BY days_until_stockout ASC NULLS LAST
                LIMIT 15
                """,
                (tenant_id, tenant_id),
            )
            rows = cur.fetchall()
    return [
        {
            "sku_id": r["sku_id"],
            "product_name": r["product_name"],
            "brand": r["brand"],
            "units_on_hand": _i(r["units_on_hand"]),
            "daily_velocity": _f(r["daily_velocity"]),
            "days_until_stockout": _i(r["days_until_stockout"]) if r["days_until_stockout"] is not None else None,
            "reorder_point": _i(r["reorder_point"]),
        }
        for r in rows
    ]


def get_reorder_suggestions(tenant_id: str) -> list[dict[str, Any]]:
    """Suggested reorder quantities for SKUs at or near their reorder point."""
    stockout_rows = get_stockout_days(tenant_id)
    if not stockout_rows:
        return []

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sv.sku_id, sv.cost_price_usd
                FROM core.sku_variants sv
                WHERE sv.tenant_id = %s::uuid AND sv.status = 'active'
                """,
                (tenant_id,),
            )
            cost_rows = cur.fetchall()

    cost_map = {r["sku_id"]: _f(r.get("cost_price_usd")) for r in cost_rows}
    suggestions = []
    for item in stockout_rows:
        daily_vel = _f(item["daily_velocity"])
        units_on_hand = _i(item["units_on_hand"])
        needed = max(int(daily_vel * 14 * 1.2) - units_on_hand, 1) if daily_vel > 0 else _i(item.get("reorder_point"))
        cost = cost_map.get(item["sku_id"], 0.0)
        suggestions.append({
            "sku_id": item["sku_id"],
            "product_name": item["product_name"],
            "brand": item["brand"],
            "units_on_hand": units_on_hand,
            "suggested_order_qty": needed,
            "estimated_cost_usd": round(needed * cost, 2),
            "days_until_stockout": item["days_until_stockout"],
            "daily_velocity": daily_vel,
        })
    suggestions.sort(key=lambda x: (x["days_until_stockout"] or 999))
    return suggestions


def get_sku_velocity_trend(tenant_id: str, sku_id: str, days: int = 30) -> dict[str, Any]:
    """Daily sales velocity for a specific SKU over 7, 14, or 30 days."""
    days_safe = days if days in (7, 14, 30) else 30
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    date_trunc('day', im.created_at)::date AS day,
                    SUM(im.quantity_delta)::int             AS units_sold,
                    ROUND(COALESCE(SUM(im.quantity_delta * im.unit_price_usd), 0)::numeric, 2) AS revenue_usd
                FROM core.inventory_movements im
                JOIN core.sku_variants sv ON sv.id = im.variant_id
                WHERE sv.sku_id = %s
                  AND sv.tenant_id = %s::uuid
                  AND im.movement_type = 'sale'
                  AND im.created_at >= now() - interval '{days_safe} days'
                GROUP BY 1
                ORDER BY 1
                """,
                (sku_id, tenant_id),
            )
            rows = cur.fetchall()

    daily = [
        {"day": str(r["day"]), "units_sold": _i(r["units_sold"]), "revenue_usd": _f(r["revenue_usd"])}
        for r in rows
    ]
    if not daily:
        return {"sku_id": sku_id, "days": days_safe, "daily": [], "trend": "no_data"}

    mid = len(daily) // 2
    first_half_avg = sum(d["units_sold"] for d in daily[:mid]) / max(mid, 1)
    second_half_avg = sum(d["units_sold"] for d in daily[mid:]) / max(len(daily) - mid, 1)
    trend = (
        "accelerating" if second_half_avg > first_half_avg * 1.1
        else "decelerating" if second_half_avg < first_half_avg * 0.9
        else "stable"
    )
    total_units = sum(d["units_sold"] for d in daily)
    total_revenue = sum(d["revenue_usd"] for d in daily)
    return {
        "sku_id": sku_id,
        "days": days_safe,
        "total_units_sold": total_units,
        "total_revenue_usd": round(total_revenue, 2),
        "daily_avg_units": round(total_units / days_safe, 2),
        "trend": trend,
        "daily": daily,
    }


def get_category_performance(tenant_id: str, days: int = 30) -> list[dict[str, Any]]:
    """Revenue, units sold, margin, and SKU count by product category."""
    days_safe = days if days in (7, 14, 30) else 30
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    p.category,
                    COUNT(DISTINCT sv.id)                            AS sku_count,
                    SUM(im.quantity_delta)::int                      AS units_sold,
                    ROUND(COALESCE(SUM(im.quantity_delta * im.unit_price_usd), 0)::numeric, 2) AS revenue_usd,
                    ROUND(
                        AVG(
                            CASE WHEN im.unit_price_usd > 0
                                 THEN (im.unit_price_usd - sv.cost_price_usd) / im.unit_price_usd * 100
                            END
                        )::numeric, 1
                    ) AS avg_margin_pct
                FROM core.inventory_movements im
                JOIN core.sku_variants sv ON sv.id = im.variant_id
                JOIN core.products p ON p.id = sv.product_id
                WHERE sv.tenant_id = %s::uuid
                  AND im.movement_type = 'sale'
                  AND im.created_at >= now() - interval '{days_safe} days'
                GROUP BY p.category
                ORDER BY revenue_usd DESC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
    return [
        {
            "category": r["category"],
            "sku_count": _i(r["sku_count"]),
            "units_sold": _i(r["units_sold"]),
            "revenue_usd": _f(r["revenue_usd"]),
            "avg_margin_pct": _f(r["avg_margin_pct"]) if r["avg_margin_pct"] is not None else None,
        }
        for r in rows
    ]


# ── competitor prices ──────────────────────────────────────────────────────────

def get_competitor_prices(
    tenant_id: str,
    sku_id: str | None = None,
    competitor_name: str | None = None,
) -> list[dict[str, Any]]:
    """Competitor price comparison for SKUs we carry, optionally filtered."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (sv.sku_id)
                    sv.sku_id                    AS our_sku,
                    p.name                       AS our_product,
                    p.brand,
                    COALESCE(pr.amount, 0)       AS our_price_usd,
                    cl.shop_code                 AS competitor,
                    cl.product_name              AS competitor_product,
                    COALESCE(cl.competitor_sale_price, cl.competitor_price) AS effective_comp_price,
                    cl.competitor_price,
                    cl.competitor_sale_price,
                    cl.currency,
                    cl.is_on_sale,
                    cl.availability,
                    cl.last_seen_at
                FROM intel.competitor_products_latest cl
                JOIN intel.tenant_competitors tc
                    ON tc.shop_code = cl.shop_code
                   AND tc.tenant_id = %s::uuid
                   AND tc.is_active = true
                JOIN core.sku_variants sv
                    ON sv.style_code = cl.style_code
                   AND sv.tenant_id = %s::uuid
                JOIN core.products p ON sv.product_id = p.id
                LEFT JOIN LATERAL (
                    SELECT amount FROM core.prices
                    WHERE variant_id = sv.id
                      AND price_type = 'retail'
                      AND valid_to IS NULL
                    LIMIT 1
                ) pr ON true
                WHERE cl.data_valid = true
                ORDER BY sv.sku_id, cl.competitor_price ASC
                LIMIT 50
                """,
                (tenant_id, tenant_id),
            )
            rows = cur.fetchall()

    result = []
    for r in rows:
        our = _f(r["our_price_usd"])
        comp = _f(r["effective_comp_price"])
        gap_pct = round((our - comp) / comp * 100, 1) if comp > 0 and our > 0 else None
        result.append({
            "our_sku": r["our_sku"],
            "our_product": r["our_product"],
            "brand": r["brand"],
            "our_price_usd": our,
            "competitor": r["competitor"],
            "comp_price_usd": comp,
            "is_on_sale": bool(r["is_on_sale"]),
            "currency": r["currency"],
            "price_gap_pct": gap_pct,
            "availability": r["availability"],
            "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
        })

    if sku_id:
        result = [r for r in result if r["our_sku"].lower() == sku_id.lower()]
    if competitor_name:
        result = [r for r in result if competitor_name.lower() in r["competitor"].lower()]
    return result


# ── recommendations ────────────────────────────────────────────────────────────

def get_pending_recommendations(tenant_id: str) -> list[dict[str, Any]]:
    """Pending PROMOTE/MARKDOWN recommendations with confidence and explanation."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    r.id,
                    r.recommendation,
                    ROUND(r.confidence * 100)::int          AS confidence_pct,
                    r.suggested_discount_pct,
                    r.suggested_price_usd,
                    r.explanation,
                    r.generated_at,
                    r.model_version,
                    COALESCE(r.fallback_used, FALSE)         AS fallback_used,
                    sv.sku_id,
                    p.name                                   AS product_name,
                    p.brand,
                    p.category,
                    COALESCE(pr.amount, 0)                   AS retail_price_usd,
                    sv.cost_price_usd,
                    COALESCE(ib.quantity_on_hand, 0)         AS current_stock
                FROM marketing.recommendations r
                JOIN core.sku_variants sv ON sv.id = r.variant_id
                JOIN core.products p ON sv.product_id = p.id
                LEFT JOIN LATERAL (
                    SELECT amount FROM core.prices
                    WHERE variant_id = sv.id AND price_type = 'retail' AND valid_to IS NULL
                    LIMIT 1
                ) pr ON true
                LEFT JOIN LATERAL (
                    SELECT COALESCE(SUM(quantity_on_hand), 0) AS quantity_on_hand
                    FROM core.inventory_balances WHERE variant_id = sv.id
                ) ib ON true
                WHERE r.tenant_id = %s::uuid AND r.status = 'pending'
                ORDER BY r.confidence DESC, r.generated_at DESC
                LIMIT 10
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
    return [
        {
            "recommendation_id": str(r["id"]),
            "recommendation": r["recommendation"],
            "confidence_pct": _i(r["confidence_pct"]),
            "suggested_discount_pct": _f(r["suggested_discount_pct"]),
            "suggested_price_usd": _f(r["suggested_price_usd"]) if r["suggested_price_usd"] else None,
            "explanation": r["explanation"] or "",
            "sku_id": r["sku_id"],
            "product_name": r["product_name"],
            "brand": r["brand"],
            "category": r["category"],
            "retail_price_usd": _f(r["retail_price_usd"]),
            "cost_price_usd": _f(r["cost_price_usd"]),
            "current_stock": _i(r["current_stock"]),
            "fallback_used": bool(r["fallback_used"]),
            "generated_at": r["generated_at"].isoformat() if r["generated_at"] else None,
        }
        for r in rows
    ]


def approve_recommendation(
    tenant_id: str,
    recommendation_id: str,
    sku_id: str,
    modified_discount_pct: float | None = None,
) -> dict[str, Any]:
    """Approve a pending recommendation."""
    with _connect() as conn:
        with conn.cursor() as cur:
            # Verify ownership before updating
            cur.execute(
                """
                SELECT r.id, r.recommendation, r.suggested_discount_pct
                FROM marketing.recommendations r
                JOIN core.sku_variants sv ON sv.id = r.variant_id
                WHERE r.id = %s::uuid AND r.tenant_id = %s::uuid AND sv.sku_id = %s
                  AND r.status = 'pending'
                """,
                (recommendation_id, tenant_id, sku_id),
            )
            row = cur.fetchone()
            if row is None:
                return {"error": "Recommendation not found, already actioned, or SKU mismatch."}

            final_discount = modified_discount_pct if modified_discount_pct is not None else _f(row["suggested_discount_pct"])

            cur.execute(
                """
                UPDATE marketing.recommendations
                SET status = 'approved',
                    approved_at = NOW(),
                    modified_discount_pct = %s
                WHERE id = %s::uuid
                """,
                (final_discount if modified_discount_pct is not None else None, recommendation_id),
            )
    return {
        "status": "approved",
        "recommendation_id": recommendation_id,
        "sku_id": sku_id,
        "final_discount_pct": final_discount,
        "message": "Recommendation approved and logged.",
    }


def reject_recommendation(tenant_id: str, recommendation_id: str, sku_id: str) -> dict[str, Any]:
    """Reject a pending recommendation."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE marketing.recommendations r
                SET status = 'rejected', approved_at = NOW()
                FROM core.sku_variants sv
                WHERE r.id = %s::uuid
                  AND r.tenant_id = %s::uuid
                  AND sv.id = r.variant_id
                  AND sv.sku_id = %s
                  AND r.status = 'pending'
                """,
                (recommendation_id, tenant_id, sku_id),
            )
            affected = conn.pgconn.transaction_status  # noqa: just check rows
            # Use rowcount from cursor
            if cur.rowcount == 0:
                return {"error": "Recommendation not found, already actioned, or SKU mismatch."}

    return {
        "status": "rejected",
        "recommendation_id": recommendation_id,
        "sku_id": sku_id,
        "message": "Recommendation rejected and logged.",
    }


# ── decision progress / outcome tracking ──────────────────────────────────────

def get_roadmap_summary(tenant_id: str) -> dict[str, Any]:
    """Management-level view of all active recommendations grouped by lifecycle stage."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    r.id,
                    r.recommendation AS decision_type,
                    r.status,
                    r.confidence,
                    r.suggested_discount_pct,
                    r.explanation,
                    r.generated_at,
                    r.approved_at,
                    sv.sku_id,
                    p.name AS product_name,
                    p.brand,
                    p.category,
                    COALESCE(pr.amount, 0)            AS retail_price_usd,
                    COALESCE(ib.quantity_on_hand, 0)  AS current_stock
                FROM marketing.recommendations r
                JOIN core.sku_variants sv ON sv.id = r.variant_id
                JOIN core.products p ON p.id = sv.product_id
                LEFT JOIN LATERAL (
                    SELECT amount FROM core.prices
                    WHERE variant_id = sv.id AND price_type = 'retail' AND valid_to IS NULL
                    LIMIT 1
                ) pr ON true
                LEFT JOIN LATERAL (
                    SELECT COALESCE(SUM(quantity_on_hand), 0) AS quantity_on_hand
                    FROM core.inventory_balances WHERE variant_id = sv.id
                ) ib ON true
                WHERE r.tenant_id = %s::uuid
                  AND r.status IN ('pending', 'approved', 'rejected')
                ORDER BY r.generated_at DESC
                LIMIT 30
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

    by_stage: dict[str, list[dict]] = {"awaiting_approval": [], "approved": [], "rejected": []}
    for r in rows:
        stage = (
            "awaiting_approval" if r["status"] == "pending"
            else "approved" if r["status"] == "approved"
            else "rejected"
        )
        by_stage.setdefault(stage, []).append({
            "recommendation_id": str(r["id"]),
            "decision_type": r["decision_type"],
            "sku_id": r["sku_id"],
            "product_name": r["product_name"],
            "brand": r["brand"],
            "category": r["category"],
            "confidence_pct": round(_f(r["confidence"]) * 100),
            "suggested_discount_pct": _f(r["suggested_discount_pct"]),
            "retail_price_usd": _f(r["retail_price_usd"]),
            "current_stock": _i(r["current_stock"]),
            "explanation": r["explanation"] or "",
            "generated_at": r["generated_at"].isoformat() if r["generated_at"] else None,
            "approved_at": r["approved_at"].isoformat() if r["approved_at"] else None,
        })

    return {
        "total_recommendations": len(rows),
        "awaiting_approval": by_stage.get("awaiting_approval", []),
        "approved": by_stage.get("approved", []),
        "rejected": by_stage.get("rejected", []),
        "summary": (
            f"{len(by_stage.get('awaiting_approval', []))} pending approval, "
            f"{len(by_stage.get('approved', []))} approved, "
            f"{len(by_stage.get('rejected', []))} rejected."
        ),
    }


def get_recommendation_detail(tenant_id: str, roadmap_id: str) -> dict[str, Any]:
    """Full detail for a single recommendation including SHAP features and audit trail."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    r.id,
                    r.recommendation AS decision_type,
                    r.status,
                    r.confidence,
                    r.suggested_discount_pct,
                    r.suggested_price_usd,
                    r.explanation,
                    r.generated_at,
                    r.approved_at,
                    r.model_version,
                    r.fallback_used,
                    COALESCE(r.shap_features_json, '[]'::jsonb) AS shap_features,
                    r.rule_override_json,
                    sv.sku_id,
                    p.name AS product_name,
                    p.brand,
                    p.category,
                    p.gender_target,
                    p.season,
                    COALESCE(pr.amount, 0)           AS retail_price_usd,
                    sv.cost_price_usd,
                    COALESCE(ib.quantity_on_hand, 0) AS current_stock,
                    sv.reorder_point
                FROM marketing.recommendations r
                JOIN core.sku_variants sv ON sv.id = r.variant_id
                JOIN core.products p ON p.id = sv.product_id
                LEFT JOIN LATERAL (
                    SELECT amount FROM core.prices
                    WHERE variant_id = sv.id AND price_type = 'retail' AND valid_to IS NULL
                    LIMIT 1
                ) pr ON true
                LEFT JOIN LATERAL (
                    SELECT COALESCE(SUM(quantity_on_hand), 0) AS quantity_on_hand
                    FROM core.inventory_balances WHERE variant_id = sv.id
                ) ib ON true
                WHERE r.id = %s::uuid AND r.tenant_id = %s::uuid
                """,
                (roadmap_id, tenant_id),
            )
            row = cur.fetchone()

    if row is None:
        return {"error": f"Recommendation {roadmap_id} not found."}

    retail = _f(row["retail_price_usd"])
    cost = _f(row["cost_price_usd"])
    margin = round((retail - cost) / retail * 100, 1) if retail > cost else 0.0
    disc = _f(row["suggested_discount_pct"])
    price_after = round(retail * (1 - disc / 100), 2) if disc > 0 else None
    margin_after = round((price_after - cost) / price_after * 100, 1) if price_after and price_after > cost else None

    shap = row["shap_features"]
    if isinstance(shap, str):
        shap = json.loads(shap)

    return {
        "recommendation_id": str(row["id"]),
        "decision_type": row["decision_type"],
        "status": row["status"],
        "sku_id": row["sku_id"],
        "product_name": row["product_name"],
        "brand": row["brand"],
        "category": row["category"],
        "gender_target": row["gender_target"],
        "season": row["season"],
        "confidence_pct": round(_f(row["confidence"]) * 100),
        "model_version": row["model_version"],
        "fallback_used": bool(row["fallback_used"]),
        "pricing": {
            "retail_price_usd": retail,
            "cost_price_usd": cost,
            "current_margin_pct": margin,
            "suggested_discount_pct": disc,
            "price_after_discount": price_after,
            "margin_after_discount": margin_after,
        },
        "inventory": {
            "current_stock": _i(row["current_stock"]),
            "reorder_point": _i(row["reorder_point"]),
        },
        "explanation": row["explanation"] or "",
        "shap_features": shap,
        "rule_override": row["rule_override_json"],
        "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
        "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
    }


def get_next_actions(tenant_id: str) -> dict[str, Any]:
    """Prioritised action list for pending recommendation approvals."""
    with _connect() as conn:
        with conn.cursor() as cur:
            # Pending recommendations
            cur.execute(
                """
                SELECT r.id, r.recommendation, r.confidence, sv.sku_id, p.name AS product_name
                FROM marketing.recommendations r
                JOIN core.sku_variants sv ON sv.id = r.variant_id
                JOIN core.products p ON p.id = sv.product_id
                WHERE r.tenant_id = %s::uuid AND r.status = 'pending'
                ORDER BY r.confidence DESC
                LIMIT 5
                """,
                (tenant_id,),
            )
            pending_recs = cur.fetchall()

    approval_items = [
        {
            "priority": "high",
            "action": "Approve or reject recommendation",
            "recommendation_id": str(r["id"]),
            "decision_type": r["recommendation"],
            "sku_id": r["sku_id"],
            "product_name": r["product_name"],
            "confidence_pct": round(_f(r["confidence"]) * 100),
        }
        for r in pending_recs
    ]

    return {
        "pending_approvals": len(approval_items),
        "action_items": approval_items,
        "summary": f"{len(approval_items)} recommendation(s) awaiting your decision.",
    }


# ── financial health ───────────────────────────────────────────────────────────

def get_financial_health(tenant_id: str) -> dict[str, Any]:
    """Financial snapshot: margin, gross profit, inventory value, dead stock, liabilities."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                # Financial profile
                cur.execute(
                    """
                    SELECT gross_profit_usd, blended_margin_pct, inventory_value_cost_usd,
                           inventory_value_retail_usd, dead_stock_value_usd, total_liabilities_usd,
                           cash_on_hand_usd, period_start, period_end
                    FROM financial.financial_profiles
                    WHERE tenant_id = %s::uuid
                    ORDER BY period_end DESC
                    LIMIT 1
                    """,
                    (tenant_id,),
                )
                fp = cur.fetchone()
    except Exception:
        fp = None

    if not fp:
        inventory = get_inventory_overview(tenant_id)
        return {
            "source": "inventory_estimate",
            "total_inventory_value_usd": inventory["total_inventory_value_usd"],
            "low_stock_count": inventory["low_stock_count"],
            "dead_stock_count": inventory["dead_stock_count"],
            "note": "No financial profile on file. Showing inventory estimate only.",
        }

    inv_cost = _f(fp["inventory_value_cost_usd"])
    inv_retail = _f(fp["inventory_value_retail_usd"])
    dead = _f(fp["dead_stock_value_usd"])
    liabilities = _f(fp["total_liabilities_usd"])
    cash = _f(fp["cash_on_hand_usd"])

    current_ratio = round((inv_cost + cash) / liabilities, 2) if liabilities > 0 else None
    cash_runway_days = round(cash / max(_f(fp["gross_profit_usd"]) / 30, 1), 0) if cash > 0 else None

    return {
        "source": "financial_profile",
        "period_start": fp["period_start"].isoformat() if fp["period_start"] else None,
        "period_end": fp["period_end"].isoformat() if fp["period_end"] else None,
        "blended_margin_pct": _f(fp["blended_margin_pct"]),
        "gross_profit_usd": _f(fp["gross_profit_usd"]),
        "inventory_value_cost_usd": inv_cost,
        "inventory_value_retail_usd": inv_retail,
        "dead_stock_value_usd": dead,
        "dead_stock_pct": round(dead / inv_cost * 100, 1) if inv_cost > 0 else 0.0,
        "total_liabilities_usd": liabilities,
        "cash_on_hand_usd": cash,
        "current_ratio": current_ratio,
        "cash_runway_days": cash_runway_days,
    }
