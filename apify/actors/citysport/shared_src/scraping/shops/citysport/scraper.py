"""CitySport scraper."""

from __future__ import annotations

import os
from dataclasses import replace
from urllib.parse import urlencode

from scraping.common.http import build_session, get_json
from scraping.common.next_api import NextApiShopConfig, _product_to_record


DEFAULT_CONFIG = NextApiShopConfig(
    competitor_name="citysport",
    base_url="https://www.citysport-lb.com",
    currency="USD",
    supports_skip=False,
)
FALLBACK_BASE_URLS = ("https://www.citysport-lb.com", "https://citysport-lb.com")
FALLBACK_CATEGORY_NAMES = ["collection"]


def scrape(max_products: int | None = 3, max_pages: int | None = None):
    last_error: RuntimeError | None = None
    for base_url in _base_urls():
        config = replace(DEFAULT_CONFIG, base_url=base_url)
        emitted = 0
        try:
            for record in _scrape_config(config, max_products=max_products, max_pages=max_pages):
                emitted += 1
                yield record
        except RuntimeError as exc:
            if emitted:
                raise
            last_error = exc
            continue
        if emitted == 0:
            last_error = RuntimeError(f"No CitySport products returned from {base_url}.")
            continue
        return

    if last_error is not None:
        raise last_error


def _base_urls() -> list[str]:
    configured = os.getenv("CITYSPORT_BASE_URLS") or os.getenv("CITYSPORT_BASE_URL")
    urls = []
    if configured:
        urls.extend(url.strip().rstrip("/") for url in configured.split(",") if url.strip())
    urls.extend(FALLBACK_BASE_URLS)
    return list(dict.fromkeys(urls))


def _scrape_config(config: NextApiShopConfig, *, max_products: int | None, max_pages: int | None):
    session = build_session()
    category_names = _category_names(session, config)
    seen_ids: set[str] = set()
    yielded = 0

    for category_name in category_names:
        page = 0
        while True:
            payload = get_json(session, _category_url(config, category_name, page))
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            products = data.get("products") or []
            total_pages = int(data.get("totalPages") or 0)

            for product in products:
                if not isinstance(product, dict):
                    continue
                product_id = str(product.get("_id") or product.get("id") or "")
                if not product_id or product_id in seen_ids:
                    continue
                seen_ids.add(product_id)
                yield _product_to_record(config, product)
                yielded += 1
                if max_products is not None and yielded >= max_products:
                    return

            page += 1
            if not products or page >= total_pages:
                break
            if max_pages is not None and page >= max_pages:
                break


def _category_names(session, config: NextApiShopConfig) -> list[str]:
    try:
        payload = get_json(session, f"{config.base_url}/api/get-categories")
    except RuntimeError:
        return FALLBACK_CATEGORY_NAMES
    categories = payload.get("Categories") or []
    first_group = categories[0] if categories else {}
    category_items = first_group.get("cateArray") or []
    names = ["collection"]
    for category in category_items:
        if isinstance(category, dict) and category.get("categoryName"):
            names.append(str(category["categoryName"]).strip().lower())
    return list(dict.fromkeys(names))


def _category_url(config: NextApiShopConfig, category_name: str, page: int) -> str:
    query = urlencode({"category": category_name, "page": page})
    return f"{config.base_url}/api/get-cate?{query}"
