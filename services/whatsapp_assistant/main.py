"""
WhatsApp AI Assistant — AI Conversation Engine (Phase 2).
Port: 8004

Run:
    uvicorn services.whatsapp_assistant.main:app --port 8004 --reload
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import make_asgi_app
from psycopg.rows import dict_row

from services.whatsapp_assistant.ai_engine import AIEngine
from services.whatsapp_assistant.business_data import (
    BusinessDataService,
    format_business_context_for_prompt,
)
from services.whatsapp_assistant.conversation import (
    DEFAULT_DATABASE_URL,
    DEFAULT_TENANT_SLUG,
    ConversationManager,
)
from services.whatsapp_assistant.promote_flow import PromoteFlow, poll_loop
from services.whatsapp_assistant.whatsapp_client import WhatsAppClient

# ── Load .env from this service directory ────────────────────────────────────
_SERVICE_DIR = Path(__file__).parent
load_dotenv(_SERVICE_DIR / ".env")  # override=False: don't overwrite vars already set by Docker/compose

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("whatsapp_assistant")

# ── Module-level singletons (populated in lifespan) ───────────────────────────
_wa_client: WhatsAppClient | None = None
_conv_manager: ConversationManager | None = None
_ai_engine: AIEngine | None = None
_business_data_service: BusinessDataService | None = None
_promote_flow: PromoteFlow | None = None
_default_tenant_id: UUID | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _wa_client, _conv_manager, _ai_engine, _business_data_service, _promote_flow, _default_tenant_id

    _db_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    _wa_client = WhatsAppClient()
    _conv_manager = ConversationManager(_db_url)
    _ai_engine = AIEngine()
    _business_data_service = BusinessDataService(
        eep_base_url=os.environ.get("EEP_BASE_URL", "http://localhost:8000"),
        db_url=_db_url,
        financial_data_path=str(Path(__file__).resolve().parents[2] / "data" / "real"),
    )
    _promote_flow = PromoteFlow(
        db_url=_db_url,
        ie3_base_url=os.environ.get("IE3_BASE_URL", "http://localhost:8003"),
        whatsapp_client=_wa_client,
        conversation_manager=_conv_manager,
    )
    await _business_data_service.warmup()

    # Cache the default tenant_id once at startup
    try:
        db_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM core.tenants WHERE slug = %s LIMIT 1",
                (DEFAULT_TENANT_SLUG,),
            )
            row = await cur.fetchone()
        await conn.close()
        if row:
            _default_tenant_id = row["id"]
            logger.info("Default tenant cached: %s", _default_tenant_id)
        else:
            logger.warning(
                "Tenant '%s' not found — inbound messages will skip session storage",
                DEFAULT_TENANT_SLUG,
            )
    except Exception as exc:
        logger.warning("Could not cache tenant_id at startup (DB unavailable?): %s", exc)

    # Start the promote poller background task
    retailer_phone = os.environ.get("RETAILER_PHONE_NUMBER", "")
    if _promote_flow is not None and retailer_phone and _default_tenant_id is not None:
        asyncio.create_task(
            poll_loop(_promote_flow, retailer_phone, _default_tenant_id),
            name="promote_poller",
        )
        logger.info("Promote poller started for %s", retailer_phone)
    else:
        logger.warning(
            "Promote poller NOT started (missing retailer_phone=%r or tenant_id=%s)",
            retailer_phone, _default_tenant_id,
        )

    yield


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="WhatsApp AI Assistant",
    description="WhatsApp Business Cloud API webhook receiver — Phase 1 echo server.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# Mount Prometheus metrics exporter
app.mount("/metrics", make_asgi_app())


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "whatsapp_assistant", "version": "1.0.0"}


@app.get("/webhook/whatsapp", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
):
    """Meta webhook verification handshake."""
    expected = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")
    if hub_mode == "subscribe" and hub_verify_token == expected:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/webhook/whatsapp")
async def receive_webhook(body: dict[str, Any]):
    """Receive inbound WhatsApp messages and run the AI conversation flow."""
    if _wa_client is None or _ai_engine is None or _business_data_service is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 1. Parse inbound
    inbound = _wa_client.parse_incoming_webhook(body)
    if inbound is None:
        return {"status": "ok"}

    phone = inbound.phone_number
    try:
        # 2. Get or create conversation session
        tenant_id = _default_tenant_id
        if _conv_manager is None or tenant_id is None:
            logger.warning("No conversation manager or tenant — skipping session storage")
            return {"status": "ok"}

        session = await _conv_manager.get_or_create_session(phone, tenant_id)

        # 3. Active promote flow takes priority
        if session.active_flow == "promote" and _promote_flow is not None:
            reply = await _promote_flow.handle_reply(
                phone, inbound.text, session.flow_context or {}
            )
            await _conv_manager.append_message(phone, "user", inbound.text)
            await _conv_manager.append_message(phone, "assistant", reply)
            await _wa_client.send_text_message(phone, reply)
            return {"status": "ok"}
        else:
            # 4a. Check for refresh trigger
            force_refresh = inbound.text.strip().lower() == "refresh"

            # 4b-c. Fetch and format business context
            context_dict = await _business_data_service.get_business_context(
                phone, force_refresh=force_refresh
            )
            context_str = format_business_context_for_prompt(context_dict)

            # 4d. Run AI
            reply, intent = await _ai_engine.process_message(
                phone, inbound.text, session.message_history, context_str
            )
            if intent:
                logger.info("Intent detected for %s: %s sku=%s", phone, intent.intent, intent.sku_hint)

        # 5-6. Persist conversation
        await _conv_manager.append_message(phone, "user", inbound.text)
        await _conv_manager.append_message(phone, "assistant", reply)

        # 7. Send reply via WhatsApp
        await _wa_client.send_text_message(phone, reply)
        logger.info("Replied to %s (%d chars)", phone, len(reply))

    except Exception as exc:
        logger.error("Error handling inbound message from %s: %s", phone, exc, exc_info=True)

    # 8. Always return 200 to Meta
    return {"status": "ok"}


@app.post("/internal/promote-notify")
async def promote_notify():
    """Internal endpoint: immediately check and send any pending promote notifications."""
    if _promote_flow is None or _default_tenant_id is None:
        raise HTTPException(status_code=503, detail="Promote flow not ready")
    retailer_phone = os.environ.get("RETAILER_PHONE_NUMBER", "")
    if not retailer_phone:
        raise HTTPException(status_code=503, detail="RETAILER_PHONE_NUMBER not configured")
    count = await _promote_flow.check_and_notify_new_promotes(retailer_phone, _default_tenant_id)
    return {"sent": count}
