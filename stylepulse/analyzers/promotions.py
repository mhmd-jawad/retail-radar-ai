"""
Promotion and pricing directive analyzer.

Determines when to promote, markdown, hold pricing, or clear stock
based on inventory health, competitive position, seasonality, and cash flow.
"""

from datetime import datetime
import calendar

from . import thresholds as T


def analyze(products, inventory_results, competitor_results, financial_results):
    """
    Generate promotion and pricing directives.

    Returns dict with:
        - hold_pricing: SKUs where price should be maintained
        - promote: SKUs to actively promote (ads, placement, bundles)
        - markdown: SKUs needing price reduction
        - clearance: SKUs to clear aggressively
        - seasonal_actions: time-based actions for upcoming months
        - directives: prioritized list of owner actions
    """
    current_month = datetime.now().month
    seasonal_mult = T.get_seasonal_multiplier(current_month)

    inv_skus = {s["sku_id"]: s for s in inventory_results.get("sku_analysis", [])}
    comp_skus = {s["sku_id"]: s for s in competitor_results.get("sku_positioning", [])}
    comp_opps = competitor_results.get("opportunities", [])
    pricing_power_skus = {o["sku_id"] for o in comp_opps if o["type"] == "pricing_power"}

    financial_alerts = financial_results.get("alerts", [])
    cash_tight = any(a["type"] in ("cash_runway_critical", "cash_runway") for a in financial_alerts)

    hold_pricing = []
    promote = []
    markdown = []
    clearance = []

    for prod in products:
        sku_id = prod["sku_id"]
        inv = inv_skus.get(sku_id, {})
        comp = comp_skus.get(sku_id, {})

        dos = inv.get("days_of_supply", 9999)
        dos_status = inv.get("dos_status", "unknown")
        margin_pct = inv.get("margin_pct", 0)
        current_stock = inv.get("current_stock", 0)
        brand = prod.get("brand", "Unknown")
        name = prod.get("product_name", "")
        category = prod.get("system_category", "other")
        retail_price = float(prod.get("retail_price_usd", 0))

        position = comp.get("position", "at_market")
        comps_oos = comp.get("competitors_out_of_stock", 0)
        comps_total = comp.get("num_competitors", 0)
        price_gap = comp.get("price_gap_pct", 0)

        cat_seasonal = T.get_seasonal_multiplier(current_month, category)

        # ── CLEARANCE: dead stock, cash recovery ──
        if dos_status == "dead" or (dos > T.DOS_DEAD and margin_pct < T.MARGIN_FLOOR):
            value_at_cost = inv.get("value_at_cost_usd", 0)
            clearance.append({
                "sku_id": sku_id,
                "brand": brand,
                "product_name": name,
                "category": category,
                "dos": dos,
                "current_stock": current_stock,
                "value_at_cost_usd": value_at_cost,
                "recommended_discount_pct": 50,
                "reason": f"DOS {dos:.0f} — dead stock. ${value_at_cost:.0f} locked up. "
                          f"Clear at 50% to recover cash.",
                "priority": "immediate" if cash_tight else "this_week",
            })
            continue

        # ── MARKDOWN: slow movers, competitive pressure ──
        md_rec = T.get_markdown_recommendation(dos)
        if md_rec and margin_pct > T.MARGIN_CRITICAL:
            # Don't markdown if competitors are out of stock (we have pricing power)
            if sku_id in pricing_power_skus:
                pass  # Skip to hold_pricing below
            else:
                markdown.append({
                    "sku_id": sku_id,
                    "brand": brand,
                    "product_name": name,
                    "category": category,
                    "dos": dos,
                    "current_stock": current_stock,
                    "current_margin_pct": margin_pct,
                    "recommended_discount_pct": md_rec["discount_pct"],
                    "markdown_tier": md_rec["label"],
                    "post_markdown_margin_pct": round(margin_pct - md_rec["discount_pct"] * (margin_pct / 100), 1),
                    "reason": _markdown_reason(dos, position, price_gap, comps_oos, comps_total),
                    "priority": "this_week" if dos > 150 else "this_month",
                })
                continue

        # ── HOLD PRICING: strong position, competitors struggling ──
        if sku_id in pricing_power_skus or (
            dos_status in ("healthy", "warning") and
            position in ("at_market", "below_market") and
            margin_pct >= T.MARGIN_HEALTHY
        ):
            hold_pricing.append({
                "sku_id": sku_id,
                "brand": brand,
                "product_name": name,
                "category": category,
                "dos": dos,
                "current_margin_pct": margin_pct,
                "position": position,
                "competitors_oos": comps_oos,
                "reason": _hold_reason(sku_id, pricing_power_skus, position, comps_oos, margin_pct),
            })
            continue

        # ── PROMOTE: seasonal opportunity, good margin, sufficient stock ──
        if (cat_seasonal >= 1.10 and dos > 20 and dos < 120 and margin_pct >= T.MARGIN_FLOOR):
            promote.append({
                "sku_id": sku_id,
                "brand": brand,
                "product_name": name,
                "category": category,
                "dos": dos,
                "current_margin_pct": margin_pct,
                "seasonal_multiplier": cat_seasonal,
                "recommended_action": "feature_placement" if margin_pct > T.MARGIN_HEALTHY else "bundle_deal",
                "reason": f"Seasonal demand is {cat_seasonal:.0%} of baseline. "
                          f"Good margin ({margin_pct:.0f}%) and sufficient stock ({dos:.0f} DOS). "
                          f"Push this now.",
                "priority": "this_week",
            })

    # ── Seasonal Actions ──────────────────────────────────────────
    seasonal_actions = _build_seasonal_actions(current_month, inventory_results, cash_tight)

    # ── Owner Directives (ranked) ─────────────────────────────────
    directives = _build_directives(
        hold_pricing, promote, markdown, clearance, seasonal_actions,
        financial_results, inventory_results, competitor_results
    )

    return {
        "hold_pricing": hold_pricing,
        "promote": promote,
        "markdown": markdown,
        "clearance": clearance,
        "seasonal_actions": seasonal_actions,
        "directives": directives,
        "summary": {
            "hold_count": len(hold_pricing),
            "promote_count": len(promote),
            "markdown_count": len(markdown),
            "clearance_count": len(clearance),
            "total_clearance_value_usd": round(sum(c.get("value_at_cost_usd", 0) for c in clearance), 2),
            "total_markdown_skus": len(markdown),
        },
    }


