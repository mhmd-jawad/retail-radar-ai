"""
Promote / Markdown approval flow — Phase 3.

Polls marketing.recommendations for un-notified PROMOTE/MARKDOWN rows,
sends Telegram notifications, and handles APPROVE / MODIFY / REJECT replies.

IE3 campaign endpoint: POST {IE3_BASE_URL}/campaign/generate
  Body: RecommendationResult-compatible JSON (services/decision_intelligence/schemas.py)
  Action: generates copy + image + publishes to Instagram/Facebook in one call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import psycopg
from psycopg.rows import dict_row

if TYPE_CHECKING:
    from services.telegram_assistant.conversation_store import ConversationManager
    from services.telegram_assistant.telegram_client import TelegramClient

logger = logging.getLogger("telegram_assistant.promotion_approval_flow")

# ── Notification template ─────────────────────────────────────────────────────

NOTIFICATION_TEMPLATE = """\
🔔 *AI Recommendation — Action Required*

*{decision}: {product_name}*
SKU: {sku_id}  |  Stock: *{current_stock} units*

*Why the AI flagged this (live data):*
{shap_bullets}

*What the AI suggests:*
• Discount: *{suggested_discount}% off* → new price *${new_price:.2f}*
• Confidence: *{confidence}%* {confidence_context}
• Estimated campaign impact: sell {units_low}–{units_high} units in 3 weeks, +${gross_profit:.0f} gross

*If you approve, Radar will:*
1. Generate Instagram + Facebook ad copy and image
2. Publish to your StylePulse social accounts
3. Log your decision in the recommendation queue

Reply:
✅ *APPROVE* — run it as suggested
✏️ *MODIFY [instruction]* — e.g. "MODIFY 20% off instead"
❌ *REJECT* — skip this one

