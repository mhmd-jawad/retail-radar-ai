"""
Create a controlled, realistic augmented training dataset from real product-week rows.

This script:
  1. Reads data/features/training_dataset.csv
  2. Uses data/features/ai_labeled_dataset.csv as an anchor-scoring guide
  3. Generates targeted synthetic rows for underrepresented classes
  4. Recomputes dependent feature columns consistently
  5. Recomputes rules labels for synthetic rows
  6. Writes an augmented training dataset and a relabeled AI dataset

Run from the repo root:
    py -m services.decision_intelligence.features.augment_training_dataset
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from services.decision_intelligence.features.build_ai_labeled_dataset import (
    OUTPUT_PATH as AI_LABELS_PATH,
    TRAINING_DATASET_PATH,
    _score_row,
    build_ai_labeled_dataset,
)
from services.decision_intelligence.training.baseline import _assign_label


ROOT = Path(__file__).resolve().parents[3]
AUGMENTED_TRAINING_DATASET_PATH = ROOT / "data" / "features" / "training_dataset_augmented.csv"
AUGMENTED_AI_LABELS_PATH = ROOT / "data" / "features" / "ai_labeled_dataset_augmented.csv"
SUMMARY_REPORT_PATH = ROOT / "data" / "reports" / "training_dataset_augmentation_summary.json"

TARGET_LABEL_ORDER = ["CLEAR", "HOLD", "PROMOTE", "MARKDOWN"]
AI_SCORE_COLUMNS = {
    "HOLD": "ai_score_hold",
    "MARKDOWN": "ai_score_markdown",
    "PROMOTE": "ai_score_promote",
    "CLEAR": "ai_score_clear",
}
DEFAULT_TARGET_COUNTS = {
    "CLEAR": 420,
    "HOLD": 180,
    "PROMOTE": 220,
    "MARKDOWN": 240,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        if pd.isna(value):
            return default
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _anchored_float(
    current: Any,
    low: float,
    high: float,
    rng: random.Random,
    anchor_weight: float = 0.35,
    decimals: int = 4,
) -> float:
    current_value = _safe_float(current, (low + high) / 2.0)
    sampled = rng.uniform(low, high)
    blended = current_value * anchor_weight + sampled * (1.0 - anchor_weight)
    return round(clamp(blended, low, high), decimals)


def _anchored_int(
    current: Any,
    low: int,
    high: int,
    rng: random.Random,
    anchor_weight: float = 0.35,
) -> int:
    current_value = _safe_float(current, (low + high) / 2.0)
    sampled = rng.uniform(low, high)
    blended = current_value * anchor_weight + sampled * (1.0 - anchor_weight)
    return int(round(clamp(blended, low, high)))


def _market_position_from_gap(price_gap_pct: float) -> str:
    if price_gap_pct > 0.15:
        return "premium"
    if price_gap_pct > 0.05:
        return "above_market"
    if price_gap_pct > -0.05:
        return "at_market"
    if price_gap_pct > -0.15:
        return "below_market"
    return "deep_value"


def _load_or_build_ai_labels(
    training_dataset_path: Path,
    ai_labels_path: Path,
    *,
    refresh: bool = False,
) -> pd.DataFrame:
    # Always rebuild from the current scoring code so anchor selection is aligned
    # with today's labeler rather than a potentially stale CSV artifact.
    _ = refresh
    return build_ai_labeled_dataset(training_dataset_path=training_dataset_path, output_path=ai_labels_path)


def _build_inventory_medians(training_df: pd.DataFrame) -> dict[tuple[str, str], float]:
    grouped = (
        training_df.groupby(["week_of", "category"], dropna=False)["total_qty"]
        .median()
        .to_dict()
    )
    return {
        (str(week_of), str(category)): float(median)
        for (week_of, category), median in grouped.items()
    }


def _prepare_base_dataframe(training_df: pd.DataFrame, ai_df: pd.DataFrame) -> pd.DataFrame:
    ai_columns = [
        "state_id",
        "ai_label",
        "ai_label_confidence",
        "ai_score_hold",
        "ai_score_markdown",
        "ai_score_promote",
        "ai_score_clear",
    ]
    merged = training_df.merge(ai_df[ai_columns], on="state_id", how="left", validate="one_to_one")
    if "data_source" not in merged.columns:
        merged["data_source"] = "real"
    merged["synthetic_is_augmented"] = merged.get("synthetic_is_augmented", 0)
    return merged


def _select_anchor_pool(base_df: pd.DataFrame, target_label: str) -> pd.DataFrame:
    df = base_df.copy()

    if target_label == "CLEAR":
        sale_pressure = (
            pd.to_numeric(df["competitors_on_sale"], errors="coerce").fillna(0.0)
            .div(pd.to_numeric(df["num_competitors"], errors="coerce").replace(0, float("nan")))
            .fillna(0.0)
        )
        pool = df[
            (df["days_of_supply"] >= 95)
            & (df["season_sell_through_pct"] <= 0.45)
            & (df["days_since_launch"] >= 100)
        ].copy()
        if pool.empty:
            pool = df[df["days_of_supply"] >= 75].copy()
        pool["_anchor_weight"] = (
            pool["ai_score_clear"].fillna(0.0)
            + pool["days_of_supply"].clip(lower=0, upper=240) / 240.0
            + (0.55 - pool["season_sell_through_pct"].clip(lower=0.0, upper=0.55))
            + pool["days_since_launch"].clip(lower=0, upper=365) / 365.0
            + pd.to_numeric(pool["price_gap_pct"], errors="coerce").fillna(0.0).clip(lower=0.0, upper=0.35) * 1.7
            + sale_pressure.loc[pool.index].clip(lower=0.0, upper=1.0) * 0.8
            + (pool["market_position"].astype(str) == "premium").astype(float) * 0.35
        )
    elif target_label == "HOLD":
        recent_discount_signal = (
            (21.0 - pd.to_numeric(df["days_since_last_discount"], errors="coerce").fillna(999.0))
            .clip(lower=0.0, upper=21.0)
            / 21.0
        )
        margin_guardrail = (
            (36.0 - pd.to_numeric(df["current_margin_pct"], errors="coerce").fillna(100.0))
            .clip(lower=0.0, upper=15.0)
            / 15.0
        )
        low_stock_signal = (
            (15.0 - pd.to_numeric(df["total_qty"], errors="coerce").fillna(999.0))
            .clip(lower=0.0, upper=15.0)
            / 15.0
        )
        pool = df[
            (df["ai_label"] == "HOLD")
            & (
                (pd.to_numeric(df["current_margin_pct"], errors="coerce").fillna(100.0) <= 38.0)
                | (pd.to_numeric(df["days_since_last_discount"], errors="coerce").fillna(999.0) <= 35.0)
                | (pd.to_numeric(df["total_qty"], errors="coerce").fillna(999.0) <= 18.0)
                | (
                    (pd.to_numeric(df["days_of_supply"], errors="coerce").fillna(0.0) >= 70.0)
                    & (pd.to_numeric(df["num_competitors"], errors="coerce").fillna(0.0) <= 1.0)
                    & (pd.to_numeric(df["price_gap_pct"], errors="coerce").fillna(0.0) <= 0.05)
                )
            )
        ].copy()
        if pool.empty:
            pool = df[df["ai_label"] == "HOLD"].copy()
        pool["_anchor_weight"] = (
            pool["ai_score_hold"].fillna(0.0)
            + recent_discount_signal.loc[pool.index] * 1.1
            + margin_guardrail.loc[pool.index] * 1.0
            + low_stock_signal.loc[pool.index] * 1.0
            + (
                pd.to_numeric(pool["days_of_supply"], errors="coerce").fillna(0.0)
                .clip(lower=0.0, upper=140.0)
                / 140.0
            ) * 0.4
        )
    elif target_label == "PROMOTE":
        pool = df[
            (df["ai_label"] == "PROMOTE")
            & (df["current_margin_pct"] >= 38)
            & (df["days_of_supply"].between(18, 110))
        ].copy()
        if pool.empty:
            pool = df[
                (df["current_margin_pct"] >= 38)
                & (df["days_of_supply"].between(18, 110))
                & ((df["seasonality_score"] >= 1.08) | (df["event_proximity_score"] >= 0.50))
            ].copy()
        if pool.empty:
            pool = df[(df["current_margin_pct"] >= 35) & (df["days_of_supply"].between(15, 120))].copy()
        pool["_anchor_weight"] = (
            pool["ai_score_promote"].fillna(0.0)
            + pool["seasonality_score"].clip(lower=0.5, upper=1.7)
            + pool["event_proximity_score"].clip(lower=0.0, upper=1.0) * 1.4
            + (1.0 - (pool["price_gap_pct"].abs().clip(lower=0.0, upper=0.18) / 0.18))
            + pool["current_margin_pct"].clip(lower=35.0, upper=65.0) / 100.0
        )
    elif target_label == "MARKDOWN":
        pool = df[
            (df["current_margin_pct"] >= 35)
            & (df["days_of_supply"] >= 55)
            & (df["price_gap_pct"] >= 0.0)
        ].copy()
        if pool.empty:
            pool = df[(df["current_margin_pct"] >= 32) & (df["days_of_supply"] >= 45)].copy()
        comp_on_sale = pd.to_numeric(pool["competitors_on_sale"], errors="coerce").fillna(0.0)
        num_competitors = pd.to_numeric(pool["num_competitors"], errors="coerce").replace(0, float("nan"))
        sale_pressure = comp_on_sale.div(num_competitors).fillna(0.0)
        pool["_anchor_weight"] = (
            pool["ai_score_markdown"].fillna(0.0)
            + pool["price_gap_pct"].clip(lower=0.0, upper=0.30) * 3.0
            + sale_pressure.clip(lower=0.0, upper=1.0)
            + pool["days_of_supply"].clip(lower=0, upper=180) / 180.0
        )
    else:
        raise ValueError(f"Unsupported target label: {target_label}")

    if pool.empty:
        raise ValueError(f"No anchor rows available for target label {target_label}")

    pool["_anchor_weight"] = pool["_anchor_weight"].fillna(0.01).clip(lower=0.01)
    return pool


def _pick_anchor(pool: pd.DataFrame, rng: random.Random) -> pd.Series:
    weights = pool["_anchor_weight"].tolist()
    indices = list(pool.index)
    picked_index = rng.choices(indices, weights=weights, k=1)[0]
    return pool.loc[picked_index]


def _recompute_dependent_fields(row: dict[str, Any], inventory_medians: dict[tuple[str, str], float]) -> None:
    price_gap_pct = _safe_float(row.get("price_gap_pct"), 0.0)
    days_of_supply = _safe_float(row.get("days_of_supply"), 0.0)
    total_qty = max(0, _safe_int(row.get("total_qty"), 0))
    retail_price = max(_safe_float(row.get("retail_price_usd"), 0.0), 0.01)
    cost_price = clamp(_safe_float(row.get("cost_price_usd"), 0.0), 0.0, retail_price * 0.98)

    row["total_qty"] = total_qty
    row["days_of_supply"] = round(days_of_supply, 1)
    row["stock_coverage_ratio"] = round(days_of_supply / 30.0, 2)
    row["stockout_risk"] = 1 if days_of_supply < 14 else 0
    row["retail_price_usd"] = round(retail_price, 2)
    row["cost_price_usd"] = round(cost_price, 2)
    row["current_margin_pct"] = round((1.0 - (cost_price / retail_price)) * 100.0, 2)
    row["market_position"] = _market_position_from_gap(price_gap_pct)
    row["price_gap_pct"] = round(price_gap_pct, 4)
    row["discount_depth_last_30d"] = round(clamp(_safe_float(row.get("discount_depth_last_30d"), 0.0), 0.0, 1.0), 4)
    row["days_since_last_discount"] = max(0, _safe_int(row.get("days_since_last_discount"), 999))
    row["days_at_current_price"] = max(0, _safe_int(row.get("days_at_current_price"), 30))
    row["season_sell_through_pct"] = round(clamp(_safe_float(row.get("season_sell_through_pct"), 0.0), 0.0, 1.0), 4)
    row["seasonality_score"] = round(clamp(_safe_float(row.get("seasonality_score"), 1.0), 0.5, 3.0), 3)
    row["category_seasonal_boost"] = round(clamp(_safe_float(row.get("category_seasonal_boost"), 0.0), 0.0, 1.0), 3)
    row["event_proximity_score"] = round(clamp(_safe_float(row.get("event_proximity_score"), 0.0), 0.0, 1.0), 3)
    row["next_month_seasonality"] = round(clamp(_safe_float(row.get("next_month_seasonality"), 1.0), 0.5, 3.0), 3)
    row["cash_runway_months"] = round(clamp(_safe_float(row.get("cash_runway_months"), 3.0), 0.0, 120.0), 2)
    row["cash_tight"] = 1 if _safe_int(row.get("cash_tight"), 0) else 0
    row["inventory_intensity"] = round(clamp(_safe_float(row.get("inventory_intensity"), 0.7), 0.0, 1.0), 4)
    row["num_competitors"] = max(0, _safe_int(row.get("num_competitors"), 0))
    row["competitors_on_sale"] = max(0, min(_safe_int(row.get("competitors_on_sale"), 0), row["num_competitors"]))
    row["competitors_out_of_stock"] = max(0, min(_safe_int(row.get("competitors_out_of_stock"), 0), row["num_competitors"]))
    row["days_since_launch"] = max(0, _safe_int(row.get("days_since_launch"), 180))

    median_key = (str(row.get("week_of", "")), str(row.get("category", "other")))
    median_qty = inventory_medians.get(median_key, 1.0)
    row["inventory_vs_median"] = round(total_qty / median_qty, 4) if median_qty > 0 else 1.0


def _is_realistic(row: dict[str, Any]) -> bool:
    return all(
        [
            _safe_float(row.get("retail_price_usd"), 0.0) > _safe_float(row.get("cost_price_usd"), 0.0),
            0.0 <= _safe_float(row.get("season_sell_through_pct"), 0.0) <= 1.0,
            0.0 <= _safe_float(row.get("discount_depth_last_30d"), 0.0) <= 1.0,
            0.0 <= _safe_float(row.get("event_proximity_score"), 0.0) <= 1.0,
            0.0 <= _safe_float(row.get("inventory_intensity"), 0.0) <= 1.0,
            _safe_float(row.get("days_of_supply"), 0.0) <= 730.0,
            _safe_int(row.get("competitors_on_sale"), 0) <= _safe_int(row.get("num_competitors"), 0),
            _safe_int(row.get("competitors_out_of_stock"), 0) <= _safe_int(row.get("num_competitors"), 0),
            _safe_int(row.get("total_qty"), 0) >= 0,
        ]
    )


def _mutate_clear(
    anchor: pd.Series,
    candidate: dict[str, Any],
    rng: random.Random,
    strong: bool,
    force_profile: str | None = None,
) -> str:
    profile = force_profile or rng.choices(
        ["event_deadstock_clear", "lifecycle_clear", "premium_deadstock_clear"],
        weights=[0.45, 0.25 if strong else 0.35, 0.30 if strong else 0.20],
        k=1,
    )[0]

    if profile == "event_deadstock_clear":
        candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], 123, 152 if strong else 148, rng, anchor_weight=0.12, decimals=1)
        candidate["total_qty"] = _anchored_int(anchor["total_qty"], max(_safe_int(anchor["total_qty"], 0), 42), max(_safe_int(anchor["total_qty"], 0) + 70, 125), rng, anchor_weight=0.28)
        candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.10, 0.17, rng, anchor_weight=0.10)
        candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 235, 420, rng, anchor_weight=0.20)
        candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], 1.03, 1.18, rng, anchor_weight=0.12, decimals=3)
        candidate["category_seasonal_boost"] = _anchored_float(anchor["category_seasonal_boost"], 0.00, 0.16, rng, anchor_weight=0.10, decimals=3)
        candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], 0.68, 0.90, rng, anchor_weight=0.10, decimals=3)
        candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], 0.22, 0.34, rng, anchor_weight=0.10)
        candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 55, 220, rng, anchor_weight=0.15)
        candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.08, rng, anchor_weight=0.08)
        candidate["days_at_current_price"] = _anchored_int(anchor["days_at_current_price"], 65, 190, rng, anchor_weight=0.18)
        num_competitors = max(1, _anchored_int(anchor["num_competitors"], 1, 6, rng, anchor_weight=0.20))
        candidate["num_competitors"] = num_competitors
        candidate["competitors_on_sale"] = min(num_competitors, max(1, int(round(num_competitors * rng.uniform(0.65, 1.00)))))
        candidate["competitors_out_of_stock"] = min(num_competitors, int(round(num_competitors * rng.uniform(0.00, 0.12))))
    elif profile == "premium_deadstock_clear":
        candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], 125, 175 if strong else 165, rng, anchor_weight=0.20, decimals=1)
        candidate["total_qty"] = _anchored_int(anchor["total_qty"], max(_safe_int(anchor["total_qty"], 0), 42), max(_safe_int(anchor["total_qty"], 0) + 70, 140), rng, anchor_weight=0.30)
        candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.00, 0.16, rng, anchor_weight=0.15)
        candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 220, 420, rng, anchor_weight=0.25)
        candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], 0.95, 1.20, rng, anchor_weight=0.20, decimals=3)
        candidate["category_seasonal_boost"] = _anchored_float(anchor["category_seasonal_boost"], 0.00, 0.20, rng, anchor_weight=0.10, decimals=3)
        candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], 0.40, 0.90, rng, anchor_weight=0.15, decimals=3)
        candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], 0.18, 0.35, rng, anchor_weight=0.15)
        candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 45, 220, rng, anchor_weight=0.15)
        candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.10, rng, anchor_weight=0.10)
        candidate["days_at_current_price"] = _anchored_int(anchor["days_at_current_price"], 55, 180, rng, anchor_weight=0.20)
        num_competitors = max(1, _anchored_int(anchor["num_competitors"], 1, 6, rng, anchor_weight=0.25))
        candidate["num_competitors"] = num_competitors
        candidate["competitors_on_sale"] = min(num_competitors, max(1, int(round(num_competitors * rng.uniform(0.60, 1.00)))))
        candidate["competitors_out_of_stock"] = min(num_competitors, int(round(num_competitors * rng.uniform(0.00, 0.15))))
    else:
        dos_low, dos_high = (170, 260) if strong else (150, 230)
        sell_low, sell_high = (0.0, 0.12) if strong else (0.0, 0.20)
        candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], dos_low, dos_high, rng, anchor_weight=0.20, decimals=1)
        candidate["total_qty"] = _anchored_int(anchor["total_qty"], max(_safe_int(anchor["total_qty"], 0), 36), max(_safe_int(anchor["total_qty"], 0) + 90, 180), rng, anchor_weight=0.25)
        candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], sell_low, sell_high, rng, anchor_weight=0.15)
        candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 180, 420 if strong else 360, rng, anchor_weight=0.20)
        candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], 0.70, 0.95, rng, anchor_weight=0.20, decimals=3)
        candidate["category_seasonal_boost"] = _anchored_float(anchor["category_seasonal_boost"], 0.00, 0.10, rng, anchor_weight=0.10, decimals=3)
        candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], 0.00, 0.30, rng, anchor_weight=0.10, decimals=3)
        candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], 0.04, 0.24 if strong else 0.20, rng, anchor_weight=0.30)
        candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 35, 200, rng, anchor_weight=0.15)
        candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.12, rng, anchor_weight=0.10)
        candidate["days_at_current_price"] = _anchored_int(anchor["days_at_current_price"], 45, 160, rng, anchor_weight=0.20)

    if rng.random() < 0.35:
        candidate["cash_tight"] = 1
        candidate["cash_runway_months"] = _anchored_float(anchor["cash_runway_months"], 1.2, 2.6, rng, anchor_weight=0.10, decimals=2)
        candidate["inventory_intensity"] = _anchored_float(anchor["inventory_intensity"], 0.60, 0.88, rng, anchor_weight=0.15)

    return profile


def _mutate_markdown(anchor: pd.Series, candidate: dict[str, Any], rng: random.Random, strong: bool) -> str:
    gap_low, gap_high = (0.18, 0.32) if strong else (0.12, 0.28)
    dos_low, dos_high = (95, 165) if strong else (80, 150)

    candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], gap_low, gap_high, rng, anchor_weight=0.20)
    candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], dos_low, dos_high, rng, anchor_weight=0.25, decimals=1)
    candidate["total_qty"] = _anchored_int(anchor["total_qty"], max(_safe_int(anchor["total_qty"], 0), 24), max(_safe_int(anchor["total_qty"], 0) + 70, 130), rng, anchor_weight=0.30)
    candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 30, 140, rng, anchor_weight=0.20)
    candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.20, rng, anchor_weight=0.15)
    candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.18, 0.55, rng, anchor_weight=0.25)
    candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 90, 300, rng, anchor_weight=0.30)
    candidate["days_at_current_price"] = _anchored_int(anchor["days_at_current_price"], 35, 120, rng, anchor_weight=0.25)

    num_competitors = max(2, _anchored_int(anchor["num_competitors"], 2, 6 if strong else 5, rng, anchor_weight=0.25))
    candidate["num_competitors"] = num_competitors
    on_sale_ratio = rng.uniform(0.45, 0.90) if strong else rng.uniform(0.35, 0.80)
    candidate["competitors_on_sale"] = min(num_competitors, max(1, int(round(num_competitors * on_sale_ratio))))
    candidate["competitors_out_of_stock"] = min(num_competitors, int(round(num_competitors * rng.uniform(0.00, 0.20))))
    return "markdown_strong" if strong else "markdown_guided"


def _mutate_hold(
    anchor: pd.Series,
    candidate: dict[str, Any],
    rng: random.Random,
    strong: bool,
    force_profile: str | None = None,
) -> str:
    profile = force_profile or rng.choices(
        [
            "margin_floor_event_hold",
            "margin_guardrail_hold",
            "recent_discount_hold",
            "scarcity_hold",
            "stable_high_dos_hold",
        ],
        weights=[0.40, 0.22, 0.18, 0.10, 0.10],
        k=1,
    )[0]

    if profile == "margin_floor_event_hold":
        candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], 48, 104, rng, anchor_weight=0.20, decimals=1)
        candidate["total_qty"] = _anchored_int(anchor["total_qty"], 26, 76, rng, anchor_weight=0.28)
        candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], 0.02, 0.10, rng, anchor_weight=0.18)
        candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 90, 240, rng, anchor_weight=0.15)
        if rng.random() < 0.30:
            candidate["days_since_last_discount"] = 999
        candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.05, rng, anchor_weight=0.12)
        candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 75, 180, rng, anchor_weight=0.25)
        candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.24, 0.46, rng, anchor_weight=0.20)
        candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], 1.03, 1.16, rng, anchor_weight=0.12, decimals=3)
        candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], 0.68, 0.90, rng, anchor_weight=0.12, decimals=3)
        candidate["cost_price_usd"] = round(candidate["retail_price_usd"] * (1.0 - rng.uniform(0.28, 0.355)), 2)
        num_competitors = max(2, _anchored_int(anchor["num_competitors"], 2, 4, rng, anchor_weight=0.25))
        candidate["num_competitors"] = num_competitors
        candidate["competitors_on_sale"] = min(num_competitors, max(1, int(round(num_competitors * rng.uniform(0.30, 0.55)))))
        candidate["competitors_out_of_stock"] = min(num_competitors, int(round(num_competitors * rng.uniform(0.00, 0.15))))
    elif profile == "margin_guardrail_hold":
        candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], 35, 95, rng, anchor_weight=0.25, decimals=1)
        candidate["total_qty"] = _anchored_int(anchor["total_qty"], 24, 90, rng, anchor_weight=0.35)
        candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], 0.00, 0.12, rng, anchor_weight=0.20)
        candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 28, 120, rng, anchor_weight=0.20)
        candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.12, rng, anchor_weight=0.20)
        candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 45, 180, rng, anchor_weight=0.30)
        candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.25, 0.55, rng, anchor_weight=0.25)
        candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], 1.00, 1.18, rng, anchor_weight=0.20, decimals=3)
        candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], 0.40, 0.90, rng, anchor_weight=0.20, decimals=3)
        candidate["cost_price_usd"] = round(candidate["retail_price_usd"] * (1.0 - rng.uniform(0.24, 0.35)), 2)
        num_competitors = max(2, _anchored_int(anchor["num_competitors"], 2, 5, rng, anchor_weight=0.30))
        candidate["num_competitors"] = num_competitors
        candidate["competitors_on_sale"] = min(num_competitors, max(1, int(round(num_competitors * rng.uniform(0.25, 0.60)))))
        candidate["competitors_out_of_stock"] = min(num_competitors, int(round(num_competitors * rng.uniform(0.00, 0.15))))
    elif profile == "recent_discount_hold":
        candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], 35, 90, rng, anchor_weight=0.25, decimals=1)
        candidate["total_qty"] = _anchored_int(anchor["total_qty"], 22, 85, rng, anchor_weight=0.35)
        candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], 0.10, 0.28, rng, anchor_weight=0.20)
        candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 3, 18, rng, anchor_weight=0.10)
        candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.08, 0.25, rng, anchor_weight=0.15)
        candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 60, 200, rng, anchor_weight=0.30)
        candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.25, 0.55, rng, anchor_weight=0.25)
        candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], 1.00, 1.20, rng, anchor_weight=0.20, decimals=3)
        candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], 0.35, 0.90, rng, anchor_weight=0.20, decimals=3)
        num_competitors = max(2, _anchored_int(anchor["num_competitors"], 2, 6, rng, anchor_weight=0.25))
        candidate["num_competitors"] = num_competitors
        candidate["competitors_on_sale"] = min(num_competitors, max(1, int(round(num_competitors * rng.uniform(0.40, 0.85)))))
        candidate["competitors_out_of_stock"] = min(num_competitors, int(round(num_competitors * rng.uniform(0.00, 0.15))))
    elif profile == "scarcity_hold":
        candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], 4, 18, rng, anchor_weight=0.15, decimals=1)
        candidate["total_qty"] = _anchored_int(anchor["total_qty"], 2, 14, rng, anchor_weight=0.15)
        candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], -0.08, 0.08, rng, anchor_weight=0.20)
        candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 21, 180, rng, anchor_weight=0.25)
        candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.08, rng, anchor_weight=0.20)
        candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 20, 180, rng, anchor_weight=0.25)
        candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.55, 0.92, rng, anchor_weight=0.20)
        candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], 0.90, 1.18, rng, anchor_weight=0.20, decimals=3)
        candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], 0.10, 0.80, rng, anchor_weight=0.20, decimals=3)
        num_competitors = max(1, _anchored_int(anchor["num_competitors"], 1, 4, rng, anchor_weight=0.30))
        candidate["num_competitors"] = num_competitors
        candidate["competitors_on_sale"] = min(num_competitors, int(round(num_competitors * rng.uniform(0.00, 0.25))))
        candidate["competitors_out_of_stock"] = min(num_competitors, max(0, int(round(num_competitors * rng.uniform(0.20, 0.70)))))
    else:
        candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], 80, 140 if strong else 125, rng, anchor_weight=0.25, decimals=1)
        candidate["total_qty"] = _anchored_int(anchor["total_qty"], 20, 65, rng, anchor_weight=0.35)
        candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], -0.02, 0.05, rng, anchor_weight=0.25)
        candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 45, 180, rng, anchor_weight=0.25)
        candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.08, rng, anchor_weight=0.20)
        candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 120, 300, rng, anchor_weight=0.30)
        candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.22, 0.48, rng, anchor_weight=0.25)
        candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], 0.75, 1.02, rng, anchor_weight=0.20, decimals=3)
        candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], 0.00, 0.30, rng, anchor_weight=0.20, decimals=3)
        num_competitors = max(0, _anchored_int(anchor["num_competitors"], 0, 1, rng, anchor_weight=0.20))
        candidate["num_competitors"] = num_competitors
        candidate["competitors_on_sale"] = 0
        candidate["competitors_out_of_stock"] = 0
    return profile


def _mutate_promote(anchor: pd.Series, candidate: dict[str, Any], rng: random.Random, strong: bool) -> str:
    season_low, season_high = (1.18, 1.55) if strong else (1.10, 1.45)
    event_low, event_high = (0.65, 0.98) if strong else (0.55, 0.92)

    candidate["days_of_supply"] = _anchored_float(anchor["days_of_supply"], 30, 90, rng, anchor_weight=0.25, decimals=1)
    candidate["total_qty"] = _anchored_int(anchor["total_qty"], max(_safe_int(anchor["total_qty"], 0), 24), max(_safe_int(anchor["total_qty"], 0) + 45, 110), rng, anchor_weight=0.35)
    candidate["seasonality_score"] = _anchored_float(anchor["seasonality_score"], season_low, season_high, rng, anchor_weight=0.20, decimals=3)
    candidate["event_proximity_score"] = _anchored_float(anchor["event_proximity_score"], event_low, event_high, rng, anchor_weight=0.20, decimals=3)
    candidate["price_gap_pct"] = _anchored_float(anchor["price_gap_pct"], -0.14, 0.00, rng, anchor_weight=0.15)
    candidate["days_since_last_discount"] = _anchored_int(anchor["days_since_last_discount"], 35, 120, rng, anchor_weight=0.15)
    candidate["discount_depth_last_30d"] = _anchored_float(anchor["discount_depth_last_30d"], 0.00, 0.15, rng, anchor_weight=0.20)
    candidate["season_sell_through_pct"] = _anchored_float(anchor["season_sell_through_pct"], 0.30, 0.70, rng, anchor_weight=0.25)
    candidate["days_since_launch"] = _anchored_int(anchor["days_since_launch"], 30, 220, rng, anchor_weight=0.30)
    candidate["days_at_current_price"] = _anchored_int(anchor["days_at_current_price"], 21, 90, rng, anchor_weight=0.25)
    candidate["next_month_seasonality"] = _anchored_float(anchor["next_month_seasonality"], 1.05, 1.40, rng, anchor_weight=0.30, decimals=3)

    num_competitors = max(1, _anchored_int(anchor["num_competitors"], 1, 5, rng, anchor_weight=0.35))
    candidate["num_competitors"] = num_competitors
    candidate["competitors_on_sale"] = min(num_competitors, int(round(num_competitors * rng.uniform(0.00, 0.10))))
    candidate["competitors_out_of_stock"] = min(num_competitors, max(0, int(round(num_competitors * rng.uniform(0.15, 0.45)))))
    return "promote_strong" if strong else "promote_guided"


def _mutate_candidate(
    anchor: pd.Series,
    candidate: dict[str, Any],
    target_label: str,
    rng: random.Random,
    strong: bool,
    force_profile: str | None = None,
) -> str:
    if target_label == "CLEAR":
        return _mutate_clear(anchor, candidate, rng, strong=strong, force_profile=force_profile)
    elif target_label == "HOLD":
        return _mutate_hold(anchor, candidate, rng, strong=strong, force_profile=force_profile)
    elif target_label == "PROMOTE":
        return _mutate_promote(anchor, candidate, rng, strong=strong)
    elif target_label == "MARKDOWN":
        return _mutate_markdown(anchor, candidate, rng, strong=strong)
    else:
        raise ValueError(f"Unsupported target label: {target_label}")


def _planned_profile(target_label: str, generated_count: int, target_count: int) -> str | None:
    if target_count <= 0:
        return None

    progress = generated_count / max(target_count, 1)
    if target_label == "CLEAR":
        if progress < 0.55:
            return "event_deadstock_clear"
        if progress < 0.80:
            return "premium_deadstock_clear"
        return "lifecycle_clear"
    if target_label == "HOLD":
        if progress < 0.55:
            return "margin_floor_event_hold"
        if progress < 0.78:
            return "margin_guardrail_hold"
        if progress < 0.90:
            return "recent_discount_hold"
        return "stable_high_dos_hold"
    return None


def _accept_candidate(candidate: dict[str, Any], target_label: str) -> tuple[bool, dict[str, Any]]:
    if not _is_realistic(candidate):
        return False, {}

    candidate_series = pd.Series(candidate)
    candidate["rules_label"] = _assign_label(candidate_series)
    ai_label, confidence, scores, rationale = _score_row(candidate_series)
    confidence_floor = {
        "HOLD": 0.60,
        "PROMOTE": 0.55,
        "MARKDOWN": 0.63,
        "CLEAR": 0.63,
    }.get(target_label, 0.63)
    if (
        target_label == "CLEAR"
        and _safe_float(candidate.get("event_proximity_score"), 0.0) >= 0.60
        and _safe_float(candidate.get("price_gap_pct"), 0.0) >= 0.18
        and _safe_float(candidate.get("days_of_supply"), 0.0) >= 120
        and _safe_float(candidate.get("season_sell_through_pct"), 1.0) <= 0.18
        and _safe_float(candidate.get("days_since_launch"), 0.0) >= 220
        and scores["CLEAR"] >= 0.55
    ):
        confidence_floor = 0.55
    if ai_label != target_label or confidence < confidence_floor:
        return False, {}

    score_payload = {
        "ai_label": ai_label,
        "ai_label_confidence": confidence,
        "ai_label_rationale": rationale,
        "ai_score_hold": scores["HOLD"],
        "ai_score_markdown": scores["MARKDOWN"],
        "ai_score_promote": scores["PROMOTE"],
        "ai_score_clear": scores["CLEAR"],
    }
    return True, score_payload


def _generate_target_rows(
    base_df: pd.DataFrame,
    inventory_medians: dict[tuple[str, str], float],
    *,
    target_label: str,
    target_count: int,
    seed: int,
    max_copies_per_anchor: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    pool = _select_anchor_pool(base_df, target_label)
    per_anchor_count: Counter[str] = Counter()
    generated_rows: list[dict[str, Any]] = []
    attempts = 0
    max_attempts = max(target_count * 90, 600)

    while len(generated_rows) < target_count and attempts < max_attempts:
        attempts += 1
        strong = len(generated_rows) >= max(1, int(target_count * 0.45))
        anchor = _pick_anchor(pool, rng)
        anchor_state_id = str(anchor["state_id"])
        if per_anchor_count[anchor_state_id] >= max_copies_per_anchor:
            continue

        candidate = anchor.to_dict()
        suffix = f"AUG-{target_label[:3]}-{len(generated_rows) + 1:04d}"
        candidate["state_id"] = f"{anchor_state_id}__{suffix}"
        candidate["data_source"] = "synthetic_augmented"
        candidate["synthetic_is_augmented"] = 1
        candidate["synthetic_target_label"] = target_label
        candidate["synthetic_anchor_state_id"] = anchor_state_id
        force_profile = _planned_profile(target_label, len(generated_rows), target_count)
        if attempts > int(max_attempts * 0.85):
            force_profile = None
        mutation_profile = _mutate_candidate(anchor, candidate, target_label, rng, strong=strong, force_profile=force_profile)
        candidate["synthetic_mutation_profile"] = mutation_profile
        _recompute_dependent_fields(candidate, inventory_medians)
        accepted, score_payload = _accept_candidate(candidate, target_label)
        if not accepted:
            continue

        candidate.update(score_payload)
        generated_rows.append(candidate)
        per_anchor_count[anchor_state_id] += 1

    summary = {
        "target_label": target_label,
        "requested_rows": target_count,
        "generated_rows": len(generated_rows),
        "attempts": attempts,
        "unique_anchor_rows_used": len(per_anchor_count),
        "top_anchor_categories": dict(Counter(str(row["category"]) for row in generated_rows).most_common(5)),
    }
    return generated_rows, summary


def build_augmented_training_dataset(
    *,
    training_dataset_path: Path = TRAINING_DATASET_PATH,
    ai_labels_path: Path = AI_LABELS_PATH,
    augmented_training_output: Path = AUGMENTED_TRAINING_DATASET_PATH,
    augmented_ai_output: Path = AUGMENTED_AI_LABELS_PATH,
    summary_report_output: Path = SUMMARY_REPORT_PATH,
    target_counts: dict[str, int] | None = None,
    seed: int = 42,
    max_copies_per_anchor: int = 3,
    refresh_ai_labels: bool = False,
) -> dict[str, Any]:
    target_counts = target_counts or DEFAULT_TARGET_COUNTS.copy()

    if not training_dataset_path.exists():
        raise FileNotFoundError(f"Training dataset not found: {training_dataset_path}")

    training_df = pd.read_csv(training_dataset_path)
    ai_df = _load_or_build_ai_labels(training_dataset_path, ai_labels_path, refresh=refresh_ai_labels)
    base_df = _prepare_base_dataframe(training_df, ai_df)
    inventory_medians = _build_inventory_medians(training_df)

    generated_rows: list[dict[str, Any]] = []
    generation_summaries: list[dict[str, Any]] = []
    for offset, label in enumerate(TARGET_LABEL_ORDER):
        requested = int(target_counts.get(label, 0))
        if requested <= 0:
            continue
        rows, summary = _generate_target_rows(
            base_df,
            inventory_medians,
            target_label=label,
            target_count=requested,
            seed=seed + offset,
            max_copies_per_anchor=max_copies_per_anchor,
        )
        generated_rows.extend(rows)
        generation_summaries.append(summary)

    synthetic_df = pd.DataFrame(generated_rows)
    if synthetic_df.empty:
        raise RuntimeError("No synthetic rows were generated. Try lowering the target counts or refresh AI labels.")

    real_df = training_df.copy()
    if "data_source" not in real_df.columns:
        real_df["data_source"] = "real"
    if "synthetic_is_augmented" not in real_df.columns:
        real_df["synthetic_is_augmented"] = 0
    for column in ["synthetic_target_label", "synthetic_anchor_state_id", "synthetic_mutation_profile"]:
        if column not in real_df.columns:
            real_df[column] = ""

    combined_df = pd.concat([real_df, synthetic_df[real_df.columns]], ignore_index=True, sort=False)

    augmented_training_output.parent.mkdir(parents=True, exist_ok=True)
    combined_df.to_csv(augmented_training_output, index=False)

    augmented_ai_df = build_ai_labeled_dataset(
        training_dataset_path=augmented_training_output,
        output_path=augmented_ai_output,
    )

    report = {
        "input_training_dataset": str(training_dataset_path),
        "output_training_dataset": str(augmented_training_output),
        "output_ai_labeled_dataset": str(augmented_ai_output),
        "seed": seed,
        "max_copies_per_anchor": max_copies_per_anchor,
        "original_row_count": int(len(training_df)),
        "synthetic_row_count": int(len(synthetic_df)),
        "augmented_row_count": int(len(combined_df)),
        "original_rules_distribution": training_df["rules_label"].value_counts().to_dict(),
        "augmented_rules_distribution": combined_df["rules_label"].value_counts().to_dict(),
        "original_ai_distribution": ai_df["ai_label"].value_counts().to_dict(),
        "augmented_ai_distribution": augmented_ai_df["ai_label"].value_counts().to_dict(),
        "synthetic_target_distribution": synthetic_df["synthetic_target_label"].value_counts().to_dict(),
        "synthetic_category_distribution": synthetic_df["category"].value_counts().head(10).to_dict(),
        "generation_summaries": generation_summaries,
    }

    summary_report_output.parent.mkdir(parents=True, exist_ok=True)
    summary_report_output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("\n" + "=" * 76)
    print("AUGMENTED TRAINING DATASET SUMMARY")
    print("=" * 76)
    print(f"Original rows:              {len(training_df)}")
    print(f"Synthetic rows added:       {len(synthetic_df)}")
    print(f"Augmented rows:             {len(combined_df)}")
    print(f"Augmented training output:  {augmented_training_output}")
    print(f"Augmented AI output:        {augmented_ai_output}")
    print(f"Summary report:             {summary_report_output}")
    print(f"Original AI labels:         {ai_df['ai_label'].value_counts().to_dict()}")
    print(f"Augmented AI labels:        {augmented_ai_df['ai_label'].value_counts().to_dict()}")
    print(f"Synthetic targets:          {synthetic_df['synthetic_target_label'].value_counts().to_dict()}")
    print("=" * 76)

    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a controlled augmented training dataset for underrepresented action classes.")
    parser.add_argument("--training-dataset", type=Path, default=TRAINING_DATASET_PATH)
    parser.add_argument("--ai-labeled-dataset", type=Path, default=AI_LABELS_PATH)
    parser.add_argument("--output-training", type=Path, default=AUGMENTED_TRAINING_DATASET_PATH)
    parser.add_argument("--output-ai", type=Path, default=AUGMENTED_AI_LABELS_PATH)
    parser.add_argument("--summary-report", type=Path, default=SUMMARY_REPORT_PATH)
    parser.add_argument("--clear-count", type=int, default=DEFAULT_TARGET_COUNTS["CLEAR"])
    parser.add_argument("--hold-count", type=int, default=DEFAULT_TARGET_COUNTS["HOLD"])
    parser.add_argument("--promote-count", type=int, default=DEFAULT_TARGET_COUNTS["PROMOTE"])
    parser.add_argument("--markdown-count", type=int, default=DEFAULT_TARGET_COUNTS["MARKDOWN"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-copies-per-anchor", type=int, default=3)
    parser.add_argument("--refresh-ai-labels", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    build_augmented_training_dataset(
        training_dataset_path=args.training_dataset,
        ai_labels_path=args.ai_labeled_dataset,
        augmented_training_output=args.output_training,
        augmented_ai_output=args.output_ai,
        summary_report_output=args.summary_report,
        target_counts={
            "CLEAR": args.clear_count,
            "HOLD": args.hold_count,
            "PROMOTE": args.promote_count,
            "MARKDOWN": args.markdown_count,
        },
        seed=args.seed,
        max_copies_per_anchor=args.max_copies_per_anchor,
        refresh_ai_labels=args.refresh_ai_labels,
    )


if __name__ == "__main__":
    main()
