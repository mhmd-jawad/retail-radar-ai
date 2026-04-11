"""
Feature Engineering Pipeline — IE2 Decision Intelligence.

Computes 26 features per SKU from the real data CSVs.
Output is a features.csv file and a list of dicts.

Features are grouped into 6 categories:
  1. Inventory (5) — stock health, days of supply, turnover signals
  2. Pricing & Margin (5) — current margin, discount history, price staleness
  3. Competitor (5) — market position, pricing pressure, OOS count
  4. Lifecycle (4) — product age, sell-through, category maturity
  5. Seasonality (4) — calendar alignment, upcoming events
  6. Financial (3) — cash pressure, inventory capital intensity

NOTE: Traffic features (page_views, conversion_rate) are excluded.
      They require POS integration — add in v2 when real data exists.
      This is documented as v2: requires POS integration below.

Usage:
    python -m services.decision_intelligence.features.engineer

    or:

    from services.decision_intelligence.features.engineer import build_features
    features = build_features(data_dir="data/real")
"""

import csv
import json
import statistics
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = ROOT / "data" / "real"
DEFAULT_OUTPUT = ROOT / "data" / "features" / "features.csv"

# ── Sentinel / fallback constants ────────────────────────────────────────────
SENTINEL_DAYS_NO_DISCOUNT = 999   # no recent discount data available
SENTINEL_DAYS_AT_PRICE = 30       # assumed stable price (v2: from POS logs)
DEFAULT_DAYS_SINCE_LAUNCH = 180   # conservative: assume mid-season product
DEFAULT_INVENTORY_INTENSITY = 0.70  # typical for multi-brand retail stores
DEFAULT_INVENTORY_AT_COST = 176_000  # fallback when financial_profile is incomplete
DEFAULT_TOTAL_ASSETS = 214_000      # fallback when financial_profile is incomplete


# ── Category velocity multipliers (calibrated from demand model) ──────────────
CATEGORY_VELOCITY = {
    "footwear": 0.80,
    "football_boots": 0.70,
    "apparel": 1.15,
    "sportswear": 1.0,
    "swimwear": 0.60,
    "accessories": 1.30,
    "kids": 0.90,
    "lifestyle": 0.85,
    "other": 0.80,
}

# ── Lebanon seasonal multipliers (month → demand multiplier) ──────────────────
SEASONAL_MULTIPLIERS = {
    1: 0.70, 2: 0.80, 3: 0.90, 4: 1.10, 5: 1.15, 6: 1.20,
    7: 1.10, 8: 1.30, 9: 1.20, 10: 0.90, 11: 0.85, 12: 0.90,
}

CATEGORY_SEASONAL_BOOST = {
    "swimwear":      {5: 0.3, 6: 0.5, 7: 0.5, 8: 0.3},
    "football_boots": {8: 0.3, 9: 0.4, 10: 0.2},
    "kids":          {8: 0.4, 9: 0.3},
}

# ── Lebanon retail events (month → event proximity score, 0-1) ───────────────
EVENT_WINDOWS = {
    8: ("back_to_school", 0.9),
    9: ("back_to_school", 0.7),
    4: ("eid_al_fitr", 0.8),
    3: ("eid_al_fitr", 0.5),
    12: ("holiday_gifting", 0.7),
    11: ("pre_holiday", 0.5),
}

