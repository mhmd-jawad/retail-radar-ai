"""
Plain-English explanation templates for all 26 IE2 features.

`explain_feature(name, value, shap_value, decision)` → human-readable string.

Used by SHAPEngine to convert raw SHAP values into owner-ready sentences.
All output is written for a Lebanese retail store owner to read.
"""

from __future__ import annotations


def explain_feature(name: str, value: float, shap_value: float, decision: str) -> str:
    """Return a plain-English explanation for a single SHAP feature contribution."""
    positive = shap_value > 0
    fn = _TEMPLATES.get(name)
    if fn:
        return fn(value, positive, decision)
    return f"{name} = {value:.2f} {'supports' if positive else 'reduces'} {decision}."


# ── Template registry ─────────────────────────────────────────────────────────

def _days_of_supply(v, pos, dec):
    if v < 14:
        return f"Only {v:.0f} days of stock left — risk of stocking out soon."
    if v > 120:
        return f"{v:.0f} days of supply — well above healthy range, stock is building up."
    return f"{v:.0f} days of supply — within healthy range (45–90 days)."

def _stock_coverage_ratio(v, pos, dec):
    pct = v * 100
    if pct < 20:
        return f"Stock covers only {pct:.0f}% of seasonal demand — running very lean."
    return f"Stock covers {pct:.0f}% of seasonal demand — adequate coverage."

def _stockout_risk(v, pos, dec):
    if v > 0.7:
        return "High stockout risk — reorder should be considered."
    return f"Stockout risk is low ({v:.0%})."

def _total_qty(v, pos, dec):
    if v < 15:
        return f"Only {v:.0f} units remain — protect from discounting."
    if v > 200:
        return f"{v:.0f} units on hand — large inventory position."
    return f"{v:.0f} units currently in stock."

def _inventory_vs_median(v, pos, dec):
    if v > 0.5:
        return f"Inventory is {v:.0%} above the category median — overstocked."
    if v < -0.3:
        return f"Inventory is {abs(v):.0%} below category median — lean stock."
    return "Inventory is close to the category median — normal level."

def _current_margin_pct(v, pos, dec):
    if v < 25:
        return f"Margin is only {v:.0f}% — below the 25% critical floor."
    if v > 50:
        return f"Healthy margin of {v:.0f}% — pricing power is strong."
    return f"Margin at {v:.0f}% — within acceptable range."

def _discount_depth_last_30d(v, pos, dec):
    if v == 0:
        return "No discounts applied in the last 30 days."
    return f"Last discount was {v:.0%} deep — recent promotion history."

def _days_since_last_discount(v, pos, dec):
    if v >= 999:
        return "No discount history recorded yet."
    if v < 21:
        return f"Only {v:.0f} days since last discount — too soon to discount again."
    return f"{v:.0f} days since last discount — safe to consider markdown."

def _days_at_current_price(v, pos, dec):
    if v > 60:
        return f"Price unchanged for {v:.0f} days — may need refresh."
    return f"Price set {v:.0f} days ago."

def _retail_price_usd(v, pos, dec):
    return f"Retail price is ${v:.0f}."

def _price_gap_pct(v, pos, dec):
    if v > 0.10:
        return f"You are {v:.0%} more expensive than the cheapest competitor."
    if v < -0.10:
        return f"You are {abs(v):.0%} cheaper than the market — you could raise the price."
    return f"Price is within {abs(v):.0%} of the market — competitive."

def _competitors_on_sale(v, pos, dec):
    if v >= 3:
        return f"{v:.0f} competitors are currently discounting this product."
    if v == 0:
        return "No competitors are running discounts on this product."
    return f"{v:.0f} competitor(s) have this product on sale."

def _competitors_out_of_stock(v, pos, dec):
    if v >= 2:
        return f"{v:.0f} competitors are out of stock — you have a supply advantage."
    return f"Competitor stock-outs: {v:.0f}."

def _num_competitors(v, pos, dec):
    return f"{v:.0f} competitors tracked for this product."

