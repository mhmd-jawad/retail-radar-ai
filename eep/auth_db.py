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
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
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
    for name in requested_names:
        cur.execute(
            """
            insert into intel.competitor_requests (tenant_id, requested_by_user_id, competitor_name)
            values (%s, %s, %s)
            """,
            (tenant_id, user_id, name),
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


def _make_token(ctx: AuthContext) -> str:
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
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(body)
    return f"{body}.{signature}"


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
    if not ctx.tenant_id:
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