# ── Brand tier encoding ────────────────────────────────────────────────────────
BRAND_TIER = {
    "Adidas": "tier1", "Nike": "tier1", "New Balance": "tier1",
    "ON": "tier1", "The North Face": "tier1",
    "Puma": "tier2", "ASICS": "tier2", "Crocs": "tier2",
    "Billabong": "tier3", "Bogner": "tier3", "Babolat": "tier3",
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


def _get_seasonal_multiplier(month: int, category: str | None = None) -> float:
    base = SEASONAL_MULTIPLIERS.get(month, 1.0)
    if category and category in CATEGORY_SEASONAL_BOOST:
        boost = CATEGORY_SEASONAL_BOOST[category].get(month, 0)
        return base + boost
    return base


def _estimate_daily_demand(units_on_hand: float, category: str,
                           num_competitors: int, retail_price: float) -> float:
    """Estimate daily demand using stock-based calibration (same logic as inventory.py)."""
    if units_on_hand <= 0:
        return 0.02  # minimum floor: near-zero stock → minimal demand signal
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


def build_competitor_index(competitor_rows: list[dict]) -> dict[str, list[dict]]:
    """Group competitor price rows by product_key (or sku_id)."""
    index: dict[str, list[dict]] = {}
    for row in competitor_rows:
        key = row.get("product_key") or row.get("sku_id", "")
        if key:
            index.setdefault(key, []).append(row)
    return index


def compute_competitor_features(sku_id: str, our_price: float,
                                 competitor_index: dict) -> dict:
    """
    Compute 5 competitor features for a single SKU.

    Features:
        price_gap_pct           — (our_price - market_min) / our_price
        competitors_on_sale     — count of competitors discounting
        competitors_out_of_stock — count OOS
        market_position         — premium/above_market/at_market/below_market/deep_value
        competitor_confidence   — 1.0 always (data is from last scrape night)
    """
    rows = competitor_index.get(sku_id, [])

    if not rows:
        return {
            "price_gap_pct": 0.0,
            "competitors_on_sale": 0,
            "competitors_out_of_stock": 0,
            "num_competitors": 0,
            "market_position": "at_market",
            "competitor_confidence": 0.0,  # zero — no competitor data available
        }

    valid_prices = []
    on_sale_count = 0
    oos_count = 0

    for r in rows:
        try:
            price = float(r.get("competitor_price_usd", 0) or 0)
        except (ValueError, TypeError):
            price = 0
        if price > 0:
            valid_prices.append(price)
        on_sale = str(r.get("on_sale", "")).strip().lower() in ("true", "1", "yes")
        if on_sale:
            on_sale_count += 1
        oos = str(r.get("availability", "")).strip().lower() in ("out_of_stock", "oos", "unavailable")
        if oos:
            oos_count += 1

    if not valid_prices:
        return {
            "price_gap_pct": 0.0,
            "competitors_on_sale": on_sale_count,
            "competitors_out_of_stock": oos_count,
            "num_competitors": len(rows),
            "market_position": "at_market",
            "competitor_confidence": 0.4,
        }

    market_min = min(valid_prices)
    price_gap = (our_price - market_min) / our_price if our_price > 0 else 0.0

    # Market position using same thresholds as competitor.py
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

    return {
        "price_gap_pct": round(price_gap, 4),
        "competitors_on_sale": on_sale_count,
        "competitors_out_of_stock": oos_count,
        "num_competitors": len(valid_prices),
        "market_position": position,
        "competitor_confidence": 1.0,
    }


def compute_sku_features(prod: dict, inv_row: dict, competitor_index: dict,
                          financial_profile: dict, today: date) -> dict:
    """
    Compute all 26 features for a single SKU.

    Returns a flat dict ready to be written as a CSV row.
    All features are numeric or short string categoricals
    (CatBoost handles categoricals natively).
    """
    sku_id = prod.get("sku_id", "")
    category = prod.get("system_category", inv_row.get("system_category", "other"))
    brand = prod.get("brand", "Unknown")
    retail_price = float(prod.get("retail_price_usd", inv_row.get("retail_price_usd", 100)) or 100)
    cost_price = float(prod.get("cost_price_usd", inv_row.get("cost_price_usd", 50)) or 50)
    current_stock = int(inv_row.get("current_stock", inv_row.get("initial_stock", 0)) or 0)
    current_month = today.month

    # ── Pricing & Margin (5 features) ────────────────────────────────────────
    margin_pct = round((1 - cost_price / retail_price) * 100, 2) if retail_price > 0 else 0.0
    # v2: discount_depth_last_30d, days_since_last_discount, days_at_current_price
    # require transaction history — not available yet; set to safe defaults
    discount_depth_last_30d = 0.0
    days_since_last_discount = SENTINEL_DAYS_NO_DISCOUNT
    days_at_current_price = SENTINEL_DAYS_AT_PRICE

    # ── Inventory (5 features) ────────────────────────────────────────────────
    comp_feats = compute_competitor_features(sku_id, retail_price, competitor_index)
    num_competitors = comp_feats["num_competitors"]

    avg_daily_demand = _estimate_daily_demand(
        current_stock, category, num_competitors, retail_price
    )
    days_of_supply = round(current_stock / avg_daily_demand, 1) if avg_daily_demand > 0 else 9999.0
    stock_coverage_ratio = round(days_of_supply / 30, 2)  # normalized to months
    stockout_risk = 1 if days_of_supply < 14 else 0

    # v2: inventory_vs_median requires category median from all 350 SKUs;
    # computed as a post-pass below once all SKUs are processed
    inventory_vs_median = 1.0  # placeholder — corrected in post-pass

    # ── Lifecycle (4 features) ────────────────────────────────────────────────
    # days_since_launch: use first_seen_date if available, else 180 (assume mid-life)
    first_seen_str = prod.get("first_seen_date") or inv_row.get("first_seen_date", "")
    if first_seen_str:
        try:
            first_seen = date.fromisoformat(str(first_seen_str)[:10])
            days_since_launch = (today - first_seen).days
        except ValueError:
            days_since_launch = 180
    else:
        days_since_launch = DEFAULT_DAYS_SINCE_LAUNCH

    # season_sell_through_pct: no actual sales data yet
    # Estimated as 1 - (current_stock / assumed_opening_stock)
    # Opening stock assumed from inventory.csv initial_stock column if present
    initial_stock = float(inv_row.get("initial_stock", current_stock) or current_stock)
    season_sell_through_pct = round(
        1 - (current_stock / initial_stock), 4
    ) if initial_stock > 0 else 0.0

    brand_tier = BRAND_TIER.get(brand, "tier2")

    # ── Seasonality (4 features) ──────────────────────────────────────────────
    seasonality_score = _get_seasonal_multiplier(current_month, category)
    category_seasonal_score = CATEGORY_SEASONAL_BOOST.get(category, {}).get(current_month, 0.0)
    event_name, event_proximity_score = EVENT_WINDOWS.get(current_month, ("none", 0.0))
    next_month = (current_month % 12) + 1
    next_month_seasonality = _get_seasonal_multiplier(next_month, category)

    # ── Financial (3 features) ────────────────────────────────────────────────
    cash_runway = financial_profile.get("cashflow_summary", {}).get("cash_runway_months", 3.0)
    cash_tight = 1 if cash_runway < 2.5 else 0
    inventory_at_cost = financial_profile.get("inventory_summary", {}).get("total_cost_usd", DEFAULT_INVENTORY_AT_COST)
    total_assets = financial_profile.get("balance_sheet_summary", {}).get("total_assets_usd", DEFAULT_TOTAL_ASSETS)
    inventory_intensity = round(inventory_at_cost / total_assets, 4) if total_assets > 0 else DEFAULT_INVENTORY_INTENSITY

    return {
        # Identity (not features — used for joining)
        "sku_id": sku_id,
        "brand": brand,
        "category": category,
        "product_name": prod.get("product_name", inv_row.get("product_name", "")),
        "week_of": today.isoformat(),

        # ── Inventory (5) ────────────────────────────────
        "days_of_supply": days_of_supply,
        "stock_coverage_ratio": stock_coverage_ratio,
        "stockout_risk": stockout_risk,
        "total_qty": current_stock,
        "inventory_vs_median": inventory_vs_median,  # corrected in post-pass

        # ── Pricing & Margin (5) ─────────────────────────
        "current_margin_pct": margin_pct,
        "discount_depth_last_30d": discount_depth_last_30d,  # v2
        "days_since_last_discount": days_since_last_discount,  # v2
        "days_at_current_price": days_at_current_price,        # v2
        "retail_price_usd": retail_price,

        # ── Competitor (5) ───────────────────────────────
        "price_gap_pct": comp_feats["price_gap_pct"],
        "competitors_on_sale": comp_feats["competitors_on_sale"],
        "competitors_out_of_stock": comp_feats["competitors_out_of_stock"],
        "num_competitors": comp_feats["num_competitors"],
        "market_position": comp_feats["market_position"],    # categorical

        # ── Lifecycle (4) ────────────────────────────────
        "days_since_launch": days_since_launch,
        "season_sell_through_pct": season_sell_through_pct,
        "brand_tier": brand_tier,                            # categorical
        "cost_price_usd": cost_price,

        # ── Seasonality (4) ──────────────────────────────
        "seasonality_score": round(seasonality_score, 3),
        "category_seasonal_boost": round(category_seasonal_score, 3),
        "event_proximity_score": round(event_proximity_score, 3),
        "next_month_seasonality": round(next_month_seasonality, 3),

        # ── Financial (3) ────────────────────────────────
        "cash_runway_months": round(cash_runway, 2),
        "cash_tight": cash_tight,
        "inventory_intensity": inventory_intensity,

        # v2 TODO — requires POS integration:
        # "units_sold_7d", "units_sold_30d", "velocity_ratio",
        # "revenue_7d", "revenue_trend_slope",
        # "page_views_7d", "conversion_rate_7d", "add_to_cart_rate_7d"
    }


def apply_inventory_vs_median_correction(all_features: list[dict]) -> list[dict]:
    """
    Post-pass: correct inventory_vs_median for every SKU using
    the actual median total_qty within each category.
    """
    from collections import defaultdict

    category_qtys: dict[str, list[float]] = defaultdict(list)
    for f in all_features:
        category_qtys[f["category"]].append(float(f["total_qty"]))

    category_medians = {
        cat: statistics.median(qtys) for cat, qtys in category_qtys.items() if qtys
    }

    for f in all_features:
        median = category_medians.get(f["category"], 1.0)
        f["inventory_vs_median"] = round(f["total_qty"] / median, 4) if median > 0 else 1.0

    return all_features


def build_features(data_dir: str | Path | None = None,
                   output_path: str | Path | None = None,
                   today: date | None = None) -> list[dict]:
    """
    Build the full feature matrix from real CSVs.

    Args:
        data_dir: path to data/real/ directory (default: auto-detect)
        output_path: where to write features.csv (default: data/features/features.csv)
        today: reference date for age calculations (default: date.today())

    Returns:
        list of dicts, one per SKU
    """
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    output_path = Path(output_path) if output_path else DEFAULT_OUTPUT
    today = today or date.today()

    print("Building feature matrix...")

    products = _load_csv(data_dir / "products.csv")
    inventory = _load_csv(data_dir / "inventory.csv")
    competitor_prices = _load_csv(data_dir / "competitor_prices.csv")
    financial_profile = _load_json(data_dir / "financial_profile.json")

    print(f"  Loaded {len(products)} products, {len(inventory)} inventory rows, "
          f"{len(competitor_prices)} competitor price records")

    # Build lookup maps
    inv_map = {r["sku_id"]: r for r in inventory}
    competitor_index = build_competitor_index(competitor_prices)

    all_features = []
    skipped = 0

    for prod in products:
        sku_id = prod.get("sku_id", "")
        inv_row = inv_map.get(sku_id)

        if not inv_row:
            skipped += 1
            continue

        features = compute_sku_features(prod, inv_row, competitor_index,
                                        financial_profile, today)
        all_features.append(features)

    if skipped:
        print(f"  Skipped {skipped} products with no inventory row")

    # Post-pass: correct inventory_vs_median
    all_features = apply_inventory_vs_median_correction(all_features)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if all_features:
        fieldnames = list(all_features[0].keys())
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_features)
        print(f"  Wrote {len(all_features)} rows → {output_path}")

    return all_features


