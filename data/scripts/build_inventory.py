"""
build_inventory.py — Build real product inventory from scraped competitor data.

Loads 37k+ scraped records across 8 Lebanese sportswear retailers,
normalizes prices to USD, deduplicates, assigns cost structures based
on Lebanon import economics, and outputs store-ready inventory files.

Outputs:
  data/real/products.csv       — deduplicated product catalogue (store's perspective)
  data/real/competitor_prices.csv — all competitor price points per product
  data/real/inventory.csv      — opening stock position

Usage:
  python data/scripts/build_inventory.py
"""

import csv
import hashlib
import json
import os
import re
import statistics
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[2]
SCRAPED_CSV = ROOT / "scraping" / "data" / "output" / "combined" / "all_shops_full_records.csv"
OUT_DIR = ROOT / "data" / "real"

FX_RATE_LBP_USD = 90_000  # April 2026 market rate

# ── Category mapping ───────────────────────────────────────────────────────
# Maps raw scraped category strings → normalized system categories.
# Unmatched categories fall through to a keyword-based fallback.

CATEGORY_MAP = {
    # Footwear
    "shoes": "footwear",
    "football shoes": "football_boots",
    "basketball shoes": "footwear",
    "running shoes": "footwear",
    "espadrilles": "footwear",
    "slippers": "footwear",
    "low boots": "footwear",
    "clog": "footwear",
    "sandal": "footwear",
    "flip flop": "footwear",
    "adidas cleats with studs": "football_boots",
    "cleats": "football_boots",
    # Apparel tops
    "t-shirt": "apparel",
    "hoody": "apparel",
    "jacket": "apparel",
    "tank": "apparel",
    "tops": "apparel",
    "fleece": "apparel",
    "vest": "apparel",
    "polo": "apparel",
    "sweater": "apparel",
    "sweatshirt": "apparel",
    "jersey": "apparel",
    # Apparel bottoms
    "pant": "apparel",
    "short": "apparel",
    "shorts": "apparel",
    "joggers & trousers": "apparel",
    "tight": "apparel",
    "legging": "apparel",
    "skirt": "apparel",
    # Sportswear / sets
    "bra": "sportswear",
    "set": "sportswear",
    "tracksuit": "sportswear",
    "sportswear": "sportswear",
    # Swimwear
    "swim short": "swimwear",
    "swim tight": "swimwear",
    "monokini": "swimwear",
    "bikini": "swimwear",
    "swimsuit": "swimwear",
    "goggles": "swimwear",
    # Kids
    "boys clothing": "kids",
    "girls clothing": "kids",
    # Accessories
    "cap": "accessories",
    "beanie": "accessories",
    "sock": "accessories",
    "accessories": "accessories",
    "bags cases and luggage": "accessories",
    "ball": "accessories",
    "pins": "accessories",
    "gloves": "accessories",
    "headband": "accessories",
    "wristband": "accessories",
    "bottle": "accessories",
    "towel": "accessories",
    "shin guard": "accessories",
    # Lifestyle
    "all items": "lifestyle",
    "originals": "lifestyle",
}

CATEGORY_KEYWORDS = {
    "footwear": ["shoe", "boot", "sneaker", "trainer", "sandal", "slide", "clog", "slipper", "espadrill", "flip"],
    "football_boots": ["cleat", "stud", "football shoe", "soccer"],
    "apparel": ["shirt", "pant", "short", "jacket", "hood", "fleece", "jersey", "polo", "sweater", "vest", "top", "tank", "tight", "legging", "jogger", "trouser"],
    "sportswear": ["bra", "set", "tracksuit"],
    "swimwear": ["swim", "bikini", "monokini", "goggle", "wetsuit"],
    "accessories": ["cap", "hat", "bag", "sock", "ball", "glove", "bottle", "towel", "pin", "beanie", "wrist", "head", "shin"],
    "kids": ["boy", "girl", "kid", "junior", "infant", "toddler"],
}

# ── Lebanon import cost model ─────────────────────────────────────────────
# Landed cost = retail × cost_ratio.  These ratios reflect:
#   - Manufacturer/distributor wholesale (40-55% of retail)
#   - Lebanon customs duty (5-15% depending on HS code)
#   - Freight to Beirut port (~8-12% on sportswear)
#   - Insurance (1-2%)
#   - Local distributor markup if applicable

