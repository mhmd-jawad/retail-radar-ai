"""
Build an evaluation-only CLEAR stress-test dataset.

The rows are anchored on the real RDS holdout set, then manually shaped into
business-valid edge cases. This file is not used for training; it is used to
verify that the candidate model handles CLEAR and near-CLEAR boundaries.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from services.decision_intelligence.features.augment_training_dataset import (
    _build_inventory_medians,
    _recompute_dependent_fields,
    _safe_float,
)
from services.decision_intelligence.training.baseline import _assign_label


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data" / "features" / "rds_leak_safe_test_real.csv"
DEFAULT_OUTPUT = ROOT / "data" / "features" / "rds_clear_stress_test.csv"
DEFAULT_REPORT = ROOT / "data" / "reports" / "rds_clear_stress_test_summary.json"

PROFILE_PLAN = {
    "clear_event_deadstock": ("CLEAR", 45),
    "clear_lifecycle_deadstock": ("CLEAR", 45),
    "clear_premium_trapped_cash": ("CLEAR", 30),
    "hold_old_low_stock": ("HOLD", 45),
    "hold_old_weak_match": ("HOLD", 45),
    "hold_thin_margin": ("HOLD", 30),
    "hold_young_high_dos": ("HOLD", 20),
    "markdown_reliable_overpriced": ("MARKDOWN", 70),
    "promote_demand_capture": ("PROMOTE", 50),
}

RATIONALES = {
    "CLEAR": "Evaluation stress case: old inventory, high days of supply, weak sell-through, and meaningful stock support clearance.",
    "HOLD": "Evaluation boundary case: at least one guardrail blocks aggressive action, so holding price is safer.",
    "MARKDOWN": "Evaluation stress case: reliable competitor pressure, positive price gap, stock, and margin support markdown.",
    "PROMOTE": "Evaluation stress case: competitive price, healthy stock and margin, and competitor scarcity support promotion.",
}


def _set_price_from_margin(row: dict[str, Any], rng: random.Random, margin_low: float, margin_high: float) -> None:
    retail = max(_safe_float(row.get("retail_price_usd"), 90.0), 10.0)
    if retail < 20.0:
        retail = rng.uniform(45.0, 140.0)
    margin = rng.uniform(margin_low, margin_high)
    row["retail_price_usd"] = round(retail, 2)
    row["cost_price_usd"] = round(retail * (1.0 - margin / 100.0), 2)


def _set_competitor_prices(row: dict[str, Any]) -> None:
    retail = max(_safe_float(row.get("retail_price_usd"), 1.0), 1.0)
    gap = _safe_float(row.get("price_gap_pct"), 0.0)
    competitor_min = max(retail / max(0.2, 1.0 + gap), 1.0)
    row["competitor_min_price_usd"] = round(competitor_min, 2)
    row["competitor_avg_price_usd"] = round(competitor_min * 1.04, 2)
    row["competitor_max_price_usd"] = round(competitor_min * 1.10, 2)


def _base_row(anchor: pd.Series, profile: str, label: str, idx: int) -> dict[str, Any]:
    row = anchor.to_dict()
    row["state_id"] = f"{anchor.get('state_id', anchor.get('sku_id', 'sku'))}__STRESS-{profile}-{idx:04d}"
    row["row_source"] = "clear_stress_test"
    row["is_augmented"] = 0
    row["augmentation_family"] = profile
    row["anchor_state_id"] = str(anchor.get("state_id", ""))
    row["sample_weight_hint"] = 1.0
    row["ai_label"] = label
    row["expected_label"] = label
    row["ai_label_confidence"] = 0.95 if label == "CLEAR" else 0.90
    row["label_confidence"] = row["ai_label_confidence"]
    row["ai_label_rationale"] = RATIONALES[label]
    row["audit_flags"] = profile
    row["label_prompt_version"] = "manual_clear_stress_v1"
    row["labeler_model"] = "business_curated_stress_set"
    row["labeled_at"] = datetime.now(timezone.utc).isoformat()
    row["ai_label_disagrees_with_rules"] = False
    row["inventory_history_quality"] = anchor.get("inventory_history_quality", "movement_reconstructed")
    row["has_competitor_data"] = int(anchor.get("has_competitor_data", 1) or 1)
    return row


def _shape_row(row: dict[str, Any], profile: str, rng: random.Random) -> None:
    if profile == "clear_event_deadstock":
        _set_price_from_margin(row, rng, 40.0, 58.0)
        row.update(
            days_of_supply=rng.uniform(130.0, 190.0),
            total_qty=rng.randint(55, 150),
            season_sell_through_pct=rng.uniform(0.02, 0.16),
            days_since_launch=rng.randint(240, 430),
            price_gap_pct=rng.uniform(0.18, 0.34),
            num_competitors=rng.randint(2, 6),
            match_type=rng.choice(["exact_style", "same_model_family"]),
            match_score=rng.uniform(0.78, 0.96),
            seasonality_score=rng.uniform(0.75, 1.05),
            event_proximity_score=rng.uniform(0.62, 0.90),
            days_since_last_discount=rng.randint(60, 190),
            discount_depth_last_30d=rng.uniform(0.0, 0.08),
        )
        row["competitors_on_sale"] = rng.randint(max(1, row["num_competitors"] // 2), row["num_competitors"])
        row["competitors_out_of_stock"] = rng.randint(0, 1)
    elif profile == "clear_lifecycle_deadstock":
        _set_price_from_margin(row, rng, 38.0, 55.0)
        row.update(
            days_of_supply=rng.uniform(165.0, 280.0),
            total_qty=rng.randint(50, 180),
            season_sell_through_pct=rng.uniform(0.00, 0.13),
            days_since_launch=rng.randint(280, 520),
            price_gap_pct=rng.uniform(0.08, 0.24),
            num_competitors=rng.randint(1, 5),
            competitors_out_of_stock=0,
            match_type=rng.choice(["exact_style", "same_model_family"]),
            match_score=rng.uniform(0.72, 0.95),
            seasonality_score=rng.uniform(0.55, 0.90),
            event_proximity_score=rng.uniform(0.00, 0.35),
            days_since_last_discount=rng.randint(80, 240),
            discount_depth_last_30d=rng.uniform(0.0, 0.06),
        )
        row["competitors_on_sale"] = rng.randint(0, row["num_competitors"])
    elif profile == "clear_premium_trapped_cash":
        _set_price_from_margin(row, rng, 42.0, 62.0)
        row.update(
            days_of_supply=rng.uniform(125.0, 210.0),
            total_qty=rng.randint(45, 145),
            season_sell_through_pct=rng.uniform(0.04, 0.18),
            days_since_launch=rng.randint(220, 460),
            price_gap_pct=rng.uniform(0.22, 0.40),
            num_competitors=rng.randint(2, 6),
            match_type="exact_style",
            match_score=rng.uniform(0.86, 0.99),
            seasonality_score=rng.uniform(0.85, 1.15),
            event_proximity_score=rng.uniform(0.40, 0.80),
            days_since_last_discount=rng.randint(45, 170),
            discount_depth_last_30d=rng.uniform(0.0, 0.10),
        )
        row["competitors_on_sale"] = rng.randint(max(1, row["num_competitors"] // 2), row["num_competitors"])
        row["competitors_out_of_stock"] = rng.randint(0, 1)
    elif profile == "hold_old_low_stock":
        _set_price_from_margin(row, rng, 38.0, 55.0)
        row.update(
            days_of_supply=rng.uniform(5.0, 18.0),
            total_qty=rng.randint(2, 12),
            season_sell_through_pct=rng.uniform(0.55, 0.92),
            days_since_launch=rng.randint(220, 500),
            price_gap_pct=rng.uniform(0.08, 0.28),
            num_competitors=rng.randint(1, 5),
            competitors_on_sale=rng.randint(0, 2),
            competitors_out_of_stock=rng.randint(0, 2),
            match_type=rng.choice(["exact_style", "same_model_family"]),
            match_score=rng.uniform(0.72, 0.95),
        )
    elif profile == "hold_old_weak_match":
        _set_price_from_margin(row, rng, 40.0, 58.0)
        row.update(
            days_of_supply=rng.uniform(95.0, 170.0),
            total_qty=rng.randint(35, 120),
            season_sell_through_pct=rng.uniform(0.18, 0.40),
            days_since_launch=rng.randint(220, 500),
            price_gap_pct=rng.uniform(0.12, 0.34),
            num_competitors=0,
            competitors_on_sale=0,
            competitors_out_of_stock=0,
            match_type="no_match",
            match_score=rng.uniform(0.00, 0.30),
        )
    elif profile == "hold_thin_margin":
        _set_price_from_margin(row, rng, 18.0, 31.0)
        row.update(
            days_of_supply=rng.uniform(80.0, 160.0),
            total_qty=rng.randint(25, 100),
            season_sell_through_pct=rng.uniform(0.18, 0.42),
            days_since_launch=rng.randint(150, 360),
            price_gap_pct=rng.uniform(0.08, 0.28),
            num_competitors=rng.randint(1, 5),
            match_type=rng.choice(["exact_style", "same_model_family"]),
            match_score=rng.uniform(0.70, 0.95),
            days_since_last_discount=rng.randint(0, 18),
            discount_depth_last_30d=rng.uniform(0.08, 0.25),
        )
        row["competitors_on_sale"] = rng.randint(0, row["num_competitors"])
        row["competitors_out_of_stock"] = rng.randint(0, 1)
    elif profile == "hold_young_high_dos":
        _set_price_from_margin(row, rng, 36.0, 55.0)
        row.update(
            days_of_supply=rng.uniform(100.0, 180.0),
            total_qty=rng.randint(40, 140),
            season_sell_through_pct=rng.uniform(0.10, 0.34),
            days_since_launch=rng.randint(25, 95),
            price_gap_pct=rng.uniform(-0.03, 0.12),
            num_competitors=rng.randint(1, 4),
            competitors_on_sale=rng.randint(0, 1),
            competitors_out_of_stock=rng.randint(0, 1),
            match_type=rng.choice(["exact_style", "same_model_family"]),
            match_score=rng.uniform(0.70, 0.95),
        )
    elif profile == "markdown_reliable_overpriced":
        _set_price_from_margin(row, rng, 39.0, 60.0)
        row.update(
            days_of_supply=rng.uniform(60.0, 125.0),
            total_qty=rng.randint(30, 115),
            season_sell_through_pct=rng.uniform(0.22, 0.55),
            days_since_launch=rng.randint(60, 230),
            price_gap_pct=rng.uniform(0.16, 0.36),
            num_competitors=rng.randint(2, 7),
            match_type=rng.choice(["exact_style", "same_model_family"]),
            match_score=rng.uniform(0.78, 0.98),
            event_proximity_score=rng.uniform(0.20, 0.80),
            days_since_last_discount=rng.randint(35, 160),
            discount_depth_last_30d=rng.uniform(0.0, 0.08),
        )
        row["competitors_on_sale"] = rng.randint(max(1, row["num_competitors"] // 2), row["num_competitors"])
        row["competitors_out_of_stock"] = rng.randint(0, 1)
    elif profile == "promote_demand_capture":
        _set_price_from_margin(row, rng, 40.0, 62.0)
        row.update(
            days_of_supply=rng.uniform(28.0, 90.0),
            total_qty=rng.randint(24, 110),
            season_sell_through_pct=rng.uniform(0.30, 0.70),
            days_since_launch=rng.randint(25, 180),
            price_gap_pct=rng.uniform(-0.16, 0.02),
            num_competitors=rng.randint(2, 6),
            competitors_on_sale=0,
            match_type=rng.choice(["exact_style", "same_model_family"]),
            match_score=rng.uniform(0.75, 0.98),
            seasonality_score=rng.uniform(1.12, 1.55),
            event_proximity_score=rng.uniform(0.55, 0.95),
            days_since_last_discount=rng.randint(35, 140),
            discount_depth_last_30d=rng.uniform(0.0, 0.08),
        )
        row["competitors_out_of_stock"] = rng.randint(max(1, row["num_competitors"] // 2), row["num_competitors"])
    else:
        raise ValueError(f"Unsupported stress profile: {profile}")


def _finalize_row(row: dict[str, Any], inventory_medians: dict[tuple[str, str], float], label: str) -> None:
    _recompute_dependent_fields(row, inventory_medians)
    row["has_competitor_data"] = 0 if row.get("match_type") == "no_match" or int(row.get("num_competitors", 0) or 0) <= 0 else 1
    _set_competitor_prices(row)
    num_competitors = max(int(row.get("num_competitors", 0) or 0), 0)
    sale_ratio = (row.get("competitors_on_sale", 0) or 0) / num_competitors if num_competitors else 0.0
    oos_ratio = (row.get("competitors_out_of_stock", 0) or 0) / num_competitors if num_competitors else 0.0
    row["competitor_sale_frequency_4w"] = round(sale_ratio, 4)
    row["competitor_oos_frequency_4w"] = round(oos_ratio, 4)
    row["price_gap_volatility_4w"] = round(abs(_safe_float(row.get("price_gap_pct"), 0.0)) * 0.35, 4)
    row["stock_velocity_4w"] = round(max(0.01, 1.0 - min(_safe_float(row.get("days_of_supply"), 0.0), 240.0) / 260.0), 4)
    row["sell_through_velocity_4w"] = round(_safe_float(row.get("season_sell_through_pct"), 0.0) / 4.0, 4)
    row["days_since_competitor_change"] = int(max(1, min(90, _safe_float(row.get("days_since_last_discount"), 30.0) / 2.0)))
    row["competitor_price_trend_4w"] = round(-0.04 if label in {"CLEAR", "MARKDOWN"} else 0.01, 4)
    row["sales_units_last_28d"] = max(0, int(round(_safe_float(row.get("total_qty"), 0.0) / max(_safe_float(row.get("days_of_supply"), 1.0), 1.0) * 28.0)))
    row["avg_daily_sales_28d"] = round(row["sales_units_last_28d"] / 28.0, 4)
    row["rules_label"] = _assign_label(pd.Series(row))
    row["ai_label_disagrees_with_rules"] = bool(row["rules_label"] != row["ai_label"])


def build_clear_stress_test(
    *,
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    seed: int = 20260606,
) -> dict[str, Any]:
    if not input_path.exists():
        raise FileNotFoundError(f"Holdout input dataset not found: {input_path}")

    source = pd.read_csv(input_path)
    if source.empty:
        raise ValueError(f"Holdout input dataset is empty: {input_path}")

    rng = random.Random(seed)
    source = source.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    inventory_medians = _build_inventory_medians(source)

    rows: list[dict[str, Any]] = []
    row_index = 0
    for profile, (label, count) in PROFILE_PLAN.items():
        for _ in range(count):
            anchor = source.iloc[row_index % len(source)]
            row_index += 1
            row = _base_row(anchor, profile, label, row_index)
            _shape_row(row, profile, rng)
            _finalize_row(row, inventory_medians, label)
            rows.append(row)

    stress = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stress.to_csv(output_path, index=False)

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_holdout_dataset": str(input_path),
        "output_dataset": str(output_path),
        "row_count": int(len(stress)),
        "label_distribution": dict(Counter(stress["ai_label"])),
        "profile_distribution": dict(Counter(stress["augmentation_family"])),
        "rules_disagreement_count": int(stress["ai_label_disagrees_with_rules"].sum()),
        "note": "Evaluation-only stress set. Do not merge into training data.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an evaluation-only CLEAR stress-test dataset.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=20260606)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = build_clear_stress_test(
        input_path=args.input,
        output_path=args.output,
        report_path=args.report,
        seed=args.seed,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
