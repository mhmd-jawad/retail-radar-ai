"""
Authentication and multi-tenant shop management for the EEP service.

Covers shop signup and login (bcrypt passwords, JWT tokens), token
validation and claims decoding, shop profile reads and updates, and admin
operations such as tenant listing, competitor management, social account
management, and notification broadcasting.

All functions connect to the ``marketing`` PostgreSQL schema.
The database URL is read from the ``DATABASE_URL`` environment variable.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from eep.retail_db import _connect, _jsonable, store_code


_AUTH_TABLES_READY = False
_AUTH_TABLES_LOCK = threading.Lock()


class AuthError(RuntimeError):
    pass


class LoginPayload(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=500)

    @field_validator("email", mode="before")
    @classmethod
    def _clean_email(cls, value: Any) -> str:
        return _normalize_email(value)


class ShopSignupPayload(BaseModel):
    owner_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=500)
    shop_name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=240)
    phone: str | None = Field(default=None, max_length=80)
    website_url: str | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=500)
    country: str = Field(default="Lebanon", max_length=120)
    timezone: str = Field(default="Asia/Beirut", max_length=120)
    selected_competitor_codes: list[str] = Field(default_factory=list, max_length=50)
    requested_competitor_names: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("email", mode="before")
    @classmethod
    def _clean_email(cls, value: Any) -> str:
        return _normalize_email(value)

    @field_validator(
        "owner_name",
        "shop_name",
        "legal_name",
        "phone",
        "website_url",
        "address",
        "country",
        "timezone",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, value: Any) -> Any:
        return _clean_optional_text(value)

    @field_validator("selected_competitor_codes", "requested_competitor_names", mode="before")
    @classmethod
    def _clean_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("must be a list")
        cleaned: list[str] = []
        for entry in value:
            text = _clean_optional_text(entry)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned


class ShopProfileUpdatePayload(BaseModel):
    business_name: str | None = Field(default=None, max_length=200)
    legal_name: str | None = Field(default=None, max_length=240)
    phone: str | None = Field(default=None, max_length=80)
    website_url: str | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=120)
    selected_competitor_codes: list[str] | None = Field(default=None, max_length=50)
    requested_competitor_names: list[str] | None = Field(default=None, max_length=50)

    @field_validator(
        "business_name",
        "legal_name",
        "phone",
        "website_url",
        "address",
        "country",
        "timezone",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, value: Any) -> Any:
        return _clean_optional_text(value)

    @field_validator("selected_competitor_codes", "requested_competitor_names", mode="before")
    @classmethod
    def _clean_list(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("must be a list")
        cleaned: list[str] = []
        for entry in value:
            text = _clean_optional_text(entry)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned


class AuthContext(BaseModel):
    user_id: str
    email: str
    full_name: str
    global_role: str
    tenant_id: str | None = None
    tenant_slug: str | None = None
    tenant_name: str | None = None
    member_role: str | None = None


def login(payload: LoginPayload, user_agent: str | None = None, ip_address: str | None = None) -> dict[str, Any]:
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, email, password_hash, full_name, global_role, is_active
                from core.app_users
                where lower(email) = lower(%s)
                """,
                (payload.email,),
            )
            user = cur.fetchone()
            if not user or not user["is_active"] or not _verify_password(payload.password, user["password_hash"]):
                raise AuthError("Invalid email or password.")

            ctx = _primary_auth_context(cur, user)
            token = _make_token(ctx)
            _store_session(cur, user["id"], token, user_agent, ip_address)
            cur.execute("update core.app_users set last_login_at = now(), updated_at = now() where id = %s", (user["id"],))

    return {"access_token": token, "token_type": "bearer", "user": ctx.model_dump()}


