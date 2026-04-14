"""
Generate historical product-week states anchored to the real catalog.

This script expands the real product catalog into a defensible product-week
training table. Each generated row maps back to an existing real product from
products.csv; only time-varying state fields are simulated.

Execution flow:
  1. clean competitor data
  2. run generate_historical_states.py
  3. run engineer.py
  4. then proceed to labeling/training

Run from the repo root:
    py services/decision_intelligence/features/generate_historical_states.py
"""

from __future__ import annotations

import argparse
import hashlib
import math
from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PRODUCTS_PATH = ROOT / "data" / "real" / "products.csv"
INVENTORY_PATH = ROOT / "data" / "real" / "inventory.csv"
COMPETITOR_CLEAN_PATH = ROOT / "data" / "real" / "competitor_prices_clean.csv"
OUTPUT_PATH = ROOT / "data" / "features" / "historical_product_states.csv"

DEFAULT_WEEKS = 16

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

EXPECTED_PRODUCT_COLUMNS = {
    "sku_id",
    "product_key",
    "style_code",
    "brand",
    "product_name",
    "system_category",
    "gender",
    "retail_price_usd",
    "cost_price_usd",
    "initial_stock",
    "collection_type",
}

EXPECTED_INVENTORY_COLUMNS = {
    "sku_id",
    "current_stock",
    "initial_stock",
}

