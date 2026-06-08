"""
Web chat session persistence for the retailer dashboard assistant.

Uses the same synchronous psycopg pattern as retail_db.py.
All operations are scoped to a (session_id, tenant_id) pair to prevent
cross-tenant data leakage.
"""
from __future__ import annotations

import json
from typing import Any

from eep.retail_db import _connect, DatabaseUnavailable


def get_or_create_session(session_id: str, tenant_id: str) -> dict[str, Any]:
    """Return existing session or create a new one. Always validates tenant ownership."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO core.chat_sessions (session_id, tenant_id, message_history)
                VALUES (%s::uuid, %s::uuid, '[]'::jsonb)
                ON CONFLICT (session_id) DO NOTHING
                """,
                (session_id, tenant_id),
            )
            cur.execute(
                """
                SELECT session_id::text, tenant_id::text, title,
                       message_history, created_at, last_message_at
                FROM core.chat_sessions
                WHERE session_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (session_id, tenant_id),
            )
            row = cur.fetchone()
    if row is None:
        raise DatabaseUnavailable("Chat session not found or tenant mismatch.")
    return dict(row)


def get_history(session_id: str, tenant_id: str) -> list[dict[str, Any]]:
    """Return message history for a session. Returns [] if session doesn't exist."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT message_history
                FROM core.chat_sessions
                WHERE session_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (session_id, tenant_id),
            )
            row = cur.fetchone()
    if row is None:
        return []
    history = row["message_history"]
    if isinstance(history, str):
        history = json.loads(history)
    return history or []


def append_messages(session_id: str, tenant_id: str, messages: list[dict[str, Any]]) -> None:
    """Append one or more messages to the session history and update last_message_at.

    Also sets the session title from the first user message if not yet set.
    """
    if not messages:
        return

    first_user_msg = next(
        (m["content"] for m in messages if m.get("role") == "user"), None
    )
    title_snippet = (first_user_msg[:60] + "…") if first_user_msg and len(first_user_msg) > 60 else first_user_msg

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE core.chat_sessions
                SET message_history  = message_history || %s::jsonb,
                    last_message_at  = NOW(),
                    title            = COALESCE(title, %s)
                WHERE session_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (
                    json.dumps(messages),
                    title_snippet,
                    session_id,
                    tenant_id,
                ),
            )


def list_sessions(tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent chat sessions for a tenant (most recent first)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id::text, title, last_message_at, created_at
                FROM core.chat_sessions
                WHERE tenant_id = %s::uuid
                ORDER BY last_message_at DESC
                LIMIT %s
                """,
                (tenant_id, limit),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]
