"""
Merge product-week features and labels into one training dataset file.

This is useful when you want one CSV where every row already contains:
  - the engineered input features
  - the training label

Execution flow:
  1. py services/decision_intelligence/features/clean_competitors.py
  2. py services/decision_intelligence/features/generate_historical_states.py
  3. py -m services.decision_intelligence.features.engineer
  4. py -m services.decision_intelligence.training.baseline
  5. py services/decision_intelligence/features/build_training_dataset.py

Run from the repo root:
    py services/decision_intelligence/features/build_training_dataset.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
FEATURES_PATH = ROOT / "data" / "features" / "features.csv"
LABELS_PATH = ROOT / "data" / "features" / "labels.csv"
OUTPUT_PATH = ROOT / "data" / "features" / "training_dataset.csv"


def _pick_join_keys(features_df: pd.DataFrame, labels_df: pd.DataFrame) -> list[str]:
    feature_cols = set(features_df.columns)
    label_cols = set(labels_df.columns)

    if "state_id" in feature_cols and "state_id" in label_cols:
        return ["state_id"]
    if {"sku_id", "week_of"}.issubset(feature_cols) and {"sku_id", "week_of"}.issubset(label_cols):
        return ["sku_id", "week_of"]
    if "sku_id" in feature_cols and "sku_id" in label_cols:
        return ["sku_id"]

    raise ValueError(
        "Could not determine how to merge features and labels. "
        "Expected state_id, or sku_id + week_of, or sku_id."
    )


def build_training_dataset(
    features_path: Path = FEATURES_PATH,
    labels_path: Path = LABELS_PATH,
    output_path: Path = OUTPUT_PATH,
) -> pd.DataFrame:
    if not features_path.exists():
        raise FileNotFoundError(
            f"Features file not found: {features_path}\n"
            "Run: py -m services.decision_intelligence.features.engineer"
        )
    if not labels_path.exists():
        raise FileNotFoundError(
            f"Labels file not found: {labels_path}\n"
            "Run: py -m services.decision_intelligence.training.baseline"
        )

    features_df = pd.read_csv(features_path)
    labels_df = pd.read_csv(labels_path)

    join_keys = _pick_join_keys(features_df, labels_df)

    if labels_df.duplicated(subset=join_keys).any():
        raise ValueError(f"labels.csv contains duplicate rows for join keys: {join_keys}")
    if features_df.duplicated(subset=join_keys).any():
        raise ValueError(f"features.csv contains duplicate rows for join keys: {join_keys}")

    label_extra_columns = [
        column for column in labels_df.columns
        if column not in join_keys and column not in features_df.columns
    ]
    labels_for_merge = labels_df[join_keys + label_extra_columns]
    merged_df = features_df.merge(labels_for_merge, on=join_keys, how="inner", validate="one_to_one")

    if len(merged_df) != len(features_df):
        missing = len(features_df) - len(merged_df)
        raise ValueError(
            f"Merged training dataset has {missing} fewer rows than features.csv. "
            "This means some feature rows do not have labels."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged_df.to_csv(output_path, index=False)

    print("\n" + "=" * 72)
    print("TRAINING DATASET SUMMARY")
    print("=" * 72)
    print(f"Features rows:       {len(features_df)}")
    print(f"Labels rows:         {len(labels_df)}")
    print(f"Merged rows:         {len(merged_df)}")
    print(f"Join keys:           {', '.join(join_keys)}")
    print(f"Output file:         {output_path}")
    if "rules_label" in merged_df.columns:
        print(f"Label distribution:  {merged_df['rules_label'].value_counts().to_dict()}")
    print("\nSample rows:")
    print(merged_df.head(5).to_string(index=False))
    print("=" * 72)

    return merged_df


if __name__ == "__main__":
    build_training_dataset()
