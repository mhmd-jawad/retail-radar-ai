"""
Telegram Bot API client.
Wraps the Telegram Bot HTTP API — async, using httpx.
Provides send_text_message(chat_id, text) and parse_incoming_update(payload) methods.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

from services.telegram_assistant.conversation_models import InboundMessage

_TELEGRAM_API = "https://api.telegram.org"
logger = logging.getLogger("telegram_assistant.telegram_client")


class TelegramClient:
    def __init__(self) -> None:
        self._token = os.environ["TELEGRAM_BOT_TOKEN"]
        self._base = f"{_TELEGRAM_API}/bot{self._token}"

    async def send_text_message(self, chat_id: str, text: str) -> str:
        """Send a plain-text message to a Telegram chat. Returns the message_id."""
        url = f"{self._base}/sendMessage"
        body = {
            "chat_id": int(chat_id),
            "text": text,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body)
            if response.status_code >= 400:
                logger.error(
                    "Telegram send failed: status=%s body=%s",
                    response.status_code, response.text,
                )
            response.raise_for_status()
            data = response.json()
            return str(data["result"]["message_id"])

    def parse_incoming_update(self, payload: dict) -> InboundMessage | None:
        """
        Parse a Telegram Update JSON payload.
        Returns None if the update carries no text message (stickers, photos, etc.).
        Uses "{chat_id}:{message_id}" as a globally unique deduplication key.
        """
        message = payload.get("message") or payload.get("edited_message")
        if not message:
            return None

        text = message.get("text")
        if not text:
            logger.debug("Ignoring non-text Telegram update")
            return None

        chat_id = str(message["chat"]["id"])
        message_id = f"{chat_id}:{message['message_id']}"
        timestamp = datetime.fromtimestamp(message["date"], tz=timezone.utc)

        return InboundMessage(
            chat_id=chat_id,
            text=text,
            message_id=message_id,
            timestamp=timestamp,
        )
