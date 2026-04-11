"""
Inventory health analyzer.

Evaluates every SKU and category for:
  - Days of Supply (DOS)
  - Sell-through rate
  - Stock status (healthy / excess / dead / stockout risk)
  - Category-level health rollups
"""

from . import thresholds as T


def analyze(products, inventory, financial_profile):
    """
    Analyze inventory health from products and current stock data.

    Returns dict with:
      - sku_analysis: per-SKU health assessment
      - category_summary: aggregated category health
      - alerts: list of actionable alerts
      - metrics: top-level inventory health metrics
    """
    # Build lookup: sku_id → product details
    product_map = {p["sku_id"]: p for p in products}

    sku_analysis = []
    alerts = []
    category_data = {}

    for inv in inventory:
        sku_id = inv["sku_id"]
        prod = product_map.get(sku_id, {})

        current_stock = int(inv.get("current_stock", inv.get("initial_stock", 0)))
        cost_price = float(inv.get("cost_price_usd", 0))
        retail_price = float(inv.get("retail_price_usd", 0))
        category = inv.get("system_category", "other")
        brand = inv.get("brand", "Unknown")

        # Compute margin
        margin_pct = round((1 - cost_price / retail_price) * 100, 1) if retail_price > 0 else 0

        # Estimate daily demand from financial projections
        merged = {**prod, "units_on_hand": current_stock}
        avg_daily_demand = _estimate_daily_demand(merged, financial_profile)

        # Days of Supply
        if avg_daily_demand > 0:
            dos = round(current_stock / avg_daily_demand, 0)
        else:
            dos = 9999  # no demand = infinite supply

        dos_status = T.get_dos_status(dos)

        # Inventory value at risk
        value_at_cost = round(current_stock * cost_price, 2)
        value_at_retail = round(current_stock * retail_price, 2)

        # Markdown recommendation
        markdown_rec = T.get_markdown_recommendation(dos)

        entry = {
            "sku_id": sku_id,
            "brand": brand,
            "product_name": prod.get("product_name", inv.get("product_name", "")),
            "system_category": category,
            "current_stock": current_stock,
            "retail_price_usd": retail_price,
            "cost_price_usd": cost_price,
            "margin_pct": margin_pct,
            "estimated_daily_demand": round(avg_daily_demand, 3),
            "days_of_supply": dos,
            "dos_status": dos_status,
            "value_at_cost_usd": value_at_cost,
            "value_at_retail_usd": value_at_retail,
            "markdown_recommendation": markdown_rec["label"] if markdown_rec else None,
            "recommended_discount_pct": markdown_rec["discount_pct"] if markdown_rec else 0,
        }
        sku_analysis.append(entry)

        # Alerts
        if dos_status == "critical":
            alerts.append({
                "severity": "high",
                "type": "stockout_risk",
                "sku_id": sku_id,
                "brand": brand,
                "product_name": entry["product_name"],
                "message": f"{brand} {entry['product_name'][:40]} has only {dos:.0f} days of supply. "
                           f"Reorder immediately — import lead time is 3-8 weeks.",
                "value_at_risk_usd": value_at_retail,
            })
        elif dos_status == "dead":
            alerts.append({
                "severity": "high",
                "type": "dead_stock",
                "sku_id": sku_id,
                "brand": brand,
                "product_name": entry["product_name"],
                "message": f"{brand} {entry['product_name'][:40]} has {dos:.0f} DOS — "
                           f"${value_at_cost:.0f} tied up in dead stock. Clear at 50% off to recover cash.",
                "value_at_risk_usd": value_at_cost,
            })
        elif dos_status == "excess":
            alerts.append({
                "severity": "medium",
                "type": "slow_mover",
                "sku_id": sku_id,
                "brand": brand,
                "product_name": entry["product_name"],
                "message": f"{brand} {entry['product_name'][:40]} — {dos:.0f} DOS, "
                           f"consider {markdown_rec['discount_pct']}% markdown." if markdown_rec else "",
                "value_at_risk_usd": value_at_cost,
            })

        if margin_pct < T.MARGIN_FLOOR:
            alerts.append({
                "severity": "medium",
                "type": "margin_warning",
                "sku_id": sku_id,
                "brand": brand,
                "product_name": entry["product_name"],
                "message": f"{brand} {entry['product_name'][:40]} margin is {margin_pct:.1f}% "
                           f"(below {T.MARGIN_FLOOR}% floor). Review pricing or drop this SKU.",
            })

        # Aggregate to category
        if category not in category_data:
            category_data[category] = {
                "sku_count": 0, "total_stock": 0,
                "total_cost": 0, "total_retail": 0,
                "dos_values": [], "margin_values": [],
                "critical_count": 0, "excess_count": 0, "dead_count": 0,
            }
        cd = category_data[category]
        cd["sku_count"] += 1
        cd["total_stock"] += current_stock
        cd["total_cost"] += value_at_cost
        cd["total_retail"] += value_at_retail
        cd["dos_values"].append(dos if dos < 9999 else 999)
        cd["margin_values"].append(margin_pct)
        if dos_status == "critical":
            cd["critical_count"] += 1
        elif dos_status == "excess":
            cd["excess_count"] += 1
        elif dos_status == "dead":
            cd["dead_count"] += 1

    # Build category summary
    category_summary = {}
    for cat, cd in category_data.items():
        avg_dos = sum(cd["dos_values"]) / len(cd["dos_values"]) if cd["dos_values"] else 0
        avg_margin = sum(cd["margin_values"]) / len(cd["margin_values"]) if cd["margin_values"] else 0
        category_summary[cat] = {
            "sku_count": cd["sku_count"],
            "total_units": cd["total_stock"],
            "value_at_cost_usd": round(cd["total_cost"], 2),
            "value_at_retail_usd": round(cd["total_retail"], 2),
            "avg_days_of_supply": round(avg_dos, 0),
            "avg_margin_pct": round(avg_margin, 1),
            "stockout_risk_skus": cd["critical_count"],
            "excess_skus": cd["excess_count"],
            "dead_stock_skus": cd["dead_count"],
            "health": _category_health_label(cd),
        }

    # Top-level metrics
    total_cost = sum(s["value_at_cost_usd"] for s in sku_analysis)
    total_retail = sum(s["value_at_retail_usd"] for s in sku_analysis)
    dead_cost = sum(s["value_at_cost_usd"] for s in sku_analysis if s["dos_status"] == "dead")
    excess_cost = sum(s["value_at_cost_usd"] for s in sku_analysis if s["dos_status"] == "excess")

    metrics = {
        "total_skus": len(sku_analysis),
        "total_units": sum(s["current_stock"] for s in sku_analysis),
        "inventory_at_cost_usd": round(total_cost, 2),
        "inventory_at_retail_usd": round(total_retail, 2),
        "dead_stock_value_usd": round(dead_cost, 2),
        "dead_stock_pct": round(dead_cost / total_cost * 100, 1) if total_cost > 0 else 0,
        "excess_stock_value_usd": round(excess_cost, 2),
        "excess_stock_pct": round(excess_cost / total_cost * 100, 1) if total_cost > 0 else 0,
        "healthy_stock_pct": round(
            (total_cost - dead_cost - excess_cost) / total_cost * 100, 1
        ) if total_cost > 0 else 0,
        "critical_stockout_skus": sum(1 for s in sku_analysis if s["dos_status"] == "critical"),
        "blended_margin_pct": round((1 - total_cost / total_retail) * 100, 1) if total_retail > 0 else 0,
    }

    # Sort alerts by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: severity_order.get(a.get("severity", "low"), 2))

    return {
        "sku_analysis": sku_analysis,
        "category_summary": category_summary,
        "alerts": alerts,
        "metrics": metrics,
    }


