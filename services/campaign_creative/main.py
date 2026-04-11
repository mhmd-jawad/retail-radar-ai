"""
IE3 — Campaign Creative Service.
Owner: Mohammad Farhat.

Status: STUB — endpoints defined but not implemented.
Receives a RecommendationResult from IE2 and generates a campaign package.

Port: 8003
Run:
    uvicorn services.campaign_creative.main:app --port 8003 --reload
"""

from fastapi import FastAPI
from pydantic import BaseModel

from services.decision_intelligence.schemas import RecommendationResult

app = FastAPI(
    title="StylePulse AI — IE3 Campaign Creative",
    description="Campaign generation service",
    version="0.1.0",
)


class CampaignPackage(BaseModel):
    sku_id: str
    headline_ar: str
    headline_en: str
    instagram_caption: str
    suggested_channels: list[str]
    budget_usd: float
    urgency_label: str   # "Act Now", "This Week", "This Month"


@app.get("/health")
def health():
    return {"status": "healthy", "service": "ie3_campaign_creative"}


@app.post("/campaign/generate", response_model=CampaignPackage)
def generate_campaign(recommendation: RecommendationResult):
    """
    TODO (Mohammad Farhat): Generate a campaign package from IE2 output.
    Use recommendation.recommendation + explanation + product_name to
    produce Arabic/English copy and channel strategy.
    """
    raise NotImplementedError("IE3: generate_campaign not implemented yet")
