"""
Synthetic edge-case benchmark for the IE2 Decision Intelligence service.

Run from the repo root:
    py -m services.decision_intelligence.evaluation.edge_case_benchmark
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from services.decision_intelligence.main import (
    MODEL_FEATURE_COLUMNS,
    MODEL_META,
    RecommendationRequest,
    _build_model_features,
    _recommend_single,
)
from services.decision_intelligence.schemas import CompetitorSignals


ROOT = Path(__file__).resolve().parents[3]
LABELS = ["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"]


@dataclass(frozen=True)
class EdgeCase:
    case_id: str
    expected_label: str
    description: str
    label_rationale: str
    request: dict[str, Any]


EDGE_CASES: list[EdgeCase] = [
    EdgeCase(
        case_id="hold_low_stock_protection",
        expected_label="HOLD",
        description="Very low unit count with healthy margin and competitor stockouts.",
        label_rationale="Scarcity should protect price; low-stock protection should block actioning downward.",
        request={
            "sku_id": "EC-001",
            "product_name": "Scarce Boot",
            "brand": "Adidas",
            "category": "football_boots",
            "retail_price_usd": 140,
            "cost_price_usd": 72,
            "current_stock": 8,
            "initial_stock": 28,
            "days_since_launch": 48,
            "days_since_last_discount": 999,
            "days_at_current_price": 40,
            "competitor_signals": {
                "sku_id": "EC-001",
                "competitor_min_price": 142,
                "competitor_avg_price": 145,
                "price_gap_pct": -0.014,
                "competitors_on_sale_count": 0,
                "competitors_out_of_stock_count": 2,
                "num_competitors_tracked": 4,
                "data_freshness_hours": 18,
                "confidence_score": 0.88,
            },
        },
    ),
    EdgeCase(
        case_id="hold_recent_discount_cooldown",
        expected_label="HOLD",
        description="Good margin and healthy stock, but it was discounted only 8 days ago.",
        label_rationale="The cooldown window should discourage another markdown immediately after a recent discount.",
        request={
            "sku_id": "EC-002",
            "product_name": "Recently Discounted Tee",
            "brand": "Puma",
            "category": "apparel",
            "retail_price_usd": 60,
            "cost_price_usd": 31,
            "current_stock": 40,
            "initial_stock": 70,
            "days_since_launch": 70,
            "days_since_last_discount": 8,
            "days_at_current_price": 8,
            "competitor_signals": {
                "sku_id": "EC-002",
                "competitor_min_price": 58,
                "competitor_avg_price": 59,
                "price_gap_pct": 0.033,
                "competitors_on_sale_count": 1,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 5,
                "data_freshness_hours": 10,
                "confidence_score": 0.93,
            },
        },
    ),
    EdgeCase(
        case_id="hold_margin_floor_protection",
        expected_label="HOLD",
        description="Mid-stock apparel where gross margin is only about 30.5%.",
        label_rationale="The margin floor should block markdown pressure and preserve profitability.",
        request={
            "sku_id": "EC-003",
            "product_name": "Thin Margin Jacket",
            "brand": "New Balance",
            "category": "apparel",
            "retail_price_usd": 82,
            "cost_price_usd": 57,
            "current_stock": 44,
            "initial_stock": 70,
            "days_since_launch": 88,
            "days_since_last_discount": 999,
            "days_at_current_price": 31,
            "competitor_signals": {
                "sku_id": "EC-003",
                "competitor_min_price": 79,
                "competitor_avg_price": 80,
                "price_gap_pct": 0.0366,
                "competitors_on_sale_count": 2,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 4,
                "data_freshness_hours": 14,
                "confidence_score": 0.86,
            },
        },
    ),
    EdgeCase(
        case_id="hold_margin_boundary_exact_floor",
        expected_label="HOLD",
        description="Boundary case at exactly 35% margin with moderate overpricing and April event pressure.",
        label_rationale="This is a cautionary HOLD edge case because margin is only just acceptable for intervention.",
        request={
            "sku_id": "EC-004",
            "product_name": "Boundary Margin Hold",
            "brand": "Nike",
            "category": "footwear",
            "retail_price_usd": 100,
            "cost_price_usd": 65,
            "current_stock": 62,
            "initial_stock": 90,
            "days_since_launch": 115,
            "days_since_last_discount": 999,
            "days_at_current_price": 36,
            "competitor_signals": {
                "sku_id": "EC-004",
                "competitor_min_price": 92,
                "competitor_avg_price": 94,
                "price_gap_pct": 0.08,
                "competitors_on_sale_count": 2,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 4,
                "data_freshness_hours": 8,
                "confidence_score": 0.91,
            },
        },
    ),
    EdgeCase(
        case_id="hold_stable_high_dos_low_competition",
        expected_label="HOLD",
        description="High days of supply but almost no competitive pressure and a neutral market position.",
        label_rationale="The SKU is stale-looking on stock cover, but not pressured enough to justify promotion or markdown.",
        request={
            "sku_id": "EC-005",
            "product_name": "Stable Cargo Short",
            "brand": "Crocs",
            "category": "lifestyle",
            "retail_price_usd": 150,
            "cost_price_usd": 76,
            "current_stock": 34,
            "initial_stock": 58,
            "days_since_launch": 125,
            "days_since_last_discount": 999,
            "days_at_current_price": 44,
            "competitor_signals": {
                "sku_id": "EC-005",
                "competitor_min_price": 151,
                "competitor_avg_price": 154,
                "price_gap_pct": -0.0067,
                "competitors_on_sale_count": 0,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 1,
                "data_freshness_hours": 12,
                "confidence_score": 0.90,
            },
        },
    ),
    EdgeCase(
        case_id="markdown_overpriced_heavy_inventory",
        expected_label="MARKDOWN",
        description="Lifestyle sneaker with elevated stock cover, heavy sale pressure, and a large premium to market.",
        label_rationale="The SKU is overpriced versus market while inventory is still piling up, so markdown is warranted.",
        request={
            "sku_id": "EC-006",
            "product_name": "Overpriced Lifestyle Sneaker",
            "brand": "Nike",
            "category": "lifestyle",
            "retail_price_usd": 145,
            "cost_price_usd": 72,
            "current_stock": 100,
            "initial_stock": 130,
            "days_since_launch": 150,
            "days_since_last_discount": 999,
            "days_at_current_price": 60,
            "competitor_signals": {
                "sku_id": "EC-006",
                "competitor_min_price": 102,
                "competitor_avg_price": 110,
                "price_gap_pct": 0.2966,
                "competitors_on_sale_count": 4,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 6,
                "data_freshness_hours": 8,
                "confidence_score": 0.95,
            },
        },
    ),
    EdgeCase(
        case_id="markdown_competitor_sale_pressure",
        expected_label="MARKDOWN",
        description="Sportswear top facing intense discounting from many competitors.",
        label_rationale="The competitive landscape is hostile and the product is materially overpriced, so markdown is the safer move.",
        request={
            "sku_id": "EC-007",
            "product_name": "Promo-Pressured Warmup Top",
            "brand": "Puma",
            "category": "sportswear",
            "retail_price_usd": 125,
            "cost_price_usd": 54,
            "current_stock": 88,
            "initial_stock": 110,
            "days_since_launch": 135,
            "days_since_last_discount": 50,
            "days_at_current_price": 65,
            "competitor_signals": {
                "sku_id": "EC-007",
                "competitor_min_price": 88,
                "competitor_avg_price": 94,
                "price_gap_pct": 0.2960,
                "competitors_on_sale_count": 5,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 7,
                "data_freshness_hours": 6,
                "confidence_score": 0.96,
            },
        },
    ),
    EdgeCase(
        case_id="markdown_supported_footwear_case",
        expected_label="MARKDOWN",
        description="Footwear case with strong margin support, elevated stock cover, and premium pricing.",
        label_rationale="This is a clean markdown setup where margin can absorb the action without tripping hard rules.",
        request={
            "sku_id": "EC-008",
            "product_name": "Overpriced City Runner",
            "brand": "New Balance",
            "category": "footwear",
            "retail_price_usd": 150,
            "cost_price_usd": 63,
            "current_stock": 80,
            "initial_stock": 100,
            "days_since_launch": 145,
            "days_since_last_discount": 42,
            "days_at_current_price": 58,
            "competitor_signals": {
                "sku_id": "EC-008",
                "competitor_min_price": 109,
                "competitor_avg_price": 117,
                "price_gap_pct": 0.2733,
                "competitors_on_sale_count": 3,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 5,
                "data_freshness_hours": 7,
                "confidence_score": 0.93,
            },
        },
    ),
    EdgeCase(
        case_id="markdown_cooldown_boundary_21_days",
        expected_label="MARKDOWN",
        description="Cooldown boundary case where the last discount was exactly 21 days ago.",
        label_rationale="The protection rule should stop firing at 21 days, so a renewed markdown becomes valid again.",
        request={
            "sku_id": "EC-009",
            "product_name": "Cooldown Boundary Shorts",
            "brand": "ASICS",
            "category": "apparel",
            "retail_price_usd": 115,
            "cost_price_usd": 49,
            "current_stock": 72,
            "initial_stock": 100,
            "days_since_launch": 140,
            "days_since_last_discount": 21,
            "days_at_current_price": 21,
            "competitor_signals": {
                "sku_id": "EC-009",
                "competitor_min_price": 84,
                "competitor_avg_price": 89,
                "price_gap_pct": 0.2696,
                "competitors_on_sale_count": 4,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 5,
                "data_freshness_hours": 9,
                "confidence_score": 0.93,
            },
        },
    ),
    EdgeCase(
        case_id="markdown_near_clear_but_not_dead_stock",
        expected_label="MARKDOWN",
        description="Very old lifestyle SKU with low sell-through, but not quite enough days of supply to qualify as dead stock.",
        label_rationale="This is intentionally near the CLEAR boundary, but it should still be treated as markdown rather than forced clearance.",
        request={
            "sku_id": "EC-010",
            "product_name": "Near Dead Stock But Not Quite",
            "brand": "Bogner",
            "category": "lifestyle",
            "retail_price_usd": 220,
            "cost_price_usd": 98,
            "current_stock": 95,
            "initial_stock": 104,
            "days_since_launch": 390,
            "days_since_last_discount": 999,
            "days_at_current_price": 110,
            "competitor_signals": {
                "sku_id": "EC-010",
                "competitor_min_price": 162,
                "competitor_avg_price": 170,
                "price_gap_pct": 0.2636,
                "competitors_on_sale_count": 4,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 3,
                "data_freshness_hours": 18,
                "confidence_score": 0.90,
            },
        },
    ),
    EdgeCase(
        case_id="promote_event_ready_runner",
        expected_label="PROMOTE",
        description="Healthy footwear SKU with strong margin and no pricing pressure ahead of an event-rich month.",
        label_rationale="The SKU has enough stock to capture demand and should be pushed rather than discounted.",
        request={
            "sku_id": "EC-011",
            "product_name": "Event Runner",
            "brand": "Nike",
            "category": "footwear",
            "retail_price_usd": 88,
            "cost_price_usd": 42,
            "current_stock": 60,
            "initial_stock": 100,
            "days_since_launch": 60,
            "days_since_last_discount": 999,
            "days_at_current_price": 20,
            "competitor_signals": {
                "sku_id": "EC-011",
                "competitor_min_price": 90,
                "competitor_avg_price": 92,
                "price_gap_pct": -0.0227,
                "competitors_on_sale_count": 0,
                "competitors_out_of_stock_count": 1,
                "num_competitors_tracked": 3,
                "data_freshness_hours": 10,
                "confidence_score": 0.90,
            },
        },
    ),
    EdgeCase(
        case_id="promote_below_market_accessory",
        expected_label="PROMOTE",
        description="Accessory SKU priced below market with healthy stock coverage.",
        label_rationale="The product can use promotion to accelerate demand without sacrificing margin unnecessarily.",
        request={
            "sku_id": "EC-012",
            "product_name": "Impulse Gym Bag",
            "brand": "Adidas",
            "category": "accessories",
            "retail_price_usd": 42,
            "cost_price_usd": 16,
            "current_stock": 34,
            "initial_stock": 60,
            "days_since_launch": 40,
            "days_since_last_discount": 999,
            "days_at_current_price": 14,
            "competitor_signals": {
                "sku_id": "EC-012",
                "competitor_min_price": 47,
                "competitor_avg_price": 49,
                "price_gap_pct": -0.119,
                "competitors_on_sale_count": 0,
                "competitors_out_of_stock_count": 1,
                "num_competitors_tracked": 4,
                "data_freshness_hours": 7,
                "confidence_score": 0.92,
            },
        },
    ),
    EdgeCase(
        case_id="promote_healthy_margin_sportswear",
        expected_label="PROMOTE",
        description="Sportswear hoodie with strong margin, balanced stock, and no recent discount history.",
        label_rationale="This is the classic promotion candidate: enough stock to push and enough margin to support the campaign.",
        request={
            "sku_id": "EC-013",
            "product_name": "Healthy Margin Hoodie",
            "brand": "New Balance",
            "category": "sportswear",
            "retail_price_usd": 78,
            "cost_price_usd": 33,
            "current_stock": 52,
            "initial_stock": 85,
            "days_since_launch": 55,
            "days_since_last_discount": 999,
            "days_at_current_price": 18,
            "competitor_signals": {
                "sku_id": "EC-013",
                "competitor_min_price": 80,
                "competitor_avg_price": 84,
                "price_gap_pct": -0.0256,
                "competitors_on_sale_count": 0,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 3,
                "data_freshness_hours": 11,
                "confidence_score": 0.90,
            },
        },
    ),
    EdgeCase(
        case_id="promote_competitors_oos_apparel",
        expected_label="PROMOTE",
        description="Apparel SKU where multiple competitors are out of stock.",
        label_rationale="Competitor scarcity creates a demand-capture window that should be exploited with promotion.",
        request={
            "sku_id": "EC-014",
            "product_name": "Hot Seller Tee",
            "brand": "Puma",
            "category": "apparel",
            "retail_price_usd": 55,
            "cost_price_usd": 22,
            "current_stock": 46,
            "initial_stock": 70,
            "days_since_launch": 42,
            "days_since_last_discount": 999,
            "days_at_current_price": 16,
            "competitor_signals": {
                "sku_id": "EC-014",
                "competitor_min_price": 56,
                "competitor_avg_price": 58,
                "price_gap_pct": -0.0182,
                "competitors_on_sale_count": 0,
                "competitors_out_of_stock_count": 3,
                "num_competitors_tracked": 4,
                "data_freshness_hours": 9,
                "confidence_score": 0.94,
            },
        },
    ),
    EdgeCase(
        case_id="promote_fast_accessory_at_market",
        expected_label="PROMOTE",
        description="Accessory SKU near market price with quick-moving stock economics.",
        label_rationale="Balanced stock, good margin, and event timing make promotion more attractive than holding.",
        request={
            "sku_id": "EC-015",
            "product_name": "Promo Accessory Alt",
            "brand": "Crocs",
            "category": "accessories",
            "retail_price_usd": 75,
            "cost_price_usd": 34,
            "current_stock": 30,
            "initial_stock": 45,
            "days_since_launch": 100,
            "days_since_last_discount": 999,
            "days_at_current_price": 30,
            "competitor_signals": {
                "sku_id": "EC-015",
                "competitor_min_price": 76,
                "competitor_avg_price": 77,
                "price_gap_pct": -0.0133,
                "competitors_on_sale_count": 0,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 1,
                "data_freshness_hours": 10,
                "confidence_score": 0.92,
            },
        },
    ),
    EdgeCase(
        case_id="clear_dead_stock_swimwear",
        expected_label="CLEAR",
        description="Late-season swimwear with very weak sell-through and premium pricing.",
        label_rationale="Dead stock criteria are clearly met, so full clearance is the only sensible action.",
        request={
            "sku_id": "EC-016",
            "product_name": "Stale Resort Set",
            "brand": "Billabong",
            "category": "swimwear",
            "retail_price_usd": 138,
            "cost_price_usd": 60,
            "current_stock": 88,
            "initial_stock": 100,
            "days_since_launch": 320,
            "days_since_last_discount": 80,
            "days_at_current_price": 65,
            "competitor_signals": {
                "sku_id": "EC-016",
                "competitor_min_price": 96,
                "competitor_avg_price": 101,
                "price_gap_pct": 0.3043,
                "competitors_on_sale_count": 5,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 5,
                "data_freshness_hours": 15,
                "confidence_score": 0.93,
            },
        },
    ),
    EdgeCase(
        case_id="clear_dead_stock_football_boots",
        expected_label="CLEAR",
        description="Old football boots with premium pricing, low sell-through, and long stock cover.",
        label_rationale="This case is squarely in the dead-stock zone and should be forced to clearance.",
        request={
            "sku_id": "EC-017",
            "product_name": "Dead Stock Cleat",
            "brand": "Adidas",
            "category": "football_boots",
            "retail_price_usd": 160,
            "cost_price_usd": 82,
            "current_stock": 75,
            "initial_stock": 86,
            "days_since_launch": 260,
            "days_since_last_discount": 999,
            "days_at_current_price": 80,
            "competitor_signals": {
                "sku_id": "EC-017",
                "competitor_min_price": 118,
                "competitor_avg_price": 125,
                "price_gap_pct": 0.2625,
                "competitors_on_sale_count": 4,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 4,
                "data_freshness_hours": 12,
                "confidence_score": 0.95,
            },
        },
    ),
    EdgeCase(
        case_id="clear_dead_stock_lifestyle",
        expected_label="CLEAR",
        description="Aging lifestyle layer with very high days of supply and minimal competitive urgency.",
        label_rationale="Even with low competitor count, the age and sell-through profile indicate trapped cash that should be freed.",
        request={
            "sku_id": "EC-018",
            "product_name": "Aging Lifestyle Layer",
            "brand": "Bogner",
            "category": "lifestyle",
            "retail_price_usd": 220,
            "cost_price_usd": 98,
            "current_stock": 95,
            "initial_stock": 110,
            "days_since_launch": 390,
            "days_since_last_discount": 999,
            "days_at_current_price": 110,
            "competitor_signals": {
                "sku_id": "EC-018",
                "competitor_min_price": 162,
                "competitor_avg_price": 170,
                "price_gap_pct": 0.2636,
                "competitors_on_sale_count": 4,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 1,
                "data_freshness_hours": 18,
                "confidence_score": 0.90,
            },
        },
    ),
    EdgeCase(
        case_id="clear_sellthrough_boundary_swimwear",
        expected_label="CLEAR",
        description="Swimwear case close to the sell-through cutoff, but still clearly weak enough for forced clearance.",
        label_rationale="This scenario probes the dead-stock boundary while still remaining on the CLEAR side of the rule.",
        request={
            "sku_id": "EC-019",
            "product_name": "Late Season Swim Set",
            "brand": "Billabong",
            "category": "swimwear",
            "retail_price_usd": 120,
            "cost_price_usd": 52,
            "current_stock": 70,
            "initial_stock": 82,
            "days_since_launch": 280,
            "days_since_last_discount": 999,
            "days_at_current_price": 90,
            "competitor_signals": {
                "sku_id": "EC-019",
                "competitor_min_price": 82,
                "competitor_avg_price": 88,
                "price_gap_pct": 0.3167,
                "competitors_on_sale_count": 4,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 3,
                "data_freshness_hours": 11,
                "confidence_score": 0.91,
            },
        },
    ),
    EdgeCase(
        case_id="clear_dead_stock_premium_footwear",
        expected_label="CLEAR",
        description="Premium footwear with very high stock cover and very weak sell-through.",
        label_rationale="The case is old, overpriced, and underperforming enough that forced clearance is appropriate.",
        request={
            "sku_id": "EC-020",
            "product_name": "Old Premium Runner",
            "brand": "Nike",
            "category": "footwear",
            "retail_price_usd": 180,
            "cost_price_usd": 80,
            "current_stock": 82,
            "initial_stock": 94,
            "days_since_launch": 340,
            "days_since_last_discount": 999,
            "days_at_current_price": 95,
            "competitor_signals": {
                "sku_id": "EC-020",
                "competitor_min_price": 128,
                "competitor_avg_price": 136,
                "price_gap_pct": 0.2889,
                "competitors_on_sale_count": 4,
                "competitors_out_of_stock_count": 0,
                "num_competitors_tracked": 1,
                "data_freshness_hours": 12,
                "confidence_score": 0.94,
            },
        },
    ),
]


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    try:
        if pd.isna(value):
            return "__nan__"
    except TypeError:
        pass
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    return str(value)


def _load_training_signatures() -> tuple[Path, set[tuple[Any, ...]]]:
    training_path = Path(MODEL_META.get("training_dataset_path", "data/features/ai_labeled_dataset.csv"))
    if not training_path.is_absolute():
        training_path = ROOT / training_path

    training_df = pd.read_csv(training_path)
    signatures = {
        tuple(_normalize_value(row[column]) for column in MODEL_FEATURE_COLUMNS)
        for _, row in training_df[MODEL_FEATURE_COLUMNS].iterrows()
    }
    return training_path, signatures


def _build_request(raw_request: dict[str, Any]) -> RecommendationRequest:
    payload = dict(raw_request)
    competitor_payload = payload.get("competitor_signals")
    if competitor_payload is not None:
        payload["competitor_signals"] = CompetitorSignals(**competitor_payload)
    return RecommendationRequest(**payload)


def _subset_metrics(case_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not case_rows:
        return None
    y_true = [row["expected_label"] for row in case_rows]
    y_pred = [row["predicted_label"] for row in case_rows]
    return {
        "count": len(case_rows),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro")), 4),
        "weighted_f1": round(float(f1_score(y_true, y_pred, average="weighted")), 4),
    }


def evaluate_edge_cases() -> dict[str, Any]:
    training_path, training_signatures = _load_training_signatures()

    case_rows: list[dict[str, Any]] = []
    for case in EDGE_CASES:
        request = _build_request(case.request)
        features = _build_model_features(request)
        signature = tuple(_normalize_value(features[column]) for column in MODEL_FEATURE_COLUMNS)
        result = _recommend_single(request)

        case_rows.append(
            {
                "case_id": case.case_id,
                "description": case.description,
                "label_rationale": case.label_rationale,
                "expected_label": case.expected_label,
                "predicted_label": result.recommendation,
                "correct": result.recommendation == case.expected_label,
                "confidence": round(float(result.confidence), 4),
                "decision_source": "hard_rule" if result.rule_override else "model",
                "rule_id": result.rule_override.rule_id if result.rule_override else None,
                "fallback_used": bool(result.fallback_used),
                "model_version": result.model_version,
                "is_exact_feature_match_in_training_data": signature in training_signatures,
                "request": case.request,
                "key_features": {
                    "days_of_supply": features["days_of_supply"],
                    "current_margin_pct": features["current_margin_pct"],
                    "season_sell_through_pct": features["season_sell_through_pct"],
                    "price_gap_pct": features["price_gap_pct"],
                    "competitors_on_sale": features["competitors_on_sale"],
                    "competitors_out_of_stock": features["competitors_out_of_stock"],
                    "num_competitors": features["num_competitors"],
                    "market_position": features["market_position"],
                    "seasonality_score": features["seasonality_score"],
                    "event_proximity_score": features["event_proximity_score"],
                },
            }
        )

    y_true = [row["expected_label"] for row in case_rows]
    y_pred = [row["predicted_label"] for row in case_rows]
    overall_report = classification_report(y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0)
    hard_rule_rows = [row for row in case_rows if row["decision_source"] == "hard_rule"]
    model_rows = [row for row in case_rows if row["decision_source"] == "model"]

    summary = {
        "model_version": case_rows[0]["model_version"] if case_rows else "unknown",
        "reference_training_dataset": str(training_path),
        "total_cases": len(case_rows),
        "exact_training_feature_matches": sum(
            1 for row in case_rows if row["is_exact_feature_match_in_training_data"]
        ),
        "novel_cases": sum(
            1 for row in case_rows if not row["is_exact_feature_match_in_training_data"]
        ),
        "expected_distribution": dict(Counter(y_true)),
        "predicted_distribution": dict(Counter(y_pred)),
        "fallback_cases": sum(1 for row in case_rows if row["fallback_used"]),
        "overall_metrics": {
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "macro_f1": round(float(f1_score(y_true, y_pred, average="macro")), 4),
            "weighted_f1": round(float(f1_score(y_true, y_pred, average="weighted")), 4),
        },
        "subset_metrics": {
            "hard_rule_cases": _subset_metrics(hard_rule_rows),
            "model_routed_cases": _subset_metrics(model_rows),
        },
        "per_class_metrics": {
            label: {
                "precision": round(float(overall_report[label]["precision"]), 4),
                "recall": round(float(overall_report[label]["recall"]), 4),
                "f1": round(float(overall_report[label]["f1-score"]), 4),
                "support": int(overall_report[label]["support"]),
            }
            for label in LABELS
        },
        "confusion_matrix": {
            "labels": LABELS,
            "matrix": confusion_matrix(y_true, y_pred, labels=LABELS).tolist(),
        },
    }

    return {
        "summary": summary,
        "cases": case_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the chosen IE2 model on 20 synthetic edge cases.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the JSON report.",
    )
    args = parser.parse_args()

    report = evaluate_edge_cases()
    rendered = json.dumps(report, indent=2)
    print(rendered)

    if args.output is not None:
        output_path = args.output
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
