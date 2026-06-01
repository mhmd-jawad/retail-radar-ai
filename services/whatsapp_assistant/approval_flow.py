"""
Promote / Markdown approval flow — Phase 3.

Polls marketing.recommendations for un-notified PROMOTE/MARKDOWN rows,
sends WhatsApp notifications, and handles APPROVE / MODIFY / REJECT replies.

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

from services.whatsapp_assistant.outcome_tracker import record_decision_snapshot

if TYPE_CHECKING:
    from services.whatsapp_assistant.session_manager import ConversationManager
    from services.whatsapp_assistant.messenger import WhatsAppClient

logger = logging.getLogger("whatsapp_assistant.approval_flow")

# ── Notification template ─────────────────────────────────────────────────────

NOTIFICATION_TEMPLATE = """\
🔔 *AI Recommendation — Action Required*

*{decision}: {product_name}*
SKU: {sku_id}

*Why now?*
{shap_bullets}

*What the AI suggests:*
• Discount: *{suggested_discount}% off* → new price *${new_price:.2f}*
• Confidence: {confidence}%
• Est. outcome: sell {units_low}–{units_high} units in 3 weeks, +${gross_profit:.0f} vs. holding

*If you approve, Radar will:*
1. Generate Instagram + Facebook ad copy and image
2. Publish to your StylePulse social accounts
3. Log it in your dashboard

Reply:
✅ *APPROVE* — run it as suggested
✏️ *MODIFY [instruction]* — e.g. "MODIFY 20% off instead"
❌ *REJECT* — skip this one

