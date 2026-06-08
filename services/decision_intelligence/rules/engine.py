"""
Hard Rules Engine — IE2 Decision Intelligence.

These 6 rules run BEFORE the ML model and can override it completely.
Rules protect the business from decisions no ML model should ever make:
  - Never miss dead stock (cash is locked up)
  - Never discount what you barely have (scarcity has value)
  - Never sell at a loss (margin floor)
  - Never double-discount within 3 weeks (brand erosion)
  - Never discount when a peak event is 14 days away (capture full price)
  - Explicitly nudge markdown when a SKU is clearly overpriced and overstocked

Each rule returns a RuleResult dict:
  {
    "fired": bool,
    "rule_id": str,
    "action": str | None,          # CLEAR / HOLD / MARKDOWN / PROMOTE / None
    "override_strength": str,       # "absolute" | "strong" | "soft"
    "reason": str,
    "blocks": list[str],            # decisions this rule blocks
  }

Usage:
    from services.decision_intelligence.rules.engine import run_rules

    result = run_rules(features)
    if result["hard_override"]:
        final_decision = result["forced_action"]
    else:
        # Pass result["nudges"] to ML model as additional signal
        pass
"""

from datetime import datetime

from services.decision_intelligence.calendar import get_active_or_upcoming_event


# ── Configurable thresholds (match stylepulse/analyzers/thresholds.py) ──────

# Rule 1 — Dead stock: 120+ DOS with <15% sell-through after 60 days on shelf
# means the product is extremely unlikely to sell at full price.  Empirically
# calibrated from Q4-2025–Q1-2026 Lebanese sportswear retail data.
DEAD_STOCK_DOS_MIN = 120
DEAD_STOCK_SELL_THROUGH_MAX = 0.15
DEAD_STOCK_DAYS_SINCE_LAUNCH_MIN = 60

# Rule 2 — Low stock protection: <15 units or <7 DOS → scarcity has value.
# In Lebanon's 3-8 week import lead times, restocking is slow; protect margin.
LOW_STOCK_QTY_MIN = 15
LOW_STOCK_DOS_MIN = 7

# Rule 3 — Margin floor: never markdown below 35% gross margin.  The 1.15×
# cost buffer ensures post-markdown price still covers operating overhead.
MARGIN_FLOOR_PCT = 35.0
MARGIN_FLOOR_BUFFER = 1.15

# Rule 4 — Cooldown: no re-markdown within 21 days (prevents brand erosion).
RECENT_DISCOUNT_DAYS = 21

# Rule 5 — Event proximity: within 14 days of Eid, back-to-school, or
# holiday season → nudge toward full-price sales to capture peak margins.
EVENT_NUDGE_DAYS = 14
EVENT_NUDGE_DOS_MIN = 30         # Rule 5: must have enough stock to benefit
EVENT_NUDGE_MARGIN_MIN = 35.0    # Rule 5: margin must be worth holding

# Rule 6 - obvious markdown nudge: some SKUs are not rule-forced markdowns,
# but they are clearly overpriced, carrying too much stock, and facing promo
# pressure from competitors. Surface that to the model as a soft signal.
MARKDOWN_NUDGE_PRICE_GAP_MIN = 0.12
MARKDOWN_NUDGE_DOS_MIN = 45
MARKDOWN_NUDGE_COMP_ON_SALE_MIN = 2
MARKDOWN_NUDGE_MARGIN_MIN = 38.0
MARKDOWN_NUDGE_RECENT_DISCOUNT_MIN_DAYS = 21

def rule_dead_stock_clear(features: dict) -> dict:
    """
    Rule 1 — DEAD STOCK CLEAR (absolute override).

    If a product has been on sale for 60+ days, less than 15% of the opening
    stock has sold, and it has 120+ days remaining, it will never sell at full
    price again. Force CLEAR regardless of ML model output.

    Override strength: ABSOLUTE — ML model is ignored entirely.
    """
    dos = features.get("days_of_supply", 0)
    sell_through = features.get("season_sell_through_pct", 1.0)
    days_since_launch = features.get("days_since_launch", 0)

    fired = (
        dos > DEAD_STOCK_DOS_MIN
        and sell_through < DEAD_STOCK_SELL_THROUGH_MAX
        and days_since_launch > DEAD_STOCK_DAYS_SINCE_LAUNCH_MIN
    )

    return {
        "fired": fired,
        "rule_id": "DEAD_STOCK_CLEAR",
        "action": "CLEAR" if fired else None,
        "override_strength": "absolute",
        "reason": (
            f"Product has {dos:.0f} days of supply, only {sell_through:.0%} sold through "
            f"in {days_since_launch:.0f} days on sale. "
            f"Will never sell at full price — clear at 50% to recover cash."
        ) if fired else "",
        "blocks": ["HOLD", "MARKDOWN", "PROMOTE"],
    }


