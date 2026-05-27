"""Runtime competitor matching for prediction requests.

This module is the live counterpart to the offline competitor cleaning job.
It uses the same normalization and matching helpers, but returns the IE2
CompetitorSignals shape for one selected product.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from services.decision_intelligence.features import clean_competitors as matcher


ROOT = Path(__file__).resolve().parents[2]
PRODUCTS_PATH = ROOT / "data" / "real" / "products.csv"
NO_MATCH_REASON = "No reliable competitor match found."


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def load_products_index() -> dict[str, dict[str, str]]:
    if not PRODUCTS_PATH.exists():
        return {}
    return {row["sku_id"]: row for row in _read_csv(PRODUCTS_PATH)}


def _load_database_competitor_rows() -> pd.DataFrame | None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return None
    try:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select brand_name, style_code, shop_code as competitor_name, product_name,
                           category, gender_target, competitor_price, competitor_sale_price,
                           discount_pct, is_on_sale, availability, currency, source_url,
                           last_seen_at as scraped_at, data_valid
                    from intel.competitor_products_latest
                    """
                )
                columns = [column.name for column in cur.description]
                return pd.DataFrame(cur.fetchall(), columns=columns)
    except Exception as exc:
        raise RuntimeError("Cannot read live competitor data from configured PostgreSQL.") from exc


def load_live_competitor_rows() -> pd.DataFrame:
    scraped = _load_database_competitor_rows()
    if scraped is None:
        scraped = matcher.load_scraped_competitors()
    clean_rows, _ = matcher.clean_scraped_rows(scraped)
    return clean_rows


def clear_processor_cache() -> None:
    load_products_index.cache_clear()


