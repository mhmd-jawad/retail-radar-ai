"""
Business Data Service — fetches and caches live business KPIs for WhatsApp AI context.

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

from services.whatsapp_assistant.conversation import ConversationManager, DEFAULT_DATABASE_URL

logger = logging.getLogger("whatsapp_assistant.business_data")

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
        eep_base_url: str,
        db_url: str,
        financial_data_path: str,
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
                r.recommendation,
                ROUND(r.confidence * 100)::int   AS confidence_pct,
                r.suggested_discount_pct,
                r.suggested_price_usd,
                r.explanation,
                r.generated_at,
                sv.sku_id,
                p.name                           AS product_name,
                p.brand,
                p.category,
                COALESCE(pr.amount, 0)           AS retail_price_usd,
                sv.cost_price_usd
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
        self, phone_number: str, force_refresh: bool = False,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        # Check cache
        if not force_refresh:
            try:
                cached_data, cached_at = await self._conv.get_cached_business_data(phone_number)
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
                        "recommendation": r["recommendation"],
                        "sku_id": r["sku_id"],
                        "product_name": r["product_name"],
                        "brand": r["brand"],
                        "confidence_pct": int(r.get("confidence_pct") or 0),
                        "suggested_discount_pct": float(r.get("suggested_discount_pct") or 0),
                        "suggested_price_usd": float(r["suggested_price_usd"]) if r.get("suggested_price_usd") else None,
                        "retail_price_usd": float(r.get("retail_price_usd") or 0),
                        "explanation": r.get("explanation") or "",
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
            await self._conv.set_cached_business_data(phone_number, context)
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