def _print_summary(features: list[dict]) -> None:
    dos_values = [f["days_of_supply"] for f in features if f["days_of_supply"] < 9999]
    margin_values = [f["current_margin_pct"] for f in features]
    position_counts: dict[str, int] = {}
    for f in features:
        pos = f["market_position"]
        position_counts[pos] = position_counts.get(pos, 0) + 1

    print("\n" + "=" * 60)
    print("FEATURE MATRIX SUMMARY")
    print("=" * 60)
    print(f"Total SKUs:         {len(features)}")
    print(f"Features per SKU:   {len(features[0]) - 4}")  # subtract identity fields
    if dos_values:
        print(f"DOS range:          {min(dos_values):.0f} - {max(dos_values):.0f} days "
              f"(median: {statistics.median(dos_values):.0f})")
    if margin_values:
        print(f"Margin range:       {min(margin_values):.1f}% - {max(margin_values):.1f}% "
              f"(avg: {statistics.mean(margin_values):.1f}%)")
    print("Market positions:")
    for pos, cnt in sorted(position_counts.items(), key=lambda x: -x[1]):
        print(f"  {pos:<20} {cnt}")
    stockout_risk = sum(1 for f in features if f["stockout_risk"] == 1)
    print(f"Stockout risk SKUs: {stockout_risk}")
    print("=" * 60)


if __name__ == "__main__":
    features = build_features()
    _print_summary(features)