def _coalesce_product_field(product: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = product.get(key)
        if value not in (None, ""):
            return value
    return None


def _product_row(product: dict[str, Any]) -> pd.Series:
    sku_id = str(_coalesce_product_field(product, "sku_id") or "").strip()
    brand = matcher.normalize_brand(_coalesce_product_field(product, "brand", "brand_name"))
    style_code = matcher.normalize_style_code(
        _coalesce_product_field(product, "style_code", "style", "model_code", "article_code")
    )
    product_name = _coalesce_product_field(product, "product_name", "name", "title")
    category = matcher.normalize_category(
        _coalesce_product_field(product, "system_category", "category", "product_category"),
        product_name,
    )
    gender = matcher.normalize_gender(_coalesce_product_field(product, "gender", "gender_target"), product_name)

    exact_key = None
    if brand and style_code:
        exact_key = f"{brand}|{style_code}"

    catalog_key = matcher.normalize_string(product.get("product_key"))
    if exact_key:
        product_key = exact_key
        product_key_source = "brand_style"
    elif catalog_key:
        product_key = catalog_key
        product_key_source = "catalog_fallback"
    else:
        product_key = f"SKU|{sku_id}" if sku_id else None
        product_key_source = "sku_fallback"

    return pd.Series(
        {
            "sku_id": sku_id,
            "catalog_brand": _coalesce_product_field(product, "brand", "brand_name"),
            "catalog_style_code": _coalesce_product_field(product, "style_code", "style"),
            "retail_price_usd": _to_float(_coalesce_product_field(product, "retail_price_usd", "retail_price")),
            "catalog_product_name": product_name,
            "brand_normalized": brand,
            "style_code_normalized": style_code,
            "category_normalized": category,
            "gender_normalized": gender,
            "product_key": product_key,
            "product_key_source": product_key_source,
        }
    )


def _as_clean_rows(competitor_rows: list[dict[str, Any]] | pd.DataFrame | None) -> pd.DataFrame:
    if competitor_rows is None:
        return load_live_competitor_rows()
    frame = competitor_rows.copy() if isinstance(competitor_rows, pd.DataFrame) else pd.DataFrame(competitor_rows)
    frame = matcher.normalize_columns(frame)
    for optional_col in matcher.RELEVANT_SCRAPE_COLUMNS:
        if optional_col not in frame.columns:
            frame[optional_col] = pd.NA
    clean_rows, _ = matcher.clean_scraped_rows(frame)
    return clean_rows


def _no_match_signals(sku_id: str) -> dict[str, Any]:
    return {
        "sku_id": sku_id,
        "competitor_min_price": 0.0,
        "competitor_avg_price": 0.0,
        "price_gap_pct": 0.0,
        "competitors_on_sale_count": 0,
        "competitors_out_of_stock_count": 0,
        "num_competitors_tracked": 0,
        "cheapest_competitor_name": None,
        "price_trend_direction": "STABLE",
        "data_freshness_hours": 0.0,
        "confidence_score": 0.0,
        "fallback_used": True,
        "fallback_reason": NO_MATCH_REASON,
        "match_type": "no_match",
        "match_score": 0.0,
        "timestamp": datetime.now(),
    }


def _confidence_from_freshness(freshness_hours: float) -> float:
    return round(max(0.25, min(1.0, 1.0 - freshness_hours / 168.0)), 4)


def build_competitor_signals_for_product(
    product: dict[str, Any],
    competitor_rows: list[dict[str, Any]] | pd.DataFrame | None = None,
) -> dict[str, Any]:
    product_row = _product_row(product)
    sku_id = str(product_row.get("sku_id") or product.get("sku_id") or "")
    clean_rows = _as_clean_rows(competitor_rows)

    product_key = product_row.get("product_key")
    exact_rows = clean_rows.loc[clean_rows["product_key"].eq(product_key)] if product_key else clean_rows.iloc[0:0]
    if not exact_rows.empty and product_row.get("product_key_source") == "brand_style":
        matched_rows = matcher._attach_catalog_fields(
            exact_rows,
            product_row,
            match_type="exact_style",
            match_score=1.0,
            match_reason="same normalized brand and style_code",
        )
    else:
        matched_rows = matcher._best_fallback_rows_for_product(product_row, clean_rows)

    if matched_rows.empty:
        return _no_match_signals(sku_id)

    aggregated = matcher.aggregate_competitor_rows(matched_rows)
    if aggregated.empty:
        return _no_match_signals(sku_id)

    row = aggregated.iloc[0]
    our_price = _to_float(product_row.get("retail_price_usd"))
    competitor_min = _to_float(row.get("competitor_min_price_usd"))
    competitor_avg = _to_float(row.get("competitor_avg_price_usd"), competitor_min)
    price_gap_pct = round((our_price - competitor_min) / our_price, 4) if our_price > 0 and competitor_min > 0 else 0.0
    freshness = _to_float(row.get("data_freshness_hours"))

    return {
        "sku_id": sku_id,
        "competitor_min_price": round(competitor_min, 2),
        "competitor_avg_price": round(competitor_avg, 2),
        "price_gap_pct": price_gap_pct,
        "competitors_on_sale_count": _to_int(row.get("competitors_on_sale_count")),
        "competitors_out_of_stock_count": _to_int(row.get("competitors_out_of_stock_count")),
        "num_competitors_tracked": _to_int(row.get("num_competitors")),
        "cheapest_competitor_name": row.get("cheapest_competitor_name") or None,
        "price_trend_direction": "STABLE",
        "data_freshness_hours": round(freshness, 1),
        "confidence_score": _confidence_from_freshness(freshness),
        "fallback_used": False,
        "fallback_reason": None,
        "match_type": row.get("match_type") or "matched_unknown",
        "match_score": round(_to_float(row.get("match_score")), 4),
        "timestamp": datetime.now(),
    }


def build_competitor_signals_for_sku(sku_id: str) -> dict[str, Any]:
    product = load_products_index().get(sku_id)
    if product is None:
        raise KeyError(sku_id)
    return build_competitor_signals_for_product(product)