def signup_shop(payload: ShopSignupPayload, user_agent: str | None = None, ip_address: str | None = None) -> dict[str, Any]:
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute("select 1 from core.app_users where lower(email) = lower(%s)", (payload.email,))
            if cur.fetchone():
                raise AuthError("An account with this email already exists.")

            tenant_slug = _unique_tenant_slug(cur, payload.shop_name)
            cur.execute(
                """
                insert into core.tenants (name, slug, default_currency)
                values (%s, %s, 'USD')
                returning id, name, slug
                """,
                (payload.shop_name, tenant_slug),
            )
            tenant = cur.fetchone()
            cur.execute(
                """
                insert into core.stores (tenant_id, code, name, timezone, currency)
                values (%s, %s, 'Main Store', %s, 'USD')
                returning id
                """,
                (tenant["id"], store_code(), payload.timezone),
            )
            cur.fetchone()
            cur.execute(
                """
                insert into core.app_users (email, password_hash, full_name, global_role, email_verified)
                values (%s, %s, %s, 'shop', false)
                returning id, email, full_name, global_role, is_active
                """,
                (payload.email, _hash_password(payload.password), payload.owner_name),
            )
            user = cur.fetchone()
            cur.execute(
                """
                insert into core.user_memberships (user_id, tenant_id, role)
                values (%s, %s, 'owner')
                """,
                (user["id"], tenant["id"]),
            )
            cur.execute(
                """
                insert into core.shop_profiles (
                    tenant_id, owner_user_id, business_name, legal_name, contact_email,
                    phone, website_url, address, country, timezone, onboarding_status
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    tenant["id"],
                    user["id"],
                    payload.shop_name,
                    payload.legal_name,
                    payload.email,
                    payload.phone,
                    payload.website_url,
                    payload.address,
                    payload.country,
                    payload.timezone,
                ),
            )
            _insert_notification(
                cur,
                recipient_role="admin",
                notification_type="shop_signup",
                title=f"New shop registered: {payload.shop_name}",
                message=f"{payload.owner_name} ({payload.email}) registered \"{payload.shop_name}\" and is awaiting approval.",
                tenant_id=tenant["id"],
                actor_user_id=user["id"],
                priority="high",
                payload={"tenant_id": str(tenant["id"]), "email": payload.email},
            )
            _replace_tenant_competitors(cur, tenant["id"], payload.selected_competitor_codes)
            _insert_competitor_requests(cur, tenant["id"], user["id"], payload.requested_competitor_names)
            ctx = _primary_auth_context(cur, user)
            token = _make_token(ctx)
            _store_session(cur, user["id"], token, user_agent, ip_address)

    return {"access_token": token, "token_type": "bearer", "user": ctx.model_dump()}


def ensure_default_admin_account() -> dict[str, Any] | None:
    email = _clean_optional_text(os.environ.get("RETAIL_ADMIN_EMAIL"))
    password = os.environ.get("RETAIL_ADMIN_PASSWORD")
    full_name = _clean_optional_text(os.environ.get("RETAIL_ADMIN_NAME")) or "Retail Radar Admin"
    if not email or not password:
        return None

    normalized_email = _normalize_email(email)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute("select id from core.app_users where lower(email) = lower(%s)", (normalized_email,))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """
                    update core.app_users
                    set full_name = %s, global_role = 'admin', is_active = true, updated_at = now()
                    where id = %s
                    """,
                    (full_name, existing["id"]),
                )
                return {"created": False, "email": normalized_email}
            cur.execute(
                """
                insert into core.app_users (email, password_hash, full_name, global_role, email_verified)
                values (%s, %s, %s, 'admin', true)
                """,
                (normalized_email, _hash_password(password), full_name),
            )
    return {"created": True, "email": normalized_email}


def authenticate_token(token: str) -> AuthContext:
    payload = _decode_token(token)
    token_hash = _token_hash(token)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select s.id
                from core.auth_sessions s
                where s.token_hash = %s
                  and s.revoked_at is null
                  and s.expires_at > now()
                """,
                (token_hash,),
            )
            if not cur.fetchone():
                raise AuthError("Session expired or revoked.")
            cur.execute(
                """
                select id, email, full_name, global_role, is_active
                from core.app_users
                where id = %s
                """,
                (payload.get("sub"),),
            )
            user = cur.fetchone()
            if not user or not user["is_active"]:
                raise AuthError("User is inactive.")
            return _primary_auth_context(cur, user)


def logout(token: str) -> dict[str, Any]:
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                "update core.auth_sessions set revoked_at = now() where token_hash = %s and revoked_at is null",
                (_token_hash(token),),
            )
    return {"ok": True}


def list_available_competitors() -> list[dict[str, Any]]:
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select shop_code, shop_name, is_active
                from intel.shops
                where is_active = true
                order by shop_name
                """
            )
            return [_row(row) for row in cur.fetchall()]


def get_shop_profile(ctx: AuthContext) -> dict[str, Any]:
    tenant_id = _require_tenant_id(ctx)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            profile = _profile_row(cur, tenant_id)
            if not profile:
                raise AuthError("Shop profile not found.")
            return profile


def update_shop_profile(ctx: AuthContext, payload: ShopProfileUpdatePayload) -> dict[str, Any]:
    tenant_id = _require_tenant_id(ctx)
    data = payload.model_dump(exclude_unset=True)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            if any(key in data for key in ("business_name", "legal_name", "phone", "website_url", "address", "country", "timezone")):
                cur.execute(
                    """
                    update core.shop_profiles
                    set business_name = coalesce(%s, business_name),
                        legal_name = coalesce(%s, legal_name),
                        phone = coalesce(%s, phone),
                        website_url = coalesce(%s, website_url),
                        address = coalesce(%s, address),
                        country = coalesce(%s, country),
                        timezone = coalesce(%s, timezone),
                        updated_at = now()
                    where tenant_id = %s
                    """,
                    (
                        data.get("business_name"),
                        data.get("legal_name"),
                        data.get("phone"),
                        data.get("website_url"),
                        data.get("address"),
                        data.get("country"),
                        data.get("timezone"),
                        tenant_id,
                    ),
                )
                if data.get("business_name"):
                    cur.execute(
                        "update core.tenants set name = %s, updated_at = now() where id = %s",
                        (data["business_name"], tenant_id),
                    )
            if "selected_competitor_codes" in data:
                _replace_tenant_competitors(cur, tenant_id, data["selected_competitor_codes"] or [])
            if data.get("requested_competitor_names"):
                _insert_competitor_requests(cur, tenant_id, ctx.user_id, data["requested_competitor_names"] or [])
            return _profile_row(cur, tenant_id)


def admin_list_tenants(ctx: AuthContext) -> list[dict[str, Any]]:
    _require_admin(ctx)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select t.id, t.name, t.slug, sp.contact_email, sp.phone, sp.onboarding_status,
                       count(distinct v.id) as sku_count,
                       count(distinct tc.shop_code) filter (where tc.is_active) as competitor_count,
                       t.created_at
                from core.tenants t
                left join core.shop_profiles sp on sp.tenant_id = t.id
                left join core.sku_variants v on v.tenant_id = t.id and v.status = 'active'
                left join intel.tenant_competitors tc on tc.tenant_id = t.id
                group by t.id, sp.tenant_id
                order by t.created_at desc
                """
            )
            return [_row(row) for row in cur.fetchall()]


