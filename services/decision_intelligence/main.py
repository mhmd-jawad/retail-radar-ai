"""
Local Decision Intelligence API for Postman testing.

This service is intentionally separate from MLflow's own serving mechanism.
It loads the CatBoost model that was exported from the winning MLflow run and
hosts a normal FastAPI application locally.

Run from the repo root:
    py -m uvicorn services.decision_intelligence.main:app --port 8002

Default local API key:
    ie2-local-postman-key
"""

from __future__ import annotations

import json
import os
import time
from datetime import date as _date, datetime
from pathlib import Path

import mlflow
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

from .features.engineer import (
    BRAND_TIER,
    DEFAULT_INVENTORY_AT_COST,
    DEFAULT_TOTAL_ASSETS,
    EVENT_WINDOWS,
    _estimate_daily_demand,
    _get_seasonal_multiplier,
)
from .rules.engine import run_rules
from .schemas import (
    BatchRecommendationRequest,
    RecommendationRequest,
    RecommendationResult,
    RuleOverride,
    SHAPFeature,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL_META_PATH = ROOT / "services" / "decision_intelligence" / "models" / "catboost_decision" / "meta.json"
LOCAL_MODEL_EXPORT_DIR = (
    ROOT
    / "services"
    / "decision_intelligence"
    / "models"
    / "mlflow_export"
    / "retail_radar_decision_model_from_trial_017"
)

DEFAULT_LOCAL_API_KEY = "ie2-local-postman-key"
CONFIDENCE_THRESHOLD = 0.45
LABEL_INV = {0: "HOLD", 1: "MARKDOWN", 2: "PROMOTE", 3: "CLEAR"}
DEFAULT_CASH_RUNWAY_MONTHS = 3.0
DEFAULT_INVENTORY_INTENSITY = round(DEFAULT_INVENTORY_AT_COST / DEFAULT_TOTAL_ASSETS, 4)
INVENTORY_MEDIAN_PROXY = {
    "footwear": 42.0,
    "football_boots": 30.0,
    "apparel": 55.0,
    "sportswear": 45.0,
    "swimwear": 24.0,
    "accessories": 35.0,
    "kids": 36.0,
    "lifestyle": 40.0,
    "other": 40.0,
}

_API_KEY = os.environ.get("IE2_API_KEY", DEFAULT_LOCAL_API_KEY)
print(f"INFO: IE2 API key ready for local testing: {_API_KEY}")

app = FastAPI(
    title="Retail Radar AI - Decision Intelligence API",
    description="Local API for testing the MLflow-exported CatBoost decision model.",
    version="2.0.0",
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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _verify_api_key(key: str | None = Security(_api_key_header)):
    if not key or key != _API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")


metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

DECISION_COUNTER = Counter(
    "ie2_decisions_total",
    "Count of recommendations by decision class",
    ["decision"],
)
RULE_OVERRIDE_COUNTER = Counter(
    "ie2_rule_overrides_total",
    "Count of hard rule overrides",
    ["rule_id"],
)
FALLBACK_COUNTER = Counter(
    "ie2_fallback_total",
    "Count of HOLD fallbacks due to low confidence",
)
REQUEST_LATENCY = Histogram(
    "ie2_request_duration_seconds",
    "Request latency in seconds",
    ["endpoint"],
)
AVG_CONFIDENCE = Gauge(
    "ie2_avg_confidence",
    "Rolling average model confidence",
)


def _load_model_meta() -> dict:
    if not MODEL_META_PATH.exists():
        return {}
    return json.loads(MODEL_META_PATH.read_text(encoding="utf-8"))


MODEL_META = _load_model_meta()
MODEL_FEATURE_COLUMNS = MODEL_META.get("feature_cols", [])
MODEL_VERSION = f"mlflow_export:{LOCAL_MODEL_EXPORT_DIR.name}"
MODEL_SOURCE = str(LOCAL_MODEL_EXPORT_DIR)
MODEL_LOADER_ERROR = None
REGISTERED_MODEL = None

try:
    REGISTERED_MODEL = mlflow.catboost.load_model(str(LOCAL_MODEL_EXPORT_DIR))
except Exception as exc:  # pragma: no cover
    MODEL_LOADER_ERROR = str(exc)
    MODEL_VERSION = "rules_fallback"


def _normalize_category(category: str | None) -> str:
    return str(category or "other").strip().lower().replace(" ", "_")


def _market_position_from_gap(price_gap: float) -> str:
    if price_gap > 0.15:
        return "premium"
    if price_gap > 0.05:
        return "above_market"
    if price_gap > -0.05:
        return "at_market"
    if price_gap > -0.15:
        return "below_market"
    return "deep_value"


def _build_model_features(req: RecommendationRequest) -> dict:
    comp = req.competitor_signals
    category = _normalize_category(req.category)
    brand = str(req.brand or "Unknown").strip()

    comp_gap = comp.price_gap_pct if comp else 0.0
    comp_on_sale = comp.competitors_on_sale_count if comp else 0
    comp_oos = comp.competitors_out_of_stock_count if comp else 0
    comp_count = comp.num_competitors_tracked if comp else 0

    margin_pct = (
        (req.retail_price_usd - req.cost_price_usd) / req.retail_price_usd * 100
        if req.retail_price_usd > 0 else 0.0
    )
    season_sell_through = 1 - (req.current_stock / req.initial_stock) if req.initial_stock > 0 else 0.0
    avg_daily = _estimate_daily_demand(req.current_stock, category, comp_count, req.retail_price_usd)
    days_of_supply = round(req.current_stock / avg_daily, 1) if avg_daily > 0 else 9999.0
    month = _date.today().month
    next_month = (month % 12) + 1
    seasonality_score = _get_seasonal_multiplier(month, category)
    base_seasonality = _get_seasonal_multiplier(month)
    stock_median = INVENTORY_MEDIAN_PROXY.get(category, INVENTORY_MEDIAN_PROXY["other"])

    return {
        "brand": brand,
        "category": category,
        "days_of_supply": days_of_supply,
        "stock_coverage_ratio": round(days_of_supply / 30.0, 2),
        "stockout_risk": 1 if days_of_supply < 14 else 0,
        "total_qty": req.current_stock,
        "inventory_vs_median": round(req.current_stock / max(stock_median, 1.0), 3),
        "current_margin_pct": round(margin_pct, 2),
        "discount_depth_last_30d": 0.0,
        "days_since_last_discount": req.days_since_last_discount,
        "days_at_current_price": req.days_at_current_price,
        "retail_price_usd": req.retail_price_usd,
        "price_gap_pct": comp_gap,
        "competitors_on_sale": comp_on_sale,
        "competitors_out_of_stock": comp_oos,
        "num_competitors": comp_count,
        "market_position": _market_position_from_gap(comp_gap),
        "days_since_launch": req.days_since_launch,
        "season_sell_through_pct": round(min(max(season_sell_through, 0.0), 1.0), 4),
        "brand_tier": BRAND_TIER.get(brand, "tier2"),
        "cost_price_usd": req.cost_price_usd,
        "seasonality_score": round(seasonality_score, 3),
        "category_seasonal_boost": round(seasonality_score - base_seasonality, 3),
        "event_proximity_score": round(EVENT_WINDOWS.get(month, ("none", 0.0))[1], 3),
        "next_month_seasonality": round(_get_seasonal_multiplier(next_month, category), 3),
        "cash_runway_months": DEFAULT_CASH_RUNWAY_MONTHS,
        "cash_tight": 0,
        "inventory_intensity": DEFAULT_INVENTORY_INTENSITY,
    }


def _predict_with_registered_model(features: dict) -> tuple[str, float]:
    if REGISTERED_MODEL is None:
        raise RuntimeError(MODEL_LOADER_ERROR or "Registered model is not loaded.")
    if not MODEL_FEATURE_COLUMNS:
        raise RuntimeError("Model feature columns are unavailable in meta.json.")

    frame = pd.DataFrame(
        [{column: features.get(column) for column in MODEL_FEATURE_COLUMNS}],
        columns=MODEL_FEATURE_COLUMNS,
    )
    probabilities = REGISTERED_MODEL.predict_proba(frame)[0]
    best_idx = max(range(len(probabilities)), key=lambda idx: probabilities[idx])
    return LABEL_INV.get(best_idx, "HOLD"), float(probabilities[best_idx])


def _build_rule_explanations(features: dict, decision: str) -> list[SHAPFeature]:
    explanations: list[SHAPFeature] = []
    dos = float(features.get("days_of_supply", 9999))
    margin = float(features.get("current_margin_pct", 0))
    price_gap = float(features.get("price_gap_pct", 0))
    seasonality = float(features.get("seasonality_score", 1.0))
    on_sale_comps = int(features.get("competitors_on_sale", 0))

    if dos < 14:
        explanations.append(
            SHAPFeature(
                feature_name="days_of_supply",
                feature_value=dos,
                shap_value=0.35,
                direction="decreases_probability",
                explanation=f"Only {dos:.0f} days of stock remaining - reorder risk.",
            )
        )
    elif dos > 120:
        explanations.append(
            SHAPFeature(
                feature_name="days_of_supply",
                feature_value=dos,
                shap_value=0.30,
                direction="increases_probability",
                explanation=f"{dos:.0f} days of supply - well above healthy range.",
            )
        )

    if price_gap > 0.05:
        explanations.append(
            SHAPFeature(
                feature_name="price_gap_pct",
                feature_value=price_gap,
                shap_value=0.25,
                direction="increases_probability",
                explanation=f"You are {price_gap:.0%} more expensive than the cheapest competitor.",
            )
        )
    elif price_gap < -0.05:
        explanations.append(
            SHAPFeature(
                feature_name="price_gap_pct",
                feature_value=price_gap,
                shap_value=0.20,
                direction="decreases_probability",
                explanation=f"You are {abs(price_gap):.0%} cheaper than the market.",
            )
        )

    if margin < 25:
        explanations.append(
            SHAPFeature(
                feature_name="current_margin_pct",
                feature_value=margin,
                shap_value=0.25,
                direction="increases_probability",
                explanation=f"Margin is {margin:.0f}% - below the critical threshold.",
            )
        )
    elif margin > 45:
        explanations.append(
            SHAPFeature(
                feature_name="current_margin_pct",
                feature_value=margin,
                shap_value=0.20,
                direction="decreases_probability",
                explanation=f"Strong margin at {margin:.0f}% - no urgent discount pressure.",
            )
        )

    if seasonality >= 1.15:
        explanations.append(
            SHAPFeature(
                feature_name="seasonality_score",
                feature_value=seasonality,
                shap_value=0.18,
                direction="increases_probability",
                explanation=f"Peak demand season at roughly {seasonality:.0%} of baseline demand.",
            )
        )

    if on_sale_comps >= 3:
        explanations.append(
            SHAPFeature(
                feature_name="competitors_on_sale",
                feature_value=on_sale_comps,
                shap_value=0.15,
                direction="increases_probability",
                explanation=f"{on_sale_comps} competitors are currently discounting this product.",
            )
        )

    while len(explanations) < 5:
        explanations.append(
            SHAPFeature(
                feature_name="model_baseline",
                feature_value=decision,
                shap_value=0.05,
                direction="increases_probability",
                explanation="Base decision signal from inventory and market context.",
            )
        )

    return explanations[:5]


def _rules_only_decision(features: dict, rule_result: dict) -> tuple[str, float, list[SHAPFeature]]:
    blocked = set(rule_result.get("blocked_actions", []))
    nudges = set(rule_result.get("nudges", []))

    dos = float(features.get("days_of_supply", 9999))
    margin = float(features.get("current_margin_pct", 0))
    price_gap = float(features.get("price_gap_pct", 0))
    seasonality = float(features.get("seasonality_score", 1.0))
    sell_through = float(features.get("season_sell_through_pct", 0))
    total_qty = int(features.get("total_qty", 0))
    on_sale_comps = int(features.get("competitors_on_sale", 0))
    event_proximity = float(features.get("event_proximity_score", 0))

    candidates: dict[str, float] = {}

    if "CLEAR" not in blocked:
        if dos > 180 and margin < 35:
            candidates["CLEAR"] = 0.85
        elif dos > 150 and sell_through < 0.15:
            candidates["CLEAR"] = 0.65

    if "MARKDOWN" not in blocked:
        md_signals = 0
        if dos > 90:
            md_signals += 1
        if price_gap > 0.08:
            md_signals += 1
        if on_sale_comps >= 2:
            md_signals += 1
        if sell_through < 0.3:
            md_signals += 1
        if md_signals >= 2:
            candidates["MARKDOWN"] = min(0.90, 0.50 + md_signals * 0.10)

    if "PROMOTE" not in blocked:
        promo_signals = 0
        if seasonality >= 1.10:
            promo_signals += 1
        if 20 < dos < 120:
            promo_signals += 1
        if margin >= 35:
            promo_signals += 1
        if event_proximity >= 0.5:
            promo_signals += 1
        if "PROMOTE" in nudges:
            promo_signals += 1
        if promo_signals >= 3:
            candidates["PROMOTE"] = min(0.85, 0.50 + promo_signals * 0.08)

    if "HOLD" not in blocked:
        hold_score = 0.55
        if total_qty < 30:
            hold_score += 0.10
        if features.get("market_position") in ("at_market", "below_market"):
            hold_score += 0.05
        if "HOLD" in nudges:
            hold_score += 0.10
        candidates["HOLD"] = min(0.80, hold_score)

    if not candidates:
        decision = "HOLD"
        confidence = 0.40
    else:
        decision = max(candidates, key=lambda item: candidates[item])
        confidence = candidates[decision]

    return decision, round(confidence, 3), _build_rule_explanations(features, decision)


def _recommend_single(req: RecommendationRequest) -> RecommendationResult:
    t_start = time.time()
    margin_pct = (
        (req.retail_price_usd - req.cost_price_usd) / req.retail_price_usd * 100
        if req.retail_price_usd > 0 else 0.0
    )
    features = _build_model_features(req)
    rule_result = run_rules(features)

    rule_override = None
    fallback_used = False

    if rule_result["hard_override"]:
        fired = rule_result["rules_fired"][0]
        decision = rule_result["forced_action"]
        confidence = 1.0 if rule_result["rule_override"] == "DEAD_STOCK_CLEAR" else 0.90
        shap_top5 = [
            SHAPFeature(
                feature_name="hard_rule",
                feature_value=rule_result["rule_override"],
                shap_value=1.0,
                direction="increases_probability",
                explanation=fired["reason"],
            )
            for _ in range(5)
        ]
        rule_override = RuleOverride(
            rule_id=fired["rule_id"],
            override_strength=fired["override_strength"],
            reason=fired["reason"],
            blocked_actions=fired.get("blocks", []),
        )
        RULE_OVERRIDE_COUNTER.labels(rule_id=fired["rule_id"]).inc()
    else:
        if REGISTERED_MODEL is not None:
            decision, confidence = _predict_with_registered_model(features)
            shap_top5 = _build_rule_explanations(features, decision)
        else:
            decision, confidence, shap_top5 = _rules_only_decision(features, rule_result)

        if confidence < CONFIDENCE_THRESHOLD:
            decision = "HOLD"
            confidence = 0.40
            fallback_used = True
            FALLBACK_COUNTER.inc()

    suggested_price = None
    suggested_discount = None
    margin_after = None
    if decision == "MARKDOWN":
        from stylepulse.analyzers.thresholds import get_markdown_recommendation

        markdown = get_markdown_recommendation(features["days_of_supply"])
        suggested_discount = markdown["discount_pct"] if markdown else 15
        suggested_price = round(req.retail_price_usd * (1 - suggested_discount / 100), 2)
        margin_after = (
            round((suggested_price - req.cost_price_usd) / suggested_price * 100, 1)
            if suggested_price > 0 else None
        )
    elif decision in ("HOLD", "PROMOTE"):
        margin_after = round(margin_pct, 1)

    explanation = rule_override.reason if rule_override else shap_top5[0].explanation

    DECISION_COUNTER.labels(decision=decision).inc()
    AVG_CONFIDENCE.set(confidence)

    return RecommendationResult(
        sku_id=req.sku_id,
        product_name=req.product_name,
        recommendation=decision,
        confidence=confidence,
        explanation=explanation,
        shap_top5=shap_top5,
        rule_override=rule_override,
        fallback_used=fallback_used,
        suggested_discount_pct=suggested_discount,
        suggested_price_usd=suggested_price,
        margin_after_action_pct=margin_after,
        model_version=MODEL_VERSION,
        processing_time_ms=int((time.time() - t_start) * 1000),
    )


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "ie2_decision_intelligence",
        "model_version": MODEL_VERSION,
        "model_source": MODEL_SOURCE,
        "registered_model_loaded": REGISTERED_MODEL is not None,
        "model_loader_error": MODEL_LOADER_ERROR,
        "api_key_hint": "Use X-API-Key: ie2-local-postman-key unless you set IE2_API_KEY manually.",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/recommend", response_model=RecommendationResult, dependencies=[Depends(_verify_api_key)])
def recommend(req: RecommendationRequest):
    with REQUEST_LATENCY.labels(endpoint="/recommend").time():
        return _recommend_single(req)


@app.post("/recommend/batch", response_model=list[RecommendationResult], dependencies=[Depends(_verify_api_key)])
def recommend_batch(req: BatchRecommendationRequest):
    with REQUEST_LATENCY.labels(endpoint="/recommend/batch").time():
        return [_recommend_single(item) for item in req.items]
