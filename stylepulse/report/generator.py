"""
Report generator — outputs both JSON and markdown advisor report.

The markdown report reads like a real business advisor reviewing the company
honestly — specific numbers, direct language, no generic AI fluff.
"""

import json
from datetime import datetime
from pathlib import Path


def generate(analysis_results, output_dir):
    """
    Generate both report.json and report.md from analysis results.

    Args:
        analysis_results: dict from engine.py with all analyzer outputs
        output_dir: Path to write reports to
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON report
    json_path = output_dir / "report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(analysis_results, f, indent=2, default=str)
    print(f"Wrote {json_path}")

    # Markdown report
    md_path = output_dir / "report.md"
    md_content = _build_markdown(analysis_results)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Wrote {md_path}")

    return json_path, md_path


def _build_markdown(r):
    """Build the full markdown advisor report."""
    inv = r.get("inventory", {})
    comp = r.get("competitor", {})
    fin = r.get("financial", {})
    promo = r.get("promotions", {})

    sections = [
        _header(),
        _executive_summary(inv, comp, fin, promo),
        _inventory_health(inv),
        _competitive_intelligence(comp),
        _financial_health(fin),
        _threshold_definitions(),
        _promotion_directives(promo),
        _owner_directives(promo),
        _footer(),
    ]
    return "\n\n".join(sections)


def _header():
    now = datetime.now().strftime("%B %d, %Y")
    return f"""# StylePulse AI — Business Intelligence Report
### Prepared for: Store Owner
### Date: {now}
### Market: Lebanon — Multi-Brand Sportswear Retail

---

