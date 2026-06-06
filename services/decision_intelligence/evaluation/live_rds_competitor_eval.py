"""Evaluate live RDS competitor data against IE2 model and system behavior.

Expected labels are loaded from an explicit AI-reviewed CSV. The evaluator does
not generate labels itself; unlabeled cases are exported as review candidates.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Iterable

import pandas as pd

from services.decision_intelligence.main import (
    LABEL_INV,
    MODEL_META,
    MODEL_CATEGORICAL_FEATURES,
    MODEL_FEATURE_COLUMNS,
    MODEL_VERSION,
    REGISTERED_MODEL,
    _build_model_features,
    _recommend_single,
    _recommend_with_features,
)
from services.decision_intelligence.schemas import CompetitorSignals, RecommendationRequest
from services.decision_intelligence.training.train import _enrich_feature_space
from services.market_intelligence import competitor_processor
from services.decision_intelligence.features import clean_competitors as matcher


ROOT = Path(__file__).resolve().parents[3]
PRODUCTS_PATH = ROOT / "data" / "real" / "products.csv"
INVENTORY_PATH = ROOT / "data" / "real" / "inventory.csv"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "reports" / "live_rds_competitor_eval.json"
DEFAULT_LABELS_PATH = ROOT / "data" / "evaluation" / "live_rds_ai_labels.csv"
DEFAULT_CANDIDATES_PATH = ROOT / "data" / "reports" / "live_rds_label_candidates.csv"
DEFAULT_FEATURE_INPUT_PATH = ROOT / str(
    MODEL_META.get("training_dataset_path") or "data/features/ai_labeled_dataset_augmented.csv"
)
LABELS = ["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"]
LIVE_COMPETITOR_FEATURES = {
    "price_gap_pct",
    "competitors_on_sale",
    "competitors_out_of_stock",
    "num_competitors",
    "market_position",
}
LABELING_SYSTEM_PROMPT = """You are a senior retail pricing and inventory decision analyst for a sportswear retailer.

Your task is to label each product case with the best business action:

HOLD
MARKDOWN
PROMOTE
CLEAR

You must label from the provided business features only. Do not use any model prediction, system prediction, confidence score, or previous label as evidence. Those fields are outputs being evaluated, not ground truth.

Decision meanings:

HOLD:
Choose HOLD when the safest business action is to keep the current price and avoid intervention. HOLD is appropriate when stock is low, competitor evidence is weak, price is close to market, margin is thin, the action signal is mixed, or there is not enough evidence to justify changing price or promotion.

MARKDOWN:
Choose MARKDOWN when the product is overpriced versus reliable competitors and has enough stock and margin to support a price reduction. MARKDOWN is appropriate when price_gap_pct is meaningfully positive, market_position is above_market or premium, competitors are on sale, days_of_supply is moderate/high, and current_margin_pct is sufficient.

PROMOTE:
Choose PROMOTE when the product should be pushed commercially without reducing price materially. PROMOTE is appropriate when stock and margin are healthy, price is at-market or below-market, competitors are out of stock or scarce, the product has demand-capture potential, and there is no strong markdown or hold reason.

CLEAR:
Choose CLEAR only for strong dead-stock/trapped-cash cases. CLEAR requires old inventory, high days_of_supply, weak sell-through, enough remaining stock to matter, and no better reason to hold/promote/markdown. Do not choose CLEAR just because one field looks stale. CLEAR should be rare.

Feature interpretation:

days_of_supply:
Estimated number of days current stock would last at current demand. Higher means slower movement or excess stock. It is not the same as product age.

days_since_launch:
Approximate age of product in inventory or assortment. Use it as lifecycle context, not as proof by itself.

total_qty/current_stock:
Current units available. Low stock should usually protect against MARKDOWN and PROMOTE.

season_sell_through_pct:
Share of initial/peak stock already sold. Higher sell-through means healthier movement. Very low sell-through can support CLEAR only when combined with age and high days_of_supply.

current_margin_pct:
Gross margin. Low margin limits markdown room. Healthy margin gives flexibility for MARKDOWN or PROMOTE.