EXPECTED_COMPETITOR_COLUMNS = {
    "product_key",
    "competitor_min_price_usd",
    "competitor_avg_price_usd",
    "competitor_max_price_usd",
    "num_competitors",
    "competitors_on_sale_count",
    "competitors_on_sale_ratio",
    "competitors_in_stock_count",
    "competitors_out_of_stock_count",
    "has_competitor_data",
    "data_freshness_hours",
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
    return df


def ensure_columns(df: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(
            f"{name} is missing required columns: {', '.join(missing)}. "
            f"Available columns: {', '.join(df.columns)}"
        )


def stable_unit_float(*parts: object) -> float:
    key = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def stable_range(low: float, high: float, *parts: object) -> float:
    return low + (high - low) * stable_unit_float(*parts)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def week_starts(num_weeks: int, anchor_date: date | None = None) -> list[pd.Timestamp]:
    anchor_ts = pd.Timestamp(anchor_date or date.today()).normalize()
    anchor_week = anchor_ts - pd.Timedelta(days=anchor_ts.weekday())
    oldest_week = anchor_week - pd.Timedelta(weeks=num_weeks - 1)
    return [oldest_week + pd.Timedelta(weeks=offset) for offset in range(num_weeks)]


def get_seasonal_multiplier(week_ts: pd.Timestamp, category: str) -> float:
    month = int(week_ts.month)
    base = SEASONAL_MULTIPLIERS.get(month, 1.0)
    boost = CATEGORY_SEASONAL_BOOST.get(category, {}).get(month, 0.0)
    return base + boost


def get_category_boost(week_ts: pd.Timestamp, category: str) -> float:
    return CATEGORY_SEASONAL_BOOST.get(category, {}).get(int(week_ts.month), 0.0)


def get_event_score(week_ts: pd.Timestamp) -> tuple[str, float]:
    return EVENT_WINDOWS.get(int(week_ts.month), ("none", 0.0))


def infer_current_age_days(product_row: pd.Series) -> int:
    category = str(product_row.get("system_category", "other") or "other")
    collection_type = str(product_row.get("collection_type", "core") or "core").lower()

    if collection_type == "core":
        low, high = 140, 320
    elif collection_type == "seasonal":
        low, high = 45, 180
    else:
        low, high = 90, 240

    if category == "swimwear":
        low, high = 35, 140
    elif category == "football_boots":
        low, high = max(low, 60), min(high, 220)
    elif category == "accessories":
        low, high = max(low, 120), max(high, 260)

    return int(round(stable_range(low, high, product_row["sku_id"], "age")))


def compute_market_pressure(retail_price: float, competitor_min: float | None, sale_ratio: float, has_competitor_data: int) -> float:
    if not has_competitor_data or not competitor_min or retail_price <= 0:
        return 1.0
    price_gap = max((retail_price - competitor_min) / retail_price, 0.0)
    return clamp(1.0 + price_gap * 0.8 + sale_ratio * 0.35, 0.9, 1.8)


def infer_peak_stock(product_row: pd.Series, current_stock: int, weeks: int, market_pressure: float) -> int:
    category = str(product_row.get("system_category", "other") or "other")
    velocity = CATEGORY_VELOCITY.get(category, 0.8)
    initial_stock = int(round(float(product_row.get("inventory_initial_stock", product_row.get("initial_stock", current_stock)) or current_stock)))
    base_anchor = max(initial_stock, current_stock)

    extra_stock = int(round(
        weeks * (0.55 + velocity * 0.85 + stable_range(0.05, 0.55, product_row["sku_id"], "stock"))
        * market_pressure
    ))
    extra_stock = max(4, extra_stock)

    cap = max(
        current_stock + 8,
        int(round(base_anchor * (1.8 + velocity * 0.6))),
        current_stock + int(round(weeks * (1.4 + velocity))),
    )
    peak_stock = min(max(base_anchor, current_stock + extra_stock), cap)
    return int(max(peak_stock, current_stock))


def build_inventory_curve(product_row: pd.Series, weeks: list[pd.Timestamp], peak_stock: int, current_stock: int, market_pressure: float) -> list[int]:
    if len(weeks) == 1:
        return [current_stock]

    category = str(product_row.get("system_category", "other") or "other")
    phase = stable_range(0.0, math.pi * 2, product_row["sku_id"], "inventory_phase")
    total_depletion = max(peak_stock - current_stock, 0)

    interval_weights: list[float] = []
    for idx, week_ts in enumerate(weeks[:-1]):
        seasonality = get_seasonal_multiplier(week_ts, category)
        wave = math.sin(phase + idx * 0.65)
        weight = 0.8 + (seasonality - 1.0) * 0.7 + (market_pressure - 1.0) * 0.35 + wave * 0.12
        interval_weights.append(max(weight, 0.15))

    weight_sum = sum(interval_weights) or 1.0
    quantities = [peak_stock]
    cumulative_weight = 0.0
    for weight in interval_weights:
        cumulative_weight += weight
        sold_so_far = round(total_depletion * cumulative_weight / weight_sum)
        next_qty = max(current_stock, peak_stock - sold_so_far)
        quantities.append(int(next_qty))

    quantities[-1] = current_stock
    for idx in range(1, len(quantities)):
        quantities[idx] = min(quantities[idx], quantities[idx - 1])
    return quantities


def build_discount_schedule(product_row: pd.Series, weeks: list[pd.Timestamp], market_pressure: float, peak_stock: int, current_stock: int) -> tuple[list[int], list[int], list[float]]:
    stock_pressure = (peak_stock - current_stock) / max(peak_stock, 1)
    pressure_score = market_pressure - 1.0 + stock_pressure * 0.65

    if pressure_score >= 0.75 and len(weeks) >= 12:
        event_count = 2
    elif pressure_score >= 0.30:
        event_count = 1
    else:
        event_count = 0

    event_positions: list[int] = []
    if event_count >= 1:
        event_positions.append(int(round(stable_range(len(weeks) * 0.30, len(weeks) * 0.72, product_row["sku_id"], "discount_1"))))
    if event_count >= 2:
        event_positions.append(int(round(stable_range(len(weeks) * 0.60, len(weeks) * 0.92, product_row["sku_id"], "discount_2"))))

    event_positions = sorted({clamp(int(pos), 1, len(weeks) - 2) for pos in event_positions})
    base_discount = stable_range(0.06, 0.18, product_row["sku_id"], "discount_depth") * max(market_pressure, 1.0)
    base_discount = clamp(base_discount, 0.05, 0.25)

    days_since_last_discount: list[int] = []
    days_at_current_price: list[int] = []
    discount_depth_last_30d: list[float] = []

    for idx in range(len(weeks)):
        prior_events = [event_idx for event_idx in event_positions if event_idx <= idx]
        if not prior_events:
            days_since_last_discount.append(999)
            days_at_current_price.append((idx + 1) * 7)
            discount_depth_last_30d.append(0.0)
            continue

        last_event = prior_events[-1]
        days_since = int((idx - last_event) * 7)
        days_since_last_discount.append(days_since)
        days_at_current_price.append(days_since)

        if days_since <= 30:
            recency_decay = 1.0 - (days_since / 35.0)
            discount_depth_last_30d.append(round(base_discount * max(recency_decay, 0.15), 4))
        else:
            discount_depth_last_30d.append(0.0)

    return days_since_last_discount, days_at_current_price, discount_depth_last_30d


def build_competitor_history(product_row: pd.Series, weeks: list[pd.Timestamp]) -> list[dict[str, object]]:
    has_comp = int(product_row.get("has_competitor_data", 0) or 0)
    category = str(product_row.get("system_category", "other") or "other")

    if not has_comp:
        return [
            {
                "competitor_min_price_usd": pd.NA,
                "competitor_avg_price_usd": pd.NA,
                "competitor_max_price_usd": pd.NA,
                "num_competitors": 0,
                "competitors_on_sale_count": 0,
                "competitors_on_sale_ratio": 0.0,
                "competitors_in_stock_count": 0,
                "competitors_out_of_stock_count": 0,
                "data_freshness_hours": round(stable_range(18.0, 72.0, product_row["sku_id"], "fresh_no_comp"), 2),
                "has_competitor_data": 0,
            }
            for _ in weeks
        ]

    min_anchor = float(product_row.get("competitor_min_price_usd", 0) or 0)
    avg_anchor = float(product_row.get("competitor_avg_price_usd", min_anchor) or min_anchor or 0)
    max_anchor = float(product_row.get("competitor_max_price_usd", avg_anchor) or avg_anchor or 0)
    num_anchor = int(product_row.get("num_competitors", 0) or 0)
    sale_count_anchor = int(product_row.get("competitors_on_sale_count", 0) or 0)
    sale_ratio_anchor = float(product_row.get("competitors_on_sale_ratio", 0.0) or 0.0)
    in_stock_anchor = int(product_row.get("competitors_in_stock_count", num_anchor) or 0)
    oos_anchor = int(product_row.get("competitors_out_of_stock_count", 0) or 0)
    freshness_anchor = float(product_row.get("data_freshness_hours", 24.0) or 24.0)

    amp = stable_range(0.015, 0.055, product_row["sku_id"], "market_amp")
    trend_per_week = stable_range(-0.003, 0.003, product_row["sku_id"], "market_trend")
    phase = stable_range(0.0, math.pi * 2, product_row["sku_id"], "market_phase")
    latest_idx = len(weeks) - 1
    latest_wave = math.sin(phase + latest_idx * 0.60)
    latest_season = get_seasonal_multiplier(weeks[-1], category)
    latest_event = get_event_score(weeks[-1])[1]

    min_avg_gap = max(avg_anchor - min_anchor, min_anchor * 0.02, 1.0)
    avg_max_gap = max(max_anchor - avg_anchor, avg_anchor * 0.02, 1.0)

    history: list[dict[str, object]] = []
    for idx, week_ts in enumerate(weeks):
        wave_delta = math.sin(phase + idx * 0.60) - latest_wave
        week_offset = idx - latest_idx
        seasonality = get_seasonal_multiplier(week_ts, category)
        event_score = get_event_score(week_ts)[1]

        price_multiplier = 1.0
        price_multiplier += amp * wave_delta
        price_multiplier += trend_per_week * week_offset
        price_multiplier += 0.015 * ((seasonality - 1.0) - (latest_season - 1.0))
        price_multiplier = clamp(price_multiplier, 0.88, 1.12)

        min_price = max(1.0, round(min_anchor * price_multiplier, 2))
        avg_price = max(min_price, round(avg_anchor * price_multiplier, 2))
        max_price = max(avg_price, round(max_anchor * price_multiplier, 2))

        if avg_price - min_price < min_avg_gap * 0.35:
            avg_price = round(min_price + min_avg_gap * 0.35, 2)
        if max_price - avg_price < avg_max_gap * 0.35:
            max_price = round(avg_price + avg_max_gap * 0.35, 2)

        raw_num = num_anchor + round((stable_range(0.8, 1.4, product_row["sku_id"], "comp_count_amp")) * wave_delta)
        num_competitors = max(1, raw_num)

        sale_ratio = sale_ratio_anchor
        sale_ratio += 0.08 * ((seasonality - 1.0) - (latest_season - 1.0))
        sale_ratio += 0.10 * (event_score - latest_event)
        sale_ratio += 0.06 * wave_delta
        sale_ratio = clamp(sale_ratio, 0.0, 1.0)
        on_sale_count = int(round(num_competitors * sale_ratio))

        anchor_oos_ratio = (oos_anchor / num_anchor) if num_anchor > 0 else 0.0
        oos_ratio = clamp(anchor_oos_ratio + 0.04 * (-wave_delta), 0.0, 0.8)
        out_of_stock_count = int(round(num_competitors * oos_ratio))
        in_stock_count = max(0, num_competitors - out_of_stock_count)

        freshness = freshness_anchor + 8.0 * wave_delta + 10.0 * (event_score - latest_event)
        freshness = round(clamp(freshness, 6.0, 96.0), 2)

        history.append(
            {
                "competitor_min_price_usd": min_price,
                "competitor_avg_price_usd": avg_price,
                "competitor_max_price_usd": max_price,
                "num_competitors": int(num_competitors),
                "competitors_on_sale_count": int(min(on_sale_count, num_competitors)),
                "competitors_on_sale_ratio": round((on_sale_count / num_competitors) if num_competitors else 0.0, 4),
                "competitors_in_stock_count": int(in_stock_count),
                "competitors_out_of_stock_count": int(out_of_stock_count),
                "data_freshness_hours": freshness,
                "has_competitor_data": 1,
            }
        )

    return history


def simulate_product_history(product_row: pd.Series, weeks: list[pd.Timestamp]) -> list[dict[str, object]]:
    retail_price = float(product_row.get("retail_price_usd", 0) or 0)
    cost_price = float(product_row.get("cost_price_usd", 0) or 0)
    current_stock = int(round(float(product_row.get("current_stock", product_row.get("inventory_initial_stock", 0)) or 0)))
    current_stock = max(current_stock, 0)

    market_pressure = compute_market_pressure(
        retail_price=retail_price,
        competitor_min=float(product_row.get("competitor_min_price_usd", 0) or 0) if int(product_row.get("has_competitor_data", 0) or 0) else None,
        sale_ratio=float(product_row.get("competitors_on_sale_ratio", 0.0) or 0.0),
        has_competitor_data=int(product_row.get("has_competitor_data", 0) or 0),
    )

    peak_stock = infer_peak_stock(product_row, current_stock, len(weeks), market_pressure)
    inventory_curve = build_inventory_curve(product_row, weeks, peak_stock, current_stock, market_pressure)
    competitor_history = build_competitor_history(product_row, weeks)
    days_since_last_discount, days_at_current_price, discount_depth_last_30d = build_discount_schedule(
        product_row=product_row,
        weeks=weeks,
        market_pressure=market_pressure,
        peak_stock=peak_stock,
        current_stock=current_stock,
    )

    current_age_days = infer_current_age_days(product_row)
    latest_idx = len(weeks) - 1

    rows: list[dict[str, object]] = []
    for idx, week_ts in enumerate(weeks):
        total_qty = int(inventory_curve[idx])
        category = str(product_row.get("system_category", "other") or "other")
        seasonality = round(get_seasonal_multiplier(week_ts, category), 3)
        category_boost = round(get_category_boost(week_ts, category), 3)
        event_name, event_score = get_event_score(week_ts)
        days_since_launch = max(14, current_age_days - (latest_idx - idx) * 7)
        sell_through_proxy = round(clamp((peak_stock - total_qty) / max(peak_stock, 1), 0.0, 0.995), 4)

        state_row = {
            "state_id": f"{product_row['sku_id']}|{week_ts.date().isoformat()}",
            "sku_id": product_row["sku_id"],
            "product_key": product_row.get("product_key"),
            "brand": product_row.get("brand"),
            "style_code": product_row.get("style_code"),
            "product_name": product_row.get("product_name"),
            "category": category,
            "gender": product_row.get("gender"),
            "collection_type": product_row.get("collection_type"),
            "week_of": week_ts.date().isoformat(),
            "retail_price_usd": retail_price,
            "cost_price_usd": cost_price,
            "base_retail_price_usd": retail_price,
            "inventory_initial_stock": int(round(float(product_row.get("inventory_initial_stock", peak_stock) or peak_stock))),
            "simulated_peak_stock": int(peak_stock),
            "total_qty": total_qty,
            "inventory_value_at_cost": round(total_qty * cost_price, 2),
            "inventory_value_at_retail": round(total_qty * retail_price, 2),
            "days_since_launch": int(days_since_launch),
            "launch_age_days": int(days_since_launch),
            "days_since_last_discount": int(days_since_last_discount[idx]),
            "days_at_current_price": int(days_at_current_price[idx]),
            "discount_depth_last_30d_proxy": float(discount_depth_last_30d[idx]),
            "seasonality_alignment_score": seasonality,
            "seasonality_score": seasonality,
            "category_seasonal_boost": category_boost,
            "event_name": event_name,
            "event_proximity_score": round(event_score, 3),
            "sell_through_proxy": sell_through_proxy,
            "inventory_pressure_index": round(total_qty / max(peak_stock, 1), 4),
            "market_pressure_index": round(market_pressure, 4),
            "identity_source": "real_catalog_product",
        }
        state_row.update(competitor_history[idx])
        rows.append(state_row)

    return rows


def load_inputs() -> pd.DataFrame:
    products = normalize_columns(pd.read_csv(PRODUCTS_PATH))
    inventory = normalize_columns(pd.read_csv(INVENTORY_PATH))

    ensure_columns(products, EXPECTED_PRODUCT_COLUMNS, "products.csv")
    ensure_columns(inventory, EXPECTED_INVENTORY_COLUMNS, "inventory.csv")

    products = products.copy()
    inventory = inventory.rename(columns={"initial_stock": "inventory_initial_stock"})
    merged = products.merge(
        inventory[["sku_id", "current_stock", "inventory_initial_stock"]],
        on="sku_id",
        how="left",
        validate="one_to_one",
    )

    if COMPETITOR_CLEAN_PATH.exists():
        competitor = normalize_columns(pd.read_csv(COMPETITOR_CLEAN_PATH))
        ensure_columns(competitor, EXPECTED_COMPETITOR_COLUMNS, "competitor_prices_clean.csv")
        merged = merged.merge(
            competitor[
                [
                    "product_key",
                    "competitor_min_price_usd",
                    "competitor_avg_price_usd",
                    "competitor_max_price_usd",
                    "num_competitors",
                    "competitors_on_sale_count",
                    "competitors_on_sale_ratio",
                    "competitors_in_stock_count",
                    "competitors_out_of_stock_count",
                    "has_competitor_data",
                    "data_freshness_hours",
                ]
            ],
            on="product_key",
            how="left",
            validate="one_to_one",
        )
    else:
        print(f"WARNING: {COMPETITOR_CLEAN_PATH} not found. Historical states will be generated without competitor coverage.")

    merged["current_stock"] = merged["current_stock"].fillna(merged["inventory_initial_stock"]).fillna(merged["initial_stock"]).fillna(0)
    merged["inventory_initial_stock"] = merged["inventory_initial_stock"].fillna(merged["initial_stock"]).fillna(merged["current_stock"]).fillna(0)

    merged["has_competitor_data"] = merged["has_competitor_data"].fillna(0).astype(int)
    numeric_cols = [
        "competitor_min_price_usd",
        "competitor_avg_price_usd",
        "competitor_max_price_usd",
        "num_competitors",
        "competitors_on_sale_count",
        "competitors_on_sale_ratio",
        "competitors_in_stock_count",
        "competitors_out_of_stock_count",
        "data_freshness_hours",
    ]
    for col in numeric_cols:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
    return merged


def validate_historical_states(states_df: pd.DataFrame, products_df: pd.DataFrame, num_weeks: int) -> None:
    product_skus = set(products_df["sku_id"])
    product_brands = set(products_df["brand"].dropna().astype(str))
    product_styles = set(products_df["style_code"].dropna().astype(str))

    if not set(states_df["sku_id"]).issubset(product_skus):
        raise ValueError("Historical states contain sku_id values not found in products.csv.")

    generated_styles = set(states_df["style_code"].dropna().astype(str))
    if not generated_styles.issubset(product_styles):
        raise ValueError("Historical states contain style_code values not found in products.csv.")

    if not set(states_df["brand"].dropna().astype(str)).issubset(product_brands):
        raise ValueError("Historical states contain brand values not found in products.csv.")

    if states_df.duplicated(subset=["sku_id", "week_of"]).any():
        raise ValueError("Duplicate sku_id + week_of rows found in historical states.")

    expected_rows = len(products_df) * num_weeks
    if len(states_df) != expected_rows:
        raise ValueError(f"Expected {expected_rows} historical rows but found {len(states_df)}.")

    if (states_df["total_qty"] < 0).any():
        raise ValueError("Historical states contain negative inventory.")

    price_cols = ["competitor_min_price_usd", "competitor_avg_price_usd", "competitor_max_price_usd"]
    for col in price_cols:
        negatives = states_df[col].dropna() < 0
        if negatives.any():
            raise ValueError(f"Historical states contain negative values in '{col}'.")

    if not states_df["seasonality_score"].between(0.5, 2.0).all():
        raise ValueError("Historical states contain seasonality scores outside the expected range [0.5, 2.0].")


def print_summary(states_df: pd.DataFrame, products_df: pd.DataFrame, num_weeks: int) -> None:
    product_coverage = (
        states_df.groupby("sku_id")["has_competitor_data"].max().mean() * 100.0
        if not states_df.empty
        else 0.0
    )
    unique_weeks = states_df["week_of"].nunique()

    print("\n" + "=" * 76)
    print("HISTORICAL PRODUCT-STATE SUMMARY")
    print("=" * 76)
    print("Every row in this file maps back to a real product from products.csv.")
    print("Only time-varying state fields were simulated between weeks.")
    print("")
    print(f"Products used:                 {len(products_df)}")
    print(f"Weeks generated:              {num_weeks}")
    print(f"Unique weeks present:         {unique_weeks}")
    print(f"Total historical rows:        {len(states_df)}")
    print(f"Products with competitor data:{product_coverage:6.2f}%")
    print(f"Output file:                  {OUTPUT_PATH}")
    print("")
    print("Sample historical rows:")
    print(states_df.head(6).to_string(index=False))
    print("=" * 76)
    print("Next steps:")
    print("  1. py services/decision_intelligence/features/clean_competitors.py")
    print("  2. py services/decision_intelligence/features/generate_historical_states.py")
    print("  3. py -m services.decision_intelligence.features.engineer")
    print("  4. then proceed to labeling/training")
    print("=" * 76)


def generate_historical_states(num_weeks: int = DEFAULT_WEEKS, anchor_date: date | None = None) -> pd.DataFrame:
    if num_weeks < 2:
        raise ValueError("num_weeks must be at least 2.")

    merged = load_inputs()
    weeks = week_starts(num_weeks, anchor_date=anchor_date)

    rows: list[dict[str, object]] = []
    for _, product_row in merged.iterrows():
        rows.extend(simulate_product_history(product_row, weeks))

    states_df = pd.DataFrame(rows)
    states_df = states_df.sort_values(["sku_id", "week_of"]).reset_index(drop=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    states_df.to_csv(OUTPUT_PATH, index=False)

    validate_historical_states(states_df, merged, num_weeks)
    print_summary(states_df, merged, num_weeks)
    return states_df


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate historical product-week states for IE2 training.")
    parser.add_argument("--weeks", type=int, default=DEFAULT_WEEKS, help="Number of weekly observations to generate per real product.")
    parser.add_argument("--anchor-date", type=str, default=None, help="Optional ISO date used as the latest week anchor.")
    args = parser.parse_args()

    anchor_date = date.fromisoformat(args.anchor_date) if args.anchor_date else None
    generate_historical_states(num_weeks=args.weeks, anchor_date=anchor_date)


if __name__ == "__main__":
    main()
