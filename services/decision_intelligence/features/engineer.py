"""
Feature Engineering Pipeline - IE2 Decision Intelligence.

Builds one feature row per real product-week state.

Execution flow:
  1. clean competitor data
  2. generate historical product-week states
  3. engineer model features from those states
  4. then proceed to labeling/training

Usage:
    py services/decision_intelligence/features/generate_historical_states.py
    py -m services.decision_intelligence.features.engineer
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = ROOT / "data" / "real"
DEFAULT_STATES_PATH = ROOT / "data" / "features" / "historical_product_states.csv"
DEFAULT_OUTPUT = ROOT / "data" / "features" / "features.csv"

SENTINEL_DAYS_NO_DISCOUNT = 999
SENTINEL_DAYS_AT_PRICE = 30
DEFAULT_INVENTORY_INTENSITY = 0.70
DEFAULT_INVENTORY_AT_COST = 176_000
DEFAULT_TOTAL_ASSETS = 214_000

CATEGORY_VELOCITY = {
    "footwear": 0.80,
    "football_boots": 0.70,
    "apparel": 1.15,
    "sportswear": 1.00,
    "swimwear": 0.60,
    "accessories": 1.30,
    "kids": 0.90,
    "lifestyle": 0.85,
    "other": 0.80,
}

SEASONAL_MULTIPLIERS = {
    1: 0.70, 2: 0.80, 3: 0.90, 4: 1.10, 5: 1.15, 6: 1.20,
    7: 1.10, 8: 1.30, 9: 1.20, 10: 0.90, 11: 0.85, 12: 0.90,
}

CATEGORY_SEASONAL_BOOST = {
    "swimwear": {5: 0.3, 6: 0.5, 7: 0.5, 8: 0.3},
    "football_boots": {8: 0.3, 9: 0.4, 10: 0.2},
    "kids": {8: 0.4, 9: 0.3},
}

EVENT_WINDOWS = {
    8: ("back_to_school", 0.9),
    9: ("back_to_school", 0.7),
    4: ("eid_al_fitr", 0.8),
    3: ("eid_al_fitr", 0.5),
    12: ("holiday_gifting", 0.7),
    11: ("pre_holiday", 0.5),
}

BRAND_TIER = {
    "Adidas": "tier1",
    "Nike": "tier1",
    "New Balance": "tier1",
    "ON": "tier1",
    "The North Face": "tier1",
    "Puma": "tier2",
    "ASICS": "tier2",
    "Crocs": "tier2",
    "Billabong": "tier3",
    "Bogner": "tier3",
    "Babolat": "tier3",
}


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _get_seasonal_multiplier(month: int, category: str | None = None) -> float:
    base = SEASONAL_MULTIPLIERS.get(month, 1.0)
    if category and category in CATEGORY_SEASONAL_BOOST:
        return base + CATEGORY_SEASONAL_BOOST[category].get(month, 0.0)
    return base


def _estimate_daily_demand(units_on_hand: float, category: str, num_competitors: int, retail_price: float) -> float:
    if units_on_hand <= 0:
        return 0.02

    base_daily = units_on_hand / 65.0
    velocity_adj = CATEGORY_VELOCITY.get(category, 1.0)

    if num_competitors >= 5:
        competitor_adj = 1.2
    elif num_competitors >= 3:
        competitor_adj = 1.05
    elif num_competitors <= 1:
        competitor_adj = 0.85
    else:
        competitor_adj = 1.0

    price_adj = min(1.3, max(0.7, 80.0 / max(retail_price, 20.0)))
    return max(0.02, base_daily * velocity_adj * competitor_adj * price_adj)


def compute_competitor_features(state_row: dict, our_price: float) -> dict:
    has_competitor_data = _to_int(state_row.get("has_competitor_data", 0), 0)
    market_min = _to_float(state_row.get("competitor_min_price_usd"), 0.0)
    num_competitors = _to_int(state_row.get("num_competitors", 0), 0)
    on_sale_count = _to_int(state_row.get("competitors_on_sale_count", 0), 0)
    out_of_stock_count = _to_int(state_row.get("competitors_out_of_stock_count", 0), 0)
    freshness_hours = _to_float(state_row.get("data_freshness_hours"), 72.0)

    if not has_competitor_data or market_min <= 0 or num_competitors <= 0:
        return {
            "price_gap_pct": 0.0,
            "competitors_on_sale": on_sale_count,
            "competitors_out_of_stock": out_of_stock_count,
            "num_competitors": num_competitors,
            "market_position": "at_market",
            "competitor_confidence": 0.0,
        }

    price_gap = (our_price - market_min) / our_price if our_price > 0 else 0.0

    if price_gap > 0.15:
        position = "premium"
    elif price_gap > 0.05:
        position = "above_market"
    elif price_gap > -0.05:
        position = "at_market"
    elif price_gap > -0.15:
        position = "below_market"
    else:
        position = "deep_value"

    confidence = max(0.25, min(1.0, 1.0 - freshness_hours / 168.0))
    return {
        "price_gap_pct": round(price_gap, 4),
        "competitors_on_sale": on_sale_count,
        "competitors_out_of_stock": out_of_stock_count,
        "num_competitors": num_competitors,
        "market_position": position,
        "competitor_confidence": round(confidence, 4),
    }


def compute_state_features(state_row: dict, financial_profile: dict) -> dict:
    sku_id = str(state_row.get("sku_id", ""))
    state_id = str(state_row.get("state_id", f"{sku_id}|{state_row.get('week_of', '')}"))
    product_key = state_row.get("product_key", "")
    brand = str(state_row.get("brand", "Unknown") or "Unknown")
    style_code = state_row.get("style_code", "")
    category = str(state_row.get("category", state_row.get("system_category", "other")) or "other")
    product_name = state_row.get("product_name", "")
    week_of = str(state_row.get("week_of", ""))

    week_date = date.fromisoformat(week_of[:10])
    retail_price = _to_float(state_row.get("retail_price_usd"), 100.0)
    cost_price = _to_float(state_row.get("cost_price_usd"), 50.0)
    total_qty = max(0, _to_int(state_row.get("total_qty", 0), 0))
    current_margin_pct = round((1 - cost_price / retail_price) * 100, 2) if retail_price > 0 else 0.0

    competitor = compute_competitor_features(state_row, retail_price)
    avg_daily_demand = _estimate_daily_demand(total_qty, category, competitor["num_competitors"], retail_price)
    days_of_supply = round(total_qty / avg_daily_demand, 1) if avg_daily_demand > 0 else 9999.0
    stock_coverage_ratio = round(days_of_supply / 30.0, 2)
    stockout_risk = 1 if days_of_supply < 14 else 0

    simulated_peak_stock = max(_to_int(state_row.get("simulated_peak_stock", total_qty), total_qty), 1)
    sell_through = _to_float(state_row.get("sell_through_proxy"), 1 - (total_qty / simulated_peak_stock))
    sell_through = round(min(max(sell_through, 0.0), 1.0), 4)

    days_since_launch = max(0, _to_int(state_row.get("days_since_launch", state_row.get("launch_age_days", 180)), 180))
    days_since_last_discount = _to_int(state_row.get("days_since_last_discount", SENTINEL_DAYS_NO_DISCOUNT), SENTINEL_DAYS_NO_DISCOUNT)
    days_at_current_price = _to_int(state_row.get("days_at_current_price", SENTINEL_DAYS_AT_PRICE), SENTINEL_DAYS_AT_PRICE)
    discount_depth_last_30d = round(_to_float(state_row.get("discount_depth_last_30d_proxy", 0.0), 0.0), 4)

    seasonality_score = _to_float(state_row.get("seasonality_score"), _get_seasonal_multiplier(week_date.month, category))
    category_seasonal_boost = _to_float(state_row.get("category_seasonal_boost"), CATEGORY_SEASONAL_BOOST.get(category, {}).get(week_date.month, 0.0))
    event_proximity_score = _to_float(state_row.get("event_proximity_score"), EVENT_WINDOWS.get(week_date.month, ("none", 0.0))[1])
    next_month = (week_date.month % 12) + 1
    next_month_seasonality = _get_seasonal_multiplier(next_month, category)

    cash_runway = _to_float(financial_profile.get("cashflow_summary", {}).get("cash_runway_months"), 3.0)
    cash_tight = 1 if cash_runway < 2.5 else 0
    inventory_at_cost = _to_float(financial_profile.get("inventory_summary", {}).get("total_cost_usd"), DEFAULT_INVENTORY_AT_COST)
    total_assets = _to_float(financial_profile.get("balance_sheet_summary", {}).get("total_assets_usd"), DEFAULT_TOTAL_ASSETS)
    inventory_intensity = round(inventory_at_cost / total_assets, 4) if total_assets > 0 else DEFAULT_INVENTORY_INTENSITY

    return {
        "state_id": state_id,
        "sku_id": sku_id,
        "product_key": product_key,
        "style_code": style_code,
        "brand": brand,
        "category": category,
        "product_name": product_name,
        "week_of": week_of,
        "days_of_supply": days_of_supply,
        "stock_coverage_ratio": stock_coverage_ratio,
        "stockout_risk": stockout_risk,
        "total_qty": total_qty,
        "inventory_vs_median": 1.0,
        "current_margin_pct": current_margin_pct,
        "discount_depth_last_30d": discount_depth_last_30d,
        "days_since_last_discount": days_since_last_discount,
        "days_at_current_price": days_at_current_price,
        "retail_price_usd": retail_price,
        "price_gap_pct": competitor["price_gap_pct"],
        "competitors_on_sale": competitor["competitors_on_sale"],
        "competitors_out_of_stock": competitor["competitors_out_of_stock"],
        "num_competitors": competitor["num_competitors"],
        "market_position": competitor["market_position"],
        "days_since_launch": days_since_launch,
        "season_sell_through_pct": sell_through,
        "brand_tier": BRAND_TIER.get(brand, "tier2"),
        "cost_price_usd": cost_price,
        "seasonality_score": round(seasonality_score, 3),
        "category_seasonal_boost": round(category_seasonal_boost, 3),
        "event_proximity_score": round(event_proximity_score, 3),
        "next_month_seasonality": round(next_month_seasonality, 3),
        "cash_runway_months": round(cash_runway, 2),
        "cash_tight": cash_tight,
        "inventory_intensity": inventory_intensity,
    }


def apply_inventory_vs_median_correction(all_features: list[dict]) -> list[dict]:
    grouped_qtys: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in all_features:
        grouped_qtys[(row["week_of"], row["category"])].append(float(row["total_qty"]))

    grouped_medians = {
        key: statistics.median(values)
        for key, values in grouped_qtys.items()
        if values
    }

    for row in all_features:
        median = grouped_medians.get((row["week_of"], row["category"]), 1.0)
        row["inventory_vs_median"] = round(row["total_qty"] / median, 4) if median > 0 else 1.0

    return all_features


def build_features(
    data_dir: str | Path | None = None,
    states_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> list[dict]:
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    states_path = Path(states_path) if states_path else DEFAULT_STATES_PATH
    output_path = Path(output_path) if output_path else DEFAULT_OUTPUT

    print("Building feature matrix from historical product-week states...")

    if not states_path.exists():
        raise FileNotFoundError(
            f"Historical states file not found: {states_path}\n"
            "Run: py services/decision_intelligence/features/generate_historical_states.py"
        )

    states = _load_csv(states_path)
    financial_profile = _load_json(data_dir / "financial_profile.json")

    print(f"  Loaded {len(states)} historical product-week states")

    all_features = [compute_state_features(state_row, financial_profile) for state_row in states]
    all_features = apply_inventory_vs_median_correction(all_features)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if all_features:
        fieldnames = list(all_features[0].keys())
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_features)
        print(f"  Wrote {len(all_features)} rows -> {output_path}")

    return all_features


def _print_summary(features: list[dict]) -> None:
    if not features:
        print("No features were generated.")
        return

    dos_values = [row["days_of_supply"] for row in features if row["days_of_supply"] < 9999]
    margin_values = [row["current_margin_pct"] for row in features]
    position_counts: dict[str, int] = defaultdict(int)
    unique_products = {row["sku_id"] for row in features}
    unique_weeks = {row["week_of"] for row in features}

    for row in features:
        position_counts[row["market_position"]] += 1

    print("\n" + "=" * 68)
    print("FEATURE MATRIX SUMMARY")
    print("=" * 68)
    print(f"Total product-week rows: {len(features)}")
    print(f"Unique products:         {len(unique_products)}")
    print(f"Unique weeks:            {len(unique_weeks)}")
    print(f"Features per row:        {len(features[0]) - 8}")
    if dos_values:
        print(
            f"DOS range:               {min(dos_values):.0f} - {max(dos_values):.0f} days "
            f"(median: {statistics.median(dos_values):.0f})"
        )
    if margin_values:
        print(
            f"Margin range:            {min(margin_values):.1f}% - {max(margin_values):.1f}% "
            f"(avg: {statistics.mean(margin_values):.1f}%)"
        )
    print("Market positions:")
    for pos, count in sorted(position_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {pos:<18} {count}")
    print("Sample feature rows:")
    for row in features[:3]:
        print(
            f"  {row['state_id']} | qty={row['total_qty']} | gap={row['price_gap_pct']:.3f} | "
            f"comp={row['num_competitors']} | season={row['seasonality_score']:.2f}"
        )
    print("=" * 68)


if __name__ == "__main__":
    feature_rows = build_features()
    _print_summary(feature_rows)
