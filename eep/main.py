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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
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


@app.post("/recommend/{sku_id}")
async def recommend_for_frontend(
    sku_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    from services.decision_intelligence.main import _recommend_single
    from services.decision_intelligence.schemas import RecommendationRequest

    request_payload = prepare_ie2_request(sku_id, payload)
    request_model = RecommendationRequest.model_validate(request_payload)
    result = _recommend_single(request_model)
    return serialize_frontend_recommendation(result)


@app.post("/recommend/batch")
async def recommend_batch(
    payload: dict[str, Any] = Body(...),
) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Body must include a non-empty 'items' array.")

    results = []
    for item in items:
        if not isinstance(item, dict) or not item.get("sku_id"):
            raise HTTPException(status_code=400, detail="Each batch item must include sku_id.")
        results.append(await recommend_for_frontend(item["sku_id"], item))
    return results


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
        (item for item in report_payload["promotions"]["promote"] if item["sku_id"] == sku_id),
        None,
    )
    return {
        "sku_id": sku_id,
        "ie2_result": recommendation,
        "campaign_creative": creative.get("creative") if creative else None,
        "status": "pending",
    }


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
