"""
CatBoost training pipeline for IE2 Decision Intelligence.

This version can:
  - train directly from a merged training_dataset.csv
  - fall back to features.csv + labels.csv when needed
  - run multiple hyperparameter trials
  - log each trial to MLflow
  - save the best model and a JSON summary of all runs

Typical usage from the repo root:
    py -m services.decision_intelligence.training.train

Example with explicit MLflow settings:
    py -m services.decision_intelligence.training.train ^
      --training-dataset data/features/training_dataset.csv ^
      --mlflow-tracking-uri http://127.0.0.1:5000 ^
      --mlflow-experiment ie2-product-week-catboost
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from itertools import product
from pathlib import Path


log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parents[3]
TRAINING_DATASET_PATH = ROOT / "data" / "features" / "training_dataset.csv"
FEATURES_PATH = ROOT / "data" / "features" / "features.csv"
LABELS_PATH = ROOT / "data" / "features" / "labels.csv"
MODELS_DIR = ROOT / "services" / "decision_intelligence" / "models" / "catboost_decision"

CATEGORICAL_FEATURES = ["category", "brand", "market_position", "brand_tier"]
IDENTIFIER_COLUMNS = {
    "state_id",
    "sku_id",
    "product_key",
    "style_code",
    "product_name",
    "week_of",
    "label",
    "approved_action",
    "rules_label",
    "ai_label",
    "ai_label_confidence",
    "ai_label_rationale",
    "ai_score_hold",
    "ai_score_markdown",
    "ai_score_promote",
    "ai_score_clear",
    "ai_label_disagrees_with_rules",
    "data_source",
    "synthetic_is_augmented",
    "synthetic_target_label",
    "synthetic_anchor_state_id",
    "synthetic_mutation_profile",
}
LABEL_MAP = {"HOLD": 0, "MARKDOWN": 1, "PROMOTE": 2, "CLEAR": 3}
LABEL_INV = {value: key for key, value in LABEL_MAP.items()}

DEFAULT_ITERATIONS_GRID = [300, 500, 800]
DEFAULT_LEARNING_RATE_GRID = [0.03, 0.05, 0.08]
DEFAULT_DEPTH_GRID = [4, 6, 8]
DEFAULT_L2_GRID = [3.0, 5.0]


def _pick_join_keys(left_columns: set[str], right_columns: set[str]) -> list[str]:
    if "state_id" in left_columns and "state_id" in right_columns:
        return ["state_id"]
    if {"sku_id", "week_of"}.issubset(left_columns) and {"sku_id", "week_of"}.issubset(right_columns):
        return ["sku_id", "week_of"]
    if "sku_id" in left_columns and "sku_id" in right_columns:
        return ["sku_id"]
    raise ValueError(
        "Could not determine label join keys. Expected state_id, or sku_id + week_of, or sku_id."
    )


def _parse_grid(value: str, cast):
    return [cast(item.strip()) for item in value.split(",") if item.strip()]


def _load_training_dataframe(
    training_dataset_path: Path,
    features_path: Path,
    labels_path: Path,
    outcome_file: Path | None,
    label_column: str,
):
    try:
        import pandas as pd
    except ImportError as e:
        raise SystemExit(
            f"Missing dependency: {e}\nRun: pip install pandas"
        ) from e

    if training_dataset_path.exists():
        df = pd.read_csv(training_dataset_path)
        if label_column in df.columns:
            df["label"] = df[label_column].map(LABEL_MAP)
            label_source = f"merged_training_dataset:{label_column}"
        elif "approved_action" in df.columns and label_column == "approved_action":
            df["label"] = df["approved_action"].map(LABEL_MAP)
            label_source = "merged_training_dataset_outcomes"
        else:
            raise ValueError(
                f"{training_dataset_path} exists but does not contain the requested label column '{label_column}'."
            )
        log.info("Loaded %d merged training rows from %s", len(df), training_dataset_path)
        return df, label_source

    if not features_path.exists():
        raise FileNotFoundError(
            f"Features file not found: {features_path}\n"
            "Run: python -m services.decision_intelligence.features.engineer"
        )

    df = pd.read_csv(features_path)
    log.info("Loaded %d feature rows from %s", len(df), features_path)

    if outcome_file and Path(outcome_file).exists():
        outcomes = pd.read_csv(outcome_file)
        join_keys = _pick_join_keys(set(df.columns), set(outcomes.columns))
        if label_column not in outcomes.columns:
            raise ValueError(f"Outcome file does not contain requested label column '{label_column}'.")
        outcomes = outcomes[join_keys + [label_column]]
        df = df.merge(outcomes, on=join_keys, how="inner")
        df["label"] = df[label_column].map(LABEL_MAP)
        label_source = f"merchant_outcomes:{label_column}"
        log.info("Using %d real merchant-approved labels", len(df))
    elif labels_path.exists():
        labels = pd.read_csv(labels_path)
        join_keys = _pick_join_keys(set(df.columns), set(labels.columns))
        if label_column not in labels.columns:
            raise ValueError(
                f"Labels file does not contain requested label column '{label_column}'. "
                "Use a merged training dataset if the target lives there."
            )
        labels = labels[join_keys + [label_column]]
        df = df.merge(labels, on=join_keys, how="inner")
        df["label"] = df[label_column].map(LABEL_MAP)
        label_source = f"labels_file:{label_column}"
        log.info("Using %d rules-engine labels (no real outcomes yet)", len(df))
    else:
        raise FileNotFoundError(
            f"No labels found at {labels_path}.\n"
            "Run: python -m services.decision_intelligence.training.baseline"
        )

    return df, label_source


def _build_feature_matrix(df):
    feature_cols = [
        column
        for column in df.columns
        if column not in IDENTIFIER_COLUMNS and not column.startswith("synthetic_")
    ]
    cat_idxs = [idx for idx, column in enumerate(feature_cols) if column in CATEGORICAL_FEATURES]
    X = df[feature_cols].fillna(-1)
    y = df["label"].astype(int)
    return X, y, feature_cols, cat_idxs


def _enrich_feature_space(df):
    import pandas as pd

    enriched = df.copy()

    days_of_supply = pd.to_numeric(enriched.get("days_of_supply"), errors="coerce").fillna(0.0)
    total_qty = pd.to_numeric(enriched.get("total_qty"), errors="coerce").fillna(0.0)
    margin_pct = pd.to_numeric(enriched.get("current_margin_pct"), errors="coerce").fillna(0.0)
    price_gap_pct = pd.to_numeric(enriched.get("price_gap_pct"), errors="coerce").fillna(0.0)
    comp_on_sale = pd.to_numeric(enriched.get("competitors_on_sale"), errors="coerce").fillna(0.0)
    comp_out = pd.to_numeric(enriched.get("competitors_out_of_stock"), errors="coerce").fillna(0.0)
    num_comp = pd.to_numeric(enriched.get("num_competitors"), errors="coerce").fillna(0.0)
    sell_through = pd.to_numeric(enriched.get("season_sell_through_pct"), errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)
    days_since_launch = pd.to_numeric(enriched.get("days_since_launch"), errors="coerce").fillna(0.0)
    days_since_discount = pd.to_numeric(enriched.get("days_since_last_discount"), errors="coerce").fillna(999.0)
    seasonality = pd.to_numeric(enriched.get("seasonality_score"), errors="coerce").fillna(1.0)
    event_score = pd.to_numeric(enriched.get("event_proximity_score"), errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)

    safe_num_comp = num_comp.replace(0, float("nan"))
    sale_pressure_ratio = comp_on_sale.div(safe_num_comp).fillna(0.0).clip(lower=0.0, upper=1.0)
    competitor_oos_ratio = comp_out.div(safe_num_comp).fillna(0.0).clip(lower=0.0, upper=1.0)
    markdown_margin_buffer = (margin_pct - 35.0).round(4)
    promote_margin_buffer = (margin_pct - 38.0).round(4)
    recent_discount_cooldown = ((21.0 - days_since_discount).clip(lower=0.0, upper=21.0) / 21.0).round(4)
    overpricing_signal = price_gap_pct.clip(lower=0.0, upper=0.40)
    stale_pressure = (1.0 - sell_through).clip(lower=0.0, upper=1.0)
    stock_staleness_index = ((days_of_supply.clip(lower=0.0, upper=240.0) / 150.0) * stale_pressure).clip(lower=0.0, upper=2.5).round(4)
    inventory_age_pressure = (
        ((days_of_supply - 90.0).clip(lower=0.0, upper=180.0) / 180.0)
        * ((days_since_launch - 180.0).clip(lower=0.0, upper=240.0) / 240.0)
    ).clip(lower=0.0, upper=1.5).round(4)
    overpricing_sale_pressure = (overpricing_signal * sale_pressure_ratio).clip(lower=0.0, upper=0.50).round(4)

    clearance_pressure_index = (
        ((days_of_supply - 120.0).clip(lower=0.0, upper=140.0) / 140.0) * 0.34
        + stale_pressure * 0.28
        + ((days_since_launch - 220.0).clip(lower=0.0, upper=220.0) / 220.0) * 0.18
        + (overpricing_signal / 0.35).clip(lower=0.0, upper=1.0) * 0.12
        + sale_pressure_ratio * 0.08
    ).clip(lower=0.0, upper=1.5).round(4)

    low_stock_signal = pd.concat(
        [
            ((14.0 - days_of_supply).clip(lower=0.0, upper=14.0) / 14.0),
            ((12.0 - total_qty).clip(lower=0.0, upper=12.0) / 12.0),
        ],
        axis=1,
    ).max(axis=1)
    stable_high_dos_signal = (
        ((days_of_supply - 70.0).clip(lower=0.0, upper=80.0) / 80.0)
        * (1.0 - sale_pressure_ratio)
        * (1.0 - (overpricing_signal / 0.15).clip(lower=0.0, upper=1.0))
    ).clip(lower=0.0, upper=1.0)
    moderate_stock = (1.0 - ((days_of_supply - 70.0).abs() / 70.0)).clip(lower=0.0, upper=1.0)
    low_margin_signal = ((35.5 - margin_pct).clip(lower=0.0, upper=15.0) / 15.0)
    hold_guardrail_index = (
        low_margin_signal * 0.40
        + recent_discount_cooldown * 0.24
        + low_stock_signal * 0.20
        + stable_high_dos_signal * 0.10
        + (moderate_stock * event_score) * 0.06
    ).clip(lower=0.0, upper=1.5).round(4)

    enriched["sale_pressure_ratio"] = sale_pressure_ratio.round(4)
    enriched["competitor_oos_ratio"] = competitor_oos_ratio.round(4)
    enriched["markdown_margin_buffer"] = markdown_margin_buffer
    enriched["promote_margin_buffer"] = promote_margin_buffer
    enriched["recent_discount_cooldown"] = recent_discount_cooldown
    enriched["stock_staleness_index"] = stock_staleness_index
    enriched["inventory_age_pressure"] = inventory_age_pressure
    enriched["overpricing_sale_pressure"] = overpricing_sale_pressure
    enriched["clearance_pressure_index"] = clearance_pressure_index
    enriched["hold_guardrail_index"] = hold_guardrail_index
    return enriched


def _compute_sample_weights(df):
    counts = df["label"].value_counts().to_dict()
    if not counts:
        return [], {}

    max_count = max(counts.values())
    class_weights = {
        int(label_id): round((max_count / count) ** 0.5, 4)
        for label_id, count in counts.items()
        if count > 0
    }

    weights: list[float] = []
    for _, row in df.iterrows():
        label_id = int(row["label"])
        label_name = LABEL_INV.get(label_id, "HOLD")
        weight = float(class_weights.get(label_id, 1.0))

        is_synthetic = int(float(row.get("synthetic_is_augmented", 0) or 0)) == 1
        if is_synthetic:
            weight *= 0.90

        dos = float(row.get("days_of_supply", 0.0) or 0.0)
        sell_through = float(row.get("season_sell_through_pct", 0.0) or 0.0)
        age = float(row.get("days_since_launch", 0.0) or 0.0)
        price_gap = float(row.get("price_gap_pct", 0.0) or 0.0)
        margin = float(row.get("current_margin_pct", 0.0) or 0.0)
        days_since_discount = float(row.get("days_since_last_discount", 999.0) or 999.0)
        qty = float(row.get("total_qty", 0.0) or 0.0)
        num_competitors = float(row.get("num_competitors", 0.0) or 0.0)
        event_score = float(row.get("event_proximity_score", 0.0) or 0.0)
        sale_pressure_ratio = float(row.get("sale_pressure_ratio", 0.0) or 0.0)
        clearance_pressure_index = float(row.get("clearance_pressure_index", 0.0) or 0.0)
        hold_guardrail_index = float(row.get("hold_guardrail_index", 0.0) or 0.0)

        if label_name == "CLEAR":
            if dos >= 125 and sell_through <= 0.16 and age >= 220:
                weight *= 1.45
            if price_gap >= 0.15:
                weight *= 1.10
            if (
                clearance_pressure_index >= 0.68
                and event_score >= 0.60
                and price_gap >= 0.18
                and 120 <= dos <= 160
            ):
                weight *= 1.55
            if is_synthetic and event_score < 0.35 and price_gap < 0.12:
                weight *= 0.92
        elif label_name == "HOLD":
            hold_signals = 0
            if margin < 36:
                hold_signals += 1
            if days_since_discount < 21:
                hold_signals += 1
            if qty < 15 or dos < 10:
                hold_signals += 1
            if num_competitors <= 1 and dos >= 80 and price_gap <= 0.05:
                hold_signals += 1
            weight *= 1.0 + hold_signals * 0.18
            if (
                hold_guardrail_index >= 0.22
                and event_score >= 0.60
                and 35 <= dos <= 110
            ):
                weight *= 1.35
            if margin <= 35.5 and price_gap <= 0.10 and days_since_discount >= 90:
                weight *= 1.18
        elif label_name == "MARKDOWN":
            if dos >= 80 and price_gap >= 0.12 and margin >= 38 and days_since_discount >= 21:
                weight *= 1.10
            if sale_pressure_ratio >= 0.45 and price_gap >= 0.18:
                weight *= 1.06
        elif label_name == "PROMOTE":
            if 25 <= dos <= 90 and margin >= 38 and price_gap <= 0.05 and event_score >= 0.50:
                weight *= 1.08

        weights.append(round(min(6.0, max(0.60, weight)), 4))

    return weights, class_weights


def _time_aware_split(df):
    import pandas as pd
    from sklearn.model_selection import train_test_split

    if "week_of" not in df.columns:
        shuffled = df.sample(frac=1, random_state=42).reset_index(drop=True)
        split_idx = int(len(shuffled) * 0.80)
        return shuffled.iloc[:split_idx].copy(), shuffled.iloc[split_idx:].copy()

    split_df = df.copy()
    split_df["_week_dt"] = pd.to_datetime(split_df["week_of"], errors="coerce")
    unique_weeks = sorted(split_df["_week_dt"].dropna().unique().tolist())

    if len(unique_weeks) < 3:
        shuffled = split_df.sample(frac=1, random_state=42).reset_index(drop=True)
        split_idx = int(len(shuffled) * 0.80)
        train_df = shuffled.iloc[:split_idx].copy()
        val_df = shuffled.iloc[split_idx:].copy()
    else:
        split_idx = max(1, int(len(unique_weeks) * 0.80))
        train_weeks = set(unique_weeks[:split_idx])
        val_weeks = set(unique_weeks[split_idx:])
        if not val_weeks:
            val_weeks = {unique_weeks[-1]}
            train_weeks = set(unique_weeks[:-1])

        train_df = split_df.loc[split_df["_week_dt"].isin(train_weeks)].copy()
        val_df = split_df.loc[split_df["_week_dt"].isin(val_weeks)].copy()

    all_labels = set(split_df["label"].dropna().astype(int).unique().tolist())
    train_labels = set(train_df["label"].dropna().astype(int).unique().tolist())
    val_labels = set(val_df["label"].dropna().astype(int).unique().tolist())

    if train_labels != all_labels or val_labels != all_labels:
        missing_train = sorted(all_labels - train_labels)
        missing_val = sorted(all_labels - val_labels)
        log.warning(
            "Time-aware split does not preserve all classes. Missing in train=%s, missing in val=%s. "
            "Falling back to stratified random split.",
            missing_train,
            missing_val,
        )
        stratify_labels = split_df["label"] if split_df["label"].nunique() > 1 else None
        train_df, val_df = train_test_split(
            split_df,
            test_size=0.20,
            random_state=42,
            stratify=stratify_labels,
        )

    train_df = train_df.drop(columns=["_week_dt"], errors="ignore")
    val_df = val_df.drop(columns=["_week_dt"], errors="ignore")
    return train_df, val_df


def _compute_metrics(model, X_val, y_val):
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support

    preds = model.predict(X_val)
    pred_labels = np.asarray(preds).reshape(-1).astype(int).tolist()
    metrics = {
        "val_accuracy": float(accuracy_score(y_val, pred_labels)),
        "val_macro_f1": float(f1_score(y_val, pred_labels, average="macro")),
        "val_weighted_f1": float(f1_score(y_val, pred_labels, average="weighted")),
    }

    precision, recall, f1, support = precision_recall_fscore_support(
        y_val,
        pred_labels,
        labels=list(LABEL_INV.keys()),
        zero_division=0,
    )
    for idx, label_id in enumerate(LABEL_INV.keys()):
        label_name = LABEL_INV[label_id].lower()
        metrics[f"precision_{label_name}"] = float(precision[idx])
        metrics[f"recall_{label_name}"] = float(recall[idx])
        metrics[f"f1_{label_name}"] = float(f1[idx])
        metrics[f"support_{label_name}"] = float(support[idx])

    return metrics


def _log_run_to_mlflow(
    *,
    run_name: str,
    params: dict,
    metrics: dict,
    label_source: str,
    feature_cols: list[str],
    model_path: Path | None,
    tracking_uri: str | None,
    experiment_name: str,
):
    try:
        import mlflow
    except ImportError:
        log.warning("mlflow is not installed in the active environment, so this run was not logged.")
        return

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    try:
        with mlflow.start_run(run_name=run_name):
            mlflow.log_params(params)
            mlflow.log_param("label_source", label_source)
            mlflow.log_param("num_features", len(feature_cols))
            mlflow.log_metrics(metrics)
            try:
                mlflow.log_text(
                    json.dumps({"feature_columns": feature_cols}, indent=2),
                    "feature_columns.json",
                )
            except Exception as exc:
                log.warning("MLflow feature-column artifact logging failed for run %s: %s", run_name, exc)
            if model_path and model_path.exists():
                try:
                    mlflow.log_artifact(str(model_path), artifact_path="model_files")
                except Exception as exc:
                    log.warning("MLflow model artifact logging failed for run %s: %s", run_name, exc)
    except Exception as exc:
        log.warning("MLflow logging failed for run %s: %s", run_name, exc)


def train(
    *,
    outcome_file: Path | None = None,
    training_dataset_path: Path = TRAINING_DATASET_PATH,
    features_path: Path = FEATURES_PATH,
    labels_path: Path = LABELS_PATH,
    models_dir: Path = MODELS_DIR,
    label_column: str = "rules_label",
    iterations_grid: list[int] | None = None,
    learning_rate_grid: list[float] | None = None,
    depth_grid: list[int] | None = None,
    l2_leaf_reg_grid: list[float] | None = None,
    mlflow_tracking_uri: str | None = None,
    mlflow_experiment: str = "ie2-product-week-catboost",
) -> Path:
    """
    Train multiple CatBoost models, track them in MLflow, and save the best one.
    """
    try:
        import catboost as cb  # type: ignore
        import pandas as pd
    except ImportError as e:
        raise SystemExit(
            f"Missing dependency: {e}\nRun: pip install catboost pandas scikit-learn mlflow"
        ) from e

    iterations_grid = iterations_grid or DEFAULT_ITERATIONS_GRID
    learning_rate_grid = learning_rate_grid or DEFAULT_LEARNING_RATE_GRID
    depth_grid = depth_grid or DEFAULT_DEPTH_GRID
    l2_leaf_reg_grid = l2_leaf_reg_grid or DEFAULT_L2_GRID

    df, label_source = _load_training_dataframe(
        training_dataset_path=training_dataset_path,
        features_path=features_path,
        labels_path=labels_path,
        outcome_file=outcome_file,
        label_column=label_column,
    )

    df = df.dropna(subset=["label"]).copy()
    if len(df) < 50:
        raise ValueError(f"Only {len(df)} labeled examples - not enough for reliable training.")

    train_df, val_df = _time_aware_split(df)
    if train_df.empty or val_df.empty:
        raise ValueError("Train/validation split failed. Check week_of coverage in the dataset.")

    train_df = _enrich_feature_space(train_df)
    val_df = _enrich_feature_space(val_df)

    X_train, y_train, feature_cols, cat_idxs = _build_feature_matrix(train_df)
    X_val, y_val, _, _ = _build_feature_matrix(val_df)
    train_weights, class_weights = _compute_sample_weights(train_df)

    train_pool = cb.Pool(X_train, y_train, cat_features=cat_idxs, feature_names=feature_cols, weight=train_weights)
    val_pool = cb.Pool(X_val, y_val, cat_features=cat_idxs, feature_names=feature_cols)

    trial_results: list[dict] = []
    best_trial: dict | None = None

    hyperparameter_grid = list(product(iterations_grid, learning_rate_grid, depth_grid, l2_leaf_reg_grid))
    log.info("Starting %d hyperparameter trials", len(hyperparameter_grid))

    models_dir.mkdir(parents=True, exist_ok=True)

    for trial_number, (iterations, learning_rate, depth, l2_leaf_reg) in enumerate(hyperparameter_grid, start=1):
        params = {
            "iterations": int(iterations),
            "learning_rate": float(learning_rate),
            "depth": int(depth),
            "l2_leaf_reg": float(l2_leaf_reg),
            "loss_function": "MultiClass",
            "eval_metric": "Accuracy",
            "classes_count": 4,
            "cat_features": cat_idxs,
            "early_stopping_rounds": 30,
            "random_seed": 42,
            "bootstrap_type": "Bernoulli",
            "subsample": 0.9,
            "verbose": 100,
        }

        log.info(
            "Trial %d/%d: iterations=%s, learning_rate=%s, depth=%s, l2_leaf_reg=%s",
            trial_number,
            len(hyperparameter_grid),
            iterations,
            learning_rate,
            depth,
            l2_leaf_reg,
        )

        model = cb.CatBoostClassifier(**params)
        model.fit(train_pool, eval_set=val_pool)

        metrics = _compute_metrics(model, X_val, y_val)
        best_iteration = model.get_best_iteration()
        metrics["best_iteration"] = int(best_iteration if best_iteration is not None and best_iteration >= 0 else params["iterations"])

        trial_model_path = models_dir / f"trial_{trial_number:03d}.cbm"
        model.save_model(str(trial_model_path))

        trial_record = {
            "trial_number": trial_number,
            "params": {
                "iterations": int(iterations),
                "learning_rate": float(learning_rate),
                "depth": int(depth),
                "l2_leaf_reg": float(l2_leaf_reg),
                "sample_weight_mode": "heuristic_v1",
            },
            "metrics": metrics,
            "model_path": str(trial_model_path),
        }
        trial_results.append(trial_record)

        _log_run_to_mlflow(
            run_name=f"catboost_trial_{trial_number:03d}",
            params=trial_record["params"],
            metrics=metrics,
            label_source=label_source,
            feature_cols=feature_cols,
            model_path=trial_model_path,
            tracking_uri=mlflow_tracking_uri,
            experiment_name=mlflow_experiment,
        )

        if best_trial is None:
            best_trial = trial_record
        else:
            current = (trial_record["metrics"]["val_macro_f1"], trial_record["metrics"]["val_accuracy"])
            best = (best_trial["metrics"]["val_macro_f1"], best_trial["metrics"]["val_accuracy"])
            if current > best:
                best_trial = trial_record

    if best_trial is None:
        raise RuntimeError("No training trials were completed.")

    best_model_path = Path(best_trial["model_path"])
    final_model_path = models_dir / "model.cbm"
    final_model_path.write_bytes(best_model_path.read_bytes())

    summary = {
        "label_source": label_source,
        "training_dataset_path": str(training_dataset_path if training_dataset_path.exists() else features_path),
        "train_examples": len(train_df),
        "val_examples": len(val_df),
        "feature_cols": feature_cols,
        "cat_features": CATEGORICAL_FEATURES,
        "train_class_weights": class_weights,
        "train_sample_weight_summary": {
            "min": min(train_weights) if train_weights else None,
            "max": max(train_weights) if train_weights else None,
            "mean": round(sum(train_weights) / len(train_weights), 4) if train_weights else None,
        },
        "label_map": LABEL_MAP,
        "label_column": label_column,
        "mlflow_tracking_uri": mlflow_tracking_uri,
        "mlflow_experiment": mlflow_experiment,
        "num_trials": len(trial_results),
        "best_trial": best_trial,
        "all_trials": trial_results,
    }
    (models_dir / "meta.json").write_text(json.dumps(summary, indent=2))

    log.info(
        "Best trial: #%s macro_f1=%.4f accuracy=%.4f",
        best_trial["trial_number"],
        best_trial["metrics"]["val_macro_f1"],
        best_trial["metrics"]["val_accuracy"],
    )
    log.info("Best model saved -> %s", final_model_path)
    log.info("Trial summary saved -> %s", models_dir / "meta.json")
    return final_model_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train IE2 CatBoost model with hyperparameter search and MLflow logging")
    parser.add_argument("--outcome-file", default=None, help="CSV with real merchant-approved labels")
    parser.add_argument("--training-dataset", default=str(TRAINING_DATASET_PATH), help="Merged dataset with features and label column")
    parser.add_argument("--features-path", default=str(FEATURES_PATH), help="Fallback features.csv path if merged dataset is unavailable")
    parser.add_argument("--labels-path", default=str(LABELS_PATH), help="Fallback labels.csv path if merged dataset is unavailable")
    parser.add_argument("--label-column", default="rules_label", help="Target column to train on, e.g. rules_label or ai_label")
    parser.add_argument("--iterations-grid", default="300,500,800", help="Comma-separated CatBoost iterations values")
    parser.add_argument("--learning-rate-grid", default="0.03,0.05,0.08", help="Comma-separated learning rates")
    parser.add_argument("--depth-grid", default="4,6,8", help="Comma-separated tree depths")
    parser.add_argument("--l2-grid", default="3,5", help="Comma-separated L2 leaf regularization values")
    parser.add_argument("--mlflow-tracking-uri", default=None, help="MLflow tracking URI, e.g. http://127.0.0.1:5000")
    parser.add_argument("--mlflow-experiment", default="ie2-product-week-catboost", help="MLflow experiment name")
    args = parser.parse_args()

    train(
        outcome_file=Path(args.outcome_file) if args.outcome_file else None,
        training_dataset_path=Path(args.training_dataset),
        features_path=Path(args.features_path),
        labels_path=Path(args.labels_path),
        label_column=args.label_column,
        iterations_grid=_parse_grid(args.iterations_grid, int),
        learning_rate_grid=_parse_grid(args.learning_rate_grid, float),
        depth_grid=_parse_grid(args.depth_grid, int),
        l2_leaf_reg_grid=_parse_grid(args.l2_grid, float),
        mlflow_tracking_uri=args.mlflow_tracking_uri,
        mlflow_experiment=args.mlflow_experiment,
    )
