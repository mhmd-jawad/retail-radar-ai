"""
EEP â€” Executive Experience Platform.

Frontend-facing API that exposes:
  - the transformed analytics report used by the dashboard
  - scrape/competitor operations data from local outputs
  - recommendation endpoints that adapt the existing IE2 service contract

Run:
    uvicorn eep.main:app --port 8000 --reload
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from zoneinfo import ZoneInfo

# Load .env from repo root (no-op if file absent or dotenv not installed)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:
    pass

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import errors as psycopg_errors

from eep.auth_db import (
    AuthContext,
    AuthError,
    LoginPayload,
    ShopProfileUpdatePayload,
    ShopSignupPayload,
    admin_list_competitors,
    admin_list_competitor_requests,
    admin_list_notifications,
    admin_list_tenants,
    admin_impersonate_shop,
    admin_list_social_accounts,
    admin_upsert_social_account,
    admin_remove_social_account,
    admin_review_competitor_request,
    admin_update_shop_status,
    authenticate_token,
    decode_token_claims,
    ensure_default_admin_account,
    get_shop_profile,
    list_available_competitors,
    list_shop_notifications,
    login,
    logout,
    signup_shop,
    token_from_authorization,
    update_notification_status,
    update_shop_profile,
)
from eep.apify_ingest import (
    apify_token,
    extract_actor_run_id,
    sync_apify_run_to_retail_core,
)
from eep.frontend_bridge import (
    build_competitor_latest,
    build_frontend_report,
    build_scrape_runs,
    report_overview,
    serialize_frontend_recommendation,
)
from services.common.price_normalization import effective_competitor_price_usd
from eep.observability import (
    configure_metrics,
    observe_competitor_match,
    observe_recommendation,
    observe_scraper_ingest,
)
from typing import Literal

from pydantic import Field as PField

from eep.retail_db import (
    DatabaseUnavailable,
    InventoryImportPayload,
    InventoryItemPayload,
    InventoryMovementPayload,
    _connect,
    _context,
    archive_inventory_item,
    create_inventory_item,
    create_system_decision_run,
    db_status,
    fail_stale_system_decision_runs,
    get_active_system_decision_run,
    get_system_decision_run,
    get_variant_id_for_sku,
    import_inventory,
    list_active_inventory_sku_ids,
    list_inventory_items,
    list_system_decision_latest,
    list_tenant_ids,
    list_unsynced_inventory_sku_ids,
    mark_system_decisions_syncing,
    patch_inventory_price,
    record_inventory_movement,
    record_retailer_decision,
    system_decision_run_exists_today,
    update_system_decision_run,
    upsert_system_decision_error,
    upsert_system_decision_success,
    update_inventory_item,
    get_financial_profile,
    upsert_financial_profile,
    get_financial_line_items,
    upsert_financial_line_item,
    delete_financial_line_item,
)
from pydantic import BaseModel


class PriceDecisionPayload(BaseModel):
    retail_price_usd: float = PField(gt=0)
    decision_type: Literal["clearance", "markdown", "hold"]
    notes: str | None = None
    recommendation_id: str | None = None
    cost_price_usd: float = 0.0


class RetailerDecisionPayload(BaseModel):
    sku_id: str
    decision_type: Literal["clearance", "markdown", "hold", "promote"]
    notes: str | None = None
    recommendation_id: str | None = None
    cost_price_usd: float = 0.0


class OutcomeMeasurePayload(BaseModel):
    window_days: Literal[7, 14] = 7


class NotificationStatusPayload(BaseModel):
    status: Literal["unread", "read", "resolved", "dismissed"]


class CompetitorRequestReviewPayload(BaseModel):
    action: Literal["approve", "reject"]
    admin_notes: str | None = None


class ShopStatusPayload(BaseModel):
    onboarding_status: Literal["pending", "active", "suspended", "archived"]


class RecommendationReviewPayload(BaseModel):
    """Human validation of a system recommendation."""

    action: Literal["accept", "override", "reject"]
    final_decision: Literal["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"] | None = None
    final_price_usd: float | None = PField(default=None, gt=0)
    final_discount_pct: float | None = PField(default=None, ge=0, le=100)
    note: str | None = PField(default=None, max_length=2000)
    recommendation_id: str | None = None


class RecommendationReviewUpdatePayload(BaseModel):
    action: Literal["accept", "override", "reject"] | None = None
    final_decision: Literal["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"] | None = None
    final_price_usd: float | None = PField(default=None, gt=0)
    final_discount_pct: float | None = PField(default=None, ge=0, le=100)
    note: str | None = PField(default=None, max_length=2000)


app = FastAPI(
    title="StylePulse AI â€” EEP Executive Platform",
    description="Unified dashboard API for the Retail Radar frontend.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)
configure_metrics(app)


_READONLY_ALLOWED_PREFIXES = ("/auth/logout",)
_SYSTEM_DECISION_SCHEDULER_STARTED = False
_SYSTEM_DECISION_SCHEDULER_LOCK = threading.Lock()
_REPORT_LIVE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SYSTEM_DECISION_LATEST_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_READ_CACHE_LOCK = threading.Lock()

SYSTEM_DECISION_DAILY_TRIGGER = "daily_7am"
SYSTEM_DECISION_MANUAL_ALL_TRIGGER = "manual_all"
SYSTEM_DECISION_MANUAL_UNSYNCED_TRIGGER = "manual_unsynced"
SYSTEM_DECISION_NEW_SKU_TRIGGER = "new_sku"


def _clear_read_caches(tenant_id: str | None = None) -> None:
    with _READ_CACHE_LOCK:
        if tenant_id:
            _REPORT_LIVE_CACHE.pop(str(tenant_id), None)
            _SYSTEM_DECISION_LATEST_CACHE.pop(str(tenant_id), None)
        else:
            _REPORT_LIVE_CACHE.clear()
            _SYSTEM_DECISION_LATEST_CACHE.clear()


@app.middleware("http")
async def _readonly_impersonation_guard(request: Request, call_next):
    """Block writes for read-only impersonation sessions (admin 'view as shop')."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        token = token_from_authorization(request.headers.get("authorization"))
        if token:
            try:
                claims = decode_token_claims(token)
            except Exception:
                claims = None
            if claims and claims.get("read_only"):
                path = request.url.path
                if not any(path.startswith(prefix) for prefix in _READONLY_ALLOWED_PREFIXES):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Read-only impersonation session â€” changes are disabled."},
                    )
    return await call_next(request)


@app.on_event("startup")
def _startup_accounts() -> None:
    try:
        ensure_default_admin_account()
    except Exception as exc:
        print(f"Admin account bootstrap skipped: {exc}")
    _reconcile_stale_system_decision_syncs()
    _start_system_decision_scheduler()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "eep",
    }


@app.post("/auth/login")
def auth_login(payload: LoginPayload, request: Request) -> dict[str, Any]:
    try:
        return login(payload, user_agent=request.headers.get("user-agent"), ip_address=_client_ip(request))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/auth/signup-shop")
