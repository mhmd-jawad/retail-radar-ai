"""
AI Engine — LLM-orchestrated WhatsApp conversation with Anthropic tool calling.

Architecture: Claude is the brain. It calls tools to fetch live business data,
decides what's relevant, and composes a natural WhatsApp-native reply.
The system prompt is cached via Anthropic prompt caching for cost efficiency.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import UUID

import anthropic
import httpx
import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger("whatsapp_assistant.ai_engine")

MAX_TOOL_ITERATIONS = 3

SYSTEM_PROMPT = """\
You are Radar, the AI business advisor for StylePulse — a multi-brand sportswear retailer in Lebanon. You live inside the owner's WhatsApp.

## IDENTITY
- Tone: Direct, warm, like a sharp operations manager who knows the numbers cold. Not robotic, not sycophantic.
- Language: English by default. If the retailer writes in Arabic or mixes Arabic and English, reply fully in the same language they used.
- Format: WhatsApp-native only. Use *bold* with asterisks. Use line breaks for lists. No markdown headers (#). No code blocks. Keep replies under 350 words unless explicitly asked for a full report.
- Always quote USD figures.

## WHAT YOU CAN DO
You have tools to fetch live data from the retailer's inventory system AND to manage a full recommendation roadmap. Use them when the retailer asks about inventory, revenue, competitors, recommendations, or decision status. Call multiple tools in sequence when a question requires combining data.

## AGENTIC ROADMAP ROLE
You manage a recommendation pipeline. Every recommendation goes through stages:
  🔍 Discovery → 💡 Ready → ⏳ Awaiting Approval → ✅ Approved → ⚙️ Executing → 📊 Monitoring → 📋 Reviewing → 🏁 Completed

Use get_roadmap_summary to give management a full pipeline view.
Use get_recommendation_detail when asked about a specific recommendation's reasoning, data, risks, or history.
Use get_next_actions when asked what to focus on, what is pending, or what management should do today.

When presenting roadmap data, structure your reply clearly:
- Lead with the priority action (what needs attention NOW)
- Group items by stage — approval pending first, then in-flight, then completed
- For each item: product name, stage, key metric (discount %, confidence, lift achieved)
- End with the recommended next step

## RECOMMENDATION EXPLANATIONS
When asked "why are you recommending this?" or "what data supports this?", call get_recommendation_detail and explain:
1. The data signals that triggered it (what the numbers showed)
2. The reasoning (why action is needed now, not later)
3. Expected impact (what will likely happen if approved)
4. Main risk (what could go wrong)
5. Alternative (what else could be done)
6. Next best step (what to do right now)

## APPROVAL FLOWS
When the retailer says anything like "sounds good", "do it", "let's try it", "yes", "go ahead", "approve", "yalla", "ok run it" in the context of a pending recommendation — call the approve_recommendation tool.
When they say "no", "skip", "not now", "pass", "reject" in the context of a recommendation — call reject_recommendation.
You do NOT need them to type the word APPROVE. Understand natural intent.
When modifying: "let's try 20% instead" → call approve_recommendation with modified_discount_pct=20.0.
Before calling approve_recommendation, always confirm the product name and discount percentage with the retailer first if there is any ambiguity.

## LEARNING FROM OUTCOMES
When presenting completed roadmap items, highlight what was learned:
- "This promotion lifted velocity by X% — above/below the X% prediction."
- "Revenue delta was $X — the model was X% accurate."
- Use this to inform the next recommendation ("Based on what worked last time...").

## STRICT RULES
- NEVER invent numbers. If a tool returns no data or an error, say so clearly.
- When cash runway < 2 months, flag it at the very top of any financial response.
- Lebanon context: 3-8 week import lead times, $220/month generator cost, ~85% cash payments.
- Always end with one concrete next-step suggestion unless the message is casual chitchat.
- Data is cached up to 4 hours. If the retailer asks for the latest data, mention they can say "refresh" to force a cache bust.

## CHITCHAT
For greetings, thank-yous, or casual messages, reply naturally without calling any tool. Keep it short and warm. If it's morning, suggest checking the daily brief or asking "what should we focus on today?" Match the retailer's energy.

## PROACTIVE INSIGHTS
When a tool result includes a "proactive_insight" field, surface it naturally at the end of your reply, introduced with something like "One thing to watch:" or "Worth noting:".
"""


class AIEngine:
    def __init__(
        self,
        business_data_service: Any,
        db_url: str,
        ie3_base_url: str,
    ) -> None:
        from services.whatsapp_assistant.agent_tools import TOOLS
        self._bds = business_data_service
        self._db_url = db_url
        self._ie3 = ie3_base_url.rstrip("/")
        self._tools = TOOLS
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = anthropic.AsyncAnthropic(api_key=api_key or "not-set")

    @property
    def is_configured(self) -> bool:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        return bool(key) and "xxxx" not in key.lower() and key != "not-set"

    async def chat(
        self,
        phone: str,
        user_text: str,
        message_history: list[dict],
        conversation_summary: str | None,
        tenant_id: UUID,
    ) -> tuple[str, list[str]]:
        messages = _build_messages(user_text, message_history, conversation_summary)
        tools_used: list[str] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            response = await self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=self._tools,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                return _extract_text(response.content), tools_used

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tools_used.append(block.name)
                        result = await self._execute_tool(
                            block.name, dict(block.input), tenant_id, phone
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })
                # Append assistant turn with tool calls, then user turn with results
                messages.append({"role": "assistant", "content": list(response.content)})
                messages.append({"role": "user", "content": tool_results})

        return "I hit an unexpected error — please try again.", tools_used

    async def _execute_tool(
        self,
        name: str,
        inp: dict,
        tenant_id: UUID,
        phone: str,
    ) -> Any:
        tid = str(tenant_id)
        try:
            if name == "get_inventory_overview":
                return await self._bds.get_inventory_overview(tid)

            if name == "get_stockout_days":
                return await self._bds._fetch_stockout_days(tid)

            if name == "get_reorder_suggestions":
                return await self._bds._fetch_reorder_suggestions(tid)

            if name == "get_sku_velocity_trend":
                return await self._bds._fetch_sku_velocity_trend(
                    tid, inp["sku_id"], inp.get("days", 30)
                )

            if name == "get_category_performance":
                return await self._bds._fetch_category_performance(
                    tid, inp.get("days", 30)
                )

            if name == "get_financials":
                return await self._bds.get_financials_snapshot(tid)

            if name == "get_revenue_trend":
                return await self._bds._fetch_revenue_trend(tid)

            if name == "get_competitor_prices":
                return await self._bds.get_competitor_prices(
                    tid,
                    sku_id=inp.get("sku_id"),
                    competitor_name=inp.get("competitor_name"),
                )

            if name == "get_pending_recommendations":
                recs = await self._bds._fetch_pending_recommendations_from_db(tid)
                return [
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
                        "explanation": r.get("explanation") or "",
                    }
                    for r in recs
                ]

            if name == "approve_recommendation":
                return await self._action_approve(
                    inp["recommendation_id"],
                    inp["sku_id"],
                    inp.get("modified_discount_pct"),
                    tenant_id,
                    phone,
                )

            if name == "reject_recommendation":
                return await self._action_reject(
                    inp["recommendation_id"],
                    inp["sku_id"],
                    tenant_id,
                    phone,
                )

            if name == "get_decision_progress":
                from services.whatsapp_assistant.outcome_tracker import get_closed_loop_summary
                return await get_closed_loop_summary(self._db_url, tenant_id)

            if name == "get_roadmap_summary":
                from services.whatsapp_assistant.roadmap import get_roadmap_summary
                return await get_roadmap_summary(self._db_url, tenant_id)

            if name == "get_recommendation_detail":
                from services.whatsapp_assistant.roadmap import get_recommendation_detail
                return await get_recommendation_detail(self._db_url, int(inp["roadmap_id"]))

            if name == "get_next_actions":
                from services.whatsapp_assistant.roadmap import get_next_actions
                return await get_next_actions(self._db_url, tenant_id)

            return {"error": f"Unknown tool: {name}"}

        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc, exc_info=True)
            return {"error": str(exc)}

    async def _action_approve(
        self,
        recommendation_id: str,
        sku_id: str,
        modified_discount_pct: float | None,
        tenant_id: UUID,
        phone: str,
    ) -> dict[str, Any]:
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        rec = None
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT r.id, r.recommendation, r.confidence, r.suggested_discount_pct,
                           r.explanation, sv.sku_id, p.name AS product_name,
                           sv.cost_price_usd,
                           COALESCE(pr.amount, 0) AS retail_price_usd
                    FROM marketing.recommendations r
                    JOIN core.sku_variants sv ON sv.id = r.variant_id
                    JOIN core.products p ON p.id = sv.product_id
                    LEFT JOIN LATERAL (
                        SELECT amount FROM core.prices
                        WHERE variant_id = sv.id
                          AND price_type = 'retail'
                          AND valid_to IS NULL
                        LIMIT 1
                    ) pr ON true
                    WHERE r.id = %s AND r.tenant_id = %s
                    """,
                    (recommendation_id, str(tenant_id)),
                )
                rec = await cur.fetchone()

            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE marketing.recommendations
                    SET status = 'approved', reviewed_at = now(), reviewed_by = 'whatsapp'
                    WHERE id = %s
                    """,
                    (recommendation_id,),
                )
            await conn.commit()
        finally:
            await conn.close()

        if not rec:
            return {"status": "error", "message": f"Recommendation {recommendation_id} not found."}

        rec_type = rec["recommendation"]
        product_name = rec.get("product_name") or sku_id
        confidence = float(rec.get("confidence") or 0.8)
        discount_pct = (
            modified_discount_pct
            if modified_discount_pct is not None
            else float(rec.get("suggested_discount_pct") or 15)
        )
        explanation = rec.get("explanation") or "AI recommendation"

        campaign_status = "not_applicable"
        if rec_type == "PROMOTE":
            try:
                body = {
                    "sku_id": sku_id,
                    "product_name": product_name,
                    "recommendation": "PROMOTE",
                    "confidence": confidence,
                    "explanation": explanation,
                    "shap_top5": [],
                    "suggested_discount_pct": discount_pct,
                    "requires_human_approval": True,
                    "fallback_used": False,
                    "model_version": "rules_v1",
                    "processing_time_ms": 0,
                }
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(f"{self._ie3}/campaign/generate", json=body)
                    resp.raise_for_status()
                campaign_status = "generated"
                logger.info("IE3 campaign generated for sku=%s", sku_id)
            except Exception as exc:
                campaign_status = f"failed: {exc}"
                logger.error("IE3 campaign failed for sku=%s: %s", sku_id, exc)

        from services.whatsapp_assistant.outcome_tracker import record_decision_snapshot
        snapshot_id = await record_decision_snapshot(
            sku_id=sku_id,
            decision_type=rec_type,
            recommendation_id=recommendation_id,
            cost_price_usd=float(rec.get("cost_price_usd") or 0),
        )

        # Try to update notification outcome if a notification exists for this recommendation
        await _update_notification_outcome_if_exists(self._db_url, recommendation_id, "approved")

        # Advance roadmap: approved → executing
        from services.whatsapp_assistant.roadmap import (
            get_roadmap_id_for_recommendation, advance_stage,
        )
        try:
            roadmap_id = await get_roadmap_id_for_recommendation(self._db_url, recommendation_id)
            if roadmap_id:
                await advance_stage(self._db_url, roadmap_id, "approved", actor="retailer")
                await advance_stage(self._db_url, roadmap_id, "executing", actor="system",
                                    notes="Campaign generation triggered via chat")
                if snapshot_id:
                    await advance_stage(self._db_url, roadmap_id, "monitoring", actor="system",
                                        notes=f"Outcome tracking started — snapshot #{snapshot_id}",
                                        extra_updates={"outcome_snapshot_id": snapshot_id})
        except Exception as exc:
            logger.warning("Roadmap advance on approve (agent) failed: %s", exc)

        from services.whatsapp_assistant.session_manager import ConversationManager
        await ConversationManager(self._db_url).clear_flow(phone)

        return {
            "status": "approved",
            "sku_id": sku_id,
            "product_name": product_name,
            "recommendation_type": rec_type,
            "discount_pct": discount_pct,
            "campaign_status": campaign_status,
            "snapshot_id": snapshot_id,
        }

    async def _action_reject(
        self,
        recommendation_id: str,
        sku_id: str,
        tenant_id: UUID,
        phone: str,
    ) -> dict[str, Any]:
        conn = await psycopg.AsyncConnection.connect(self._db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE marketing.recommendations
                    SET status = 'rejected', reviewed_at = now(), reviewed_by = 'whatsapp'
                    WHERE id = %s AND tenant_id = %s
                    """,
                    (recommendation_id, str(tenant_id)),
                )
            await conn.commit()
        finally:
            await conn.close()

        await _update_notification_outcome_if_exists(self._db_url, recommendation_id, "rejected")

        # Advance roadmap to 'expired'
        from services.whatsapp_assistant.roadmap import (
            get_roadmap_id_for_recommendation, advance_stage,
        )
        try:
            roadmap_id = await get_roadmap_id_for_recommendation(self._db_url, recommendation_id)
            if roadmap_id:
                await advance_stage(self._db_url, roadmap_id, "expired", actor="retailer",
                                    notes="Rejected via chat")
        except Exception as exc:
            logger.warning("Roadmap advance on reject (agent) failed: %s", exc)


        from services.whatsapp_assistant.session_manager import ConversationManager
        await ConversationManager(self._db_url).clear_flow(phone)

        return {"status": "rejected", "sku_id": sku_id}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _update_notification_outcome_if_exists(
    db_url: str, recommendation_id: str, outcome: str
) -> None:
    """Update notification outcome if a promote_notification row exists for this recommendation."""
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE whatsapp.promote_notifications
                SET outcome = %s, outcome_at = now()
                WHERE recommendation_id = %s
                  AND outcome = 'pending'
                """,
                (outcome, recommendation_id),
            )
        await conn.commit()
    except Exception as exc:
        logger.debug("Could not update notification outcome: %s", exc)
    finally:
        await conn.close()


def _build_messages(
    user_text: str,
    history: list[dict],
    conversation_summary: str | None,
) -> list[dict]:
    messages: list[dict] = []

    if conversation_summary:
        messages.append({
            "role": "user",
            "content": f"[Earlier conversation summary]\n{conversation_summary}",
        })
        messages.append({
            "role": "assistant",
            "content": "Understood — I have context from our earlier conversation.",
        })

    for entry in history:
        role = entry.get("role", "user")
        content = entry.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_text})
    return messages


def _extract_text(content: list) -> str:
    parts = [block.text for block in content if hasattr(block, "type") and block.type == "text"]
    return "\n".join(parts).strip() or "I couldn't generate a reply — please try again."
