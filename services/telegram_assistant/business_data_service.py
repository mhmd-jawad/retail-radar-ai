"""
Business Data Service — fetches and caches live business KPIs for Telegram AI context.

All live data is queried directly from AWS RDS PostgreSQL.
Financial profile / cashflow CSV are loaded from data/real/ as a fallback when
the DB has no sales history yet (early deployment).
"""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from prometheus_client import Gauge
from psycopg.rows import dict_row

from services.telegram_assistant.conversation_store import ConversationManager, DEFAULT_DATABASE_URL

logger = logging.getLogger("telegram_assistant.business_data_service")

# ── Prometheus gauges ─────────────────────────────────────────────────────────
retail_cash_runway_months = Gauge("retail_cash_runway_months", "Cash runway in months")
retail_low_stock_sku_count = Gauge("retail_low_stock_sku_count", "SKUs under 21 days of supply")

_CACHE_TTL_HOURS = 4

# ── DOS estimation helpers ────────────────────────────────────────────────────
# The /inventory/items endpoint does not expose days_of_supply directly.
# We estimate: DOS = current_stock / daily_rate
# daily_rate = reorder_quantity / 30  (if set), else reorder_point / 15, else assume 1 unit/day.

def _estimate_dos(item: dict[str, Any]) -> float:
    stock = int(item.get("current_stock") or 0)
    rq = int(item.get("reorder_quantity") or 0)
    rp = int(item.get("reorder_point") or 0)
    if rq > 0:
        daily = rq / 30.0
    elif rp > 0:
        daily = rp / 15.0
    else:
        daily = 1.0
    return round(stock / daily, 1)


