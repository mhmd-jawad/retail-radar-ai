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
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from eep.frontend_bridge import (
    build_competitor_latest,
    build_frontend_report,
    build_scrape_runs,
    prepare_ie2_request,
    report_overview,
    serialize_frontend_recommendation,
)
from eep.retail_db import (
    DatabaseUnavailable,
    InventoryImportPayload,
    InventoryItemPayload,
    archive_inventory_item,
    create_inventory_item,
    db_status,
    import_inventory,
    list_inventory_items,
    update_inventory_item,
)
from services.decision_intelligence.main import _recommend_single
from services.decision_intelligence.schemas import RecommendationRequest


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
    allow_headers=["Content-Type", "Authorization"],
)


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


@app.get("/report")
def report() -> dict[str, Any]:
    return build_frontend_report()


@app.get("/ops/scrape-runs")
def scrape_runs() -> list[dict[str, Any]]:
    return build_scrape_runs()


@app.get("/ops/competitor-latest")
def competitor_latest(limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
    return build_competitor_latest(limit=limit)


@app.get("/inventory/db/status")
def inventory_db_status() -> dict[str, Any]:
    return db_status()


@app.get("/inventory/items")
def inventory_items(
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    try:
        return list_inventory_items(search=search, limit=limit)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/inventory/items")
def create_inventory_item_route(payload: InventoryItemPayload) -> dict[str, Any]:
    try:
        return create_inventory_item(payload)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.put("/inventory/items/{sku_id}")
def update_inventory_item_route(sku_id: str, payload: InventoryItemPayload) -> dict[str, Any]:
    try:
        return update_inventory_item(sku_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/inventory/items/{sku_id}")
def archive_inventory_item_route(sku_id: str) -> dict[str, Any]:
    try:
        return archive_inventory_item(sku_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku_id}") from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/inventory/import")
def import_inventory_route(payload: InventoryImportPayload) -> dict[str, Any]:
    try:
        return import_inventory(payload)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/recommend/batch")
async def recommend_batch(
    payload: dict[str, Any] = Body(...),
) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Body must include a non-empty 'items' array.")

    for item in items:
        if not isinstance(item, dict) or not item.get("sku_id"):
            raise HTTPException(status_code=400, detail="Each batch item must include sku_id.")

    return list(await asyncio.gather(*[recommend_for_frontend(item["sku_id"], item) for item in items]))


@app.post("/recommend/full")
async def full_recommendation(
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    sku_id = payload.get("sku_id")
    if not sku_id:
        raise HTTPException(status_code=400, detail="sku_id is required.")

    report_payload = build_frontend_report()
    recommendation = await recommend_for_frontend(sku_id, payload)
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
    sku_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    request_payload = prepare_ie2_request(sku_id, payload)
    request_model = RecommendationRequest.model_validate(request_payload)
    result = _recommend_single(request_model)
    return serialize_frontend_recommendation(result)


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