_(Expires in 24 hours)_"""


def _build_shap_bullets(explanation: str | None, shap_top5_json: str | None) -> str:
    """Convert SHAP/explanation data into WhatsApp bullet lines."""
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
        whatsapp_client: "WhatsAppClient",
        conversation_manager: "ConversationManager",
    ) -> None:
        self._db_url = db_url
        self._ie3 = ie3_base_url.rstrip("/")
        self._wa = whatsapp_client
        self._conv = conversation_manager

    # ── Poller ────────────────────────────────────────────────────────────────

    async def check_and_notify_new_promotes(
        self, retailer_phone: str, tenant_id: UUID
    ) -> int:
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT r.id, r.variant_id, r.recommendation,
                           r.confidence, r.suggested_discount_pct,
                           r.explanation,
                           v.sku_id, p.name AS product_name,
                           coalesce(pr.amount, 0) AS retail_price_usd,
                           coalesce(v.cost_price_usd, 0) AS cost_price_usd
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
                    LEFT JOIN whatsapp.promote_notifications n
                        ON n.recommendation_id = r.id
                    WHERE r.recommendation IN ('PROMOTE','MARKDOWN')
                      AND r.status = 'pending'
                      AND n.id IS NULL
                      AND r.generated_at > now() - interval '24 hours'
                      AND r.tenant_id = %s
                    """,
                    (str(tenant_id),),
                )
                rows = await cur.fetchall()
        finally:
            await conn.close()

        count = 0
        for row in rows:
            try:
                await self._send_notification(retailer_phone, tenant_id, row)
                count += 1
            except Exception as exc:
                logger.error(
                    "Failed to notify for recommendation %s: %s", row["id"], exc
                )
        return count

    async def _send_notification(
        self, retailer_phone: str, tenant_id: UUID, row: dict
    ) -> None:
        retail_price = float(row["retail_price_usd"] or 0)
        cost_price = float(row["cost_price_usd"] or 0)
        suggested_discount = float(row["suggested_discount_pct"] or 15.0)
        confidence = int(float(row["confidence"]) * 100)
        decision = row["recommendation"]
        sku_id = row["sku_id"]
        product_name = row["product_name"] or sku_id

        new_price = retail_price * (1 - suggested_discount / 100)
        estimated_units = 20
        gross_profit = (new_price - cost_price) * estimated_units
        units_low = int(estimated_units * 0.7)
        units_high = int(estimated_units * 1.3)
        shap_bullets = _build_shap_bullets(row.get("explanation"), None)

        message = NOTIFICATION_TEMPLATE.format(
            decision=decision,
            product_name=product_name,
            sku_id=sku_id,
            shap_bullets=shap_bullets,
            suggested_discount=int(suggested_discount),
            new_price=new_price,
            confidence=confidence,
            units_low=units_low,
            units_high=units_high,
            gross_profit=gross_profit,
        )

        await self._wa.send_text_message(retailer_phone, message)

        # Persist notification record
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO whatsapp.promote_notifications
                        (tenant_id, recommendation_id, sku_id, phone_number,
                         message_text, outcome, expires_at)
                    VALUES (%s, %s, %s, %s, %s, 'pending',
                            now() + interval '24 hours')
                    RETURNING id
                    """,
                    (
                        str(tenant_id),
                        str(row["id"]),
                        sku_id,
                        retailer_phone,
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
        from services.whatsapp_assistant.roadmap import (
            create_roadmap, advance_stage, generate_rich_context,
        )
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
            retailer_phone,
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
            },
        )
        logger.info(
            "Sent %s notification for %s (%s) → notification_id=%s",
            decision, sku_id, product_name, notification_id,
        )

    # ── Reply handler (entry point from main.py) ──────────────────────────────

    async def handle_reply(
        self, phone: str, reply_text: str, flow_context: dict
    ) -> str:
        upper = reply_text.strip().upper()
        if upper == "APPROVE" or upper.startswith("APPROVE"):
            return await self._handle_approve(phone, flow_context)
        if upper.startswith("MODIFY"):
            modification = reply_text[6:].strip()
            return await self._handle_modify(phone, flow_context, modification)
        if upper == "REJECT" or upper.startswith("REJECT"):
            return await self._handle_reject(phone, flow_context)
        return "Please reply *APPROVE*, *MODIFY [your instruction]*, or *REJECT*."

    # ── Approve ───────────────────────────────────────────────────────────────

    async def _handle_approve(self, phone: str, context: dict) -> str:
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
        from services.whatsapp_assistant.roadmap import (
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

        snapshot_id = await record_decision_snapshot(
            sku_id=sku_id,
            decision_type=recommendation,
            recommendation_id=context.get("recommendation_id"),
            cost_price_usd=float(context.get("cost_price") or 0),
        )
        await self._update_notification_outcome(context["notification_id"], "approved")
        await self._conv.clear_flow(phone)

        tracking = (
            f"Closed-loop tracking started: snapshot *#{snapshot_id}*.\n"
            if snapshot_id
            else "Closed-loop tracking could not start because baseline data was unavailable.\n"
        )
        return (
            "✅ *Campaign is live!*\n\n"
            "Instagram and Facebook posts published.\n"
            f"{tracking}"
            "I'll notify you at the 7-day and 14-day progress checks."
        )

    # ── Modify ────────────────────────────────────────────────────────────────

    async def _handle_modify(
        self, phone: str, context: dict, modification: str
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
                    UPDATE whatsapp.promote_notifications
                    SET modification_instructions = %s
                    WHERE id = %s
                    """,
                    (modification, context["notification_id"]),
                )
            await conn.commit()
        finally:
            await conn.close()

        # Advance roadmap to 'modified'
        from services.whatsapp_assistant.roadmap import (
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
        await self._conv.set_flow(phone, "pending_recommendation", updated_context)

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

    async def _handle_reject(self, phone: str, context: dict) -> str:
        await self._update_recommendation_status(context.get("recommendation_id"), "rejected")
        await self._update_notification_outcome(context["notification_id"], "rejected")
        await self._conv.clear_flow(phone)

        # Advance roadmap to 'expired'
        from services.whatsapp_assistant.roadmap import (
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
                    UPDATE whatsapp.promote_notifications
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
                    SET status = %s, reviewed_at = now(), reviewed_by = 'whatsapp'
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
    retailer_phone: str,
    tenant_id: UUID,
) -> None:
    """Background task: poll every 5 minutes for new un-notified recommendations."""
    while True:
        await asyncio.sleep(300)
        try:
            count = await promote_flow_instance.check_and_notify_new_promotes(
                retailer_phone, tenant_id
            )
            if count > 0:
                logger.info("Sent %d promote notification(s)", count)
        except Exception as exc:
            logger.error("Promote poll error: %s", exc)

