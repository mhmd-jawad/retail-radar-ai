"""Runtime feature construction for IE1 -> IE2 prediction.

This module mirrors the RDS training feature construction path for a single
live SKU. It intentionally builds engineered model features, not a raw request
payload, so online predictions stay aligned with the active CatBoost model.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from services.decision_intelligence.features.engineer import compute_state_features
from services.market_intelligence.competitor_processor import build_competitor_signals_for_product


DEFAULT_TENANT_SLUG = "main"
DEFAULT_STORE_CODE = "main"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/retail_radar")


def _tenant_slug() -> str:
    return os.environ.get("RETAIL_TENANT_SLUG", DEFAULT_TENANT_SLUG)


def _store_code() -> str:
    return os.environ.get("RETAIL_STORE_CODE", DEFAULT_STORE_CODE)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def market_position_from_gap(price_gap_pct: float) -> str:
    if price_gap_pct > 0.15:
        return "premium"
    if price_gap_pct > 0.05:
        return "above_market"
    if price_gap_pct > -0.05:
        return "at_market"
    if price_gap_pct > -0.15:
        return "below_market"
    return "deep_value"


def add_decision_derived_features(features: dict[str, Any]) -> dict[str, Any]:
    """Add the derived RDS-era feature columns used during model training."""
    days_of_supply = _to_float(features.get("days_of_supply"))
    total_qty = _to_float(features.get("total_qty"))
    margin_pct = _to_float(features.get("current_margin_pct"))
    price_gap_pct = _to_float(features.get("price_gap_pct"))
    competitors_on_sale = _to_float(features.get("competitors_on_sale"))
    competitors_out_of_stock = _to_float(features.get("competitors_out_of_stock"))
    num_competitors = _to_float(features.get("num_competitors"))
    season_sell_through = min(max(_to_float(features.get("season_sell_through_pct")), 0.0), 1.0)
    days_since_launch = _to_float(features.get("days_since_launch"))
    days_since_discount = _to_float(features.get("days_since_last_discount"), 999.0)
    event_score = min(max(_to_float(features.get("event_proximity_score")), 0.0), 1.0)

    sale_pressure_ratio = (
        min(max(competitors_on_sale / num_competitors, 0.0), 1.0)
        if num_competitors > 0
        else 0.0
    )
    competitor_oos_ratio = (
        min(max(competitors_out_of_stock / num_competitors, 0.0), 1.0)
        if num_competitors > 0
        else 0.0
    )
    overpricing_signal = min(max(price_gap_pct, 0.0), 0.40)
    stale_pressure = min(max(1.0 - season_sell_through, 0.0), 1.0)
    low_stock_signal = max(
        min(max((14.0 - days_of_supply) / 14.0, 0.0), 1.0),
        min(max((12.0 - total_qty) / 12.0, 0.0), 1.0),
    )
    stable_high_dos_signal = (
        min(max((days_of_supply - 70.0) / 80.0, 0.0), 1.0)
        * (1.0 - sale_pressure_ratio)
        * (1.0 - min(max(overpricing_signal / 0.15, 0.0), 1.0))
    )
    moderate_stock = min(max(1.0 - abs(days_of_supply - 70.0) / 70.0, 0.0), 1.0)
    low_margin_signal = min(max((35.5 - margin_pct) / 15.0, 0.0), 1.0)
    recent_discount_cooldown = min(max((21.0 - days_since_discount) / 21.0, 0.0), 1.0)

    features.update(
        {
            "sale_pressure_ratio": round(sale_pressure_ratio, 4),
            "competitor_oos_ratio": round(competitor_oos_ratio, 4),
            "markdown_margin_buffer": round(margin_pct - 35.0, 4),
            "promote_margin_buffer": round(margin_pct - 38.0, 4),
            "recent_discount_cooldown": round(recent_discount_cooldown, 4),
            "stock_staleness_index": round(
                min(max((min(max(days_of_supply, 0.0), 240.0) / 150.0) * stale_pressure, 0.0), 2.5),
                4,
            ),
            "inventory_age_pressure": round(
                min(
                    max(
                        (min(max(days_of_supply - 90.0, 0.0), 180.0) / 180.0)
                        * (min(max(days_since_launch - 180.0, 0.0), 240.0) / 240.0),
                        0.0,
                    ),
                    1.5,
                ),
                4,
            ),
            "overpricing_sale_pressure": round(min(max(overpricing_signal * sale_pressure_ratio, 0.0), 0.50), 4),
            "clearance_pressure_index": round(
                min(
                    max(
                        (min(max(days_of_supply - 120.0, 0.0), 140.0) / 140.0) * 0.34
                        + stale_pressure * 0.28
                        + (min(max(days_since_launch - 220.0, 0.0), 220.0) / 220.0) * 0.18
                        + min(max(overpricing_signal / 0.35, 0.0), 1.0) * 0.12
                        + sale_pressure_ratio * 0.08,
                        0.0,
                    ),
                    1.5,
                ),
                4,
            ),
            "hold_guardrail_index": round(
                min(
                    max(
                        low_margin_signal * 0.40
                        + recent_discount_cooldown * 0.24
                        + low_stock_signal * 0.20
                        + stable_high_dos_signal * 0.10
                        + (moderate_stock * event_score) * 0.06,
                        0.0,
                    ),
                    1.5,
                ),
                4,
            ),
        }
    )
    return features


def align_feature_defaults(features: dict[str, Any], feature_columns: list[str] | None = None) -> dict[str, Any]:
    """Fill safe runtime defaults for feature columns expected by the model."""
    aligned = dict(features)
    aligned.setdefault("match_type", "no_match" if _to_int(aligned.get("num_competitors")) <= 0 else "matched_unknown")
    aligned.setdefault("match_score", 0.0)
    aligned.setdefault("inventory_history_quality", "movement_reconstructed")
    aligned.setdefault("has_competitor_data", 1 if _to_int(aligned.get("num_competitors")) > 0 else 0)
    aligned.setdefault("competitor_min_price_usd", 0.0)
    aligned.setdefault("competitor_avg_price_usd", 0.0)
    aligned.setdefault("competitor_max_price_usd", max(_to_float(aligned.get("competitor_min_price_usd")), _to_float(aligned.get("competitor_avg_price_usd"))))
    aligned.setdefault("sales_units_last_28d", 0.0)
    aligned.setdefault("avg_daily_sales_28d", 0.0)
    aligned.setdefault("competitor_price_trend_4w", 0.0)
    aligned.setdefault("competitor_sale_frequency_4w", 0.0)
    aligned.setdefault("competitor_oos_frequency_4w", 0.0)
    aligned.setdefault("price_gap_volatility_4w", round(abs(_to_float(aligned.get("price_gap_pct"))) * 0.25, 4))
    aligned.setdefault("stock_velocity_4w", 0.0)
    aligned.setdefault("sell_through_velocity_4w", 0.0)
    aligned.setdefault("days_since_competitor_change", 30)
    add_decision_derived_features(aligned)
    if feature_columns:
        for column in feature_columns:
            aligned.setdefault(column, -1)
    return aligned


def _context(cur, tenant_id: str | None = None) -> dict[str, Any]:
    desired_store = _store_code()
    if tenant_id:
        cur.execute(
            """
            select t.id as tenant_id, t.slug as tenant_slug, s.id as store_id, s.code as store_code
            from core.tenants t
            join core.stores s on s.tenant_id = t.id
            where t.id = %s and s.code = %s and s.is_active = true
            """,
            (tenant_id, desired_store),
        )
    else:
        cur.execute(
            """
            select t.id as tenant_id, t.slug as tenant_slug, s.id as store_id, s.code as store_code
            from core.tenants t
            join core.stores s on s.tenant_id = t.id
            where t.slug = %s and s.code = %s and s.is_active = true
            """,
            (_tenant_slug(), desired_store),
        )
    row = cur.fetchone()
    if not row:
        raise KeyError(f"Tenant/store not found: {tenant_id or _tenant_slug()}/{desired_store}")
    return row


def _load_inventory_row(cur, tenant_id: str, store_id: str, sku_id: str) -> dict[str, Any]:
    cur.execute(
        """
        select
            v.id as variant_id,
            v.sku_id,
            v.style_code,
            v.cost_price_usd,
            v.created_at as variant_created_at,
            p.id as product_id,
            p.name as product_name,
            p.brand,
            p.category,
            p.gender_target,
            p.created_at as product_created_at,
            coalesce(pr.amount, 0) as retail_price_usd,
            coalesce(b.quantity_on_hand, 0) as current_stock
        from core.sku_variants v
        join core.products p on p.id = v.product_id
        left join core.inventory_balances b
            on b.variant_id = v.id and b.store_id = %s and b.tenant_id = v.tenant_id
        left join lateral (
            select amount
            from core.prices
            where variant_id = v.id and tenant_id = v.tenant_id and price_type = 'retail' and valid_to is null
            order by valid_from desc
            limit 1
        ) pr on true
        where v.tenant_id = %s and v.sku_id = %s and v.status = 'active'
        """,
        (store_id, tenant_id, sku_id),
    )
    row = cur.fetchone()
    if not row:
        raise KeyError(f"SKU not found: {sku_id}")
    return dict(row)


def _load_competitor_rows(cur, tenant_id: str) -> pd.DataFrame:
    cur.execute(
        """
        select
            cpl.brand_name,
            cpl.style_code,
            cpl.shop_code as competitor_name,
            cpl.product_name,
            cpl.category,
            cpl.gender_target,
            cpl.competitor_price,
            cpl.competitor_sale_price,
            cpl.discount_pct,
            cpl.is_on_sale,
            cpl.availability,
            cpl.currency,
            cpl.source_url,
            cpl.last_seen_at as scraped_at,
            cpl.data_valid
        from intel.competitor_products_latest cpl
        join intel.tenant_competitors tc
            on tc.shop_code = cpl.shop_code and tc.tenant_id = %s and tc.is_active = true
        """,
        (tenant_id,),
    )
    rows = cur.fetchall() or []
    return pd.DataFrame(rows)


def _load_recent_sales(cur, tenant_id: str, variant_id: str) -> float:
    cur.execute(
        """
        select coalesce(sum(-quantity_delta), 0) as sold_28d
        from core.inventory_movements
        where tenant_id = %s
          and variant_id = %s
          and movement_type = 'sale'
          and created_at >= now() - interval '28 days'
        """,
        (tenant_id, variant_id),
    )
    row = cur.fetchone() or {}
    return max(_to_float(row.get("sold_28d")), 0.0)


def _days_since(value: Any, default: int = 180) -> int:
    if value is None:
        return default
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return default
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - dt).days, 0)


def _feature_package(product: dict[str, Any], competitor_signals: dict[str, Any], sold_28d: float) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    stock = max(_to_int(product.get("current_stock")), 0)
    peak_stock = max(stock + int(round(sold_28d)), stock, 1)
    sell_through = min(max(sold_28d / peak_stock, 0.0), 1.0)
    retail = _to_float(product.get("retail_price_usd"))
    comp_min = _to_float(competitor_signals.get("competitor_min_price"))
    comp_avg = _to_float(competitor_signals.get("competitor_avg_price"), comp_min)
    num_comp = _to_int(competitor_signals.get("num_competitors_tracked"))
    comp_on_sale = _to_int(competitor_signals.get("competitors_on_sale_count"))
    comp_oos = _to_int(competitor_signals.get("competitors_out_of_stock_count"))
    has_comp = 1 if num_comp > 0 and comp_min > 0 else 0
    avg_daily = round(sold_28d / 28.0, 4)

    state_row = {
        "state_id": f"{product['sku_id']}|runtime",
        "sku_id": product["sku_id"],
        "product_key": f"{product.get('brand') or ''}|{product.get('style_code') or product['sku_id']}",
        "style_code": product.get("style_code") or "",
        "brand": product.get("brand") or "Unknown",
        "category": product.get("category") or "other",
        "product_name": product.get("product_name") or "",
        "week_of": now.date().isoformat(),
        "retail_price_usd": retail,
        "cost_price_usd": _to_float(product.get("cost_price_usd")),
        "total_qty": stock,
        "simulated_peak_stock": peak_stock,
        "sell_through_proxy": sell_through,
        "days_since_launch": _days_since(product.get("variant_created_at") or product.get("product_created_at")),
        "days_since_last_discount": 999,
        "days_at_current_price": 30,
        "discount_depth_last_30d_proxy": 0.0,
        "has_competitor_data": has_comp,
        "competitor_min_price_usd": comp_min,
        "competitor_avg_price_usd": comp_avg,
        "competitor_max_price_usd": max(comp_min, comp_avg),
        "num_competitors": num_comp,
        "competitors_on_sale_count": comp_on_sale,
        "competitors_out_of_stock_count": comp_oos,
        "data_freshness_hours": _to_float(competitor_signals.get("data_freshness_hours"), 72.0),
    }

    financial_profile = {
        "cashflow_summary": {"cash_runway_months": 3.0},
        "inventory_summary": {"total_cost_usd": 176000},
        "balance_sheet_summary": {"total_assets_usd": 214000},
    }
    features = compute_state_features(state_row, financial_profile)
    if avg_daily > 0:
        features["days_of_supply"] = round(stock / avg_daily, 1)
        features["stock_coverage_ratio"] = round(features["days_of_supply"] / 30.0, 2)
        features["stockout_risk"] = 1 if features["days_of_supply"] < 14 else 0

    features.update(
        {
            "match_type": competitor_signals.get("match_type") or ("no_match" if not has_comp else "matched_unknown"),
            "match_score": round(_to_float(competitor_signals.get("match_score"), competitor_signals.get("confidence_score")), 4),
            "inventory_history_quality": "movement_reconstructed" if sold_28d > 0 else "online_estimated",
            "has_competitor_data": has_comp,
            "competitor_min_price_usd": round(comp_min, 4),
            "competitor_avg_price_usd": round(comp_avg, 4),
            "competitor_max_price_usd": round(max(comp_min, comp_avg), 4),
            "sales_units_last_28d": round(sold_28d, 2),
            "avg_daily_sales_28d": avg_daily,
            "competitor_price_trend_4w": 0.0,
            "competitor_sale_frequency_4w": round(comp_on_sale / num_comp, 4) if num_comp > 0 else 0.0,
            "competitor_oos_frequency_4w": round(comp_oos / num_comp, 4) if num_comp > 0 else 0.0,
            "price_gap_volatility_4w": round(abs(_to_float(features.get("price_gap_pct"))) * 0.25, 4),
            "stock_velocity_4w": round(sold_28d / max(peak_stock, 1), 4),
            "sell_through_velocity_4w": round(sell_through / 4.0, 4),
            "days_since_competitor_change": 30,
            "feature_source": "ie1_runtime_rds",
        }
    )
    features["market_position"] = market_position_from_gap(_to_float(features.get("price_gap_pct")))
    return align_feature_defaults(features)


def build_runtime_feature_instance(
    sku_id: str,
    tenant_id: str | None = None,
    feature_columns: list[str] | None = None,
) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            product = _load_inventory_row(cur, str(ctx["tenant_id"]), str(ctx["store_id"]), sku_id)
            competitor_rows = _load_competitor_rows(cur, str(ctx["tenant_id"]))
            sold_28d = _load_recent_sales(cur, str(ctx["tenant_id"]), str(product["variant_id"]))

    product_payload = {
        "sku_id": product["sku_id"],
        "product_name": product.get("product_name"),
        "brand": product.get("brand"),
        "category": product.get("category"),
        "style_code": product.get("style_code"),
        "gender_target": product.get("gender_target"),
        "retail_price_usd": product.get("retail_price_usd"),
    }
    competitor_signals = build_competitor_signals_for_product(product_payload, competitor_rows=competitor_rows)
    features = align_feature_defaults(_feature_package(product, competitor_signals, sold_28d), feature_columns)

    return {
        "sku_id": str(product["sku_id"]),
        "product_name": str(product.get("product_name") or ""),
        "brand": str(product.get("brand") or "Unknown"),
        "category": str(product.get("category") or "other"),
        "retail_price_usd": round(_to_float(product.get("retail_price_usd")), 2),
        "cost_price_usd": round(_to_float(product.get("cost_price_usd")), 2),
        "current_stock": max(_to_int(product.get("current_stock")), 0),
        "features": features,
        "competitor_signals": competitor_signals,
    }
