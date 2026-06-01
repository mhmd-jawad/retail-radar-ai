"""
Anthropic tool schemas for the WhatsApp assistant.
Pure data — no logic. Maps 1:1 to BusinessDataService methods and actions.
"""
from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "get_inventory_overview",
        "description": (
            "Returns total SKU count, units on hand, inventory value at cost, "
            "low-stock SKU list, and dead-stock SKU list. Use for broad inventory questions "
            "like 'how's my stock', 'what do I have', or 'inventory status'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_stockout_days",
        "description": (
            "Returns each low-stock SKU with estimated days until stockout based on "
            "30-day sales velocity. Use when the retailer asks 'how long until I run out', "
            "'which products are running low', or needs urgency ranking for reorders."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_reorder_suggestions",
        "description": (
            "Returns suggested reorder quantities for SKUs at or near their reorder point. "
            "Includes estimated cost to place the order and 14-day coverage calculation. "
            "Use when the retailer asks 'what should I order', 'what do I need to restock'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_sku_velocity_trend",
        "description": (
            "Returns daily sales velocity trend for a specific SKU — units sold per day "
            "and revenue over 7, 14, or 30 days. Use for follow-up questions about a specific "
            "product: 'is this selling well?', 'how is Nike 270 trending?', 'is Ultraboost growing?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "The SKU ID to analyse, e.g. NB-550-WHT-42",
                },
                "days": {
                    "type": "integer",
                    "enum": [7, 14, 30],
                    "description": "Lookback window in days. Default 30.",
                },
            },
            "required": ["sku_id"],
        },
    },
    {
        "name": "get_category_performance",
        "description": (
            "Returns revenue, units sold, margin, and SKU count broken down by product category "
            "for the last N days. Use for questions like 'what category is performing best?', "
            "'which department is losing money?', 'how are shoes vs apparel?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "enum": [7, 14, 30],
                    "description": "Lookback window in days. Default 30.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_financials",
        "description": (
            "Returns cash runway, monthly OPEX burn, blended gross margin, and revenue "
            "figures (current month, last 7 days, last 30 days). Use for financial health "
            "questions: 'how much cash do I have?', 'what's my margin?', 'cashflow status'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_revenue_trend",
        "description": (
            "Returns this-week vs last-week daily revenue average with trend direction and "
            "percentage change. Use when the retailer asks if sales are growing or declining: "
            "'are sales up this week?', 'how's revenue trending?', 'better or worse than last week?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_competitor_prices",
        "description": (
            "Returns competitor price comparisons for SKUs we carry, showing our price vs "
            "competitor price and the gap percentage. Optionally filter by a specific SKU or "
            "competitor. Use for questions like 'who's cheaper than us?', 'competitor prices', "
            "'are we overpriced on Nike?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "Filter results to this specific SKU ID (optional).",
                },
                "competitor_name": {
                    "type": "string",
                    "description": "Filter results to this competitor shop code (optional).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_pending_recommendations",
        "description": (
            "Returns pending PROMOTE and MARKDOWN AI recommendations with confidence scores, "
            "suggested discounts, and explanations. Use when the retailer asks 'what does the AI "
            "suggest?', 'any pending recommendations?', 'what should I promote?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "approve_recommendation",
        "description": (
            "Approves a pending PROMOTE or MARKDOWN recommendation. Triggers campaign generation "
            "for PROMOTE actions via IE3 and starts closed-loop outcome tracking. "
            "Call this when the retailer confirms they want to proceed — natural phrases like "
            "'sounds good', 'do it', 'yalla', 'go ahead', 'yes run it', or 'ok approve'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recommendation_id": {
                    "type": "string",
                    "description": "UUID of the recommendation to approve.",
                },
                "sku_id": {
                    "type": "string",
                    "description": "SKU ID of the product being approved.",
                },
                "modified_discount_pct": {
                    "type": "number",
                    "description": (
                        "Override the suggested discount percentage, e.g. 20.0 for 20% off. "
                        "Only provide when the retailer explicitly requests a different discount."
                    ),
                },
            },
            "required": ["recommendation_id", "sku_id"],
        },
    },
    {
        "name": "reject_recommendation",
        "description": (
            "Rejects a pending recommendation and logs the decision. "
            "Call this when the retailer declines — natural phrases like 'no', 'skip this', "
            "'not now', 'pass', 'reject it'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recommendation_id": {
                    "type": "string",
                    "description": "UUID of the recommendation to reject.",
                },
                "sku_id": {
                    "type": "string",
                    "description": "SKU ID of the product being rejected.",
                },
            },
            "required": ["recommendation_id", "sku_id"],
        },
    },
    {
        "name": "get_decision_progress",
        "description": (
            "Returns closed-loop tracking summary: decisions being tracked, 7-day and 14-day "
            "outcome measurements, velocity lifts, revenue deltas, and model accuracy. "
            "Use for questions like 'how are my decisions performing?', 'did that promotion work?', "
            "'show me campaign results'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_roadmap_summary",
        "description": (
            "Returns a management-level view of ALL active recommendation roadmaps — every "
            "recommendation's current lifecycle stage, reasoning, expected impact, modification "
            "history, and outcome results. Groups by stage: awaiting approval, approved, executing, "
            "monitoring, completed, blocked. "
            "Use for questions like 'what is the status of our recommendations?', 'what is in the "
            "pipeline?', 'show me all active decisions', 'what stage is each recommendation at?', "
            "'give me a full progress report', 'what has been done and what is pending?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_recommendation_detail",
        "description": (
            "Returns the full detail for a single recommendation roadmap: the data that triggered it, "
            "Claude's reasoning, expected impact, risks, alternatives, next best step, and the full "
            "audit trail of every action taken. "
            "Use when the retailer asks about a specific recommendation: 'why are you recommending this?', "
            "'what data supports this decision?', 'what are the risks?', 'show me the history of "
            "this recommendation', 'what stage is [product name] at?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "roadmap_id": {
                    "type": "integer",
                    "description": "The roadmap ID to look up. Get it from get_roadmap_summary first.",
                },
            },
            "required": ["roadmap_id"],
        },
    },
    {
        "name": "get_next_actions",
        "description": (
            "Returns a prioritised action list for management: what needs immediate attention, "
            "pending approvals, modified recommendations waiting re-approval, blocked items, "
            "overdue performance reviews, and recently completed actions with outcomes. "
            "Use for questions like 'what should I do today?', 'what is waiting for my approval?', "
            "'what needs my attention?', 'what should management focus on?', 'what is blocked?', "
            "'what are the next recommended actions?', 'give me a daily brief on decisions'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
