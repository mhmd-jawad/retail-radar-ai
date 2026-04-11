"""
Competitive intelligence analyzer.

Cross-references the store's products against all competitor prices
to determine market positioning, pricing opportunities, and risks.
"""

import statistics
from collections import Counter

from . import thresholds as T


def analyze(products, competitor_prices, inventory_results):
    """
    Analyze competitive positioning across all products.

    Args:
        products: store's product catalogue (list of dicts)
        competitor_prices: all competitor price records (list of dicts)
        inventory_results: output from inventory analyzer (for cross-referencing)

    Returns dict with:
        - sku_positioning: per-SKU competitive analysis
        - brand_summary: brand-level competitive positioning
        - category_summary: category-level positioning
        - opportunities: actionable competitive insights
        - market_overview: top-level competitive metrics
    """
    # Index competitor prices by product_key
    comp_by_key = {}
    for cp in competitor_prices:
        key = cp.get("product_key", "")
        comp_by_key.setdefault(key, []).append(cp)

    sku_positioning = []
    opportunities = []
    brand_agg = {}
    category_agg = {}

    for prod in products:
        sku_id = prod["sku_id"]
        product_key = prod.get("product_key", "")
        brand = prod.get("brand", "Unknown")
        category = prod.get("system_category", "other")
        our_price = float(prod.get("retail_price_usd", 0))

        # Get all competitor prices for this product
        comps = comp_by_key.get(product_key, [])
        comp_prices_list = []
        comp_details = []

        for cp in comps:
            cp_name = cp.get("competitor_name", "")
            cp_price = float(cp.get("competitor_price_usd", 0))
            cp_sale = cp.get("competitor_sale_price_usd")
            cp_sale = float(cp_sale) if cp_sale else None
            cp_avail = cp.get("availability", "unknown")

            effective_price = cp_sale if cp_sale and cp_sale > 0 else cp_price
            if effective_price <= 0:
                continue

            comp_prices_list.append(effective_price)
            comp_details.append({
                "competitor": cp_name,
                "regular_price_usd": cp_price,
                "sale_price_usd": cp_sale,
                "effective_price_usd": effective_price,
                "is_on_sale": cp.get("is_on_sale") == "True",
                "availability": cp_avail,
            })

        if not comp_prices_list or our_price <= 0:
            continue

        # Market statistics
        market_median = statistics.median(comp_prices_list)
        market_min = min(comp_prices_list)
        market_max = max(comp_prices_list)
        price_gap_pct = round((our_price - market_median) / market_median * 100, 1) if market_median > 0 else 0

        # Competitive position
        if price_gap_pct > T.COMP_PREMIUM:
            position = "premium"
        elif price_gap_pct > T.COMP_NEUTRAL_HIGH:
            position = "above_market"
        elif price_gap_pct >= T.COMP_NEUTRAL_LOW:
            position = "at_market"
        elif price_gap_pct >= T.COMP_VALUE:
            position = "below_market"
        else:
            position = "deep_value"

        # Competitor stock status
        in_stock_comps = [c for c in comp_details if c["availability"] == "in_stock"]
        oos_comps = [c for c in comp_details if c["availability"] == "out_of_stock"]
        comps_on_sale = [c for c in comp_details if c["is_on_sale"]]

        entry = {
            "sku_id": sku_id,
            "brand": brand,
            "product_name": prod.get("product_name", ""),
            "system_category": category,
            "our_price_usd": our_price,
            "market_median_usd": round(market_median, 2),
            "market_min_usd": round(market_min, 2),
            "market_max_usd": round(market_max, 2),
            "price_gap_pct": price_gap_pct,
            "position": position,
            "num_competitors": len(comp_details),
            "competitors_in_stock": len(in_stock_comps),
            "competitors_out_of_stock": len(oos_comps),
            "competitors_on_sale": len(comps_on_sale),
        }
        sku_positioning.append(entry)

        # Opportunities
        if len(oos_comps) > len(in_stock_comps) and len(oos_comps) >= 2:
            opportunities.append({
                "type": "pricing_power",
                "sku_id": sku_id,
                "brand": brand,
                "product_name": prod.get("product_name", ""),
                "message": f"{brand} {prod.get('product_name', '')[:40]} — "
                           f"{len(oos_comps)} of {len(comp_details)} competitors are out of stock. "
                           f"You can hold or increase price.",
                "impact": "high",
            })
        elif position == "premium" and len(comps_on_sale) >= 2:
            opportunities.append({
                "type": "price_adjustment",
                "sku_id": sku_id,
                "brand": brand,
                "product_name": prod.get("product_name", ""),
                "message": f"{brand} {prod.get('product_name', '')[:40]} — "
                           f"priced {price_gap_pct:.0f}% above market median "
                           f"and {len(comps_on_sale)} competitors have it on sale. "
                           f"Consider matching market to protect volume.",
                "impact": "medium",
            })
        elif position == "deep_value":
            opportunities.append({
                "type": "margin_recovery",
                "sku_id": sku_id,
                "brand": brand,
                "product_name": prod.get("product_name", ""),
                "message": f"{brand} {prod.get('product_name', '')[:40]} — "
                           f"priced {abs(price_gap_pct):.0f}% below market. "
                           f"You can raise price by ${abs(our_price - market_median):.2f} "
                           f"and still be competitive.",
                "impact": "medium",
            })

        # Aggregate by brand
        brand_agg.setdefault(brand, {"gaps": [], "positions": [], "count": 0})
        brand_agg[brand]["gaps"].append(price_gap_pct)
        brand_agg[brand]["positions"].append(position)
        brand_agg[brand]["count"] += 1

        # Aggregate by category
        category_agg.setdefault(category, {"gaps": [], "positions": [], "count": 0})
        category_agg[category]["gaps"].append(price_gap_pct)
        category_agg[category]["positions"].append(position)
        category_agg[category]["count"] += 1

    # Brand summary
    brand_summary = {}
    for brand, data in brand_agg.items():
        pos_dist = Counter(data["positions"])
        brand_summary[brand] = {
            "sku_count": data["count"],
            "avg_price_gap_pct": round(statistics.mean(data["gaps"]), 1) if data["gaps"] else 0,
            "median_price_gap_pct": round(statistics.median(data["gaps"]), 1) if data["gaps"] else 0,
            "position_distribution": dict(pos_dist),
            "dominant_position": pos_dist.most_common(1)[0][0] if pos_dist else "unknown",
        }

    # Category summary
    category_comp_summary = {}
    for cat, data in category_agg.items():
        pos_dist = Counter(data["positions"])
        category_comp_summary[cat] = {
            "sku_count": data["count"],
            "avg_price_gap_pct": round(statistics.mean(data["gaps"]), 1) if data["gaps"] else 0,
            "position_distribution": dict(pos_dist),
        }

    # Market overview
    all_gaps = [s["price_gap_pct"] for s in sku_positioning]
    all_positions = Counter(s["position"] for s in sku_positioning)

    market_overview = {
        "products_analyzed": len(sku_positioning),
        "avg_price_gap_pct": round(statistics.mean(all_gaps), 1) if all_gaps else 0,
        "median_price_gap_pct": round(statistics.median(all_gaps), 1) if all_gaps else 0,
        "position_distribution": dict(all_positions),
        "products_with_pricing_power": sum(
            1 for o in opportunities if o["type"] == "pricing_power"
        ),
        "products_overpriced": sum(
            1 for s in sku_positioning if s["position"] == "premium"
        ),
        "products_underpriced": sum(
            1 for s in sku_positioning if s["position"] in ("below_market", "deep_value")
        ),
    }

    return {
        "sku_positioning": sku_positioning,
        "brand_summary": brand_summary,
        "category_summary": category_comp_summary,
        "opportunities": opportunities,
        "market_overview": market_overview,
    }
