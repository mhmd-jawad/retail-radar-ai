"""Adapter for the custom Next/Vercel shop APIs used by some Lebanese stores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from .http import build_session, get_json
from .models import ScrapedProductRecord
from .normalization import (
    clean_text,
    competitor_product_id,
    discount_pct,
    extract_product_code,
    infer_brand_name,
    infer_gender_target,
    has_real_identifier,
    normalize_category,
    normalize_identifier,
    parse_float,
    unique_preserve_order,
    utc_timestamp,
)


@dataclass(frozen=True, slots=True)
class NextApiShopConfig:
    competitor_name: str
    base_url: str
    currency: str = "USD"
    endpoint_path: str = "/api/get-data"
    default_limit: int = 100
    supports_skip: bool = True


def scrape_next_api_catalog(
    config: NextApiShopConfig,
    *,
    max_products: int | None = 3,
    max_pages: int | None = None,
) -> object:
    session = build_session()
    seen_ids: set[str] = set()
    yielded = 0
    skip = 0
    page = 1

    while True:
        limit = config.default_limit if max_products is None else min(config.default_limit, max_products)
        url = _api_url(config, limit=limit, skip=skip)
        payload = get_json(session, url)
        products = _extract_product_dicts(payload)
        if not products:
            break

        new_records = 0
        for product in products:
            product_id = clean_text(product.get("_id") or product.get("id") or product.get("shopifyId"))
            if not product_id or product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            yield _product_to_record(config, product)
            new_records += 1
            yielded += 1
            if max_products is not None and yielded >= max_products:
                return

        if new_records == 0:
            break

        page += 1
        if max_pages is not None and page > max_pages:
            break
        if not config.supports_skip:
            break
        skip += limit


def _api_url(config: NextApiShopConfig, *, limit: int, skip: int) -> str:
    query = {"tkn": "", "limit": limit}
    if config.supports_skip:
        query["skip"] = skip
    return f"{config.base_url.rstrip('/')}{config.endpoint_path}?{urlencode(query)}"


def _extract_product_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    products: list[dict[str, Any]] = []

    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                products.extend(item for item in value if _looks_like_product(item))
    elif isinstance(data, list):
        products.extend(item for item in data if _looks_like_product(item))

    return products


def _looks_like_product(value: object) -> bool:
    return isinstance(value, dict) and bool(value.get("title") or value.get("name")) and (
        value.get("_id") or value.get("id") or value.get("shopifyId")
    )


def _product_to_record(config: NextApiShopConfig, product: dict[str, Any]) -> ScrapedProductRecord:
    product_id = clean_text(product.get("_id") or product.get("id") or product.get("shopifyId"))
    title = clean_text(product.get("title") or product.get("name"))
    current_price = parse_float(product.get("price") or product.get("newprice"))
    original_price = parse_float(product.get("originalPrice") or product.get("oldPrice") or product.get("compareAtPrice"))
    explicit_new_price = parse_float(product.get("newPrice") or product.get("salePrice"))

    regular_price = current_price
    sale_price = None
    if explicit_new_price is not None and current_price is not None and 0 < explicit_new_price < current_price:
        regular_price = current_price
        sale_price = explicit_new_price
    elif original_price is not None and current_price is not None and original_price > current_price:
        regular_price = original_price
        sale_price = current_price

    sizes = _extract_sizes(product)
    in_stock = product.get("inStock")
    availability = "in_stock" if in_stock is True or sizes else "out_of_stock" if in_stock is False else "unknown"
    category = normalize_category(product.get("category"), product.get("subCategory"), product.get("type"))
    tags = product.get("tags") or []
    tag_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags)
    brand_name = infer_brand_name(title) or infer_brand_name(product.get("brand"), product.get("type"), category, tag_text)
    handle = clean_text(product.get("handle"))
    description = product.get("description")
    sku_id = _primary_sku(product)
    style_code = extract_product_code(
        product.get("productCode"),
        product.get("product_code"),
        product.get("styleCode"),
        product.get("style_code"),
        product.get("modelCode"),
        product.get("articleCode"),
        handle,
        title,
        description,
        product.get("type"),
        category,
        tag_text,
    )

    return ScrapedProductRecord(
        competitor_product_id=competitor_product_id(config.competitor_name, product_id),
        competitor_name=config.competitor_name,
        style_code=normalize_identifier(style_code),
        sku_id=normalize_identifier(sku_id),
        brand_name=brand_name,
        product_name=title,
        category=category,
        gender_target=infer_gender_target(title, category, product.get("type"), tag_text),
        competitor_price=regular_price,
        competitor_sale_price=sale_price,
        discount_pct=discount_pct(regular_price, sale_price),
        is_on_sale=sale_price is not None,
        availability=availability,
        currency=config.currency,
        sizes_available=sizes,
        source_url=f"{config.base_url.rstrip('/')}/product/{product_id}" if product_id else config.base_url,
        scraped_at=utc_timestamp(),
        data_valid=bool(product_id and title and regular_price is not None),
    )


def _extract_sizes(product: dict[str, Any]) -> list[str]:
    sizes: list[object] = []
    for key in ("sizes", "productList"):
        raw_sizes = product.get(key)
        if not isinstance(raw_sizes, list):
            continue
        for item in raw_sizes:
            if isinstance(item, dict):
                sizes.append(item.get("size") or item.get("name") or item.get("value"))
            else:
                sizes.append(item)
    if product.get("size"):
        sizes.append(product.get("size"))
    return unique_preserve_order(sizes)


def _primary_sku(product: dict[str, Any]) -> str | None:
    for key in ("sku", "SKU", "variantSku", "variantSKU"):
        sku = clean_text(product.get(key))
        if has_real_identifier(sku):
            return sku
    return None