price_gap_pct:
Positive means our price is higher than the cheapest/market competitor. Negative means we are cheaper. Large positive gaps support MARKDOWN. Negative or near-zero gaps can support PROMOTE or HOLD.

market_position:
premium or above_market supports MARKDOWN if the competitor match is reliable.
at_market supports HOLD or PROMOTE.
below_market or deep_value supports PROMOTE or HOLD.

competitors_on_sale:
Competitors discounting this product. This can increase MARKDOWN pressure if our price is also high.

competitors_out_of_stock:
Competitors unavailable. This can support PROMOTE because we can capture demand.

num_competitors:
Number of reliable competitor signals. More competitors makes the market signal stronger. Zero or weak match should usually push toward HOLD.

match_type and match_score:
Use exact_style as strongest evidence.
Use same_model_family or similar_product as useful but slightly weaker evidence.
Use no_match as weak evidence; avoid aggressive MARKDOWN/PROMOTE/CLEAR when match_type is no_match.

Labeling priorities:

1. Protect availability:
If stock is low, usually label HOLD unless there is overwhelming evidence for another action.

2. Avoid fake precision:
If evidence is mixed, label HOLD.

3. Do not overuse CLEAR:
CLEAR should require multiple strong signals: old product, high days_of_supply, weak sell-through, meaningful remaining stock, and poor market position.

4. Separate MARKDOWN from PROMOTE:
MARKDOWN is for price correction when we are too expensive.
PROMOTE is for demand capture when our price is competitive and we have stock/margin to push.

5. Competitor reliability matters:
A strong price_gap_pct from an exact_style match is more persuasive than the same signal from similar_product. no_match should rarely lead to action.

6. Margin matters:
Do not label MARKDOWN if margin is too thin. Prefer HOLD unless promotion is clearly safer.

7. Product age is context, not destiny:
Old age alone is not enough for CLEAR or MARKDOWN.

Output format:

Return exactly one JSON object per product case with these fields:

{
  "sku_id": "...",
  "expected_label": "HOLD | MARKDOWN | PROMOTE | CLEAR",
  "ai_label_confidence": 0.0 to 1.0,
  "ai_label_rationale": "Short explanation using the business features.",
  "audit_flags": ["optional short flags such as low_stock, weak_competitor_match, thin_margin, stale_inventory, overpriced, demand_capture"]
}

