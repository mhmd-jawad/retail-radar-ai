"""
PostgreSQL-backed WhatsApp conversation session manager.
Uses psycopg3 async — mirrors eep/retail_db.py connection pattern.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/retail_radar"
DEFAULT_TENANT_SLUG = "default"
_MAX_HISTORY = 10       # legacy constant kept for backward compatibility
_MAX_RECENT = 12        # messages kept verbatim in the sliding window
_SUMMARIZE_AFTER = 20   # trigger summarization when history reaches this size


async def ensure_conversation_tables(db_url: str) -> None:
    """Idempotent migration: add new columns and helper tables to whatsapp schema."""
    import psycopg

    conn = await psycopg.AsyncConnection.connect(db_url)
    try:
        async with conn.cursor() as cur:
            await cur.execute("CREATE SCHEMA IF NOT EXISTS whatsapp")
            # Main conversations table — idempotent
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS whatsapp.conversations (
                    phone_number          TEXT        PRIMARY KEY,
                    tenant_id             UUID        NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
                    message_history       JSONB       NOT NULL DEFAULT '[]',
                    active_flow           TEXT,
                    flow_context          JSONB,
                    cached_business_data  JSONB,
                    cached_at             TIMESTAMPTZ,
                    last_message_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_inbound_at       TIMESTAMPTZ,
                    conversation_summary  TEXT,
                    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # New columns added in later migrations — safe to run on existing tables
            await cur.execute(
                "ALTER TABLE whatsapp.conversations "
                "ADD COLUMN IF NOT EXISTS conversation_summary TEXT"
            )
            await cur.execute(
                "ALTER TABLE whatsapp.conversations "
                "ADD COLUMN IF NOT EXISTS last_inbound_at TIMESTAMPTZ"
            )
            # Table: deduplication — prevents processing Meta webhook retries twice
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS whatsapp.processed_messages (
                    message_id   TEXT        PRIMARY KEY,
                    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processed_messages_cleanup
                    ON whatsapp.processed_messages (processed_at)
                """
            )
        await conn.commit()
    except Exception:
        # Table may not exist yet (closed_loop creates whatsapp schema); ignore here
        pass
    finally:
        await conn.close()


async def is_within_24h_window(db_url: str, phone: str) -> bool:
    """Return True if the retailer sent an inbound message within the last 24 hours.

    Used by proactive senders to decide whether a free-form text message can be
    sent without being rejected by Meta's 24-hour conversation window policy.
    """
    import psycopg
    from psycopg.rows import dict_row

    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT last_inbound_at FROM whatsapp.conversations WHERE phone_number = %s",
                (phone,),
            )
            row = await cur.fetchone()
        if not row or not row.get("last_inbound_at"):
            return False
        last = row["last_inbound_at"]
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - last).total_seconds() < 86400
    except Exception:
        return True  # Assume in-window on DB error to avoid blocking sends
    finally:
        await conn.close()


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


async def _summarize_messages(messages: list[dict]) -> str:
    """Summarize a batch of old messages into a compact text using Claude Haiku."""
    try:
        import anthropic as _anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or "xxxx" in api_key.lower():
            return _simple_summary(messages)

        text_block = "\n".join(
            f"{m['role'].upper()}: {m.get('content', '')[:300]}" for m in messages
        )
        client = _anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize this WhatsApp retail assistant conversation in 3-4 bullet points. "
                        "Preserve key decisions, approved/rejected actions, and any business figures mentioned.\n\n"
                        + text_block
                    ),
                }
            ],
        )
        return response.content[0].text if response.content else _simple_summary(messages)
    except Exception:
        return _simple_summary(messages)


def _simple_summary(messages: list[dict]) -> str:
    """Fallback: return a plain-text excerpt when LLM is unavailable."""
    lines = [f"[{m['role']}] {str(m.get('content', ''))[:120]}" for m in messages[-6:]]
    return "Earlier conversation excerpt:\n" + "\n".join(lines)