def _market_position(v, pos, dec):
    labels = {"below_market": "below market", "at_market": "at market",
               "above_market": "above market", "premium": "at a premium"}
    return f"Market position: {labels.get(str(v), str(v))}."

def _days_since_launch(v, pos, dec):
    if v > 365:
        return f"Product is {v:.0f} days old — mature item with sell-through pressure."
    if v < 30:
        return f"Only {v:.0f} days since launch — very new product."
    return f"Product launched {v:.0f} days ago."

def _season_sell_through_pct(v, pos, dec):
    pct = v * 100
    if pct < 15:
        return f"Only {pct:.0f}% sold this season — very slow moving."
    if pct > 70:
        return f"{pct:.0f}% sold this season — strong performance."
    return f"{pct:.0f}% sell-through this season."

def _brand_tier(v, pos, dec):
    tiers = {"premium": "Premium brand", "standard": "Standard brand",
              "budget": "Budget brand"}
    return f"{tiers.get(str(v), str(v))} — affects margin expectations."

def _cost_price_usd(v, pos, dec):
    return f"Cost price is ${v:.0f}."

def _seasonality_score(v, pos, dec):
    if v >= 1.20:
        return f"Peak season — demand is {(v-1)*100:.0f}% above baseline."
    if v <= 0.80:
        return f"Slow season — demand is {(1-v)*100:.0f}% below baseline."
    return f"Seasonality index is {v:.2f} — near normal demand."

def _category_seasonal_boost(v, pos, dec):
    return f"Category-level seasonal boost: {v:.2f}x."

def _event_proximity_score(v, pos, dec):
    if v >= 0.7:
        return "Close to a major Lebanon shopping event — promotional opportunity."
    if v == 0:
        return "No upcoming shopping events within 4 weeks."
    return f"Moderate proximity to a Lebanon event (score: {v:.2f})."

def _next_month_seasonality(v, pos, dec):
    if v > 1.10:
        return f"Next month demand forecast is {v:.0%} of baseline — rising trend."
    if v < 0.90:
        return f"Next month demand is expected to drop to {v:.0%} of baseline."
    return f"Next month seasonality is flat at {v:.2f}."

def _cash_runway_months(v, pos, dec):
    if v < 3:
        return f"Only {v:.1f} months of cash runway — cash is tight."
    return f"{v:.1f} months of cash runway — healthy liquidity."

def _cash_tight(v, pos, dec):
    return "Business is in a cash-tight period." if v else "Cash position is comfortable."

def _inventory_intensity(v, pos, dec):
    pct = v * 100
    if pct > 60:
        return f"{pct:.0f}% of working capital tied up in inventory — very high."
    return f"Inventory uses {pct:.0f}% of working capital."


_TEMPLATES = {
    "days_of_supply":          _days_of_supply,
    "stock_coverage_ratio":    _stock_coverage_ratio,
    "stockout_risk":           _stockout_risk,
    "total_qty":               _total_qty,
    "inventory_vs_median":     _inventory_vs_median,
    "current_margin_pct":      _current_margin_pct,
    "discount_depth_last_30d": _discount_depth_last_30d,
    "days_since_last_discount":_days_since_last_discount,
    "days_at_current_price":   _days_at_current_price,
    "retail_price_usd":        _retail_price_usd,
    "price_gap_pct":           _price_gap_pct,
    "competitors_on_sale":     _competitors_on_sale,
    "competitors_out_of_stock":_competitors_out_of_stock,
    "num_competitors":         _num_competitors,
    "market_position":         _market_position,
    "days_since_launch":       _days_since_launch,
    "season_sell_through_pct": _season_sell_through_pct,
    "brand_tier":              _brand_tier,
    "cost_price_usd":          _cost_price_usd,
    "seasonality_score":       _seasonality_score,
    "category_seasonal_boost": _category_seasonal_boost,
    "event_proximity_score":   _event_proximity_score,
    "next_month_seasonality":  _next_month_seasonality,
    "cash_runway_months":      _cash_runway_months,
    "cash_tight":              _cash_tight,
    "inventory_intensity":     _inventory_intensity,
}