def rule_low_stock_protection(features: dict) -> dict:
    """
    Rule 2 — LOW STOCK PROTECTION (strong override).

    When stock is critically low, scarcity has value. Never discount or
    actively promote what you barely have — the customer will pay full price
    or substitute. Block MARKDOWN and PROMOTE, allow only HOLD.

    Override strength: STRONG — blocks MARKDOWN and PROMOTE.
    Exception: CLEAR is still allowed if product is also dead stock.
    """
    total_qty = features.get("total_qty", 999)
    dos = features.get("days_of_supply", 999)

    fired = total_qty < LOW_STOCK_QTY_MIN or dos < LOW_STOCK_DOS_MIN

    return {
        "fired": fired,
        "rule_id": "LOW_STOCK_PROTECTION",
        "action": "HOLD" if fired else None,
        "override_strength": "strong",
        "reason": (
            f"Only {total_qty} units remaining ({dos:.0f} days of supply). "
            f"Scarcity has value — hold price until restocked."
        ) if fired else "",
        "blocks": ["MARKDOWN", "PROMOTE"],
    }


def rule_margin_floor_protection(features: dict) -> dict:
    """
    Rule 3 — MARGIN FLOOR PROTECTION (strong override).

    Never recommend a markdown that would bring margin below 35% or
    final price below cost × 1.15. This is the minimum profitable operation.

    Override strength: STRONG — blocks MARKDOWN only.
    """
    current_margin_pct = features.get("current_margin_pct", 100.0)
    cost_price = features.get("cost_price_usd", 0)
    retail_price = features.get("retail_price_usd", 1)
    suggested_discount = features.get("suggested_discount_pct", 0)

    # Check if the suggested markdown would breach the floor
    post_markdown_price = retail_price * (1 - suggested_discount / 100)
    post_markdown_margin = (
        (post_markdown_price - cost_price) / post_markdown_price * 100
        if post_markdown_price > 0 else 0
    )
    floor_price = cost_price * MARGIN_FLOOR_BUFFER

    fired = (
        current_margin_pct < MARGIN_FLOOR_PCT
        or (suggested_discount > 0 and post_markdown_margin < MARGIN_FLOOR_PCT)
        or (suggested_discount > 0 and post_markdown_price < floor_price)
    )

    return {
        "fired": fired,
        "rule_id": "MARGIN_FLOOR_PROTECTION",
        "action": "HOLD" if fired else None,
        "override_strength": "strong",
        "reason": (
            f"Markdown would bring margin to {post_markdown_margin:.1f}% "
            f"(floor is {MARGIN_FLOOR_PCT}%). "
            f"Minimum sell price is ${floor_price:.2f}. "
            f"Review cost structure before discounting further."
        ) if fired else "",
        "blocks": ["MARKDOWN"],
    }


def rule_recent_discount_protection(features: dict) -> dict:
    """
    Rule 4 — RECENT DISCOUNT PROTECTION (strong override).

    Double-discounting within 21 days destroys brand perception and signals
    desperation to customers. If a markdown was applied recently, block
    any further markdown recommendation.

    Override strength: STRONG — blocks MARKDOWN only.
    """
    days_since_last_discount = features.get("days_since_last_discount", 999)

    fired = days_since_last_discount < RECENT_DISCOUNT_DAYS

    return {
        "fired": fired,
        "rule_id": "RECENT_DISCOUNT_PROTECTION",
        "action": None,  # doesn't force a decision, just blocks markdown
        "override_strength": "strong",
        "reason": (
            f"A markdown was applied {days_since_last_discount} days ago "
            f"(minimum gap is {RECENT_DISCOUNT_DAYS} days). "
            f"Too soon to discount again — customers will wait for further drops."
        ) if fired else "",
        "blocks": ["MARKDOWN"],
    }


