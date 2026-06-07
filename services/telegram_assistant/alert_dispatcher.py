"""
Alert Dispatcher — proactive retailer notifications via Telegram.

Polls for business conditions every 30 minutes and sends formatted alerts when
thresholds are crossed. Each alert type has an independent cooldown to prevent spam.

Alert categories:
  INVENTORY  — stockout imminent, reorder triggered, dead stock high-value
  FINANCIAL  — cash runway critical, low margin
  REVENUE    — weekly revenue drop, revenue milestone
  COMPETITOR — competitor sale started, competitor price undercut

Approval/recommendation alerts are handled by promotion_approval_flow.py (poll every 5 min).
Decision progress alerts are handled by outcome_tracking.py (poll every 15 min).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from services.common.price_normalization import (
    effective_competitor_price_usd,
    normalize_competitor_price_usd,
    price_gap_pct,
)

if TYPE_CHECKING:
    from services.telegram_assistant.telegram_client import TelegramClient

logger = logging.getLogger("telegram_assistant.alert_dispatcher")

# ── Alert type registry ───────────────────────────────────────────────────────
# Each entry: (label, description, cooldown_hours)
ALERT_TYPES: dict[str, tuple[str, str, int]] = {
    # INVENTORY
    "stockout_imminent": (
        "Stockout Imminent",
        "SKU has ≤ 3 days of supply at current sales velocity",
        8,
    ),
    "reorder_triggered": (
        "Reorder Point Breached",
        "SKU stock fell to or below its configured reorder point",
        24,
    ),
    "dead_stock_value": (
        "Dead Stock — Capital Tied Up",
        "SKU has had no sales for 30+ days with >$500 in inventory cost",
        72,
    ),
    # FINANCIAL
    "cash_runway_critical": (
        "Cash Runway Critical",
        "Cash runway dropped below 2 months at current OPEX burn",
        24,
    ),
    "low_blended_margin": (
        "Low Margin Warning",
        "Blended gross margin fell below 25%",
        48,
    ),
    # REVENUE
    "revenue_drop_weekly": (
        "Weekly Revenue Drop",
        "This week's daily revenue average is >20% below last week",
        48,
    ),
    "revenue_milestone": (
        "Revenue Milestone",
        "Monthly revenue crossed 75% or 100% of last month's total",
        24,
    ),
    # COMPETITOR
    "competitor_sale_started": (
        "Competitor Sale Started",
        "A competitor started a sale on a product you carry",
        24,
    ),
    "competitor_price_undercut": (
        "Competitor Price Undercut",
        "A competitor's price is now >15% below your retail price on a matched SKU",
        24,
    ),
}


# ── DB migration ──────────────────────────────────────────────────────────────

async def ensure_alert_tables(db_url: str) -> None:
    """Create telegram.alert_log table if not present."""
    conn = await psycopg.AsyncConnection.connect(db_url)
    try:
        async with conn.cursor() as cur:
            await cur.execute("CREATE SCHEMA IF NOT EXISTS telegram")
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram.alert_log (
                    id          BIGSERIAL PRIMARY KEY,
                    tenant_id   UUID      NOT NULL,
                    chat_id TEXT     NOT NULL,
                    alert_type  TEXT      NOT NULL,
                    subject_key TEXT      NOT NULL DEFAULT '',
                    message_text TEXT     NOT NULL,
                    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_alert_log_cooldown
                    ON telegram.alert_log
                    (tenant_id, chat_id, alert_type, subject_key, sent_at DESC)
                """
            )
        await conn.commit()
    finally:
        await conn.close()


# ── Alert Dispatcher ──────────────────────────────────────────────────────────────