class BusinessDataService:
    def __init__(
        self,
        db_url: str,
        financial_data_path: str,
        eep_base_url: str = "",  # reserved, unused
    ) -> None:
        self._db_url = db_url
        self._data_dir = Path(financial_data_path)
        self._conv = ConversationManager(db_url)

    # ── CSV / JSON fallback loaders (used when DB has no sales history yet) ───

    def _load_financial_profile(self) -> dict[str, Any]:
        path = self._data_dir / "financial_profile.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _load_cashflow_current_month(self) -> float:
        """Return revenue_projected_usd for the current calendar month from CSV."""
        path = self._data_dir / "cashflow_template.csv"
        current_month = datetime.now().month
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["month"]) == current_month:
                    return float(row.get("revenue_usd") or row.get("revenue_projected_usd") or 0)
        return 0.0

    # ── Direct RDS queries ────────────────────────────────────────────────────

    async def _db_connect(self):
        return await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)

    async def _fetch_inventory_from_db(self, tenant_id: str) -> list[dict[str, Any]]:
        """
        Returns all active SKUs with current stock, retail price, and cost.
        Source: core.sku_variants + core.inventory_balances + core.prices (RDS)
        """
        sql = """
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
            WHERE sv.tenant_id = %s
              AND sv.status = 'active'
              AND p.status = 'active'
            GROUP BY sv.id, sv.sku_id, p.name, p.brand, p.category,
                     sv.cost_price_usd, sv.reorder_point, pr.amount
            ORDER BY current_stock ASC
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (tenant_id,))
                return await cur.fetchall()
        finally:
            await conn.close()

    async def _fetch_revenue_from_db(self, tenant_id: str) -> dict[str, Any]:
        """
        Returns revenue for current month and last 4 weeks from sales_transactions.
        Falls back to CSV projection if no sales data in DB.
        """
        sql = """
            SELECT
                COALESCE(SUM(CASE WHEN sold_at >= date_trunc('month', now())
                                  THEN total_amount_usd END), 0) AS current_month_usd,
                COALESCE(SUM(CASE WHEN sold_at >= now() - interval '7 days'
                                  THEN total_amount_usd END), 0) AS last_7d_usd,
                COALESCE(SUM(CASE WHEN sold_at >= now() - interval '30 days'
                                  THEN total_amount_usd END), 0) AS last_30d_usd,
                COUNT(DISTINCT CASE WHEN sold_at >= date_trunc('month', now())
                                    THEN id END) AS txn_count_this_month
            FROM core.sales_transactions
            WHERE tenant_id = %s
              AND sold_at >= now() - interval '60 days'
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (tenant_id,))
                row = await cur.fetchone()
                return row or {}
        finally:
            await conn.close()

    async def _fetch_competitor_intel_from_db(self, tenant_id: str) -> list[dict[str, Any]]:
        """
        Returns competitor price comparisons for SKUs we carry, matched by style_code.
        Source: intel.competitor_products_latest joined to core.sku_variants (RDS)
        """
        sql = """
            SELECT DISTINCT ON (sv.sku_id)
                sv.sku_id                    AS our_sku,
                p.name                       AS our_product,
                p.brand,
                COALESCE(pr.amount, 0)       AS our_price_usd,
                cl.shop_code                 AS competitor,
                cl.product_name              AS competitor_product,
                cl.competitor_price          AS comp_price_usd,
                cl.competitor_sale_price     AS comp_sale_price_usd,
                cl.is_on_sale,
                cl.availability,
                ROUND(
                    ((COALESCE(pr.amount,0) - COALESCE(cl.competitor_sale_price, cl.competitor_price)) /
                     NULLIF(COALESCE(pr.amount,0), 0) * 100)::numeric, 1
                )                            AS price_gap_pct,
                cl.last_seen_at
            FROM intel.competitor_products_latest cl
            JOIN core.sku_variants sv
                ON sv.style_code = cl.style_code
               AND sv.tenant_id = %s
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
            LIMIT 25
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (tenant_id,))
                return await cur.fetchall()
        finally:
            await conn.close()

    async def _fetch_pending_recommendations_from_db(self, tenant_id: str) -> list[dict[str, Any]]:
        """
        Returns pending PROMOTE/MARKDOWN recommendations with full product details.
        Source: marketing.recommendations + core.sku_variants + core.products (RDS)
        """
        sql = """
            SELECT
                r.id,
                r.recommendation,
                ROUND(r.confidence * 100)::int   AS confidence_pct,
                r.suggested_discount_pct,
                r.suggested_price_usd,
                r.explanation,
                r.generated_at,
                COALESCE(r.shap_features_json, '[]'::jsonb)  AS shap_features_json,
                r.rule_override_json,
                COALESCE(r.fallback_used, FALSE)             AS fallback_used,
                r.model_version,
                sv.sku_id,
                p.name                           AS product_name,
                p.brand,
                p.category,
                COALESCE(pr.amount, 0)           AS retail_price_usd,
                sv.cost_price_usd,
                COALESCE(ib.quantity_on_hand, 0) AS current_stock
            FROM marketing.recommendations r
            JOIN core.sku_variants sv ON sv.id = r.variant_id
            JOIN core.products p ON sv.product_id = p.id
            LEFT JOIN LATERAL (
                SELECT amount FROM core.prices
                WHERE variant_id = sv.id
                  AND price_type = 'retail'
                  AND valid_to IS NULL
                LIMIT 1
            ) pr ON true
            LEFT JOIN LATERAL (
                SELECT COALESCE(SUM(quantity_on_hand), 0) AS quantity_on_hand
                FROM core.inventory_balances
                WHERE variant_id = sv.id
            ) ib ON true
            WHERE r.tenant_id = %s
              AND r.status = 'pending'
            ORDER BY r.confidence DESC, r.generated_at DESC
            LIMIT 10
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (tenant_id,))
                return await cur.fetchall()
        finally:
            await conn.close()

    async def _fetch_inventory(self) -> list[dict[str, Any]]:
        """Legacy method kept for backward compatibility — returns empty list."""
        return []

    async def _fetch_competitor_count(self) -> int:
        """Legacy shim — count rows in intel.competitor_products_latest directly."""
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) AS n FROM intel.competitor_products_latest WHERE data_valid = true")
                row = await cur.fetchone()
                return int(row["n"]) if row else 0
        except Exception:
            return 0
        finally:
            await conn.close()

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_business_context(
        self, chat_id: str, force_refresh: bool = False,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        # Check cache
        if not force_refresh:
            try:
                cached_data, cached_at = await self._conv.get_cached_business_data(chat_id)
                if cached_data and cached_at:
                    age = (
                        datetime.now(tz=timezone.utc) - cached_at.replace(tzinfo=timezone.utc)
                        if cached_at.tzinfo is None
                        else datetime.now(tz=timezone.utc) - cached_at
                    )
                    if age < timedelta(hours=_CACHE_TTL_HOURS):
                        return cached_data
            except Exception as exc:
                logger.warning("Cache read failed, fetching fresh: %s", exc)

        # Resolve tenant_id
        _tenant_id = tenant_id
        if not _tenant_id:
            try:
                conn = await self._db_connect()
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id FROM core.tenants WHERE slug = 'default' LIMIT 1"
                    )
                    row = await cur.fetchone()
                    _tenant_id = str(row["id"]) if row else None
                await conn.close()
            except Exception as exc:
                logger.warning("Could not resolve tenant_id: %s", exc)

        context: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            # Financial (from CSV — source of truth until POS is live)
            "cash_runway_months": 0.0,
            "monthly_fixed_opex": 0.0,
            "blended_margin_pct": 0.0,
            # Inventory (from RDS)
            "total_sku_count": 0,
            "total_units": 0,
            "total_inventory_value_usd": 0.0,
            "dead_stock_skus": [],      # list of {sku_id, product_name, brand, units, value_usd}
            "low_stock_skus": [],       # list of {sku_id, product_name, brand, units, reorder_point}
            # Revenue (from RDS sales_transactions; 0 if not yet populated)
            "revenue_current_month_usd": 0.0,
            "revenue_last_7d_usd": 0.0,
            "revenue_last_30d_usd": 0.0,
            "sales_txn_count_this_month": 0,
            # Competitor intel (from RDS intel schema)
            "competitor_intel": [],     # list of {our_sku, our_product, our_price, competitor, comp_price, gap_pct, is_on_sale}
            # AI recommendations (from RDS marketing schema)
            "pending_recommendations": [],  # list of {recommendation, sku_id, product_name, confidence_pct, discount_pct, explanation}
        }

        # 1. Financial profile (CSV — reliable baseline)
        try:
            fp = self._load_financial_profile()
            cf = fp.get("cashflow_summary", {})
            inv = fp.get("inventory_summary", {})
            context["cash_runway_months"] = float(cf.get("cash_runway_months", 0))
            context["monthly_fixed_opex"] = float(cf.get("monthly_fixed_opex_usd", 0))
            context["blended_margin_pct"] = float(inv.get("blended_margin_pct", 0))
        except Exception as exc:
            logger.warning("Failed to load financial_profile.json: %s", exc)

        if _tenant_id:
            # 2. Inventory from RDS
            try:
                items = await self._fetch_inventory_from_db(_tenant_id)
                context["total_sku_count"] = len(items)
                context["total_units"] = sum(int(i.get("current_stock") or 0) for i in items)
                context["total_inventory_value_usd"] = round(
                    sum(float(i.get("current_stock") or 0) * float(i.get("cost_price_usd") or 0) for i in items), 2
                )
                context["low_stock_skus"] = [
                    {
                        "sku_id": i["sku_id"],
                        "product_name": i["product_name"],
                        "brand": i["brand"],
                        "units": int(i["current_stock"]),
                        "reorder_point": int(i.get("reorder_point") or 0),
                        "retail_price_usd": float(i.get("retail_price_usd") or 0),
                    }
                    for i in items
                    if 0 < int(i.get("current_stock") or 0) <= max(int(i.get("reorder_point") or 5), 5)
                ][:10]
                context["dead_stock_skus"] = sorted(
                    [
                        {
                            "sku_id": i["sku_id"],
                            "product_name": i["product_name"],
                            "brand": i["brand"],
                            "units": int(i["current_stock"]),
                            "value_usd": round(
                                float(i["current_stock"]) * float(i.get("cost_price_usd") or 0), 2
                            ),
                        }
                        for i in items
                        if int(i.get("current_stock") or 0) > 30
                        and float(i.get("retail_price_usd") or 0) == 0
                    ],
                    key=lambda x: x["value_usd"], reverse=True
                )[:10]
            except Exception as exc:
                logger.warning("Failed to fetch inventory from RDS: %s", exc)

            # 3. Revenue from RDS (0 if sales_transactions not yet populated)
            try:
                rev = await self._fetch_revenue_from_db(_tenant_id)
                context["revenue_current_month_usd"] = float(rev.get("current_month_usd") or 0)
                context["revenue_last_7d_usd"] = float(rev.get("last_7d_usd") or 0)
                context["revenue_last_30d_usd"] = float(rev.get("last_30d_usd") or 0)
                context["sales_txn_count_this_month"] = int(rev.get("txn_count_this_month") or 0)
                # Fall back to CSV projection if DB has no sales yet
                if context["revenue_current_month_usd"] == 0:
                    try:
                        context["revenue_current_month_usd"] = self._load_cashflow_current_month()
                        context["_revenue_source"] = "csv_projection"
                    except Exception:
                        pass
                else:
                    context["_revenue_source"] = "live_pos"
            except Exception as exc:
                logger.warning("Failed to fetch revenue from RDS: %s", exc)

            # 4. Competitor intelligence from RDS
            try:
                comp_rows = await self._fetch_competitor_intel_from_db(_tenant_id)
                context["competitor_intel"] = [
                    {
                        "our_sku": r["our_sku"],
                        "our_product": r["our_product"],
                        "brand": r["brand"],
                        "our_price_usd": float(r.get("our_price_usd") or 0),
                        "competitor": r["competitor"],
                        "comp_price_usd": float(r.get("comp_price_usd") or 0),
                        "comp_sale_price_usd": float(r["comp_sale_price_usd"]) if r.get("comp_sale_price_usd") else None,
                        "is_on_sale": bool(r.get("is_on_sale")),
                        "availability": r.get("availability"),
                        "price_gap_pct": float(r.get("price_gap_pct") or 0),
                    }
                    for r in comp_rows
                ]
            except Exception as exc:
                logger.warning("Failed to fetch competitor intel from RDS: %s", exc)

            # 5. Pending AI recommendations from RDS
            try:
                recs = await self._fetch_pending_recommendations_from_db(_tenant_id)
                context["pending_recommendations"] = [
                    {
                        "recommendation_id": str(r["id"]),
                        "recommendation": r["recommendation"],
                        "sku_id": r["sku_id"],
                        "product_name": r["product_name"],
                        "brand": r["brand"],
                        "confidence_pct": int(r.get("confidence_pct") or 0),
                        "suggested_discount_pct": float(r.get("suggested_discount_pct") or 0),
                        "suggested_price_usd": float(r["suggested_price_usd"]) if r.get("suggested_price_usd") else None,
                        "retail_price_usd": float(r.get("retail_price_usd") or 0),
                        "cost_price_usd": float(r.get("cost_price_usd") or 0),
                        "current_stock": int(r.get("current_stock") or 0),
                        "explanation": r.get("explanation") or "",
                        "shap_features": r.get("shap_features_json") or [],
                        "rule_override": r.get("rule_override_json"),
                        "fallback_used": bool(r.get("fallback_used")),
                        "model_version": r.get("model_version") or "unknown",
                    }
                    for r in recs
                ]
            except Exception as exc:
                logger.warning("Failed to fetch recommendations from RDS: %s", exc)

        # Update Prometheus gauges
        retail_cash_runway_months.set(context["cash_runway_months"])
        retail_low_stock_sku_count.set(len(context["low_stock_skus"]))

        # Cache result
        try:
            await self._conv.set_cached_business_data(chat_id, context)
        except Exception as exc:
            logger.warning("Failed to write business data cache: %s", exc)

        return context

    async def warmup(self) -> None:
        """Load financial data and pre-populate Prometheus gauges at startup."""
        try:
            fp = self._load_financial_profile()
            runway = float(fp.get("cashflow_summary", {}).get("cash_runway_months", 0))
            retail_cash_runway_months.set(runway)
            logger.info("Warmup: cash_runway_months=%.1f", runway)
        except Exception as exc:
            logger.warning("Warmup failed: %s", exc)

    async def get_cash_runway(self) -> float:
        fp = self._load_financial_profile()
        return float(fp.get("cashflow_summary", {}).get("cash_runway_months", 0))

    async def get_low_stock_skus(self) -> list[dict[str, Any]]:
        ctx = await self.get_business_context("__internal__")
        return ctx.get("low_stock_skus", [])

    async def get_dead_stock_skus(self) -> list[dict[str, Any]]:
        ctx = await self.get_business_context("__internal__")
        return ctx.get("dead_stock_skus", [])

    # ── Tool-facing public wrappers ────────────────────────────────────────────

    async def get_inventory_overview(self, tenant_id: str) -> dict[str, Any]:
        """Summary inventory snapshot with proactive_insight field for the LLM."""
        items = await self._fetch_inventory_from_db(tenant_id)
        total_sku_count = len(items)
        total_units = sum(int(i.get("current_stock") or 0) for i in items)
        total_value = round(
            sum(float(i.get("current_stock") or 0) * float(i.get("cost_price_usd") or 0) for i in items), 2
        )
        low_stock = [
            {
                "sku_id": i["sku_id"],
                "product_name": i["product_name"],
                "brand": i["brand"],
                "units": int(i["current_stock"]),
                "reorder_point": int(i.get("reorder_point") or 0),
                "retail_price_usd": float(i.get("retail_price_usd") or 0),
            }
            for i in items
            if 0 < int(i.get("current_stock") or 0) <= max(int(i.get("reorder_point") or 5), 5)
        ][:10]
        dead_stock = sorted(
            [
                {
                    "sku_id": i["sku_id"],
                    "product_name": i["product_name"],
                    "brand": i["brand"],
                    "units": int(i["current_stock"]),
                    "value_usd": round(
                        float(i["current_stock"]) * float(i.get("cost_price_usd") or 0), 2
                    ),
                }
                for i in items
                if int(i.get("current_stock") or 0) > 30 and float(i.get("retail_price_usd") or 0) == 0
            ],
            key=lambda x: x["value_usd"],
            reverse=True,
        )[:10]

        dead_value = sum(d["value_usd"] for d in dead_stock)
        proactive_insight = None
        if total_value > 0 and dead_value / total_value > 0.15:
            proactive_insight = (
                f"Dead stock represents {dead_value / total_value * 100:.0f}% "
                f"(${dead_value:,.0f}) of your inventory value — consider a markdown bundle."
            )
        elif len(low_stock) >= 5:
            proactive_insight = (
                f"{len(low_stock)} SKUs are at or below their reorder point. "
                "Prioritise reorders before the weekend."
            )

        result: dict[str, Any] = {
            "total_sku_count": total_sku_count,
            "total_units": total_units,
            "total_inventory_value_usd": total_value,
            "low_stock_count": len(low_stock),
            "low_stock_skus": low_stock,
            "dead_stock_count": len(dead_stock),
            "dead_stock_skus": dead_stock,
        }
        if proactive_insight:
            result["proactive_insight"] = proactive_insight
        return result

    async def get_financials_snapshot(self, tenant_id: str) -> dict[str, Any]:
        """Financial snapshot combining CSV profile and live revenue from DB."""
        result: dict[str, Any] = {}
        try:
            fp = self._load_financial_profile()
            cf = fp.get("cashflow_summary", {})
            inv = fp.get("inventory_summary", {})
            result["cash_runway_months"] = float(cf.get("cash_runway_months", 0))
            result["monthly_fixed_opex_usd"] = float(cf.get("monthly_fixed_opex_usd", 0))
            result["blended_margin_pct"] = float(inv.get("blended_margin_pct", 0))
        except Exception as exc:
            logger.warning("Failed to load financial_profile.json: %s", exc)

        try:
            rev = await self._fetch_revenue_from_db(tenant_id)
            result["revenue_current_month_usd"] = float(rev.get("current_month_usd") or 0)
            result["revenue_last_7d_usd"] = float(rev.get("last_7d_usd") or 0)
            result["revenue_last_30d_usd"] = float(rev.get("last_30d_usd") or 0)
            result["transactions_this_month"] = int(rev.get("txn_count_this_month") or 0)
            if result.get("revenue_current_month_usd", 0) == 0:
                try:
                    result["revenue_current_month_usd"] = self._load_cashflow_current_month()
                    result["revenue_source"] = "csv_projection"
                except Exception:
                    result["revenue_source"] = "unavailable"
            else:
                result["revenue_source"] = "live_pos"
        except Exception as exc:
            logger.warning("Failed to fetch revenue for financials snapshot: %s", exc)

        runway = result.get("cash_runway_months", 0)
        if runway > 0 and runway < 2:
            result["proactive_insight"] = (
                f"URGENT: Cash runway is only {runway:.1f} months. "
                "Review OPEX cuts and accelerate collections immediately."
            )
        return result

    async def get_competitor_prices(
        self,
        tenant_id: str,
        sku_id: str | None = None,
        competitor_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Competitor price comparison, optionally filtered."""
        rows = await self._fetch_competitor_intel_from_db(tenant_id)
        result = [
            {
                "our_sku": r["our_sku"],
                "our_product": r["our_product"],
                "brand": r["brand"],
                "our_price_usd": float(r.get("our_price_usd") or 0),
                "competitor": r["competitor"],
                "comp_price_usd": float(r.get("comp_price_usd") or 0),
                "comp_sale_price_usd": float(r["comp_sale_price_usd"]) if r.get("comp_sale_price_usd") else None,
                "is_on_sale": bool(r.get("is_on_sale")),
                "price_gap_pct": float(r.get("price_gap_pct") or 0),
            }
            for r in rows
        ]
        if sku_id:
            result = [r for r in result if r["our_sku"].lower() == sku_id.lower()]
        if competitor_name:
            result = [r for r in result if competitor_name.lower() in r["competitor"].lower()]
        return result

    # ── New on-demand query methods ────────────────────────────────────────────

    async def _fetch_sku_velocity_trend(
        self, tenant_id: str, sku_id: str, days: int = 30
    ) -> dict[str, Any]:
        """Daily units/revenue for a specific SKU to show trend direction."""
        days_safe = days if days in (7, 14, 30) else 30
        sql = f"""
            SELECT
                date_trunc('day', st.sold_at)::date AS day,
                SUM(ti.quantity)::int                AS units_sold,
                ROUND(SUM(ti.quantity * ti.unit_price_usd * (1 - ti.discount_pct / 100.0))::numeric, 2) AS revenue_usd
            FROM core.sales_transactions st
            JOIN core.sales_transaction_lines ti ON ti.sales_transaction_id = st.id
            JOIN core.sku_variants sv ON sv.id = ti.variant_id
            WHERE sv.sku_id = %s
              AND st.tenant_id = %s
              AND st.sold_at >= now() - interval '{days_safe} days'
            GROUP BY 1
            ORDER BY 1
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (sku_id, tenant_id))
                rows = await cur.fetchall()
        finally:
            await conn.close()

        daily = [
            {"day": str(r["day"]), "units_sold": r["units_sold"], "revenue_usd": float(r["revenue_usd"])}
            for r in rows
        ]
        if not daily:
            return {"sku_id": sku_id, "days": days_safe, "daily": [], "trend": "no_data"}

        mid = len(daily) // 2
        first_half_avg = sum(d["units_sold"] for d in daily[:mid]) / max(mid, 1)
        second_half_avg = sum(d["units_sold"] for d in daily[mid:]) / max(len(daily) - mid, 1)
        if second_half_avg > first_half_avg * 1.1:
            trend = "accelerating"
        elif second_half_avg < first_half_avg * 0.9:
            trend = "decelerating"
        else:
            trend = "stable"

        total_units = sum(d["units_sold"] for d in daily)
        total_revenue = sum(d["revenue_usd"] for d in daily)
        return {
            "sku_id": sku_id,
            "days": days_safe,
            "total_units_sold": total_units,
            "total_revenue_usd": round(total_revenue, 2),
            "daily_avg_units": round(total_units / days_safe, 2),
            "trend": trend,
            "first_half_daily_avg": round(first_half_avg, 2),
            "second_half_daily_avg": round(second_half_avg, 2),
            "daily": daily,
        }

    async def _fetch_category_performance(
        self, tenant_id: str, days: int = 30
    ) -> list[dict[str, Any]]:
        """Revenue, units sold, and margin by product category."""
        days_safe = days if days in (7, 14, 30) else 30
        sql = f"""
            SELECT
                p.category,
                COUNT(DISTINCT sv.id)                            AS sku_count,
                SUM(ti.quantity)::int                            AS units_sold,
                ROUND(SUM(ti.quantity * ti.unit_price_usd * (1 - ti.discount_pct / 100.0))::numeric, 2) AS revenue_usd,
                ROUND(
                    AVG(
                        CASE WHEN ti.unit_price_usd > 0
                             THEN (ti.unit_price_usd - sv.cost_price_usd) / ti.unit_price_usd * 100
                        END
                    )::numeric, 1
                )                                                AS avg_margin_pct
            FROM core.sales_transactions st
            JOIN core.sales_transaction_lines ti ON ti.sales_transaction_id = st.id
            JOIN core.sku_variants sv ON sv.id = ti.variant_id
            JOIN core.products p ON p.id = sv.product_id
            WHERE st.tenant_id = %s
              AND st.sold_at >= now() - interval '{days_safe} days'
            GROUP BY p.category
            ORDER BY revenue_usd DESC
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (tenant_id,))
                rows = await cur.fetchall()
        finally:
            await conn.close()

        return [
            {
                "category": r["category"],
                "sku_count": r["sku_count"],
                "units_sold": r["units_sold"],
                "revenue_usd": float(r["revenue_usd"]),
                "avg_margin_pct": float(r["avg_margin_pct"]) if r["avg_margin_pct"] is not None else None,
            }
            for r in rows
        ]

    async def _fetch_stockout_days(self, tenant_id: str) -> list[dict[str, Any]]:
        """Estimate days until stockout for low-stock SKUs based on 30-day velocity."""
        sql = """
            WITH recent_velocity AS (
                SELECT sv.id AS variant_id,
                       COALESCE(SUM(ti.quantity)::float / 30.0, 0) AS daily_velocity
                FROM core.sku_variants sv
                LEFT JOIN core.sales_transaction_lines ti ON ti.variant_id = sv.id
                LEFT JOIN core.sales_transactions st ON st.id = ti.sales_transaction_id
                    AND st.sold_at >= now() - interval '30 days'
                WHERE sv.tenant_id = %s AND sv.status = 'active'
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
                        )
                        ELSE NULL
                   END::int                                        AS days_until_stockout,
                   sv.reorder_point
            FROM core.sku_variants sv
            JOIN core.products p ON p.id = sv.product_id
            LEFT JOIN core.inventory_balances ib ON ib.variant_id = sv.id
            LEFT JOIN recent_velocity rv ON rv.variant_id = sv.id
            WHERE sv.tenant_id = %s AND sv.status = 'active'
            GROUP BY sv.id, sv.sku_id, p.name, p.brand, sv.reorder_point, rv.daily_velocity
            HAVING COALESCE(SUM(ib.quantity_on_hand), 0) <= GREATEST(sv.reorder_point, 5)
               AND COALESCE(SUM(ib.quantity_on_hand), 0) > 0
            ORDER BY days_until_stockout ASC NULLS LAST
            LIMIT 15
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (tenant_id, tenant_id))
                rows = await cur.fetchall()
        finally:
            await conn.close()

        return [
            {
                "sku_id": r["sku_id"],
                "product_name": r["product_name"],
                "brand": r["brand"],
                "units_on_hand": r["units_on_hand"],
                "daily_velocity": float(r["daily_velocity"]),
                "days_until_stockout": r["days_until_stockout"],
                "reorder_point": r["reorder_point"],
            }
            for r in rows
        ]

    async def _fetch_reorder_suggestions(self, tenant_id: str) -> list[dict[str, Any]]:
        """Suggest reorder quantities for SKUs near or at their reorder point."""
        stockout_rows = await self._fetch_stockout_days(tenant_id)
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT sv.sku_id, sv.cost_price_usd
                    FROM core.sku_variants sv
                    WHERE sv.tenant_id = %s AND sv.status = 'active'
                    """,
                    (tenant_id,),
                )
                cost_rows = await cur.fetchall()
        finally:
            await conn.close()

        cost_map = {r["sku_id"]: float(r.get("cost_price_usd") or 0) for r in cost_rows}
        suggestions = []
        for item in stockout_rows:
            daily_vel = item["daily_velocity"]
            units_on_hand = item["units_on_hand"]
            # 14-day coverage at current velocity, with 20% safety buffer
            needed = max(int(daily_vel * 14 * 1.2) - units_on_hand, 1) if daily_vel > 0 else item["reorder_point"]
            cost = cost_map.get(item["sku_id"], 0)
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

    async def _fetch_live_signals_for_recommendation(
        self,
        tenant_id: str,
        sku_id: str,
        suggested_discount_pct: float = 0.0,
    ) -> dict[str, Any]:
        """
        Returns every signal Claude needs to reason about a recommendation
        without relying on pre-stored explanation strings.

        Fetches in one pass: inventory state, velocity, margin, competitor position.
        The caller (tool handler) attaches this to the recommendation dict so
        Claude Sonnet can reason from raw data instead of canned text.
        """
        sql = """
            WITH velocity AS (
                SELECT
                    sv.id AS variant_id,
                    COALESCE(SUM(ti.quantity)::float / 30.0, 0) AS daily_vel
                FROM core.sku_variants sv
                LEFT JOIN core.sales_transaction_lines ti ON ti.variant_id = sv.id
                LEFT JOIN core.sales_transactions st
                    ON st.id = ti.sales_transaction_id
                    AND st.sold_at >= now() - interval '30 days'
                WHERE sv.sku_id = %s AND sv.tenant_id = %s
                GROUP BY sv.id
            ),
            comp AS (
                SELECT
                    COUNT(*)                              AS total_tracked,
                    MIN(COALESCE(cl.competitor_sale_price, cl.competitor_price)) AS cheapest_price,
                    MIN(cl.shop_code)                     AS cheapest_shop,
                    SUM(CASE WHEN cl.is_on_sale THEN 1 ELSE 0 END)  AS on_sale_count,
                    SUM(CASE WHEN cl.availability = 'out_of_stock' THEN 1 ELSE 0 END) AS oos_count
                FROM intel.competitor_products_latest cl
                JOIN core.sku_variants sv2
                    ON sv2.style_code = cl.style_code
                    AND sv2.tenant_id = %s
                    AND sv2.sku_id = %s
                WHERE cl.data_valid = true
            )
            SELECT
                sv.sku_id,
                p.name                                       AS product_name,
                p.brand,
                p.category,
                sv.cost_price_usd,
                COALESCE(pr.amount, 0)                       AS retail_price_usd,
                COALESCE(SUM(ib.quantity_on_hand), 0)::int   AS units_on_hand,
                sv.reorder_point,
                ROUND(vel.daily_vel::numeric, 3)             AS daily_velocity,
                CASE WHEN vel.daily_vel > 0
                     THEN ROUND(
                        COALESCE(SUM(ib.quantity_on_hand), 0) / vel.daily_vel
                     )::int
                     ELSE NULL
                END                                          AS days_of_supply,
                comp.total_tracked,
                comp.cheapest_price,
                comp.cheapest_shop,
                comp.on_sale_count,
                comp.oos_count
            FROM core.sku_variants sv
            JOIN core.products p ON p.id = sv.product_id
            LEFT JOIN LATERAL (
                SELECT amount FROM core.prices
                WHERE variant_id = sv.id AND price_type = 'retail' AND valid_to IS NULL
                LIMIT 1
            ) pr ON true
            LEFT JOIN core.inventory_balances ib ON ib.variant_id = sv.id
            LEFT JOIN velocity vel ON vel.variant_id = sv.id
            LEFT JOIN comp ON true
            WHERE sv.tenant_id = %s AND sv.sku_id = %s
            GROUP BY sv.id, sv.sku_id, p.name, p.brand, p.category,
                     sv.cost_price_usd, sv.reorder_point, pr.amount,
                     vel.daily_vel, comp.total_tracked, comp.cheapest_price,
                     comp.cheapest_shop, comp.on_sale_count, comp.oos_count
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (sku_id, tenant_id, tenant_id, sku_id, tenant_id, sku_id))
                row = await cur.fetchone()
        finally:
            await conn.close()

        if not row:
            return {"sku_id": sku_id, "error": "SKU not found in live inventory"}

        retail = float(row["retail_price_usd"] or 0)
        cost = float(row["cost_price_usd"] or 0)
        units = int(row["units_on_hand"] or 0)
        vel = float(row["daily_velocity"] or 0)
        dos = row["days_of_supply"]
        margin_now = round((retail - cost) / retail * 100, 1) if retail > cost else 0.0
        cheapest = float(row["cheapest_price"] or 0)
        price_gap_pct = round((retail - cheapest) / retail * 100, 1) if retail > 0 and cheapest > 0 else None

        # Post-discount pricing
        disc = suggested_discount_pct or 0.0
        price_after = round(retail * (1 - disc / 100), 2) if disc > 0 else None
        margin_after = round((price_after - cost) / price_after * 100, 1) if price_after and price_after > cost else None

        # DOS zone — used by Claude to contextualise
        if dos is None:
            dos_zone = "no_velocity_data"
        elif dos < 14:
            dos_zone = "critical_low (< 14 days — risk of stockout)"
        elif dos < 30:
            dos_zone = "low (14–30 days — reorder soon)"
        elif dos <= 90:
            dos_zone = "healthy (30–90 days)"
        elif dos <= 120:
            dos_zone = "excess (90–120 days — above optimal)"
        else:
            dos_zone = "dead_stock (120+ days — capital trapped)"

        # Margin zone
        if margin_now >= 50:
            margin_zone = "high — strong pricing power"
        elif margin_now >= 35:
            margin_zone = "healthy — above the 35% protection floor"
        elif margin_now >= 25:
            margin_zone = "thin — approaching the 35% floor"
        else:
            margin_zone = "below floor — cannot discount without special approval"

        return {
            "sku_id": row["sku_id"],
            "product_name": row["product_name"],
            "brand": row["brand"],
            "category": row["category"],
            "inventory": {
                "units_on_hand": units,
                "daily_velocity_30d": vel,
                "days_of_supply": dos,
                "dos_zone": dos_zone,
                "reorder_point": row["reorder_point"],
            },
            "pricing": {
                "retail_price_usd": retail,
                "cost_price_usd": cost,
                "current_margin_pct": margin_now,
                "margin_zone": margin_zone,
                "suggested_discount_pct": disc if disc > 0 else None,
                "price_after_discount_usd": price_after,
                "margin_after_discount_pct": margin_after,
                "margin_floor_pct": 35.0,
            },
            "competition": {
                "competitors_tracked": int(row["total_tracked"] or 0),
                "cheapest_competitor_price_usd": cheapest if cheapest > 0 else None,
                "cheapest_competitor": row["cheapest_shop"],
                "our_price_vs_cheapest_gap_pct": price_gap_pct,
                "price_position": (
                    "above_market" if (price_gap_pct or 0) > 5
                    else "below_market" if (price_gap_pct or 0) < -5
                    else "at_market"
                ),
                "competitors_on_sale": int(row["on_sale_count"] or 0),
                "competitors_out_of_stock": int(row["oos_count"] or 0),
            },
            "data_freshness": {
                "inventory": "live (real-time)",
                "competitor_prices": "up to 48h old",
            },
        }

    async def _fetch_sku_live_snapshot(self, tenant_id: str, sku_id: str) -> dict[str, Any]:
        """
        Returns a live inventory + pricing + competitor snapshot for a single SKU.
        Used to cross-reference recommendation reasoning with current real data.
        """
        sql = """
            SELECT
                sv.sku_id,
                p.name                                       AS product_name,
                p.brand,
                p.category,
                sv.cost_price_usd,
                COALESCE(pr.amount, 0)                       AS retail_price_usd,
                COALESCE(SUM(ib.quantity_on_hand), 0)::int   AS current_stock,
                sv.reorder_point,
                ROUND(
                    (COALESCE(pr.amount, 0) - sv.cost_price_usd)
                    / NULLIF(COALESCE(pr.amount, 0), 0) * 100
                , 1)                                         AS margin_pct,
                -- 30-day velocity from sales
                COALESCE(vel.daily_velocity, 0)              AS daily_velocity,
                CASE WHEN COALESCE(vel.daily_velocity, 0) > 0
                     THEN ROUND(
                        COALESCE(SUM(ib.quantity_on_hand), 0) / vel.daily_velocity
                     )
                     ELSE NULL
                END::int                                     AS days_of_supply
            FROM core.sku_variants sv
            JOIN core.products p ON p.id = sv.product_id
            LEFT JOIN LATERAL (
                SELECT amount FROM core.prices
                WHERE variant_id = sv.id AND price_type = 'retail' AND valid_to IS NULL
                LIMIT 1
            ) pr ON true
            LEFT JOIN core.inventory_balances ib ON ib.variant_id = sv.id
            LEFT JOIN LATERAL (
                SELECT COALESCE(SUM(ti.quantity)::float / 30.0, 0) AS daily_velocity
                FROM core.sales_transaction_lines ti
                JOIN core.sales_transactions st ON st.id = ti.sales_transaction_id
                WHERE ti.variant_id = sv.id
                  AND st.sold_at >= now() - interval '30 days'
            ) vel ON true
            WHERE sv.tenant_id = %s AND sv.sku_id = %s
            GROUP BY sv.id, sv.sku_id, p.name, p.brand, p.category,
                     sv.cost_price_usd, sv.reorder_point, pr.amount, vel.daily_velocity
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (tenant_id, sku_id))
                row = await cur.fetchone()
        finally:
            await conn.close()

        if not row:
            return {"sku_id": sku_id, "error": "SKU not found in live inventory"}

        # Competitor data for this SKU
        comp_rows = await self.get_competitor_prices(tenant_id, sku_id=sku_id)

        return {
            "sku_id": row["sku_id"],
            "product_name": row["product_name"],
            "brand": row["brand"],
            "category": row["category"],
            "live_stock_units": row["current_stock"],
            "days_of_supply": row["days_of_supply"],
            "daily_velocity_units": round(float(row["daily_velocity"]), 2),
            "retail_price_usd": float(row["retail_price_usd"]),
            "cost_price_usd": float(row["cost_price_usd"]),
            "margin_pct": float(row["margin_pct"]) if row["margin_pct"] is not None else None,
            "reorder_point": row["reorder_point"],
            "data_source": "live_rds",
            "competitors": comp_rows[:5],
        }

    async def _fetch_revenue_trend(self, tenant_id: str) -> dict[str, Any]:
        """This-week vs last-week daily revenue average with trend direction."""
        sql = """
            SELECT date_trunc('day', sold_at)::date AS day,
                   ROUND(SUM(total_amount_usd)::numeric, 2) AS revenue_usd
            FROM core.sales_transactions
            WHERE tenant_id = %s
              AND sold_at >= now() - interval '14 days'
            GROUP BY 1
            ORDER BY 1
        """
        conn = await self._db_connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, (tenant_id,))
                rows = await cur.fetchall()
        finally:
            await conn.close()

        if not rows:
            return {"trend": "no_data", "this_week_daily_avg_usd": 0, "last_week_daily_avg_usd": 0, "trend_pct": 0}

        from datetime import date as _date
        today = _date.today()
        this_week = [r for r in rows if (today - r["day"]).days < 7]
        last_week = [r for r in rows if 7 <= (today - r["day"]).days < 14]

        this_avg = sum(float(r["revenue_usd"]) for r in this_week) / max(len(this_week), 1)
        last_avg = sum(float(r["revenue_usd"]) for r in last_week) / max(len(last_week), 1)
        trend_pct = ((this_avg - last_avg) / max(last_avg, 1)) * 100 if last_avg else 0

        return {
            "this_week_daily_avg_usd": round(this_avg, 2),
            "last_week_daily_avg_usd": round(last_avg, 2),
            "trend_pct": round(trend_pct, 1),
            "direction": "up" if trend_pct > 5 else "down" if trend_pct < -5 else "flat",
            "daily": [{"day": str(r["day"]), "revenue_usd": float(r["revenue_usd"])} for r in rows],
        }

    # ── Public API aliases ────────────────────────────────────────────────────
    # These thin wrappers expose the private fetch methods as stable public API so
    # callers (ai_engine dispatch, tests) don't depend on private naming conventions.

    async def get_stockout_days(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._fetch_stockout_days(tenant_id)

    async def get_reorder_suggestions(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._fetch_reorder_suggestions(tenant_id)

    async def get_sku_velocity_trend(
        self, tenant_id: str, sku_id: str, days: int = 30
    ) -> dict[str, Any]:
        return await self._fetch_sku_velocity_trend(tenant_id, sku_id, days)

    async def get_category_performance(
        self, tenant_id: str, days: int = 30
    ) -> list[dict[str, Any]]:
        return await self._fetch_category_performance(tenant_id, days)

    async def get_revenue_trend(self, tenant_id: str) -> dict[str, Any]:
        return await self._fetch_revenue_trend(tenant_id)

    async def get_pending_recommendations(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._fetch_pending_recommendations_from_db(tenant_id)

    async def get_live_signals_for_recommendation(
        self, tenant_id: str, sku_id: str, discount_pct: float
    ) -> dict[str, Any]:
        return await self._fetch_live_signals_for_recommendation(tenant_id, sku_id, discount_pct)

    async def get_sku_live_snapshot(self, tenant_id: str, sku_id: str) -> dict[str, Any]:
        return await self._fetch_sku_live_snapshot(tenant_id, sku_id)


# ── Formatting helper ─────────────────────────────────────────────────────────

def format_business_context_for_prompt(context: dict[str, Any]) -> str:
    ts = context.get("timestamp", "unknown")
    lines = [f"LIVE BUSINESS DATA (as of {ts}):"]

    # ── Financial ─────────────────────────────────────────────────────────────
    lines.append("\n[FINANCIALS]")
    lines.append(f"- Cash runway: {context.get('cash_runway_months', 0)} months")
    lines.append(f"- Monthly fixed OPEX: ${context.get('monthly_fixed_opex', 0):,.0f}")
    lines.append(f"- Blended gross margin: {context.get('blended_margin_pct', 0):.1f}%")

    # ── Revenue ───────────────────────────────────────────────────────────────
    rev_source = context.get("_revenue_source", "unknown")
    lines.append(f"\n[REVENUE] (source: {rev_source})")
    lines.append(f"- This month so far: ${context.get('revenue_current_month_usd', 0):,.2f}")
    lines.append(f"- Last 7 days: ${context.get('revenue_last_7d_usd', 0):,.2f}")
    lines.append(f"- Last 30 days: ${context.get('revenue_last_30d_usd', 0):,.2f}")
    lines.append(f"- Transactions this month: {context.get('sales_txn_count_this_month', 0)}")

    # ── Inventory ─────────────────────────────────────────────────────────────
    lines.append(f"\n[INVENTORY]")
    lines.append(f"- Total SKUs: {context.get('total_sku_count', 0)}")
    lines.append(f"- Total units on hand: {context.get('total_units', 0)}")
    lines.append(f"- Inventory value (at cost): ${context.get('total_inventory_value_usd', 0):,.2f}")

    low_stock = context.get("low_stock_skus", [])
    if low_stock:
        lines.append(f"\n[LOW STOCK — {len(low_stock)} SKUs at or below reorder point]")
        for s in low_stock[:8]:
            lines.append(f"  • {s['brand']} {s['product_name']} ({s['sku_id']}): {s['units']} units left (reorder at {s['reorder_point']}), retail ${s['retail_price_usd']:.2f}")
    else:
        lines.append("- Low stock SKUs: none detected (inventory not yet synced)")

    dead = context.get("dead_stock_skus", [])
    if dead:
        lines.append(f"\n[DEAD STOCK — {len(dead)} SKUs with high stock, no price set]")
        for s in dead[:5]:
            lines.append(f"  • {s['brand']} {s['product_name']} ({s['sku_id']}): {s['units']} units, ${s['value_usd']:,.2f} tied up")

    # ── Competitor intel ──────────────────────────────────────────────────────
    comp = context.get("competitor_intel", [])
    if comp:
        lines.append(f"\n[COMPETITOR PRICES — {len(comp)} matched SKUs]")
        for c in comp[:12]:
            sale_note = f" (ON SALE: ${c['comp_sale_price_usd']:.2f})" if c.get("comp_sale_price_usd") else ""
            avail = f", {c['availability']}" if c.get("availability") else ""
            gap = c.get("price_gap_pct", 0)
            gap_note = f"we are {abs(gap):.1f}% {'MORE expensive' if gap > 0 else 'cheaper'}"
            lines.append(
                f"  • {c['brand']} {c['our_product']} ({c['our_sku']}): "
                f"our ${c['our_price_usd']:.2f} vs {c['competitor']} ${c['comp_price_usd']:.2f}{sale_note}{avail} — {gap_note}"
            )
    else:
        lines.append("\n[COMPETITOR PRICES] No matched competitor data yet (scraper not yet synced to DB)")

    # ── AI Recommendations ────────────────────────────────────────────────────
    recs = context.get("pending_recommendations", [])
    if recs:
        lines.append(f"\n[PENDING AI RECOMMENDATIONS — {len(recs)} items]")
        for r in recs:
            price_note = f"→ ${r['suggested_price_usd']:.2f}" if r.get("suggested_price_usd") else ""
            lines.append(
                f"  • {r['recommendation']} {r['brand']} {r['product_name']} ({r['sku_id']}): "
                f"{r['confidence_pct']}% confidence, {r['suggested_discount_pct']:.0f}% off {price_note} — {r['explanation'][:80]}"
            )
    else:
        lines.append("\n[PENDING AI RECOMMENDATIONS] None pending")

    return "\n".join(lines)


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    from pathlib import Path as _Path

    _env_file = _Path(__file__).parent / ".env"
    if _env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=True)

    _DB_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    _DATA_DIR = str(_Path(__file__).resolve().parents[2] / "data" / "real")

    TEST_PHONE = "+96170000000"

    async def _run_test() -> None:
        svc = BusinessDataService(
            eep_base_url="",
            db_url=_DB_URL,
            financial_data_path=_DATA_DIR,
        )

        ctx = await svc.get_business_context(TEST_PHONE, force_refresh=True)
        print(format_business_context_for_prompt(ctx))

        runway = ctx.get("cash_runway_months", 0)
        assert runway > 0, f"Expected cash_runway_months > 0, got {runway}"
        print(f"\ncash_runway_months = {runway}")
        print("Business data test passed")

    asyncio.run(
        _run_test(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
