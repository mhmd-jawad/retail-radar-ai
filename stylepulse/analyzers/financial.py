"""
Financial health analyzer.

Evaluates balance sheet strength, cash flow health, and profitability
through the lens of a Lebanese retail business.
"""

from . import thresholds as T


def analyze(financial_profile, balance_sheet, cashflow, inventory_results):
    """
    Analyze financial health of the business.

    Returns dict with:
        - balance_sheet_health: asset quality, liquidity
        - cashflow_health: burn rate, runway, breakeven
        - profitability: margins, OpEx efficiency
        - alerts: financial warnings
        - metrics: top-level financial metrics
    """
    fp = financial_profile
    alerts = []

    # ── Balance Sheet Analysis ─────────────────────────────────────────
    bs_summary = fp.get("balance_sheet_summary", {})
    total_assets = bs_summary.get("total_assets_usd", 0)
    total_liabilities = bs_summary.get("total_liabilities_usd", 0)
    total_equity = bs_summary.get("total_equity_usd", 0)
    current_ratio = bs_summary.get("current_ratio")
    if current_ratio is None:
        current_ratio = 0
    inventory_pct = bs_summary.get("inventory_pct_of_assets", 0)

    inv_metrics = inventory_results.get("metrics", {})
    dead_stock_pct = inv_metrics.get("dead_stock_pct", 0)
    dead_stock_value = inv_metrics.get("dead_stock_value_usd", 0)

    # Current ratio assessment
    if current_ratio >= T.CURRENT_RATIO_HEALTHY:
        liquidity_status = "healthy"
    elif current_ratio >= T.CURRENT_RATIO_WARNING:
        liquidity_status = "adequate"
        alerts.append({
            "severity": "medium",
            "type": "liquidity_warning",
            "message": f"Current ratio is {current_ratio:.1f}x — adequate but below the {T.CURRENT_RATIO_HEALTHY}x "
                       f"target for Lebanon's cash-constrained environment.",
        })
    else:
        liquidity_status = "critical"
        alerts.append({
            "severity": "high",
            "type": "liquidity_critical",
            "message": f"Current ratio is {current_ratio:.1f}x — critically low for Lebanon. "
                       f"Prioritize collecting receivables and reducing supplier obligations.",
        })

    # Inventory concentration
    if inventory_pct > T.INVENTORY_PCT_OF_ASSETS_MAX:
        alerts.append({
            "severity": "high",
            "type": "inventory_concentration",
            "message": f"{inventory_pct:.0f}% of total assets are locked in inventory. "
                       f"This is dangerously high — if demand slows, cash dries up fast. "
                       f"Target below {T.INVENTORY_PCT_OF_ASSETS_WARNING}%.",
        })
    elif inventory_pct > T.INVENTORY_PCT_OF_ASSETS_WARNING:
        alerts.append({
            "severity": "medium",
            "type": "inventory_concentration",
            "message": f"{inventory_pct:.0f}% of assets in inventory. "
                       f"Watch this — it's approaching the {T.INVENTORY_PCT_OF_ASSETS_MAX}% danger zone.",
        })

    balance_sheet_health = {
        "total_assets_usd": total_assets,
        "total_liabilities_usd": total_liabilities,
        "total_equity_usd": total_equity,
        "current_ratio": current_ratio,
        "liquidity_status": liquidity_status,
        "inventory_pct_of_assets": inventory_pct,
        "dead_stock_pct_of_inventory": dead_stock_pct,
        "dead_stock_value_usd": dead_stock_value,
        "equity_quality": "solid" if dead_stock_pct < 10 else "impaired",
    }

    # ── Cash Flow Analysis ─────────────────────────────────────────────
    cf_summary = fp.get("cashflow_summary", {})
    cash_runway = cf_summary.get("cash_runway_months", 0)
    monthly_fixed = cf_summary.get("monthly_fixed_opex_usd", 0)
    breakeven_revenue = cf_summary.get("breakeven_monthly_revenue_usd", 0)
    annual_revenue = cf_summary.get("annual_revenue_projected_usd", 0)

    if cash_runway >= T.CASH_RUNWAY_SAFE:
        runway_status = "safe"
    elif cash_runway >= T.CASH_RUNWAY_WARNING:
        runway_status = "adequate"
        alerts.append({
            "severity": "medium",
            "type": "cash_runway",
            "message": f"Cash runway is {cash_runway:.1f} months. "
                       f"Target {T.CASH_RUNWAY_SAFE} months minimum for Lebanon.",
        })
    else:
        runway_status = "critical"
        alerts.append({
            "severity": "high",
            "type": "cash_runway_critical",
            "message": f"Only {cash_runway:.1f} months of cash runway. "
                       f"This is dangerous — one slow month could mean missing rent or salaries. "
                       f"Liquidate slow inventory immediately to build cash buffer.",
        })

    # Monthly burn analysis from cashflow template
    months_positive = 0
    months_negative = 0
    worst_month = None
    best_month = None

    for cf in cashflow:
        net = float(cf.get("net_cash_movement_usd", 0))
        month_name = cf.get("month_name", "")
        if net >= 0:
            months_positive += 1
        else:
            months_negative += 1
        if worst_month is None or net < worst_month[1]:
            worst_month = (month_name, net)
        if best_month is None or net > best_month[1]:
            best_month = (month_name, net)

    cashflow_health = {
        "cash_runway_months": cash_runway,
        "runway_status": runway_status,
        "monthly_fixed_opex_usd": monthly_fixed,
        "breakeven_monthly_revenue_usd": breakeven_revenue,
        "projected_annual_revenue_usd": annual_revenue,
        "months_cash_positive": months_positive,
        "months_cash_negative": months_negative,
        "best_month": {"name": best_month[0], "net_cash_usd": round(best_month[1], 2)} if best_month else None,
        "worst_month": {"name": worst_month[0], "net_cash_usd": round(worst_month[1], 2)} if worst_month else None,
    }

    if months_negative > 3:
        alerts.append({
            "severity": "medium",
            "type": "seasonal_cash_drain",
            "message": f"{months_negative} months are projected cash-negative. "
                       f"Build reserves during peak months ({best_month[0]}) "
                       f"to survive slow months ({worst_month[0]}).",
        })

    # ── Profitability ──────────────────────────────────────────────────
    blended_margin = inv_metrics.get("blended_margin_pct", 0)
    annual_fixed_opex = monthly_fixed * 12
    annual_gross_profit = annual_revenue * (blended_margin / 100) if blended_margin > 0 else 0
    opex_coverage = round(annual_gross_profit / annual_fixed_opex, 2) if annual_fixed_opex > 0 else 0

    profitability = {
        "blended_margin_pct": blended_margin,
        "annual_gross_profit_projected_usd": round(annual_gross_profit, 2),
        "annual_fixed_opex_usd": annual_fixed_opex,
        "opex_coverage_ratio": opex_coverage,
        "margin_health": "healthy" if blended_margin >= T.MARGIN_HEALTHY else (
            "warning" if blended_margin >= T.MARGIN_FLOOR else "critical"
        ),
    }

    if opex_coverage < 1.5:
        alerts.append({
            "severity": "high",
            "type": "opex_coverage",
            "message": f"Gross profit covers fixed costs only {opex_coverage:.1f}x. "
                       f"Target at least 2.0x to have margin for variable costs and profit. "
                       f"Either increase volume/prices or cut fixed costs.",
        })

    # Sort alerts
    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: severity_order.get(a.get("severity", "low"), 2))

    return {
        "balance_sheet_health": balance_sheet_health,
        "cashflow_health": cashflow_health,
        "profitability": profitability,
        "alerts": alerts,
    }
