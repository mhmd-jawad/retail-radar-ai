"""ShoesWorld Lebanon scraper."""

from __future__ import annotations

from scraping.common.next_api import NextApiShopConfig, scrape_next_api_catalog


CONFIG = NextApiShopConfig(
    competitor_name="shoesworld",
    base_url="https://www.shoesworldlb.com",
    currency="USD",
    supports_skip=True,
)


def scrape(max_products: int | None = 3, max_pages: int | None = None):
    return scrape_next_api_catalog(CONFIG, max_products=max_products, max_pages=max_pages)
