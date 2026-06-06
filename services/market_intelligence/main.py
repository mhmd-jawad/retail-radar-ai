"""
IE1 — Market Intelligence Service.
Owner: Mohammad Jawad.

Status: STUB — endpoints defined but not implemented.
IE1 collects competitor pricing from scraping/*.py and exposes it to IE2.

Contract:
  The output of each endpoint must conform to CompetitorSignals (imported
  from services.decision_intelligence.schemas).

Port: 8001
Run:
    uvicorn services.market_intelligence.main:app --port 8001 --reload
"""

import json
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# IE1 must produce data that conforms to IE2's CompetitorSignals schema
from services.decision_intelligence.schemas import CompetitorSignals
from services.decision_intelligence.features.runtime_features import build_runtime_feature_instance
from services.market_intelligence.competitor_processor import build_competitor_signals_for_sku


ROOT = Path(__file__).resolve().parents[2]
MODEL_META_PATH = ROOT / "services" / "decision_intelligence" / "models" / "catboost_decision" / "meta.json"


class FeatureBatchItem(BaseModel):
    sku_id: str


class FeatureBatchRequest(BaseModel):
    items: list[FeatureBatchItem] = Field(min_length=1, max_length=100)
    tenant_id: str | None = None

app = FastAPI(
    title="StylePulse AI — IE1 Market Intelligence",
    description="Competitor pricing signals service",
    version="0.1.0",
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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "ie1_market_intelligence"}


def _model_feature_columns() -> list[str]:
    if not MODEL_META_PATH.exists():
        return []
    try:
        return json.loads(MODEL_META_PATH.read_text(encoding="utf-8")).get("feature_cols", [])
    except Exception:
        return []


@app.get("/competitor/{sku_id}", response_model=CompetitorSignals)
def get_competitor_signals(sku_id: str):
    """
    Return live competitor pricing signals for a SKU.

    Uses exact style matching first, then the shared fallback matcher. If no
    reliable competitor is found, the response remains schema-valid with zero
    competitor count and fallback_used=True.
    """
    try:
        return CompetitorSignals.model_validate(build_competitor_signals_for_sku(sku_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku_id}") from exc


@app.get("/features/{sku_id}")
def get_feature_instance(
    sku_id: str,
    tenant_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return the full engineered feature instance IE2 should score."""
    try:
        return build_runtime_feature_instance(
            sku_id=sku_id,
            tenant_id=tenant_id,
            feature_columns=_model_feature_columns(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"IE1 feature construction failed: {exc}") from exc


@app.post("/features/batch")
def get_feature_batch(payload: FeatureBatchRequest = Body(...)) -> list[dict[str, Any]]:
    """Return engineered feature instances with row-level errors."""
    feature_columns = _model_feature_columns()
    results: list[dict[str, Any]] = []
    for item in payload.items:
        try:
            results.append(
                build_runtime_feature_instance(
                    sku_id=item.sku_id,
                    tenant_id=payload.tenant_id,
                    feature_columns=feature_columns,
                )
            )
        except Exception as exc:
            results.append(
                {
                    "sku_id": item.sku_id,
                    "error": str(exc),
                    "status_code": 404 if isinstance(exc, KeyError) else 503,
                }
            )
    return results


@app.post("/ingest/competitor")
def ingest_competitor(signals: CompetitorSignals):
    """
    TODO (Mohammad Jawad): Accept scraped competitor data and persist it.
    Called by the scraper runner after each shop scrape.
    """
    raise HTTPException(status_code=501, detail="IE1: ingest_competitor not implemented yet")