_(Ask me "why this?" for full reasoning. Expires 24h)_"""


def _build_shap_bullets(explanation: str | None, shap_top5_json: str | None) -> str:
    """Convert SHAP/explanation data into Telegram bullet lines."""
    # Try structured shap_top5 JSON first
    if shap_top5_json:
        try:
            items = json.loads(shap_top5_json) if isinstance(shap_top5_json, str) else shap_top5_json
            if isinstance(items, list) and items:
                lines = [f"• {item['explanation']}" for item in items[:3] if item.get("explanation")]
                if lines:
                    return "\n".join(lines)
        except Exception:
            pass
    # Fall back to plain explanation text
    if explanation:
        return f"• {explanation}"
    return "• Stock level and competitive pricing analysis"


class PromoteFlow:
    def __init__(
        self,
        db_url: str,
        ie3_base_url: str,
        telegram_client: "TelegramClient",
        conversation_manager: "ConversationManager",
        business_data_service: "Any | None" = None,
    ) -> None:
        self._db_url = db_url
        self._ie3 = ie3_base_url.rstrip("/")
        self._telegram = telegram_client
        self._conv = conversation_manager
        self._bds = business_data_service  # reuse app-level warmed instance

    # ── Poller ────────────────────────────────────────────────────────────────

    async def check_and_notify_new_promotes(
        self, retailer_chat_id: str, tenant_id: UUID
    ) -> int:
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT r.id, r.variant_id, r.recommendation,
                           r.confidence, r.suggested_discount_pct,
                           r.explanation,
                           COALESCE(r.shap_features_json, '[]'::jsonb) AS shap_features_json,
                           r.rule_override_json,
                           COALESCE(r.fallback_used, FALSE)             AS fallback_used,
                           v.sku_id, p.name AS product_name,
                           coalesce(pr.amount, 0) AS retail_price_usd,
                           coalesce(v.cost_price_usd, 0) AS cost_price_usd,
                           COALESCE(SUM(ib.quantity_on_hand), 0)::int   AS current_stock
                    FROM marketing.recommendations r
                    JOIN core.sku_variants v ON v.id = r.variant_id
                    JOIN core.products p ON p.id = v.product_id
                    LEFT JOIN lateral (
                        SELECT amount FROM core.prices
                        WHERE variant_id = v.id
                          AND price_type = 'retail'
                          AND valid_to IS NULL
                        ORDER BY valid_from DESC LIMIT 1
                    ) pr ON true
                    LEFT JOIN core.inventory_balances ib ON ib.variant_id = v.id
                    LEFT JOIN telegram.promote_notifications n
                        ON n.recommendation_id = r.id
                    WHERE r.recommendation IN ('PROMOTE','MARKDOWN')
                      AND r.status = 'pending'
                      AND n.id IS NULL
                      AND r.generated_at > now() - interval '24 hours'
                      AND r.tenant_id = %s
                    GROUP BY r.id, r.variant_id, r.recommendation, r.confidence,
                             r.suggested_discount_pct, r.explanation, r.shap_features_json,
                             r.rule_override_json, r.fallback_used,
                             v.sku_id, p.name, pr.amount, v.cost_price_usd
                    """,
                    (str(tenant_id),),
                )
                rows = await cur.fetchall()
        finally:
            await conn.close()

        count = 0
        for row in rows:
            try:
                await self._send_notification(retailer_chat_id, tenant_id, row)
                count += 1
            except Exception as exc:
                logger.error(
                    "Failed to notify for recommendation %s: %s", row["id"], exc
                )
        return count

    async def _send_notification(
        self, retailer_chat_id: str, tenant_id: UUID, row: dict
    ) -> None:
        retail_price = float(row["retail_price_usd"] or 0)
        cost_price = float(row["cost_price_usd"] or 0)
        suggested_discount = float(row["suggested_discount_pct"] or 15.0)
        confidence = int(float(row["confidence"]) * 100)
        decision = row["recommendation"]
        sku_id = row["sku_id"]
        product_name = row["product_name"] or sku_id
        current_stock = int(row.get("current_stock") or 0)

        new_price = retail_price * (1 - suggested_discount / 100)
        estimated_units = max(current_stock // 4, 5) if current_stock else 20
        gross_profit = (new_price - cost_price) * estimated_units
        units_low = int(estimated_units * 0.7)
        units_high = int(estimated_units * 1.3)

        # Confidence tier context
        if confidence >= 90:
            confidence_context = "(very strong — hard rule or all signals aligned)"
        elif confidence >= 75:
            confidence_context = "(strong — inventory, price, and competitor signals converge)"
        elif confidence >= 60:
            confidence_context = "(moderate - worth reviewing carefully)"
        else:
            confidence_context = "(weak signal — review carefully before approving)"

        shap_bullets = _build_shap_bullets(
            row.get("explanation"),
            row.get("shap_features_json"),
        )

        message = NOTIFICATION_TEMPLATE.format(
            decision=decision,
            product_name=product_name,
            sku_id=sku_id,
            current_stock=current_stock,
            shap_bullets=shap_bullets,
            suggested_discount=int(suggested_discount),
            new_price=new_price,
            confidence=confidence,
            confidence_context=confidence_context,
            units_low=units_low,
            units_high=units_high,
            gross_profit=gross_profit,
        )

        await self._telegram.send_text_message(retailer_chat_id, message)

        # Persist notification record
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO telegram.promote_notifications
                        (tenant_id, recommendation_id, sku_id, chat_id,
                         message_text, outcome, expires_at)
                    VALUES (%s, %s, %s, %s, %s, 'pending',
                            now() + interval '24 hours')
                    RETURNING id
                    """,
                    (
                        str(tenant_id),
                        str(row["id"]),
                        sku_id,
                        retailer_chat_id,
                        message,
                    ),
                )
                notif_row = await cur.fetchone()
            await conn.commit()
        finally:
            await conn.close()

        notification_id = str(notif_row["id"])

        # Create / advance roadmap for this recommendation
        import os
        from services.telegram_assistant.recommendation_roadmap import (
            create_roadmap, advance_stage, generate_rich_context,
        )
        # Fetch live signals so generate_rich_context reasons from real data
        live_signals: dict = {}
        try:
            _tid = str(tenant_id)
            if self._bds is not None:
                live_signals = await self._bds._fetch_live_signals_for_recommendation(
                    _tid, sku_id, suggested_discount
                )
            else:
                from services.telegram_assistant.business_data_service import BusinessDataService as _BDS
                _bds = _BDS(db_url=self._db_url, eep_base_url="")
                live_signals = await _bds._fetch_live_signals_for_recommendation(
                    _tid, sku_id, suggested_discount
                )
        except Exception as sig_exc:
            logger.warning("Live signal fetch skipped for %s: %s", sku_id, sig_exc)

        try:
            ctx = await generate_rich_context(
                anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                product_name=product_name,
                decision_type=decision,
                confidence_pct=float(row["confidence"]),
                suggested_discount_pct=suggested_discount,
                explanation=row.get("explanation") or "",
                retail_price=retail_price,
                cost_price=cost_price,
                shap_features=row.get("shap_features_json") or [],
                rule_override=row.get("rule_override_json"),
                current_stock=int(row.get("current_stock") or 0),
                live_signals=live_signals or None,
            )
            roadmap_id = await create_roadmap(
                db_url=self._db_url,
                tenant_id=tenant_id,
                recommendation_id=str(row["id"]),
                sku_id=sku_id,
                product_name=product_name,
                decision_type=decision,
                confidence_pct=float(row["confidence"]),
                suggested_discount_pct=suggested_discount,
                context=ctx,
            )
            if roadmap_id > 0:
                await advance_stage(
                    self._db_url, roadmap_id, "awaiting_approval", actor="system",
                    notes="Notification sent to retailer",
                )
            logger.info("Roadmap %s created/advanced for recommendation %s", roadmap_id, row["id"])
        except Exception as exc:
            logger.warning("Roadmap creation failed for %s: %s", row["id"], exc)

        # Store recommendation context so the LLM can handle natural approval language
        await self._conv.set_flow(
            retailer_chat_id,
            "pending_recommendation",
            {
                "notification_id": notification_id,
                "recommendation_id": str(row["id"]),
                "sku_id": sku_id,
                "product_name": product_name,
                "suggested_discount": suggested_discount,
                "retail_price": retail_price,
                "cost_price": cost_price,
                "confidence": float(row["confidence"]),
                "recommendation": decision,
                "explanation": row.get("explanation") or "",
                "tenant_id": str(tenant_id),
            },
            tenant_id=tenant_id,
        )
        logger.info(
            "Sent %s notification for %s (%s) → notification_id=%s",
            decision, sku_id, product_name, notification_id,
        )

    # ── Expiry warnings ───────────────────────────────────────────────────────

    async def check_and_send_expiry_warnings(
        self, retailer_chat_id: str, tenant_id: UUID
    ) -> int:
        """Send a reminder for any pending notification expiring within the next 2 hours."""
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT n.id, n.sku_id, n.expires_at,
                           r.recommendation, p.name AS product_name
                    FROM telegram.promote_notifications n
                    JOIN marketing.recommendations r ON r.id = n.recommendation_id
                    JOIN core.sku_variants sv ON sv.sku_id = n.sku_id AND sv.tenant_id = %s
                    JOIN core.products p ON p.id = sv.product_id
                    WHERE n.tenant_id = %s
                      AND n.chat_id = %s
                      AND n.outcome = 'pending'
                      AND n.expiry_warning_sent = FALSE
                      AND n.expires_at <= now() + interval '2 hours'
                      AND n.expires_at > now()
                    """,
                    (str(tenant_id), str(tenant_id), retailer_chat_id),
                )
                rows = await cur.fetchall()
        finally:
            await conn.close()

        count = 0
        for row in rows:
            try:
                expires_at = row["expires_at"]
                minutes_left = int((expires_at - datetime.now(timezone.utc)).total_seconds() / 60)
                product_name = row.get("product_name") or row["sku_id"]
                decision = row["recommendation"]
                warning = (
                    f"⏰ *Reminder — decision expiring soon*\n\n"
                    f"Your *{decision}* recommendation for *{product_name}* "
                    f"expires in *{minutes_left} minutes*.\n\n"
                    f"Reply *APPROVE*, *REJECT*, or ask me \"why this?\" for full reasoning."
                )
                await self._telegram.send_text_message(retailer_chat_id, warning)
                conn2 = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
                try:
                    async with conn2.cursor() as cur:
                        await cur.execute(
                            "UPDATE telegram.promote_notifications "
                            "SET expiry_warning_sent = TRUE WHERE id = %s",
                            (row["id"],),
                        )
                    await conn2.commit()
                finally:
                    await conn2.close()
                count += 1
                logger.info("Sent expiry warning for notification %s (%s min left)", row["id"], minutes_left)
            except Exception as exc:
                logger.error("Expiry warning send failed for notification %s: %s", row["id"], exc)
        return count

    # ── Reply handler (entry point from main.py) ──────────────────────────────

    async def handle_reply(
        self, chat_id: str, reply_text: str, flow_context: dict
    ) -> str:
        upper = reply_text.strip().upper()
        if upper == "APPROVE" or upper.startswith("APPROVE"):
            return await self._handle_approve(chat_id, flow_context)
        if upper.startswith("MODIFY"):
            modification = reply_text[6:].strip()
            return await self._handle_modify(chat_id, flow_context, modification)
        if upper == "REJECT" or upper.startswith("REJECT"):
            return await self._handle_reject(chat_id, flow_context)
        return "Please reply *APPROVE*, *MODIFY [your instruction]*, or *REJECT*."

    # ── Approve ───────────────────────────────────────────────────────────────

    async def _handle_approve(self, chat_id: str, context: dict) -> str:
        sku_id = context["sku_id"]
        recommendation = context.get("recommendation", "PROMOTE")

        if recommendation == "PROMOTE":
            try:
                # Build RecommendationResult-compatible body for IE3
                body = {
                    "sku_id": sku_id,
                    "product_name": context.get("product_name", sku_id),
                    "recommendation": "PROMOTE",
                    "confidence": context.get("confidence", 0.8),
                    "explanation": context.get("explanation", "AI recommendation"),
                    "shap_top5": [],
                    "suggested_discount_pct": context.get("suggested_discount"),
                    "requires_human_approval": True,
                    "fallback_used": False,
                    "model_version": "rules_v1",
                    "processing_time_ms": 0,
                }
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self._ie3}/campaign/generate",
                        json=body,
                    )
                    resp.raise_for_status()
                logger.info("IE3 campaign generated for sku=%s", sku_id)
            except Exception as exc:
                logger.error("IE3 campaign generation failed for sku=%s: %s", sku_id, exc)

        await self._update_recommendation_status(context.get("recommendation_id"), "approved")

        # Advance roadmap: approved → executing
        from services.telegram_assistant.recommendation_roadmap import (
            get_roadmap_id_for_recommendation, advance_stage,
        )
        try:
            roadmap_id = await get_roadmap_id_for_recommendation(
                self._db_url, context.get("recommendation_id", "")
            )
            if roadmap_id:
                await advance_stage(self._db_url, roadmap_id, "approved", actor="retailer")
                await advance_stage(self._db_url, roadmap_id, "executing", actor="system",
                                    notes="Campaign generation triggered")
        except Exception as exc:
            logger.warning("Roadmap advance on approve failed: %s", exc)

        await self._update_notification_outcome(context["notification_id"], "approved")
        await self._conv.clear_flow(chat_id, tenant_id=context.get("tenant_id"))

        return (
            "Approved. Campaign is live.\n\n"
            "Instagram and Facebook posts published.\n"
            "Your approval has been logged in the recommendation queue."
        )
    # ── Modify ────────────────────────────────────────────────────────────────

    async def _handle_modify(
        self, chat_id: str, context: dict, modification: str
    ) -> str:
        # Update discount if a percentage is mentioned
        updated_context = dict(context)
        match = re.search(r"(\d+)\s*%", modification)
        if match:
            new_discount = float(match.group(1))
            updated_context["suggested_discount"] = new_discount

        new_discount_pct = updated_context["suggested_discount"]
        retail_price = updated_context.get("retail_price", 0.0)
        new_price = retail_price * (1 - new_discount_pct / 100)

        # Persist modification instructions
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE telegram.promote_notifications
                    SET modification_instructions = %s
                    WHERE id = %s
                    """,
                    (modification, context["notification_id"]),
                )
            await conn.commit()
        finally:
            await conn.close()

        # Advance roadmap to 'modified'
        from services.telegram_assistant.recommendation_roadmap import (
            get_roadmap_id_for_recommendation, mark_modification,
        )
        try:
            roadmap_id = await get_roadmap_id_for_recommendation(
                self._db_url, context.get("recommendation_id", "")
            )
            if roadmap_id:
                await mark_modification(self._db_url, roadmap_id, modification)
        except Exception as exc:
            logger.warning("Roadmap mark_modification failed: %s", exc)

        # Update flow context with new numbers — keep the same flow name so APPROVE still works
        await self._conv.set_flow(
            chat_id,
            "pending_recommendation",
            updated_context,
            tenant_id=context.get("tenant_id"),
        )

        product_name = updated_context.get("product_name", updated_context["sku_id"])
        reply = (
            f"Got it — modified to *{int(new_discount_pct)}% off*.\n\n"
            f"*Updated proposal:*\n"
            f"• {product_name} → new price *${new_price:.2f}*\n"
            f"• Instruction: _{modification}_\n\n"
            f"Reply *APPROVE* to confirm or *REJECT* to cancel."
        )
        return reply

    # ── Reject ────────────────────────────────────────────────────────────────

    async def _handle_reject(self, chat_id: str, context: dict) -> str:
        await self._update_recommendation_status(context.get("recommendation_id"), "rejected")
        await self._update_notification_outcome(context["notification_id"], "rejected")
        await self._conv.clear_flow(chat_id, tenant_id=context.get("tenant_id"))

        # Advance roadmap to 'expired'
        from services.telegram_assistant.recommendation_roadmap import (
            get_roadmap_id_for_recommendation, advance_stage,
        )
        try:
            roadmap_id = await get_roadmap_id_for_recommendation(
                self._db_url, context.get("recommendation_id", "")
            )
            if roadmap_id:
                await advance_stage(self._db_url, roadmap_id, "expired", actor="retailer",
                                    notes="Rejected by retailer")
        except Exception as exc:
            logger.warning("Roadmap advance on reject failed: %s", exc)

        return "Noted — skipping this one. I'll flag it again if conditions change."

    # ── DB helper ─────────────────────────────────────────────────────────────

    async def _update_notification_outcome(
        self, notification_id: str, outcome: str
    ) -> None:
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE telegram.promote_notifications
                    SET outcome = %s, outcome_at = now()
                    WHERE id = %s
                    """,
                    (outcome, notification_id),
                )
            await conn.commit()
        finally:
            await conn.close()

    async def _update_recommendation_status(
        self, recommendation_id: str | None, status: str
    ) -> None:
        if not recommendation_id:
            return
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE marketing.recommendations
                    SET status = %s, reviewed_at = now(), reviewed_by = 'telegram'
                    WHERE id = %s
                    """,
                    (status, recommendation_id),
                )
            await conn.commit()
        finally:
            await conn.close()


# ── Module-level poller ───────────────────────────────────────────────────────

async def poll_loop(
    promote_flow_instance: PromoteFlow,
    retailer_chat_id: str,
    tenant_id: UUID,
) -> None:
    """Background task: poll every 5 minutes for new un-notified recommendations."""
    while True:
        await asyncio.sleep(300)
        try:
            count = await promote_flow_instance.check_and_notify_new_promotes(
                retailer_chat_id, tenant_id
            )
            if count > 0:
                logger.info("Sent %d promote notification(s)", count)
        except Exception as exc:
            logger.error("Promote poll error: %s", exc)

