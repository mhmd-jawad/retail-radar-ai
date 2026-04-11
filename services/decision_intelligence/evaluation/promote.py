"""
Model promotion gate for IE2 Decision Intelligence.

Evaluates a trained CatBoost model against the promotion thresholds.
Only promotes a model if ALL gates pass:
  - Overall accuracy ≥ 0.80
  - Macro F1 ≥ 0.75
  - CLEAR recall ≥ 0.88  (critical: costly to miss dead stock)

Usage:
    python -m services.decision_intelligence.evaluation.promote [--model-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Resolve to repo root (retail-radar-ai/)
ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR    = ROOT / "services" / "decision_intelligence" / "models" / "catboost_decision"
FEATURES_PATH = ROOT / "data" / "features" / "features.csv"
LABELS_PATH   = ROOT / "data" / "features" / "labels.csv"

THRESHOLDS = {
    "accuracy":     0.80,
    "macro_f1":     0.75,
    "CLEAR_recall": 0.88,
}

LABEL_MAP = {"HOLD": 0, "MARKDOWN": 1, "PROMOTE": 2, "CLEAR": 3}
LABEL_INV = {v: k for k, v in LABEL_MAP.items()}


def evaluate(model_dir: Path = MODELS_DIR) -> dict:
    try:
        import catboost as cb  # type: ignore
        import pandas as pd
        from sklearn.metrics import (  # type: ignore
            accuracy_score,
            classification_report,
            f1_score,
        )
    except ImportError as e:
        raise SystemExit(f"Missing dependency: {e}") from e

    model_path = model_dir / "model.cbm"
    meta_path  = model_dir / "meta.json"

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    model = cb.CatBoostClassifier()
    model.load_model(str(model_path))

    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    feature_cols = meta.get("feature_cols", [])
    cat_features = meta.get("cat_features", [])

    df = pd.read_csv(FEATURES_PATH)
    labels = pd.read_csv(LABELS_PATH)
    df = df.merge(labels, on="sku_id", how="inner")
    df["label"] = df["rules_label"].map(LABEL_MAP)
    df = df.dropna(subset=["label"])

    X = df[feature_cols].fillna(-1) if feature_cols else df.drop(
        columns=["sku_id", "label", "rules_label"], errors="ignore"
    )
    y_true = df["label"].astype(int).tolist()

    pool = cb.Pool(X, cat_features=cat_features, feature_names=feature_cols)
    y_pred = model.predict(pool, prediction_type="Class").flatten().astype(int).tolist()

    accuracy = accuracy_score(y_true, y_pred)
    macro_f1 = f1_score(y_true, y_pred, average="macro")

    report = classification_report(
        y_true, y_pred,
        target_names=["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"],
        output_dict=True
    )
    clear_recall = report.get("CLEAR", {}).get("recall", 0.0)

    results = {
        "accuracy":     round(accuracy, 4),
        "macro_f1":     round(macro_f1, 4),
        "CLEAR_recall": round(clear_recall, 4),
    }

    log.info("Evaluation results: %s", results)

    gates_passed = all(
        results[k] >= THRESHOLDS[k] for k in THRESHOLDS
    )

    failed = [
        f"{k}: {results[k]:.3f} < {THRESHOLDS[k]}"
        for k in THRESHOLDS
        if results[k] < THRESHOLDS[k]
    ]

    if gates_passed:
        log.info("ALL PROMOTION GATES PASSED — model is ready to promote.")
    else:
        log.warning("PROMOTION BLOCKED — gates failed: %s", failed)

    return {**results, "gates_passed": gates_passed, "failed_gates": failed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=MODELS_DIR)
    args = parser.parse_args()
    result = evaluate(args.model_dir)
    print(json.dumps(result, indent=2))