BRAND_COST_RATIOS = {
    "Adidas": 0.48,
    "Nike": 0.47,
    "Puma": 0.50,
    "New Balance": 0.49,
    "Under Armour": 0.50,
    "The North Face": 0.45,
    "ON": 0.46,
    "Crocs": 0.52,
    "ASICS": 0.49,
    "Salewa": 0.44,
    "Joma": 0.55,
    "Lotto": 0.55,
    "Erke": 0.58,
    "Anta": 0.57,
    "Top Ten": 0.58,
    "Oil And Gaz": 0.55,
    "O'Neill": 0.50,
    "Head": 0.48,
    "Billabong": 0.50,
    "Trek": 0.52,
}
DEFAULT_COST_RATIO = 0.52  # conservative for unknown brands

# ── Stock depth model ──────────────────────────────────────────────────────
# Units per SKU for opening inventory. Based on category sell-through norms
# and Lebanon's import lead times (3-8 weeks). Deeper stock on staples.

STOCK_DEPTH = {
    "footwear": (8, 14),       # per size run: moderate, size-dependent
    "football_boots": (5, 10),  # seasonal, lower depth
    "apparel": (10, 18),       # each size: S/M/L/XL
    "sportswear": (8, 15),
    "swimwear": (6, 12),       # seasonal
    "accessories": (12, 25),   # small items, higher depth
    "kids": (6, 12),           # smaller market
    "lifestyle": (8, 15),
    "other": (6, 12),
}


