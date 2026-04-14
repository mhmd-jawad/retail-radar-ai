"""CitySport scraper."""

from __future__ import annotations

from urllib.parse import urlencode

from scraping.common.http import build_session, get_json
from scraping.common.next_api import NextApiShopConfig, _product_to_record


CONFIG = NextApiShopConfig(
    competitor_name="citysport",
    base_url="https://www.citysport-lb.com",
    currency="USD",
    supports_skip=False,
)


def scrape(max_products: int | None = 3, max_pages: int | None = None):
    session = build_session()
    category_names = ["collection", *_category_names(session)]
    seen_ids: set[str] = set()
    yielded = 0

    for category_name in category_names:
        page = 0
        while True:
            payload = get_json(session, _category_url(category_name, page))
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
                yield _product_to_record(CONFIG, product)
                yielded += 1
                if max_products is not None and yielded >= max_products:
                    return

            page += 1
            if not products or page >= total_pages:
                break
            if max_pages is not None and page >= max_pages:
                break


def _category_names(session) -> list[str]:
    payload = get_json(session, f"{CONFIG.base_url}/api/get-categories")
    categories = payload.get("Categories") or []
    first_group = categories[0] if categories else {}
    category_items = first_group.get("cateArray") or []
    names = []
    for category in category_items:
        if isinstance(category, dict) and category.get("categoryName"):
            names.append(str(category["categoryName"]).strip().lower())
    return names


def _category_url(category_name: str, page: int) -> str:
    query = urlencode({"category": category_name, "page": page})
    return f"{CONFIG.base_url}/api/get-cate?{query}"