def _markdown_reason(dos, position, price_gap, comps_oos, comps_total):
    """Generate a specific reason string for a markdown recommendation."""
    parts = [f"DOS is {dos:.0f} days (excess stock)."]
    if position == "premium":
        parts.append(f"Priced {price_gap:.0f}% above market — customers have cheaper options.")
    if comps_total > 0:
        in_stock = comps_total - comps_oos
        parts.append(f"{in_stock} of {comps_total} competitors still have this in stock.")
    return " ".join(parts)


def _hold_reason(sku_id, pricing_power_skus, position, comps_oos, margin_pct):
    """Generate a specific reason string for holding price."""
    parts = []
    if sku_id in pricing_power_skus:
        parts.append(f"{comps_oos} competitors are out of stock on this item — you have pricing power.")
    if position in ("at_market", "below_market"):
        parts.append(f"Already competitively priced ({position.replace('_', ' ')}).")
    if margin_pct >= T.MARGIN_HEALTHY:
        parts.append(f"Margin is healthy at {margin_pct:.0f}%.")
    return " ".join(parts) if parts else "No reason to discount — maintain price."


def _build_seasonal_actions(current_month, inventory_results, cash_tight):
    """Build forward-looking seasonal action calendar."""
    actions = []

    next_3_months = [(current_month + i - 1) % 12 + 1 for i in range(1, 4)]

    for m in next_3_months:
        mult = T.get_seasonal_multiplier(m)
        name = calendar.month_name[m]

        if mult >= 1.15:
            actions.append({
                "month": name,
                "signal": "peak_demand",
                "multiplier": mult,
                "action": f"{name}: peak demand period ({mult:.0%} of baseline). "
                          f"Ensure stock is deep on core items. Hold prices firm. "
                          f"This is when you build cash reserves.",
            })
        elif mult <= 0.80:
            action_text = f"{name}: slow period ({mult:.0%} of baseline). "
            if cash_tight:
                action_text += "Run targeted promotions to maintain cash flow. Clear excess stock now."
            else:
                action_text += "Minimize new orders. Use this time for clearance and store improvements."
            actions.append({
                "month": name,
                "signal": "slow_period",
                "multiplier": mult,
                "action": action_text,
            })
        else:
            actions.append({
                "month": name,
                "signal": "normal",
                "multiplier": mult,
                "action": f"{name}: normal demand ({mult:.0%}). Maintain regular operations.",
            })

    # Lebanon-specific events
    # Ramadan shifts yearly; approximate for 2026
    if current_month in (2, 3):
        actions.append({
            "month": "Ramadan (approx. Feb-Mar 2026)",
            "signal": "event",
            "multiplier": 0.85,
            "action": "Ramadan: daytime foot traffic drops ~30%. "
                      "Shift marketing to evening hours. "
                      "Athletic wear demand increases post-iftar for exercise.",
        })
    if current_month in (8, 9):
        actions.append({
            "month": "Back to School (Aug-Sep)",
            "signal": "event",
            "multiplier": 1.30,
            "action": "Back-to-school: biggest sales window. "
                      "Stock kids footwear and school-appropriate sportswear deep. "
                      "Run bundles (shoes + bag, etc.).",
        })

    return actions


