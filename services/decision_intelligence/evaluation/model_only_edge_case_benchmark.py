"""
Raw-model-only edge-case benchmark for the IE2 Decision Intelligence service.

This evaluates the CatBoost model directly on the same synthetic edge cases
used by the full pipeline benchmark, without applying:
  - hard rules
  - soft nudges
  - confidence fallback to HOLD

Run from the repo root:
    py -m services.decision_intelligence.evaluation.model_only_edge_case_benchmark
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from services.decision_intelligence.evaluation.edge_case_benchmark import (
    EDGE_CASES,
    LABELS,
    ROOT,
    _build_request,
    _load_training_signatures,
    _normalize_value,
)
from services.decision_intelligence.main import (
    MODEL_FEATURE_COLUMNS,
    MODEL_VERSION,
    REGISTERED_MODEL,
    _build_model_features,
)


def _predict_model_only(features: dict[str, Any]) -> tuple[str, float, dict[str, float]]:
    if REGISTERED_MODEL is None:
        raise RuntimeError("Registered CatBoost model is not loaded.")

    frame = pd.DataFrame(
        [{column: features.get(column) for column in MODEL_FEATURE_COLUMNS}],
        columns=MODEL_FEATURE_COLUMNS,
    )
    probabilities = REGISTERED_MODEL.predict_proba(frame)[0]
    label_scores = {
        LABELS[idx]: round(float(probabilities[idx]), 4)
        for idx in range(len(LABELS))
    }
    best_idx = max(range(len(probabilities)), key=lambda idx: probabilities[idx])
    return LABELS[best_idx], float(probabilities[best_idx]), label_scores


def evaluate_model_only_edge_cases() -> dict[str, Any]:
    training_path, training_signatures = _load_training_signatures()

    case_rows: list[dict[str, Any]] = []
    for case in EDGE_CASES:
        request = _build_request(case.request)
        features = _build_model_features(request)
        signature = tuple(_normalize_value(features[column]) for column in MODEL_FEATURE_COLUMNS)
        predicted_label, confidence, label_scores = _predict_model_only(features)

        case_rows.append(
            {
                "case_id": case.case_id,
                "description": case.description,
                "label_rationale": case.label_rationale,
                "expected_label": case.expected_label,
                "predicted_label": predicted_label,
                "correct": predicted_label == case.expected_label,
                "confidence": round(confidence, 4),
                "model_version": MODEL_VERSION,
                "is_exact_feature_match_in_training_data": signature in training_signatures,
                "raw_class_probabilities": label_scores,
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

    summary = {
        "model_version": MODEL_VERSION,
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
        "overall_metrics": {
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "macro_f1": round(float(f1_score(y_true, y_pred, average="macro")), 4),
            "weighted_f1": round(float(f1_score(y_true, y_pred, average="weighted")), 4),
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
    parser = argparse.ArgumentParser(description="Evaluate the raw CatBoost model on synthetic edge cases.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/model_only_edge_case_benchmark.json"),
        help="Optional path to write the JSON report.",
    )
    args = parser.parse_args()

    report = evaluate_model_only_edge_cases()
    rendered = json.dumps(report, indent=2)
    print(rendered)

    output_path = args.output
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
