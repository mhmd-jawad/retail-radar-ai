"""
Feature Validation — IE2 Decision Intelligence.

Validates the feature matrix produced by engineer.py using pandera.
Checks ranges, null rates, and type correctness before ML training or inference.

Install: pip install pandera
"""

from __future__ import annotations

import csv
from pathlib import Path

# --- pandera import with graceful degradation ---
# pandera is only required for validation runs, not for inference.
try:
    import pandera as pa
    from pandera import Column, DataFrameSchema, Check
    PANDERA_AVAILABLE = True
except ImportError:
    PANDERA_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FEATURES_PATH = ROOT / "data" / "features" / "features.csv"

# Feature range definitions: {column: (min, max)}
FEATURE_RANGES = {
    "days_of_supply": (0, 730),        # max ~2 years; above that is clearly stale data
    "stock_coverage_ratio": (0, 400),
    "stockout_risk": (0, 1),
    "total_qty": (0, 10000),
    "inventory_vs_median": (0, 50),
    "current_margin_pct": (-100, 100),
    "discount_depth_last_30d": (0, 1),
    "days_since_last_discount": (0, 3650),   # sentinel 999 fits within 10y
    "days_at_current_price": (0, 3650),
    "retail_price_usd": (0, 10000),
    "price_gap_pct": (-2, 2),
    "competitors_on_sale": (0, 20),
    "competitors_out_of_stock": (0, 20),
    "num_competitors": (0, 20),
    "days_since_launch": (0, 3650),
    "season_sell_through_pct": (0, 1),
    "cost_price_usd": (0, 10000),
    "seasonality_score": (0.5, 3.0),
    "category_seasonal_boost": (0, 1),
    "event_proximity_score": (0, 1),
    "next_month_seasonality": (0.5, 3.0),
    "cash_runway_months": (0, 120),
    "cash_tight": (0, 1),
    "inventory_intensity": (0, 1),
}

REQUIRED_COLUMNS = list(FEATURE_RANGES.keys()) + [
    "sku_id", "brand", "category", "market_position", "brand_tier"
]

CATEGORICAL_COLUMNS = {
    "market_position": {"premium", "above_market", "at_market", "below_market", "deep_value"},
    "brand_tier": {"tier1", "tier2", "tier3"},
}

MAX_NULL_RATE = 0.05  # allow at most 5% nulls per column


def validate_features(features: list[dict]) -> dict:
    """
    Validate a list of feature dicts.

    Returns:
        {
            "passed": bool,
            "row_count": int,
            "errors": list[str],
            "warnings": list[str],
        }
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not features:
        return {"passed": False, "row_count": 0,
                "errors": ["Feature matrix is empty"], "warnings": []}

    # Check required columns exist
    first = features[0]
    for col in REQUIRED_COLUMNS:
        if col not in first:
            errors.append(f"Missing required column: {col}")

    if errors:
        return {"passed": False, "row_count": len(features), "errors": errors, "warnings": warnings}

    # Check ranges and nulls
    for col, (lo, hi) in FEATURE_RANGES.items():
        null_count = 0
        out_of_range = 0
        for row in features:
            val = row.get(col)
            if val is None or val == "":
                null_count += 1
                continue
            try:
                v = float(val)
                if not (lo <= v <= hi):
                    out_of_range += 1
            except (ValueError, TypeError):
                errors.append(f"Column {col}: non-numeric value '{val}'")

        null_rate = null_count / len(features)
        if null_rate > MAX_NULL_RATE:
            errors.append(f"Column {col}: null rate {null_rate:.1%} exceeds {MAX_NULL_RATE:.0%} threshold")
        elif null_rate > 0:
            warnings.append(f"Column {col}: {null_count} null values ({null_rate:.1%})")

        if out_of_range > 0:
            warnings.append(f"Column {col}: {out_of_range} values outside [{lo}, {hi}]")

    # Check categorical values
    for col, valid_values in CATEGORICAL_COLUMNS.items():
        invalid = set()
        for row in features:
            val = row.get(col, "")
            if val and val not in valid_values:
                invalid.add(val)
        if invalid:
            errors.append(f"Column {col}: unexpected values {invalid} (allowed: {valid_values})")

    # Check label distribution if labels present
    if "label" in features[0]:
        from collections import Counter
        counts = Counter(row.get("label") for row in features)
        total = len(features)
        for label, cnt in counts.items():
            pct = cnt / total
            if pct < 0.05:
                warnings.append(f"Label '{label}': only {pct:.1%} of rows — very low representation")
            if pct > 0.70:
                warnings.append(f"Label '{label}': {pct:.1%} of rows — highly imbalanced")

    passed = len(errors) == 0
    return {
        "passed": passed,
        "row_count": len(features),
        "errors": errors,
        "warnings": warnings,
    }


def validate_from_csv(path: Path | None = None) -> dict:
    """Load features.csv and validate it."""
    path = path or DEFAULT_FEATURES_PATH
    if not path.exists():
        return {"passed": False, "row_count": 0,
                "errors": [f"Features file not found: {path}"], "warnings": []}

    with open(path, encoding="utf-8") as f:
        features = list(csv.DictReader(f))

    return validate_features(features)


if __name__ == "__main__":
    result = validate_from_csv()
    status = "✓ PASSED" if result["passed"] else "✗ FAILED"
    print(f"\nValidation: {status} ({result['row_count']} rows)")
    if result["errors"]:
        print("\nErrors:")
        for e in result["errors"]:
            print(f"  ✗ {e}")
    if result["warnings"]:
        print("\nWarnings:")
        for w in result["warnings"]:
            print(f"  ⚠ {w}")
    if result["passed"] and not result["warnings"]:
        print("  All checks passed, no warnings.")
