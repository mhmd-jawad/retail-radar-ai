"""
EEP — Executive Experience Platform.

Frontend-facing API that exposes:
  - the transformed analytics report used by the dashboard
  - scrape/competitor operations data from local outputs
  - recommendation endpoints that adapt the existing IE2 service contract

Run:
    uvicorn eep.main:app --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

# Load .env from repo root (no-op if file absent or dotenv not installed)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:
    pass

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from eep.auth_db import (
    AuthContext,
    AuthError,
    LoginPayload,
    ShopProfileUpdatePayload,
    ShopSignupPayload,
    admin_list_competitor_requests,
    admin_list_tenants,
    authenticate_token,
    ensure_default_admin_account,
    get_shop_profile,
    list_available_competitors,
    login,
    logout,
    signup_shop,
    token_from_authorization,
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
    prepare_ie2_request,
    report_overview,
    serialize_frontend_recommendation,
)
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
    _connect,
    _context,
    archive_inventory_item,
    create_inventory_item,
    db_status,
    import_inventory,
    list_inventory_items,
    patch_inventory_price,
    record_retailer_decision,
    update_inventory_item,
)
from pydantic import BaseModel
from services.decision_intelligence.schemas import CompetitorSignals, RecommendationRequest


class PriceDecisionPayload(BaseModel):
    retail_price_usd: float = PField(gt=0)
    decision_type: Literal["clearance", "markdown", "hold"]
    notes: str | None = None


class RetailerDecisionPayload(BaseModel):
    sku_id: str
    decision_type: Literal["clearance", "markdown", "hold", "promote"]
    notes: str | None = None


app = FastAPI(
    title="StylePulse AI — EEP Executive Platform",
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


@app.on_event("startup")
def _startup_accounts() -> None:
    try:
        ensure_default_admin_account()
    except Exception as exc:
        print(f"Admin account bootstrap skipped: {exc}")


def _recommend_single(request_model: RecommendationRequest):
    from services.decision_intelligence.main import _recommend_single as recommend_single

    return recommend_single(request_model)


@app.get("/health")
def health() -> dict[str, Any]:
    overview = report_overview()
    return {
        "status": "healthy",
        "service": "eep",
        "report_ready": True,
        "sku_count": overview["sku_count"],
        "shops_covered": overview["shop_count"],
    }


@app.post("/auth/login")
def auth_login(payload: LoginPayload, request: Request) -> dict[str, Any]:
    try:
        return login(payload, user_agent=request.headers.get("user-agent"), ip_address=_client_ip(request))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
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
    return _required_auth(request).model_dump()


@app.post("/auth/logout")
def auth_logout(request: Request) -> dict[str, Any]:
    token = _bearer_or_401(request)
    try:
        return logout(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/auth/competitors")
def auth_competitors() -> list[dict[str, Any]]:
    try:
        return list_available_competitors()
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/shop/profile")
def shop_profile(request: Request) -> dict[str, Any]:
    try:
        return get_shop_profile(_required_auth(request))
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.put("/shop/profile")
def shop_profile_update(payload: ShopProfileUpdatePayload, request: Request) -> dict[str, Any]:
    try:
        return update_shop_profile(_required_auth(request), payload)
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/admin/tenants")
def admin_tenants(request: Request) -> list[dict[str, Any]]:
    try:
        return admin_list_tenants(_required_auth(request))
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
        return admin_list_competitor_requests(_required_auth(request), status=status)
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


def _bearer_or_401(request: Request) -> str:
    token = token_from_authorization(request.headers.get("authorization"))
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is required.")
    return token


def _tenant_id_from_request(request: Request) -> str | None:
    ctx = _optional_auth(request)
    return ctx.tenant_id if ctx and ctx.tenant_id else None


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else None


@app.get("/report")
def report() -> dict[str, Any]:
    return build_frontend_report()


@app.get("/ops/scrape-runs")
def scrape_runs() -> list[dict[str, Any]]:
    return build_scrape_runs()


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
                           coalesce(cpl.competitor_sale_price, cpl.competitor_price, 0) as price_usd,
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
            "price_usd": float(row["price_usd"] or 0),
            "on_sale": bool(row["is_on_sale"]),
            "in_stock": "out" not in str(row["availability"] or "").lower(),
            "url": row["source_url"] or "",
            "last_seen": row["last_seen_at"].isoformat() if row["last_seen_at"] else "",
        }
        for row in rows
    ]


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


@app.patch("/inventory/items/{sku_id}/price")
def patch_inventory_item_price(sku_id: str, payload: "PriceDecisionPayload", request: Request) -> dict[str, Any]:
    try:
        return patch_inventory_price(
            sku_id,
            payload.retail_price_usd,
            payload.decision_type,
            payload.notes,
            tenant_id=_tenant_id_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/decisions")
def record_decision_route(payload: "RetailerDecisionPayload", request: Request) -> dict[str, Any]:
    try:
        return record_retailer_decision(
            payload.sku_id,
            payload.decision_type,
            payload.notes,
            tenant_id=_tenant_id_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {payload.sku_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    return list(await asyncio.gather(*[
        _recommend_for_frontend(item["sku_id"], item, endpoint_label="/recommend/batch", tenant_id=tenant_id)
        for item in items
    ]))


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
    if tenant_id:
        try:
            payload = {**payload, **_live_recommendation_payload(sku_id, tenant_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"SKU not found for this shop: {sku_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DatabaseUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    request_payload = prepare_ie2_request(sku_id, payload)
    competitor_metric_payload = request_payload.get("competitor_signals")
    request_payload = _strip_competitor_metadata(request_payload)
    request_model = RecommendationRequest.model_validate(request_payload)
    result = _recommend_single(request_model)
    observe_competitor_match(competitor_metric_payload)
    observe_recommendation(endpoint_label, getattr(result, "recommendation", None))
    return serialize_frontend_recommendation(result)


def _strip_competitor_metadata(request_payload: dict[str, Any]) -> dict[str, Any]:
    competitor_signals = request_payload.get("competitor_signals")
    if not isinstance(competitor_signals, dict):
        return request_payload

    allowed_fields = set(CompetitorSignals.model_fields)
    cleaned_signals = {
        key: value
        for key, value in competitor_signals.items()
        if key in allowed_fields
    }
    return {**request_payload, "competitor_signals": cleaned_signals}


def _live_recommendation_payload(sku_id: str, tenant_id: str) -> dict[str, Any]:
    from datetime import datetime, timezone

    with _connect() as conn:
        with conn.cursor() as cur:
            ctx = _context(cur, tenant_id=tenant_id)
            cur.execute(
                """
                select
                    v.id as variant_id,
                    v.sku_id,
                    v.style_code,
                    p.name as product_name,
                    p.brand,
                    p.category,
                    v.cost_price_usd,
                    coalesce(pr.amount, 0) as retail_price_usd,
                    coalesce(b.quantity_on_hand, 0) as current_stock,
                    v.created_at as variant_created_at
                from core.sku_variants v
                join core.products p on p.id = v.product_id
                left join core.inventory_balances b
                    on b.variant_id = v.id and b.store_id = %s
                left join lateral (
                    select amount
                    from core.prices
                    where variant_id = v.id and price_type = 'retail' and valid_to is null
                    order by valid_from desc
                    limit 1
                ) pr on true
                where v.tenant_id = %s and v.sku_id = %s and v.status = 'active'
                """,
                (ctx["store_id"], ctx["tenant_id"], sku_id),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(sku_id)

            retail = float(row["retail_price_usd"] or 0)
            cost = float(row["cost_price_usd"] or 0)
            if retail <= 0:
                raise ValueError(f"SKU {sku_id} needs a retail price greater than 0 before recommending.")
            if cost <= 0 or cost >= retail:
                raise ValueError(f"SKU {sku_id} needs a cost price greater than 0 and lower than retail price.")

            created_at = row["variant_created_at"]
            if created_at is not None and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            days_since_launch = (datetime.now(timezone.utc) - created_at).days if created_at else 180
            current_stock = int(row["current_stock"] or 0)

            return {
                "sku_id": row["sku_id"],
                "product_name": row["product_name"],
                "brand": row["brand"] or "Unknown",
                "category": row["category"] or "uncategorized",
                "retail_price_usd": round(retail, 2),
                "cost_price_usd": round(cost, 2),
                "current_stock": current_stock,
                "initial_stock": max(current_stock, 1),
                "days_since_launch": max(days_since_launch, 0),
                "days_since_last_discount": 999,
                "days_at_current_price": 30,
                "competitor_signals": _live_competitor_signals(cur, ctx["tenant_id"], row),
            }


def _live_competitor_signals(cur, tenant_id: Any, product_row: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timezone
    from statistics import mean

    sku_id = str(product_row["sku_id"])
    style_code = product_row.get("style_code")
    brand = str(product_row.get("brand") or "").strip()
    product_name = str(product_row.get("product_name") or "").strip()
    retail = float(product_row.get("retail_price_usd") or 0)

    match_sql = "lower(cpl.sku_id) = lower(%s)"
    params: list[Any] = [tenant_id, sku_id]
    if style_code:
        match_sql = "(lower(coalesce(cpl.style_code, '')) = lower(%s) or lower(coalesce(cpl.sku_id, '')) = lower(%s))"
        params = [tenant_id, style_code, sku_id]
    elif brand and product_name:
        token = product_name.split()[0]
        match_sql = (
            "(lower(coalesce(cpl.sku_id, '')) = lower(%s)"
            " or (lower(coalesce(cpl.brand_name, '')) = lower(%s)"
            " and lower(cpl.product_name) like %s))"
        )
        params = [tenant_id, sku_id, brand, f"%{token.lower()}%"]

    cur.execute(
        """
        select cpl.shop_code, s.shop_name,
               coalesce(cpl.competitor_sale_price, cpl.competitor_price) as price_usd,
               cpl.is_on_sale,
               cpl.availability,
               cpl.last_seen_at
        from intel.competitor_products_latest cpl
        join intel.tenant_competitors tc
            on tc.shop_code = cpl.shop_code and tc.tenant_id = %s and tc.is_active = true
        join intel.shops s on s.shop_code = cpl.shop_code
        where """
        + match_sql
        + """
          and coalesce(cpl.competitor_sale_price, cpl.competitor_price) is not null
        order by coalesce(cpl.competitor_sale_price, cpl.competitor_price) asc
        limit 50
        """,
        params,
    )
    rows = cur.fetchall() or []
    priced_rows = [
        (row, float(row["price_usd"]))
        for row in rows
        if row.get("price_usd") is not None and float(row["price_usd"]) > 0
    ]
    prices = [price for _, price in priced_rows]
    timestamp = datetime.now(timezone.utc)
    if not prices or retail <= 0:
        return {
            "sku_id": sku_id,
            "competitor_min_price": 0,
            "competitor_avg_price": 0,
            "price_gap_pct": 0,
            "competitors_on_sale_count": 0,
            "competitors_out_of_stock_count": 0,
            "num_competitors_tracked": 0,
            "cheapest_competitor_name": None,
            "price_trend_direction": "STABLE",
            "data_freshness_hours": 0,
            "confidence_score": 0,
            "fallback_used": True,
            "fallback_reason": "No matching products found in this shop's selected competitors.",
            "timestamp": timestamp.isoformat(),
        }

    cheapest_row, min_price = min(priced_rows, key=lambda item: item[1])
    latest_seen = max((row.get("last_seen_at") for row, _ in priced_rows if row.get("last_seen_at")), default=None)
    if latest_seen and latest_seen.tzinfo is None:
        latest_seen = latest_seen.replace(tzinfo=timezone.utc)
    freshness_hours = round((timestamp - latest_seen).total_seconds() / 3600, 2) if latest_seen else 0
    out_of_stock = sum(1 for row, _ in priced_rows if "out" in str(row.get("availability") or "").lower())
    on_sale = sum(1 for row, _ in priced_rows if bool(row.get("is_on_sale")))

    return {
        "sku_id": sku_id,
        "competitor_min_price": round(min_price, 2),
        "competitor_avg_price": round(mean(prices), 2),
        "price_gap_pct": round((retail - min_price) / retail, 4),
        "competitors_on_sale_count": on_sale,
        "competitors_out_of_stock_count": out_of_stock,
        "num_competitors_tracked": len(prices),
        "cheapest_competitor_name": cheapest_row.get("shop_name") or cheapest_row.get("shop_code"),
        "price_trend_direction": "STABLE",
        "data_freshness_hours": freshness_hours,
        "confidence_score": 0.85,
        "fallback_used": False,
        "fallback_reason": None,
        "timestamp": timestamp.isoformat(),
    }


@app.get("/report/live")
def report_live(request: Request) -> dict[str, Any]:
    """Build the full frontend report from live DB inventory data."""
    from datetime import datetime, timezone
    from statistics import median as _median

    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        request_tenant_id = _tenant_id_from_request(request)
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
                    LEFT JOIN core.inventory_balances ib ON ib.variant_id = v.id
                    LEFT JOIN LATERAL (
                        SELECT amount FROM core.prices
                        WHERE variant_id = v.id
                          AND price_type = 'retail'
                          AND valid_to IS NULL
                        ORDER BY valid_from DESC LIMIT 1
                    ) pr ON true
                    WHERE v.tenant_id = %s AND v.status = 'active'
                    ORDER BY p.brand, p.name
                    """,
                    (tenant_id,),
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
            # No sales data — use margin and age as proxy
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
            # No velocity data — classify by margin percentile tiers
            # (margin range in this dataset: ~40–64%, median ~54%)
            if stock == 0:
                decision = "HOLD"
            elif margin >= 57:           # top ~25% — high margin: promote
                decision = "PROMOTE"
            elif margin >= 50:           # mid-upper — hold current pricing
                decision = "HOLD"
            elif margin >= 46:           # mid-lower — nudge with markdown
                decision = "MARKDOWN"
            else:                        # bottom tier — recover capital
                decision = "CLEAR"

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
    for cat, items in sorted(cat_buckets.items()):
        avg_margin = round(sum(i["margin_pct"] for i in items) / len(items), 1) if items else 0.0
        med_dos_val = float(_median([i["days_of_supply"] for i in items])) if items else 0.0
        val_usd = round(sum(i["current_stock"] * i["cost_price_usd"] for i in items), 2)
        score = int(round(max(0, min(100, 100 - abs(med_dos_val - 60) * 0.6 - max(0, 45 - avg_margin) * 1.5))))
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
    med_dos_global = round(float(_median(all_dos)), 1) if all_dos else 0.0
    cash_on_hand = round(total_cost * 0.25, 2) if total_cost > 0 else 0.0
    monthly_burn = round(max(total_cost / 12, 0), 2) if total_cost > 0 else 0.0
    cash_runway = round(cash_on_hand / monthly_burn, 1) if monthly_burn > 0 else 0.0
    total_assets = round(total_cost + cash_on_hand, 2)
    liabilities = round(total_assets * 0.39, 2) if total_assets > 0 else 0.0
    equity = round(total_assets - liabilities, 2)
    current_ratio = round(total_assets / liabilities, 2) if liabilities > 0 else 0.0
    inventory_pct_assets = round(total_cost / total_assets * 100, 1) if total_assets > 0 else 0.0
    breakeven_revenue = round(monthly_burn * 12, 2)
    projected_revenue = round(total_retail * 1.1, 2)
    opex_coverage = round(projected_revenue / breakeven_revenue, 2) if breakeven_revenue > 0 else 0.0

    # Build promotion lists
    promote_items = []
    markdown_items = []
    clearance_items = []
    hold_items = []

    for s in inventory_skus:
        if s["decision"] == "PROMOTE":
            lift = round(max(s["margin_pct"] - 35, 0) / 5 + 10, 1)
            dos_disp = int(s["days_of_supply"]) if s["days_of_supply"] < 900 else s["current_stock"]
            promote_items.append({
                "sku_id": s["sku_id"],
                "product_name": s["product_name"],
                "brand": s["brand"],
                "category": s["category"],
                "reason": f"Good margin ({s['margin_pct']:.0f}%) and sufficient stock ({dos_disp} DOS). Push this now.",
                "expected_lift_pct": lift,
                "channels": ["Instagram", "WhatsApp", "In-store window"],
            })
        elif s["decision"] == "MARKDOWN":
            discount = 15 if s["margin_pct"] > 40 else 20 if s["margin_pct"] > 30 else 10
            margin_after = round(s["margin_pct"] - discount * (s["retail_price_usd"] / max(s["retail_price_usd"], 0.01)), 1)
            margin_after = round(s["margin_pct"] * (1 - discount / 100), 1)
            suggested_price = round(s["retail_price_usd"] * (1 - discount / 100), 2)
            dos_disp = int(s["days_of_supply"]) if s["days_of_supply"] < 900 else "high"
            urgency = "high" if s["days_of_supply"] > 180 else "medium" if s["days_of_supply"] > 120 else "low"
            markdown_items.append({
                "sku_id": s["sku_id"],
                "product_name": s["product_name"],
                "brand": s["brand"],
                "current_price_usd": s["retail_price_usd"],
                "suggested_discount_pct": float(discount),
                "suggested_price_usd": suggested_price,
                "margin_after_pct": margin_after,
                "reason": f"Slow-moving stock ({dos_disp} DOS). A {discount}% markdown accelerates sell-through.",
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
                "urgency": "critical" if s["days_of_supply"] > 365 else "high",
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

    return {
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
        "financial": {
            "balance_sheet_health": {
                "current_ratio": current_ratio,
                "inventory_pct_of_assets": inventory_pct_assets,
                "inventory_concentration_top5_pct": 0.0,
                "total_assets_usd": total_assets,
                "liabilities_usd": liabilities,
                "equity_usd": equity,
            },
            "cashflow_health": {
                "cash_runway_months": cash_runway,
                "monthly_burn_usd": monthly_burn,
                "monthly_cash_in_usd": 0.0,
                "cash_on_hand_usd": cash_on_hand,
                "lollar_exposure_pct": 0.0,
                "series": [],
            },
            "profitability": {
                "blended_margin_pct": blended_margin,
                "breakeven_revenue_usd": breakeven_revenue,
                "annual_revenue_projection_usd": projected_revenue,
                "opex_coverage_ratio": opex_coverage,
            },
            "alerts": [],
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


@app.get("/financial/balance-sheet")
def financial_balance_sheet(request: Request) -> dict[str, Any]:
    """Detailed balance sheet — requires live DB."""
    import csv
    from datetime import datetime, timezone

    generated_at = datetime.now(timezone.utc).isoformat()
    request_tenant_id = _tenant_id_from_request(request)

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur, tenant_id=request_tenant_id)
                tenant_id = ctx["tenant_id"]

                # Inventory at cost and at retail
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(ib.quantity_on_hand * v.cost_price_usd), 0)  AS inventory_at_cost,
                        COALESCE(SUM(ib.quantity_on_hand * p.amount), 0)           AS inventory_at_retail
                    FROM core.inventory_balances ib
                    JOIN core.sku_variants v ON v.id = ib.variant_id
                    LEFT JOIN LATERAL (
                        SELECT amount FROM core.prices
                        WHERE variant_id = v.id AND price_type = 'retail' AND valid_to IS NULL
                        ORDER BY valid_from DESC LIMIT 1
                    ) p ON true
                    WHERE ib.tenant_id = %s
                    """,
                    (tenant_id,),
                )
                inv_row = cur.fetchone() or {}
                inventory_at_cost = float(inv_row.get("inventory_at_cost") or 0)
                inventory_at_retail = float(inv_row.get("inventory_at_retail") or 0)

        # Load supplemental fields from static profile
        _fp = _load_financial_profile()
        bs = _fp.get("balance_sheet_summary", {})
        lc = _fp.get("lebanon_context", {})
        cash_usd = bs.get("total_assets_usd", 0) - (_fp.get("inventory_summary", {}).get("value_at_cost_usd", 0))
        lollar_face = float(lc.get("lollar_balance_usd", 12000))
        lollar_real = float(lc.get("lollar_real_value_usd", 1800))
        other_assets = 0.0
        total_assets = inventory_at_cost + cash_usd + lollar_real + other_assets
        supplier_payables = float(bs.get("total_liabilities_usd", 45344)) * (43000 / 45344)
        other_liabilities = float(bs.get("total_liabilities_usd", 45344)) - supplier_payables
        total_liabilities = supplier_payables + other_liabilities
        equity = total_assets - total_liabilities
        current_ratio = round(total_assets / total_liabilities, 2) if total_liabilities else 0
        inv_pct = round(inventory_at_cost / total_assets * 100, 1) if total_assets else 0
        debt_to_equity = round(total_liabilities / equity, 2) if equity else 0
        top5_pct = float(bs.get("inventory_concentration_top5_pct", 71.0) if "inventory_concentration_top5_pct" in bs else 71.0)

        return {
            "data_source": "live-db",
            "generated_at": generated_at,
            "assets": {
                "inventory_at_cost_usd": round(inventory_at_cost, 2),
                "inventory_at_retail_usd": round(inventory_at_retail, 2),
                "cash_on_hand_usd": round(cash_usd, 2),
                "lollar_face_usd": lollar_face,
                "lollar_real_usd": lollar_real,
                "other_assets_usd": other_assets,
                "total_usd": round(total_assets, 2),
            },
            "liabilities": {
                "supplier_payables_usd": round(supplier_payables, 2),
                "other_usd": round(other_liabilities, 2),
                "total_usd": round(total_liabilities, 2),
            },
            "equity_usd": round(equity, 2),
            "ratios": {
                "current_ratio": current_ratio,
                "inventory_pct_of_assets": inv_pct,
                "debt_to_equity": debt_to_equity,
                "top5_concentration_pct": top5_pct,
            },
        }
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/financial/profitability")
def financial_profitability(request: Request) -> dict[str, Any]:
    """Detailed profitability — requires live DB for category breakdown."""
    import csv
    from datetime import datetime, timezone

    generated_at = datetime.now(timezone.utc).isoformat()
    request_tenant_id = _tenant_id_from_request(request)
    _fp = _load_financial_profile()
    cs = _fp.get("cashflow_summary", {})
    inv = _fp.get("inventory_summary", {})

    monthly_fixed_opex = float(cs.get("monthly_fixed_opex_usd", 3500))
    blended_margin_pct = float(inv.get("blended_margin_pct", 48.6))
    breakeven_usd = round(monthly_fixed_opex / (blended_margin_pct / 100), 2) if blended_margin_pct else 0

    opex_breakdown = [
        {"label": "Rent", "amount_usd": 1100, "type": "fixed"},
        {"label": "Owner Salary", "amount_usd": 800, "type": "fixed"},
        {"label": "Staff (2 part-time)", "amount_usd": 900, "type": "fixed"},
        {"label": "Generator Fuel", "amount_usd": 220, "type": "fixed"},
        {"label": "Internet / Phone", "amount_usd": 150, "type": "fixed"},
        {"label": "Water", "amount_usd": 40, "type": "fixed"},
        {"label": "Insurance", "amount_usd": 80, "type": "fixed"},
        {"label": "Accounting / Legal", "amount_usd": 100, "type": "fixed"},
        {"label": "Miscellaneous", "amount_usd": 110, "type": "fixed"},
        {"label": "Payment Processing (1.5% rev)", "amount_usd": 0, "type": "variable", "rate_pct": 1.5},
        {"label": "Marketing (3.5% rev)", "amount_usd": 0, "type": "variable", "rate_pct": 3.5},
        {"label": "Logistics (2% COGS)", "amount_usd": 0, "type": "variable", "rate_pct": 2.0},
        {"label": "Shrinkage (0.8%/yr inventory)", "amount_usd": 0, "type": "variable", "rate_pct": 0.8},
    ]

    cogs_pct = round(100 - blended_margin_pct, 1)
    for_every_100 = {
        "cogs": cogs_pct,
        "marketing": 3.5,
        "payment_processing": 1.5,
        "logistics": 1.0,
        "fixed_opex": 2.0,
        "net_profit": round(100 - cogs_pct - 3.5 - 1.5 - 1.0 - 2.0, 1),
    }

    # --- Live DB for category breakdown ---
    category_breakdown: list[dict[str, Any]] = []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                ctx = _context(cur, tenant_id=request_tenant_id)
                tenant_id = ctx["tenant_id"]
                cur.execute(
                    """
                    WITH base AS (
                        SELECT
                            p.category,
                            COUNT(DISTINCT v.id) AS sku_count,
                            COALESCE(SUM(ib.quantity_on_hand * pr.amount), 0)        AS revenue_at_retail,
                            COALESCE(SUM(ib.quantity_on_hand * v.cost_price_usd), 0) AS cogs
                        FROM core.sku_variants v
                        JOIN core.products p ON p.id = v.product_id
                        JOIN core.inventory_balances ib ON ib.variant_id = v.id
                        LEFT JOIN LATERAL (
                            SELECT amount FROM core.prices
                            WHERE variant_id = v.id AND price_type = 'retail' AND valid_to IS NULL
                            ORDER BY valid_from DESC LIMIT 1
                        ) pr ON true
                        WHERE v.tenant_id = %s
                        GROUP BY p.category
                    )
                    SELECT category, sku_count, revenue_at_retail, cogs
                    FROM base
                    ORDER BY (revenue_at_retail - cogs) / NULLIF(revenue_at_retail, 0) DESC
                    """,
                    (tenant_id,),
                )
                rows = cur.fetchall() or []
                for row in rows:
                    rev = float(row.get("revenue_at_retail") or 0)
                    cg = float(row.get("cogs") or 0)
                    margin = round((rev - cg) / rev * 100, 1) if rev else 0
                    category_breakdown.append({
                        "category": row.get("category") or "Unknown",
                        "sku_count": int(row.get("sku_count") or 0),
                        "revenue_usd": round(rev, 2),
                        "cogs_usd": round(cg, 2),
                        "margin_pct": margin,
                    })
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    annual_rev = float(cs.get("annual_revenue_projected_usd", 2116080))
    breakeven_pairs = round(breakeven_usd / 60, 0) if breakeven_usd else 0  # assume avg ~$60/pair

    return {
        "data_source": "live-db",
        "generated_at": generated_at,
        "summary": {
            "blended_margin_pct": blended_margin_pct,
            "breakeven_revenue_usd": breakeven_usd,
            "annual_revenue_projection_usd": annual_rev,
            "opex_coverage_ratio": round(annual_rev / 12 / breakeven_usd, 2) if breakeven_usd else 0,
        },
        "for_every_100_usd": for_every_100,
        "opex_breakdown": opex_breakdown,
        "category_breakdown": category_breakdown,
        "breakeven": {
            "monthly_fixed_opex_usd": monthly_fixed_opex,
            "blended_margin_pct": blended_margin_pct,
            "result_usd": breakeven_usd,
            "plain_english": f"You need ~${breakeven_usd:,.0f}/mo in sales to cover your fixed costs.",
            "pairs_estimate": int(breakeven_pairs),
        },
    }


@app.get("/financial/cashflow")
def financial_cashflow() -> dict[str, Any]:
    """12-month cashflow series — reads cashflow_template.csv."""
    import csv
    from datetime import datetime, timezone

    generated_at = datetime.now(timezone.utc).isoformat()
    fp = _load_financial_profile()
    cf_path = _DATA_REAL / "cashflow_template.csv"
    series: list[dict[str, Any]] = []
    if cf_path.exists():
        with cf_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                series.append({
                    "month": row.get("month_name", row.get("month", "")),
                    "in": float(row.get("revenue_usd", 0)),
                    "out": float(row.get("total_opex_usd", 0)) + float(row.get("cogs_usd", 0)),
                    "net": float(row.get("net_cash_movement_usd", 0)),
                })
    return {
        "data_source": "static-file",
        "generated_at": generated_at,
        "series": series,
        "summary": fp.get("cashflow_summary", {}),
    }


def _load_financial_profile() -> dict[str, Any]:
    path = _DATA_REAL / "financial_profile.json"
    if path.exists():
        import json as _json
        return _json.loads(path.read_text(encoding="utf-8"))
    return {}


_DATA_REAL = Path(__file__).resolve().parents[1] / "data" / "real"


@app.get("/dashboard/summary")
async def dashboard_summary() -> dict[str, Any]:
    report_payload = build_frontend_report()
    return {
        "generated_at": report_payload["metadata"]["generated_at"],
        "inventory": report_payload["inventory"]["metrics"],
        "market": report_payload["competitor"]["market_overview"],
        "promotions": report_payload["promotions"]["summary"],
        "financial": {
            "cash_runway_months": report_payload["financial"]["cashflow_health"]["cash_runway_months"],
            "inventory_pct_of_assets": report_payload["financial"]["balance_sheet_health"]["inventory_pct_of_assets"],
            "blended_margin_pct": report_payload["financial"]["profitability"]["blended_margin_pct"],
        },
    }