def load_scraped_data():
    """Load and validate all scraped records."""
    rows = []
    with open(SCRAPED_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("data_valid") != "True":
                continue
            if not r.get("product_name") or not r.get("competitor_price"):
                continue
            price = float(r["competitor_price"])
            if price <= 0:
                continue
            rows.append(r)
    print(f"Loaded {len(rows)} valid scraped records from {SCRAPED_CSV.name}")
    return rows


def normalize_price_usd(row):
    """Convert price to USD. LBP rows (adidas_lb) divided by FX rate."""
    price = float(row["competitor_price"])
    sale = float(row["competitor_sale_price"]) if row.get("competitor_sale_price") else None

    if row.get("currency") == "LBP":
        price = round(price / FX_RATE_LBP_USD, 2)
        if sale:
            sale = round(sale / FX_RATE_LBP_USD, 2)

    return price, sale


def classify_category(raw_cat, product_name=""):
    """Map a raw scraped category to a system category."""
    if not raw_cat:
        raw_cat = ""
    key = raw_cat.strip().lower()

    # Direct map
    if key in CATEGORY_MAP:
        return CATEGORY_MAP[key]

    # Keyword fallback on category string + product name
    combined = f"{key} {product_name.lower()}"
    for sys_cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return sys_cat

    return "other"


def normalize_gender(raw_gender):
    """Normalize gender target to standard values."""
    g = (raw_gender or "").strip().lower()
    if g in ("boys", "girls", "kids", "junior", "infant"):
        return "kids"
    if g in ("men", "male"):
        return "men"
    if g in ("women", "female"):
        return "women"
    if g in ("unisex",):
        return "unisex"
    return "unisex"  # default if unknown


def deduplicate_products(rows):
    """
    Deduplicate across shops: group by (brand + style_code) or (brand + normalized name).
    For each group, pick the median price as the 'market price' and track all competitors.
    """
    groups = {}

    for r in rows:
        brand = (r.get("brand_name") or "Unknown").strip()
        style = (r.get("style_code") or "").strip()
        name = (r.get("product_name") or "").strip()

        # Build dedup key
        if style:
            key = f"{brand}|{style}".upper()
        else:
            # Normalize name: lowercase, remove color suffixes, strip sizes
            norm_name = re.sub(r"\s*[-,]\s*(black|white|grey|gray|blue|red|green|navy|pink|orange|yellow|brown|beige|olive|purple|multi).*$", "", name, flags=re.IGNORECASE)
            norm_name = re.sub(r"\s+", " ", norm_name).strip().upper()
            key = f"{brand}|NAME:{norm_name}"

        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    print(f"Deduplicated {len(rows)} records → {len(groups)} unique products")
    return groups


def build_product_catalogue(groups):
    """
    From deduplicated groups, build the store's product catalogue.
    Each product gets: market price, cost price, competitor count, category, stock depth.
    """
    products = []
    competitor_prices = []

    for key, records in groups.items():
        # Use the first record with the most data as the "reference"
        ref = max(records, key=lambda r: len(r.get("product_name", "")))

        brand = (ref.get("brand_name") or "Unknown").strip()
        style_code = (ref.get("style_code") or "").strip()
        name = (ref.get("product_name") or "").strip()
        raw_cat = (ref.get("category") or "").strip()
        gender = normalize_gender(ref.get("gender_target"))
        sys_cat = classify_category(raw_cat, name)

        # Collect all USD prices across competitors
        all_prices = []
        for r in records:
            p, sp = normalize_price_usd(r)
            effective = sp if sp and sp > 0 else p

            # Filter outlier prices (likely data errors)
            if effective < 1 or effective > 2000:
                continue

            all_prices.append(effective)

            competitor_prices.append({
                "product_key": key,
                "brand": brand,
                "style_code": style_code,
                "product_name": name,
                "competitor_name": r["competitor_name"],
                "competitor_price_usd": round(p, 2),
                "competitor_sale_price_usd": round(sp, 2) if sp else "",
                "is_on_sale": r.get("is_on_sale", "False"),
                "availability": r.get("availability", "unknown"),
                "scraped_at": r.get("scraped_at", ""),
            })

        if not all_prices:
            continue

        # Market price = median of all competitor prices
        market_price = round(statistics.median(all_prices), 2)
        min_price = round(min(all_prices), 2)
        max_price = round(max(all_prices), 2)

        # Cost price using brand-specific Lebanon import ratios
        cost_ratio = BRAND_COST_RATIOS.get(brand, DEFAULT_COST_RATIO)
        cost_price = round(market_price * cost_ratio, 2)
        gross_margin_pct = round((1 - cost_ratio) * 100, 1)

        # Competitor intelligence (computed early for pricing strategy)
        num_competitors = len(set(r["competitor_name"] for r in records))
        competitors_list = list(set(r["competitor_name"] for r in records))

        # Retail price: store pricing strategy (not exactly at median)
        # A new Lebanese store mixes: premium on exclusives/accessories,
        # competitive on core, aggressive on traffic-drivers
        import random
        random.seed(hash(key) & 0xFFFFFFFF)  # deterministic per product

        # Generate a base adjustment using brand positioning
        tier = random.random()  # 0-1 uniform
        if tier < 0.15:
            # 15% of SKUs: traffic drivers — priced below market
            price_adj = random.uniform(0.86, 0.95)
        elif tier < 0.35:
            # 20% of SKUs: competitive — at or slightly below market
            price_adj = random.uniform(0.95, 1.02)
        elif tier < 0.70:
            # 35% of SKUs: core — moderate markup
            price_adj = random.uniform(1.02, 1.10)
        elif tier < 0.90:
            # 20% of SKUs: premium positioning
            price_adj = random.uniform(1.10, 1.18)
        else:
            # 10% of SKUs: exclusive / high-service premium
            price_adj = random.uniform(1.18, 1.30)

        # Category nudge
        if sys_cat == "accessories":
            price_adj *= 1.05  # impulse items tolerate markup
        elif sys_cat in ("football_boots", "swimwear"):
            price_adj *= 0.97  # seasonal items need to move

        retail_price = round(market_price * price_adj, 2)
        # Ensure margin stays above cost
        if retail_price <= cost_price * 1.15:
            retail_price = round(cost_price * 1.35, 2)
        gross_margin_pct = round((1 - cost_price / retail_price) * 100, 1)

        # Size info from the record with the most sizes
        sizes_record = max(records, key=lambda r: len(r.get("sizes_available", "[]")))
        try:
            sizes = json.loads(sizes_record.get("sizes_available", "[]"))
        except (json.JSONDecodeError, TypeError):
            sizes = []
        num_sizes = max(len(sizes), 1)

        # Stock depth: category-driven, scaled by size count
        depth_min, depth_max = STOCK_DEPTH.get(sys_cat, (6, 12))
        # More sizes → deeper stock (footwear especially)
        if sys_cat in ("footwear", "football_boots"):
            base_depth = depth_min + min(num_sizes, 10) * ((depth_max - depth_min) / 10)
        else:
            base_depth = (depth_min + depth_max) / 2
        initial_stock = int(round(base_depth))

        # Availability signal: if most competitors are in_stock → popular item
        in_stock_count = sum(1 for r in records if r.get("availability") == "in_stock")
        availability_ratio = in_stock_count / len(records) if records else 0

        collection_type = "core"

        # Generate a stable SKU ID
        sku_id = hashlib.md5(key.encode()).hexdigest()[:10].upper()

        products.append({
            "sku_id": f"SP-{sku_id}",
            "product_key": key,
            "style_code": style_code,
            "brand": brand,
            "product_name": name,
            "system_category": sys_cat,
            "gender": gender,
            "retail_price_usd": retail_price,
            "cost_price_usd": cost_price,
            "gross_margin_pct": gross_margin_pct,
            "market_median_price_usd": market_price,
            "market_min_price_usd": min_price,
            "market_max_price_usd": max_price,
            "num_competitors": num_competitors,
            "competitors": ",".join(sorted(competitors_list)),
            "num_sizes": num_sizes,
            "initial_stock": initial_stock,
            "availability_ratio": round(availability_ratio, 2),
            "collection_type": "core" if availability_ratio > 0.6 else "seasonal",
            "fx_rate_used": FX_RATE_LBP_USD,
        })

    # Sort by brand, then category, then name
    products.sort(key=lambda p: (p["brand"], p["system_category"], p["product_name"]))
    print(f"Built catalogue: {len(products)} products")

    return products, competitor_prices


def curate_store_catalogue(all_products, target_skus=350):
    """
    Select a realistic store assortment from the full market catalogue.

    A Lebanese multi-brand sportswear store typically carries 300–500 SKUs.
    Selection prioritizes:
      1. Products stocked by multiple competitors (proven demand)
      2. Balanced brand mix (anchored by Adidas/Nike, diversified with 8-10 brands)
      3. Balanced category mix (footwear 30%, apparel 35%, accessories 15%, other 20%)
      4. Healthy margins (skip items where cost ≈ retail)
    """
    import random
    random.seed(42)  # reproducible

    # Target category allocation (% of target_skus)
    CATEGORY_ALLOC = {
        "footwear": 0.28,
        "football_boots": 0.05,
        "apparel": 0.30,
        "sportswear": 0.08,
        "accessories": 0.10,
        "swimwear": 0.04,
        "kids": 0.05,
        "lifestyle": 0.05,
        "other": 0.05,
    }

    # Target brand anchors: top brands get a minimum allocation
    BRAND_ANCHORS = {
        "Adidas": 0.22,
        "Nike": 0.18,
        "Puma": 0.08,
        "New Balance": 0.07,
        "Under Armour": 0.06,
        "The North Face": 0.05,
        "ON": 0.04,
        "Crocs": 0.04,
    }
    # Remaining 26% is distributed across other brands

    # Score each product for selection priority
    for p in all_products:
        score = 0
        # Multi-competitor presence = proven demand
        score += p["num_competitors"] * 10
        # High availability ratio = popular item
        score += p["availability_ratio"] * 20
        # Known brands preferred
        if p["brand"] in BRAND_ANCHORS:
            score += 15
        # Healthy margin preferred
        if p["gross_margin_pct"] >= 40:
            score += 10
        # Has style code = identifiable product
        if p["style_code"]:
            score += 5
        p["_selection_score"] = score

    # Group by category
    by_category = {}
    for p in all_products:
        cat = p["system_category"]
        by_category.setdefault(cat, []).append(p)

    # Sort each category by score descending
    for cat in by_category:
        by_category[cat].sort(key=lambda x: -x["_selection_score"])

    selected = []
    used_keys = set()

    # Pass 1: Fill category quotas, respecting brand diversity
    for cat, alloc_pct in CATEGORY_ALLOC.items():
        quota = int(target_skus * alloc_pct)
        candidates = by_category.get(cat, [])
        brand_counts = {}
        max_per_brand_in_cat = max(3, quota // 4)  # no single brand dominates a category

        picked = 0
        for p in candidates:
            if picked >= quota:
                break
            brand = p["brand"]
            if brand_counts.get(brand, 0) >= max_per_brand_in_cat:
                continue
            selected.append(p)
            used_keys.add(p["product_key"])
            brand_counts[brand] = brand_counts.get(brand, 0) + 1
            picked += 1

    # Pass 2: Fill remaining slots to reach target, prioritizing underrepresented brands
    remaining = target_skus - len(selected)
    if remaining > 0:
        all_remaining = [p for p in all_products if p["product_key"] not in used_keys]
        all_remaining.sort(key=lambda x: -x["_selection_score"])
        for p in all_remaining[:remaining]:
            selected.append(p)

    # Clean up temp field
    for p in selected:
        p.pop("_selection_score", None)
    for p in all_products:
        p.pop("_selection_score", None)

    print(f"Curated store catalogue: {len(selected)} SKUs from {len(all_products)} market products")
    return selected


def build_opening_inventory(products):
    """Create opening inventory snapshot from products."""
    inventory = []
    for p in products:
        inventory.append({
            "sku_id": p["sku_id"],
            "brand": p["brand"],
            "product_name": p["product_name"],
            "system_category": p["system_category"],
            "gender": p["gender"],
            "retail_price_usd": p["retail_price_usd"],
            "cost_price_usd": p["cost_price_usd"],
            "initial_stock": p["initial_stock"],
            "current_stock": p["initial_stock"],
            "inventory_value_at_cost": round(p["cost_price_usd"] * p["initial_stock"], 2),
            "inventory_value_at_retail": round(p["retail_price_usd"] * p["initial_stock"], 2),
            "status": "active",
        })
    return inventory


def write_csv(path, rows, fieldnames=None):
    """Write rows to CSV."""
    if not rows:
        print(f"WARNING: No rows to write to {path}")
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows → {path}")


def print_summary(products, inventory):
    """Print a validation summary."""
    total_skus = len(products)
    total_stock_units = sum(i["initial_stock"] for i in inventory)
    total_cost_value = sum(i["inventory_value_at_cost"] for i in inventory)
    total_retail_value = sum(i["inventory_value_at_retail"] for i in inventory)

    # Category breakdown
    from collections import Counter
    cat_counts = Counter(p["system_category"] for p in products)
    brand_counts = Counter(p["brand"] for p in products)

    print("\n" + "=" * 60)
    print("INVENTORY BUILD SUMMARY")
    print("=" * 60)
    print(f"Total SKUs:              {total_skus}")
    print(f"Total stock units:       {total_stock_units:,}")
    print(f"Inventory at cost:       ${total_cost_value:,.2f}")
    print(f"Inventory at retail:     ${total_retail_value:,.2f}")
    print(f"Blended margin:          {(1 - total_cost_value/total_retail_value)*100:.1f}%")
    print()
    print("Categories:")
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:20s} {count:5d} SKUs")
    print()
    print("Top 15 Brands:")
    for brand, count in brand_counts.most_common(15):
        print(f"  {brand:20s} {count:5d} SKUs")
    print()

    # Validation checks
    errors = []
    for p in products:
        if p["cost_price_usd"] <= 0:
            errors.append(f"{p['sku_id']}: cost_price <= 0")
        if p["retail_price_usd"] <= 0:
            errors.append(f"{p['sku_id']}: retail_price <= 0")
        if p["cost_price_usd"] >= p["retail_price_usd"]:
            errors.append(f"{p['sku_id']}: cost >= retail (margin negative)")
        if p["gross_margin_pct"] < 30:
            errors.append(f"{p['sku_id']}: margin {p['gross_margin_pct']}% below 30% floor")

    if errors:
        print(f"VALIDATION WARNINGS ({len(errors)}):")
        for e in errors[:10]:
            print(f"  ⚠ {e}")
        if len(errors) > 10:
            print(f"  ... and {len(errors)-10} more")
    else:
        print("✓ All validation checks passed")
    print("=" * 60)


def main():
    if not SCRAPED_CSV.exists():
        print(f"ERROR: Scraped data not found at {SCRAPED_CSV}")
        print("Run the scraper first: python -m scraping.cli scrape --all")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Load
    rows = load_scraped_data()

    # Step 2: Deduplicate
    groups = deduplicate_products(rows)

    # Step 3: Build full market catalogue + competitor prices
    all_products, comp_prices = build_product_catalogue(groups)

    # Step 4: Curate realistic store assortment (300-500 SKUs)
    store_products = curate_store_catalogue(all_products, target_skus=350)

    # Step 5: Build opening inventory
    inventory = build_opening_inventory(store_products)

    # Step 6: Write outputs
    write_csv(OUT_DIR / "products.csv", store_products)
    write_csv(OUT_DIR / "competitor_prices.csv", comp_prices)
    write_csv(OUT_DIR / "inventory.csv", inventory)
    write_csv(OUT_DIR / "market_catalogue.csv", all_products)  # full market for intelligence

    # Step 7: Summary
    print_summary(store_products, inventory)


if __name__ == "__main__":
    main()