def rule_calendar_event_nudge(features: dict, *, today: datetime | None = None) -> dict:
    """
    Rule 5 — CALENDAR EVENT NUDGE (soft — influences, does not override).

    If a major retail event is within EVENT_NUDGE_DAYS and stock/margin are
    healthy, nudge toward PROMOTE or HOLD rather than MARKDOWN. This captures
    full-price demand during the most valuable selling window.

    Override strength: SOFT — adds a signal, does not force a decision.
    """
    current_date = (today or datetime.now()).date()
    dos = features.get("days_of_supply", 0)
    margin_pct = features.get("current_margin_pct", 0)
    event_score = float(features.get("event_proximity_score", 0.0) or 0.0)
    event_window, days_until_event = get_active_or_upcoming_event(current_date, EVENT_NUDGE_DAYS)
    has_event_signal = event_window is not None or event_score >= 0.5

    fired = (
        has_event_signal
        and dos >= EVENT_NUDGE_DOS_MIN
        and margin_pct >= EVENT_NUDGE_MARGIN_MIN
    )

    if event_window is None and event_score >= 0.5:
        event_summary = f"Event proximity signal is high ({event_score:.2f})."
    elif event_window is None:
        event_summary = ""
    elif days_until_event == 0:
        event_summary = (
            f"Event window active now: {event_window.name.replace('_', ' ').title()} "
            f"({event_window.start_date.isoformat()} to {event_window.end_date.isoformat()})."
        )
    else:
        event_summary = (
            f"Upcoming event: {event_window.name.replace('_', ' ').title()} in {days_until_event} days "
            f"(starts {event_window.start_date.isoformat()})."
        )

    return {
        "fired": fired,
        "rule_id": "CALENDAR_EVENT_NUDGE",
        "action": None,  # soft nudge — never forces a decision
        "override_strength": "soft",
        "nudge_toward": ["PROMOTE", "HOLD"] if fired else [],
        "reason": (
            f"{event_summary} "
            f"Stock is healthy ({dos:.0f} DOS) and margin is {margin_pct:.0f}%. "
            f"Do not discount now — promote at full price to capture peak demand."
        ) if fired else "",
        "blocks": [],
    }


def rule_obvious_markdown_nudge(features: dict) -> dict:
    """
    Rule 6 - OBVIOUS MARKDOWN NUDGE (soft - influences, does not override).

    When a SKU is clearly overpriced versus market, has enough inventory to
    absorb a markdown, still has healthy margin, and competitors are already
    discounting, nudge the downstream decision toward MARKDOWN.
    """
    dos = features.get("days_of_supply", 0)
    margin_pct = features.get("current_margin_pct", 0)
    price_gap = features.get("price_gap_pct", 0.0)
    comp_on_sale = features.get("competitors_on_sale", 0)
    days_since_last_discount = features.get("days_since_last_discount", 999)
    sell_through = features.get("season_sell_through_pct", 1.0)

    fired = (
        price_gap >= MARKDOWN_NUDGE_PRICE_GAP_MIN
        and dos >= MARKDOWN_NUDGE_DOS_MIN
        and margin_pct >= MARKDOWN_NUDGE_MARGIN_MIN
        and comp_on_sale >= MARKDOWN_NUDGE_COMP_ON_SALE_MIN
        and days_since_last_discount >= MARKDOWN_NUDGE_RECENT_DISCOUNT_MIN_DAYS
        and sell_through <= 0.45
    )

    return {
        "fired": fired,
        "rule_id": "OBVIOUS_MARKDOWN_NUDGE",
        "action": None,
        "override_strength": "soft",
        "nudge_toward": ["MARKDOWN"] if fired else [],
        "reason": (
            f"SKU is {price_gap:.0%} above market with {dos:.0f} DOS, "
            f"{comp_on_sale} competitors on sale, and margin at {margin_pct:.0f}%. "
            f"This is a strong markdown candidate."
        ) if fired else "",
        "blocks": [],
    }


def run_rules(features: dict) -> dict:
    """
    Run all 6 rules in priority order.

    Returns:
        {
            "hard_override": bool,          # True if any absolute/strong rule fired
            "forced_action": str | None,    # the action to use (if hard_override=True)
            "blocked_actions": list[str],   # decisions the ML model must not return
            "nudges": list[str],            # soft signals toward these decisions
            "rules_fired": list[dict],      # all rules that fired (for audit trail)
            "rule_override": str | None,    # rule_id of the winning rule (if any)
        }
    """
    results = [
        rule_dead_stock_clear(features),
        rule_low_stock_protection(features),
        rule_margin_floor_protection(features),
        rule_recent_discount_protection(features),
        rule_calendar_event_nudge(features),
        rule_obvious_markdown_nudge(features),
    ]

    rules_fired = [r for r in results if r["fired"]]
    blocked_actions = set()
    nudges = []
    forced_action = None
    rule_override_id = None

    for rule in rules_fired:
        blocked_actions.update(rule.get("blocks", []))
        nudges.extend(rule.get("nudge_toward", []))

        if rule["override_strength"] == "absolute":
            forced_action = rule["action"]
            rule_override_id = rule["rule_id"]
            break  # absolute rule wins immediately, stop checking

        if rule["override_strength"] == "strong" and rule.get("action"):
            if forced_action is None:  # first strong rule wins
                forced_action = rule["action"]
                rule_override_id = rule["rule_id"]

    hard_override = forced_action is not None

    return {
        "hard_override": hard_override,
        "forced_action": forced_action,
        "blocked_actions": list(blocked_actions),
        "nudges": list(set(nudges)),
        "rules_fired": rules_fired,
        "rule_override": rule_override_id,
    }
