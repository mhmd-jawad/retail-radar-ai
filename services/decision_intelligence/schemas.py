"""
Pydantic Schemas — IE2 Decision Intelligence Service.

Defines all request/response models for the /recommend endpoint.
These schemas are the contract between IE2 and:
  - IE1 (Market Intelligence): CompetitorSignals → IE2 input
  - EEP (Orchestrator): RecommendationResult → EEP assembles final package

Team contract:
  - Mohammad Jawad (IE1): CompetitorSignals is the output of IE1.
    IE2 expects this exact schema on every /recommend request.
  - Mohammad Farhat (EEP): RecommendationResult is IE2's output.
    EEP wraps this in RecommendationPackage before returning to the owner.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ── Incoming from IE1 — Market Intelligence ───────────────────────────────────

class CompetitorSignals(BaseModel):
    """
    Output of IE1, input to IE2.
    IE1 computes these from the nightly competitor price scrape.
    """
    sku_id: str

    # Price signals
    competitor_min_price: float = Field(ge=0)
    competitor_avg_price: float = Field(ge=0)
    price_gap_pct: float = Field(
        description="(our_price - comp_min) / our_price. Positive = we're more expensive."
    )
    competitors_on_sale_count: int = Field(ge=0)
    competitors_out_of_stock_count: int = Field(ge=0)
    num_competitors_tracked: int = Field(ge=0)
    cheapest_competitor_name: Optional[str] = None

    # Trend
    price_trend_direction: Literal["RISING", "STABLE", "FALLING"] = "STABLE"

    # Confidence
    data_freshness_hours: float = Field(ge=0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    fallback_used: bool = False
    fallback_reason: Optional[str] = None

    @field_validator("fallback_reason")
    @classmethod
    def fallback_reason_required_if_fallback(cls, v, info):
        if info.data.get("fallback_used") and not v:
            raise ValueError("fallback_reason is required when fallback_used is True")
        return v

    timestamp: datetime = Field(default_factory=datetime.now)


# ── IE2 Internal ──────────────────────────────────────────────────────────────

class SKUFeatures(BaseModel):
    """
    The full feature vector IE2 assembles for a single SKU.
    Built from: product data + inventory CSV + CompetitorSignals from IE1.
    """
    sku_id: str
    product_name: str
    brand: str
    category: str
    brand_tier: Literal["tier1", "tier2", "tier3"]

    # Inventory (5)
    days_of_supply: float = Field(ge=0)
    stock_coverage_ratio: float = Field(ge=0)
    stockout_risk: int = Field(ge=0, le=1)
    total_qty: int = Field(ge=0)
    inventory_vs_median: float = Field(ge=0)

    # Pricing & Margin (5)
    current_margin_pct: float
    discount_depth_last_30d: float = 0.0      # v2: requires sales history
    days_since_last_discount: int = 999        # v2: 999 = no recent discount known
    days_at_current_price: int = 30            # v2: requires price change log
    retail_price_usd: float = Field(ge=0)

    # Competitor (5 — from CompetitorSignals)
    price_gap_pct: float
    competitors_on_sale: int = Field(ge=0)
    competitors_out_of_stock: int = Field(ge=0)
    num_competitors: int = Field(ge=0)
    market_position: Literal[
        "premium", "above_market", "at_market", "below_market", "deep_value"
    ]

    # Lifecycle (4)
    days_since_launch: int = Field(ge=0)
    season_sell_through_pct: float = Field(ge=0, le=1)
    cost_price_usd: float = Field(ge=0)

    # Seasonality (4)
    seasonality_score: float = Field(ge=0)
    category_seasonal_boost: float = 0.0
    event_proximity_score: float = Field(ge=0, le=1)
    next_month_seasonality: float = Field(ge=0)

    # Financial (3)
    cash_runway_months: float = Field(ge=0)
    cash_tight: int = Field(ge=0, le=1)
    inventory_intensity: float = Field(ge=0, le=1)


# ── Recommendation result components ─────────────────────────────────────────

class SHAPFeature(BaseModel):
    """One feature's contribution to the recommendation."""
    feature_name: str
    feature_value: float | str
    shap_value: float
    direction: Literal["increases_probability", "decreases_probability"]
    explanation: str  # plain English — e.g. "You are 12% more expensive than JD Sports"


class RuleOverride(BaseModel):
    """Details when a hard rule overrides the ML model."""
    rule_id: str   # e.g. "DEAD_STOCK_CLEAR"
    override_strength: Literal["absolute", "strong", "soft"]
    reason: str
    blocked_actions: list[str]


# ── IE2 Output — consumed by EEP ─────────────────────────────────────────────

class RecommendationResult(BaseModel):
    """
    IE2's output per SKU.
    EEP (Mohammad Farhat) receives this and wraps it in RecommendationPackage.
    """
    sku_id: str
    product_name: str

    recommendation: Literal["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"]
    confidence: float = Field(ge=0.0, le=1.0)

    # Why
    explanation: str              # top-level plain English summary
    shap_top5: list[SHAPFeature]  # top 5 feature contributions

    # Rule info (None if ML model decided)
    rule_override: Optional[RuleOverride] = None
    fallback_used: bool = False   # True if confidence < 0.45 → returned HOLD

    # Action details
    suggested_discount_pct: Optional[float] = None  # set for MARKDOWN
    suggested_price_usd: Optional[float] = None      # set for MARKDOWN
    margin_after_action_pct: Optional[float] = None  # projected margin post-action

    # Service metadata
    model_version: str = "rules_v1"   # "rules_v1" until CatBoost is trained
    processing_time_ms: int = 0
    generated_at: datetime = Field(default_factory=datetime.now)

    requires_human_approval: bool = True  # ALWAYS True — cannot be overridden


# ── IE2 Request ───────────────────────────────────────────────────────────────

class RecommendationRequest(BaseModel):
    """
    Request body for POST /recommend.
    EEP sends this after getting CompetitorSignals from IE1.
    """
    sku_id: str
    product_name: str
    brand: str
    category: str

    # Current state
    retail_price_usd: float = Field(gt=0, le=10_000)
    cost_price_usd: float = Field(gt=0, le=10_000)
    current_stock: int = Field(ge=0, le=100_000)
    days_since_launch: int = Field(ge=0, le=3650, default=180)
    initial_stock: int = Field(ge=1, le=100_000, default=1)

    # Optional — v2 when POS data is available
    days_since_last_discount: int = Field(default=999, ge=0, le=3650)
    days_at_current_price: int = Field(default=30, ge=0, le=3650)

    # Competitor signals from IE1
    competitor_signals: Optional[CompetitorSignals] = None

    @field_validator("cost_price_usd")
    @classmethod
    def cost_below_retail(cls, v, info):
        retail = info.data.get("retail_price_usd", float("inf"))
        if v >= retail:
            raise ValueError("cost_price_usd must be less than retail_price_usd")
        return v


class BatchRecommendationRequest(BaseModel):
    """Request body for POST /recommend/batch. Max 50 SKUs."""
    items: list[RecommendationRequest] = Field(min_length=1, max_length=50)
