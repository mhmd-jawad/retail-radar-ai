"""
IE2 — Decision Intelligence Service.
FastAPI application. Port 8002.

Decision pipeline per SKU:
  1. Hard Rules Engine  →  may short-circuit with absolute/strong override
  2. Feature assembly   →  build SKUFeatures from request + IE1 signals
  3. Model inference    →  CatBoost (v2) or enhanced rules engine (v1)
  4. Rule reconciliation →  filter blocked actions from model output
  5. Confidence check   →  < 0.45 → return HOLD fallback
  6. SHAP computation   →  top 5 features per prediction
  7. Plain English       →  translate SHAP to owner-readable reasons
  8. Return RecommendationResult

Current model version: rules_v1 (CatBoost to be added in v2)

Run:
    uvicorn services.decision_intelligence.main:app --port 8002 --reload
"""

import time
from datetime import date as _date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

from .schemas import (
    BatchRecommendationRequest,
    RecommendationRequest,
    RecommendationResult,
    RuleOverride,
    SHAPFeature,
)
from .rules.engine import run_rules
from .features.engineer import (
    _estimate_daily_demand,
    _get_seasonal_multiplier,
    CATEGORY_VELOCITY,
    EVENT_WINDOWS,
)

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="StylePulse AI — IE2 Decision Intelligence",
    description="Retail recommendation engine: HOLD / MARKDOWN / PROMOTE / CLEAR",
    version="1.0.0",
)

