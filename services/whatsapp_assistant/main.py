"""
WhatsApp AI Assistant — LLM-orchestrated conversation engine.
Port: 8004

Run:
    uvicorn services.whatsapp_assistant.main:app --port 8004 --reload
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json as _json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from psycopg.rows import dict_row

from services.whatsapp_assistant.agent import AIEngine
from services.whatsapp_assistant.data_service import BusinessDataService
from services.whatsapp_assistant.outcome_tracker import (
    due_progress_notifications,
    ensure_closed_loop_tables,
    mark_progress_notification_sent,
)
from services.whatsapp_assistant.session_manager import (
    DEFAULT_DATABASE_URL,
    DEFAULT_TENANT_SLUG,
    ConversationManager,
    ensure_conversation_tables,
    is_within_24h_window,
)
from services.whatsapp_assistant.approval_flow import PromoteFlow, poll_loop
from services.whatsapp_assistant.messenger import WhatsAppClient
from services.whatsapp_assistant.alert_engine import AlertEngine, alert_poll_loop, ensure_alert_tables
from services.whatsapp_assistant.roadmap import ensure_roadmap_tables, roadmap_followup_loop

# ── Load .env ─────────────────────────────────────────────────────────────────
_SERVICE_DIR = Path(__file__).parent
load_dotenv(_SERVICE_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("whatsapp_assistant")

# ── Required env vars ─────────────────────────────────────────────────────────
_REQUIRED_ENV_VARS: list[tuple[str, str]] = [
    ("WHATSAPP_TOKEN",              "WhatsApp Business API token (Meta App)"),
    ("WHATSAPP_PHONE_NUMBER_ID",    "Phone Number ID from Meta Business Suite"),
    ("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "Webhook verification token (self-chosen)"),
    ("RETAILER_PHONE_NUMBER",       "Retailer's WhatsApp number e.g. +96170XXXXXX"),
    ("ANTHROPIC_API_KEY",           "Anthropic API key for the LLM agent"),
    ("DATABASE_URL",                "PostgreSQL connection string"),
]


def _validate_env_vars() -> None:
    """Fail fast at startup if required environment variables are missing."""
    missing = [(k, desc) for k, desc in _REQUIRED_ENV_VARS if not os.environ.get(k, "").strip()]
    if missing:
        lines = "\n".join(f"  {k}: {desc}" for k, desc in missing)
        raise RuntimeError(
            f"Service cannot start — missing required environment variables:\n{lines}\n"
            "Set them in .env or your deployment config."
        )
    if not os.environ.get("WHATSAPP_APP_SECRET", "").strip():
        logger.warning(
            "WHATSAPP_APP_SECRET is not set — webhook signature verification is DISABLED. "
            "Set it from Meta App Settings → App Secret to secure the endpoint."
        )


# ── Prometheus metrics ────────────────────────────────────────────────────────
whatsapp_inbound_messages_total = Counter(
    "whatsapp_inbound_messages_total",
    "Inbound WhatsApp text messages received by the assistant",
)
whatsapp_ignored_webhooks_total = Counter(
    "whatsapp_ignored_webhooks_total",
    "Webhook events ignored because they were not inbound text messages",
)
whatsapp_duplicate_messages_total = Counter(
    "whatsapp_duplicate_messages_total",
    "Webhook deliveries skipped because message_id was already processed",
)
whatsapp_outbound_messages_total = Counter(
    "whatsapp_outbound_messages_total",
    "Outbound WhatsApp messages sent by the assistant",
)
whatsapp_send_errors_total = Counter(
    "whatsapp_send_errors_total",
    "Outbound WhatsApp send failures",
)
whatsapp_ai_errors_total = Counter(
    "whatsapp_ai_errors_total",
    "LLM failures",
)
whatsapp_agent_tool_uses_total = Counter(
    "whatsapp_agent_tool_uses_total",
    "Tool calls made by the LLM during a conversation turn",
    ["tool"],
)
whatsapp_response_latency_seconds = Histogram(
    "whatsapp_response_latency_seconds",
    "End-to-end WhatsApp assistant response latency",
)
radar_pending_recommendations = Gauge(
    "radar_pending_recommendations",
    "Pending model recommendations visible to the WhatsApp assistant",
)
radar_inventory_value_usd = Gauge(
    "radar_inventory_value_usd",
    "Inventory value at cost visible to the WhatsApp assistant",
)

# ── Module-level singletons ───────────────────────────────────────────────────
_wa_client: WhatsAppClient | None = None
_conv_manager: ConversationManager | None = None
_ai_engine: AIEngine | None = None
_business_data_service: BusinessDataService | None = None
_promote_flow: PromoteFlow | None = None
_alert_engine: AlertEngine | None = None
_default_tenant_id: UUID | None = None


# ── Webhook security helpers ──────────────────────────────────────────────────

async def _verify_signature_and_parse(request: Request) -> dict[str, Any]:
    """Verify X-Hub-Signature-256 from Meta and return the parsed JSON body.

    If WHATSAPP_APP_SECRET is set, the signature MUST match or we return 403.
    If it is not set we let the request through but the startup warning flags this.
    """
    raw_body = await request.body()
    app_secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()

    if app_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not signature:
            raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256 header")
        expected = "sha256=" + _hmac.new(
            app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not _hmac.compare_digest(signature, expected):
            logger.warning("Webhook signature mismatch — possible spoofed request")
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    return _json.loads(raw_body)


# ── Deduplication helpers ─────────────────────────────────────────────────────

async def _is_duplicate(db_url: str, message_id: str) -> bool:
    """Return True if this message_id was already processed (prevents double-send on Meta retries)."""
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM whatsapp.processed_messages WHERE message_id = %s",
                (message_id,),
            )
            return bool(await cur.fetchone())
    finally:
        await conn.close()


async def _mark_processed(db_url: str, message_id: str) -> None:
    """Record message_id as processed and purge entries older than 24 h."""
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO whatsapp.processed_messages (message_id)
                VALUES (%s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (message_id,),
            )
            await cur.execute(
                "DELETE FROM whatsapp.processed_messages "
                "WHERE processed_at < now() - interval '24 hours'"
            )
        await conn.commit()
    finally:
        await conn.close()


# ── 24-hour window helpers ────────────────────────────────────────────────────

async def _track_last_inbound(db_url: str, phone: str) -> None:
    """Stamp last_inbound_at so proactive senders know if the 24 h window is open."""
    conn = await psycopg.AsyncConnection.connect(db_url)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE whatsapp.conversations SET last_inbound_at = now() WHERE phone_number = %s",
                (phone,),
            )
        await conn.commit()
    except Exception as exc:
        logger.debug("Could not update last_inbound_at: %s", exc)
    finally:
        await conn.close()


async def _send_proactive(db_url: str, phone: str, message: str) -> bool:
    """Send a proactive (business-initiated) notification only when the 24 h window is open.

    Returns True if sent, False if deferred because the window is closed.
    The caller (poller) will retry on the next cycle once the retailer replies.
    """
    if not await is_within_24h_window(db_url, phone):
        logger.info(
            "Proactive send deferred for %s — 24 h window closed (retailer hasn't messaged recently)",
            phone,
        )
        return False
    await _send_and_count(phone, message)
    return True


# ── Send helper ───────────────────────────────────────────────────────────────

async def _send_and_count(phone: str, reply: str) -> None:
    if _wa_client is None:
        raise RuntimeError("WhatsApp client not ready")
    try:
        await _wa_client.send_text_message(phone, reply)
        whatsapp_outbound_messages_total.inc()
    except Exception:
        whatsapp_send_errors_total.inc()
        raise


# ── Background pollers ────────────────────────────────────────────────────────

async def _closed_loop_notification_loop(
    db_url: str, retailer_phone: str, tenant_id: UUID
) -> None:
    """Notify the retailer when approved decisions are due for 7d/14d checks."""
    while True:
        await asyncio.sleep(int(os.environ.get("CLOSED_LOOP_POLL_SECONDS", "900")))
        try:
            notifications = await due_progress_notifications(db_url, tenant_id, retailer_phone)
            for item in notifications:
                sent = await _send_proactive(db_url, retailer_phone, item["message"])
                if sent:
                    await mark_progress_notification_sent(
                        db_url,
                        tenant_id,
                        retailer_phone,
                        int(item["snapshot_id"]),
                        int(item["window_days"]),
                        item["message"],
                    )
                    whatsapp_agent_tool_uses_total.labels(tool="closed_loop_notify").inc()
        except Exception as exc:
            logger.error("Closed-loop notification poll error: %s", exc, exc_info=True)


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _wa_client, _conv_manager, _ai_engine, _business_data_service, _promote_flow, _alert_engine, _default_tenant_id

    # Fail loudly if required env vars are absent — don't start a broken service
    _validate_env_vars()

    _db_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    _ie3_url = os.environ.get("IE3_BASE_URL", "http://localhost:8003")
    _financial_data_path = str(Path(__file__).resolve().parents[2] / "data" / "real")

    _wa_client = WhatsAppClient()
    _conv_manager = ConversationManager(_db_url)
    _business_data_service = BusinessDataService(
        db_url=_db_url,
        financial_data_path=_financial_data_path,
    )
    _ai_engine = AIEngine(
        business_data_service=_business_data_service,
        db_url=_db_url,
        ie3_base_url=_ie3_url,
    )
    _promote_flow = PromoteFlow(
        db_url=_db_url,
        ie3_base_url=_ie3_url,
        whatsapp_client=_wa_client,
        conversation_manager=_conv_manager,
    )

    # DB migrations — all idempotent
    await ensure_closed_loop_tables(_db_url)
    await ensure_conversation_tables(_db_url)   # also creates processed_messages table
    await ensure_alert_tables(_db_url)
    await ensure_roadmap_tables(_db_url)
    await _business_data_service.warmup()

    # Cache default tenant_id
    try:
        conn = await psycopg.AsyncConnection.connect(_db_url, row_factory=dict_row)
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
            logger.warning("Tenant '%s' not found in DB", DEFAULT_TENANT_SLUG)
    except Exception as exc:
        logger.warning("Could not cache tenant_id at startup: %s", exc)

    retailer_phone = os.environ.get("RETAILER_PHONE_NUMBER", "")
    if _promote_flow is not None and retailer_phone and _default_tenant_id is not None:
        asyncio.create_task(
            poll_loop(_promote_flow, retailer_phone, _default_tenant_id),
            name="promote_poller",
        )
        asyncio.create_task(
            _closed_loop_notification_loop(_db_url, retailer_phone, _default_tenant_id),
            name="closed_loop_poller",
        )
        _alert_engine = AlertEngine(
            db_url=_db_url,
            wa_client=_wa_client,
            retailer_phone=retailer_phone,
            tenant_id=_default_tenant_id,
            financial_data_path=_financial_data_path,
        )
        asyncio.create_task(
            alert_poll_loop(
                _alert_engine,
                interval_seconds=int(os.environ.get("ALERT_POLL_SECONDS", "1800")),
            ),
            name="alert_poller",
        )
        asyncio.create_task(
            roadmap_followup_loop(
                db_url=_db_url,
                retailer_phone=retailer_phone,
                tenant_id=_default_tenant_id,
                wa_client=_wa_client,
                interval_seconds=int(os.environ.get("ROADMAP_FOLLOWUP_SECONDS", "3600")),
            ),
            name="roadmap_followup_poller",
        )
        logger.info(
            "Background pollers started for %s  "
            "(recommendations/5 min · decisions/15 min · alerts/30 min · roadmap-followup/60 min)",
            retailer_phone,
        )
    else:
        logger.warning(
            "Pollers NOT started — missing retailer_phone=%r or tenant_id=%s",
            retailer_phone,
            _default_tenant_id,
        )

    yield


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="WhatsApp AI Assistant",
    description="LLM-orchestrated WhatsApp Business API conversation engine.",
    version="2.0.0",
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

app.mount("/metrics", make_asgi_app())


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "whatsapp_assistant",
        "version": "2.0.0",
        "anthropic_configured": bool(_ai_engine and _ai_engine.is_configured),
        "signature_verification": bool(os.environ.get("WHATSAPP_APP_SECRET", "").strip()),
    }


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
async def receive_webhook(request: Request):
    """Receive inbound WhatsApp messages and run the LLM conversation flow."""
    if _wa_client is None or _ai_engine is None or _business_data_service is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # ① Verify Meta X-Hub-Signature-256 and parse body
    body = await _verify_signature_and_parse(request)

    inbound = _wa_client.parse_incoming_webhook(body)
    if inbound is None:
        whatsapp_ignored_webhooks_total.inc()
        return {"status": "ok"}

    # ② Validate message length (WhatsApp max = 4096 chars)
    if len(inbound.text) > 4096:
        logger.warning("Message from %s is %d chars — truncating to 4096", inbound.phone_number, len(inbound.text))
        inbound = inbound.model_copy(update={"text": inbound.text[:4000] + "…"})

    started_at = time.perf_counter()
    whatsapp_inbound_messages_total.inc()
    phone = inbound.phone_number
    _db_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

    # ③ Deduplicate — Meta retries webhooks on timeout; prevent duplicate LLM calls
    if await _is_duplicate(_db_url, inbound.message_id):
        whatsapp_duplicate_messages_total.inc()
        logger.info("Duplicate message_id=%s from %s — skipped", inbound.message_id, phone)
        return {"status": "ok"}
    await _mark_processed(_db_url, inbound.message_id)

    # ④ Update 24-hour window timestamp
    await _track_last_inbound(_db_url, phone)

    try:
        tenant_id = _default_tenant_id
        if _conv_manager is None or tenant_id is None:
            logger.warning("No conversation manager or tenant — skipping")
            return {"status": "ok"}

        session = await _conv_manager.get_or_create_session(phone, tenant_id)

        if session.cached_business_data:
            ctx = session.cached_business_data
            radar_pending_recommendations.set(len(ctx.get("pending_recommendations") or []))
            radar_inventory_value_usd.set(float(ctx.get("total_inventory_value_usd") or 0))

        # ⑤ Single LLM entry point — Claude decides what tools to call and how to reply
        reply, tools_used = await _ai_engine.chat(
            phone=phone,
            user_text=inbound.text,
            message_history=session.message_history,
            conversation_summary=session.conversation_summary,
            tenant_id=tenant_id,
        )

        for tool in tools_used:
            whatsapp_agent_tool_uses_total.labels(tool=tool).inc()

        await _conv_manager.append_message(phone, "user", inbound.text)
        await _conv_manager.append_message(phone, "assistant", reply)
        await _send_and_count(phone, reply)

        whatsapp_response_latency_seconds.observe(time.perf_counter() - started_at)
        logger.info("Replied to %s — tools=%s chars=%d", phone, tools_used, len(reply))

    except Exception as exc:
        whatsapp_ai_errors_total.inc()
        whatsapp_response_latency_seconds.observe(time.perf_counter() - started_at)
        logger.error("Error handling message from %s: %s", phone, exc, exc_info=True)
        # ⑥ Send a fallback reply so the retailer isn't left hanging
        try:
            await _send_and_count(
                phone,
                "Something went wrong on my end — please try again in a moment.",
            )
        except Exception:
            pass  # best-effort; original error already logged

    return {"status": "ok"}


@app.post("/internal/promote-notify")
async def promote_notify():
    """Internal endpoint: immediately trigger pending promote notifications."""
    if _promote_flow is None or _default_tenant_id is None:
        raise HTTPException(status_code=503, detail="Promote flow not ready")
    retailer_phone = os.environ.get("RETAILER_PHONE_NUMBER", "")
    if not retailer_phone:
        raise HTTPException(status_code=503, detail="RETAILER_PHONE_NUMBER not configured")
    count = await _promote_flow.check_and_notify_new_promotes(retailer_phone, _default_tenant_id)
    if count:
        whatsapp_outbound_messages_total.inc(count)
    whatsapp_agent_tool_uses_total.labels(tool="promote_notify").inc()
    return {"sent": count}