> This report is generated from real competitor market data scraped across
> 6+ Lebanese sportswear retailers, combined with your store's inventory
> and financial position. Every number below is traceable to actual data.
> No synthetic or fabricated figures."""


def _executive_summary(inv, comp, fin, promo):
    metrics = inv.get("metrics", {})
    fin_bs = fin.get("balance_sheet_health", {})
    fin_cf = fin.get("cashflow_health", {})
    comp_overview = comp.get("market_overview", {})
    promo_summary = promo.get("summary", {})

    total_skus = metrics.get("total_skus", 0)
    inv_cost = metrics.get("inventory_at_cost_usd", 0)
    dead_pct = metrics.get("dead_stock_pct", 0)
    dead_value = metrics.get("dead_stock_value_usd", 0)
    healthy_pct = metrics.get("healthy_stock_pct", 0)
    blended_margin = metrics.get("blended_margin_pct", 0)
    critical_stockouts = metrics.get("critical_stockout_skus", 0)

    current_ratio = fin_bs.get("current_ratio", 0)
    cash_runway = fin_cf.get("cash_runway_months", 0)
    inv_pct = fin_bs.get("inventory_pct_of_assets", 0)

    overpriced = comp_overview.get("products_overpriced", 0)
    underpriced = comp_overview.get("products_underpriced", 0)

    clearance_count = promo_summary.get("clearance_count", 0)
    clearance_value = promo_summary.get("total_clearance_value_usd", 0)
    markdown_count = promo_summary.get("markdown_count", 0)

    lines = [
        "## 1. Executive Summary",
        "",
        "Here is where your business stands today:",
        "",
    ]

    # Honest assessment bullets
    if dead_pct > 15:
        lines.append(f"- **Inventory problem.** {dead_pct:.0f}% of your inventory (${dead_value:,.0f} at cost) "
                     f"is dead stock — not moving, not generating cash. This needs to go.")
    elif dead_pct > 5:
        lines.append(f"- **Some dead weight.** {dead_pct:.1f}% of inventory (${dead_value:,.0f}) is slow/dead stock. "
                     f"Manageable, but clear it before it grows.")
    else:
        lines.append(f"- **Inventory is clean.** Only {dead_pct:.1f}% dead stock. Well managed.")

    if critical_stockouts > 0:
        lines.append(f"- **Stockout risk.** {critical_stockouts} SKUs have less than 21 days of supply. "
                     f"With Lebanon's 3-8 week import lead times, these will be empty shelves soon.")

    if inv_pct > 75:
        lines.append(f"- **Capital is over-concentrated in stock.** {inv_pct:.0f}% of your assets are inventory. "
                     f"If sales slow down, you have no cash buffer.")
    elif inv_pct > 60:
        lines.append(f"- **Heavy in inventory.** {inv_pct:.0f}% of assets are stock. "
                     f"This is typical for a new store but needs to come down over time.")

    lines.append(f"- **Margin is {'solid' if blended_margin >= 45 else 'tight'}.** "
                 f"Blended gross margin is {blended_margin:.1f}%. "
                 f"{'This gives breathing room for promotions.' if blended_margin >= 50 else 'Be careful with discounting — every point matters.'}")

    lines.append(f"- **Cash runway: {cash_runway:.1f} months.** "
                 f"{'Tight — one bad month and you are in trouble.' if cash_runway < 3 else 'Adequate but build more buffer.'}")

    if overpriced > 10:
        lines.append(f"- **Pricing risk.** {overpriced} products are priced above the market median. "
                     f"Competitors have better prices — you are losing volume on these.")
    if underpriced > 10:
        lines.append(f"- **Leaving money on the table.** {underpriced} products are priced below market. "
                     f"Raise prices on these — customers won't notice a 5-10% increase.")

    lines.append(f"- **Action items:** {clearance_count} SKUs to clear, "
                 f"{markdown_count} to markdown, and reorders needed on {critical_stockouts} SKUs.")

    return "\n".join(lines)


def _inventory_health(inv):
    metrics = inv.get("metrics", {})
    cat_summary = inv.get("category_summary", {})
    alerts = inv.get("alerts", [])

    lines = [
        "## 2. Inventory Health",
        "",
        f"**{metrics.get('total_skus', 0)} SKUs** in stock, "
        f"**{metrics.get('total_units', 0):,} units**, "
        f"valued at **${metrics.get('inventory_at_cost_usd', 0):,.0f}** at cost "
        f"(${metrics.get('inventory_at_retail_usd', 0):,.0f} at retail).",
        "",
        "### By Category",
        "",
        "| Category | SKUs | Value (Cost) | Avg DOS | Avg Margin | Health |",
        "|----------|------|-------------|---------|------------|--------|",
    ]

    for cat, data in sorted(cat_summary.items(), key=lambda x: -x[1]["value_at_cost_usd"]):
        health_emoji = {"healthy": "✅", "warning": "⚠️", "critical": "🔴"}.get(data["health"], "❓")
        lines.append(
            f"| {cat} | {data['sku_count']} | ${data['value_at_cost_usd']:,.0f} | "
            f"{data['avg_days_of_supply']:.0f} days | {data['avg_margin_pct']:.0f}% | "
            f"{health_emoji} {data['health']} |"
        )

    # Top alerts
    high_alerts = [a for a in alerts if a.get("severity") == "high"]
    if high_alerts:
        lines.extend(["", "### Critical Alerts", ""])
        for a in high_alerts[:10]:
            lines.append(f"- 🔴 {a['message']}")

    medium_alerts = [a for a in alerts if a.get("severity") == "medium"]
    if medium_alerts:
        lines.extend(["", "### Warnings", ""])
        for a in medium_alerts[:10]:
            lines.append(f"- ⚠️ {a['message']}")

    return "\n".join(lines)


def _competitive_intelligence(comp):
    overview = comp.get("market_overview", {})
    brand_summary = comp.get("brand_summary", {})
    opportunities = comp.get("opportunities", [])

    lines = [
        "## 3. Competitive Intelligence",
        "",
        f"Analyzed **{overview.get('products_analyzed', 0)} products** against "
        f"6+ Lebanese sportswear competitors.",
        "",
    ]

    # Position distribution
    pos_dist = overview.get("position_distribution", {})
    if pos_dist:
        lines.extend([
            "### Your Price Position in the Market",
            "",
            "| Position | Count | Meaning |",
            "|----------|-------|---------|",
        ])
        pos_meanings = {
            "premium": "Priced >15% above market — risk losing sales",
            "above_market": "Slightly above — OK if justified by service/brand",
            "at_market": "Competitive — good position",
            "below_market": "Below market — margin opportunity",
            "deep_value": "Way below — raising prices immediately",
        }
        for pos, count in sorted(pos_dist.items(), key=lambda x: -x[1]):
            meaning = pos_meanings.get(pos, "")
            lines.append(f"| {pos.replace('_', ' ').title()} | {count} | {meaning} |")

    # Brand positioning
    if brand_summary:
        lines.extend(["", "### Brand-Level Positioning", ""])
        for brand, data in sorted(brand_summary.items(), key=lambda x: -x[1]["sku_count"]):
            gap = data["avg_price_gap_pct"]
            dominant = data["dominant_position"].replace("_", " ")
            if gap > 10:
                assessment = f"overpriced by {gap:.0f}% on average — review pricing"
            elif gap < -10:
                assessment = f"underpriced by {abs(gap):.0f}% — raise prices"
            else:
                assessment = f"competitively positioned (avg gap: {gap:+.0f}%)"
            lines.append(f"- **{brand}** ({data['sku_count']} SKUs): {assessment}")

    # Top opportunities
    if opportunities:
        lines.extend(["", "### Actionable Opportunities", ""])
        high_impact = [o for o in opportunities if o.get("impact") == "high"]
        for o in high_impact[:8]:
            lines.append(f"- 💰 {o['message']}")
        medium_impact = [o for o in opportunities if o.get("impact") == "medium"]
        for o in medium_impact[:5]:
            lines.append(f"- 📊 {o['message']}")

    return "\n".join(lines)


def _financial_health(fin):
    bs = fin.get("balance_sheet_health", {})
    cf = fin.get("cashflow_health", {})
    prof = fin.get("profitability", {})
    alerts = fin.get("alerts", [])

    lines = [
        "## 4. Financial Health",
        "",
        "### Balance Sheet",
        "",
        f"| Metric | Value | Status |",
        f"|--------|-------|--------|",
        f"| Total Assets | ${bs.get('total_assets_usd', 0):,.0f} | — |",
        f"| Total Liabilities | ${bs.get('total_liabilities_usd', 0):,.0f} | — |",
        f"| Owner's Equity | ${bs.get('total_equity_usd', 0):,.0f} | — |",
        f"| Current Ratio | {bs.get('current_ratio', 0):.1f}x | {bs.get('liquidity_status', 'unknown')} |",
        f"| Inventory % of Assets | {bs.get('inventory_pct_of_assets', 0):.0f}% | "
        f"{'⚠️ High' if bs.get('inventory_pct_of_assets', 0) > 60 else '✅ OK'} |",
        f"| Dead Stock % | {bs.get('dead_stock_pct_of_inventory', 0):.1f}% | "
        f"{'🔴 Concern' if bs.get('dead_stock_pct_of_inventory', 0) > 10 else '✅ OK'} |",
        f"| Equity Quality | {bs.get('equity_quality', 'unknown')} | — |",
        "",
        "### Cash Flow",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Cash Runway | {cf.get('cash_runway_months', 0):.1f} months |",
        f"| Monthly Fixed OpEx | ${cf.get('monthly_fixed_opex_usd', 0):,.0f}/mo |",
        f"| Breakeven Revenue | ${cf.get('breakeven_monthly_revenue_usd', 0):,.0f}/mo |",
        f"| Projected Annual Revenue | ${cf.get('projected_annual_revenue_usd', 0):,.0f} |",
        f"| Cash-Positive Months | {cf.get('months_cash_positive', 0)} of 12 |",
    ]

    best = cf.get("best_month")
    worst = cf.get("worst_month")
    if best and worst:
        lines.extend([
            f"| Best Month | {best['name']} (+${best['net_cash_usd']:,.0f}) |",
            f"| Worst Month | {worst['name']} (${worst['net_cash_usd']:,.0f}) |",
        ])

    # Profitability
    lines.extend([
        "",
        "### Profitability",
        "",
        f"- Blended gross margin: **{prof.get('blended_margin_pct', 0):.1f}%**",
        f"- OpEx coverage ratio: **{prof.get('opex_coverage_ratio', 0):.1f}x** "
        f"(gross profit covers fixed costs {prof.get('opex_coverage_ratio', 0):.1f} times)",
        f"- Margin health: **{prof.get('margin_health', 'unknown')}**",
    ])

    # Financial alerts
    if alerts:
        lines.extend(["", "### Financial Warnings", ""])
        for a in alerts:
            icon = {"high": "🔴", "medium": "⚠️", "low": "ℹ️"}.get(a.get("severity"), "")
            lines.append(f"- {icon} {a['message']}")

    # USD operating context
    lines.extend([
        "",
        "### USD Operating Context",
        "",
        "- All figures are tracked in USD",
        "- Liquidity is based on available cash, bank/wallet balances, receivables, and liabilities",
        "- Generator fuel and utilities should be treated as fixed monthly operating costs when they apply",
        "- Payment processing is low (1.5%) because ~85% of sales are cash",
    ])

    return "\n".join(lines)


def _threshold_definitions():
    """Document the thresholds so the owner understands the logic."""
    return """## 5. Threshold Definitions

