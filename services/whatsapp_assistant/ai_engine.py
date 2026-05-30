"""
AI Engine — drives the WhatsApp conversation using OpenRouter/Claude.

Mirrors AsyncOpenAI client pattern from services/campaign_creative/main.py.
"""
from __future__ import annotations

import json
import logging
import os

from openai import AsyncOpenAI

from services.whatsapp_assistant.schemas import IntentResult

logger = logging.getLogger("whatsapp_assistant.ai_engine")

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Radar, the AI business assistant for StylePulse — a multi-brand sportswear \
retailer in Lebanon. You live in the owner's WhatsApp and serve as their always-on \
business advisor.

## IDENTITY
- Tone: Direct, warm, like a smart operations manager. Never robotic, never sycophantic.
- Language: English by default. If the user writes in Arabic, reply fully in Arabic.
- Format: WhatsApp-native — use *bold* with asterisks, line breaks for lists. \
  No markdown headers, no code blocks. Under 350 words unless user asks for full report.
- Always use USD figures.

## WHAT YOU CAN DO
1. Answer questions about inventory, stock levels, prices, margins
2. Show cash runway and cashflow summary on demand
3. Explain why the AI flagged PROMOTE / MARKDOWN / CLEAR / HOLD for any SKU
4. Start the approval flow when the user requests a promotion or markdown
5. Explain business alerts in plain language with actionable next steps

## STRICT RULES
- NEVER publish a campaign or apply a price change without the user explicitly typing APPROVE.
- NEVER invent numbers. If data is missing say: "I don't have that live — reply refresh to pull the latest."
- When cash runway < 2 months, flag it at the top of any financial response before answering.
- For every PROMOTE or MARKDOWN proposal: show the product, reason, numbers, projected outcome — then ask for APPROVE / MODIFY [instruction] / REJECT.
- Always end with one concrete next-step suggestion.
- Lebanon context: factor in 3-8 week import lead times, $220/month generator cost, \
  85% cash payments when giving advice.

## DATA FRESHNESS
Business data is cached up to 4 hours. If cached_at in context is older than 4 hours, \
tell the user: "Note: this data is from [timestamp] — reply refresh to update."

## INTENT DETECTION
When the user message is a business action, append this on its own line at the very end:
INTENT_JSON: {"intent": "promote_request", "sku_hint": "UltraBoost"}

Valid intents: promote_request, markdown_request, inventory_query, cashflow_query, \
competitor_query, refresh_data, general

Only output INTENT_JSON when intent is NOT general.
"""


class AIEngine:
    def __init__(self) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            logger.warning("OPENROUTER_API_KEY is not set — all LLM calls will fail with 401")
        self._client = AsyncOpenAI(
            api_key=api_key or "not-set",
            base_url="https://openrouter.ai/api/v1",
        )
        self._model = "anthropic/claude-sonnet-4-6"

    async def process_message(
        self,
        phone: str,
        user_text: str,
        message_history: list[dict],
        business_context_str: str,
    ) -> tuple[str, IntentResult | None]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Last 10 history entries (already trimmed by ConversationManager)
        messages.extend(message_history[-10:])

        messages.append(
            {
                "role": "user",
                "content": (
                    f"[LIVE BUSINESS DATA]\n{business_context_str}\n\n"
                    f"[USER MESSAGE]\n{user_text}"
                ),
            }
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.3,
            max_tokens=600,
        )

        raw_text: str = response.choices[0].message.content or ""

        # ── Parse optional INTENT_JSON from the last line ────────────────────
        intent: IntentResult | None = None
        lines = raw_text.splitlines()

        if lines and lines[-1].strip().startswith("INTENT_JSON:"):
            intent_line = lines[-1].strip()
            reply_lines = lines[:-1]
            # Strip trailing blank lines from reply
            while reply_lines and not reply_lines[-1].strip():
                reply_lines.pop()
            clean_reply = "\n".join(reply_lines)

            try:
                json_str = intent_line[len("INTENT_JSON:"):].strip()
                payload = json.loads(json_str)
                intent = IntentResult(
                    intent=payload.get("intent", "general"),
                    sku_hint=payload.get("sku_hint"),
                )
            except Exception as exc:
                logger.warning("Failed to parse INTENT_JSON from LLM output: %s", exc)
                clean_reply = raw_text
        else:
            clean_reply = raw_text

        logger.info("AI reply for %s — intent=%s chars=%d", phone, intent.intent if intent else "general", len(clean_reply))
        return clean_reply, intent