class AlertDispatcher:
    """
    Polls business conditions on a schedule and sends Telegram alerts.

    Usage:
        engine = AlertDispatcher(db_url, telegram_client, retailer_chat_id, tenant_id, data_dir)
        asyncio.create_task(alert_poll_loop(engine))
    """

    def __init__(
        self,
        db_url: str,
        telegram_client: "TelegramClient",
        retailer_chat_id: str,
        tenant_id: UUID,
        financial_data_path: str,
    ) -> None:
        self._db_url = db_url
        self._telegram = telegram_client
        self._chat_id = retailer_chat_id
        self._tenant_id = tenant_id
        self._tid = str(tenant_id)
        from pathlib import Path
        self._data_dir = Path(financial_data_path)

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run_all_checks(self) -> int:
        """Run every alert category and return the total number of alerts sent."""
        sent = 0
        checks = [
            self._check_stockout_imminent,
            self._check_reorder_triggered,
            self._check_dead_stock,
            self._check_cash_runway,
            self._check_low_margin,
            self._check_revenue_drop,
        ]
        competitor_alerts = os.environ.get("TELEGRAM_COMPETITOR_ALERTS_ENABLED", "false").strip().lower()
        if competitor_alerts in {"1", "true", "yes", "on"}:
            checks.extend([
                self._check_competitor_sale,
                self._check_competitor_price_undercut,
            ])
        for check in checks:
            try:
                sent += await check()
            except Exception as exc:
                logger.error("Alert check %s failed: %s", check.__name__, exc, exc_info=True)
        return sent

    # ── INVENTORY ALERTS ──────────────────────────────────────────────────────

    async def _check_stockout_imminent(self) -> int:
        """Send alert when a SKU has ≤ 3 days of supply remaining."""
        sql = """
            WITH velocity AS (
                SELECT sv.id AS variant_id,
                       sv.sku_id,
                       COALESCE(SUM(ti.quantity)::float / 30.0, 0) AS daily_vel
                FROM core.sku_variants sv
                LEFT JOIN core.sales_transaction_lines ti ON ti.variant_id = sv.id
                LEFT JOIN core.sales_transactions st
                    ON st.id = ti.sales_transaction_id
                    AND st.sold_at >= now() - interval '30 days'
                WHERE sv.tenant_id = %s AND sv.status = 'active'
                GROUP BY sv.id, sv.sku_id
            )
            SELECT sv.sku_id,
                   p.name  AS product_name,
                   p.brand,
                   COALESCE(SUM(ib.quantity_on_hand), 0)::int AS units,
                   v.daily_vel,
                   ROUND(
                       CASE WHEN v.daily_vel > 0
                            THEN COALESCE(SUM(ib.quantity_on_hand), 0) / v.daily_vel
                            ELSE NULL END
                   )::int AS days_left
            FROM core.sku_variants sv
            JOIN core.products p ON p.id = sv.product_id
            LEFT JOIN core.inventory_balances ib ON ib.variant_id = sv.id
            LEFT JOIN velocity v ON v.variant_id = sv.id
            WHERE sv.tenant_id = %s AND sv.status = 'active'
            GROUP BY sv.id, sv.sku_id, p.name, p.brand, v.daily_vel
            HAVING v.daily_vel > 0
               AND COALESCE(SUM(ib.quantity_on_hand), 0) > 0
               AND COALESCE(SUM(ib.quantity_on_hand), 0) / v.daily_vel <= 3
            ORDER BY days_left ASC
            LIMIT 10
        """
        rows = await self._query(sql, (self._tid, self._tid))
        sent = 0
        for r in rows:
            days = r["days_left"] or 0
            msg = (
                f"*⚠️ Stockout Alert — {r['brand']} {r['product_name']}*\n"
                f"SKU: {r['sku_id']}\n\n"
                f"Only *{r['units']} units* left — *{days} day{'s' if days != 1 else ''} of supply* "
                f"at current velocity of {r['daily_vel']:.1f} units/day.\n\n"
                f"Next step: place a reorder now or ask Radar for suggested quantities."
            )
            if await self._send_if_new("stockout_imminent", r["sku_id"], msg, cooldown_hours=8):
                sent += 1
        return sent

    async def _check_reorder_triggered(self) -> int:
        """Send alert when a SKU stock falls to or below its reorder point."""
        sql = """
            SELECT sv.sku_id,
                   p.name  AS product_name,
                   p.brand,
                   COALESCE(SUM(ib.quantity_on_hand), 0)::int AS units,
                   sv.reorder_point,
                   ROUND(sv.cost_price_usd * GREATEST(sv.reorder_point * 2, 10), 2) AS est_order_cost
            FROM core.sku_variants sv
            JOIN core.products p ON p.id = sv.product_id
            LEFT JOIN core.inventory_balances ib ON ib.variant_id = sv.id
            WHERE sv.tenant_id = %s
              AND sv.status = 'active'
              AND sv.reorder_point > 0
            GROUP BY sv.id, sv.sku_id, p.name, p.brand, sv.reorder_point, sv.cost_price_usd
            HAVING COALESCE(SUM(ib.quantity_on_hand), 0) <= sv.reorder_point
               AND COALESCE(SUM(ib.quantity_on_hand), 0) > 0
            ORDER BY (sv.reorder_point - COALESCE(SUM(ib.quantity_on_hand), 0)) DESC
            LIMIT 10
        """
        rows = await self._query(sql, (self._tid,))
        sent = 0
        for r in rows:
            msg = (
                f"*📦 Reorder Needed — {r['brand']} {r['product_name']}*\n"
                f"SKU: {r['sku_id']}\n\n"
                f"*{r['units']} units* left — at or below reorder point of *{r['reorder_point']}*.\n"
                f"Estimated restock cost: *~${float(r['est_order_cost']):,.0f}*\n\n"
                f"Ask Radar: \"what should I order for {r['sku_id']}?\""
            )
            if await self._send_if_new("reorder_triggered", r["sku_id"], msg, cooldown_hours=24):
                sent += 1
        return sent

    async def _check_dead_stock(self) -> int:
        """Send alert for high-value SKUs with no sales in 30+ days."""
        sql = """
            WITH last_sale AS (
                SELECT ti.variant_id,
                       MAX(st.sold_at) AS last_sold_at
                FROM core.sales_transaction_lines ti
                JOIN core.sales_transactions st ON st.id = ti.sales_transaction_id
                WHERE st.tenant_id = %s
                GROUP BY ti.variant_id
            )
            SELECT sv.sku_id,
                   p.name  AS product_name,
                   p.brand,
                   COALESCE(SUM(ib.quantity_on_hand), 0)::int    AS units,
                   ROUND(
                       COALESCE(SUM(ib.quantity_on_hand), 0) * sv.cost_price_usd, 2
                   )                                              AS tied_up_usd,
                   EXTRACT(DAY FROM now() - ls.last_sold_at)::int AS days_no_sale,
                   CASE
                       WHEN EXTRACT(DAY FROM now() - ls.last_sold_at) < 45 THEN 15
                       WHEN EXTRACT(DAY FROM now() - ls.last_sold_at) < 90 THEN 25
                       ELSE 35
                   END                                            AS suggested_markdown_pct
            FROM core.sku_variants sv
            JOIN core.products p ON p.id = sv.product_id
            LEFT JOIN core.inventory_balances ib ON ib.variant_id = sv.id
            LEFT JOIN last_sale ls ON ls.variant_id = sv.id
            WHERE sv.tenant_id = %s
              AND sv.status = 'active'
              AND (ls.last_sold_at IS NULL OR ls.last_sold_at < now() - interval '30 days')
            GROUP BY sv.id, sv.sku_id, p.name, p.brand, sv.cost_price_usd, ls.last_sold_at
            HAVING COALESCE(SUM(ib.quantity_on_hand), 0) * sv.cost_price_usd > 500
            ORDER BY tied_up_usd DESC
            LIMIT 5
        """
        rows = await self._query(sql, (self._tid, self._tid))
        sent = 0
        for r in rows:
            days = r["days_no_sale"] or 30
            msg = (
                f"*🔴 Dead Stock Alert — {r['brand']} {r['product_name']}*\n"
                f"SKU: {r['sku_id']}\n\n"
                f"*No sales in {days} days.* "
                f"*${float(r['tied_up_usd']):,.0f}* tied up in {r['units']} units.\n"
                f"Suggested markdown: *{r['suggested_markdown_pct']}% off* to unlock cash.\n\n"
                f"Ask Radar: \"markdown {r['sku_id']}\" to see the AI recommendation."
            )
            if await self._send_if_new("dead_stock_value", r["sku_id"], msg, cooldown_hours=72):
                sent += 1
        return sent

    # ── FINANCIAL ALERTS ──────────────────────────────────────────────────────

    async def _check_cash_runway(self) -> int:
        """Send alert when cash runway drops below 2 months."""
        try:
            import json as _json
            fp_path = self._data_dir / "financial_profile.json"
            with open(fp_path, encoding="utf-8") as f:
                fp = _json.load(f)
            runway = float(fp.get("cashflow_summary", {}).get("cash_runway_months", 0))
            opex = float(fp.get("cashflow_summary", {}).get("monthly_fixed_opex_usd", 0))
        except Exception:
            return 0

        if runway <= 0 or runway >= 2:
            return 0

        msg = (
            f"*🚨 URGENT — Cash Runway: {runway:.1f} Months*\n\n"
            f"At your current fixed burn of *${opex:,.0f}/month*, "
            f"you have *{runway:.1f} months* of cash remaining.\n\n"
            f"*Immediate actions:*\n"
            f"• Review non-essential OPEX line items\n"
            f"• Accelerate payment collections\n"
            f"• Consider markdown on dead stock to generate cash\n\n"
            f"Ask Radar: \"show me financials\" for the full picture."
        )
        sent = await self._send_if_new("cash_runway_critical", "", msg, cooldown_hours=24)
        return 1 if sent else 0

    async def _check_low_margin(self) -> int:
        """Send alert when blended gross margin falls below 25%."""
        try:
            import json as _json
            fp_path = self._data_dir / "financial_profile.json"
            with open(fp_path, encoding="utf-8") as f:
                fp = _json.load(f)
            margin = float(fp.get("inventory_summary", {}).get("blended_margin_pct", 0))
        except Exception:
            return 0

        if margin <= 0 or margin >= 25:
            return 0

        msg = (
            f"*⚠️ Low Margin Warning — {margin:.1f}%*\n\n"
            f"Your blended gross margin has dropped to *{margin:.1f}%*, "
            f"below the healthy threshold of 25%.\n\n"
            f"*Common causes:*\n"
            f"• Excessive markdowns eroding margins\n"
            f"• Competitor pressure forcing price cuts\n"
            f"• High-cost SKUs selling more than high-margin ones\n\n"
            f"Ask Radar: \"which category has the lowest margin?\" to pinpoint the issue."
        )
        sent = await self._send_if_new("low_blended_margin", "", msg, cooldown_hours=48)
        return 1 if sent else 0

    # ── REVENUE ALERTS ────────────────────────────────────────────────────────

    async def _check_revenue_drop(self) -> int:
        """Send alert when this week's daily revenue is >20% below last week's."""
        sql = """
            SELECT
                COALESCE(SUM(CASE WHEN sold_at >= now() - interval '7 days'
                                  THEN total_amount_usd END), 0) AS this_week,
                COALESCE(SUM(CASE WHEN sold_at >= now() - interval '14 days'
                                   AND sold_at < now() - interval '7 days'
                                  THEN total_amount_usd END), 0) AS last_week
            FROM core.sales_transactions
            WHERE tenant_id = %s
              AND sold_at >= now() - interval '14 days'
        """
        rows = await self._query(sql, (self._tid,))
        if not rows:
            return 0

        this_week = float(rows[0]["this_week"] or 0)
        last_week = float(rows[0]["last_week"] or 0)

        if last_week == 0 or this_week == 0:
            return 0

        drop_pct = ((last_week - this_week) / last_week) * 100
        if drop_pct < 20:
            return 0

        this_daily = this_week / 7
        last_daily = last_week / 7
        msg = (
            f"*📉 Revenue Alert — Down {drop_pct:.0f}% This Week*\n\n"
            f"This week's daily average: *${this_daily:,.0f}*\n"
            f"Last week's daily average: *${last_daily:,.0f}*\n"
            f"Total this week: *${this_week:,.0f}* vs *${last_week:,.0f}* last week.\n\n"
            f"*Possible causes:* weekend effect, competitor promotion, out-of-stock SKUs.\n\n"
            f"Ask Radar: \"what's selling this week?\" or \"show competitor prices\"."
        )
        sent = await self._send_if_new("revenue_drop_weekly", "", msg, cooldown_hours=48)
        return 1 if sent else 0

    # ── COMPETITOR ALERTS ─────────────────────────────────────────────────────

    async def _check_competitor_sale(self) -> int:
        """Send alert when a competitor starts a sale on a product we carry."""
        sql = """
            SELECT DISTINCT ON (sv.sku_id, cl.shop_code)
                sv.sku_id,
                p.name       AS our_product,
                p.brand,
                cl.shop_code AS competitor,
                COALESCE(pr.amount, 0)       AS our_price,
                cl.competitor_price          AS comp_price,
                cl.competitor_sale_price     AS comp_sale_price,
                cl.currency,
                cl.is_on_sale
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
            WHERE cl.is_on_sale = true
              AND cl.data_valid = true
              AND cl.competitor_sale_price IS NOT NULL
            ORDER BY sv.sku_id, cl.shop_code, cl.last_seen_at DESC
        """
        rows = await self._query(sql, (self._tid,))
        sent = 0
        for r in rows:
            subject = f"{r['sku_id']}:{r['competitor']}"
            our_price = float(r["our_price"] or 0)
            sale_price = normalize_competitor_price_usd(r["comp_sale_price"], r.get("currency"))
            comp_price = normalize_competitor_price_usd(r["comp_price"], r.get("currency"))
            effective_price = effective_competitor_price_usd(
                r["comp_price"],
                r["comp_sale_price"],
                r.get("currency"),
                r.get("is_on_sale"),
            )
            gap_pct = price_gap_pct(our_price, effective_price)
            if sale_price is None or comp_price is None or gap_pct is None:
                continue

            msg = (
                f"*🔔 Competitor Sale — {r['competitor']}*\n\n"
                f"*{r['brand']} {r['our_product']}* ({r['sku_id']})\n"
                f"• {r['competitor']}: *${sale_price:.2f}* (was ${comp_price:.2f}) — ON SALE\n"
                f"• Your price: *${our_price:.2f}*\n"
                f"• You're *{gap_pct:.0f}% more expensive* right now.\n\n"
                f"Consider a temporary price match or bundle deal.\n"
                f"Ask Radar: \"should I markdown {r['sku_id']}?\""
            )
            if await self._send_if_new("competitor_sale_started", subject, msg, cooldown_hours=24):
                sent += 1
        return sent

    async def _check_competitor_price_undercut(self) -> int:
        """Send alert when a competitor's price is >15% below ours on a matched SKU."""
        sql = """
            SELECT DISTINCT ON (sv.sku_id, cl.shop_code)
                sv.sku_id,
                p.name       AS our_product,
                p.brand,
                cl.shop_code AS competitor,
                COALESCE(pr.amount, 0)   AS our_price,
                cl.competitor_price,
                cl.competitor_sale_price,
                cl.currency,
                cl.is_on_sale
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
              AND COALESCE(pr.amount, 0) > 0
            ORDER BY sv.sku_id, cl.shop_code, cl.last_seen_at DESC
        """
        rows = await self._query(sql, (self._tid,))
        sent = 0
        for r in rows:
            subject = f"{r['sku_id']}:{r['competitor']}"
            our_price = float(r["our_price"] or 0)
            their_price = effective_competitor_price_usd(
                r["competitor_price"],
                r["competitor_sale_price"],
                r.get("currency"),
                r.get("is_on_sale"),
            )
            gap = price_gap_pct(our_price, their_price)
            if gap is None or gap < 15 or their_price is None:
                continue
            msg = (
                f"*💰 Price Alert — {r['competitor']} Undercutting Us*\n\n"
                f"*{r['brand']} {r['our_product']}* ({r['sku_id']})\n"
                f"• {r['competitor']}: *${their_price:.2f}*\n"
                f"• Your price: *${our_price:.2f}*\n"
                f"• Gap: *{gap:.0f}% cheaper* than you.\n\n"
                f"This gap may be diverting sales. Consider a review.\n"
                f"Ask Radar: \"competitor prices for {r['sku_id']}\""
            )
            if await self._send_if_new("competitor_price_undercut", subject, msg, cooldown_hours=24):
                sent += 1
        return sent

    # ── Deduplication + sending ───────────────────────────────────────────────

    async def _send_if_new(
        self,
        alert_type: str,
        subject_key: str,
        message: str,
        cooldown_hours: int,
    ) -> bool:
        """Send the alert only if it hasn't been sent within the cooldown window."""
        if not await self._is_cooldown_elapsed(alert_type, subject_key, cooldown_hours):
            return False
        try:
            await self._telegram.send_text_message(self._chat_id, message)
            await self._log_alert(alert_type, subject_key, message)
            logger.info("Alert sent: type=%s subject=%s", alert_type, subject_key)
            return True
        except Exception as exc:
            logger.error("Failed to send alert %s/%s: %s", alert_type, subject_key, exc)
            return False

    async def _is_cooldown_elapsed(
        self, alert_type: str, subject_key: str, cooldown_hours: int
    ) -> bool:
        """Return True if no alert of this type was sent within the cooldown window."""
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT sent_at FROM telegram.alert_log
                    WHERE tenant_id = %s
                      AND chat_id = %s
                      AND alert_type = %s
                      AND subject_key = %s
                      AND sent_at >= now() - (%s * interval '1 hour')
                    ORDER BY sent_at DESC
                    LIMIT 1
                    """,
                    (self._tid, self._chat_id, alert_type, subject_key, cooldown_hours),
                )
                row = await cur.fetchone()
            return row is None
        finally:
            await conn.close()

    async def _log_alert(
        self, alert_type: str, subject_key: str, message: str
    ) -> None:
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO telegram.alert_log
                        (tenant_id, chat_id, alert_type, subject_key, message_text)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (self._tid, self._chat_id, alert_type, subject_key, message),
                )
            await conn.commit()
        finally:
            await conn.close()

    async def _query(self, sql: str, params: tuple) -> list[dict[str, Any]]:
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return await cur.fetchall()
        except Exception as exc:
            logger.error("Alert query failed: %s", exc)
            return []
        finally:
            await conn.close()


# ── Background poll loop ──────────────────────────────────────────────────────

async def alert_poll_loop(
    engine: AlertDispatcher,
    interval_seconds: int = 1800,
) -> None:
    """
    Background task: run all alert checks every `interval_seconds` (default 30 min).
    Each check is independently protected by per-type cooldowns — no duplicate spam.
    """
    # Initial delay so the service fully starts before the first check
    await asyncio.sleep(60)
    while True:
        try:
            count = await engine.run_all_checks()
            if count:
                logger.info("Alert cycle sent %d alert(s)", count)
        except Exception as exc:
            logger.error("Alert poll cycle failed: %s", exc, exc_info=True)
        await asyncio.sleep(interval_seconds)
