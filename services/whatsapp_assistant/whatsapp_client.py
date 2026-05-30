"""
WhatsApp Business Cloud API client.
Wraps Meta Graph API v20.0 — async, using httpx (mirroring services/campaign_creative/main.py).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from services.whatsapp_assistant.schemas import InboundMessage

_GRAPH_BASE = "https://graph.facebook.com/v20.0"


class WhatsAppClient:
    def __init__(self) -> None:
        self._token = os.environ["WHATSAPP_TOKEN"]
        self._phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def send_text_message(self, to: str, text: str) -> str:
        """Send a plain-text WhatsApp message. Returns the message_id from Meta."""
        url = f"{_GRAPH_BASE}/{self._phone_number_id}/messages"
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body, headers=self._headers)
            response.raise_for_status()
            data = response.json()
            return data["messages"][0]["id"]

    async def send_template_message(
        self,
        to: str,
        template_name: str = "hello_world",
        language_code: str = "en_US",
        components: list | None = None,
    ) -> str:
        """Send a pre-approved template message (business-initiated, no 24h window needed)."""
        url = f"{_GRAPH_BASE}/{self._phone_number_id}/messages"
        template: dict = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body, headers=self._headers)
            response.raise_for_status()
            data = response.json()
            return data["messages"][0]["id"]

    def parse_incoming_webhook(self, payload: dict) -> InboundMessage | None:
        """
        Parse a raw Meta webhook payload.
        Returns None if the event is a message-status update (no "messages" key).
        """
        try:
            value = payload["entry"][0]["changes"][0]["value"]
        except (KeyError, IndexError):
            return None

        if "messages" not in value:
            return None

        message = value["messages"][0]
        contact = value["contacts"][0]

        phone_number: str = contact["wa_id"]
        text: str = message["text"]["body"]
        message_id: str = message["id"]
        # Meta sends timestamp as a Unix epoch string
        timestamp = datetime.fromtimestamp(int(message["timestamp"]), tz=timezone.utc)

        return InboundMessage(
            phone_number=phone_number,
            text=text,
            message_id=message_id,
            timestamp=timestamp,
        )
