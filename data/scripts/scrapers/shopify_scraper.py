"""
Generic Shopify scraper.

Shopify stores expose a public JSON API at /products.json
No API key needed — it is fully public.

Works for:
  - lb.mikesport.com    → MikeSport Lebanon
  - comostore.me        → Como Store Lebanon
  - Any other Shopify-based Adidas retailer
"""

import re
from typing import Optional
from .base import BaseCompetitorScraper, ScrapedProduct, now_iso, usd_to_lbp, lbp_to_usd

# Adidas style code appears in Shopify product SKUs or titles
# Pattern: letters followed by digits e.g. B75806, HQ4202, GX3617
ADIDAS_SKU_RE = re.compile(r'\b([A-Z]{1,3}[0-9]{4,6})\b')


def _detect_style_code(product: dict) -> Optional[str]:
    """Search all Shopify variant SKUs and product title/tags for an Adidas style code."""
    # 1. Check variant SKUs first — most reliable
    for variant in product.get("variants", []):
        sku = (variant.get("sku") or "").upper().strip()
        if ADIDAS_SKU_RE.match(sku):
            return sku

    # 2. Check product title
    title = product.get("title", "").upper()
    matches = ADIDAS_SKU_RE.findall(title)
    if matches:
        return matches[0]

    # 3. Check product tags
    for tag in product.get("tags", []):
        tag = tag.upper().strip()
        if ADIDAS_SKU_RE.match(tag):
            return tag

    # 4. Check body_html for the article number
    body = re.sub(r'<[^>]+>', ' ', product.get("body_html", "") or "").upper()
    matches = ADIDAS_SKU_RE.findall(body)
    if matches:
        return matches[0]

    return None


def _parse_availability(variant: dict) -> str:
    qty = variant.get("inventory_quantity", 0) or 0
    policy = variant.get("inventory_policy", "deny")
    if qty > 10:
        return "in_stock"
    if qty > 0:
        return "low_stock"
    if policy == "continue":   # "continue selling when out of stock"
        return "in_stock"
    return "out_of_stock"


def _parse_gender(product: dict) -> Optional[str]:
    text = (product.get("title", "") + " " + " ".join(product.get("tags", []))).lower()
    if "women" in text or "ladies" in text or "female" in text:
        return "women"
    if "men" in text or "male" in text:
        return "men"
    if "kids" in text or "junior" in text or "boy" in text or "girl" in text or "child" in text:
        return "kids"
    return "unisex"


def _parse_category(product: dict) -> Optional[str]:
    ptype = (product.get("product_type") or "").lower()
    title = product.get("title", "").lower()
    combined = ptype + " " + title
    if "shoe" in combined or "sneaker" in combined or "boot" in combined or "trainer" in combined:
        return "shoes"
    if "shirt" in combined or "jersey" in combined or "top" in combined or "tee" in combined:
        return "tops"
    if "short" in combined or "pant" in combined or "legging" in combined or "tight" in combined:
        return "bottoms"
    if "jacket" in combined or "hoodie" in combined or "sweatshirt" in combined:
        return "outerwear"
    if "sock" in combined or "underwear" in combined:
        return "accessories"
    if "bag" in combined or "backpack" in combined:
        return "bags"
    if "cap" in combined or "hat" in combined or "beanie" in combined:
        return "headwear"
    return product.get("product_type") or None