class ConversationManager:
    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or _database_url()

    # ── internal helpers ──────────────────────────────────────────────────────

    async def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return await psycopg.AsyncConnection.connect(
            self._database_url, row_factory=dict_row
        )

    async def _default_tenant_id(self, conn) -> UUID:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM core.tenants WHERE slug = %s LIMIT 1",
                (DEFAULT_TENANT_SLUG,),
            )
            row = await cur.fetchone()
            if not row:
                raise RuntimeError(
                    f"Default tenant '{DEFAULT_TENANT_SLUG}' not found. Run the schema first."
                )
            return row["id"]

    # ── public API ────────────────────────────────────────────────────────────

    async def get_or_create_session(
        self, phone_number: str, tenant_id: UUID
    ):
        from services.whatsapp_assistant.models import ConversationSession

        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT phone_number, tenant_id, message_history,
                           active_flow, flow_context,
                           cached_business_data, cached_at,
                           conversation_summary
                    FROM whatsapp.conversations
                    WHERE phone_number = %s
                    """,
                    (phone_number,),
                )
                row = await cur.fetchone()

            if row:
                return ConversationSession(
                    phone_number=row["phone_number"],
                    tenant_id=row["tenant_id"],
                    message_history=row["message_history"] or [],
                    active_flow=row["active_flow"],
                    flow_context=row["flow_context"],
                    cached_business_data=row["cached_business_data"],
                    cached_at=row["cached_at"],
                    conversation_summary=row.get("conversation_summary"),
                )

            # Not found — insert a fresh session
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO whatsapp.conversations
                        (tenant_id, phone_number, message_history)
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (tenant_id, phone_number) DO NOTHING
                    """,
                    (str(tenant_id), phone_number, json.dumps([])),
                )
            await conn.commit()

            return ConversationSession(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_history=[],
            )
        finally:
            await conn.close()

    async def append_message(
        self, phone_number: str, role: str, content: str
    ) -> None:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT message_history FROM whatsapp.conversations WHERE phone_number = %s",
                    (phone_number,),
                )
                row = await cur.fetchone()
                history: list[dict] = row["message_history"] if row else []

            history.append(
                {
                    "role": role,
                    "content": content,
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                }
            )

            # Sliding window with summarization
            summary_to_store: str | None = None
            if len(history) >= _SUMMARIZE_AFTER:
                old_messages = history[:-_MAX_RECENT]
                history = history[-_MAX_RECENT:]
                summary_to_store = await _summarize_messages(old_messages)

            async with conn.cursor() as cur:
                if summary_to_store is not None:
                    await cur.execute(
                        """
                        UPDATE whatsapp.conversations
                        SET message_history = %s::jsonb,
                            conversation_summary = %s,
                            last_message_at = now()
                        WHERE phone_number = %s
                        """,
                        (json.dumps(history), summary_to_store, phone_number),
                    )
                else:
                    await cur.execute(
                        """
                        UPDATE whatsapp.conversations
                        SET message_history = %s::jsonb,
                            last_message_at = now()
                        WHERE phone_number = %s
                        """,
                        (json.dumps(history), phone_number),
                    )
            await conn.commit()
        finally:
            await conn.close()

    async def set_flow(
        self, phone_number: str, flow_name: str, context: dict
    ) -> None:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE whatsapp.conversations
                    SET active_flow = %s,
                        flow_context = %s::jsonb
                    WHERE phone_number = %s
                    """,
                    (flow_name, json.dumps(context), phone_number),
                )
            await conn.commit()
        finally:
            await conn.close()

    async def clear_flow(self, phone_number: str) -> None:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE whatsapp.conversations
                    SET active_flow = null,
                        flow_context = null
                    WHERE phone_number = %s
                    """,
                    (phone_number,),
                )
            await conn.commit()
        finally:
            await conn.close()

    async def get_cached_business_data(
        self, phone_number: str
    ) -> tuple[dict | None, datetime | None]:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT cached_business_data, cached_at FROM whatsapp.conversations WHERE phone_number = %s",
                    (phone_number,),
                )
                row = await cur.fetchone()
            if not row:
                return None, None
            return row["cached_business_data"], row["cached_at"]
        finally:
            await conn.close()

    async def set_cached_business_data(
        self, phone_number: str, data: dict
    ) -> None:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE whatsapp.conversations
                    SET cached_business_data = %s::jsonb,
                        cached_at = now()
                    WHERE phone_number = %s
                    """,
                    (json.dumps(data), phone_number),
                )
            await conn.commit()
        finally:
            await conn.close()


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pathlib import Path

    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        from dotenv import load_dotenv

        load_dotenv(_env_file, override=True)

    TEST_PHONE = "+96170000000"

    async def _run_tests() -> None:
        import psycopg
        from psycopg.rows import dict_row

        db_url = _database_url()
        mgr = ConversationManager(db_url)

        # Resolve default tenant_id
        conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM core.tenants WHERE slug = %s LIMIT 1",
                (DEFAULT_TENANT_SLUG,),
            )
            row = await cur.fetchone()
        await conn.close()
        if not row:
            raise RuntimeError(f"Tenant '{DEFAULT_TENANT_SLUG}' not found.")
        default_tenant_id: UUID = row["id"]

        # 1 + 2. get_or_create_session
        session = await mgr.get_or_create_session(TEST_PHONE, default_tenant_id)
        print(f"[1] session created/fetched for {session.phone_number}")

        # 3. append_message
        await mgr.append_message(TEST_PHONE, "user", "hello")
        print("[2] message appended")

        # 4. re-fetch and print history
        session2 = await mgr.get_or_create_session(TEST_PHONE, default_tenant_id)
        print(f"[3] message_history: {session2.message_history}")
        assert len(session2.message_history) >= 1, "Expected at least 1 message in history"

        # 5. set_flow
        await mgr.set_flow(TEST_PHONE, "promote", {"sku_id": "TEST-001"})
        print("[4] flow set to 'promote'")

        # 6. clear_flow
        await mgr.clear_flow(TEST_PHONE)
        print("[5] flow cleared")

        print("\nAll tests passed")

    import selectors
    asyncio.run(_run_tests(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
