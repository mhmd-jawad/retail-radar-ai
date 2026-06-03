"""
Telegram AI Assistant — LLM-orchestrated conversation engine.
Port: 8004

Run:
    uvicorn services.telegram_assistant.app:app --port 8004 --reload
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from psycopg.rows import dict_row

from services.telegram_assistant.ai_engine import AIEngine
from services.telegram_assistant.business_data_service import BusinessDataService
from services.telegram_assistant.outcome_tracking import (
    due_progress_notifications,
    ensure_closed_loop_tables,
    mark_progress_notification_sent,
)
from services.telegram_assistant.conversation_store import (
    DEFAULT_DATABASE_URL,
    DEFAULT_TENANT_SLUG,
    ConversationManager,
    ensure_conversation_tables,
)
from services.telegram_assistant.promotion_approval_flow import PromoteFlow, poll_loop
from services.telegram_assistant.telegram_client import TelegramClient
from services.telegram_assistant.alert_dispatcher import AlertDispatcher, alert_poll_loop, ensure_alert_tables
from services.telegram_assistant.recommendation_roadmap import ensure_roadmap_tables, roadmap_followup_loop

# ── Load .env ─────────────────────────────────────────────────────────────────
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_SERVICE_DIR = Path(__file__).parent
load_dotenv(_SERVICE_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("telegram_assistant")

# ── Required env vars ─────────────────────────────────────────────────────────
_REQUIRED_ENV_VARS: list[tuple[str, str]] = [
    ("TELEGRAM_BOT_TOKEN",  "Telegram Bot token from @BotFather"),
    ("RETAILER_CHAT_ID",    "Retailer's Telegram chat ID (message the bot then call getUpdates)"),
    ("ANTHROPIC_API_KEY",   "Anthropic API key for the LLM agent"),
    ("DATABASE_URL",        "PostgreSQL connection string"),
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
    if not os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip():
        logger.warning(
            "TELEGRAM_WEBHOOK_SECRET is not set — webhook secret verification is DISABLED. "
            "Set it via setWebhook?secret_token=... to secure the endpoint."
        )


# ── Prometheus metrics ────────────────────────────────────────────────────────
telegram_inbound_messages_total = Counter(
    "telegram_inbound_messages_total",
    "Inbound Telegram text messages received by the assistant",
)
telegram_ignored_webhooks_total = Counter(
    "telegram_ignored_webhooks_total",
    "Webhook events ignored because they were not inbound text messages",
)
telegram_duplicate_messages_total = Counter(
    "telegram_duplicate_messages_total",
    "Webhook deliveries skipped because message_id was already processed",
)
telegram_outbound_messages_total = Counter(
    "telegram_outbound_messages_total",
    "Outbound Telegram messages sent by the assistant",
)
telegram_send_errors_total = Counter(
    "telegram_send_errors_total",
    "Outbound Telegram send failures",
)
telegram_ai_errors_total = Counter(
    "telegram_ai_errors_total",
    "LLM failures",
)
telegram_agent_tool_uses_total = Counter(
    "telegram_agent_tool_uses_total",
    "Tool calls made by the LLM during a conversation turn",
    ["tool"],
)
telegram_response_latency_seconds = Histogram(
    "telegram_response_latency_seconds",
    "End-to-end assistant response latency",
)
radar_pending_recommendations = Gauge(
    "radar_pending_recommendations",
    "Pending model recommendations visible to the assistant",
)
radar_inventory_value_usd = Gauge(
    "radar_inventory_value_usd",
    "Inventory value at cost visible to the assistant",
)

# ── Module-level singletons ───────────────────────────────────────────────────
_telegram_client: TelegramClient | None = None
_conv_manager: ConversationManager | None = None
_ai_engine: AIEngine | None = None
_business_data_service: BusinessDataService | None = None
_promote_flow: PromoteFlow | None = None
_alert_dispatcher: AlertDispatcher | None = None
_default_tenant_id: UUID | None = None
_db_url: str = ""                                  # set once at startup, read on every request
_background_tasks: list[asyncio.Task[Any]] = []    # tracked so lifespan can cancel cleanly


# ── Webhook security ──────────────────────────────────────────────────────────

def _verify_telegram_secret(request: Request) -> None:
    """Verify X-Telegram-Bot-Api-Secret-Token header if TELEGRAM_WEBHOOK_SECRET is configured."""
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not secret:
        return
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if token != secret:
        logger.warning("Webhook secret mismatch — possible spoofed request")
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


# ── Deduplication helpers ─────────────────────────────────────────────────────

async def _is_duplicate(db_url: str, message_id: str) -> bool:
    """Return True if this message_id was already processed."""
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM telegram.processed_messages WHERE message_id = %s",
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
                INSERT INTO telegram.processed_messages (message_id)
                VALUES (%s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (message_id,),
            )
            await cur.execute(
                "DELETE FROM telegram.processed_messages "
                "WHERE processed_at < now() - interval '24 hours'"
            )
        await conn.commit()
    finally:
        await conn.close()


# ── Send helper ───────────────────────────────────────────────────────────────

async def _send_and_count(chat_id: str, reply: str) -> None:
    if _telegram_client is None:
        raise RuntimeError("Telegram client not ready")
    try:
        await _telegram_client.send_text_message(chat_id, reply)
        telegram_outbound_messages_total.inc()
    except Exception:
        telegram_send_errors_total.inc()
        raise


# ── Background pollers ────────────────────────────────────────────────────────

async def _closed_loop_notification_loop(
    db_url: str, retailer_chat_id: str, tenant_id: UUID
) -> None:
    """Notify the retailer when approved decisions are due for 7d/14d checks."""
    while True:
        await asyncio.sleep(int(os.environ.get("CLOSED_LOOP_POLL_SECONDS", "900")))
        try:
            notifications = await due_progress_notifications(db_url, tenant_id, retailer_chat_id)
            for item in notifications:
                try:
                    await _send_and_count(retailer_chat_id, item["message"])
                    await mark_progress_notification_sent(
                        db_url,
                        tenant_id,
                        retailer_chat_id,
                        int(item["snapshot_id"]),
                        int(item["window_days"]),
                        item["message"],
                    )
                    telegram_agent_tool_uses_total.labels(tool="closed_loop_notify").inc()
                except Exception as exc:
                    logger.error("Closed-loop send failed: %s", exc)
        except Exception as exc:
            logger.error("Closed-loop notification poll error: %s", exc, exc_info=True)


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _telegram_client, _conv_manager, _ai_engine, _business_data_service, _promote_flow, _alert_dispatcher, _default_tenant_id, _db_url, _background_tasks

    _validate_env_vars()

    _db_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    _ie3_url = os.environ.get("IE3_BASE_URL", "http://localhost:8003")
    _financial_data_path = str(Path(__file__).resolve().parents[2] / "data" / "real")

    _telegram_client = TelegramClient()
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
        telegram_client=_telegram_client,
        conversation_manager=_conv_manager,
    )

    # DB migrations — all idempotent
    await ensure_closed_loop_tables(_db_url)
    await ensure_conversation_tables(_db_url)
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

    retailer_chat_id = os.environ.get("RETAILER_CHAT_ID", "")
    if _promote_flow is not None and retailer_chat_id and _default_tenant_id is not None:
        _background_tasks = [
            asyncio.create_task(
                poll_loop(_promote_flow, retailer_chat_id, _default_tenant_id),
                name="promote_poller",
            ),
            asyncio.create_task(
                _closed_loop_notification_loop(_db_url, retailer_chat_id, _default_tenant_id),
                name="closed_loop_poller",
            ),
        ]
        _alert_dispatcher = AlertDispatcher(
            db_url=_db_url,
            telegram_client=_telegram_client,
            retailer_chat_id=retailer_chat_id,
            tenant_id=_default_tenant_id,
            financial_data_path=_financial_data_path,
        )
        _background_tasks += [
            asyncio.create_task(
                alert_poll_loop(
                    _alert_dispatcher,
                    interval_seconds=int(os.environ.get("ALERT_POLL_SECONDS", "1800")),
                ),
                name="alert_poller",
            ),
            asyncio.create_task(
                roadmap_followup_loop(
                    db_url=_db_url,
                    retailer_chat_id=retailer_chat_id,
                    tenant_id=_default_tenant_id,
                    telegram_client=_telegram_client,
                    interval_seconds=int(os.environ.get("ROADMAP_FOLLOWUP_SECONDS", "3600")),
                ),
                name="roadmap_followup_poller",
            ),
        ]
        logger.info(
            "Background pollers started for chat_id=%s  "
            "(recommendations/5 min · decisions/15 min · alerts/30 min · roadmap-followup/60 min)",
            retailer_chat_id,
        )
    else:
        logger.warning(
            "Pollers NOT started — missing retailer_chat_id=%r or tenant_id=%s",
            retailer_chat_id,
            _default_tenant_id,
        )

    yield

    # Graceful shutdown — cancel background pollers and wait for them to finish
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
        logger.info("Background pollers stopped.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Telegram AI Assistant",
    description="LLM-orchestrated Telegram Bot conversation engine.",
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
        "service": "telegram_assistant",
        "version": "2.0.0",
        "anthropic_configured": bool(_ai_engine and _ai_engine.is_configured),
        "webhook_secret_configured": bool(os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()),
    }


@app.post("/webhook/telegram")
async def receive_webhook(request: Request):
    """Receive inbound Telegram updates and run the LLM conversation flow."""
    if _telegram_client is None or _ai_engine is None or _business_data_service is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # ① Verify Telegram webhook secret
    _verify_telegram_secret(request)

    body = _json.loads(await request.body())

    inbound = _telegram_client.parse_incoming_update(body)
    if inbound is None:
        telegram_ignored_webhooks_total.inc()
        return {"ok": True}

    # ② Validate message length (Telegram max = 4096 chars)
    if len(inbound.text) > 4096:
        logger.warning("Message from %s is %d chars — truncating", inbound.chat_id, len(inbound.text))
        inbound = inbound.model_copy(update={"text": inbound.text[:4000] + "…"})

    started_at = time.perf_counter()
    telegram_inbound_messages_total.inc()
    chat_id = inbound.chat_id

    # ③ Deduplicate — Telegram retries on timeout; prevent duplicate LLM calls
    if await _is_duplicate(_db_url, inbound.message_id):
        telegram_duplicate_messages_total.inc()
        logger.info("Duplicate message_id=%s from chat_id=%s — skipped", inbound.message_id, chat_id)
        return {"ok": True}
    await _mark_processed(_db_url, inbound.message_id)

    try:
        tenant_id = _default_tenant_id
        if _conv_manager is None or tenant_id is None:
            logger.warning("No conversation manager or tenant — skipping")
            return {"ok": True}

        session = await _conv_manager.get_or_create_session(chat_id, tenant_id)

        if session.cached_business_data:
            ctx = session.cached_business_data
            radar_pending_recommendations.set(len(ctx.get("pending_recommendations") or []))
            radar_inventory_value_usd.set(float(ctx.get("total_inventory_value_usd") or 0))

        # ④ Single LLM entry point — Claude decides what tools to call and how to reply
        reply, tools_used = await _ai_engine.chat(
            chat_id=chat_id,
            user_text=inbound.text,
            message_history=session.message_history,
            conversation_summary=session.conversation_summary,
            tenant_id=tenant_id,
        )

        for tool in tools_used:
            telegram_agent_tool_uses_total.labels(tool=tool).inc()

        await _conv_manager.append_message(chat_id, "user", inbound.text)
        await _conv_manager.append_message(chat_id, "assistant", reply)
        await _send_and_count(chat_id, reply)

        telegram_response_latency_seconds.observe(time.perf_counter() - started_at)
        logger.info("Replied to chat_id=%s — tools=%s chars=%d", chat_id, tools_used, len(reply))

    except Exception as exc:
        telegram_ai_errors_total.inc()
        telegram_response_latency_seconds.observe(time.perf_counter() - started_at)
        logger.error("Error handling message from chat_id=%s: %s", chat_id, exc, exc_info=True)
        try:
            await _send_and_count(
                chat_id,
                "Something went wrong on my end — please try again in a moment.",
            )
        except Exception:
            pass

    return {"ok": True}


@app.post("/internal/promote-notify")
async def promote_notify():
    """Internal endpoint: immediately trigger pending promote notifications."""
    if _promote_flow is None or _default_tenant_id is None:
        raise HTTPException(status_code=503, detail="Promote flow not ready")
    retailer_chat_id = os.environ.get("RETAILER_CHAT_ID", "")
    if not retailer_chat_id:
        raise HTTPException(status_code=503, detail="RETAILER_CHAT_ID not configured")
    count = await _promote_flow.check_and_notify_new_promotes(retailer_chat_id, _default_tenant_id)
    if count:
        telegram_outbound_messages_total.inc(count)
    telegram_agent_tool_uses_total.labels(tool="promote_notify").inc()
    return {"sent": count}
