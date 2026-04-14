"""Generic Shopify catalog adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from .http import build_session, get_json
from .models import ScrapedProductRecord
from .normalization import (
    GENERIC_VENDOR_VALUES,
    clean_text,
    competitor_product_id,
    discount_pct,
    infer_brand_name,
    infer_gender_target,
    infer_style_code,
    normalize_category,
    parse_float,
    unique_preserve_order,
    utc_timestamp,
)


@dataclass(frozen=True, slots=True)
class ShopifyShopConfig:
    competitor_name: str
    base_url: str
    currency: str = "USD"
    endpoint_path: str = "/products.json"
    default_limit: int = 250


def scrape_shopify_catalog(
    config: ShopifyShopConfig,
    *,
    max_products: int | None = 3,
    max_pages: int | None = None,
) -> list[ScrapedProductRecord]:
    session = build_session()
    records: list[ScrapedProductRecord] = []
    page = 1

    while True:
        limit = config.default_limit if max_products is None else min(config.default_limit, max_products)
        url = _catalog_url(config, page=page, limit=limit)
        try:
            payload = get_json(session, url)
        except RuntimeError as exc:
            if page > 1 and "400 Client Error" in str(exc):
                break
            raise
        products = payload.get("products") or []
        if not products:
            break

        for product in products:
            if isinstance(product, dict):
                records.append(_product_to_record(config, product))
                if max_products is not None and len(records) >= max_products:
                    return records

        page += 1
        if max_pages is not None and page > max_pages:
            break

    return records


def _catalog_url(config: ShopifyShopConfig, *, page: int, limit: int) -> str:
    query = urlencode({"limit": limit, "page": page})
    return f"{config.base_url.rstrip('/')}{config.endpoint_path}?{query}"


def _product_to_record(config: ShopifyShopConfig, product: dict[str, Any]) -> ScrapedProductRecord:
    variants = [variant for variant in product.get("variants", []) if isinstance(variant, dict)]
    available_variants = [variant for variant in variants if variant.get("available") is True]
    variants_for_price = available_variants or variants
    price_info = _extract_price_info(variants_for_price)
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    option_signals: list[str] = []
    for variant in variants:
        option_signals.extend(
            str(value)
            for value in (
                variant.get("sku"),
                variant.get("title"),
                variant.get("option1"),
                variant.get("option2"),
                variant.get("option3"),
            )
            if value
        )

    product_id = product.get("id")
    handle = clean_text(product.get("handle"))
    source_url = f"{config.base_url.rstrip('/')}/products/{handle}" if handle else config.base_url
    product_name = clean_text(product.get("title"))
    category = normalize_category(product.get("product_type"), *(tags or []))
    vendor = clean_text(product.get("vendor"))
    brand_name = infer_brand_name(vendor, product_name, category, " ".join(tags))
    if not brand_name and vendor and vendor.lower() not in GENERIC_VENDOR_VALUES:
        brand_name = vendor
    style_code = infer_style_code(handle, product_name, category, " ".join(tags), *option_signals)
    sizes_available = unique_preserve_order(
        _variant_size(variant) for variant in available_variants
    )
    availability = "in_stock" if available_variants else "out_of_stock"

    return ScrapedProductRecord(
        competitor_product_id=competitor_product_id(config.competitor_name, product_id),
        competitor_name=config.competitor_name,
        style_code=style_code,
        brand_name=brand_name,
        product_name=product_name,
        category=category,
        gender_target=infer_gender_target(product_name, category, " ".join(tags)),
        competitor_price=price_info["competitor_price"],
        competitor_sale_price=price_info["competitor_sale_price"],
        discount_pct=price_info["discount_pct"],
        is_on_sale=price_info["competitor_sale_price"] is not None,
        availability=availability,
        currency=config.currency,
        sizes_available=sizes_available,
        source_url=source_url,
        scraped_at=utc_timestamp(),
        data_valid=bool(product_id and product_name and price_info["competitor_price"] is not None and source_url),
    )


def _extract_price_info(variants: list[dict[str, Any]]) -> dict[str, float | None]:
    best_current: float | None = None
    best_regular: float | None = None

    for variant in variants:
        current = parse_float(variant.get("price"))
        compare_at = parse_float(variant.get("compare_at_price"))
        if current is None:
            continue
        regular = compare_at if compare_at is not None and compare_at > current else current
        if best_current is None or current < best_current:
            best_current = current
            best_regular = regular

    sale_price = best_current if best_regular is not None and best_current is not None and best_current < best_regular else None
    return {
        "competitor_price": best_regular if sale_price is not None else best_current,
        "competitor_sale_price": sale_price,
        "discount_pct": discount_pct(best_regular, sale_price),
    }


def _variant_size(variant: dict[str, Any]) -> str | None:
    options = [variant.get("option1"), variant.get("option2"), variant.get("option3")]
    for option in options:
        cleaned = clean_text(option)
        if cleaned and _looks_like_size(cleaned):
            return cleaned
    return clean_text(variant.get("title"))


def _looks_like_size(value: str) -> bool:
    lower = value.lower()
    if lower in {"black", "white", "blue", "red", "green", "grey", "gray", "pink", "orange", "brown"}:
        return False
    return True
