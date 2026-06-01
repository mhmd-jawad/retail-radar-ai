from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class InboundMessage(BaseModel):
    phone_number: str
    text: str
    message_id: str
    timestamp: datetime


class WhatsAppWebhookPayload(BaseModel):
    """Raw Meta webhook JSON shape — entry list is untyped to tolerate schema changes."""
    entry: list[Any]


class AlertmanagerAlert(BaseModel):
    fingerprint: str
    status: str
    labels: dict[str, Any]
    annotations: dict[str, Any]
    starts_at: datetime
    ends_at: datetime | None = None


class AlertmanagerWebhookPayload(BaseModel):
    version: str
    group_key: str
    alerts: list[AlertmanagerAlert]


class ConversationSession(BaseModel):
    phone_number: str
    tenant_id: UUID
    message_history: list[dict[str, Any]] = Field(default_factory=list)
    active_flow: str | None = None
    flow_context: dict[str, Any] | None = None
    cached_business_data: dict[str, Any] | None = None
    cached_at: datetime | None = None
    conversation_summary: str | None = None


class IntentResult(BaseModel):
    intent: Literal[
        "promote_request",
        "markdown_request",
        "inventory_query",
        "cashflow_query",
        "competitor_query",
        "refresh_data",
        "general",
    ]
    sku_hint: str | None = None


class PromoteNotification(BaseModel):
    id: UUID
    recommendation_id: UUID | None = None
    sku_id: str
    phone_number: str
    outcome: str
    expires_at: datetime
