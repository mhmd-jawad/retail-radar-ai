"""
Azadea Lebanon — Custom site scraper.
https://www.azadea.com/lb/en/brands/adidas

HOW TO VERIFY SELECTORS (do this once in browser DevTools):
  1. Open https://www.azadea.com/lb/en/brands/adidas in Chrome
  2. Press F12 → Elements tab
  3. Inspect the price element → note the CSS class
  4. Inspect the product name → note the CSS class
  5. Search the page HTML for any Adidas style code (e.g. "B75806") to see where it appears
  6. Update the SELECTORS dict below
"""

import re
from typing import Optional
from bs4 import BeautifulSoup
from ..base import BaseCompetitorScraper, ScrapedProduct, now_iso, ADIDAS_SKU_RE

# ─── SELECTORS — update these after inspecting the live site ────────────────
SELECTORS = {
    # Product listing page — each product card
    "product_card": "div.product-tile, li.product-item, div[data-product-id]",

    # Inside a product card
    "product_name": "span.product-name, h2.product-title, a.product-link",
    "price": "span.price, span.product-price, div.price-value",
    "sale_price": "span.sale-price, span.price--sale, ins.price",
    "original_price": "span.compare-price, span.price--compare, del.price",
    "availability": "span.availability, div.stock-status, span.in-stock",

    # Product listing URL pattern
    "product_link": "a.product-link, a.product-tile__link, h2.product-title a",
}

# Base URLs
CATALOG_URL = "https://www.azadea.com/lb/en/brands/adidas"
SEARCH_URL   = "https://www.azadea.com/lb/en/search?q={style_code}&lang=en_LB"


def _parse_price(text: str) -> Optional[float]:
    """Extract numeric price from text like '$159.00' or '159,000 LBP'."""
    if not text:
        return None
    cleaned = re.sub(r'[^\d.]', '', text.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


class AzadeaLB(BaseCompetitorScraper):
    retailer_name = "azadea_lb"
    competitor_name = "Azadea Lebanon"
    base_url = "https://www.azadea.com"
    currency = "USD"

    async def _scrape_listing_page(self, url: str) -> list[ScrapedProduct]:
        """Scrape one product listing page and return all products found."""
        try:
            resp = await self.get(url)
            if resp.status_code != 200:
                print(f"  [azadea_lb] HTTP {resp.status_code} for {url}")
                return []
        except Exception as e:
            print(f"  [azadea_lb] Request failed: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        products = []

        for card in soup.select(SELECTORS["product_card"]):
            try:
                name_el = card.select_one(SELECTORS["product_name"])
                product_name = name_el.get_text(strip=True) if name_el else ""

                # Try to find style code in the card HTML
                card_html = str(card)
                style_match = ADIDAS_SKU_RE.search(card_html.upper())
                style_code = style_match.group(0) if style_match else None
                if not style_code:
                    continue

                # Price
                sale_el = card.select_one(SELECTORS["sale_price"])
                orig_el = card.select_one(SELECTORS["original_price"])
                price_el = card.select_one(SELECTORS["price"])

                if sale_el and orig_el:
                    sale_price = _parse_price(sale_el.get_text())
                    orig_price = _parse_price(orig_el.get_text())
                    is_on_sale = True
                    discount = round((orig_price - sale_price) / orig_price, 4) if orig_price else None
                    display_price = orig_price
                elif price_el:
                    sale_price = None
                    orig_price = _parse_price(price_el.get_text())
                    is_on_sale = False
                    discount = None
                    display_price = orig_price
                else:
                    continue

                # Availability
                avail_el = card.select_one(SELECTORS["availability"])
                avail_text = avail_el.get_text(strip=True).lower() if avail_el else ""
                if "out" in avail_text or "unavail" in avail_text:
                    availability = "out_of_stock"
                elif "low" in avail_text or "few" in avail_text or "last" in avail_text:
                    availability = "low_stock"
                else:
                    availability = "in_stock"

                # Product URL
                link_el = card.select_one(SELECTORS["product_link"])
                product_url = ""
                if link_el and link_el.get("href"):
                    href = link_el["href"]
                    product_url = href if href.startswith("http") else self.base_url + href

                products.append(ScrapedProduct(
                    retailer_name=self.retailer_name,
                    product_name=product_name,
                    style_code=style_code,
                    sku_id=None,
                    competitor_name=self.competitor_name,
                    competitor_price=display_price,
                    competitor_sale_price=sale_price,
                    is_on_sale=is_on_sale,
                    discount_pct=discount,
                    availability=availability,
                    currency=self.currency,
                    colorway=None,
                    category=None,
                    gender_target=None,
                    sizes_available=[],
                    source_url=product_url,
                    scraped_at=now_iso(),
                    data_valid=True,
                    raw_price_text=price_el.get_text(strip=True) if price_el else None,
                    raw_availability_text=avail_text or None,
                    error_message=None,
                ))
            except Exception as e:
                print(f"  [azadea_lb] Error parsing product card: {e}")
                continue

        return products

    async def scrape_all_products(self) -> list[ScrapedProduct]:
        """Scrape Azadea's Adidas collection across all pages."""
        all_products = []
        page = 1
        while True:
            url = f"{CATALOG_URL}?start={(page-1)*24}&sz=24"
            products = await self._scrape_listing_page(url)
            if not products:
                break
            all_products.extend(products)
            print(f"  [azadea_lb] Page {page}: {len(products)} products")
            page += 1
            if page > 50:   # safety limit
                break
        print(f"  [azadea_lb] Total: {len(all_products)} Adidas products")
        return all_products

    async def scrape_by_style_code(self, style_code: str) -> Optional[ScrapedProduct]:
        """Search Azadea for a specific style code."""
        url = SEARCH_URL.format(style_code=style_code)
        products = await self._scrape_listing_page(url)
        for p in products:
            if p.style_code == style_code.upper():
                return p
        return None
