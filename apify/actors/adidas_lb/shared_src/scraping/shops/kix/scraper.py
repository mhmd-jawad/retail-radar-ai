"""KIX Lebanon scraper."""

from __future__ import annotations

from scraping.common.shopify import ShopifyShopConfig, scrape_shopify_catalog


CONFIG = ShopifyShopConfig(
    competitor_name="kix",
    base_url="https://kixlb.com",
    currency="USD",
)


def scrape(max_products: int | None = 3, max_pages: int | None = None):
    return scrape_shopify_catalog(CONFIG, max_products=max_products, max_pages=max_pages)