def auth_signup_shop(payload: ShopSignupPayload, request: Request) -> dict[str, Any]:
    try:
        return signup_shop(payload, user_agent=request.headers.get("user-agent"), ip_address=_client_ip(request))
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    try:
        return _required_auth(request).model_dump()
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/auth/logout")
def auth_logout(request: Request) -> dict[str, Any]:
    token = _bearer_or_401(request)
    try:
        return logout(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/auth/competitors")
def auth_competitors() -> list[dict[str, Any]]:
    try:
        return list_available_competitors()
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/shop/profile")
def shop_profile(request: Request) -> dict[str, Any]:
    try:
        return get_shop_profile(_required_shop(request))
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.put("/shop/profile")
def shop_profile_update(payload: ShopProfileUpdatePayload, request: Request) -> dict[str, Any]:
    try:
        return update_shop_profile(_required_shop(request), payload)
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/shop/financial-profile")
def shop_financial_profile(request: Request) -> dict[str, Any]:
    try:
        return get_financial_profile(_required_shop(request))
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class FinancialProfilePayload(BaseModel):
    total_assets_usd: float | None = None
    total_liabilities_usd: float | None = None
    monthly_fixed_opex_usd: float | None = None
    annual_revenue_projected_usd: float | None = None
    cash_runway_months: float | None = None
    breakeven_monthly_revenue_usd: float | None = None


@app.put("/shop/financial-profile")
def shop_financial_profile_update(payload: FinancialProfilePayload, request: Request) -> dict[str, Any]:
    try:
        return upsert_financial_profile(_required_shop(request), payload.model_dump(exclude_unset=False))
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/shop/financial-items")
def shop_financial_items(request: Request) -> list[dict[str, Any]]:
    try:
        return get_financial_line_items(_required_shop(request))
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class FinancialLineItemPayload(BaseModel):
    label: str
    amount_usd: float
    item_type: str
    sort_order: int = 0


@app.post("/shop/financial-items")
def shop_financial_item_create(payload: FinancialLineItemPayload, request: Request) -> dict[str, Any]:
    try:
        return upsert_financial_line_item(
            _required_shop(request), None,
            payload.label, payload.amount_usd, payload.item_type, payload.sort_order,
        )
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.put("/shop/financial-items/{item_id}")
def shop_financial_item_update(item_id: str, payload: FinancialLineItemPayload, request: Request) -> dict[str, Any]:
    try:
        return upsert_financial_line_item(
            _required_shop(request), item_id,
            payload.label, payload.amount_usd, payload.item_type, payload.sort_order,
        )
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/shop/financial-items/{item_id}")
def shop_financial_item_delete(item_id: str, request: Request) -> dict[str, Any]:
    try:
        deleted = delete_financial_line_item(_required_shop(request), item_id)
        return {"deleted": deleted}
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/shop/notifications")
def shop_notifications(
    request: Request,
    status: str | None = Query(default=None, pattern="^(unread|read|resolved|dismissed)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    try:
        return list_shop_notifications(_required_shop(request), status=status, limit=limit)
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.patch("/shop/notifications/{notification_id}")
def shop_notification_update(notification_id: str, payload: NotificationStatusPayload, request: Request) -> dict[str, Any]:
    try:
        return update_notification_status(_required_shop(request), notification_id, payload.status)
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/admin/tenants")
def admin_tenants(request: Request) -> list[dict[str, Any]]:
    try:
        return admin_list_tenants(_required_admin(request))
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/admin/competitor-requests")
def admin_competitor_requests(
    request: Request,
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected|onboarded)$"),
) -> list[dict[str, Any]]:
    try:
        return admin_list_competitor_requests(_required_admin(request), status=status)
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/admin/notifications")
def admin_notifications(
    request: Request,
    status: str | None = Query(default=None, pattern="^(unread|read|resolved|dismissed)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    try:
        return admin_list_notifications(_required_admin(request), status=status, limit=limit)
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.patch("/admin/notifications/{notification_id}")
def admin_notification_update(notification_id: str, payload: NotificationStatusPayload, request: Request) -> dict[str, Any]:
    try:
        return update_notification_status(_required_admin(request), notification_id, payload.status)
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/admin/competitors")
def admin_competitors(request: Request) -> list[dict[str, Any]]:
    try:
        return admin_list_competitors(_required_admin(request))
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.patch("/admin/competitor-requests/{request_id}")
def admin_competitor_request_review(
    request_id: str,
    payload: CompetitorRequestReviewPayload,
    request: Request,
) -> dict[str, Any]:
    ctx = _required_admin(request)
    try:
        return admin_review_competitor_request(ctx, request_id, payload.action, payload.admin_notes)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.patch("/admin/shops/{tenant_id}")
def admin_shop_status_update(
    tenant_id: str,
    payload: ShopStatusPayload,
    request: Request,
) -> dict[str, Any]:
    ctx = _required_admin(request)
    try:
        return admin_update_shop_status(ctx, tenant_id, payload.onboarding_status)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/admin/impersonate/{tenant_id}")
def admin_impersonate(tenant_id: str, request: Request) -> dict[str, Any]:
    ctx = _required_admin(request)
    try:
        return admin_impersonate_shop(ctx, tenant_id)
    except AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# â”€â”€â”€ Admin Platform Operations Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class AdminTriggerMeasurementPayload(BaseModel):
    snapshot_id: int
    window_days: Literal[7, 14] = 7


class CampaignPersistPayload(BaseModel):
    variant_id: str | None = None
    recommendation_id: str | None = None
    channel: str
    headline: str
    body: str = ""
    tone: str | None = None
    generation_confidence: float | None = None
    fallback_used: bool = False


class AdminAssistantPayload(BaseModel):
    message: str
    session_id: str | None = None


class RetailerChatPayload(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/admin/outcomes/aggregate")
def admin_outcomes_aggregate(request: Request) -> dict[str, Any]:
    """Cross-tenant model accuracy and outcome measurement aggregate."""
    _required_admin(request)
    try:
        from eep.admin_analytics_db import get_outcomes_aggregate
        return get_outcomes_aggregate()
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/admin/outcomes/trigger")
def admin_outcomes_trigger(payload: AdminTriggerMeasurementPayload, request: Request) -> dict[str, Any]:
    """Admin triggers a 7d/14d measurement for any tenant's snapshot."""
    _required_admin(request)
    try:
        from eep.admin_analytics_db import admin_trigger_measurement
        return admin_trigger_measurement(payload.snapshot_id, payload.window_days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc



@app.get("/admin/campaigns/overview")
def admin_campaigns_overview(request: Request) -> dict[str, Any]:
    """Cross-tenant campaign activity summary."""
    _required_admin(request)
    try:
        from eep.admin_analytics_db import get_campaigns_overview
        return get_campaigns_overview()
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/campaigns")
def persist_campaign_route(payload: CampaignPersistPayload, request: Request) -> dict[str, Any]:
    """Shop persists a generated campaign after IE3 returns successfully."""
    ctx = _required_shop(request)
    try:
        from eep.admin_analytics_db import persist_campaign
        return persist_campaign(
            tenant_id=ctx.tenant_id,
            variant_id=payload.variant_id,
            recommendation_id=payload.recommendation_id,
            channel=payload.channel,
            headline=payload.headline,
            body=payload.body,
            tone=payload.tone,
            generation_confidence=payload.generation_confidence,
            fallback_used=payload.fallback_used,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/admin/assistant/chat")
async def admin_assistant_chat(payload: AdminAssistantPayload, request: Request) -> dict[str, Any]:
    """
    Platform-level AI assistant for admin operations.
    Uses Claude with tool use to answer cross-tenant questions.
    """
    _required_admin(request)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured.")

    try:
        from eep.admin_analytics_db import (
            get_admin_assistant_context,
            get_outcomes_aggregate,
            get_campaigns_overview,
        )
        from eep.auth_db import admin_list_tenants, admin_list_competitor_requests
        import anthropic as _anthropic

        client = _anthropic.Anthropic(api_key=anthropic_key)

        ctx_summary = get_admin_assistant_context()
        system_prompt = (
            "You are the Platform Intelligence Assistant for Retail Radar AI, "
            "an AI-powered retail analytics platform. You are speaking with a platform admin (operations manager). "
            "You have access to real-time cross-tenant data. "
            f"Current platform snapshot: {ctx_summary['tenant_count']} active shops, "
            f"{ctx_summary['pending_competitor_requests']} pending competitor requests, "
            f"{ctx_summary['pending_outcome_measurements']} outcome measurements due, "
            "Answer concisely and accurately. Use tools to fetch live data before answering data questions."
        )

        tools = [
            {
                "name": "get_platform_outcomes",
                "description": "Get cross-tenant recommendation accuracy, pending measurements, revenue impact, and accuracy trend.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_campaigns_activity",
                "description": "Get campaign generation activity across all shops â€” volumes, channels, fallback rate, recent campaigns.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "list_tenants",
                "description": "List all registered shops with their onboarding status, SKU count, and competitor count.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Filter by status: pending, active, suspended, archived",
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "get_pending_items",
                "description": "Get all pending competitor requests and unread admin notifications.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]

        from eep.auth_db import AuthContext as _AuthContext, _require_admin as _db_require_admin
        _fake_admin_ctx = type("C", (), {"global_role": "admin", "tenant_id": None, "user_id": "admin"})()

        messages = [{"role": "user", "content": payload.message}]

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        tools_used: list[str] = []

        while response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tools_used.append(block.name)
                try:
                    if block.name == "get_platform_outcomes":
                        data = get_outcomes_aggregate()
                    elif block.name == "get_campaigns_activity":
                        data = get_campaigns_overview()
                    elif block.name == "list_tenants":
                        import eep.auth_db as _adb
                        class _FakeCtx:
                            global_role = "admin"
                            tenant_id = None
                        data = _adb.admin_list_tenants(_FakeCtx())
                    elif block.name == "get_pending_items":
                        import eep.auth_db as _adb
                        class _FakeCtx:
                            global_role = "admin"
                            tenant_id = None
                        pending_requests = _adb.admin_list_competitor_requests(_FakeCtx(), status="pending")
                        pending_notifications = _adb.admin_list_notifications(_FakeCtx(), status="unread", limit=20)
                        data = {"pending_requests": pending_requests, "unread_notifications": pending_notifications}
                    else:
                        data = {"error": f"Unknown tool: {block.name}"}
                except Exception as tool_exc:
                    data = {"error": str(tool_exc)}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(data, default=str),
                })

            messages = [
                {"role": "user", "content": payload.message},
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

        reply = ""
        for block in response.content:
            if hasattr(block, "text"):
                reply += block.text

        return {
            "reply": reply,
            "tools_used": list(dict.fromkeys(tools_used)),
            "session_id": payload.session_id or "",
        }

    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Assistant error: {exc}") from exc


@app.post("/chat")
async def retailer_assistant_chat(payload: RetailerChatPayload, request: Request) -> dict[str, Any]:
    """
    Retailer-facing AI assistant.

    Scoped to the authenticated retailer's tenant. Uses Claude with 14 live-data
    tools and persists every conversation turn to core.chat_sessions so history
    survives browser refreshes.
    """
    ctx = _required_shop(request)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured.")

    try:
        import anthropic as _anthropic
        from eep import chat_db, assistant_db
        from services.telegram_assistant.assistant_tools import TOOLS as RETAILER_TOOLS

        client = _anthropic.Anthropic(api_key=anthropic_key)

        # ── Session management ────────────────────────────────────────────────
        session_id = payload.session_id or ""
        if not session_id:
            import uuid as _uuid
            session_id = str(_uuid.uuid4())

        chat_db.get_or_create_session(session_id, str(ctx.tenant_id))
        history = chat_db.get_history(session_id, str(ctx.tenant_id))

        # ── System prompt — tenant-specific ───────────────────────────────────
        from datetime import date as _date
        competitors = assistant_db.get_competitor_list(str(ctx.tenant_id))
        competitor_str = ", ".join(competitors) if competitors else "none configured yet"

        system_prompt = (
            f"You are the Radar Intelligence Assistant for {ctx.tenant_name or 'this retailer'}. "
            "You are a senior retail analytics AI helping an Adidas single-brand retailer make "
            "data-driven decisions on inventory, pricing, promotions, and competitors. "
            f"Today is {_date.today().isoformat()}. "
            f"Competitors being tracked: {competitor_str}.\n\n"

            "TOOLS: You have 14 live-data tools. Always call the relevant tool(s) BEFORE answering "
            "any question about inventory, pricing, recommendations, competitors, or financials. "
            "Never answer data questions from memory — always fetch fresh data first.\n\n"

            "PROACTIVE BEHAVIOUR: When answering a question, use ALL tools that are relevant — "
            "not just the one most directly named. For example, when asked about recommendations, "
            "also check inventory levels and competitor prices to give richer context. "
            "When asked 'what should I focus on today?', call get_next_actions, get_stockout_days, "
            "and get_pending_recommendations together.\n\n"

            "GRACEFUL DEGRADATION — THIS IS CRITICAL: If one tool returns empty data, test data "
            "(SKU IDs containing 'TEST', 'DEMO', 'SYNTHETIC', or product names like 'Test Sneaker'), "
            "or zero values across the board, DO NOT stop there and refuse to help. Instead:\n"
            "  1. Briefly note the data gap in one sentence.\n"
            "  2. Immediately call the other tools that DO have data and present those insights.\n"
            "  3. Always give the retailer something actionable — never end with 'I cannot help'.\n"
            "  4. If recommendations are all test/empty, automatically run get_inventory_overview, "
            "     get_stockout_days, and get_competitor_prices and answer from those instead.\n\n"

            "FORMAT: Use *bold* for key numbers and product names. Use bullet points for lists. "
            "Keep answers focused and actionable — the retailer is busy. "
            "End every answer with a concrete next step or follow-up question. "
            "Respond in the same language the retailer uses (English or Arabic)."
        )

        # ── Build message list from persisted history + new message ───────────
        # History is stored as [{role, content, tools_used, ts}]; Claude API needs {role, content}
        claude_history = [
            {"role": m["role"], "content": m["content"]}
            for m in history
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        # Limit to last 20 turns to avoid hitting token limits
        claude_history = claude_history[-20:]
        messages: list[dict] = claude_history + [{"role": "user", "content": payload.message}]

        # ── Claude tool-use loop ──────────────────────────────────────────────
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=system_prompt,
            tools=RETAILER_TOOLS,
            messages=messages,
        )

        tools_used: list[str] = []
        tenant_id_str = str(ctx.tenant_id)

        while response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tools_used.append(block.name)
                inp = block.input or {}
                try:
                    if block.name == "get_inventory_overview":
                        data = assistant_db.get_inventory_overview(tenant_id_str)
                    elif block.name == "get_stockout_days":
                        data = assistant_db.get_stockout_days(tenant_id_str)
                    elif block.name == "get_reorder_suggestions":
                        data = assistant_db.get_reorder_suggestions(tenant_id_str)
                    elif block.name == "get_sku_velocity_trend":
                        data = assistant_db.get_sku_velocity_trend(
                            tenant_id_str, inp["sku_id"], inp.get("days", 30)
                        )
                    elif block.name == "get_category_performance":
                        data = assistant_db.get_category_performance(tenant_id_str, inp.get("days", 30))
                    elif block.name == "get_competitor_prices":
                        data = assistant_db.get_competitor_prices(
                            tenant_id_str,
                            sku_id=inp.get("sku_id"),
                            competitor_name=inp.get("competitor_name"),
                        )
                    elif block.name == "get_pending_recommendations":
                        data = assistant_db.get_pending_recommendations(tenant_id_str)
                    elif block.name == "approve_recommendation":
                        data = assistant_db.approve_recommendation(
                            tenant_id_str,
                            inp["recommendation_id"],
                            inp["sku_id"],
                            inp.get("modified_discount_pct"),
                        )
                    elif block.name == "reject_recommendation":
                        data = assistant_db.reject_recommendation(
                            tenant_id_str, inp["recommendation_id"], inp["sku_id"]
                        )
                    elif block.name == "get_decision_progress":
                        data = assistant_db.get_decision_progress(tenant_id_str)
                    elif block.name == "get_roadmap_summary":
                        data = assistant_db.get_roadmap_summary(tenant_id_str)
                    elif block.name == "get_recommendation_detail":
                        data = assistant_db.get_recommendation_detail(
                            tenant_id_str, str(inp["roadmap_id"])
                        )
                    elif block.name == "get_next_actions":
                        data = assistant_db.get_next_actions(tenant_id_str)
                    elif block.name == "get_financial_health":
                        data = assistant_db.get_financial_health(tenant_id_str)
                    else:
                        data = {"error": f"Unknown tool: {block.name}"}
                except Exception as tool_exc:
                    data = {"error": str(tool_exc)}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(data, default=str),
                })

            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=system_prompt,
                tools=RETAILER_TOOLS,
                messages=messages,
            )

        reply = ""
        for block in response.content:
            if hasattr(block, "text"):
                reply += block.text

        # ── Persist this turn to DB ───────────────────────────────────────────
        import datetime as _dt
        ts = _dt.datetime.utcnow().isoformat()
        chat_db.append_messages(
            session_id,
            tenant_id_str,
            [
                {"role": "user", "content": payload.message, "tools_used": [], "ts": ts},
                {"role": "assistant", "content": reply, "tools_used": list(dict.fromkeys(tools_used)), "ts": ts},
            ],
        )

        return {
            "reply": reply,
            "tools_used": list(dict.fromkeys(tools_used)),
            "session_id": session_id,
        }

    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Assistant error: {exc}") from exc


@app.get("/chat/history")
def retailer_chat_history(request: Request, session_id: str) -> dict[str, Any]:
    """
    Return persisted message history for a chat session.

    Used by the frontend on mount to reload a previous conversation.
    Only returns messages belonging to the authenticated retailer's tenant.
    """
    ctx = _required_shop(request)
    try:
        from eep import chat_db
        messages = chat_db.get_history(session_id, str(ctx.tenant_id))
        return {"messages": messages, "session_id": session_id}
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"History error: {exc}") from exc


@app.post("/webhooks/apify/run-succeeded")
@app.post("/apify/webhook")
async def apify_run_succeeded_webhook(
    request: Request,
    shop: str = Query(..., min_length=1, max_length=120),
) -> dict[str, Any]:
    _require_webhook_secret(request)
    token = apify_token()
    if not token:
        observe_scraper_ingest("configuration_error")
        raise HTTPException(status_code=503, detail="APIFY_TOKEN is not configured.")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object.")

    actor_run_id = extract_actor_run_id(payload)
    if not actor_run_id:
        observe_scraper_ingest("bad_request")
        raise HTTPException(status_code=400, detail="Webhook payload did not include an Apify actor run id.")

    try:
        result = await asyncio.to_thread(
            sync_apify_run_to_retail_core,
            shop=shop,
            actor_run_id=actor_run_id,
            token=token,
            raw_webhook_payload=payload,
        )
    except Exception as exc:
        observe_scraper_ingest("failure")
        raise HTTPException(status_code=502, detail=f"Apify ingest failed: {exc}") from exc

    observe_scraper_ingest("success")
    return {"ok": True, **result.to_dict()}


@app.post("/webhooks/apify/replay-run")
async def replay_apify_run(
    request: Request,
    shop: str = Query(..., min_length=1, max_length=120),
    run_id: str = Query(..., min_length=1, max_length=200),
) -> dict[str, Any]:
    _require_webhook_secret(request)
    token = apify_token()
    if not token:
        observe_scraper_ingest("configuration_error")
        raise HTTPException(status_code=503, detail="APIFY_TOKEN is not configured.")

    try:
        result = await asyncio.to_thread(
            sync_apify_run_to_retail_core,
            shop=shop,
            actor_run_id=run_id,
            token=token,
            raw_webhook_payload={"source": "manual_replay", "run_id": run_id},
        )
    except Exception as exc:
        observe_scraper_ingest("failure")
        raise HTTPException(status_code=502, detail=f"Apify replay ingest failed: {exc}") from exc

    observe_scraper_ingest("success")
    return {"ok": True, **result.to_dict()}


def _require_webhook_secret(request: Request) -> None:
    expected = os.environ.get("APIFY_WEBHOOK_SECRET") or os.environ.get("WEBHOOK_SECRET")
    if not expected:
        return
    header_secret = request.headers.get("x-webhook-secret")
    bearer = request.headers.get("authorization")
    if header_secret == expected or bearer == f"Bearer {expected}":
        return
    raise HTTPException(status_code=401, detail="Invalid webhook secret.")


def _optional_auth(request: Request) -> AuthContext | None:
    token = token_from_authorization(request.headers.get("authorization"))
    if not token:
        return None
    try:
        return authenticate_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _required_auth(request: Request) -> AuthContext:
    token = _bearer_or_401(request)
    try:
        return authenticate_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _required_admin(request: Request) -> AuthContext:
    ctx = _required_auth(request)
    if ctx.global_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    return ctx


def _required_shop(request: Request) -> AuthContext:
    ctx = _required_auth(request)
    if ctx.global_role != "shop" or not ctx.tenant_id:
        raise HTTPException(status_code=403, detail="Shop access is required.")
    return ctx


def _bearer_or_401(request: Request) -> str:
    token = token_from_authorization(request.headers.get("authorization"))
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is required.")
    return token


def _tenant_id_from_request(request: Request) -> str | None:
    ctx = _required_shop(request)
    return ctx.tenant_id


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


@app.get("/report")
def report(request: Request) -> dict[str, Any]:
    return report_live(request)


@app.get("/ops/scrape-runs")
def scrape_runs(request: Request) -> list[dict[str, Any]]:
    return _tenant_scrape_runs(_tenant_id_from_request(request))


def _tenant_scrape_runs(tenant_id: str) -> list[dict[str, Any]]:
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select sr.id, sr.shop_code, sr.item_count, sr.ingest_status,
                           sr.started_at, sr.finished_at, sr.created_at
                    from intel.scrape_runs sr
                    join intel.tenant_competitors tc
                        on tc.shop_code = sr.shop_code
                       and tc.tenant_id = %s
                       and tc.is_active = true
                    order by sr.created_at desc
                    limit 100
                    """,
                    (tenant_id,),
                )
                rows = cur.fetchall() or []
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return [
        {
            "id": str(row["id"]),
            "shop": row["shop_code"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else row["created_at"].isoformat(),
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else row["created_at"].isoformat(),
            "status": "success" if row["ingest_status"] == "succeeded" else "failed",
            "items_scraped": int(row["item_count"] or 0),
            "valid_rows": int(row["item_count"] or 0) if row["ingest_status"] == "succeeded" else 0,
        }
        for row in rows
    ]


@app.get("/ops/competitor-latest")
def competitor_latest(request: Request, limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
    tenant_id = _tenant_id_from_request(request)
    if tenant_id:
        return _tenant_competitor_latest(tenant_id, limit)
    return build_competitor_latest(limit=limit)


def _tenant_competitor_latest(tenant_id: str, limit: int) -> list[dict[str, Any]]:
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select cpl.shop_code, cpl.product_key, cpl.competitor_product_id,
                           cpl.product_name, cpl.brand_name,
                           cpl.competitor_price, cpl.competitor_sale_price, cpl.currency,
                           cpl.is_on_sale, cpl.availability, cpl.source_url, cpl.last_seen_at
                    from intel.competitor_products_latest cpl
                    join intel.tenant_competitors tc
                        on tc.shop_code = cpl.shop_code
                       and tc.tenant_id = %s
                       and tc.is_active = true
                    order by cpl.last_seen_at desc
                    limit %s
                    """,
                    (tenant_id, limit),
                )
                rows = cur.fetchall() or []
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return [
        {
            "shop": row["shop_code"],
            "external_id": row["competitor_product_id"] or row["product_key"],
            "product_name": row["product_name"],
            "brand": row["brand_name"] or "Unknown",
            "price_usd": effective_competitor_price_usd(
                row["competitor_price"],
                row["competitor_sale_price"],
                row["currency"],
                row["is_on_sale"],
            ) or 0.0,
            "on_sale": bool(row["is_on_sale"]),
            "in_stock": "out" not in str(row["availability"] or "").lower(),
            "url": row["source_url"] or "",
            "last_seen": row["last_seen_at"].isoformat() if row["last_seen_at"] else "",
        }
        for row in rows
    ]


@app.get("/evaluation/live-rds/metrics")
def live_rds_evaluation_metrics() -> Response:
    from services.decision_intelligence.evaluation.live_rds_metrics import render_prometheus_metrics

    return Response(render_prometheus_metrics(), media_type="text/plain; version=0.0.4")


@app.get("/inventory/db/status")
def inventory_db_status(request: Request) -> dict[str, Any]:
    return db_status(tenant_id=_tenant_id_from_request(request))


@app.get("/inventory/items")
def inventory_items(
    request: Request,
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    try:
        return list_inventory_items(search=search, limit=limit, tenant_id=_tenant_id_from_request(request))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/inventory/items")
def create_inventory_item_route(payload: InventoryItemPayload, request: Request) -> dict[str, Any]:
    try:
        return create_inventory_item(payload, tenant_id=_tenant_id_from_request(request))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.put("/inventory/items/{sku_id}")
def update_inventory_item_route(sku_id: str, payload: InventoryItemPayload, request: Request) -> dict[str, Any]:
    try:
        return update_inventory_item(sku_id, payload, tenant_id=_tenant_id_from_request(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/inventory/items/{sku_id}/movement")
def record_inventory_movement_route(sku_id: str, payload: InventoryMovementPayload, request: Request) -> dict[str, Any]:
    try:
        return record_inventory_movement(sku_id, payload, tenant_id=_tenant_id_from_request(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.patch("/inventory/items/{sku_id}/price")
def patch_inventory_item_price(
    sku_id: str,
    payload: "PriceDecisionPayload",
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, Any]:
    try:
        result = patch_inventory_price(
            sku_id,
            payload.retail_price_usd,
            payload.decision_type,
            payload.notes,
            tenant_id=_tenant_id_from_request(request),
        )
        # Map clearance â†’ CLEAR, markdown â†’ MARKDOWN, hold â†’ HOLD
        _decision_map = {"clearance": "CLEAR", "markdown": "MARKDOWN", "hold": "HOLD", "promote": "PROMOTE"}
        decision_upper = _decision_map.get(payload.decision_type, payload.decision_type.upper())
        background_tasks.add_task(
            _snapshot_in_background,
            sku_id=sku_id,
            decision_type=decision_upper,
            recommendation_id=payload.recommendation_id,
            cost_price_usd=payload.cost_price_usd,
            tenant_id=_tenant_id_from_request(request),
        )
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/decisions")
def record_decision_route(
    payload: "RetailerDecisionPayload",
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, Any]:
    try:
        result = record_retailer_decision(
            payload.sku_id,
            payload.decision_type,
            payload.notes,
            tenant_id=_tenant_id_from_request(request),
        )
        _decision_map = {"clearance": "CLEAR", "markdown": "MARKDOWN", "hold": "HOLD", "promote": "PROMOTE"}
        decision_upper = _decision_map.get(payload.decision_type, payload.decision_type.upper())
        background_tasks.add_task(
            _snapshot_in_background,
            sku_id=payload.sku_id,
            decision_type=decision_upper,
            recommendation_id=payload.recommendation_id,
            cost_price_usd=payload.cost_price_usd,
            tenant_id=_tenant_id_from_request(request),
        )
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {payload.sku_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _snapshot_in_background(
    sku_id: str,
    decision_type: str,
    recommendation_id: str | None,
    cost_price_usd: float,
    tenant_id: str,
) -> None:
    try:
        variant_id = get_variant_id_for_sku(sku_id, tenant_id=tenant_id)
        if not variant_id:
            return
        from eep.outcome_tracking import snapshot_decision
        snapshot_decision(
            sku_id=sku_id,
            variant_id=variant_id,
            decision_type=decision_type,
            recommendation_id=recommendation_id,
            cost_price_usd=cost_price_usd,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Background snapshot failed for %s: %s", sku_id, exc)


# â”€â”€â”€ Outcome Tracking Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/outcomes/snapshot")
def create_outcome_snapshot(
    request: Request,
    payload: dict[str, Any] = Body(...),
    background_tasks: BackgroundTasks = None,
) -> dict[str, Any]:
    """Manually trigger a snapshot for a given variant_id + decision_type."""
    from eep.outcome_tracking import snapshot_decision
    variant_id = payload.get("variant_id")
    sku_id = payload.get("sku_id", "")
    decision_type = (payload.get("decision_type") or "").upper()
    if not variant_id or not decision_type:
        raise HTTPException(status_code=400, detail="variant_id and decision_type are required")
    tenant_id = _tenant_id_from_request(request)
    try:
        snapshot_id = snapshot_decision(
            sku_id=sku_id,
            variant_id=variant_id,
            decision_type=decision_type,
            recommendation_id=payload.get("recommendation_id"),
            cost_price_usd=float(payload.get("cost_price_usd") or 0),
            tenant_id=tenant_id,
        )
        return {"snapshot_id": snapshot_id, "ok": snapshot_id is not None}
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/outcomes")
def list_all_outcomes(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Return all outcome snapshots for the authenticated tenant with product info joined."""
    from eep.outcome_tracking import get_all_outcomes
    try:
        return get_all_outcomes(
            tenant_id=_tenant_id_from_request(request),
            limit=limit,
            offset=offset,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/outcomes/measure-all-due")
def measure_all_due_route(request: Request) -> dict[str, Any]:
    """Measure all due snapshots for the authenticated tenant in one call."""
    from eep.outcome_tracking import measure_all_due
    try:
        return measure_all_due(tenant_id=_tenant_id_from_request(request))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/outcomes/by-sku/{sku_id}")
def get_outcomes_by_sku(sku_id: str, request: Request) -> list[dict[str, Any]]:
    """Return outcome snapshots for a sku_id (resolves variant_id internally)."""
    from eep.outcome_tracking import get_outcomes_for_sku
    try:
        tenant_id = _tenant_id_from_request(request)
        variant_id = get_variant_id_for_sku(sku_id, tenant_id=tenant_id)
        if not variant_id:
            return []
        return get_outcomes_for_sku(variant_id, tenant_id=tenant_id)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/outcomes/{variant_id}")
def get_outcomes(variant_id: str, request: Request) -> list[dict[str, Any]]:
    """Return all outcome snapshots + measurements for a variant."""
    from eep.outcome_tracking import get_outcomes_for_sku
    try:
        return get_outcomes_for_sku(variant_id, tenant_id=_tenant_id_from_request(request))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/outcomes/{snapshot_id}/measure")
def trigger_measurement(snapshot_id: int, payload: "OutcomeMeasurePayload", request: Request) -> dict[str, Any]:
    """Trigger a measurement for a snapshot (7 or 14 day window)."""
    from eep.outcome_tracking import measure_outcome
    try:
        return measure_outcome(snapshot_id, payload.window_days, tenant_id=_tenant_id_from_request(request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/outcomes/{snapshot_id}/daily-series")
def get_daily_series(snapshot_id: int, request: Request) -> list[dict[str, Any]]:
    """Return daily sales series for velocity timeline chart (7d before + 14d after)."""
    from eep.outcome_tracking import get_daily_series
    try:
        return get_daily_series(snapshot_id, tenant_id=_tenant_id_from_request(request))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/outcomes/portfolio/accuracy")
def portfolio_accuracy(
    request: Request,
    decision_type: str | None = Query(default=None),
) -> dict[str, Any]:
    """Aggregate accuracy stats across all completed measurements."""
    from eep.outcome_tracking import get_accuracy
    try:
        return get_accuracy(decision_type, tenant_id=_tenant_id_from_request(request))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ─── Human Validation Layer ──────────────────────────────────────────────────
# Final human-review stage applied AFTER the system recommendation is generated.
# The original system recommendation is never modified — each review snapshots it.

def _reviewer_from_ctx(ctx: AuthContext) -> dict[str, Any]:
    return {"user_id": ctx.user_id, "email": ctx.email, "role": ctx.global_role}


@app.post("/recommendations/{sku_id}/review")
def submit_recommendation_review(
    sku_id: str,
    payload: "RecommendationReviewPayload",
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, Any]:
    """Record a human accept/override/reject of the system recommendation for a SKU."""
    ctx = _required_shop(request)
    from eep.human_validation_db import ReviewValidationError, create_review
    try:
        review = create_review(
            sku_id=sku_id,
            action=payload.action,
            final_decision=payload.final_decision,
            final_price_usd=payload.final_price_usd,
            final_discount_pct=payload.final_discount_pct,
            note=payload.note,
            reviewer=_reviewer_from_ctx(ctx),
            recommendation_id=payload.recommendation_id,
            tenant_id=ctx.tenant_id,
        )
    except ReviewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Keep the closed-loop outcome tracker working: snapshot the acted decision.
    final_decision = review.get("final_decision")
    if payload.action in {"accept", "override"} and final_decision and final_decision != "HOLD":
        background_tasks.add_task(
            _snapshot_in_background,
            sku_id=sku_id,
            decision_type=final_decision,
            recommendation_id=review.get("recommendation_id"),
            cost_price_usd=0.0,
            tenant_id=ctx.tenant_id,
        )
    return review


@app.get("/recommendations/reviews")
def list_recommendation_reviews(
    request: Request,
    action: str | None = Query(default=None, pattern="^(accept|override|reject)$"),
    model_version: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    ctx = _required_shop(request)
    from eep.human_validation_db import list_reviews
    try:
        return list_reviews(
            tenant_id=ctx.tenant_id,
            action=action,
            model_version=model_version,
            limit=limit,
            offset=offset,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/recommendations/reviews/{review_id}/history")
def recommendation_review_history(review_id: str, request: Request) -> list[dict[str, Any]]:
    ctx = _required_shop(request)
    from eep.human_validation_db import get_review_history
    try:
        return get_review_history(review_id, tenant_id=ctx.tenant_id)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.put("/recommendations/reviews/{review_id}")
def update_recommendation_review(
    review_id: str,
    payload: "RecommendationReviewUpdatePayload",
    request: Request,
) -> dict[str, Any]:
    ctx = _required_shop(request)
    from eep.human_validation_db import ReviewValidationError, update_review
    try:
        return update_review(
            review_id,
            action=payload.action,
            final_decision=payload.final_decision,
            final_price_usd=payload.final_price_usd,
            final_discount_pct=payload.final_discount_pct,
            note=payload.note,
            reviewer=_reviewer_from_ctx(ctx),
            tenant_id=ctx.tenant_id,
        )
    except ReviewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Review not found: {review_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/recommendations/{sku_id}/review")
def get_recommendation_review(sku_id: str, request: Request) -> dict[str, Any] | None:
    ctx = _required_shop(request)
    from eep.human_validation_db import get_current_review_for_sku
    try:
        return get_current_review_for_sku(sku_id, tenant_id=ctx.tenant_id)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/analytics/recommendation-reviews")
def recommendation_review_analytics(
    request: Request,
    model_version: str | None = Query(default=None, max_length=120),
) -> dict[str, Any]:
    """Acceptance rate, override rate, agreement, and trends for the tenant."""
    ctx = _required_shop(request)
    from eep.human_validation_db import get_review_analytics
    try:
        return get_review_analytics(tenant_id=ctx.tenant_id, model_version=model_version)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/admin/recommendation-reviews/aggregate")
def admin_recommendation_review_aggregate(
    request: Request,
    model_version: str | None = Query(default=None, max_length=120),
) -> dict[str, Any]:
    """Cross-tenant human-vs-system agreement aggregate, broken down by model version."""
    _required_admin(request)
    from eep.human_validation_db import get_review_analytics_cross_tenant
    try:
        return get_review_analytics_cross_tenant(model_version=model_version)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/admin/export/training-labels")
def admin_export_training_labels(
    request: Request,
    tenant_id: str | None = Query(default=None),
    since: str | None = Query(default=None),
    include_unlabeled: bool = Query(default=False),
    limit: int = Query(default=10000, ge=1, le=100000),
) -> Response:
    """Export human-reviewed ground-truth labels as JSON Lines for retraining pipelines."""
    _required_admin(request)
    from eep.human_validation_db import export_training_labels
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="`since` must be ISO-8601.") from exc
    try:
        rows = export_training_labels(
            tenant_id=tenant_id,
            since=since_dt,
            include_unlabeled=include_unlabeled,
            limit=limit,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    body = "\n".join(json.dumps(row, default=str) for row in rows)
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=training_labels.jsonl"},
    )


@app.delete("/inventory/items/{sku_id}")
def archive_inventory_item_route(sku_id: str, request: Request) -> dict[str, Any]:
    try:
        return archive_inventory_item(sku_id, tenant_id=_tenant_id_from_request(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/inventory/import")
def import_inventory_route(payload: InventoryImportPayload, request: Request) -> dict[str, Any]:
    try:
        return import_inventory(payload, tenant_id=_tenant_id_from_request(request))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/recommend/batch")
async def recommend_batch(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Body must include a non-empty 'items' array.")

    for item in items:
        if not isinstance(item, dict) or not item.get("sku_id"):
            raise HTTPException(status_code=400, detail="Each batch item must include sku_id.")

    tenant_id = _tenant_id_from_request(request)
    feature_results = _ie1_feature_batch([str(item["sku_id"]) for item in items], tenant_id=tenant_id)
    response_rows: list[dict[str, Any] | None] = [None] * len(feature_results)
    valid_features: list[dict[str, Any]] = []
    valid_indexes: list[int] = []

    for index, feature_payload in enumerate(feature_results):
        if not isinstance(feature_payload, dict):
            response_rows[index] = _batch_error_row(str(items[index]["sku_id"]), "IE1 returned an invalid row.", 502)
            continue
        if feature_payload.get("error"):
            response_rows[index] = _batch_error_row(
                str(feature_payload.get("sku_id") or items[index]["sku_id"]),
                str(feature_payload.get("error")),
                int(feature_payload.get("status_code") or 503),
            )
            continue
        valid_indexes.append(index)
        valid_features.append(feature_payload)

    if valid_features:
        decision_results = _ie2_recommend_features_batch(valid_features)
        for feature_payload, index, decision in zip(valid_features, valid_indexes, decision_results):
            sku_id = str(feature_payload.get("sku_id") or items[index]["sku_id"])
            competitor_metric_payload = feature_payload.get("competitor_signals")
            if not isinstance(decision, dict) or decision.get("error"):
                response_rows[index] = _batch_error_row(
                    sku_id,
                    str(decision.get("error") if isinstance(decision, dict) else "IE2 returned an invalid row."),
                    int(decision.get("status_code") if isinstance(decision, dict) and decision.get("status_code") else 502),
                )
                continue
            observe_competitor_match(competitor_metric_payload)
            observe_recommendation("/recommend/batch", decision.get("recommendation"))
            response_payload = serialize_frontend_recommendation(decision)
            response_rows[index] = {
                **response_payload,
                "competitor_signals_used": competitor_metric_payload,
                "input_context": _frontend_input_context(feature_payload, competitor_metric_payload),
            }

    return [
        row if row is not None else _batch_error_row(str(items[index]["sku_id"]), "Recommendation row was not produced.", 500)
        for index, row in enumerate(response_rows)
    ]


@app.get("/system-decisions/latest")
def system_decisions_latest(request: Request) -> dict[str, Any]:
    try:
        tenant_id = str(_tenant_id_from_request(request))
        ttl_seconds = float(os.environ.get("SYSTEM_DECISION_LATEST_CACHE_SECONDS", "5"))
        now = time.time()
        with _READ_CACHE_LOCK:
            cached = _SYSTEM_DECISION_LATEST_CACHE.get(tenant_id)
            if cached and now - cached[0] <= ttl_seconds:
                return cached[1]
        payload = list_system_decision_latest(tenant_id=tenant_id)
        with _READ_CACHE_LOCK:
            _SYSTEM_DECISION_LATEST_CACHE[tenant_id] = (now, payload)
        return payload
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/system-decisions/sync-all")
def system_decisions_sync_all(background_tasks: BackgroundTasks, request: Request) -> dict[str, Any]:
    tenant_id = _tenant_id_from_request(request)
    try:
        sku_ids = list_active_inventory_sku_ids(tenant_id=tenant_id)
        return _begin_system_decision_sync(
            sku_ids,
            tenant_id=tenant_id,
            trigger=SYSTEM_DECISION_MANUAL_ALL_TRIGGER,
            background_tasks=background_tasks,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/system-decisions/sync-unsynced")
def system_decisions_sync_unsynced(background_tasks: BackgroundTasks, request: Request) -> dict[str, Any]:
    tenant_id = _tenant_id_from_request(request)
    try:
        sku_ids = list_unsynced_inventory_sku_ids(tenant_id=tenant_id)
        return _begin_system_decision_sync(
            sku_ids,
            tenant_id=tenant_id,
            trigger=SYSTEM_DECISION_MANUAL_UNSYNCED_TRIGGER,
            background_tasks=background_tasks,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/system-decisions/sync/{sku_id}")
def system_decisions_sync_sku(sku_id: str, background_tasks: BackgroundTasks, request: Request) -> dict[str, Any]:
    tenant_id = _tenant_id_from_request(request)
    try:
        return _begin_system_decision_sync(
            [sku_id],
            tenant_id=tenant_id,
            trigger=SYSTEM_DECISION_NEW_SKU_TRIGGER,
            background_tasks=background_tasks,
            allow_existing_run=False,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/system-decisions/runs/{run_id}")
def system_decision_run(run_id: str, request: Request) -> dict[str, Any]:
    try:
        run = get_system_decision_run(run_id, tenant_id=_tenant_id_from_request(request))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not run:
        raise HTTPException(status_code=404, detail=f"System decision run not found: {run_id}")
    return run


def _begin_system_decision_sync(
    sku_ids: list[str],
    *,
    tenant_id: str,
    trigger: str,
    background_tasks: BackgroundTasks | None = None,
    allow_existing_run: bool = True,
) -> dict[str, Any]:
    _clear_read_caches(tenant_id)
    _reconcile_stale_system_decision_syncs()
    unique_sku_ids = _unique_non_empty(sku_ids)
    if allow_existing_run:
        active_run = get_active_system_decision_run(tenant_id=tenant_id)
        if active_run:
            return {**active_run, "already_running": True}

    run = create_system_decision_run(trigger=trigger, total_count=len(unique_sku_ids), tenant_id=tenant_id)
    if not unique_sku_ids:
        update_system_decision_run(
            run["id"],
            tenant_id=tenant_id,
            status="completed",
            completed_count=0,
            failed_count=0,
            finished=True,
        )
        completed_run = get_system_decision_run(run["id"], tenant_id=tenant_id)
        return {**(completed_run or run), "already_running": False}

    if background_tasks is not None:
        background_tasks.add_task(
            _run_system_decision_sync_job,
            run["id"],
            unique_sku_ids,
            tenant_id,
            trigger,
        )
    else:
        threading.Thread(
            target=_run_system_decision_sync_job,
            args=(run["id"], unique_sku_ids, tenant_id, trigger),
            name=f"system-decision-sync-{run['id']}",
            daemon=True,
        ).start()
    return {**run, "already_running": False}


def _reconcile_stale_system_decision_syncs() -> None:
    stale_minutes = max(1, int(os.environ.get("SYSTEM_DECISION_STALE_RUN_MINUTES", "10")))
    reason = (
        "Previous sync run stopped before completion. "
        "This row is safe to retry with Sync Unsynced or Sync All."
    )
    try:
        result = fail_stale_system_decision_runs(stale_minutes, reason)
        if result.get("stale_runs") or result.get("stale_items"):
            _clear_read_caches(None)
            print(
                "Recovered stale system decision syncs: "
                f"{result.get('stale_runs', 0)} runs, {result.get('stale_items', 0)} items."
            )
    except Exception as exc:
        print(f"Stale system decision sync recovery skipped: {exc}")


def _run_system_decision_sync_job(run_id: str, sku_ids: list[str], tenant_id: str, trigger: str) -> None:
    completed = 0
    failed = 0
    total = len(sku_ids)
    summary_error: str | None = None
    update_system_decision_run(run_id, tenant_id=tenant_id, status="running", completed_count=0, failed_count=0)

    batch_size = max(1, int(os.environ.get("SYSTEM_DECISION_SYNC_BATCH_SIZE", "25")))
    concurrency = max(1, int(os.environ.get("SYSTEM_DECISION_SYNC_CONCURRENCY", "1")))
    chunks = list(_chunks(sku_ids, batch_size))

    def record_progress(result: tuple[int, int, str | None]) -> None:
        nonlocal completed, failed, summary_error
        result_completed, result_failed, result_error = result
        completed += result_completed
        failed += result_failed
        if result_error:
            summary_error = result_error
        _clear_read_caches(tenant_id)
        update_system_decision_run(run_id, tenant_id=tenant_id, completed_count=completed, failed_count=failed)

    if concurrency == 1 or len(chunks) <= 1:
        for chunk in chunks:
            record_progress(_process_system_decision_sync_chunk(run_id, chunk, tenant_id, trigger))
    else:
        with ThreadPoolExecutor(max_workers=min(concurrency, len(chunks))) as executor:
            futures = {
                executor.submit(_process_system_decision_sync_chunk, run_id, chunk, tenant_id, trigger): chunk
                for chunk in chunks
            }
            for future in as_completed(futures):
                try:
                    record_progress(future.result())
                except Exception as exc:
                    # A worker-level crash is unexpected; keep the run visible instead of silently stalling.
                    chunk = futures[future]
                    completed += len(chunk)
                    failed += len(chunk)
                    summary_error = str(exc)
                    update_system_decision_run(run_id, tenant_id=tenant_id, completed_count=completed, failed_count=failed)

    if failed == 0:
        final_status = "completed"
    elif failed >= total:
        final_status = "failed"
    else:
        final_status = "partial"
    update_system_decision_run(
        run_id,
        tenant_id=tenant_id,
        status=final_status,
        completed_count=completed,
        failed_count=failed,
        summary_error=summary_error,
        finished=True,
    )


def _process_system_decision_sync_chunk(
    run_id: str,
    chunk: list[str],
    tenant_id: str,
    trigger: str,
) -> tuple[int, int, str | None]:
    completed = 0
    failed = 0
    summary_error: str | None = None

    mark_system_decisions_syncing(chunk, tenant_id=tenant_id, run_id=run_id, trigger=trigger)
    try:
        feature_results = _ie1_feature_batch(chunk, tenant_id=tenant_id)
    except HTTPException as exc:
        detail = str(exc.detail)
        error_code = _classify_sync_error("IE1", detail, exc.status_code)
        for sku_id in chunk:
            upsert_system_decision_error(
                sku_id,
                tenant_id=tenant_id,
                run_id=run_id,
                trigger=trigger,
                error_stage="IE1",
                error_code=error_code,
                error_detail=detail,
            )
        return len(chunk), len(chunk), detail
    except Exception as exc:
        detail = str(exc)
        for sku_id in chunk:
            upsert_system_decision_error(
                sku_id,
                tenant_id=tenant_id,
                run_id=run_id,
                trigger=trigger,
                error_stage="IE1",
                error_code=_classify_sync_error("IE1", detail, 503),
                error_detail=detail,
            )
        return len(chunk), len(chunk), detail

    valid_features: list[dict[str, Any]] = []
    valid_sku_ids: list[str] = []
    for index, feature_payload in enumerate(feature_results):
        sku_id = str(feature_payload.get("sku_id") if isinstance(feature_payload, dict) else chunk[index])
        if not isinstance(feature_payload, dict):
            detail = "IE1 returned an invalid feature row."
            upsert_system_decision_error(
                sku_id,
                tenant_id=tenant_id,
                run_id=run_id,
                trigger=trigger,
                error_stage="IE1",
                error_code="IE1_FEATURE_ERROR",
                error_detail=detail,
            )
            completed += 1
            failed += 1
            summary_error = detail
            continue
        if feature_payload.get("error"):
            detail = str(feature_payload.get("error") or "IE1 feature construction failed.")
            status_code = int(feature_payload.get("status_code") or 503)
            upsert_system_decision_error(
                sku_id,
                tenant_id=tenant_id,
                run_id=run_id,
                trigger=trigger,
                error_stage="IE1",
                error_code=_classify_sync_error("IE1", detail, status_code),
                error_detail=detail,
            )
            completed += 1
            failed += 1
            summary_error = detail
            continue
        validation_error = _feature_validation_error(feature_payload)
        if validation_error:
            error_code, detail = validation_error
            upsert_system_decision_error(
                sku_id,
                tenant_id=tenant_id,
                run_id=run_id,
                trigger=trigger,
                error_stage="DATA_VALIDATION",
                error_code=error_code,
                error_detail=detail,
            )
            completed += 1
            failed += 1
            summary_error = detail
            continue
        valid_features.append(feature_payload)
        valid_sku_ids.append(sku_id)

    if valid_features:
        try:
            decision_results = _ie2_recommend_features_batch(valid_features)
        except HTTPException as exc:
            detail = str(exc.detail)
            error_code = _classify_sync_error("IE2", detail, exc.status_code)
            for sku_id in valid_sku_ids:
                upsert_system_decision_error(
                    sku_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    trigger=trigger,
                    error_stage="IE2",
                    error_code=error_code,
                    error_detail=detail,
                )
            return completed + len(valid_sku_ids), failed + len(valid_sku_ids), detail
        except Exception as exc:
            detail = str(exc)
            for sku_id in valid_sku_ids:
                upsert_system_decision_error(
                    sku_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    trigger=trigger,
                    error_stage="IE2",
                    error_code=_classify_sync_error("IE2", detail, 503),
                    error_detail=detail,
                )
            return completed + len(valid_sku_ids), failed + len(valid_sku_ids), detail

        for feature_payload, sku_id, decision in zip(valid_features, valid_sku_ids, decision_results):
            if not isinstance(decision, dict) or decision.get("error"):
                detail = str(decision.get("error") if isinstance(decision, dict) else "IE2 returned an invalid row.")
                status_code = int(decision.get("status_code") if isinstance(decision, dict) and decision.get("status_code") else 502)
                upsert_system_decision_error(
                    sku_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    trigger=trigger,
                    error_stage="IE2",
                    error_code=_classify_sync_error("IE2", detail, status_code),
                    error_detail=detail,
                )
                failed += 1
                summary_error = detail
            else:
                competitor_metric_payload = feature_payload.get("competitor_signals")
                observe_competitor_match(competitor_metric_payload)
                observe_recommendation("/system-decisions/sync", decision.get("recommendation"))
                response_payload = serialize_frontend_recommendation(decision)
                full_payload = {
                    **response_payload,
                    "sku_id": sku_id,
                    "competitor_signals_used": competitor_metric_payload,
                    "input_context": _frontend_input_context(feature_payload, competitor_metric_payload),
                }
                upsert_system_decision_success(
                    sku_id,
                    full_payload,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    trigger=trigger,
                )
            completed += 1

        if len(decision_results) < len(valid_sku_ids):
            missing_sku_ids = valid_sku_ids[len(decision_results):]
            detail = "IE2 returned fewer recommendation rows than requested."
            for sku_id in missing_sku_ids:
                upsert_system_decision_error(
                    sku_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    trigger=trigger,
                    error_stage="IE2",
                    error_code="IE2_DECISION_ERROR",
                    error_detail=detail,
                )
                completed += 1
                failed += 1
            summary_error = detail

    return completed, failed, summary_error


def _start_system_decision_scheduler() -> None:
    global _SYSTEM_DECISION_SCHEDULER_STARTED
    if os.environ.get("SYSTEM_DECISION_SCHEDULER_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        return
    with _SYSTEM_DECISION_SCHEDULER_LOCK:
        if _SYSTEM_DECISION_SCHEDULER_STARTED:
            return
        _SYSTEM_DECISION_SCHEDULER_STARTED = True
        threading.Thread(target=_system_decision_scheduler_loop, name="system-decision-scheduler", daemon=True).start()


def _system_decision_scheduler_loop() -> None:
    timezone_name = os.environ.get("SYSTEM_DECISION_SCHEDULER_TIMEZONE", "Asia/Beirut")
    hour = int(os.environ.get("SYSTEM_DECISION_SCHEDULER_HOUR", "7"))
    minute = int(os.environ.get("SYSTEM_DECISION_SCHEDULER_MINUTE", "0"))
    tz = ZoneInfo(timezone_name)
    while True:
        try:
            now = datetime.now(tz)
            if now.hour == hour and now.minute == minute:
                for tenant_id in list_tenant_ids():
                    active_run = get_active_system_decision_run(tenant_id=tenant_id)
                    if active_run or system_decision_run_exists_today(tenant_id, SYSTEM_DECISION_DAILY_TRIGGER, timezone_name):
                        continue
                    sku_ids = list_active_inventory_sku_ids(tenant_id=tenant_id)
                    _begin_system_decision_sync(
                        sku_ids,
                        tenant_id=tenant_id,
                        trigger=SYSTEM_DECISION_DAILY_TRIGGER,
                        background_tasks=None,
                    )
            time.sleep(60)
        except Exception as exc:
            print(f"System decision scheduler skipped cycle: {exc}")
            time.sleep(60)


def _classify_sync_error(stage: str, detail: str, status_code: int | None = None) -> str:
    text = detail.lower()
    if status_code in {401, 403}:
        return "AUTH_ERROR"
    if status_code == 404 or "sku not found" in text:
        return "SKU_NOT_FOUND"
    if "tenant" in text and ("not found" in text or "scope" in text):
        return "TENANT_SCOPE_MISMATCH"
    if "timed out" in text or "timeout" in text:
        return f"{stage}_TIMEOUT"
    if "network" in text or "service call failed" in text or "connection" in text:
        return "NETWORK_ERROR"
    return "IE1_FEATURE_ERROR" if stage == "IE1" else "IE2_DECISION_ERROR"


def _unique_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _batch_error_row(sku_id: str, detail: str, status_code: int) -> dict[str, Any]:
    return {
        "sku_id": sku_id,
        "recommendation": "HOLD",
        "confidence": 0.0,
        "explanation": detail,
        "shap_top5": [],
        "rule_override": None,
        "fallback_used": True,
        "model_version": "error",
        "processing_time_ms": 0,
        "requires_human_approval": True,
        "error": detail,
        "status_code": status_code,
    }


def _safe_sync_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _feature_validation_error(feature_payload: dict[str, Any]) -> tuple[str, str] | None:
    features = feature_payload.get("features") if isinstance(feature_payload.get("features"), dict) else {}
    retail_price = _safe_sync_float(feature_payload.get("retail_price_usd") or features.get("retail_price_usd"))
    cost_price = _safe_sync_float(feature_payload.get("cost_price_usd") or features.get("cost_price_usd"))
    if retail_price is None or retail_price <= 0:
        return "INVALID_RETAIL_PRICE", "Invalid inventory pricing: retail_price_usd must be greater than zero."
    if cost_price is None or cost_price < 0:
        return "INVALID_COST_PRICE", "Invalid inventory pricing: cost_price_usd must be zero or greater."
    if cost_price >= retail_price:
        return "INVALID_PRICE_MARGIN", "Invalid inventory pricing: cost_price_usd must be lower than retail_price_usd."
    return None


async def _recommend_batch_item(
    item: dict[str, Any],
    endpoint_label: str,
    tenant_id: str | None,
) -> dict[str, Any]:
    sku_id = str(item.get("sku_id") or "")
    try:
        return await _recommend_for_frontend(sku_id, item, endpoint_label=endpoint_label, tenant_id=tenant_id)
    except HTTPException as exc:
        return {
            "sku_id": sku_id,
            "recommendation": "HOLD",
            "confidence": 0.0,
            "explanation": str(exc.detail),
            "shap_top5": [],
            "rule_override": None,
            "fallback_used": True,
            "model_version": "error",
            "processing_time_ms": 0,
            "requires_human_approval": True,
            "error": str(exc.detail),
            "status_code": exc.status_code,
        }
    except Exception as exc:
        return {
            "sku_id": sku_id,
            "recommendation": "HOLD",
            "confidence": 0.0,
            "explanation": "Unexpected recommendation error.",
            "shap_top5": [],
            "rule_override": None,
            "fallback_used": True,
            "model_version": "error",
            "processing_time_ms": 0,
            "requires_human_approval": True,
            "error": str(exc),
            "status_code": 500,
        }


@app.post("/recommend/full")
async def full_recommendation(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    sku_id = payload.get("sku_id")
    if not sku_id:
        raise HTTPException(status_code=400, detail="sku_id is required.")

    tenant_id = _tenant_id_from_request(request)
    report_payload = report_live(request) if tenant_id else build_frontend_report()
    recommendation = await _recommend_for_frontend(sku_id, payload, endpoint_label="/recommend/full", tenant_id=tenant_id)
    creative = next(
        (item for item in report_payload.get("promotions", {}).get("promote", []) if item["sku_id"] == sku_id),
        None,
    )
    return {
        "sku_id": sku_id,
        "ie2_result": recommendation,
        "campaign_creative": creative.get("creative") if creative else None,
        "status": "complete",
    }


@app.post("/recommend/{sku_id}")
async def recommend_for_frontend(
    request: Request,
    sku_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await _recommend_for_frontend(
        sku_id,
        payload,
        endpoint_label="/recommend/{sku_id}",
        tenant_id=_tenant_id_from_request(request),
    )


async def _recommend_for_frontend(
    sku_id: str,
    payload: dict[str, Any],
    endpoint_label: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    feature_payload = _ie1_feature_instance(sku_id, tenant_id=tenant_id)
    competitor_metric_payload = feature_payload.get("competitor_signals")
    result = _ie2_recommend_from_features(feature_payload)
    observe_competitor_match(competitor_metric_payload)
    observe_recommendation(endpoint_label, result.get("recommendation"))
    response_payload = serialize_frontend_recommendation(result)
    return {
        **response_payload,
        "competitor_signals_used": competitor_metric_payload,
        "input_context": _frontend_input_context(feature_payload, competitor_metric_payload),
    }


def _service_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib_request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("detail", detail)
        except Exception:
            pass
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Service call failed for {url}: {exc}") from exc


def _ie1_base_url() -> str:
    return os.environ.get("IE1_BASE_URL", "http://ie1_market_intelligence:8001").rstrip("/")


def _ie2_base_url() -> str:
    return os.environ.get("IE2_BASE_URL", "http://ie2_decision_intelligence:8002").rstrip("/")


def _ie1_feature_instance(sku_id: str, tenant_id: str | None) -> dict[str, Any]:
    query = f"?tenant_id={tenant_id}" if tenant_id else ""
    payload = _service_json(f"{_ie1_base_url()}/features/{sku_id}{query}", timeout=120.0)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="IE1 returned an invalid feature payload.")
    return payload


def _ie1_feature_batch(sku_ids: list[str], tenant_id: str | None) -> list[dict[str, Any]]:
    timeout = float(os.environ.get("SYSTEM_DECISION_IE1_BATCH_TIMEOUT_SECONDS", "300"))
    payload = {
        "items": [{"sku_id": sku_id} for sku_id in sku_ids],
        "tenant_id": tenant_id,
    }
    result = _service_json(
        f"{_ie1_base_url()}/features/batch",
        method="POST",
        payload=payload,
        timeout=timeout,
    )
    if not isinstance(result, list):
        raise HTTPException(status_code=502, detail="IE1 returned an invalid feature batch payload.")
    return result


def _ie2_recommend_from_features(feature_payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get("IE2_API_KEY", "ie2-local-postman-key")
    result = _service_json(
        f"{_ie2_base_url()}/recommend/features",
        method="POST",
        payload=feature_payload,
        headers={"X-API-Key": api_key},
        timeout=90.0,
    )
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="IE2 returned an invalid recommendation payload.")
    return result


def _ie2_recommend_features_batch(feature_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    api_key = os.environ.get("IE2_API_KEY", "ie2-local-postman-key")
    timeout = float(os.environ.get("SYSTEM_DECISION_IE2_BATCH_TIMEOUT_SECONDS", "180"))
    result = _service_json(
        f"{_ie2_base_url()}/recommend/features/batch",
        method="POST",
        payload={"items": feature_payloads},
        headers={"X-API-Key": api_key},
        timeout=timeout,
    )
    if not isinstance(result, list):
        raise HTTPException(status_code=502, detail="IE2 returned an invalid recommendation batch payload.")
    return result


def _frontend_input_context(
    request_payload: dict[str, Any],
    competitor_signals: Any,
) -> dict[str, Any]:
    allowed_fields = {
        "sku_id",
        "product_name",
        "brand",
        "category",
        "retail_price_usd",
        "cost_price_usd",
        "current_stock",
        "initial_stock",
        "days_since_launch",
        "days_since_last_discount",
        "days_at_current_price",
    }
    context = {key: request_payload.get(key) for key in allowed_fields if key in request_payload}
    context["competitor_signals"] = competitor_signals if isinstance(competitor_signals, dict) else None
    return context


@app.get("/report/live")
def report_live(request: Request) -> dict[str, Any]:
    """Build the full frontend report from live DB inventory data."""
    from datetime import datetime, timezone
    from statistics import median as _median

    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        request_tenant_id = _tenant_id_from_request(request)
        tenant_cache_key = str(request_tenant_id)
        ttl_seconds = float(os.environ.get("REPORT_LIVE_CACHE_SECONDS", "120"))
        now_epoch = time.time()
        with _READ_CACHE_LOCK:
            cached = _REPORT_LIVE_CACHE.get(tenant_cache_key)
            if cached and now_epoch - cached[0] <= ttl_seconds:
                return cached[1]
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur, tenant_id=request_tenant_id)
                tenant_id = ctx["tenant_id"]

                # All active SKUs with stock + latest retail price
                cur.execute(
                    """
                    SELECT
                        v.id AS variant_id,
                        v.sku_id,
                        p.name  AS product_name,
                        p.brand,
                        p.category,
                        v.cost_price_usd,
                        COALESCE(pr.amount, 0)           AS retail_price_usd,
                        COALESCE(ib.quantity_on_hand, 0) AS current_stock,
                        v.created_at                     AS variant_created_at
                    FROM core.sku_variants v
                    JOIN core.products p ON p.id = v.product_id
                    LEFT JOIN core.inventory_balances ib
                        ON ib.variant_id = v.id
                       AND ib.tenant_id = v.tenant_id
                       AND ib.store_id = %s
                    LEFT JOIN LATERAL (
                        SELECT amount FROM core.prices
                        WHERE variant_id = v.id
                          AND tenant_id = v.tenant_id
                          AND price_type = 'retail'
                          AND valid_to IS NULL
                        ORDER BY valid_from DESC LIMIT 1
                    ) pr ON true
                    WHERE v.tenant_id = %s AND v.status = 'active'
                    ORDER BY p.brand, p.name
                    """,
                    (ctx["store_id"], tenant_id),
                )
                sku_rows = cur.fetchall() or []

                # Velocity: units sold in last 30 days per variant
                cur.execute(
                    """
                    SELECT variant_id, SUM(-quantity_delta) AS sold_30d
                    FROM core.inventory_movements
                    WHERE tenant_id = %s
                      AND movement_type = 'sale'
                      AND created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY variant_id
                    """,
                    (tenant_id,),
                )
                velocity_map: dict = {r["variant_id"]: max(float(r["sold_30d"] or 0), 0) for r in (cur.fetchall() or [])}

                cur.execute(
                    """
                    SELECT entity_id AS sku_id, action
                    FROM core.audit_logs
                    WHERE tenant_id = %s
                      AND entity_type = 'inventory_item'
                      AND action IN (
                          'retailer_decision_promote',
                          'retailer_decision_markdown',
                          'retailer_decision_clearance',
                          'retailer_decision_hold'
                      )
                    """,
                    (tenant_id,),
                )
                handled_skus = {
                    str(r["sku_id"])
                    for r in (cur.fetchall() or [])
                }

    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def _cat(c: str) -> str:
        labels = {
            "footwear": "Footwear", "football_boots": "Football Boots",
            "apparel": "Apparel", "sportswear": "Sportswear",
            "swimwear": "Swimwear", "accessories": "Accessories",
            "kids": "Kids", "lifestyle": "Lifestyle",
        }
        return labels.get((c or "").lower(), (c or "Other").title())

    now = datetime.now(timezone.utc)
    inventory_skus: list[dict] = []

    for row in sku_rows:
        stock = int(row["current_stock"] or 0)
        retail = float(row["retail_price_usd"] or 0)
        cost = float(row["cost_price_usd"] or 0)
        margin = round((retail - cost) / retail * 100, 1) if retail > 0 else 0.0
        units_sold = velocity_map.get(row["variant_id"], 0.0)
        velocity = round(units_sold / 30.0, 2)
        if velocity > 0:
            dos = round(stock / velocity, 1)
        elif stock > 0:
            dos = 999.0
        else:
            dos = 0.0

        created_at = row["variant_created_at"]
        if created_at is not None:
            if created_at.tzinfo is None:
                from datetime import timezone as _tz
                created_at = created_at.replace(tzinfo=_tz.utc)
            days_since_launch = (now - created_at).days
        else:
            days_since_launch = 365

        has_velocity = velocity > 0
        if has_velocity:
            if dos > 365:
                health = "dead"
            elif dos > 120:
                health = "excess"
            elif dos < 7 and stock > 0:
                health = "critical"
            else:
                health = "healthy"
        else:
            # No sales data â€” use margin and age as proxy
            if stock == 0:
                health = "healthy"
            elif days_since_launch > 365:
                health = "dead"
            elif days_since_launch > 180 or margin < 5:
                health = "excess"
            else:
                health = "healthy"

        # Decision rules
        if has_velocity:
            if dos > 180 or health == "dead":
                decision = "CLEAR"
            elif dos > 90 and margin >= 10:
                decision = "MARKDOWN"
            elif margin >= 40 and 20 <= dos <= 150 and stock >= 5:
                decision = "PROMOTE"
            else:
                decision = "HOLD"
        else:
            # No velocity data â€” classify by margin percentile tiers
            # (margin range in this dataset: ~40â€“64%, median ~54%)
            if stock == 0:
                decision = "HOLD"
            elif margin >= 57:           # top ~25% â€” high margin: promote
                decision = "PROMOTE"
            elif margin >= 50:           # mid-upper â€” hold current pricing
                decision = "HOLD"
            elif margin >= 46:           # mid-lower â€” nudge with markdown
                decision = "MARKDOWN"
            else:                        # bottom tier â€” recover capital
                decision = "CLEAR"

        if str(row["sku_id"]) in handled_skus:
            continue

        inventory_skus.append({
            "sku_id": row["sku_id"],
            "product_name": row["product_name"],
            "brand": row["brand"] or "Unknown",
            "category": _cat(row["category"]),
            "current_stock": stock,
            "initial_stock": stock,
            "retail_price_usd": round(retail, 2),
            "cost_price_usd": round(cost, 2),
            "margin_pct": margin,
            "days_of_supply": dos,
            "days_since_launch": days_since_launch,
            "days_since_last_discount": 999,
            "days_at_current_price": 30,
            "velocity_units_per_day": velocity,
            "health": health,
            "decision": decision,
        })

    # Category summaries
    from collections import defaultdict as _dd
    cat_buckets: dict = _dd(list)
    for s in inventory_skus:
        cat_buckets[s["category"]].append(s)

    category_summary: dict = {}
    health_score_points = {"healthy": 75, "excess": 45, "dead": 20, "critical": 15}
    for cat, items in sorted(cat_buckets.items()):
        avg_margin = round(sum(i["margin_pct"] for i in items) / len(items), 1) if items else 0.0
        known_dos = [i["days_of_supply"] for i in items if i["days_of_supply"] < 999]
        med_dos_val = float(_median(known_dos)) if known_dos else 999.0
        val_usd = round(sum(i["current_stock"] * i["cost_price_usd"] for i in items), 2)
        if known_dos:
            score = int(round(max(0, min(100, 100 - abs(med_dos_val - 60) * 0.6 - max(0, 45 - avg_margin) * 1.5))))
        else:
            score = int(round(sum(health_score_points.get(i["health"], 50) for i in items) / len(items))) if items else 0
        category_summary[cat] = {
            "skus": len(items),
            "units": sum(i["current_stock"] for i in items),
            "value_usd": val_usd,
            "avg_margin_pct": avg_margin,
            "median_dos": round(med_dos_val, 1),
            "health_score": score,
        }

    total_units = sum(s["current_stock"] for s in inventory_skus)
    total_cost = round(sum(s["current_stock"] * s["cost_price_usd"] for s in inventory_skus), 2)
    total_retail = round(sum(s["current_stock"] * s["retail_price_usd"] for s in inventory_skus), 2)
    blended_margin = round((total_retail - total_cost) / total_retail * 100, 1) if total_retail > 0 else 0.0
    all_dos = [s["days_of_supply"] for s in inventory_skus if s["days_of_supply"] < 999]
    med_dos_global = round(float(_median(all_dos)), 1) if all_dos else 999.0

    # Build promotion lists
    promote_items = []
    markdown_items = []
    clearance_items = []
    hold_items = []

    for s in inventory_skus:
        unknown_dos = s["days_of_supply"] >= 999
        if s["decision"] == "PROMOTE":
            lift = round(max(s["margin_pct"] - 35, 0) / 5 + 10, 1)
            reason = (
                f"Good margin ({s['margin_pct']:.0f}%) with {s['current_stock']} units on hand. No sales history yet; push visibility and start measuring velocity."
                if unknown_dos
                else f"Good margin ({s['margin_pct']:.0f}%) and sufficient stock ({int(s['days_of_supply'])} DOS). Push this now."
            )
            promote_items.append({
                "sku_id": s["sku_id"],
                "product_name": s["product_name"],
                "brand": s["brand"],
                "category": s["category"],
                "reason": reason,
                "expected_lift_pct": lift,
                "channels": ["Instagram", "WhatsApp", "In-store window"],
            })
        elif s["decision"] == "MARKDOWN":
            discount = 15 if s["margin_pct"] > 40 else 20 if s["margin_pct"] > 30 else 10
            margin_after = round(s["margin_pct"] - discount * (s["retail_price_usd"] / max(s["retail_price_usd"], 0.01)), 1)
            margin_after = round(s["margin_pct"] * (1 - discount / 100), 1)
            suggested_price = round(s["retail_price_usd"] * (1 - discount / 100), 2)
            if unknown_dos:
                reason = f"No sales history yet and margin is lower than stronger SKUs. A controlled {discount}% markdown can test demand."
                urgency = "medium"
            else:
                dos_disp = int(s["days_of_supply"])
                reason = f"Slow-moving stock ({dos_disp} DOS). A {discount}% markdown accelerates sell-through."
                urgency = "high" if s["days_of_supply"] > 180 else "medium" if s["days_of_supply"] > 120 else "low"
            markdown_items.append({
                "sku_id": s["sku_id"],
                "product_name": s["product_name"],
                "brand": s["brand"],
                "current_price_usd": s["retail_price_usd"],
                "suggested_discount_pct": float(discount),
                "suggested_price_usd": suggested_price,
                "margin_after_pct": margin_after,
                "reason": reason,
                "urgency": urgency,
            })
        elif s["decision"] == "CLEAR":
            discount = 50
            suggested_price = round(s["retail_price_usd"] * 0.5, 2) if s["retail_price_usd"] > 0 else round(s["cost_price_usd"] * 0.5, 2)
            recovered = round(suggested_price * s["current_stock"], 2)
            clearance_items.append({
                "sku_id": s["sku_id"],
                "product_name": s["product_name"],
                "brand": s["brand"],
                "current_stock": s["current_stock"],
                "age_days": s["days_since_launch"],
                "suggested_price_usd": suggested_price,
                "recovered_cash_usd": recovered,
                "urgency": "high" if unknown_dos else "critical" if s["days_of_supply"] > 365 else "high",
            })
        else:  # HOLD
            hold_items.append({
                "sku_id": s["sku_id"],
                "product_name": s["product_name"],
                "brand": s["brand"],
                "reason": "Healthy velocity and margin. Maintain current pricing.",
                "margin_pct": s["margin_pct"],
                "velocity": s["velocity_units_per_day"],
            })

    payload = {
        "inventory": {
            "metrics": {
                "total_skus": len(inventory_skus),
                "total_units": total_units,
                "inventory_value_at_cost_usd": total_cost,
                "inventory_value_at_retail_usd": total_retail,
                "blended_margin_pct": blended_margin,
                "median_days_of_supply": med_dos_global,
                "critical_stockouts": sum(1 for s in inventory_skus if s["health"] == "critical"),
                "dead_stock_skus": sum(1 for s in inventory_skus if s["health"] == "dead"),
                "excess_stock_skus": sum(1 for s in inventory_skus if s["health"] == "excess"),
                "healthy_skus": sum(1 for s in inventory_skus if s["health"] == "healthy"),
            },
            "sku_analysis": inventory_skus,
            "category_summary": category_summary,
            "alerts": [],
        },
        "competitor": {
            "market_overview": {
                "skus_tracked": len(inventory_skus),
                "competitor_records": 0,
                "shops_covered": 0,
                "avg_price_gap_pct": 0.0,
                "overpriced_skus": 0,
                "underpriced_skus": 0,
                "at_market_skus": len(inventory_skus),
                "data_freshness_hours": 0.0,
            },
            "sku_positioning": [],
            "brand_summary": {},
            "category_summary": {},
            "opportunities": [],
        },
        "promotions": {
            "hold_pricing": hold_items,
            "promote": promote_items,
            "markdown": markdown_items,
            "clearance": clearance_items,
            "seasonal_actions": [],
            "directives": [],
            "summary": {
                "hold_count": len(hold_items),
                "promote_count": len(promote_items),
                "markdown_count": len(markdown_items),
                "clearance_count": len(clearance_items),
            },
        },
        "metadata": {
            "generated_at": generated_at,
            "engine_version": "live-db-1.0",
            "market": "Lebanon",
            "currency": "fresh USD",
            "data_window_days": 30,
            "source": "live-db",
        },
    }
    with _READ_CACHE_LOCK:
        _REPORT_LIVE_CACHE[tenant_cache_key] = (now_epoch, payload)
    return payload



@app.get("/social/accounts")
def social_accounts_list(request: Request) -> list[dict[str, Any]]:
    """List connected social media accounts for the authenticated tenant."""
    request_tenant_id = _tenant_id_from_request(request)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur, tenant_id=request_tenant_id)
                cur.execute(
                    """
                    SELECT id, platform, account_name, page_id, user_id,
                           is_active, token_expires_at, created_at
                    FROM marketing.tenant_social_accounts
                    WHERE tenant_id = %s
                    ORDER BY platform
                    """,
                    (ctx["tenant_id"],),
                )
                rows = cur.fetchall() or []
        return [dict(r) for r in rows]
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/social/accounts")
def social_accounts_add(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Connect a social media account for the authenticated tenant."""
    request_tenant_id = _tenant_id_from_request(request)
    platform = body.get("platform", "")
    access_token = body.get("access_token", "")
    if not platform or not access_token:
        raise HTTPException(status_code=400, detail="platform and access_token are required")
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur, tenant_id=request_tenant_id)
                cur.execute(
                    """
                    INSERT INTO marketing.tenant_social_accounts
                        (tenant_id, platform, account_name, page_id, user_id,
                         access_token, token_expires_at, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, true)
                    ON CONFLICT (tenant_id, platform) DO UPDATE SET
                        account_name     = EXCLUDED.account_name,
                        page_id          = EXCLUDED.page_id,
                        user_id          = EXCLUDED.user_id,
                        access_token     = EXCLUDED.access_token,
                        token_expires_at = EXCLUDED.token_expires_at,
                        is_active        = true
                    RETURNING id
                    """,
                    (
                        ctx["tenant_id"], platform,
                        body.get("account_name"),
                        body.get("page_id"),
                        body.get("user_id"),
                        access_token,
                        body.get("token_expires_at"),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return {"ok": True, "id": str(row["id"]) if row else None}
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/social/accounts/{platform}")
def social_accounts_remove(platform: str, request: Request) -> dict[str, Any]:
    """Disconnect a social media platform for the authenticated tenant."""
    request_tenant_id = _tenant_id_from_request(request)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur, tenant_id=request_tenant_id)
                cur.execute(
                    "UPDATE marketing.tenant_social_accounts SET is_active = false "
                    "WHERE tenant_id = %s AND platform = %s",
                    (ctx["tenant_id"], platform),
                )
            conn.commit()
        return {"ok": True}
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class SocialDisplayNamePayload(BaseModel):
    account_name: str


@app.patch("/social/accounts/{platform}")
def social_account_update_name(
    platform: str, payload: SocialDisplayNamePayload, request: Request
) -> dict[str, Any]:
    """Allow a retailer to set their display name for a connected social platform."""
    request_tenant_id = _tenant_id_from_request(request)
    if not payload.account_name.strip():
        raise HTTPException(status_code=400, detail="account_name must not be empty")
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur, tenant_id=request_tenant_id)
                cur.execute(
                    """
                    UPDATE marketing.tenant_social_accounts
                    SET account_name = %s
                    WHERE tenant_id = %s AND platform = %s AND is_active = true
                    RETURNING platform, account_name, is_active
                    """,
                    (payload.account_name.strip(), ctx["tenant_id"], platform),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise HTTPException(
                status_code=404,
                detail="Social account not found â€” your admin must connect this platform first.",
            )
        return dict(row)
    except HTTPException:
        raise
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not update display name: {exc}") from exc


@app.post("/admin/tenants/{tenant_id}/registration-code")
def generate_registration_code(tenant_id: str, request: Request) -> dict[str, Any]:
    """Generate a one-time Telegram registration code for a tenant (admin only)."""
    import secrets
    request_tenant_id = _tenant_id_from_request(request)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                # Verify the requesting user has access to this tenant
                ctx = _context(cur, tenant_id=request_tenant_id)
                code = secrets.token_urlsafe(12)
                cur.execute(
                    """
                    INSERT INTO telegram.registration_codes
                        (code, tenant_id, created_by, expires_at)
                    VALUES (%s, %s, %s, now() + interval '7 days')
                    """,
                    (code, tenant_id, ctx.get("user_id")),
                )
            conn.commit()
        return {"code": code, "expires_in": "7 days", "usage": f"/register {code}"}
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# â”€â”€ Admin: Social Account Credentials per Tenant â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class SocialAccountPayload(BaseModel):
    platform: str
    access_token: str
    page_id: str | None = None
    user_id: str | None = None
    account_name: str | None = None


@app.get("/admin/tenants/{tenant_id}/social-accounts")
def admin_get_social_accounts(tenant_id: str, request: Request) -> list[dict[str, Any]]:
    """List all connected social accounts for a tenant (admin only). Tokens are masked."""
    ctx = _required_admin(request)
    try:
        return admin_list_social_accounts(ctx, tenant_id)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not load social accounts: {exc}") from exc


@app.post("/admin/tenants/{tenant_id}/social-accounts")
async def admin_save_social_account(
    tenant_id: str, payload: SocialAccountPayload, request: Request
) -> dict[str, Any]:
    """Save (upsert) a social account credential for a tenant.

    For platform='telegram', the EEP service automatically calls Telegram's
    setWebhook API to register a per-tenant webhook at
    {TELEGRAM_WEBHOOK_BASE_URL}/webhook/telegram/{tenant_id}.
    """
    ctx = _required_admin(request)
    webhook_registered_at = None

    if payload.platform == "telegram":
        webhook_base = os.environ.get("TELEGRAM_WEBHOOK_BASE_URL", "").rstrip("/")
        if webhook_base:
            webhook_url = f"{webhook_base}/webhook/telegram/{tenant_id}"
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{payload.access_token}/setWebhook",
                        json={"url": webhook_url},
                    )
                    result = resp.json()
                    if result.get("ok"):
                        from datetime import datetime, timezone
                        webhook_registered_at = datetime.now(timezone.utc)
                    else:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Telegram setWebhook failed: {result.get('description', 'unknown error')}. "
                                   "Check the bot token and try again.",
                        )
            except _httpx.RequestError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not reach Telegram API: {exc}",
                ) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Telegram webhook registration failed: {exc}",
                ) from exc
        else:
            raise HTTPException(
                status_code=400,
                detail="TELEGRAM_WEBHOOK_BASE_URL is not configured on the server. "
                       "Set it to your public server URL (e.g. https://api.yourdomain.com).",
            )

    try:
        saved = admin_upsert_social_account(
            ctx,
            tenant_id=tenant_id,
            platform=payload.platform,
            access_token=payload.access_token,
            page_id=payload.page_id,
            user_id=payload.user_id,
            account_name=payload.account_name,
            webhook_registered_at=webhook_registered_at,
        )
        return {**saved, "webhook_registered": webhook_registered_at is not None}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/admin/tenants/{tenant_id}/social-accounts/{platform}")
def admin_delete_social_account(
    tenant_id: str, platform: str, request: Request
) -> dict[str, Any]:
    """Deactivate a social account for a tenant (admin only). Reversible via re-save."""
    ctx = _required_admin(request)
    try:
        admin_remove_social_account(ctx, tenant_id, platform)
        return {"ok": True, "platform": platform}
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/dashboard/summary")
async def dashboard_summary(request: Request) -> dict[str, Any]:
    report_payload = report_live(request)
    return {
        "generated_at": report_payload["metadata"]["generated_at"],
        "inventory": report_payload["inventory"]["metrics"],
        "market": report_payload["competitor"]["market_overview"],
        "promotions": report_payload["promotions"]["summary"],
    }


