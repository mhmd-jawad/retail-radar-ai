"""
Build leak-safe RDS candidate training data.

This script keeps the newest real RDS week as a real-only holdout, then
generates controlled augmentation from the older real training rows only.
That prevents synthetic variants from the same anchor patterns leaking into
the test set used for candidate acceptance.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from services.decision_intelligence.features.augment_training_dataset import build_augmented_training_dataset
from services.decision_intelligence.features.build_rds_expanded_dataset import postprocess_augmented_dataset


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data" / "features" / "rds_ai_labeled_dataset.csv"
DEFAULT_TRAIN_REAL = ROOT / "data" / "features" / "rds_leak_safe_train_real.csv"
DEFAULT_TEST_REAL = ROOT / "data" / "features" / "rds_leak_safe_test_real.csv"
DEFAULT_AUG_TRAINING = ROOT / "data" / "features" / "rds_leak_safe_training_dataset_augmented.csv"
DEFAULT_AUG_AI = ROOT / "data" / "features" / "rds_leak_safe_ai_labeled_dataset_augmented.csv"
DEFAULT_AUG_SUMMARY = ROOT / "data" / "reports" / "rds_leak_safe_training_dataset_augmentation_summary.json"
DEFAULT_SPLIT_SUMMARY = ROOT / "data" / "reports" / "rds_leak_safe_training_dataset_summary.json"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _label_counts(df: pd.DataFrame) -> dict[str, int]:
    if "ai_label" not in df.columns:
        return {}
    return {str(label): int(count) for label, count in df["ai_label"].value_counts().items()}


def build_leak_safe_dataset(
    *,
    input_path: Path = DEFAULT_INPUT,
    train_real_output: Path = DEFAULT_TRAIN_REAL,
    test_real_output: Path = DEFAULT_TEST_REAL,
    augmented_training_output: Path = DEFAULT_AUG_TRAINING,
    augmented_ai_output: Path = DEFAULT_AUG_AI,
    augmentation_summary_output: Path = DEFAULT_AUG_SUMMARY,
    split_summary_output: Path = DEFAULT_SPLIT_SUMMARY,
    holdout_weeks: int = 1,
    clear_count: int = 700,
    hold_count: int = 5400,
    promote_count: int = 900,
    markdown_count: int = 4000,
    max_copies_per_anchor: int = 55,
    seed: int = 126,
) -> dict[str, Any]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input real RDS labeled dataset not found: {input_path}")
    if holdout_weeks < 1:
        raise ValueError("holdout_weeks must be >= 1")

    real = pd.read_csv(input_path)
    if "week_of" not in real.columns:
        raise ValueError("Input dataset must contain week_of for leak-safe time split.")

    real["_week_dt"] = pd.to_datetime(real["week_of"], errors="coerce")
    weeks = sorted(real["_week_dt"].dropna().unique().tolist())
    if len(weeks) <= holdout_weeks:
        raise ValueError(
            f"Need more than {holdout_weeks} real weeks for a holdout split; found {len(weeks)}."
        )

    test_weeks = set(weeks[-holdout_weeks:])
    train_real = real.loc[~real["_week_dt"].isin(test_weeks)].drop(columns=["_week_dt"]).copy()
    test_real = real.loc[real["_week_dt"].isin(test_weeks)].drop(columns=["_week_dt"]).copy()

    train_real_output.parent.mkdir(parents=True, exist_ok=True)
    test_real_output.parent.mkdir(parents=True, exist_ok=True)
    train_real.to_csv(train_real_output, index=False)
    test_real.to_csv(test_real_output, index=False)

    anchor_ai_output = train_real_output.with_name(f"{train_real_output.stem}_augmentation_anchor.csv")
    augmentation_report = build_augmented_training_dataset(
        training_dataset_path=train_real_output,
        ai_labels_path=anchor_ai_output,
        augmented_training_output=augmented_training_output,
        augmented_ai_output=augmented_ai_output,
        summary_report_output=augmentation_summary_output,
        target_counts={
            "CLEAR": clear_count,
            "HOLD": hold_count,
            "PROMOTE": promote_count,
            "MARKDOWN": markdown_count,
        },
        seed=seed,
        max_copies_per_anchor=max_copies_per_anchor,
        refresh_ai_labels=True,
    )
    augmented = postprocess_augmented_dataset(augmented_ai_output)

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_real_dataset": str(input_path),
        "outputs": {
            "train_real": str(train_real_output),
            "test_real": str(test_real_output),
            "augmented_training_dataset": str(augmented_training_output),
            "augmented_ai_labeled_dataset": str(augmented_ai_output),
            "augmentation_summary": str(augmentation_summary_output),
        },
        "split": {
            "holdout_weeks": holdout_weeks,
            "train_weeks": [str(pd.Timestamp(week).date()) for week in weeks[:-holdout_weeks]],
            "test_weeks": [str(pd.Timestamp(week).date()) for week in weeks[-holdout_weeks:]],
        },
        "row_counts": {
            "real_total": int(len(real)),
            "train_real": int(len(train_real)),
            "test_real": int(len(test_real)),
            "augmented_final": int(len(augmented)),
            "synthetic_rows": int(len(augmented) - len(train_real)),
        },
        "label_distribution": {
            "real_total": _label_counts(real),
            "train_real": _label_counts(train_real),
            "test_real": _label_counts(test_real),
            "augmented_final": _label_counts(augmented),
        },
        "row_source_distribution": augmented["row_source"].value_counts().to_dict()
        if "row_source" in augmented.columns
        else {},
        "sample_weight_distribution": augmented["sample_weight_hint"].value_counts().to_dict()
        if "sample_weight_hint" in augmented.columns
        else {},
        "augmentation": augmentation_report,
    }

    split_summary_output.parent.mkdir(parents=True, exist_ok=True)
    split_summary_output.write_text(json.dumps(_json_safe(summary), indent=2) + "\n", encoding="utf-8")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build leak-safe RDS train/test + train-only augmentation datasets.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--train-real-output", type=Path, default=DEFAULT_TRAIN_REAL)
    parser.add_argument("--test-real-output", type=Path, default=DEFAULT_TEST_REAL)
    parser.add_argument("--augmented-training-output", type=Path, default=DEFAULT_AUG_TRAINING)
    parser.add_argument("--augmented-ai-output", type=Path, default=DEFAULT_AUG_AI)
    parser.add_argument("--augmentation-summary-output", type=Path, default=DEFAULT_AUG_SUMMARY)
    parser.add_argument("--split-summary-output", type=Path, default=DEFAULT_SPLIT_SUMMARY)
    parser.add_argument("--holdout-weeks", type=int, default=1)
    parser.add_argument("--clear-count", type=int, default=700)
    parser.add_argument("--hold-count", type=int, default=5400)
    parser.add_argument("--promote-count", type=int, default=900)
    parser.add_argument("--markdown-count", type=int, default=4000)
    parser.add_argument("--max-copies-per-anchor", type=int, default=55)
    parser.add_argument("--seed", type=int, default=126)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = build_leak_safe_dataset(
        input_path=args.input,
        train_real_output=args.train_real_output,
        test_real_output=args.test_real_output,
        augmented_training_output=args.augmented_training_output,
        augmented_ai_output=args.augmented_ai_output,
        augmentation_summary_output=args.augmentation_summary_output,
        split_summary_output=args.split_summary_output,
        holdout_weeks=args.holdout_weeks,
        clear_count=args.clear_count,
        hold_count=args.hold_count,
        promote_count=args.promote_count,
        markdown_count=args.markdown_count,
        max_copies_per_anchor=args.max_copies_per_anchor,
        seed=args.seed,
    )
    print(json.dumps(_json_safe(summary), indent=2))


if __name__ == "__main__":
    main()
