"""
Telegram AI Assistant — LLM-orchestrated conversation engine.
Port: 8004

Run:
    uvicorn services.telegram_assistant.app:app --port 8004 --reload
"""
from __future__ import annotations

import asyncio
import collections
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

from eep.auth_db import AuthError, authenticate_token, token_from_authorization
from services.telegram_assistant.ai_engine import AIEngine
from services.telegram_assistant.business_data_service import BusinessDataService
from services.telegram_assistant.outcome_tracking import (
    due_progress_notifications,
    ensure_closed_loop_tables,
    mark_progress_notification_sent,
)
from services.telegram_assistant.conversation_store import (
    DEFAULT_DATABASE_URL,
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
logging.getLogger("httpx").setLevel(logging.WARNING)

# ── Required env vars ─────────────────────────────────────────────────────────
_REQUIRED_ENV_VARS: list[tuple[str, str]] = [
    ("TELEGRAM_BOT_TOKEN",  "Telegram Bot token from @BotFather"),
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
    _polling_enabled = os.environ.get("TELEGRAM_POLLING_ENABLED", "true").strip().lower()
    _polling_on = _polling_enabled in {"1", "true", "yes", "on"}
    _webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not _webhook_secret:
        if not _polling_on:
            raise RuntimeError(
                "TELEGRAM_WEBHOOK_SECRET must be set when TELEGRAM_POLLING_ENABLED=false. "
                "Set it to secure your public webhook endpoint."
            )
        logger.warning(
            "TELEGRAM_WEBHOOK_SECRET is not set — webhook secret verification is DISABLED. "
            "This is acceptable for local dev (polling mode) but must be set in production."
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
_db_url: str = ""                                  # set once at startup, read on every request
_background_tasks: list[asyncio.Task[Any]] = []    # tracked so lifespan can cancel cleanly
_start_time: float = time.time()                   # service start timestamp for /status

# ── Rate limiting ─────────────────────────────────────────────────────────────
_RATE_LIMIT_MAX = 20       # messages per minute per chat_id
_rate_limit_windows: dict[str, collections.deque] = {}

def _is_rate_limited(chat_id: str) -> bool:
    """Return True (and DO NOT append) if chat_id has exceeded rate limit, else append and return False."""
    now = time.time()
    window = _rate_limit_windows.setdefault(chat_id, collections.deque())
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= _RATE_LIMIT_MAX:
        return True
    window.append(now)
    return False


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


# ── Tenant resolution helpers ─────────────────────────────────────────────────

async def _resolve_tenant_for_chat(chat_id: str) -> tuple[UUID | None, str, str]:
    """Return (tenant_id, role, shop_name) for a registered chat, or (None, '', '') if not registered."""
    conn = await psycopg.AsyncConnection.connect(_db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT rc.tenant_id, rc.role, COALESCE(sp.business_name, t.name, 'your store') AS shop_name
                FROM telegram.registered_chats rc
                JOIN core.tenants t ON t.id = rc.tenant_id
                LEFT JOIN core.shop_profiles sp ON sp.tenant_id = rc.tenant_id
                WHERE rc.chat_id = %s AND rc.is_active = true
                LIMIT 1
                """,
                (chat_id,),
            )
            row = await cur.fetchone()
        if row:
            return row["tenant_id"], row.get("role") or "owner", row.get("shop_name") or "your store"
        return None, "", ""
    finally:
        await conn.close()


async def _fetch_shop_name(tenant_id: str) -> str:
    """Return the business name for a tenant, falling back to the tenant name."""
    conn = await psycopg.AsyncConnection.connect(_db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COALESCE(sp.business_name, t.name, 'your store') AS shop_name
                FROM core.tenants t
                LEFT JOIN core.shop_profiles sp ON sp.tenant_id = t.id
                WHERE t.id = %s
                LIMIT 1
                """,
                (tenant_id,),
            )
            row = await cur.fetchone()
        return row["shop_name"] if row else "your store"
    except Exception:
        return "your store"
    finally:
        await conn.close()


async def _get_all_active_tenant_chats() -> list[dict]:
    """Return all {tenant_id, chat_id} pairs for active registered chats."""
    conn = await psycopg.AsyncConnection.connect(_db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT tenant_id, chat_id FROM telegram.registered_chats WHERE is_active = true"
            )
            return await cur.fetchall()
    finally:
        await conn.close()


async def _handle_register_command(chat_id: str, code: str) -> None:
    """Process /register <code> — bind chat_id to a tenant via a one-time registration code."""
    conn = await psycopg.AsyncConnection.connect(_db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT rc.tenant_id, sp.business_name
                FROM telegram.registration_codes rc
                LEFT JOIN core.shop_profiles sp ON sp.tenant_id = rc.tenant_id
                WHERE rc.code = %s
                  AND rc.expires_at > now()
                  AND rc.used_at IS NULL
                """,
                (code.strip(),),
            )
            row = await cur.fetchone()
        if not row:
            await _send_and_count(
                chat_id,
                "❌ Invalid or expired registration code. Please generate a new one from your dashboard.",
            )
            return

        tenant_id = row["tenant_id"]
        business_name = row.get("business_name") or "your store"

        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO telegram.registered_chats (tenant_id, chat_id, is_active, role)
                VALUES (%s, %s, true, 'owner')
                ON CONFLICT (chat_id) DO UPDATE
                    SET tenant_id = EXCLUDED.tenant_id,
                        is_active = true
                """,
                (str(tenant_id), chat_id),
            )
            await cur.execute(
                "UPDATE telegram.registration_codes "
                "SET used_at = now(), used_by_chat_id = %s WHERE code = %s",
                (chat_id, code.strip()),
            )
        await conn.commit()

        await _send_and_count(
            chat_id,
            f"✅ You're connected to *{business_name}* as *owner*.\n\n"
            "*Three things to try first:*\n"
            "• \"How is my inventory?\" — stock overview\n"
            "• \"Show me pending recommendations\" — AI decisions waiting for your call\n"
            "• \"What should I do today?\" — prioritized action list\n\n"
            "Type /help for the full list of what I can do.",
        )
        logger.info("Registered chat_id=%s for tenant_id=%s", chat_id, tenant_id)
    except Exception as exc:
        logger.error("Register command failed for chat_id=%s: %s", chat_id, exc)
        await _send_and_count(chat_id, "Registration failed — please try again.")
    finally:
        await conn.close()


_HELP_TEXT = """\
📖 *What I can do for you:*

*📦 Inventory*
• "How is my inventory?" — stock overview + dead stock
• "What's running low?" — low stock and stockout risk
• "What should I reorder?" — reorder suggestions with quantities

*💰 Financials*
• "How much cash do I have?" — runway, OPEX, blended margin
• "Are sales up this week?" — week-over-week revenue trend

*🏷️ Pricing & Competitors*
• "What are competitors charging?" — price gaps vs 7 Lebanese retailers
• "Which category is doing best?" — revenue and margin by category

*🤖 AI Decisions*
• "Show me pending recommendations" — awaiting your approval
• "Approve" / "Reject" / "Modify 20% instead" — act on a recommendation
• "Show all active decisions" — full lifecycle roadmap
• "What should I do today?" — priority action list

*📊 Outcome Tracking*
• "How did my last decisions perform?" — 7-day and 14-day results

*⚙️ Commands*
• /help — this menu
• /status — service health check
• /unregister — disconnect this chat from your store

_Ask in plain English or Arabic — I understand both._"""


async def _handle_help_command(chat_id: str) -> None:
    await _send_and_count(chat_id, _HELP_TEXT)


async def _handle_status_command(chat_id: str) -> None:
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes = remainder // 60
    uptime_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

    db_ok = False
    try:
        conn = await psycopg.AsyncConnection.connect(_db_url, row_factory=dict_row)
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
        await conn.close()
        db_ok = True
    except Exception:
        pass

    ai_ok = bool(_ai_engine and _ai_engine.is_configured)
    webhook_secured = bool(os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip())

    lines = [
        "⚙️ *Radar AI — Service Status*\n",
        f"• Database: {'✅ connected' if db_ok else '❌ unreachable'}",
        f"• AI engine: {'✅ configured' if ai_ok else '❌ not configured'}",
        f"• Webhook secret: {'✅ enforced' if webhook_secured else '⚠️ not set (dev mode)'}",
        f"• Uptime: {uptime_str}",
        "\n_Pollers: promote/5 min · alerts/30 min · roadmap/60 min · outcomes/15 min_",
    ]
    await _send_and_count(chat_id, "\n".join(lines))


_pending_unregister: set[str] = set()


async def _handle_unregister_command(chat_id: str, args: str) -> None:
    """Handle /unregister — requires /unregister YES to confirm."""
    if args.strip().upper() == "YES":
        if chat_id not in _pending_unregister:
            await _send_and_count(
                chat_id,
                "No pending unregister request. Send /unregister first to start.",
            )
            return
        _pending_unregister.discard(chat_id)
        conn = await psycopg.AsyncConnection.connect(_db_url, row_factory=dict_row)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE telegram.registered_chats SET is_active = false WHERE chat_id = %s",
                    (chat_id,),
                )
            await conn.commit()
        except Exception as exc:
            logger.error("Unregister failed for chat_id=%s: %s", chat_id, exc)
            await _send_and_count(chat_id, "Failed to unregister — please try again.")
            return
        finally:
            await conn.close()
        await _send_and_count(
            chat_id,
            "✅ This chat has been disconnected from Radar AI.\n\n"
            "You will no longer receive alerts or recommendations here. "
            "Use /register <code> to reconnect.",
        )
    else:
        _pending_unregister.add(chat_id)
        await _send_and_count(
            chat_id,
            "⚠️ *Are you sure you want to disconnect?*\n\n"
            "You will stop receiving all alerts, recommendations, and outcome reports on this chat.\n\n"
            "Send /unregister YES to confirm, or send any other message to cancel.",
        )


# ── Deduplication helpers ─────────────────────────────────────────────────────

async def _is_duplicate(db_url: str, tenant_id: UUID, message_id: str) -> bool:
    """Return True if this (tenant, message_id) was already processed."""
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM telegram.processed_messages "
                "WHERE tenant_id = %s AND message_id = %s",
                (str(tenant_id), message_id),
            )
            return bool(await cur.fetchone())
    finally:
        await conn.close()


async def _mark_processed(db_url: str, tenant_id: UUID, message_id: str) -> None:
    """Record (tenant, message_id) as processed and purge entries older than 24 h."""
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO telegram.processed_messages (tenant_id, message_id)
                VALUES (%s, %s)
                ON CONFLICT (tenant_id, message_id) DO NOTHING
                """,
                (str(tenant_id), message_id),
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

def _build_outcome_notification(item: dict, measurement: dict | None) -> str:
    """Build a rich Telegram notification for a completed outcome measurement."""
    window_days = int(item.get("window_days", 7))
    decision_type = item.get("decision_type", "")
    brand = item.get("brand") or ""
    product_name = item.get("product_name") or ""
    sku_id = item.get("sku_id") or ""

    if measurement and measurement.get("data_available"):
        lift = measurement.get("velocity_lift_pct")
        rev_delta = float(measurement.get("revenue_delta_usd") or 0)
        accuracy = measurement.get("accuracy_score")
        narrative = (measurement.get("narrative") or "").strip()

        lift_val = float(lift) if lift is not None else None
        if lift_val is not None and lift_val > 5:
            verdict = "✅ Good call"
        elif lift_val is not None and lift_val < -5:
            verdict = "⚠️ Below target"
        else:
            verdict = "➡️ Neutral"

        lift_str = f"{lift_val:+.1f}%" if lift_val is not None else "?"
        acc_str = f"{float(accuracy) * 100:.0f}%" if accuracy is not None else "?"

        lines = [
            f"📊 *{window_days}-Day Outcome — {verdict}*",
            f"{decision_type} › {brand} {product_name} ({sku_id})\n",
            f"• Velocity lift: *{lift_str}*",
            f"• Revenue delta: *${rev_delta:+,.0f}*",
            f"• Model accuracy: *{acc_str}*",
        ]
        if narrative:
            lines.append(f"\n_{narrative[:300]}_")
        lines.append("\nAsk *decision progress* for full analysis.")
        return "\n".join(lines)

    # No sales data available
    return (
        f"📊 *{window_days}-Day Check — No Data*\n"
        f"{decision_type} › {brand} {product_name} ({sku_id})\n\n"
        "Insufficient sales data is available for this window. "
        "Connect your POS feed to enable automatic outcome tracking.\n\n"
        "Ask *decision progress* to see all tracked decisions."
    )


async def _closed_loop_notification_loop(db_url: str) -> None:
    """Auto-measure due snapshots and notify registered retailers with rich results."""
    while True:
        await asyncio.sleep(int(os.environ.get("CLOSED_LOOP_POLL_SECONDS", "900")))
        try:
            tenant_chats = await _get_all_active_tenant_chats()
            for tc in tenant_chats:
                chat_id = tc["chat_id"]
                tenant_id = tc["tenant_id"]
                try:
                    notifications = await due_progress_notifications(db_url, tenant_id, chat_id)
                    for item in notifications:
                        snapshot_id = int(item["snapshot_id"])
                        window_days = int(item["window_days"])

                        # Auto-measure before notifying
                        measurement: dict | None = None
                        try:
                            def _do_measure(sid: int, wd: int, tid: Any) -> dict:
                                from eep.outcome_tracking import measure_outcome
                                return measure_outcome(sid, wd, tenant_id=tid)

                            measurement = await asyncio.to_thread(_do_measure, snapshot_id, window_days, tenant_id)
                        except Exception as exc:
                            logger.warning(
                                "Auto-measure snapshot %d failed: %s — will still notify",
                                snapshot_id, exc,
                            )

                        message = _build_outcome_notification(item, measurement)

                        try:
                            await _send_and_count(chat_id, message)
                            await mark_progress_notification_sent(
                                db_url,
                                tenant_id,
                                chat_id,
                                snapshot_id,
                                window_days,
                                message,
                            )
                            telegram_agent_tool_uses_total.labels(tool="closed_loop_notify").inc()
                        except Exception as exc:
                            logger.error("Closed-loop send to chat %s failed: %s", chat_id, exc)
                except Exception as exc:
                    logger.error("Closed-loop poll for tenant %s failed: %s", tenant_id, exc)
        except Exception as exc:
            logger.error("Closed-loop notification poll error: %s", exc, exc_info=True)


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _telegram_client, _conv_manager, _ai_engine, _business_data_service, _promote_flow, _db_url, _background_tasks

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

    # Multi-tenant pollers — self-discover all registered tenants from DB on each cycle
    _background_tasks = [
        asyncio.create_task(
            _telegram_polling_loop(),
            name="telegram_polling",
        ),
        asyncio.create_task(
            _multi_tenant_promote_loop(_promote_flow),
            name="promote_poller",
        ),
        asyncio.create_task(
            _closed_loop_notification_loop(_db_url),
            name="closed_loop_poller",
        ),
        asyncio.create_task(
            _multi_tenant_alert_loop(
                _db_url,
                _telegram_client,
                _financial_data_path,
                interval_seconds=int(os.environ.get("ALERT_POLL_SECONDS", "1800")),
            ),
            name="alert_poller",
        ),
        asyncio.create_task(
            _multi_tenant_roadmap_loop(
                _db_url,
                _telegram_client,
                interval_seconds=int(os.environ.get("ROADMAP_FOLLOWUP_SECONDS", "3600")),
            ),
            name="roadmap_followup_poller",
        ),
    ]
    logger.info(
        "Multi-tenant background pollers started "
        "(promote/5 min · closed-loop/15 min · alerts/30 min · roadmap/60 min)"
    )

    yield

    # Graceful shutdown — cancel background pollers and wait for them to finish
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
        logger.info("Background pollers stopped.")


# ── Multi-tenant poller wrappers ──────────────────────────────────────────────

async def _multi_tenant_promote_loop(promote_flow: PromoteFlow) -> None:
    """Poll all registered tenants every 5 min for new recommendations and expiry warnings."""
    while True:
        await asyncio.sleep(300)
        try:
            tenant_chats = await _get_all_active_tenant_chats()
            for tc in tenant_chats:
                try:
                    count = await promote_flow.check_and_notify_new_promotes(
                        tc["chat_id"], tc["tenant_id"]
                    )
                    if count > 0:
                        telegram_outbound_messages_total.inc(count)
                    warn_count = await promote_flow.check_and_send_expiry_warnings(
                        tc["chat_id"], tc["tenant_id"]
                    )
                    if warn_count > 0:
                        telegram_outbound_messages_total.inc(warn_count)
                except Exception as exc:
                    logger.error("Promote poll for tenant %s failed: %s", tc["tenant_id"], exc)
        except Exception as exc:
            logger.error("Multi-tenant promote poll error: %s", exc)


async def _telegram_polling_loop() -> None:
    """Poll Telegram directly for local deployments that do not expose a public webhook."""
    enabled = os.environ.get("TELEGRAM_POLLING_ENABLED", "true").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        logger.info("Telegram polling disabled by TELEGRAM_POLLING_ENABLED=%s", enabled)
        return
    if os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip():
        logger.warning(
            "TELEGRAM_WEBHOOK_SECRET is set — polling disabled to prevent duplicate message processing. "
            "Set TELEGRAM_POLLING_ENABLED=false to suppress this warning."
        )
        return

    while _telegram_client is None:
        await asyncio.sleep(1)

    try:
        await _telegram_client.delete_webhook(drop_pending_updates=False)
    except Exception as exc:
        logger.warning("Could not clear Telegram webhook before polling: %s", exc)

    logger.info("Telegram polling loop started")
    offset: int | None = None
    while True:
        try:
            updates = await _telegram_client.get_updates(offset=offset, timeout=30)
            for update in updates:
                update_id = int(update.get("update_id", 0))
                offset = update_id + 1
                await _process_telegram_update(update)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Telegram polling error: %s", exc, exc_info=True)
            await asyncio.sleep(5)


async def _multi_tenant_alert_loop(
    db_url: str,
    telegram_client: "TelegramClient",
    financial_data_path: str,
    interval_seconds: int = 1800,
) -> None:
    """Run all alert checks for every registered tenant every `interval_seconds`."""
    await asyncio.sleep(60)  # Initial delay so service fully starts
    while True:
        try:
            tenant_chats = await _get_all_active_tenant_chats()
            for tc in tenant_chats:
                try:
                    dispatcher = AlertDispatcher(
                        db_url=db_url,
                        telegram_client=telegram_client,
                        retailer_chat_id=tc["chat_id"],
                        tenant_id=tc["tenant_id"],
                        financial_data_path=financial_data_path,
                    )
                    count = await dispatcher.run_all_checks()
                    if count:
                        logger.info(
                            "Alert cycle sent %d alert(s) for tenant %s",
                            count, tc["tenant_id"],
                        )
                except Exception as exc:
                    logger.error("Alert check for tenant %s failed: %s", tc["tenant_id"], exc)
        except Exception as exc:
            logger.error("Multi-tenant alert poll error: %s", exc, exc_info=True)
        await asyncio.sleep(interval_seconds)


async def _multi_tenant_roadmap_loop(
    db_url: str,
    telegram_client: "TelegramClient",
    interval_seconds: int = 3600,
) -> None:
    """Send roadmap follow-ups for every registered tenant."""
    await asyncio.sleep(120)
    while True:
        try:
            tenant_chats = await _get_all_active_tenant_chats()
            for tc in tenant_chats:
                try:
                    await roadmap_followup_loop(
                        db_url=db_url,
                        retailer_chat_id=tc["chat_id"],
                        tenant_id=tc["tenant_id"],
                        telegram_client=telegram_client,
                        interval_seconds=0,  # single run, outer loop controls cadence
                    )
                except Exception as exc:
                    logger.error("Roadmap loop for tenant %s failed: %s", tc["tenant_id"], exc)
        except Exception as exc:
            logger.error("Multi-tenant roadmap loop error: %s", exc)
        await asyncio.sleep(interval_seconds)


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
    return await _process_telegram_update(body)


async def _process_telegram_update(body: dict[str, Any]) -> dict[str, bool]:
    """Process one Telegram Update from either webhook delivery or getUpdates polling."""
    if _telegram_client is None or _ai_engine is None or _business_data_service is None:
        raise RuntimeError("Service not ready")

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

    # ③ Handle commands that work before tenant resolution
    cmd_text = inbound.text.strip()
    if cmd_text.startswith("/register"):
        parts = cmd_text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code:
            await _send_and_count(chat_id, "Usage: /register <your-registration-code>")
        else:
            await _handle_register_command(chat_id, code)
        return {"ok": True}

    if cmd_text == "/help":
        await _handle_help_command(chat_id)
        return {"ok": True}

    if cmd_text.startswith("/unregister"):
        args = cmd_text[len("/unregister"):].strip()
        await _handle_unregister_command(chat_id, args)
        return {"ok": True}

    # ④ Resolve which tenant owns this chat (also returns role)
    tenant_id, role, shop_name = await _resolve_tenant_for_chat(chat_id)
    if tenant_id is None:
        await _send_and_count(
            chat_id,
            "👋 Welcome to Radar AI!\n\n"
            "To get started, send /register <code> using the registration code from your dashboard.\n\n"
            "Type /help to see what I can do once you're connected.",
        )
        return {"ok": True}

    # /status requires tenant resolution so the DB check uses the right connection
    if cmd_text == "/status":
        await _handle_status_command(chat_id)
        return {"ok": True}

    # ⑤ Rate limiting — 20 messages per minute per chat
    if _is_rate_limited(chat_id):
        await _send_and_count(
            chat_id,
            "⏳ Slow down — I'm still processing your last request. Please wait a moment.",
        )
        return {"ok": True}

    # Cancel pending unregister if user sends any other message
    _pending_unregister.discard(chat_id)

    # ⑥ Deduplicate — Telegram retries on timeout; prevent duplicate LLM calls
    if await _is_duplicate(_db_url, tenant_id, inbound.message_id):
        telegram_duplicate_messages_total.inc()
        logger.info("Duplicate message_id=%s from chat_id=%s — skipped", inbound.message_id, chat_id)
        return {"ok": True}
    await _mark_processed(_db_url, tenant_id, inbound.message_id)

    try:
        if _conv_manager is None:
            logger.warning("No conversation manager — skipping")
            return {"ok": True}

        session = await _conv_manager.get_or_create_session(chat_id, tenant_id)

        if session.cached_business_data:
            ctx = session.cached_business_data
            radar_pending_recommendations.set(len(ctx.get("pending_recommendations") or []))
            radar_inventory_value_usd.set(float(ctx.get("total_inventory_value_usd") or 0))

        # ⑦ Single LLM entry point — Claude decides what tools to call and how to reply
        reply, tools_used = await _ai_engine.chat(
            chat_id=chat_id,
            user_text=inbound.text,
            message_history=session.message_history,
            conversation_summary=session.conversation_summary,
            tenant_id=tenant_id,
            role=role,
            shop_name=shop_name,
        )

        for tool in tools_used:
            telegram_agent_tool_uses_total.labels(tool=tool).inc()

        await _conv_manager.append_message(chat_id, "user", inbound.text, tenant_id=tenant_id)
        await _conv_manager.append_message(chat_id, "assistant", reply, tenant_id=tenant_id)
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
                "⚠️ Something went wrong on my end — please try again in a moment.\n\n"
                "If this keeps happening, type /status to check if all systems are up.",
            )
        except Exception:
            pass

    return {"ok": True}


@app.post("/chat")
async def web_chat(request: Request):
    """Web chat endpoint — used by the React dashboard to talk to the AI assistant."""
    if _ai_engine is None or _conv_manager is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    token = token_from_authorization(request.headers.get("authorization"))
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is required")
    try:
        auth_ctx = await asyncio.to_thread(authenticate_token, token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if auth_ctx.global_role != "shop" or not auth_ctx.tenant_id:
        raise HTTPException(status_code=403, detail="Shop tenant access is required")

    body = await request.json()
    message: str = (body.get("message") or "").strip()
    session_id: str = (body.get("session_id") or "default").strip()

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    try:
        tenant_id = UUID(auth_ctx.tenant_id)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid tenant on authenticated session")

    chat_id = f"web:{session_id}"

    shop_name = await _fetch_shop_name(str(tenant_id))

    try:
        session = await _conv_manager.get_or_create_session(chat_id, tenant_id)
        reply, tools_used = await _ai_engine.chat(
            chat_id=chat_id,
            user_text=message,
            message_history=session.message_history,
            conversation_summary=session.conversation_summary,
            tenant_id=tenant_id,
            role="owner",
            shop_name=shop_name,
        )
        await _conv_manager.append_message(chat_id, "user", message, tenant_id=tenant_id)
        await _conv_manager.append_message(chat_id, "assistant", reply, tenant_id=tenant_id)
        telegram_inbound_messages_total.inc()
        telegram_outbound_messages_total.inc()
        return {"reply": reply, "tools_used": tools_used}
    except Exception as exc:
        logger.error("Web chat error for tenant=%s: %s", tenant_id, exc, exc_info=True)
        telegram_ai_errors_total.inc()
        raise HTTPException(status_code=500, detail="AI processing failed — please try again")


@app.post("/internal/promote-notify")
async def promote_notify():
    """Internal endpoint: immediately trigger pending promote notifications for all tenants."""
    if _promote_flow is None:
        raise HTTPException(status_code=503, detail="Promote flow not ready")
    tenant_chats = await _get_all_active_tenant_chats()
    total = 0
    for tc in tenant_chats:
        try:
            count = await _promote_flow.check_and_notify_new_promotes(
                tc["chat_id"], tc["tenant_id"]
            )
            total += count
        except Exception as exc:
            logger.error("promote_notify for tenant %s failed: %s", tc["tenant_id"], exc)
    if total:
        telegram_outbound_messages_total.inc(total)
    telegram_agent_tool_uses_total.labels(tool="promote_notify").inc()
    return {"sent": total}