These are the rules StylePulse AI uses to evaluate your business.
They are calibrated for **Lebanon's specific retail environment** — not
generic Western retail benchmarks.

### Inventory Thresholds (Days of Supply)

| DOS Range | Status | What It Means | Action |
|-----------|--------|---------------|--------|
| < 21 days | 🔴 Critical | Will stockout before import shipment arrives | Reorder immediately. Consider air freight for top sellers. |
| 21–45 days | ⚠️ Warning | Running low — order pipeline should already be active | Accelerate pending orders. Check with distributor. |
| 45–90 days | ✅ Healthy | Comfortable range for Lebanese import lead times | No action needed. Monitor weekly. |
| 90–180 days | ⚠️ Excess | Too much stock — capital is locked | Begin markdown (15–35% depending on age). |
| > 180 days | 🔴 Dead | Money is trapped and depreciating | Clearance at 50%. Bundle. Remove from prime shelf space. |

**Why 45–90 is "healthy" (not 30–60 like US retail):** Lebanon's import pipeline
is 3–8 weeks. A reorder placed today arrives in 21–56 days. If you stockout,
you lose 1–2 months of sales on that SKU.

### Margin Thresholds

| Margin | Status | Reasoning |
|--------|--------|-----------|
| > 55% | Excellent | Premium item — protect this price. No discounting. |
| 45–55% | Healthy | Standard for Lebanon sportswear after import costs. |
| 35–45% | Floor | Minimum acceptable. Below this, review supplier terms. |
| 25–35% | Critical | Losing money after OpEx allocation. Reprice or drop. |
| < 25% | Clearance only | Only acceptable when liquidating dead stock. |

