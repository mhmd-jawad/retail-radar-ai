"""
Clean competitor scrape output into ML-ready competitor datasets.

This script uses the scrape output as the source of truth and produces:
  - data/real/competitor_prices_clean_rows.csv
  - data/real/competitor_prices_clean.csv

Run from the repo root:
    py services/decision_intelligence/features/clean_competitors.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PRODUCTS_PATH = ROOT / "data" / "real" / "products.csv"
SCRAPED_PATH = ROOT / "scraping" / "data" / "output" / "combined" / "all_shops_full_records.csv"
OUTPUT_ROWS_PATH = ROOT / "data" / "real" / "competitor_prices_clean_rows.csv"
OUTPUT_AGG_PATH = ROOT / "data" / "real" / "competitor_prices_clean.csv"

LBP_TO_USD = 1 / 90_000

RELEVANT_SCRAPE_COLUMNS = [
    "brand_name",
    "style_code",
    "competitor_name",
    "product_name",
    "competitor_price",
    "competitor_sale_price",
    "discount_pct",
    "is_on_sale",
    "availability",
    "currency",
    "source_url",
    "scraped_at",
    "data_valid",
]

REQUIRED_SCRAPE_COLUMNS = {
    "brand_name",
    "style_code",
    "competitor_name",
    "competitor_price",
    "currency",
}

PRODUCT_ID_CANDIDATES = ("sku_id", "product_id", "id")
PRODUCT_BRAND_CANDIDATES = ("brand", "brand_name")
PRODUCT_STYLE_CANDIDATES = ("style_code", "style", "model_code", "article_code")
PRODUCT_PRICE_CANDIDATES = ("retail_price_usd", "retail_price", "price_usd", "price")
PRODUCT_NAME_CANDIDATES = ("product_name", "name", "title")

ROW_OUTPUT_COLUMNS = [
    "sku_id",
    "product_key",
    "brand",
    "style_code",
    "catalog_product_name",
    "product_name",
    "competitor_name",
    "competitor_price",
    "competitor_sale_price",
    "discount_pct",
    "is_on_sale",
    "availability",
    "currency",
    "competitor_price_usd",
    "competitor_sale_price_usd",
    "effective_competitor_price_usd",
    "source_url",
    "scraped_at",
]


@dataclass(frozen=True)
class ProductSchema:
    product_id: str
    brand: str
    style_code: str
    retail_price: str | None
    product_name: str | None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        str(col).strip().lower().replace(" ", "_")
        for col in df.columns
    ]
    return df


def choose_column(df: pd.DataFrame, candidates: tuple[str, ...], label: str, required: bool = True) -> str | None:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    if required:
        raise ValueError(
            f"Could not find a {label} column. Expected one of: {', '.join(candidates)}. "
            f"Available columns: {', '.join(df.columns)}"
        )
    return None


def inspect_product_schema(products_df: pd.DataFrame) -> ProductSchema:
    return ProductSchema(
        product_id=choose_column(products_df, PRODUCT_ID_CANDIDATES, "product identifier"),
        brand=choose_column(products_df, PRODUCT_BRAND_CANDIDATES, "product brand"),
        style_code=choose_column(products_df, PRODUCT_STYLE_CANDIDATES, "product style_code"),
        retail_price=choose_column(products_df, PRODUCT_PRICE_CANDIDATES, "retail price", required=False),
        product_name=choose_column(products_df, PRODUCT_NAME_CANDIDATES, "product name", required=False),
    )


def normalize_string(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_brand(value: object) -> str | None:
    text = normalize_string(value)
    return text.upper() if text else None


def normalize_style_code(value: object) -> str | None:
    text = normalize_string(value)
    if not text:
        return None
    return re.sub(r"\s+", "", text.upper())


def normalize_competitor_name(value: object) -> str | None:
    text = normalize_string(value)
    if not text:
        return None
    text = text.lower()
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or None


def normalize_availability(value: object) -> str:
    text = normalize_string(value)
    if not text:
        return "UNKNOWN"

    normalized = re.sub(r"[\s\-]+", "_", text.lower())
    if normalized in {"in_stock", "available", "instock"}:
        return "IN_STOCK"
    if normalized in {"low_stock", "limited_stock", "few_left", "last_units", "last_few"}:
        return "LOW_STOCK"
    if normalized in {"out_of_stock", "oos", "sold_out", "unavailable"}:
        return "OUT_OF_STOCK"
    return "UNKNOWN"


def parse_boolean(value: object) -> bool | None:
    if pd.isna(value):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return None


def to_numeric(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        .str.replace(r"[^0-9.\-]+", "", regex=True)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_discount_pct(series: pd.Series) -> pd.Series:
    """
    Keep discounts as decimal ratios.

    Examples:
      20   -> 0.20
      0.20 -> 0.20
      5%   -> 0.05
    """
    numeric = to_numeric(series)
    numeric = numeric.mask(numeric < 0)
    return numeric.where(numeric <= 1, numeric / 100.0)


def build_product_key(brand_series: pd.Series, style_series: pd.Series) -> pd.Series:
    key = brand_series.fillna("") + "|" + style_series.fillna("")
    key = key.where(brand_series.notna() & style_series.notna())
    return key


def ensure_required_columns(df: pd.DataFrame, required_columns: set[str], dataset_name: str) -> None:
    missing = sorted(required_columns - set(df.columns))
    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns: {', '.join(missing)}. "
            f"Available columns: {', '.join(df.columns)}"
        )


def load_products() -> tuple[pd.DataFrame, ProductSchema]:
    if not PRODUCTS_PATH.exists():
        raise FileNotFoundError(f"Products file not found: {PRODUCTS_PATH}")

    products_df = normalize_columns(pd.read_csv(PRODUCTS_PATH))
    schema = inspect_product_schema(products_df)

    products_clean = products_df.copy()
    products_clean["brand_normalized"] = products_clean[schema.brand].map(normalize_brand)
    products_clean["style_code_normalized"] = products_clean[schema.style_code].map(normalize_style_code)
    products_clean["product_key"] = build_product_key(
        products_clean["brand_normalized"],
        products_clean["style_code_normalized"],
    )

    if products_clean[schema.product_id].duplicated().any():
        dup_count = int(products_clean[schema.product_id].duplicated().sum())
        raise ValueError(f"products.csv contains {dup_count} duplicate product identifiers in '{schema.product_id}'.")

    non_null_product_keys = products_clean["product_key"].dropna()
    if non_null_product_keys.duplicated().any():
        dup_keys = non_null_product_keys[non_null_product_keys.duplicated()]
        sample = ", ".join(dup_keys.astype(str).head(5).tolist())
        raise ValueError(f"products.csv contains duplicate product_key values. Sample duplicates: {sample}")

    selected_columns = {
        schema.product_id: "sku_id",
        schema.brand: "catalog_brand",
        schema.style_code: "catalog_style_code",
    }
    if schema.retail_price:
        selected_columns[schema.retail_price] = "retail_price_usd"
    if schema.product_name:
        selected_columns[schema.product_name] = "catalog_product_name"

    products_clean = products_clean[list(selected_columns.keys()) + ["brand_normalized", "style_code_normalized", "product_key"]]
    products_clean = products_clean.rename(columns=selected_columns)
    return products_clean, schema


def load_scraped_competitors() -> pd.DataFrame:
    if not SCRAPED_PATH.exists():
        raise FileNotFoundError(f"Scraped competitor file not found: {SCRAPED_PATH}")

    scraped_df = normalize_columns(pd.read_csv(SCRAPED_PATH))
    ensure_required_columns(scraped_df, REQUIRED_SCRAPE_COLUMNS, "all_shops_full_records.csv")

    keep_columns = [col for col in RELEVANT_SCRAPE_COLUMNS if col in scraped_df.columns]
    scraped_df = scraped_df[keep_columns].copy()

    for optional_col in RELEVANT_SCRAPE_COLUMNS:
        if optional_col not in scraped_df.columns:
            scraped_df[optional_col] = pd.NA

    return scraped_df


def clean_scraped_rows(scraped_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int | list[str]]]:
    working = scraped_df.copy()
    raw_row_count = len(working)

    working["brand_name"] = working["brand_name"].map(normalize_brand)
    working["style_code"] = working["style_code"].map(normalize_style_code)
    working["competitor_name"] = working["competitor_name"].map(normalize_competitor_name)
    working["availability"] = working["availability"].map(normalize_availability)
    working["currency"] = working["currency"].astype(str).str.strip().str.upper()
    working["data_valid_bool"] = working["data_valid"].map(parse_boolean)
    working["is_on_sale_bool"] = working["is_on_sale"].map(parse_boolean)

    working["competitor_price"] = to_numeric(working["competitor_price"])
    working["competitor_sale_price"] = to_numeric(working["competitor_sale_price"])
    working["discount_pct"] = normalize_discount_pct(working["discount_pct"])

    invalid_mask = pd.Series(False, index=working.index)
    if "data_valid" in working.columns:
        invalid_mask |= working["data_valid_bool"].eq(False)
    invalid_mask |= working["brand_name"].isna()
    invalid_mask |= working["style_code"].isna()
    invalid_mask |= working["competitor_name"].isna()
    invalid_mask |= working["competitor_price"].isna()

    dropped_invalid_rows = int(invalid_mask.sum())
    working = working.loc[~invalid_mask].copy()

    currencies_found = sorted(working["currency"].dropna().unique().tolist())
    unknown_currencies = sorted(set(currencies_found) - {"USD", "LBP"})
    if unknown_currencies:
        raise ValueError(
            "Unknown currencies found in scrape output: "
            f"{', '.join(unknown_currencies)}. Update the conversion logic before continuing."
        )

    working["product_key"] = build_product_key(working["brand_name"], working["style_code"])
    working["competitor_price_usd"] = working["competitor_price"].where(
        working["currency"] == "USD",
        working["competitor_price"] * LBP_TO_USD,
    )
    working["competitor_sale_price_usd"] = working["competitor_sale_price"].where(
        working["currency"] == "USD",
        working["competitor_sale_price"] * LBP_TO_USD,
    )
    working["is_on_sale"] = working["is_on_sale_bool"].fillna(False)
    working["effective_competitor_price_usd"] = working["competitor_price_usd"]

    sale_mask = working["is_on_sale"] & working["competitor_sale_price_usd"].notna() & (working["competitor_sale_price_usd"] > 0)
    working.loc[sale_mask, "effective_competitor_price_usd"] = working.loc[sale_mask, "competitor_sale_price_usd"]

    working["scraped_at"] = pd.to_datetime(working["scraped_at"], utc=True, errors="coerce")

    before_dedup = len(working)
    working = working.drop_duplicates(
        subset=["product_key", "competitor_name", "competitor_price", "competitor_sale_price"],
        keep="first",
    ).copy()
    duplicates_removed = before_dedup - len(working)

    stats = {
        "input_row_count": raw_row_count,
        "cleaned_row_count": len(working),
        "dropped_invalid_rows": dropped_invalid_rows,
        "duplicates_removed": duplicates_removed,
        "currencies_found": currencies_found,
    }
    return working, stats


def filter_to_catalog_products(clean_rows: pd.DataFrame, products_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float | int]]:
    catalog = products_df.copy()
    catalog_valid = catalog.loc[catalog["product_key"].notna()].copy()
    catalog_keys = set(catalog_valid["product_key"])

    filtered_rows = clean_rows.loc[clean_rows["product_key"].isin(catalog_keys)].copy()
    filtered_rows = filtered_rows.merge(
        catalog_valid,
        on="product_key",
        how="left",
        validate="many_to_one",
    )

    filtered_rows = filtered_rows.rename(
        columns={
            "brand_name": "brand",
            "catalog_brand": "catalog_brand_raw",
            "catalog_style_code": "catalog_style_code_raw",
        }
    )
    filtered_rows["brand"] = filtered_rows["brand"]
    filtered_rows["style_code"] = filtered_rows["style_code"]

    matched_product_keys = filtered_rows["product_key"].dropna().nunique()
    total_products = len(products_df)
    products_with_no_match = total_products - matched_product_keys
    avg_competitors_per_matched_product = (
        filtered_rows.groupby("product_key")["competitor_name"].nunique().mean()
        if matched_product_keys
        else 0.0
    )

    coverage = {
        "total_products": total_products,
        "matchable_products": int(catalog_valid["product_key"].nunique()),
        "products_missing_safe_key": int(products_df["product_key"].isna().sum()),
        "unique_product_keys_in_clean_rows": int(clean_rows["product_key"].dropna().nunique()),
        "matched_product_keys": int(matched_product_keys),
        "products_with_no_match": int(products_with_no_match),
        "avg_competitors_per_matched_product": float(avg_competitors_per_matched_product),
    }
    return filtered_rows, coverage


def aggregate_competitor_rows(filtered_rows: pd.DataFrame) -> pd.DataFrame:
    grouped = filtered_rows.groupby("product_key", dropna=False)
    now_utc = pd.Timestamp.now(tz="UTC")

    aggregated = grouped.apply(_aggregate_one_product, include_groups=False).reset_index()
    aggregated["has_competitor_data"] = 1
    aggregated["data_freshness_hours"] = (
        (now_utc - aggregated["latest_scraped_at"]).dt.total_seconds() / 3600.0
    ).round(2)
    aggregated["latest_scraped_at"] = aggregated["latest_scraped_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    aggregated["competitors_on_sale_ratio"] = aggregated["competitors_on_sale_ratio"].round(4)
    aggregated["competitor_min_price_usd"] = aggregated["competitor_min_price_usd"].round(4)
    aggregated["competitor_avg_price_usd"] = aggregated["competitor_avg_price_usd"].round(4)
    aggregated["competitor_max_price_usd"] = aggregated["competitor_max_price_usd"].round(4)
    return aggregated


def _aggregate_one_product(group: pd.DataFrame) -> pd.Series:
    in_stock_mask = group["availability"].isin(["IN_STOCK", "LOW_STOCK"])
    out_of_stock_mask = group["availability"].eq("OUT_OF_STOCK")
    latest_scraped_at = group["scraped_at"].max()

    cheapest_row = group.sort_values(
        by=["effective_competitor_price_usd", "competitor_name"],
        ascending=[True, True],
        na_position="last",
    ).head(1)
    cheapest_competitor_name = (
        cheapest_row["competitor_name"].iloc[0]
        if not cheapest_row.empty
        else pd.NA
    )

    num_competitors = group["competitor_name"].nunique()
    on_sale_competitors = group.loc[group["is_on_sale"], "competitor_name"].nunique()

    first_row = group.iloc[0]
    return pd.Series(
        {
            "sku_id": first_row.get("sku_id"),
            "brand": first_row.get("brand"),
            "style_code": first_row.get("style_code"),
            "catalog_product_name": first_row.get("catalog_product_name"),
            "retail_price_usd": first_row.get("retail_price_usd"),
            "competitor_min_price_usd": group["effective_competitor_price_usd"].min(),
            "competitor_avg_price_usd": group["effective_competitor_price_usd"].mean(),
            "competitor_max_price_usd": group["effective_competitor_price_usd"].max(),
            "num_competitors": int(num_competitors),
            "competitors_on_sale_count": int(on_sale_competitors),
            "competitors_on_sale_ratio": (on_sale_competitors / num_competitors) if num_competitors else 0.0,
            "competitors_in_stock_count": int(group.loc[in_stock_mask, "competitor_name"].nunique()),
            "competitors_out_of_stock_count": int(group.loc[out_of_stock_mask, "competitor_name"].nunique()),
            "latest_scraped_at": latest_scraped_at,
            "cheapest_competitor_name": cheapest_competitor_name,
        }
    )


def validate_outputs(clean_rows: pd.DataFrame, aggregated: pd.DataFrame) -> None:
    price_columns = [
        "competitor_price_usd",
        "competitor_sale_price_usd",
        "effective_competitor_price_usd",
    ]
    for column in price_columns:
        negatives = clean_rows[column].dropna() < 0
        if negatives.any():
            raise ValueError(f"Negative USD prices found in row-level output column '{column}'.")

    if aggregated["product_key"].duplicated().any():
        raise ValueError("Duplicate product_key rows found in aggregated competitor output.")

    if aggregated["num_competitors"].isna().any():
        raise ValueError("Aggregated output contains null num_competitors values.")

    invalid_min_price = aggregated["has_competitor_data"].eq(1) & aggregated["competitor_min_price_usd"].isna()
    if invalid_min_price.any():
        raise ValueError("Aggregated output contains null competitor_min_price_usd values where competitor data exists.")


def save_outputs(clean_rows: pd.DataFrame, aggregated: pd.DataFrame) -> None:
    OUTPUT_ROWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean_rows_to_save = clean_rows.copy()
    clean_rows_to_save["scraped_at"] = clean_rows_to_save["scraped_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    clean_rows_to_save = clean_rows_to_save[[col for col in ROW_OUTPUT_COLUMNS if col in clean_rows_to_save.columns]]

    clean_rows_to_save.to_csv(OUTPUT_ROWS_PATH, index=False)
    aggregated.to_csv(OUTPUT_AGG_PATH, index=False)


def print_summary(
    clean_stats: dict[str, int | list[str]],
    filtered_rows: pd.DataFrame,
    aggregated: pd.DataFrame,
    coverage: dict[str, float | int],
) -> None:
    print("\n" + "=" * 72)
    print("COMPETITOR CLEANING SUMMARY")
    print("=" * 72)
    print(f"Source scrape file:         {SCRAPED_PATH}")
    print(f"Products file:              {PRODUCTS_PATH}")
    print(f"Input row count:            {clean_stats['input_row_count']}")
    print(f"Cleaned row count:          {clean_stats['cleaned_row_count']}")
    print(f"Filtered row count:         {len(filtered_rows)}")
    print(f"Aggregated product count:   {len(aggregated)}")
    print(f"Dropped invalid rows:       {clean_stats['dropped_invalid_rows']}")
    print(f"Duplicate rows removed:     {clean_stats['duplicates_removed']}")
    print(f"Currencies found:           {', '.join(clean_stats['currencies_found'])}")
    print("")
    print(f"Total products:             {coverage['total_products']}")
    print(f"Products with safe key:     {coverage['matchable_products']}")
    print(f"Products missing safe key:  {coverage['products_missing_safe_key']}")
    print(f"Unique product_keys in cleaned competitor rows: {coverage['unique_product_keys_in_clean_rows']}")
    print(f"Products with competitor match:                 {coverage['matched_product_keys']}")
    print(f"Products with no competitor match:              {coverage['products_with_no_match']}")
    print(f"Avg competitors / matched product:              {coverage['avg_competitors_per_matched_product']:.2f}")
    print("")
    print(f"Row-level output:           {OUTPUT_ROWS_PATH}")
    print(f"Aggregated output:          {OUTPUT_AGG_PATH}")
    print("")
    preview_columns = ", ".join(aggregated.columns.tolist())
    print(f"Aggregated columns:         {preview_columns}")
    if not aggregated.empty:
        print("\nAggregated preview:")
        print(aggregated.head(5).to_string(index=False))
    print("=" * 72)
    print("Run this from the repo root with:")
    print("  py services/decision_intelligence/features/clean_competitors.py")
    print("=" * 72)


def main() -> None:
    products_df, schema = load_products()
    print(
        f"Detected products schema: id='{schema.product_id}', brand='{schema.brand}', "
        f"style='{schema.style_code}', retail_price='{schema.retail_price}', product_name='{schema.product_name}'"
    )

    scraped_df = load_scraped_competitors()
    clean_rows, clean_stats = clean_scraped_rows(scraped_df)
    filtered_rows, coverage = filter_to_catalog_products(clean_rows, products_df)
    aggregated = aggregate_competitor_rows(filtered_rows)
    validate_outputs(filtered_rows, aggregated)
    save_outputs(filtered_rows, aggregated)
    print_summary(clean_stats, filtered_rows, aggregated, coverage)


if __name__ == "__main__":
    main()