def admin_list_competitor_requests(ctx: AuthContext, status: str | None = None) -> list[dict[str, Any]]:
    _require_admin(ctx)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            conditions = []
            params: list[Any] = []
            if status:
                conditions.append("cr.status = %s")
                params.append(status)
            where = f"where {' and '.join(conditions)}" if conditions else ""
            cur.execute(
                """
                select cr.id, cr.tenant_id, t.name as shop_name, cr.competitor_name,
                       cr.website_url, cr.status, u.email as requested_by_email,
                       cr.admin_notes, cr.created_at, cr.reviewed_at
                from intel.competitor_requests cr
                join core.tenants t on t.id = cr.tenant_id
                left join core.app_users u on u.id = cr.requested_by_user_id
                """
                + where
                + """
                order by cr.created_at desc
                limit 500
                """,
                params,
            )
            return [_row(row) for row in cur.fetchall()]


def admin_list_notifications(
    ctx: AuthContext,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _require_admin(ctx)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            conditions = ["n.recipient_role = 'admin'"]
            params: list[Any] = []
            if status:
                conditions.append("n.status = %s")
                params.append(status)
            params.append(limit)
            cur.execute(
                """
                select n.id, n.recipient_role, n.recipient_user_id, n.tenant_id,
                       t.name as shop_name, t.slug as shop_slug,
                       n.actor_user_id, u.email as actor_email, u.full_name as actor_name,
                       n.type, n.title, n.message, n.payload, n.status, n.priority,
                       n.created_at, n.read_at, n.resolved_at
                from core.notifications n
                left join core.tenants t on t.id = n.tenant_id
                left join core.app_users u on u.id = n.actor_user_id
                where """ + " and ".join(conditions) + """
                order by
                    case n.status when 'unread' then 0 when 'read' then 1 when 'resolved' then 2 else 3 end,
                    n.created_at desc
                limit %s
                """,
                params,
            )
            return [_row(row) for row in cur.fetchall()]


def list_shop_notifications(
    ctx: AuthContext,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    tenant_id = _require_tenant_id(ctx)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            conditions = ["n.recipient_role = 'shop'", "(n.tenant_id = %s or n.recipient_user_id = %s)"]
            params: list[Any] = [tenant_id, ctx.user_id]
            if status:
                conditions.append("n.status = %s")
                params.append(status)
            params.append(limit)
            cur.execute(
                """
                select n.id, n.recipient_role, n.recipient_user_id, n.tenant_id,
                       t.name as shop_name, t.slug as shop_slug,
                       n.actor_user_id, u.email as actor_email, u.full_name as actor_name,
                       n.type, n.title, n.message, n.payload, n.status, n.priority,
                       n.created_at, n.read_at, n.resolved_at
                from core.notifications n
                left join core.tenants t on t.id = n.tenant_id
                left join core.app_users u on u.id = n.actor_user_id
                where """ + " and ".join(conditions) + """
                order by n.created_at desc
                limit %s
                """,
                params,
            )
            return [_row(row) for row in cur.fetchall()]


def update_notification_status(ctx: AuthContext, notification_id: str, status: str) -> dict[str, Any]:
    if status not in {"unread", "read", "resolved", "dismissed"}:
        raise AuthError("Invalid notification status.")

    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            conditions = ["id = %s"]
            params: list[Any] = [notification_id]
            if ctx.global_role == "admin":
                conditions.append("recipient_role = 'admin'")
            else:
                tenant_id = _require_tenant_id(ctx)
                conditions.append("recipient_role = 'shop'")
                conditions.append("(tenant_id = %s or recipient_user_id = %s)")
                params.extend([tenant_id, ctx.user_id])

            read_at_sql = "now()" if status in {"read", "resolved"} else "read_at"
            resolved_at_sql = "now()" if status == "resolved" else "resolved_at"
            params.append(status)
            cur.execute(
                f"""
                update core.notifications
                set status = %s,
                    read_at = {read_at_sql},
                    resolved_at = {resolved_at_sql}
                where {' and '.join(conditions)}
                returning id, recipient_role, recipient_user_id, tenant_id, actor_user_id,
                          type, title, message, payload, status, priority,
                          created_at, read_at, resolved_at
                """,
                [params[-1], *params[:-1]],
            )
            row = cur.fetchone()
            if not row:
                raise AuthError("Notification not found.")
            return _row(row)


def admin_list_competitors(ctx: AuthContext) -> list[dict[str, Any]]:
    _require_admin(ctx)
    return list_available_competitors()


def admin_review_competitor_request(
    ctx: AuthContext,
    request_id: str,
    action: str,
    admin_notes: str | None = None,
) -> dict[str, Any]:
    """Approve or reject a shop's competitor request.

    Approving onboards the competitor into the catalog (intel.shops), links it to
    the requesting tenant, marks the request 'onboarded', notifies the shop, and
    resolves the matching admin notification(s).
    """
    _require_admin(ctx)
    if action not in {"approve", "reject"}:
        raise AuthError("Invalid action.")
    notes = _clean_optional_text(admin_notes)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select cr.id, cr.tenant_id, cr.requested_by_user_id, cr.competitor_name,
                       cr.website_url, cr.status, t.name as shop_name
                from intel.competitor_requests cr
                join core.tenants t on t.id = cr.tenant_id
                where cr.id = %s
                """,
                (request_id,),
            )
            req = cur.fetchone()
            if not req:
                raise AuthError("Competitor request not found.")
            if req["status"] in {"rejected", "onboarded"}:
                raise AuthError("This request has already been reviewed.")

            if action == "reject":
                cur.execute(
                    """
                    update intel.competitor_requests
                    set status = 'rejected', admin_notes = %s,
                        reviewed_at = now(), reviewed_by_user_id = %s
                    where id = %s
                    """,
                    (notes, ctx.user_id, request_id),
                )
                _insert_notification(
                    cur,
                    recipient_role="shop",
                    notification_type="competitor_request_update",
                    title="Competitor request declined",
                    message=f'Your request for "{req["competitor_name"]}" was declined.',
                    tenant_id=req["tenant_id"],
                    recipient_user_id=req["requested_by_user_id"],
                    actor_user_id=ctx.user_id,
                    priority="normal",
                    payload={"competitor_request_id": str(request_id), "status": "rejected"},
                )
                _resolve_request_notifications(cur, request_id)
                return _competitor_request_row(cur, request_id)

            # approve -> onboard into the competitor catalog
            cur.execute(
                "select shop_code from intel.shops where lower(shop_name) = lower(%s) limit 1",
                (req["competitor_name"],),
            )
            existing = cur.fetchone()
            shop_code = existing["shop_code"] if existing else _unique_shop_code(cur, req["competitor_name"])
            cur.execute(
                """
                insert into intel.shops (shop_code, shop_name, is_active)
                values (%s, %s, true)
                on conflict (shop_code) do update set
                    shop_name = excluded.shop_name, is_active = true, updated_at = now()
                """,
                (shop_code, req["competitor_name"]),
            )
            cur.execute(
                """
                insert into intel.tenant_competitors (tenant_id, shop_code, is_active)
                values (%s, %s, true)
                on conflict (tenant_id, shop_code) do update set is_active = true, updated_at = now()
                """,
                (req["tenant_id"], shop_code),
            )
            cur.execute(
                """
                update intel.competitor_requests
                set status = 'onboarded', admin_notes = %s,
                    reviewed_at = now(), reviewed_by_user_id = %s
                where id = %s
                """,
                (notes, ctx.user_id, request_id),
            )
            _insert_notification(
                cur,
                recipient_role="shop",
                notification_type="competitor_request_update",
                title="Competitor request approved",
                message=f'"{req["competitor_name"]}" was approved and added to your competitor catalog.',
                tenant_id=req["tenant_id"],
                recipient_user_id=req["requested_by_user_id"],
                actor_user_id=ctx.user_id,
                priority="normal",
                payload={
                    "competitor_request_id": str(request_id),
                    "status": "onboarded",
                    "shop_code": shop_code,
                },
            )
            _resolve_request_notifications(cur, request_id)
            return _competitor_request_row(cur, request_id)


def admin_update_shop_status(
    ctx: AuthContext,
    tenant_id: str,
    onboarding_status: str,
) -> dict[str, Any]:
    """Approve / suspend / archive a shop and notify its owner."""
    _require_admin(ctx)
    if onboarding_status not in {"pending", "active", "suspended", "archived"}:
        raise AuthError("Invalid shop status.")
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                update core.shop_profiles
                set onboarding_status = %s, updated_at = now()
                where tenant_id = %s
                returning owner_user_id
                """,
                (onboarding_status, tenant_id),
            )
            updated = cur.fetchone()
            if not updated:
                raise AuthError("Shop not found.")
            _insert_notification(
                cur,
                recipient_role="shop",
                notification_type="shop_status_update",
                title=f"Account {onboarding_status}",
                message=f'Your shop account status is now "{onboarding_status}".',
                tenant_id=tenant_id,
                recipient_user_id=updated["owner_user_id"],
                actor_user_id=ctx.user_id,
                priority="high" if onboarding_status in {"suspended", "archived"} else "normal",
                payload={"onboarding_status": onboarding_status},
            )
            if onboarding_status == "active":
                cur.execute(
                    """
                    update core.notifications
                    set status = 'resolved', read_at = coalesce(read_at, now()), resolved_at = now()
                    where recipient_role = 'admin' and status <> 'resolved'
                      and type = 'shop_signup' and tenant_id = %s
                    """,
                    (tenant_id,),
                )
            return _admin_tenant_row(cur, tenant_id)


def admin_impersonate_shop(ctx: AuthContext, tenant_id: str) -> dict[str, Any]:
    """Mint a READ-ONLY session that views a shop's workspace as its owner.

    The token carries a `read_only` claim; the EEP middleware blocks all writes
    for such sessions, so the admin can inspect a tenant's data without changing it.
    """
    _require_admin(ctx)
    with _connect() as conn:
        _ensure_auth_tables(conn)
        with conn.cursor() as cur:
            cur.execute("select id, slug, name from core.tenants where id = %s", (tenant_id,))
            tenant = cur.fetchone()
            if not tenant:
                raise AuthError("Shop not found.")
            cur.execute(
                """
                select u.id, u.email, u.full_name, u.global_role
                from core.shop_profiles sp
                join core.app_users u on u.id = sp.owner_user_id
                where sp.tenant_id = %s
                """,
                (tenant_id,),
            )
            owner = cur.fetchone()
            if not owner:
                cur.execute(
                    """
                    select u.id, u.email, u.full_name, u.global_role
                    from core.user_memberships m
                    join core.app_users u on u.id = m.user_id
                    where m.tenant_id = %s and m.is_active = true
                    order by m.created_at asc
                    limit 1
                    """,
                    (tenant_id,),
                )
                owner = cur.fetchone()
            if not owner:
                raise AuthError("This shop has no owner account to view.")
            cur.execute(
                """
                select role from core.user_memberships
                where user_id = %s and tenant_id = %s and is_active = true
                limit 1
                """,
                (owner["id"], tenant_id),
            )
            membership = cur.fetchone()
            shop_ctx = AuthContext(
                user_id=str(owner["id"]),
                email=owner["email"],
                full_name=owner["full_name"],
                global_role="shop",
                tenant_id=str(tenant["id"]),
                tenant_slug=tenant["slug"],
                tenant_name=tenant["name"],
                member_role=membership["role"] if membership else "owner",
            )
            token = _make_token(
                shop_ctx,
                extra_claims={"read_only": True, "impersonated_by": ctx.user_id},
            )
            _store_session(cur, owner["id"], token, "admin-impersonation", None)
    user = shop_ctx.model_dump()
    user["read_only"] = True
    user["impersonated_by_email"] = ctx.email
    return {"access_token": token, "token_type": "bearer", "user": user}


def _competitor_request_row(cur, request_id: str) -> dict[str, Any]:
    cur.execute(
        """
        select cr.id, cr.tenant_id, t.name as shop_name, cr.competitor_name,
               cr.website_url, cr.status, u.email as requested_by_email,
               cr.admin_notes, cr.created_at, cr.reviewed_at
        from intel.competitor_requests cr
        join core.tenants t on t.id = cr.tenant_id
        left join core.app_users u on u.id = cr.requested_by_user_id
        where cr.id = %s
        """,
        (request_id,),
    )
    return _row(cur.fetchone())


def _admin_tenant_row(cur, tenant_id: str) -> dict[str, Any]:
    cur.execute(
        """
        select t.id, t.name, t.slug, sp.contact_email, sp.phone, sp.onboarding_status,
               count(distinct v.id) as sku_count,
               count(distinct tc.shop_code) filter (where tc.is_active) as competitor_count,
               t.created_at
        from core.tenants t
        left join core.shop_profiles sp on sp.tenant_id = t.id
        left join core.sku_variants v on v.tenant_id = t.id and v.status = 'active'
        left join intel.tenant_competitors tc on tc.tenant_id = t.id
        where t.id = %s
        group by t.id, sp.tenant_id
        """,
        (tenant_id,),
    )
    return _row(cur.fetchone())


def _resolve_request_notifications(cur, request_id: str) -> None:
    cur.execute(
        """
        update core.notifications
        set status = 'resolved', read_at = coalesce(read_at, now()), resolved_at = now()
        where recipient_role = 'admin' and status <> 'resolved'
          and payload->>'competitor_request_id' = %s
        """,
        (str(request_id),),
    )


def _unique_shop_code(cur, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (name or "competitor").lower()).strip("_") or "competitor"
    base = base[:48]
    for index in range(0, 100):
        code = base if index == 0 else f"{base}_{index + 1}"
        cur.execute("select 1 from intel.shops where shop_code = %s", (code,))
        if not cur.fetchone():
            return code
    return f"{base}_{secrets.token_hex(3)}"


def token_from_authorization(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _ensure_auth_tables(conn) -> None:
    global _AUTH_TABLES_READY
    if _AUTH_TABLES_READY:
        return
    if os.environ.get("AUTH_ENSURE_RUNTIME_SCHEMA", "false").lower() not in {"1", "true", "yes"}:
        _AUTH_TABLES_READY = True
        return
    with _AUTH_TABLES_LOCK:
        if _AUTH_TABLES_READY:
            return
        with conn.cursor() as cur:
            cur.execute(
                """
                create extension if not exists pgcrypto;
                create schema if not exists core;
                create schema if not exists intel;

                create table if not exists core.app_users (
                    id uuid primary key default gen_random_uuid(),
                    email text not null,
                    password_hash text not null,
                    full_name text not null,
                    global_role text not null default 'shop' check (global_role in ('admin', 'shop')),
                    is_active boolean not null default true,
                    email_verified boolean not null default false,
                    last_login_at timestamptz,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                );

                alter table core.app_users
                    add column if not exists password_hash text,
                    add column if not exists full_name text,
                    add column if not exists global_role text not null default 'shop',
                    add column if not exists is_active boolean not null default true,
                    add column if not exists email_verified boolean not null default false,
                    add column if not exists last_login_at timestamptz,
                    add column if not exists created_at timestamptz not null default now(),
                    add column if not exists updated_at timestamptz not null default now();

                create unique index if not exists ux_app_users_email_lower
                    on core.app_users (lower(email));

                create table if not exists core.user_memberships (
                    id uuid primary key default gen_random_uuid(),
                    user_id uuid not null references core.app_users(id) on delete cascade,
                    tenant_id uuid not null references core.tenants(id) on delete cascade,
                    role text not null default 'owner' check (role in ('owner', 'manager', 'staff')),
                    is_active boolean not null default true,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now(),
                    unique (user_id, tenant_id)
                );

                alter table core.user_memberships
                    add column if not exists role text not null default 'owner',
                    add column if not exists is_active boolean not null default true,
                    add column if not exists created_at timestamptz not null default now(),
                    add column if not exists updated_at timestamptz not null default now();

                create index if not exists idx_user_memberships_tenant
                    on core.user_memberships (tenant_id, is_active);

                create table if not exists core.shop_profiles (
                    tenant_id uuid primary key references core.tenants(id) on delete cascade,
                    owner_user_id uuid references core.app_users(id) on delete set null,
                    business_name text not null,
                    legal_name text,
                    contact_email text,
                    phone text,
                    website_url text,
                    address text,
                    country text not null default 'Lebanon',
                    timezone text not null default 'Asia/Beirut',
                    onboarding_status text not null default 'pending' check (
                        onboarding_status in ('pending', 'active', 'suspended', 'archived')
                    ),
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                );

                alter table core.shop_profiles
                    add column if not exists owner_user_id uuid references core.app_users(id) on delete set null,
                    add column if not exists business_name text,
                    add column if not exists legal_name text,
                    add column if not exists contact_email text,
                    add column if not exists phone text,
                    add column if not exists website_url text,
                    add column if not exists address text,
                    add column if not exists country text not null default 'Lebanon',
                    add column if not exists timezone text not null default 'Asia/Beirut',
                    add column if not exists onboarding_status text not null default 'pending',
                    add column if not exists created_at timestamptz not null default now(),
                    add column if not exists updated_at timestamptz not null default now();

                create table if not exists core.auth_sessions (
                    id uuid primary key default gen_random_uuid(),
                    user_id uuid not null references core.app_users(id) on delete cascade,
                    token_hash text not null unique,
                    expires_at timestamptz not null,
                    revoked_at timestamptz,
                    user_agent text,
                    ip_address text,
                    created_at timestamptz not null default now()
                );

                alter table core.auth_sessions
                    add column if not exists token_hash text,
                    add column if not exists expires_at timestamptz,
                    add column if not exists revoked_at timestamptz,
                    add column if not exists user_agent text,
                    add column if not exists ip_address text,
                    add column if not exists created_at timestamptz not null default now();

                create index if not exists idx_auth_sessions_user_active
                    on core.auth_sessions (user_id, expires_at)
                    where revoked_at is null;

                create table if not exists core.notifications (
                    id uuid primary key default gen_random_uuid(),
                    recipient_role text not null check (recipient_role in ('admin', 'shop')),
                    recipient_user_id uuid references core.app_users(id) on delete cascade,
                    tenant_id uuid references core.tenants(id) on delete cascade,
                    actor_user_id uuid references core.app_users(id) on delete set null,
                    type text not null,
                    title text not null,
                    message text not null,
                    payload jsonb not null default '{}'::jsonb,
                    status text not null default 'unread' check (status in ('unread', 'read', 'resolved', 'dismissed')),
                    priority text not null default 'normal' check (priority in ('low', 'normal', 'high', 'urgent')),
                    created_at timestamptz not null default now(),
                    read_at timestamptz,
                    resolved_at timestamptz
                );

                alter table core.notifications
                    add column if not exists recipient_role text not null default 'admin',
                    add column if not exists recipient_user_id uuid references core.app_users(id) on delete cascade,
                    add column if not exists tenant_id uuid references core.tenants(id) on delete cascade,
                    add column if not exists actor_user_id uuid references core.app_users(id) on delete set null,
                    add column if not exists type text,
                    add column if not exists title text,
                    add column if not exists message text,
                    add column if not exists payload jsonb not null default '{}'::jsonb,
                    add column if not exists status text not null default 'unread',
                    add column if not exists priority text not null default 'normal',
                    add column if not exists created_at timestamptz not null default now(),
                    add column if not exists read_at timestamptz,
                    add column if not exists resolved_at timestamptz;

                create index if not exists idx_notifications_admin_status
                    on core.notifications (recipient_role, status, created_at desc);

                create index if not exists idx_notifications_tenant_status
                    on core.notifications (tenant_id, status, created_at desc);

                create table if not exists intel.shops (
                    shop_code text primary key,
                    shop_name text not null
                );

                alter table intel.shops
                    add column if not exists is_active boolean not null default true,
                    add column if not exists expected_frequency text not null default 'daily',
                    add column if not exists created_at timestamptz not null default now(),
                    add column if not exists updated_at timestamptz not null default now();

                create table if not exists intel.tenant_competitors (
                    tenant_id uuid not null references core.tenants(id) on delete cascade,
                    shop_code text not null references intel.shops(shop_code) on delete restrict,
                    is_active boolean not null default true,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now(),
                    primary key (tenant_id, shop_code)
                );

                alter table intel.tenant_competitors
                    add column if not exists is_active boolean not null default true,
                    add column if not exists created_at timestamptz not null default now(),
                    add column if not exists updated_at timestamptz not null default now();

                create index if not exists idx_tenant_competitors_active
                    on intel.tenant_competitors (tenant_id, is_active);

                create table if not exists intel.competitor_requests (
                    id uuid primary key default gen_random_uuid(),
                    tenant_id uuid not null references core.tenants(id) on delete cascade,
                    requested_by_user_id uuid references core.app_users(id) on delete set null,
                    competitor_name text not null,
                    website_url text,
                    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'onboarded')),
                    admin_notes text,
                    created_at timestamptz not null default now(),
                    reviewed_at timestamptz,
                    reviewed_by_user_id uuid references core.app_users(id) on delete set null
                );

                alter table intel.competitor_requests
                    add column if not exists requested_by_user_id uuid references core.app_users(id) on delete set null,
                    add column if not exists website_url text,
                    add column if not exists status text not null default 'pending',
                    add column if not exists admin_notes text,
                    add column if not exists created_at timestamptz not null default now(),
                    add column if not exists reviewed_at timestamptz,
                    add column if not exists reviewed_by_user_id uuid references core.app_users(id) on delete set null;

                create index if not exists idx_competitor_requests_status
                    on intel.competitor_requests (status, created_at desc);

                create index if not exists idx_competitor_requests_tenant
                    on intel.competitor_requests (tenant_id, created_at desc);
                """
            )
        conn.commit()
        _AUTH_TABLES_READY = True


def _primary_auth_context(cur, user: dict[str, Any]) -> AuthContext:
    cur.execute(
        """
        select m.tenant_id, m.role as member_role, t.slug as tenant_slug, t.name as tenant_name
        from core.user_memberships m
        join core.tenants t on t.id = m.tenant_id
        where m.user_id = %s and m.is_active = true
        order by m.created_at asc
        limit 1
        """,
        (user["id"],),
    )
    membership = cur.fetchone()
    return AuthContext(
        user_id=str(user["id"]),
        email=user["email"],
        full_name=user["full_name"],
        global_role=user["global_role"],
        tenant_id=str(membership["tenant_id"]) if membership else None,
        tenant_slug=membership["tenant_slug"] if membership else None,
        tenant_name=membership["tenant_name"] if membership else None,
        member_role=membership["member_role"] if membership else None,
    )


def _profile_row(cur, tenant_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select sp.tenant_id, t.slug as tenant_slug, sp.business_name, sp.legal_name,
               sp.contact_email, sp.phone, sp.website_url, sp.address, sp.country,
               sp.timezone, sp.onboarding_status, sp.created_at, sp.updated_at
        from core.shop_profiles sp
        join core.tenants t on t.id = sp.tenant_id
        where sp.tenant_id = %s
        """,
        (tenant_id,),
    )
    profile = cur.fetchone()
    if not profile:
        return None
    cur.execute(
        """
        select s.shop_code, s.shop_name
        from intel.tenant_competitors tc
        join intel.shops s on s.shop_code = tc.shop_code
        where tc.tenant_id = %s and tc.is_active = true
        order by s.shop_name
        """,
        (tenant_id,),
    )
    competitors = [_row(row) for row in cur.fetchall()]
    cur.execute(
        """
        select id, competitor_name, website_url, status, admin_notes, created_at, reviewed_at
        from intel.competitor_requests
        where tenant_id = %s
        order by created_at desc
        limit 100
        """,
        (tenant_id,),
    )
    requests = [_row(row) for row in cur.fetchall()]
    return {**_row(profile), "selected_competitors": competitors, "competitor_requests": requests}


def _replace_tenant_competitors(cur, tenant_id: Any, selected_codes: list[str]) -> None:
    cur.execute("update intel.tenant_competitors set is_active = false, updated_at = now() where tenant_id = %s", (tenant_id,))
    if not selected_codes:
        return
    cur.execute("select shop_code from intel.shops where is_active = true and shop_code = any(%s)", (selected_codes,))
    valid_codes = [row["shop_code"] for row in cur.fetchall()]
    for code in valid_codes:
        cur.execute(
            """
            insert into intel.tenant_competitors (tenant_id, shop_code, is_active)
            values (%s, %s, true)
            on conflict (tenant_id, shop_code) do update set
                is_active = true,
                updated_at = now()
            """,
            (tenant_id, code),
        )


def _insert_competitor_requests(cur, tenant_id: Any, user_id: Any, requested_names: list[str]) -> None:
    cur.execute("select name from core.tenants where id = %s", (tenant_id,))
    tenant = cur.fetchone() or {}
    shop_name = tenant.get("name") or "Shop"
    for name in requested_names:
        cur.execute(
            """
            insert into intel.competitor_requests (tenant_id, requested_by_user_id, competitor_name)
            values (%s, %s, %s)
            returning id, competitor_name
            """,
            (tenant_id, user_id, name),
        )
        request_row = cur.fetchone()
        _insert_notification(
            cur,
            recipient_role="admin",
            notification_type="competitor_request",
            title=f"New competitor request from {shop_name}",
            message=f"{shop_name} requested competitor: {request_row['competitor_name']}",
            tenant_id=tenant_id,
            actor_user_id=user_id,
            priority="normal",
            payload={
                "competitor_request_id": str(request_row["id"]),
                "competitor_name": request_row["competitor_name"],
            },
        )


def _insert_notification(
    cur,
    *,
    recipient_role: str,
    notification_type: str,
    title: str,
    message: str,
    tenant_id: Any | None = None,
    recipient_user_id: Any | None = None,
    actor_user_id: Any | None = None,
    priority: str = "normal",
    payload: dict[str, Any] | None = None,
) -> None:
    cur.execute(
        """
        insert into core.notifications (
            recipient_role, recipient_user_id, tenant_id, actor_user_id,
            type, title, message, payload, priority
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
        """,
        (
            recipient_role,
            recipient_user_id,
            tenant_id,
            actor_user_id,
            notification_type,
            title,
            message,
            json.dumps(_jsonable(payload or {})),
            priority,
        ),
    )


def _unique_tenant_slug(cur, name: str) -> str:
    base = _slugify(name) or "shop"
    for index in range(0, 100):
        slug = base if index == 0 else f"{base}-{index + 1}"
        cur.execute("select 1 from core.tenants where slug = %s", (slug,))
        if not cur.fetchone():
            return slug
    return f"{base}-{secrets.token_hex(4)}"


def _hash_password(password: str) -> str:
    iterations = 240_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        _b64(salt),
        _b64(digest),
    )


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, raw_iterations, raw_salt, raw_digest = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        salt = _unb64(raw_salt)
        expected = _unb64(raw_digest)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _make_token(ctx: AuthContext, extra_claims: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    ttl = int(os.environ.get("AUTH_TOKEN_TTL_HOURS", "12"))
    payload = {
        "sub": ctx.user_id,
        "email": ctx.email,
        "role": ctx.global_role,
        "tenant_id": ctx.tenant_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl)).timestamp()),
        "nonce": secrets.token_hex(12),
    }
    if extra_claims:
        payload.update(extra_claims)
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(body)
    return f"{body}.{signature}"


def decode_token_claims(token: str) -> dict[str, Any]:
    """Validate signature + expiry and return the raw JWT-style claims (no DB hit)."""
    return _decode_token(token)


def _decode_token(token: str) -> dict[str, Any]:
    body, separator, signature = token.partition(".")
    if not separator or not hmac.compare_digest(_sign(body), signature):
        raise AuthError("Invalid token.")
    try:
        payload = json.loads(_unb64(body).decode("utf-8"))
    except Exception as exc:
        raise AuthError("Invalid token payload.") from exc
    if int(payload.get("exp") or 0) <= int(datetime.now(timezone.utc).timestamp()):
        raise AuthError("Token expired.")
    return payload


def _store_session(cur, user_id: Any, token: str, user_agent: str | None, ip_address: str | None) -> None:
    payload = _decode_token(token)
    expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    cur.execute(
        """
        insert into core.auth_sessions (user_id, token_hash, expires_at, user_agent, ip_address)
        values (%s, %s, %s, %s, %s)
        """,
        (user_id, _token_hash(token), expires_at, user_agent, ip_address),
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign(value: str) -> str:
    secret = os.environ.get("AUTH_TOKEN_SECRET") or os.environ.get("WEBHOOK_SECRET") or "retail-radar-local-dev-secret"
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return _b64(digest)


def _require_tenant_id(ctx: AuthContext) -> str:
    if ctx.global_role != "shop" or not ctx.tenant_id:
        raise AuthError("This endpoint requires a shop account.")
    return ctx.tenant_id


def _require_admin(ctx: AuthContext) -> None:
    if ctx.global_role != "admin":
        raise AuthError("Admin access is required.")


def _normalize_email(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "@" not in text or "." not in text.rsplit("@", 1)[-1]:
        raise ValueError("valid email is required")
    return text


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-+", "-", slug)[:80]


def _row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _jsonable(value) for key, value in row.items()}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# ── Admin Social Account Management ──────────────────────────────────────────


def admin_list_social_accounts(ctx: AuthContext, tenant_id: str) -> list[dict[str, Any]]:
    """Return all social accounts for a tenant (admin only).

    Tokens are masked for display — only the first/last 6 chars are shown.
    """
    _require_admin(ctx)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select platform, account_name, page_id, user_id,
                       is_active, webhook_registered_at, created_at,
                       left(access_token, 6) || '…' || right(access_token, 6) as token_preview
                from marketing.tenant_social_accounts
                where tenant_id = %s
                order by platform
                """,
                (tenant_id,),
            )
            return [_row(r) for r in cur.fetchall()]


def admin_upsert_social_account(
    ctx: AuthContext,
    tenant_id: str,
    platform: str,
    access_token: str,
    page_id: str | None = None,
    user_id: str | None = None,
    account_name: str | None = None,
    webhook_registered_at: Any = None,
) -> dict[str, Any]:
    """Insert or update a social account credential for a tenant (admin only).

    Uses ON CONFLICT upsert so re-saving a token is safe.
    Returns the saved row (with masked token).
    """
    _require_admin(ctx)
    allowed = {"facebook", "instagram", "tiktok", "telegram"}
    if platform not in allowed:
        raise ValueError(f"platform must be one of {allowed}")
    if not access_token or not access_token.strip():
        raise ValueError("access_token must not be empty")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into marketing.tenant_social_accounts
                    (tenant_id, platform, access_token, page_id, user_id,
                     account_name, is_active, webhook_registered_at)
                values (%s, %s, %s, %s, %s, %s, true, %s)
                on conflict (tenant_id, platform) do update
                set access_token          = excluded.access_token,
                    page_id               = excluded.page_id,
                    user_id               = excluded.user_id,
                    account_name          = excluded.account_name,
                    is_active             = true,
                    webhook_registered_at = excluded.webhook_registered_at
                returning platform, account_name, page_id, user_id,
                          is_active, webhook_registered_at, created_at,
                          left(access_token, 6) || '…' || right(access_token, 6) as token_preview
                """,
                (
                    tenant_id, platform, access_token.strip(),
                    page_id or None, user_id or None, account_name or None,
                    webhook_registered_at,
                ),
            )
            return _row(cur.fetchone())


def admin_remove_social_account(
    ctx: AuthContext, tenant_id: str, platform: str
) -> None:
    """Deactivate (soft-delete) a social account for a tenant (admin only)."""
    _require_admin(ctx)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update marketing.tenant_social_accounts
                set is_active = false
                where tenant_id = %s and platform = %s
                """,
                (tenant_id, platform),
            )


def get_tenants_with_telegram_credentials() -> list[dict[str, Any]]:
    """Return all tenants that have an active Telegram bot token AND a registered chat.

    Used by alert_dispatcher to route notifications to the right bot + chat.
    Returns rows with: tenant_id, bot_token, chat_id.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select tsa.tenant_id::text,
                       tsa.access_token   as bot_token,
                       tc.chat_id
                from marketing.tenant_social_accounts tsa
                join telegram.conversations tc on tc.tenant_id = tsa.tenant_id
                where tsa.platform = 'telegram'
                  and tsa.is_active = true
                  and tc.is_active  = true
                order by tsa.tenant_id
                """
            )
            return [_row(r) for r in cur.fetchall()]
