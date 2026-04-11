"""
Lebanon-adjusted thresholds for retail intelligence.

All thresholds are calibrated for:
  - Lebanon's 3-8 week import lead times
  - Cash-constrained operating environment
  - High import cost structure (40-55% cost ratio)
  - Seasonal demand concentration
"""

# ── Days of Supply (DOS) Thresholds ────────────────────────────────────────
# Wider bands than Western retail due to import lead times.
# A US retailer might panic at DOS > 60; in Lebanon, 90 is acceptable.

DOS_CRITICAL = 21       # Reorder immediately — will stockout before shipment arrives
DOS_WARNING = 45        # Accelerate reorder, consider air freight for key items
DOS_HEALTHY_MIN = 45
DOS_HEALTHY_MAX = 90    # Comfortable range for Lebanon
DOS_EXCESS = 90         # Start considering markdown
DOS_DEAD = 180          # Aggressive clearance territory

# ── Velocity Thresholds ────────────────────────────────────────────────────
# velocity_ratio = (recent 7-day avg sales) / (prior 28-day avg sales)
# >1.0 = accelerating, <1.0 = decelerating

VELOCITY_STRONG = 1.20     # Trend accelerating — hold pricing, ensure stock
VELOCITY_HEALTHY = 0.80    # Normal range
VELOCITY_WEAK = 0.50       # Decelerating — markdown candidate
VELOCITY_DEAD = 0.20       # Effectively not selling — clear

# ── Sell-Through Rate Thresholds ───────────────────────────────────────────
# sell_through = cumulative_sold / (cumulative_sold + current_stock)

STR_EXCELLENT = 0.70    # >70% sold through — strong performer
STR_GOOD = 0.50         # Healthy pace
STR_WARNING = 0.30      # Below expectations — needs intervention
STR_CRITICAL = 0.15     # Stalled product — clear or bundle

# ── Margin Thresholds ─────────────────────────────────────────────────────
# Lebanon cost structure: import duties + freight + distributor = high cost
# Margin below 35% is dangerous; below 25% is losing money after OpEx

MARGIN_EXCELLENT = 55.0     # Premium positioning, protect this
MARGIN_HEALTHY = 45.0       # Standard for Lebanon sportswear
MARGIN_FLOOR = 35.0         # Minimum acceptable — below this, review pricing
MARGIN_CRITICAL = 25.0      # Losing money on this item after OpEx allocation
MARGIN_CLEARANCE = 15.0     # Only acceptable for dead stock clearance

# ── Competitive Position Thresholds ────────────────────────────────────────
# price_gap_pct = (our_price - market_median) / market_median × 100

COMP_PREMIUM = 15.0         # >15% above market — risk losing sales
COMP_NEUTRAL_HIGH = 5.0     # Slightly above — acceptable if service/location justifies
COMP_NEUTRAL_LOW = -5.0     # Slightly below — good positioning
COMP_VALUE = -15.0          # More than 15% below — leaving margin on the table

# ── Financial Health Thresholds ────────────────────────────────────────────

CURRENT_RATIO_HEALTHY = 2.0       # Lebanon needs higher buffer than normal
CURRENT_RATIO_WARNING = 1.5
CURRENT_RATIO_CRITICAL = 1.0

CASH_RUNWAY_SAFE = 4.0            # months of OpEx in cash
CASH_RUNWAY_WARNING = 2.5
CASH_RUNWAY_CRITICAL = 1.5

INVENTORY_PCT_OF_ASSETS_MAX = 75.0  # If >75%, too much capital locked in stock
INVENTORY_PCT_OF_ASSETS_WARNING = 60.0

# ── Markdown Escalation ───────────────────────────────────────────────────
# Progressive markdown strategy based on DOS

MARKDOWN_SCHEDULE = [
    {"dos_min": 90, "dos_max": 120, "discount_pct": 15, "label": "light_markdown"},
    {"dos_min": 120, "dos_max": 150, "discount_pct": 25, "label": "moderate_markdown"},
    {"dos_min": 150, "dos_max": 180, "discount_pct": 35, "label": "deep_markdown"},
    {"dos_min": 180, "dos_max": 9999, "discount_pct": 50, "label": "clearance"},
]

# ── Seasonal Calendar (Lebanon) ────────────────────────────────────────────
# Month → seasonal signal multiplier for demand expectations

SEASONAL_MULTIPLIERS = {
    1: 0.70,   # Jan: post-holiday slump
    2: 0.80,   # Feb: slow recovery
    3: 0.90,   # Mar: spring collections, Ramadan (variable)
    4: 1.10,   # Apr: spring peak, Eid (variable)
    5: 1.15,   # May: warm weather surge
    6: 1.20,   # Jun: summer peak, tourism begins
    7: 1.10,   # Jul: summer continues
    8: 1.30,   # Aug: back-to-school (biggest period)
    9: 1.20,   # Sep: school season continues
    10: 0.90,  # Oct: shoulder season
    11: 0.85,  # Nov: pre-holiday
    12: 0.90,  # Dec: holiday gifting
}

# Category-specific seasonality adjustments
CATEGORY_SEASONAL_BOOST = {
    "swimwear": {5: 0.3, 6: 0.5, 7: 0.5, 8: 0.3},     # summer boost
    "football_boots": {8: 0.3, 9: 0.4, 10: 0.2},         # season start
    "kids": {8: 0.4, 9: 0.3},                             # back-to-school
}

# ── Reorder Point Formula ──────────────────────────────────────────────────
# ROP = (avg_daily_demand × max_lead_time_days) + safety_stock
# Safety stock = avg_daily_demand × safety_factor × sqrt(lead_time_days)

LEAD_TIME_DAYS = {
    "local_distributor": 14,   # 2 weeks (Beirut-based)
    "regional": 35,            # 5 weeks (Dubai/Turkey)
    "import": 56,              # 8 weeks (Europe/Asia)
}

SAFETY_FACTOR = 1.65  # ~95% service level (z-score)


def get_dos_status(dos):
    """Return status label for a given days-of-supply value."""
    if dos <= DOS_CRITICAL:
        return "critical"
    if dos <= DOS_WARNING:
        return "warning"
    if dos <= DOS_HEALTHY_MAX:
        return "healthy"
    if dos <= DOS_DEAD:
        return "excess"
    return "dead"


def get_markdown_recommendation(dos, velocity=None):
    """Return markdown depth recommendation based on DOS and velocity."""
    if velocity is not None and velocity >= VELOCITY_HEALTHY:
        return None  # Don't markdown if still selling well

    for tier in MARKDOWN_SCHEDULE:
        if tier["dos_min"] <= dos < tier["dos_max"]:
            return tier
    return None


def get_seasonal_multiplier(month, category=None):
    """Return demand multiplier for a given month and optional category."""
    base = SEASONAL_MULTIPLIERS.get(month, 1.0)
    if category and category in CATEGORY_SEASONAL_BOOST:
        boost = CATEGORY_SEASONAL_BOOST[category].get(month, 0)
        return base + boost
    return base


def compute_reorder_point(avg_daily_demand, lead_time_type="regional"):
    """Compute reorder point for Lebanon lead times."""
    lead_days = LEAD_TIME_DAYS.get(lead_time_type, 35)
    safety_stock = avg_daily_demand * SAFETY_FACTOR * (lead_days ** 0.5)
    rop = (avg_daily_demand * lead_days) + safety_stock
    return round(rop), round(safety_stock)
