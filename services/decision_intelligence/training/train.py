"""
CatBoost training pipeline for IE2 Decision Intelligence.

STATUS: v1 stub — CatBoost will be trained once real merchant-approval
        outcome data is accumulated (target: month 3+).

Current behaviour:
  - Loads features.csv produced by features/engineer.py
  - Falls back to rules engine labels when no real outcomes exist
  - Trains a CatBoost classification model (4-class: HOLD/MARKDOWN/PROMOTE/CLEAR)
  - Saves the model to models/catboost_decision/

Usage:
    python -m services.decision_intelligence.training.train [--outcome-file PATH]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ── Constants ──────────────────────────────────────────────────────────────────

# Resolve to repo root (retail-radar-ai/)
ROOT = Path(__file__).resolve().parents[3]
FEATURES_PATH = ROOT / "data" / "features" / "features.csv"
MODELS_DIR = ROOT / "services" / "decision_intelligence" / "models" / "catboost_decision"
LABELS_PATH = ROOT / "data" / "features" / "labels.csv"

CATEGORICAL_FEATURES = ["category", "brand", "market_position", "brand_tier"]

LABEL_MAP = {"HOLD": 0, "MARKDOWN": 1, "PROMOTE": 2, "CLEAR": 3}
LABEL_INV = {v: k for k, v in LABEL_MAP.items()}

# ── Training pipeline ──────────────────────────────────────────────────────────

def train(
    outcome_file: Path | None = None,
    features_path: Path = FEATURES_PATH,
    models_dir: Path = MODELS_DIR,
    iterations: int = 500,
    learning_rate: float = 0.05,
    depth: int = 6,
) -> Path:
    """
    Train a CatBoost multi-class classifier on features + labels.

    Args:
        outcome_file: Path to CSV with columns [sku_id, approved_action] from
                      merchant approvals (real labels). If None, uses rules-engine
                      labels from labels.csv.
        features_path: features.csv produced by engineer.py
        models_dir: Output directory for saved model
        iterations, learning_rate, depth: CatBoost hyperparams

    Returns:
        Path to saved model directory.
    """
    try:
        import catboost as cb  # type: ignore
        import pandas as pd
    except ImportError as e:
        raise SystemExit(
            f"Missing dependency: {e}\nRun: pip install catboost pandas"
        ) from e

    # ── Load features ─────────────────────────────────────────────────────────
    if not features_path.exists():
        raise FileNotFoundError(
            f"Features file not found: {features_path}\n"
            "Run: python -m services.decision_intelligence.features.engineer"
        )

    df = pd.read_csv(features_path)
    log.info("Loaded %d SKU features from %s", len(df), features_path)

    # ── Load labels ───────────────────────────────────────────────────────────
    if outcome_file and Path(outcome_file).exists():
        outcomes = pd.read_csv(outcome_file)[["sku_id", "approved_action"]]
        df = df.merge(outcomes, on="sku_id", how="inner")
        df["label"] = df["approved_action"].map(LABEL_MAP)
        label_source = "merchant_outcomes"
        log.info("Using %d real merchant-approved labels", len(df))
    elif LABELS_PATH.exists():
        labels = pd.read_csv(LABELS_PATH)[["sku_id", "rules_label"]]
        df = df.merge(labels, on="sku_id", how="inner")
        df["label"] = df["rules_label"].map(LABEL_MAP)
        label_source = "rules_engine"
        log.info("Using %d rules-engine labels (no real outcomes yet)", len(df))
    else:
        raise FileNotFoundError(
            f"No labels found at {LABELS_PATH}.\n"
            "Run: python -m services.decision_intelligence.training.baseline"
        )

    df = df.dropna(subset=["label"])
    if len(df) < 50:
        raise ValueError(
            f"Only {len(df)} labeled examples — not enough for reliable training."
        )

    # ── Build feature matrix ──────────────────────────────────────────────────
    feature_cols = [c for c in df.columns if c not in {
        "sku_id", "product_name", "label",
        "approved_action", "rules_label",
    }]

    cat_idxs = [
        i for i, c in enumerate(feature_cols) if c in CATEGORICAL_FEATURES
    ]

    X = df[feature_cols].fillna(-1)
    y = df["label"].astype(int)

    # ── Shuffle + Train / eval split ───────────────────────────────────────────
    df_shuffled = pd.DataFrame({"X": X.values.tolist(), "y": y.values}).sample(
        frac=1, random_state=42
    ).reset_index(drop=True)
    X = pd.DataFrame(df_shuffled["X"].tolist(), columns=feature_cols)
    y = df_shuffled["y"].astype(int)
    split = int(len(X) * 0.80)
    X_train, X_val = X.iloc[:split], X.iloc[split:]
    y_train, y_val = y.iloc[:split], y.iloc[split:]

    train_pool = cb.Pool(X_train, y_train, cat_features=cat_idxs,
                         feature_names=feature_cols)
    val_pool   = cb.Pool(X_val,   y_val,   cat_features=cat_idxs,
                         feature_names=feature_cols)

    # ── CatBoost ──────────────────────────────────────────────────────────────
    model = cb.CatBoostClassifier(
        iterations=iterations,
        learning_rate=learning_rate,
        depth=depth,
        loss_function="MultiClass",
        classes_count=4,
        eval_metric="Accuracy",
        class_names=["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"],
        cat_features=cat_idxs,
        early_stopping_rounds=30,
        random_seed=42,
        verbose=100,
    )

    model.fit(train_pool, eval_set=val_pool)

    # ── Save model ────────────────────────────────────────────────────────────
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / "model.cbm"
    model.save_model(str(model_path))

    meta = {
        "label_source": label_source,
        "train_examples": len(X_train),
        "val_examples": len(X_val),
        "feature_cols": feature_cols,
        "cat_features": CATEGORICAL_FEATURES,
        "catboost_iterations": iterations,
        "catboost_learning_rate": learning_rate,
        "catboost_depth": depth,
        "label_map": LABEL_MAP,
    }
    (MODELS_DIR / "meta.json").write_text(json.dumps(meta, indent=2))

    log.info("Model saved → %s", model_path)
    return model_path


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train IE2 CatBoost model")
    parser.add_argument("--outcome-file", default=None,
                        help="CSV with real merchant-approved labels")
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--depth", type=int, default=6)
    args = parser.parse_args()

    train(
        outcome_file=args.outcome_file,
        iterations=args.iterations,
        learning_rate=args.learning_rate,
        depth=args.depth,
    )
