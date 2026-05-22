"""
Build an AI-assisted labeled training dataset from product-week features.

This script reads the merged training dataset, applies a broader expert-style
labeling heuristic than the baseline hard thresholds, and writes:

  data/features/ai_labeled_dataset.csv

The resulting file preserves the full feature matrix and adds:
  - ai_label
  - ai_label_confidence
  - ai_label_rationale
  - ai_score_hold
  - ai_score_markdown
  - ai_score_promote
  - ai_score_clear
  - ai_label_disagrees_with_rules

Run from the repo root:
    py services/decision_intelligence/features/build_ai_labeled_dataset.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
TRAINING_DATASET_PATH = ROOT / "data" / "features" / "training_dataset.csv"
OUTPUT_PATH = ROOT / "data" / "features" / "ai_labeled_dataset.csv"

LABELS = ["HOLD", "MARKDOWN", "PROMOTE", "CLEAR"]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def to_float(row: pd.Series, column: str, default: float = 0.0) -> float:
    try:
        value = row.get(column, default)
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def scale(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return clamp((value - low) / (high - low))


def _score_row(row: pd.Series) -> tuple[str, float, dict[str, float], str]:
    dos = to_float(row, "days_of_supply", 9999.0)
    qty = to_float(row, "total_qty", 0.0)
    margin = to_float(row, "current_margin_pct", 0.0)
    price_gap = to_float(row, "price_gap_pct", 0.0)
    comp_on_sale = to_float(row, "competitors_on_sale", 0.0)
    comp_out = to_float(row, "competitors_out_of_stock", 0.0)
    num_comp = to_float(row, "num_competitors", 0.0)
    seasonality = to_float(row, "seasonality_score", 1.0)
    event_score = to_float(row, "event_proximity_score", 0.0)
    sell_through = to_float(row, "season_sell_through_pct", 0.0)
    days_since_launch = to_float(row, "days_since_launch", 180.0)
    days_since_discount = to_float(row, "days_since_last_discount", 999.0)
    cash_tight = to_float(row, "cash_tight", 0.0)
    inventory_intensity = to_float(row, "inventory_intensity", 0.5)
    market_position = str(row.get("market_position", "at_market") or "at_market")
    category = str(row.get("category", "other") or "other")

    sale_pressure = clamp((comp_on_sale / num_comp) if num_comp > 0 else 0.0)
    inventory_pressure = scale(dos, 75, 180)
    severe_inventory = scale(dos, 120, 220)
    low_stock = max(scale(14 - dos, 0, 12), scale(12 - qty, 0, 10))
    age_pressure = scale(days_since_launch, 140, 360)
    stale_pressure = 1.0 - clamp(sell_through)
    season_strength = scale(seasonality, 1.03, 1.35)
    season_weakness = scale(1.0 - seasonality, 0.02, 0.40)
    markdown_ready_margin = scale(margin, 32, 58)
    thin_margin = scale(35 - margin, 0, 15)
    recent_discount_penalty = scale(28 - days_since_discount, 0, 28) if days_since_discount < 999 else 0.0
    market_overpricing = scale(price_gap, 0.03, 0.22)
    market_underpricing = scale(-price_gap, 0.03, 0.18)
    moderate_stock = 1.0 - clamp(abs(dos - 65.0) / 55.0)
    stock_health = clamp(1.0 - low_stock * 0.9 - severe_inventory * 0.45)
    event_promo_signal = clamp(event_score * 1.15)
    cash_pressure = clamp(cash_tight * 0.8 + scale(inventory_intensity, 0.58, 0.85) * 0.35)
    scarcity_signal = clamp(comp_out / num_comp) if num_comp > 0 else 0.0

    if category in {"swimwear", "football_boots"}:
        season_strength = clamp(season_strength * 1.12)
        season_weakness = clamp(season_weakness * 1.10)

    score_clear = (
        severe_inventory * 0.28
        + stale_pressure * 0.23
        + age_pressure * 0.18
        + season_weakness * 0.08
        + market_overpricing * 0.10
        + sale_pressure * 0.07
        + cash_pressure * 0.04
        + thin_margin * 0.02
    )

    score_markdown = (
        market_overpricing * 0.30
        + sale_pressure * 0.20
        + inventory_pressure * 0.18
        + stale_pressure * 0.12
        + markdown_ready_margin * 0.12
        + age_pressure * 0.05
        + cash_pressure * 0.03
        - recent_discount_penalty * 0.14
    )

    score_promote = (
        season_strength * 0.28
        + event_promo_signal * 0.24
        + moderate_stock * 0.16
        + markdown_ready_margin * 0.13
        + stock_health * 0.10
        + scarcity_signal * 0.05
        + market_underpricing * 0.06
        - inventory_pressure * 0.05
        - recent_discount_penalty * 0.06
    )

    score_hold = (
        stock_health * 0.22
        + moderate_stock * 0.18
        + clamp(1.0 - market_overpricing) * 0.16
        + clamp(1.0 - sale_pressure) * 0.12
        + clamp(1.0 - severe_inventory) * 0.10
        + clamp(1.0 - season_weakness) * 0.08
        + clamp(1.0 - recent_discount_penalty) * 0.08
        + clamp(1.0 - cash_pressure) * 0.06
    )

    # Gentle business-aware adjustments.
    if low_stock > 0.45:
        score_hold += 0.16
        score_markdown -= 0.10
        score_clear -= 0.05
    if num_comp <= 0:
        score_hold += 0.08
        score_promote -= 0.03
        score_markdown -= 0.04
    if market_position == "premium":
        score_markdown += 0.07
    elif market_position == "below_market":
        score_promote += 0.04
        score_hold += 0.03
    elif market_position == "deep_value":
        score_hold += 0.06
        score_promote += 0.03

    # Make markdown easier to win when multiple commercial signals line up.
    obvious_markdown_pressure = clamp(
        market_overpricing * 0.38
        + sale_pressure * 0.22
        + inventory_pressure * 0.18
        + stale_pressure * 0.10
        + markdown_ready_margin * 0.12
        + clamp(1.0 - recent_discount_penalty) * 0.08
    )
    if obvious_markdown_pressure >= 0.33:
        score_markdown += 0.10
    if market_overpricing >= 0.18 and sale_pressure >= 0.35:
        score_markdown += 0.08
    if market_overpricing >= 0.16 and inventory_pressure >= 0.16 and markdown_ready_margin >= 0.28:
        score_markdown += 0.08
    if season_strength >= 0.55 and event_score >= 0.70 and market_overpricing < 0.10:
        score_markdown -= 0.06
        score_promote += 0.04
    if dos >= 125 and stale_pressure >= 0.84 and age_pressure >= 0.45:
        score_clear += 0.12
        score_markdown -= 0.10
    if dos >= 125 and sell_through <= 0.16 and days_since_launch >= 220 and market_overpricing >= 0.15:
        score_clear += 0.10
        score_markdown -= 0.06

    scores = {
        "HOLD": round(max(score_hold, 0.0), 4),
        "MARKDOWN": round(max(score_markdown, 0.0), 4),
        "PROMOTE": round(max(score_promote, 0.0), 4),
        "CLEAR": round(max(score_clear, 0.0), 4),
    }

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_label, best_score = ranked[0]
    second_score = ranked[1][1]

    # Expert-style guardrails: let very strong product-week conditions override
    # the generic HOLD bias when a clear intervention pattern is present.
    if (
        severe_inventory >= 0.55
        and stale_pressure >= 0.75
        and dos >= 150
        and (days_since_launch >= 60 or seasonality <= 0.90 or market_overpricing >= 0.15)
        and score_clear >= 0.40
    ):
        best_label = "CLEAR"
        best_score = scores["CLEAR"]
        second_score = max(scores["HOLD"], scores["MARKDOWN"], scores["PROMOTE"])
    elif (
        dos >= 125
        and sell_through <= 0.16
        and days_since_launch >= 220
        and score_clear >= 0.38
        and (
            market_overpricing >= 0.15
            or sale_pressure >= 0.45
            or market_position == "premium"
        )
    ):
        best_label = "CLEAR"
        best_score = scores["CLEAR"]
        second_score = max(scores["HOLD"], scores["MARKDOWN"], scores["PROMOTE"])
    elif (
        seasonality >= 1.08
        and event_score >= 0.50
        and 20 <= dos <= 100
        and margin >= 38
        and low_stock <= 0.25
        and recent_discount_penalty <= 0.35
        and score_promote >= 0.42
        and price_gap <= 0.18
    ):
        best_label = "PROMOTE"
        best_score = scores["PROMOTE"]
        second_score = max(scores["HOLD"], scores["MARKDOWN"], scores["CLEAR"])
    elif (
        market_overpricing >= 0.18
        and inventory_pressure >= 0.14
        and markdown_ready_margin >= 0.24
        and recent_discount_penalty <= 0.45
        and (
            sale_pressure >= 0.35
            or stale_pressure >= 0.70
            or obvious_markdown_pressure >= 0.42
        )
        and score_markdown >= 0.33
    ):
        best_label = "MARKDOWN"
        best_score = scores["MARKDOWN"]
        second_score = max(scores["HOLD"], scores["PROMOTE"], scores["CLEAR"])

    confidence = clamp(0.55 + (best_score - second_score) * 1.35, 0.55, 0.98)

    rationale_parts: list[str] = []
    if best_label == "CLEAR":
        if dos >= 120:
            rationale_parts.append(f"very high stock cover ({dos:.0f} DOS)")
        if sell_through <= 0.20:
            rationale_parts.append(f"weak sell-through ({sell_through:.0%})")
        if days_since_launch >= 200:
            rationale_parts.append(f"older lifecycle stage ({days_since_launch:.0f} days)")
        if seasonality < 0.95:
            rationale_parts.append("weak seasonal fit")
    elif best_label == "MARKDOWN":
        if price_gap > 0.05:
            rationale_parts.append(f"priced above market by {price_gap:.0%}")
        if sale_pressure > 0.30:
            rationale_parts.append("competitors are discounting")
        if dos >= 90:
            rationale_parts.append(f"stock cover is elevated ({dos:.0f} DOS)")
        if margin >= 35:
            rationale_parts.append("margin can support a markdown")
    elif best_label == "PROMOTE":
        if seasonality >= 1.10:
            rationale_parts.append(f"strong seasonality ({seasonality:.2f})")
        if event_score >= 0.5:
            rationale_parts.append("calendar/event timing supports demand")
        if 20 <= dos <= 100:
            rationale_parts.append(f"healthy stock position ({dos:.0f} DOS)")
        if margin >= 40:
            rationale_parts.append("margin supports promotion")
    else:
        if stock_health > 0.50:
            rationale_parts.append("inventory position is balanced")
        if abs(price_gap) <= 0.05:
            rationale_parts.append("price is close to market")
        if recent_discount_penalty == 0:
            rationale_parts.append("no urgent pricing intervention is needed")
        if season_strength < 0.35:
            rationale_parts.append("seasonal pressure is moderate")

    rationale = "; ".join(rationale_parts[:3]) if rationale_parts else "balanced product-week state"
    return best_label, round(confidence, 4), scores, rationale


def build_ai_labeled_dataset(
    training_dataset_path: Path = TRAINING_DATASET_PATH,
    output_path: Path = OUTPUT_PATH,
) -> pd.DataFrame:
    if not training_dataset_path.exists():
        raise FileNotFoundError(
            f"Training dataset not found: {training_dataset_path}\n"
            "Run: py services/decision_intelligence/features/build_training_dataset.py"
        )

    df = pd.read_csv(training_dataset_path)

    ai_labels: list[str] = []
    ai_confidences: list[float] = []
    rationales: list[str] = []
    hold_scores: list[float] = []
    markdown_scores: list[float] = []
    promote_scores: list[float] = []
    clear_scores: list[float] = []

    for _, row in df.iterrows():
        ai_label, confidence, scores, rationale = _score_row(row)
        ai_labels.append(ai_label)
        ai_confidences.append(confidence)
        rationales.append(rationale)
        hold_scores.append(scores["HOLD"])
        markdown_scores.append(scores["MARKDOWN"])
        promote_scores.append(scores["PROMOTE"])
        clear_scores.append(scores["CLEAR"])

    labeled_df = df.copy()
    labeled_df["ai_label"] = ai_labels
    labeled_df["ai_label_confidence"] = ai_confidences
    labeled_df["ai_label_rationale"] = rationales
    labeled_df["ai_score_hold"] = hold_scores
    labeled_df["ai_score_markdown"] = markdown_scores
    labeled_df["ai_score_promote"] = promote_scores
    labeled_df["ai_score_clear"] = clear_scores
    labeled_df["ai_label_disagrees_with_rules"] = (
        labeled_df["rules_label"].astype(str) != labeled_df["ai_label"].astype(str)
    ).astype(int)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    labeled_df.to_csv(output_path, index=False)

    disagreement_rate = labeled_df["ai_label_disagrees_with_rules"].mean() * 100.0
    print("\n" + "=" * 76)
    print("AI-LABELED DATASET SUMMARY")
    print("=" * 76)
    print("This dataset keeps the real product-week rows and adds AI-assisted labels.")
    print("These labels are stronger weak supervision than rules_label, but they are not ground truth.")
    print("")
    print(f"Input rows:                 {len(df)}")
    print(f"Output file:                {output_path}")
    print(f"AI label distribution:      {labeled_df['ai_label'].value_counts().to_dict()}")
    print(f"Rules disagreement rate:    {disagreement_rate:.2f}%")
    print("")
    print("Sample rows:")
    preview_cols = [
        "state_id",
        "sku_id",
        "week_of",
        "rules_label",
        "ai_label",
        "ai_label_confidence",
        "ai_label_rationale",
    ]
    print(labeled_df[preview_cols].head(8).to_string(index=False))
    print("=" * 76)
    print("To train on these labels later, point train.py at this file and use --label-column ai_label.")
    print("=" * 76)

    return labeled_df


if __name__ == "__main__":
    build_ai_labeled_dataset()