def _build_directives(hold, promote, markdown, clearance, seasonal,
                      financial_results, inventory_results, competitor_results):
    """Build prioritized list of 5-7 concrete owner directives."""
    directives = []
    priority = 1

    # Directive 1: Cash emergency (if applicable)
    fin_alerts = financial_results.get("alerts", [])
    critical_financial = [a for a in fin_alerts if a.get("severity") == "high"]
    if critical_financial:
        directives.append({
            "priority": priority,
            "timeframe": "this_week",
            "directive": critical_financial[0]["message"],
            "category": "financial",
        })
        priority += 1

    # Directive 2: Clear dead stock
    if clearance:
        total_value = sum(c.get("value_at_cost_usd", 0) for c in clearance)
        directives.append({
            "priority": priority,
            "timeframe": "this_week",
            "directive": f"Clear {len(clearance)} dead-stock SKUs worth ${total_value:,.0f} at cost. "
                         f"Run a 50% clearance on these items — recovering even $0.50 on the dollar "
                         f"frees up working capital for reorders.",
            "category": "inventory",
        })
        priority += 1

    # Directive 3: Markdown slow movers
    if markdown:
        directives.append({
            "priority": priority,
            "timeframe": "this_week",
            "directive": f"Apply markdowns to {len(markdown)} slow-moving SKUs. "
                         f"Start at 15-25% — don't go deeper unless they don't move in 2 weeks.",
            "category": "pricing",
        })
        priority += 1

    # Directive 4: Hold pricing on strong items
    if hold:
        directives.append({
            "priority": priority,
            "timeframe": "ongoing",
            "directive": f"Protect margins on {len(hold)} well-positioned SKUs. "
                         f"These items are selling well and/or competitors are out of stock. "
                         f"Do NOT discount these — they fund your business.",
            "category": "pricing",
        })
        priority += 1

    # Directive 5: Promote seasonal items
    if promote:
        directives.append({
            "priority": priority,
            "timeframe": "this_week",
            "directive": f"Push {len(promote)} seasonal items via Instagram/window placement. "
                         f"These have good margins and seasonal demand is peaking. "
                         f"No discount needed — just visibility.",
            "category": "marketing",
        })
        priority += 1

    # Directive 6: Reorder critical items
    inv_metrics = inventory_results.get("metrics", {})
    critical_stockout = inv_metrics.get("critical_stockout_skus", 0)
    if critical_stockout > 0:
        directives.append({
            "priority": priority,
            "timeframe": "immediate",
            "directive": f"{critical_stockout} SKUs are at risk of stockout (< {T.DOS_CRITICAL} days supply). "
                         f"Place reorders NOW — Lebanese import lead times are 3-8 weeks. "
                         f"Prioritize top-selling items and items where competitors are also low.",
            "category": "supply_chain",
        })
        priority += 1

    # Directive 7: Competitive pricing opportunities
    comp_overview = competitor_results.get("market_overview", {})
    underpriced = comp_overview.get("products_underpriced", 0)
    if underpriced > 5:
        directives.append({
            "priority": priority,
            "timeframe": "this_month",
            "directive": f"{underpriced} products are priced below market. "
                         f"Review these for price increases — you're leaving margin on the table.",
            "category": "pricing",
        })
        priority += 1

    # Seasonal directive
    peak_months = [s for s in seasonal if s.get("signal") == "peak_demand"]
    if peak_months:
        directives.append({
            "priority": priority,
            "timeframe": "this_month",
            "directive": peak_months[0]["action"],
            "category": "planning",
        })
        priority += 1

    return directives
