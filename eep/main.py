"""
EEP — Executive Experience Platform.
Owner: Mohammad Farhat.

Status: STUB — endpoints defined, orchestration logic not implemented.

Pipeline per request:
  1. Call IE1 → GET /competitor/{sku_id} → CompetitorSignals
  2. Call IE2 → POST /recommend → RecommendationResult
  3. Call IE3 → POST /campaign/generate → CampaignPackage
  4. Return RecommendationPackage (all three merged)

Port: 8000
Run:
    uvicorn eep.main:app --port 8000 --reload
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

app = FastAPI(
    title="StylePulse AI — EEP Executive Platform",
    description="Unified dashboard API — orchestrates IE1 + IE2 + IE3",
    version="0.1.0",
)

IE1_URL = "http://localhost:8001"
IE2_URL = "http://localhost:8002"
IE3_URL = "http://localhost:8003"


class RecommendationPackage(BaseModel):
    """Full package returned to the dashboard."""
    sku_id: str
    product_name: str
    recommendation: str
    confidence: float
    explanation: str
    suggested_price_usd: Optional[float]
    campaign_headline_en: Optional[str]
    campaign_headline_ar: Optional[str]
    instagram_caption: Optional[str]
    suggested_channels: list[str] = []
    requires_human_approval: bool = True


@app.get("/health")
def health():
    return {"status": "healthy", "service": "eep"}


@app.post("/recommend/full", response_model=RecommendationPackage)
async def full_recommendation(sku_id: str):
    """
    TODO (Mohammad Farhat): Orchestrate IE1 → IE2 → IE3 pipeline.
    Use httpx.AsyncClient to call all three services and merge results
    into a RecommendationPackage for the dashboard.
    """
    raise NotImplementedError("EEP: full_recommendation not implemented yet")


@app.get("/dashboard/summary")
async def dashboard_summary():
    """
    TODO (Mohammad Farhat): Return aggregated stats for the dashboard home page.
    Query IE2 batch endpoint for all 350 SKUs, aggregate by decision class.
    """
    raise NotImplementedError("EEP: dashboard_summary not implemented yet")
