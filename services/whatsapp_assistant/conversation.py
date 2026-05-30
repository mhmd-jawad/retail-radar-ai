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
_MAX_HISTORY = 10


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


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
        from services.whatsapp_assistant.schemas import ConversationSession

        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT phone_number, tenant_id, message_history,
                           active_flow, flow_context,
                           cached_business_data, cached_at
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
            history = history[-_MAX_HISTORY:]

            async with conn.cursor() as cur:
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