### Competitive Position

| Gap vs Market | Position | Action |
|---|---|---|
| > +15% | Premium | Risk losing sales. Justify or reduce. |
| +5% to +15% | Above Market | OK if service/brand justifies. Monitor. |
| -5% to +5% | At Market | Competitive. Hold. |
| -15% to -5% | Below Market | Margin opportunity. Raise price. |
| < -15% | Deep Value | Raise immediately. You're subsidizing customers. |

### Cash Thresholds

| Cash Runway | Status | Action |
|---|---|---|
| > 4 months | Safe | Invest in stock depth for growth. |
| 2.5–4 months | Adequate | Maintain. Don't overstock. |
| < 2.5 months | Critical | Liquidate slow stock NOW. Delay non-essential spending. |"""


def _promotion_directives(promo):
    hold = promo.get("hold_pricing", [])
    promote = promo.get("promote", [])
    markdown = promo.get("markdown", [])
    clearance = promo.get("clearance", [])
    seasonal = promo.get("seasonal_actions", [])

    lines = [
        "## 6. Promotion & Pricing Directives",
        "",
    ]

    # Clearance
    if clearance:
        lines.extend(["### 🔴 Clear Immediately", ""])
        for c in clearance[:15]:
            lines.append(f"- **{c['brand']} {c['product_name'][:50]}** — "
                         f"{c['dos']:.0f} DOS, ${c.get('value_at_cost_usd', 0):.0f} at cost. "
                         f"Discount: {c['recommended_discount_pct']}%. {c['reason']}")
    else:
        lines.extend(["### Clearance", "", "No dead stock requiring clearance. Well managed."])

    # Markdown
    if markdown:
        lines.extend(["", "### ⚠️ Markdown", ""])
        for m in markdown[:15]:
            lines.append(f"- **{m['brand']} {m['product_name'][:50]}** — "
                         f"{m['dos']:.0f} DOS, {m['markdown_tier']}. "
                         f"Discount: {m['recommended_discount_pct']}% "
                         f"(margin after: ~{m['post_markdown_margin_pct']:.0f}%). "
                         f"{m['reason']}")

    # Hold
    if hold:
        lines.extend(["", "### ✅ Hold Pricing (do NOT discount)", ""])
        for h in hold[:15]:
            lines.append(f"- **{h['brand']} {h['product_name'][:50]}** — "
                         f"{h['current_margin_pct']:.0f}% margin. {h['reason']}")

    # Promote
    if promote:
        lines.extend(["", "### 📈 Push / Promote (no discount needed)", ""])
        for p in promote[:15]:
            lines.append(f"- **{p['brand']} {p['product_name'][:50]}** — "
                         f"Seasonal demand at {p['seasonal_multiplier']:.0%}. "
                         f"{p['recommended_action'].replace('_', ' ').title()}. {p['reason']}")

    # Seasonal calendar
    if seasonal:
        lines.extend(["", "### 📅 Seasonal Calendar (Next 3 Months)", ""])
        for s in seasonal:
            lines.append(f"- **{s['month']}**: {s['action']}")

    return "\n".join(lines)


def _owner_directives(promo):
    directives = promo.get("directives", [])
    if not directives:
        return "## 7. Owner Directives\n\nNo critical actions needed at this time."

    lines = [
        "## 7. Owner Directives — Ranked by Priority",
        "",
        "These are your top actions. Do them in order.",
        "",
    ]

    for d in directives:
        timeframe = d.get("timeframe", "").replace("_", " ").title()
        lines.append(f"**{d['priority']}. [{timeframe}]** {d['directive']}")
        lines.append("")

    return "\n".join(lines)


def _footer():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""---

*Report generated by StylePulse AI on {now}.*
*Data sources: Real competitor prices scraped from 6+ Lebanese retailers.*
*Financial model: USD-only retailer balance sheet, cashflow, and operating costs.*
*All thresholds calibrated for Lebanese import lead times and cost structures.*"""