class ShopifyScraper(BaseCompetitorScraper):
    """
    Scrapes any Shopify store by paginating /products.json.
    Subclass this and set retailer_name, competitor_name, base_url.
    """

    currency: str = "USD"

    async def _fetch_all_shopify_products(self) -> list[dict]:
        """Paginate /products.json until all products are fetched."""
        all_products = []
        page = 1
        while True:
            url = f"{self.base_url}/products.json?limit=250&page={page}"
            try:
                resp = await self.get(url)
                if resp.status_code != 200:
                    print(f"  [{self.retailer_name}] HTTP {resp.status_code} on page {page}, stopping.")
                    break
                data = resp.json()
                products = data.get("products", [])
                if not products:
                    break
                all_products.extend(products)
                print(f"  [{self.retailer_name}] Page {page}: {len(products)} products (total so far: {len(all_products)})")
                page += 1
            except Exception as e:
                print(f"  [{self.retailer_name}] Error on page {page}: {e}")
                break
        return all_products

    def _product_to_scraped(self, product: dict) -> Optional[ScrapedProduct]:
        """Convert a Shopify product dict to ScrapedProduct. Returns None if not Adidas."""
        style_code = _detect_style_code(product)
        if not style_code:
            return None

        # Use the cheapest available variant as the price
        variants = product.get("variants", [])
        if not variants:
            return None

        available_variants = [v for v in variants if _parse_availability(v) != "out_of_stock"]
        target_variants = available_variants if available_variants else variants

        prices = []
        for v in target_variants:
            try:
                prices.append(float(v.get("price", 0) or 0))
            except (ValueError, TypeError):
                pass

        if not prices:
            return None

        retail_price = min(prices)

        # Compare prices across compare_at_price
        compare_prices = []
        for v in target_variants:
            cp = v.get("compare_at_price")
            if cp:
                try:
                    compare_prices.append(float(cp))
                except (ValueError, TypeError):
                    pass

        original_price = max(compare_prices) if compare_prices else None
        is_on_sale = bool(original_price and original_price > retail_price)
        sale_price = retail_price if is_on_sale else None
        display_price = original_price if is_on_sale else retail_price
        discount_pct = round((original_price - retail_price) / original_price, 4) if is_on_sale and original_price else None

        # Sizes
        size_option_idx = None
        for i, opt in enumerate(product.get("options", [])):
            if opt.get("name", "").lower() in ("size", "shoe size", "sizes"):
                size_option_idx = i
                break

        sizes = []
        if size_option_idx is not None:
            for v in available_variants:
                val = v.get(f"option{size_option_idx + 1}")
                if val and val.lower() not in ("default title", "one size"):
                    sizes.append(val)

        # Availability (overall product)
        if available_variants:
            availability = "in_stock" if len(available_variants) > 3 else "low_stock"
        else:
            availability = "out_of_stock"

        # Handle currency conversion
        if self.currency == "USD":
            competitor_price_stored = display_price
        else:
            competitor_price_stored = display_price

        product_url = f"{self.base_url}/products/{product.get('handle', '')}"

        return ScrapedProduct(
            retailer_name=self.retailer_name,
            product_name=product.get("title", ""),
            style_code=style_code,
            sku_id=None,
            competitor_name=self.competitor_name,
            competitor_price=competitor_price_stored,
            competitor_sale_price=sale_price,
            is_on_sale=is_on_sale,
            discount_pct=discount_pct,
            availability=availability,
            currency=self.currency,
            colorway=None,
            category=_parse_category(product),
            gender_target=_parse_gender(product),
            sizes_available=sizes,
            source_url=product_url,
            scraped_at=now_iso(),
            data_valid=True,
            raw_price_text=str(display_price),
            raw_availability_text=availability,
            error_message=None,
        )

    async def scrape_all_products(self) -> list[ScrapedProduct]:
        raw = await self._fetch_all_shopify_products()
        results = []
        for p in raw:
            parsed = self._product_to_scraped(p)
            if parsed:
                results.append(parsed)
        print(f"  [{self.retailer_name}] {len(results)} Adidas products found out of {len(raw)} total.")
        return results

    async def scrape_by_style_code(self, style_code: str) -> Optional[ScrapedProduct]:
        """Search Shopify for a specific style code via /search/suggest.json."""
        url = f"{self.base_url}/search/suggest.json?q={style_code}&resources[type]=product&resources[limit]=5"
        try:
            resp = await self.get(url)
            if resp.status_code != 200:
                return self.make_error_product(style_code, url, f"HTTP {resp.status_code}")
            data = resp.json()
            products = data.get("resources", {}).get("results", {}).get("products", [])
            for p in products:
                # Verify this is actually the right style code
                if style_code.upper() in (p.get("title", "") + str(p.get("variants_min_price", ""))).upper():
                    # Fetch full product details
                    handle = p.get("handle", "")
                    detail_url = f"{self.base_url}/products/{handle}.json"
                    detail_resp = await self.get(detail_url)
                    if detail_resp.status_code == 200:
                        full = detail_resp.json().get("product", {})
                        result = self._product_to_scraped(full)
                        if result and result.style_code == style_code.upper():
                            return result
        except Exception as e:
            return self.make_error_product(style_code, url, str(e))
        return None