Do not include markdown.
Do not include extra commentary.
Do not mention model predictions or system predictions."""
LABEL_PROMPT_EXCLUDED_FIELDS = {
    "model_only_prediction",
    "model_only_confidence",
    "model_only_probabilities",
    "system_prediction",
    "system_confidence",
    "system_rule_id",
    "system_fallback_used",
    "expected_label",
    "ai_label_rationale",
    "ai_label_confidence",
    "audit_flags",
    "feature_source",
    "feature_week_of",
}
LABEL_CANDIDATE_COLUMNS = [
    "sku_id",
    "product_name",
    "brand",
    "category",
    "retail_price_usd",
    "cost_price_usd",
    "current_stock",
    "initial_stock",
    "total_qty",
    "days_since_launch",
    "days_since_last_discount",
    "days_at_current_price",
    "days_of_supply",
    "current_margin_pct",
    "season_sell_through_pct",
    "price_gap_pct",
    "competitors_on_sale",
    "competitors_out_of_stock",
    "num_competitors",
    "market_position",
    "match_type",
    "match_score",
]

ModelPredictor = Callable[[dict[str, Any]], dict[str, Any]]
SystemPredictor = Callable[[RecommendationRequest], Any]


def load_dotenv_if_present(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class AILabel:
    label: str
    rationale: str


def load_product_inputs(
    products_path: Path = PRODUCTS_PATH,
    inventory_path: Path = INVENTORY_PATH,
) -> list[dict[str, Any]]:
    products = _read_csv(products_path)
    inventory = {row["sku_id"]: row for row in _read_csv(inventory_path)} if inventory_path.exists() else {}
    merged: list[dict[str, Any]] = []
    for product in products:
        sku_id = product.get("sku_id")
        inv = inventory.get(sku_id or "", {})
        merged.append({**product, **{k: v for k, v in inv.items() if v not in (None, "")}})
    return merged


def load_ai_labels(labels_path: Path = DEFAULT_LABELS_PATH) -> dict[str, AILabel]:
    if not labels_path.exists():
        return {}
    labels: dict[str, AILabel] = {}
    for row in _read_csv(labels_path):
        sku_id = str(row.get("sku_id") or "").strip()
        label = str(row.get("expected_label") or "").strip().upper()
        rationale = str(row.get("ai_label_rationale") or "").strip()
        if not sku_id:
            continue
        if label not in LABELS:
            raise ValueError(f"Invalid expected_label for {sku_id}: {label!r}")
        labels[sku_id] = AILabel(label=label, rationale=rationale or "AI-reviewed live case label.")
    return labels


def load_training_feature_rows(features_path: Path = DEFAULT_FEATURE_INPUT_PATH) -> dict[str, dict[str, Any]]:
    if not features_path.exists():
        return {}

    rows = _read_csv(features_path)
    selected: dict[str, dict[str, Any]] = {}
    fallback: dict[str, dict[str, Any]] = {}
    for row in rows:
        sku_id = str(row.get("sku_id") or "").strip()
        if not sku_id:
            continue
        if _is_later_feature_row(row, fallback.get(sku_id)):
            fallback[sku_id] = row
        if str(row.get("synthetic_is_augmented") or "0").strip().lower() in {"1", "true", "yes"}:
            continue
        if _is_later_feature_row(row, selected.get(sku_id)):
            selected[sku_id] = row

    for sku_id, row in fallback.items():
        selected.setdefault(sku_id, row)
    return selected


def load_rds_competitor_rows() -> pd.DataFrame:
    rows = competitor_processor._load_database_competitor_rows()
    if rows is None:
        raise RuntimeError("DATABASE_URL is not configured; cannot evaluate live RDS competitor data.")
    return rows


def evaluate_live_rds_competitor_data(
    sample_size: int | str = 5000,
    output_path: Path | None = DEFAULT_OUTPUT_PATH,
    labels_path: Path | None = DEFAULT_LABELS_PATH,
    candidates_path: Path | None = DEFAULT_CANDIDATES_PATH,
    seed: int = 42,
    product_rows: list[dict[str, Any]] | None = None,
    competitor_rows: pd.DataFrame | list[dict[str, Any]] | None = None,
    feature_input_path: Path | None = None,
    ai_labels: dict[str, AILabel] | None = None,
    model_predictor: ModelPredictor | None = None,
    system_predictor: SystemPredictor | None = None,
) -> dict[str, Any]:
    products = product_rows or load_product_inputs()
    labels = ai_labels if ai_labels is not None else load_ai_labels(labels_path or DEFAULT_LABELS_PATH)
    feature_rows = load_training_feature_rows(feature_input_path) if feature_input_path else {}
    raw_competitors = (
        competitor_rows.copy()
        if isinstance(competitor_rows, pd.DataFrame)
        else pd.DataFrame(competitor_rows) if competitor_rows is not None
        else load_rds_competitor_rows()
    )
    clean_rows, clean_stats = _prepare_competitor_rows(raw_competitors)
    feature_stats = {
        "feature_input_path": str(feature_input_path) if feature_input_path else None,
        "feature_input_row_count": len(feature_rows),
        "feature_mode": "training_feature_rows_with_live_rds_competitor_overlay" if feature_rows else "online_request_features",
        "matched_feature_count": 0,
        "missing_feature_count": 0,
    }

    sampled_products = _sample_products(products, sample_size, seed)
    cases: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for product in sampled_products:
        request, competitor_signals, skip_reason = _build_request(product, clean_rows)
        if request is None:
            skipped.append({"sku_id": str(product.get("sku_id") or ""), "reason": skip_reason or "invalid_request"})
            continue

        online_features = _build_model_features(request)
        features, feature_source = _select_case_features(
            request.sku_id,
            feature_rows,
            online_features,
        )
        if feature_source["source"] == "training_feature_row":
            feature_stats["matched_feature_count"] += 1
        else:
            feature_stats["missing_feature_count"] += 1
        ai_label = labels.get(request.sku_id)
        model_result = (model_predictor or predict_model_only)(features)
        if system_predictor is not None:
            system_result = _normalize_system_result(system_predictor(request))
        elif feature_source["source"] == "training_feature_row":
            system_result = _normalize_system_result(_recommend_with_features(request, features))
        else:
            system_result = _normalize_system_result(_recommend_single(request))

        cases.append(
            {
                "sku_id": request.sku_id,
                "product_name": request.product_name,
                "brand": request.brand,
                "category": request.category,
                "expected_label": ai_label.label if ai_label else None,
                "ai_label_rationale": ai_label.rationale if ai_label else None,
                "model_only_prediction": model_result["prediction"],
                "model_only_confidence": round(_to_float(model_result.get("confidence")), 4),
                "model_only_probabilities": model_result.get("probabilities", {}),
                "system_prediction": system_result["prediction"],
                "system_confidence": round(_to_float(system_result.get("confidence")), 4),
                "system_rule_id": system_result.get("rule_id"),
                "system_fallback_used": bool(system_result.get("fallback_used")),
                "feature_source": feature_source,
                "match": _match_diagnostics(competitor_signals),
                "key_features": _key_features(features),
                "request": request.model_dump(mode="json"),
            }
        )

    if candidates_path is not None:
        _write_label_candidates(cases, candidates_path if candidates_path.is_absolute() else ROOT / candidates_path)

    report = _build_report(
        cases=cases,
        skipped=skipped,
        sample_size=sample_size,
        labels_path=labels_path,
        feature_input_path=feature_input_path,
        products=products,
        clean_stats=clean_stats,
        feature_stats=feature_stats,
        clean_rows=clean_rows,
    )
    if output_path is not None:
        output_path = output_path if output_path.is_absolute() else ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _select_case_features(
    sku_id: str,
    feature_rows: dict[str, dict[str, Any]],
    online_features: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    training_row = feature_rows.get(sku_id)
    if not training_row:
        return online_features, {"source": "online_request_features", "reason": "no_training_feature_row"}

    features = _coerce_feature_row(training_row)
    for key in LIVE_COMPETITOR_FEATURES:
        features[key] = online_features.get(key)

    enriched = _enrich_feature_space(pd.DataFrame([features])).iloc[0].to_dict()
    return enriched, {
        "source": "training_feature_row",
        "week_of": training_row.get("week_of"),
        "live_rds_competitor_overlay": True,
    }


def predict_model_only(features: dict[str, Any]) -> dict[str, Any]:
    if REGISTERED_MODEL is None:
        raise RuntimeError("Registered model is not loaded.")
    if not MODEL_FEATURE_COLUMNS:
        raise RuntimeError("Model feature columns are unavailable.")
    frame = pd.DataFrame(
        [{column: features.get(column) for column in MODEL_FEATURE_COLUMNS}],
        columns=MODEL_FEATURE_COLUMNS,
    )
    probabilities = REGISTERED_MODEL.predict_proba(frame)[0]
    best_idx = max(range(len(probabilities)), key=lambda idx: probabilities[idx])
    return {
        "prediction": LABEL_INV.get(best_idx, "HOLD"),
        "confidence": float(probabilities[best_idx]),
        "probabilities": {
            LABEL_INV.get(idx, str(idx)): round(float(prob), 4)
            for idx, prob in enumerate(probabilities)
        },
    }


def _prepare_competitor_rows(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    clean_markers = {"product_key", "effective_competitor_price_usd", "category_normalized", "gender_normalized"}
    if clean_markers.issubset(set(rows.columns)):
        return rows.copy(), {"input_row_count": len(rows), "cleaned_row_count": len(rows), "already_clean": True}
    normalized = matcher.normalize_columns(rows)
    for optional_col in matcher.RELEVANT_SCRAPE_COLUMNS:
        if optional_col not in normalized.columns:
            normalized[optional_col] = pd.NA
    return matcher.clean_scraped_rows(normalized)


def _build_request(
    product: dict[str, Any],
    clean_rows: pd.DataFrame,
) -> tuple[RecommendationRequest | None, dict[str, Any] | None, str | None]:
    try:
        signals = competitor_processor.build_competitor_signals_for_product(product, competitor_rows=clean_rows)
        request_payload = {
            "sku_id": str(product.get("sku_id") or ""),
            "product_name": str(product.get("product_name") or product.get("name") or "Unknown Product"),
            "brand": str(product.get("brand") or "Unknown"),
            "category": str(product.get("system_category") or product.get("category") or "other"),
            "retail_price_usd": _to_float(product.get("retail_price_usd")),
            "cost_price_usd": _to_float(product.get("cost_price_usd")),
            "current_stock": max(_to_int(product.get("current_stock"), _to_int(product.get("initial_stock"), 1)), 0),
            "initial_stock": max(
                _to_int(product.get("initial_stock"), _to_int(product.get("current_stock"), 1)),
                _to_int(product.get("current_stock"), 1),
                1,
            ),
            "days_since_launch": _to_int(product.get("days_since_launch"), 180),
            "days_since_last_discount": _to_int(product.get("days_since_last_discount"), 999),
            "days_at_current_price": _to_int(product.get("days_at_current_price"), 30),
            "competitor_signals": _strip_signal_metadata(signals),
        }
        request = RecommendationRequest.model_validate(request_payload)
        return request, signals, None
    except Exception as exc:
        return None, None, str(exc)


def _strip_signal_metadata(signals: dict[str, Any]) -> dict[str, Any]:
    allowed = set(CompetitorSignals.model_fields)
    return {key: value for key, value in signals.items() if key in allowed}


def _normalize_system_result(result: Any) -> dict[str, Any]:
    payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
    rule = payload.get("rule_override")
    return {
        "prediction": payload.get("recommendation", "HOLD"),
        "confidence": _to_float(payload.get("confidence")),
        "fallback_used": bool(payload.get("fallback_used")),
        "rule_id": rule.get("rule_id") if isinstance(rule, dict) else rule,
    }


def _build_report(
    cases: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    sample_size: int | str,
    labels_path: Path | None,
    feature_input_path: Path | None,
    products: list[dict[str, Any]],
    clean_stats: dict[str, Any],
    feature_stats: dict[str, Any],
    clean_rows: pd.DataFrame,
) -> dict[str, Any]:
    labeled_cases = [case for case in cases if case.get("expected_label")]
    unlabeled_cases = [case for case in cases if not case.get("expected_label")]
    y_true = [case["expected_label"] for case in labeled_cases]
    report = {
        "summary": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "requested_sample_size": sample_size,
            "requested_sample_size_numeric": len(products) if sample_size == "all" else _to_int(sample_size),
            "available_product_count": len(products),
            "valid_request_count": len(cases),
            "evaluated_cases": len(labeled_cases),
            "unlabeled_case_count": len(unlabeled_cases),
            "skipped_product_count": len(skipped),
            "expected_label_distribution": dict(Counter(y_true)),
            "labeling_note": (
                "Expected labels come from an explicit AI-reviewed CSV. "
                "Label candidates are exported with business-only fields using LABELING_SYSTEM_PROMPT."
            ),
        },
        "source_data": {
            "products_path": str(PRODUCTS_PATH),
            "inventory_path": str(INVENTORY_PATH),
            "competitor_source": "intel.competitor_products_latest or injected test rows",
            "competitor_clean_stats": clean_stats,
            "labels_path": str(labels_path) if labels_path else None,
            "feature_input_path": str(feature_input_path) if feature_input_path else None,
            "feature_stats": feature_stats,
        },
        "freshness": _freshness_summary(clean_rows),
        "matching": _matching_summary(cases),
        "scoring": {
            "model_only": _score_predictions(
                y_true,
                [case["model_only_prediction"] for case in labeled_cases],
                [case["model_only_confidence"] for case in labeled_cases],
            ),
            "system": _score_predictions(
                y_true,
                [case["system_prediction"] for case in labeled_cases],
                [case["system_confidence"] for case in labeled_cases],
            ),
        },
        "skipped": skipped[:100],
        "cases": cases,
    }
    return report


def _write_label_candidates(cases: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_CANDIDATE_COLUMNS)
        writer.writeheader()
        for case in cases:
            writer.writerow(_label_prompt_payload(case))


def _label_prompt_payload(case: dict[str, Any]) -> dict[str, Any]:
    request = case["request"]
    features = case["key_features"]
    match = case["match"]
    payload = {
        "sku_id": case["sku_id"],
        "product_name": case["product_name"],
        "brand": case["brand"],
        "category": case["category"],
        "retail_price_usd": request.get("retail_price_usd"),
        "cost_price_usd": request.get("cost_price_usd"),
        "current_stock": request.get("current_stock"),
        "initial_stock": request.get("initial_stock"),
        "total_qty": features.get("total_qty"),
        "days_since_launch": features.get("days_since_launch"),
        "days_since_last_discount": request.get("days_since_last_discount"),
        "days_at_current_price": request.get("days_at_current_price"),
        "days_of_supply": features.get("days_of_supply"),
        "current_margin_pct": features.get("current_margin_pct"),
        "season_sell_through_pct": features.get("season_sell_through_pct"),
        "price_gap_pct": features.get("price_gap_pct"),
        "competitors_on_sale": features.get("competitors_on_sale"),
        "competitors_out_of_stock": features.get("competitors_out_of_stock"),
        "num_competitors": features.get("num_competitors"),
        "market_position": features.get("market_position"),
        "match_type": match.get("match_type"),
        "match_score": match.get("match_score"),
    }
    leaked_fields = set(payload).intersection(LABEL_PROMPT_EXCLUDED_FIELDS)
    if leaked_fields:
        raise ValueError(f"Label prompt payload includes evaluation fields: {sorted(leaked_fields)}")
    return payload


def _score_predictions(y_true: list[str], y_pred: list[str], confidences: list[float]) -> dict[str, Any]:
    total = len(y_true)
    correct = sum(1 for actual, predicted in zip(y_true, y_pred) if actual == predicted)
    per_class: dict[str, dict[str, float | int]] = {}
    f1_values = []
    supported_f1_values = []
    weighted_f1_sum = 0.0
    for label in LABELS:
        tp = sum(1 for actual, predicted in zip(y_true, y_pred) if actual == label and predicted == label)
        fp = sum(1 for actual, predicted in zip(y_true, y_pred) if actual != label and predicted == label)
        fn = sum(1 for actual, predicted in zip(y_true, y_pred) if actual == label and predicted != label)
        support = sum(1 for actual in y_true if actual == label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        f1_values.append(f1)
        if support > 0:
            supported_f1_values.append(f1)
        weighted_f1_sum += f1 * support
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }
    return {
        "accuracy": round(correct / total, 4) if total else 0.0,
        "macro_f1": round(sum(supported_f1_values) / len(supported_f1_values), 4) if supported_f1_values else 0.0,
        "macro_f1_all_classes": round(sum(f1_values) / len(LABELS), 4) if LABELS else 0.0,
        "weighted_f1": round(weighted_f1_sum / total, 4) if total else 0.0,
        "mean_confidence": round(mean(confidences), 4) if confidences else 0.0,
        "median_confidence": round(median(confidences), 4) if confidences else 0.0,
        "expected_distribution": dict(Counter(y_true)),
        "predicted_distribution": dict(Counter(y_pred)),
        "per_class_metrics": per_class,
        "confusion_matrix": {
            "labels": LABELS,
            "matrix": [
                [sum(1 for actual, predicted in zip(y_true, y_pred) if actual == row and predicted == col) for col in LABELS]
                for row in LABELS
            ],
        },
    }


def _matching_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    match_types = Counter(case["match"]["match_type"] for case in cases)
    total = len(cases)
    exact = match_types.get("exact_style", 0)
    no_match = match_types.get("no_match", 0)
    fallback = total - exact - no_match
    return {
        "match_type_distribution": dict(match_types),
        "exact_match_count": exact,
        "fallback_match_count": fallback,
        "no_match_count": no_match,
        "no_match_rate": round(no_match / total, 4) if total else 0.0,
        "coverage_ratio": {
            "exact": round(exact / total, 4) if total else 0.0,
            "fallback": round(fallback / total, 4) if total else 0.0,
            "no_match": round(no_match / total, 4) if total else 0.0,
        },
    }


def _freshness_summary(clean_rows: pd.DataFrame) -> dict[str, Any]:
    if "scraped_at" not in clean_rows.columns or clean_rows.empty:
        return {"median_freshness_hours": 0.0, "max_freshness_hours": 0.0}
    timestamps = pd.to_datetime(clean_rows["scraped_at"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return {"median_freshness_hours": 0.0, "max_freshness_hours": 0.0}
    ages = ((pd.Timestamp.now(tz="UTC") - timestamps).dt.total_seconds() / 3600.0).tolist()
    return {
        "median_freshness_hours": round(float(median(ages)), 2),
        "max_freshness_hours": round(float(max(ages)), 2),
    }


def _match_diagnostics(signals: dict[str, Any] | None) -> dict[str, Any]:
    signals = signals or {}
    competitor_count = _to_int(signals.get("num_competitors_tracked"))
    match_type = str(signals.get("match_type") or ("no_match" if competitor_count == 0 else "matched_unknown"))
    if bool(signals.get("fallback_used")) and competitor_count == 0:
        match_type = "no_match"
    return {
        "match_type": match_type,
        "match_score": round(_to_float(signals.get("match_score")), 4),
        "fallback_used": bool(signals.get("fallback_used")),
        "fallback_reason": signals.get("fallback_reason"),
        "num_competitors_tracked": competitor_count,
        "cheapest_competitor_name": signals.get("cheapest_competitor_name"),
        "data_freshness_hours": round(_to_float(signals.get("data_freshness_hours")), 1),
    }


def _key_features(features: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "days_of_supply",
        "days_since_launch",
        "total_qty",
        "current_margin_pct",
        "season_sell_through_pct",
        "price_gap_pct",
        "competitors_on_sale",
        "competitors_out_of_stock",
        "num_competitors",
        "market_position",
        "seasonality_score",
        "event_proximity_score",
    ]
    return {key: features.get(key) for key in keys}


def _is_later_feature_row(row: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if current is None:
        return True
    return str(row.get("week_of") or "") >= str(current.get("week_of") or "")


def _coerce_feature_row(row: dict[str, Any]) -> dict[str, Any]:
    categorical = set(MODEL_CATEGORICAL_FEATURES) or {"brand", "category", "market_position", "brand_tier"}
    features: dict[str, Any] = {}
    for column in MODEL_FEATURE_COLUMNS:
        value = row.get(column)
        if column in categorical:
            features[column] = str(value if value not in (None, "") else "unknown")
        else:
            features[column] = _to_float(value)
    return features


def _sample_products(products: list[dict[str, Any]], sample_size: int | str, seed: int) -> list[dict[str, Any]]:
    if sample_size == "all":
        return list(products)
    requested = max(_to_int(sample_size), 0)
    if requested >= len(products):
        return list(products)
    rng = random.Random(seed)
    return rng.sample(products, requested)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "") or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "") or pd.isna(value):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def main() -> None:
    load_dotenv_if_present()
    parser = argparse.ArgumentParser(description="Evaluate IE2 against live RDS competitor data.")
    parser.add_argument("--sample-size", default="5000", help="Number of products to sample, or 'all'.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--candidates-output", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument(
        "--feature-input",
        type=Path,
        default=DEFAULT_FEATURE_INPUT_PATH,
        help="Training-style feature dataset to align live evaluation features by sku_id.",
    )
    parser.add_argument(
        "--no-feature-input",
        action="store_true",
        help="Use online request feature generation only.",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    sample_size: int | str = "all" if str(args.sample_size).lower() == "all" else int(args.sample_size)
    report = evaluate_live_rds_competitor_data(
        sample_size=sample_size,
        output_path=args.output,
        labels_path=args.labels,
        candidates_path=args.candidates_output,
        feature_input_path=None if args.no_feature_input else args.feature_input,
        seed=args.seed,
    )
    print(json.dumps(report["summary"], indent=2))
    print(json.dumps(report["scoring"], indent=2))


if __name__ == "__main__":
    main()