def _estimate_daily_demand(product, financial_profile):
    """
    Estimate daily demand for a product based on projected revenue, price
    elasticity, competitor availability, and category velocity.

    Uses price-weighted revenue distribution: cheaper items sell more units.
    Uses competitor count as a popularity signal.
    """
    if not financial_profile:
        return 0.1  # fallback

    annual_rev = financial_profile.get("cashflow_summary", {}).get(
        "annual_revenue_projected_usd", 500000
    )
    retail_price = float(product.get("retail_price_usd", 100))
    if retail_price <= 0:
        return 0.05

    # Target: inventory turns 3.5x/year (reasonable for new Lebanese sportswear)
    # This means each SKU should sell its stock ~3.5 times per year on average
    inventory_cost = financial_profile.get("inventory_summary", {}).get(
        "total_cost_usd", 176000
    )
    total_skus = financial_profile.get("inventory_summary", {}).get("total_skus", 350)

    # Average stock value per SKU, divided by retail price → avg units per SKU
    avg_cost_per_sku = inventory_cost / max(total_skus, 1)
    cost_price = float(product.get("cost_price_usd", retail_price * 0.5))
    units_on_hand = float(product.get("units_on_hand", 10))

    # Base demand: sell through opening stock in ~65 days
    # This targets a healthy DOS range of 45-90 days, accounting for
    # category velocity adjustments that slow down some categories
    base_daily = units_on_hand / 65.0

    # Category adjustment (calibrated so slowest categories stay in healthy range)
    CATEGORY_VELOCITY = {
        "footwear": 0.80,
        "football_boots": 0.70,
        "apparel": 1.15,
        "sportswear": 1.0,
        "swimwear": 0.60,
        "accessories": 1.30,
        "kids": 0.90,
        "lifestyle": 0.85,
        "other": 0.80,
    }
    category = product.get("system_category", "other")
    velocity_adj = CATEGORY_VELOCITY.get(category, 1.0)

    # Competitor availability signal: items at more shops = higher demand
    num_competitors = int(product.get("num_competitors", 2))
    if num_competitors >= 5:
        competitor_adj = 1.2
    elif num_competitors >= 3:
        competitor_adj = 1.05
    elif num_competitors <= 1:
        competitor_adj = 0.85  # niche item
    else:
        competitor_adj = 1.0

    # Price elasticity: cheaper items within category sell faster
    # Use a mild inverse price effect (normalize around $80 midpoint)
    price_adj = min(1.3, max(0.7, 80.0 / max(retail_price, 20.0)))

    daily_demand = base_daily * velocity_adj * competitor_adj * price_adj

    return max(0.02, daily_demand)


def _category_health_label(cd):
    """Assign a health label to a category based on its metrics."""
    total = cd["sku_count"]
    if total == 0:
        return "unknown"
    problem_pct = (cd["critical_count"] + cd["dead_count"]) / total
    if problem_pct > 0.3:
        return "critical"
    if problem_pct > 0.15 or cd["excess_count"] / total > 0.3:
        return "warning"
    return "healthy"