ALLOWED_ORIGINS = [
    "http://localhost:8000",   # EEP dashboard (local dev)
    "http://localhost:3000",   # frontend dev server
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Prometheus metrics
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

MODEL_VERSION = "rules_v1"
CONFIDENCE_THRESHOLD = 0.45

# ── Decision engine (v1 — rules-based) ───────────────────────────────────────

def _rules_only_decision(features: dict, rule_result: dict) -> tuple[str, float, list[SHAPFeature]]:
    """
    v1 decision engine: enhanced rules with confidence scoring.

    Returns (decision, confidence, shap_top5).

    When CatBoost is integrated (v2), this function is replaced by
    CatBoost inference + real SHAP values. The interface stays identical.
    """
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

    # Scored candidates: build confidence for each eligible decision
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
        hold_score = 0.55  # default
        if total_qty < 30:
            hold_score += 0.10
        if features.get("market_position") in ("at_market", "below_market"):
            hold_score += 0.05
        if "HOLD" in nudges:
            hold_score += 0.10
        candidates["HOLD"] = min(0.80, hold_score)

    # Pick highest-confidence eligible decision
    if not candidates:
        decision = "HOLD"
        confidence = 0.40
    else:
        decision = max(candidates, key=lambda d: candidates[d])
        confidence = candidates[decision]

    # Build synthetic SHAP-style top-5 explanations from rules model
    # v2: replace with real SHAP values from CatBoost TreeSHAP
    shap_top5 = _build_rule_explanations(features, decision, candidates)

    return decision, round(confidence, 3), shap_top5


def _build_rule_explanations(features: dict, decision: str,
                              candidates: dict) -> list[SHAPFeature]:
    """
    Build plain-English explanations for the rules-based decision.
    v2: replace with real SHAP values from TreeSHAP.
    """
    explanations = []
    dos = float(features.get("days_of_supply", 9999))
    margin = float(features.get("current_margin_pct", 0))
    price_gap = float(features.get("price_gap_pct", 0))
    seasonality = float(features.get("seasonality_score", 1.0))
    on_sale_comps = int(features.get("competitors_on_sale", 0))

    if dos < 14:
        explanations.append(SHAPFeature(
            feature_name="days_of_supply",
            feature_value=dos,
            shap_value=0.35,
            direction="decreases_probability",
            explanation=f"Only {dos:.0f} days of stock remaining — reorder risk.",
        ))
    elif dos > 120:
        explanations.append(SHAPFeature(
            feature_name="days_of_supply",
            feature_value=dos,
            shap_value=0.30,
            direction="increases_probability",
            explanation=f"{dos:.0f} days of supply — well above healthy range (45-90).",
        ))

    if price_gap > 0.05:
        explanations.append(SHAPFeature(
            feature_name="price_gap_pct",
            feature_value=price_gap,
            shap_value=0.25,
            direction="increases_probability",
            explanation=f"You are {price_gap:.0%} more expensive than the cheapest competitor.",
        ))
    elif price_gap < -0.05:
        explanations.append(SHAPFeature(
            feature_name="price_gap_pct",
            feature_value=price_gap,
            shap_value=0.20,
            direction="decreases_probability",
            explanation=f"You are {abs(price_gap):.0%} cheaper than the market — room to raise price.",
        ))

    if margin > 45:
        explanations.append(SHAPFeature(
            feature_name="current_margin_pct",
            feature_value=margin,
            shap_value=0.20,
            direction="decreases_probability",
            explanation=f"Strong margin at {margin:.0f}% — no pressure to discount.",
        ))
    elif margin < 25:
        explanations.append(SHAPFeature(
            feature_name="current_margin_pct",
            feature_value=margin,
            shap_value=0.25,
            direction="increases_probability",
            explanation=f"Margin is {margin:.0f}% — below critical threshold of 25%.",
        ))

    if seasonality >= 1.15:
        explanations.append(SHAPFeature(
            feature_name="seasonality_score",
            feature_value=seasonality,
            shap_value=0.18,
            direction="increases_probability",
            explanation=f"Peak demand season — {seasonality:.0%} of baseline demand expected.",
        ))
    elif seasonality <= 0.80:
        explanations.append(SHAPFeature(
            feature_name="seasonality_score",
            feature_value=seasonality,
            shap_value=0.15,
            direction="decreases_probability",
            explanation=f"Slow season — only {seasonality:.0%} of baseline demand expected.",
        ))

    if on_sale_comps >= 3:
        explanations.append(SHAPFeature(
            feature_name="competitors_on_sale",
            feature_value=on_sale_comps,
            shap_value=0.15,
            direction="increases_probability",
            explanation=f"{on_sale_comps} competitors are currently discounting this product.",
        ))

    # Pad to 5 if needed
    while len(explanations) < 5:
        explanations.append(SHAPFeature(
            feature_name="model_baseline",
            feature_value=0.0,
            shap_value=0.05,
            direction="increases_probability",
            explanation="Base prediction from inventory and market signals.",
        ))

    return explanations[:5]


# ── Core recommendation logic ─────────────────────────────────────────────────

def _recommend_single(req: RecommendationRequest) -> RecommendationResult:
    """Run the full decision pipeline for a single SKU."""
    t_start = time.time()

    # Assemble features dict for the rules engine
    comp_gap = (
        req.competitor_signals.price_gap_pct
        if req.competitor_signals else 0.0
    )
    comp_on_sale = (
        req.competitor_signals.competitors_on_sale_count
        if req.competitor_signals else 0
    )
    comp_oos = (
        req.competitor_signals.competitors_out_of_stock_count
        if req.competitor_signals else 0
    )
    comp_conf = (
        req.competitor_signals.confidence_score
        if req.competitor_signals else 0.2
    )

    margin_pct = (
        (req.retail_price_usd - req.cost_price_usd) / req.retail_price_usd * 100
        if req.retail_price_usd > 0 else 0.0
    )
    season_sell_through = 1 - (req.current_stock / req.initial_stock) if req.initial_stock > 0 else 0.0

    features = {
        "sku_id": req.sku_id,
        "category": req.category,
        "brand": req.brand,
        "total_qty": req.current_stock,
        "retail_price_usd": req.retail_price_usd,
        "cost_price_usd": req.cost_price_usd,
        "current_margin_pct": margin_pct,
        "days_since_launch": req.days_since_launch,
        "days_since_last_discount": req.days_since_last_discount,
        "days_at_current_price": req.days_at_current_price,
        "season_sell_through_pct": max(0.0, min(1.0, season_sell_through)),
        "price_gap_pct": comp_gap,
        "competitors_on_sale": comp_on_sale,
        "competitors_out_of_stock": comp_oos,
        "competitor_confidence": comp_conf,
        "market_position": "at_market",  # will be updated by feature engineer in v2
        "suggested_discount_pct": 0,     # no pending suggestion at this step
    }

    # Seasonality for this SKU
    today_month = _date.today().month
    features["seasonality_score"] = _get_seasonal_multiplier(today_month, req.category)
    features["event_proximity_score"] = EVENT_WINDOWS.get(today_month, ("none", 0.0))[1]

    # DOS estimate
    num_comp = comp_oos  # crude proxy
    avg_daily = _estimate_daily_demand(
        req.current_stock, req.category, num_comp, req.retail_price_usd
    )
    features["days_of_supply"] = (
        round(req.current_stock / avg_daily, 1) if avg_daily > 0 else 9999.0
    )

    # Step 1: Hard rules
    rule_result = run_rules(features)

    rule_override = None
    _fallback_used = False
    if rule_result["hard_override"]:
        decision = rule_result["forced_action"]
        confidence = 1.0 if rule_result["rule_override"] == "DEAD_STOCK_CLEAR" else 0.90
        shap_top5 = [
            SHAPFeature(
                feature_name="hard_rule",
                feature_value=rule_result["rule_override"],
                shap_value=1.0,
                direction="increases_probability",
                explanation=rule_result["rules_fired"][0]["reason"],
            )
            for _ in range(5)
        ]
        fired = rule_result["rules_fired"][0]
        rule_override = RuleOverride(
            rule_id=fired["rule_id"],
            override_strength=fired["override_strength"],
            reason=fired["reason"],
            blocked_actions=fired.get("blocks", []),
        )
        RULE_OVERRIDE_COUNTER.labels(rule_id=fired["rule_id"]).inc()
    else:
        # Step 2-6: ML/rules-based inference
        decision, confidence, shap_top5 = _rules_only_decision(features, rule_result)

        # Step 5: Confidence fallback
        if confidence < CONFIDENCE_THRESHOLD:
            decision = "HOLD"
            confidence = 0.40
            _fallback_used = True
            FALLBACK_COUNTER.inc()

    # Markdown price calculation
    suggested_price = None
    suggested_discount = None
    margin_after = None
    if decision == "MARKDOWN":
        from stylepulse.analyzers.thresholds import get_markdown_recommendation
        md = get_markdown_recommendation(features["days_of_supply"])
        disc_pct = md["discount_pct"] if md else 15
        suggested_discount = disc_pct
        suggested_price = round(req.retail_price_usd * (1 - disc_pct / 100), 2)
        margin_after = round(
            (suggested_price - req.cost_price_usd) / suggested_price * 100, 1
        ) if suggested_price > 0 else None
    elif decision in ("HOLD", "PROMOTE"):
        margin_after = round(margin_pct, 1)

    # Build explanation summary
    explanation = shap_top5[0].explanation if shap_top5 else "No signals available."
    if rule_override:
        explanation = rule_override.reason

    DECISION_COUNTER.labels(decision=decision).inc()
    AVG_CONFIDENCE.set(confidence)

    ms = int((time.time() - t_start) * 1000)

    return RecommendationResult(
        sku_id=req.sku_id,
        product_name=req.product_name,
        recommendation=decision,
        confidence=confidence,
        explanation=explanation,
        shap_top5=shap_top5,
        rule_override=rule_override,
        fallback_used=_fallback_used,
        suggested_discount_pct=suggested_discount,
        suggested_price_usd=suggested_price,
        margin_after_action_pct=margin_after,
        model_version=MODEL_VERSION,
        processing_time_ms=ms,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "healthy", "service": "ie2_decision_intelligence",
            "model_version": MODEL_VERSION, "timestamp": datetime.now().isoformat()}


@app.post("/recommend", response_model=RecommendationResult)
def recommend(req: RecommendationRequest):
    """Single SKU recommendation."""
    with REQUEST_LATENCY.labels(endpoint="/recommend").time():
        return _recommend_single(req)


@app.post("/recommend/batch", response_model=list[RecommendationResult])
def recommend_batch(req: BatchRecommendationRequest):
    """Batch recommendation for up to 50 SKUs."""
    with REQUEST_LATENCY.labels(endpoint="/recommend/batch").time():
        return [_recommend_single(item) for item in req.items]
