"""
Closed-Loop Outcome Tracking.

Flow:
1. snapshot_decision()  — called at approval time, captures real baseline from DB
2. measure_outcome()    — called at 7d / 14d, queries real post-decision sales
3. generate_narrative() — calls Claude to verify calculations and write analysis
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from eep.retail_db import (
    DatabaseUnavailable,
    get_current_stock_for_variant,
    get_portfolio_accuracy,
    get_recommendation_by_id,
    get_snapshot_by_id,
    get_snapshots_for_variant,
    insert_decision_snapshot,
    insert_outcome_measurement,
    query_daily_sales_series,
    query_velocity_window,
    update_snapshot_status,
)

logger = logging.getLogger(__name__)

# Campaign cost estimate for PROMOTE ROI calculation (USD)
_PROMOTE_CAMPAIGN_COST_EST = float(os.environ.get("PROMOTE_CAMPAIGN_COST_USD", "25.0"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _derive_predicted_lift(
    decision_type: str,
    ie2_confidence: float,
    suggested_discount_pct: float | None,
) -> float:
    """
    Derive the predicted velocity lift % from IE2 outputs.

    PROMOTE  : confidence × 30  (max ~25.5% at confidence=0.85)
    MARKDOWN : suggested_discount × 0.65  (price elasticity approx)
    CLEAR    : constant 80% (target near full sell-through)
    HOLD     : 0 (no change expected)
    """
    if decision_type == "PROMOTE":
        return round(ie2_confidence * 30.0, 1)
    if decision_type == "MARKDOWN":
        discount = suggested_discount_pct or 10.0
        return round(discount * 0.65, 1)
    if decision_type == "CLEAR":
        return 80.0
    return 0.0


def snapshot_decision(
    sku_id: str,
    variant_id: str,
    decision_type: str,
    recommendation_id: str | None = None,
    cost_price_usd: float = 0.0,
) -> int | None:
    """
    Capture a baseline snapshot when a decision is approved.

    Queries real sales_transaction_lines for 7-day baseline velocity.
    Returns snapshot_id, or None if DB is unavailable.
    """
    try:
        now = _now()
        window_start = now - timedelta(days=7)

        # Baseline sales velocity (real data)
        baseline = query_velocity_window(variant_id, window_start, now)

        # Current stock
        qty_on_hand = get_current_stock_for_variant(variant_id)

        # IE2 recommendation details
        ie2_confidence = 0.0
        ie2_explanation: str | None = None
        suggested_discount_pct: float | None = None
        retail_price = 0.0

        if recommendation_id:
            rec = get_recommendation_by_id(recommendation_id)
            if rec:
                ie2_confidence = float(rec.get("confidence") or 0)
                ie2_explanation = rec.get("explanation")
                suggested_discount_pct = (
                    float(rec["suggested_discount_pct"]) if rec.get("suggested_discount_pct") else None
                )
                retail_price = float(rec.get("suggested_price_usd") or 0)

        # Baseline margin
        avg_price = baseline["avg_unit_price"] or retail_price
        baseline_margin = (
            round((avg_price - cost_price_usd) / avg_price * 100, 2)
            if avg_price > 0 else None
        )

        # Baseline DOS
        baseline_dos = (
            round(qty_on_hand / baseline["velocity_daily"], 1)
            if baseline["velocity_daily"] > 0 else None
        )

        predicted_lift = _derive_predicted_lift(
            decision_type, ie2_confidence, suggested_discount_pct
        )

        status = "tracking" if baseline["data_available"] else "insufficient_data"

        snapshot_id = insert_decision_snapshot({
            "variant_id": variant_id,
            "recommendation_id": recommendation_id,
            "decision_type": decision_type,
            "approved_at": now,
            "baseline_velocity_daily": baseline["velocity_daily"] if baseline["data_available"] else None,
            "baseline_revenue_7d": baseline["total_revenue"] if baseline["data_available"] else None,
            "baseline_avg_price": baseline["avg_unit_price"] if baseline["data_available"] else None,
            "baseline_qty_on_hand": qty_on_hand,
            "baseline_margin_pct": baseline_margin,
            "baseline_dos": baseline_dos,
            "predicted_lift_pct": predicted_lift,
            "ie2_confidence": ie2_confidence,
            "ie2_explanation": ie2_explanation,
            "suggested_discount_pct": suggested_discount_pct,
            "check_7d_at": now + timedelta(days=7),
            "check_14d_at": now + timedelta(days=14),
            "status": status,
        })
        logger.info("Outcome snapshot %d created for %s (%s)", snapshot_id, sku_id, decision_type)
        return snapshot_id

    except DatabaseUnavailable as exc:
        logger.warning("DB unavailable during snapshot_decision for %s: %s", sku_id, exc)
        return None
    except Exception as exc:
        logger.error("snapshot_decision failed for %s: %s", sku_id, exc, exc_info=True)
        return None


def measure_outcome(snapshot_id: int, window_days: int) -> dict[str, Any]:
    """
    Measure actual post-decision outcome from real sales data.
    Calls Claude to verify calculations and generate a narrative.

    window_days: 7 or 14
    """
    snapshot = get_snapshot_by_id(snapshot_id)
    if not snapshot:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    variant_id = snapshot["variant_id"]
    approved_at_raw = snapshot["approved_at"]

    # Parse approved_at — may be a string (from _jsonable) or datetime
    if isinstance(approved_at_raw, str):
        approved_at = datetime.fromisoformat(approved_at_raw)
        if approved_at.tzinfo is None:
            approved_at = approved_at.replace(tzinfo=timezone.utc)
    else:
        approved_at = approved_at_raw
        if approved_at.tzinfo is None:
            approved_at = approved_at.replace(tzinfo=timezone.utc)

    window_start = approved_at
    window_end = approved_at + timedelta(days=window_days)

    # Real post-decision sales
    actuals = query_velocity_window(variant_id, window_start, window_end)

    if not actuals["data_available"]:
        measurement_id = insert_outcome_measurement({
            "snapshot_id": snapshot_id,
            "window_days": window_days,
            "data_available": False,
        })
        new_status = "measured_7d" if window_days == 7 else "completed"
        update_snapshot_status(snapshot_id, new_status)
        return {
            "snapshot_id": snapshot_id,
            "window_days": window_days,
            "data_available": False,
            "message": "No sales transactions found for this window. Connect your sales feed to enable outcome tracking.",
        }

    # Compute deltas
    baseline_vel = float(snapshot.get("baseline_velocity_daily") or 0)
    actual_vel = actuals["velocity_daily"]

    velocity_lift_pct: float | None = None
    if baseline_vel > 0:
        velocity_lift_pct = round((actual_vel - baseline_vel) / baseline_vel * 100, 2)

    baseline_rev = float(snapshot.get("baseline_revenue_7d") or 0)
    actual_rev = actuals["total_revenue"]
    # Normalize revenue delta to the same window size as baseline (7d)
    revenue_delta = round(actual_rev - (baseline_rev * (window_days / 7.0)), 2)

    # Campaign ROI for PROMOTE (revenue delta minus estimated campaign cost)
    campaign_roi: float | None = None
    if snapshot["decision_type"] == "PROMOTE" and revenue_delta is not None:
        campaign_roi = round(revenue_delta - _PROMOTE_CAMPAIGN_COST_EST, 2)

    # Accuracy score: 1 - |predicted - actual| / max(|predicted|, 1)
    predicted_lift = float(snapshot.get("predicted_lift_pct") or 0)
    accuracy_score: float | None = None
    if velocity_lift_pct is not None:
        accuracy_score = round(
            max(0.0, 1.0 - abs(predicted_lift - velocity_lift_pct) / max(abs(predicted_lift), 1.0)),
            4,
        )

    # LLM narrative
    narrative_data = _generate_narrative(snapshot, actuals, velocity_lift_pct, revenue_delta, window_days)

    measurement_id = insert_outcome_measurement({
        "snapshot_id": snapshot_id,
        "window_days": window_days,
        "actual_velocity_daily": actual_vel,
        "actual_revenue_total": actual_rev,
        "actual_qty_sold": actuals["total_units"],
        "actual_avg_price": actuals["avg_unit_price"],
        "velocity_lift_pct": velocity_lift_pct,
        "revenue_delta_usd": revenue_delta,
        "campaign_roi_usd": campaign_roi,
        "accuracy_score": accuracy_score,
        "narrative": narrative_data.get("narrative"),
        "llm_computed_lift_pct": narrative_data.get("verified_lift_pct"),
        "llm_computed_revenue_delta": narrative_data.get("verified_revenue_delta"),
        "data_available": True,
    })

    new_status = "measured_7d" if window_days == 7 else "completed"
    update_snapshot_status(snapshot_id, new_status)

    return {
        "measurement_id": measurement_id,
        "snapshot_id": snapshot_id,
        "window_days": window_days,
        "actual_velocity_daily": actual_vel,
        "actual_qty_sold": actuals["total_units"],
        "actual_revenue_total": actual_rev,
        "velocity_lift_pct": velocity_lift_pct,
        "revenue_delta_usd": revenue_delta,
        "campaign_roi_usd": campaign_roi,
        "accuracy_score": accuracy_score,
        "narrative": narrative_data.get("narrative"),
        "data_available": True,
    }


def _generate_narrative(
    snapshot: dict[str, Any],
    actuals: dict[str, Any],
    velocity_lift_pct: float | None,
    revenue_delta: float,
    window_days: int,
) -> dict[str, Any]:
    """
    Call Claude to re-verify calculations and write a 3-sentence analysis.
    Returns { narrative, verified_lift_pct, verified_revenue_delta }.
    Falls back gracefully if Anthropic is unavailable.
    """
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed, skipping narrative generation")
        return {"narrative": None, "verified_lift_pct": None, "verified_revenue_delta": None}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping narrative generation")
        return {"narrative": None, "verified_lift_pct": None, "verified_revenue_delta": None}

    baseline_vel = float(snapshot.get("baseline_velocity_daily") or 0)
    baseline_rev = float(snapshot.get("baseline_revenue_7d") or 0)
    actual_vel = actuals["velocity_daily"]
    actual_rev = actuals["total_revenue"]
    baseline_units = round(baseline_vel * 7)
    actual_units = actuals["total_units"]
    decision_type = snapshot["decision_type"]
    predicted_lift = float(snapshot.get("predicted_lift_pct") or 0)
    confidence_pct = round(float(snapshot.get("ie2_confidence") or 0) * 100, 1)
    explanation = snapshot.get("ie2_explanation") or "No IE2 explanation available."

    prompt = f"""You are the Radar AI outcome analyst. A Lebanese fashion retailer approved an AI recommendation and you are analyzing its {window_days}-day result.

=== DECISION ===
Type: {decision_type}
IE2 Confidence: {confidence_pct}%
IE2 Reasoning: "{explanation}"
Predicted velocity lift: +{predicted_lift}%

=== RAW MEASUREMENTS (from live sales database) ===
Baseline window (7 days before decision):
  - Units sold: {baseline_units}
  - Days in window: 7
  - Baseline velocity: {baseline_units} ÷ 7 = {baseline_vel:.4f} units/day
  - Revenue: ${baseline_rev:.2f}

Post-decision window ({window_days} days after decision):
  - Units sold: {actual_units}
  - Days in window: {window_days}
  - Post velocity: {actual_units} ÷ {window_days} = {actual_vel:.4f} units/day
  - Revenue: ${actual_rev:.2f}

=== YOUR TASK ===
Step 1 — Verify these calculations (show your arithmetic):
  velocity_lift_pct = ({actual_vel:.4f} - {baseline_vel:.4f}) / {baseline_vel:.4f} × 100 = ?
  revenue_delta = ${actual_rev:.2f} - ${baseline_rev:.2f} = ?

Step 2 — Write a 3-sentence analysis (max 90 words total):
  Sentence 1: State whether the prediction was accurate and by how much (use your verified numbers).
  Sentence 2: Identify what likely drove the actual result based on the IE2 reasoning and the numbers.
  Sentence 3: Give one concrete, specific recommendation for future similar decisions.

Step 3 — Output ONLY valid JSON (no markdown, no code fences):
{{"verified_lift_pct": <your calculated value as a number>, "verified_revenue_delta": <your calculated value as a number>, "narrative": "<your 3-sentence analysis>"}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            raw_text = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()

        result = json.loads(raw_text)

        llm_lift = float(result.get("verified_lift_pct") or 0)
        llm_rev_delta = float(result.get("verified_revenue_delta") or 0)

        # Sanity check: flag divergence > 0.5 percentage points
        if velocity_lift_pct is not None and abs(llm_lift - velocity_lift_pct) > 0.5:
            logger.warning(
                "LLM lift %.2f diverges from Python %.2f for snapshot — using Python value",
                llm_lift, velocity_lift_pct,
            )

        return {
            "narrative": result.get("narrative"),
            "verified_lift_pct": llm_lift,
            "verified_revenue_delta": llm_rev_delta,
        }

    except json.JSONDecodeError as exc:
        logger.error("LLM narrative JSON parse error: %s — raw: %s", exc, raw_text[:200])
        return {"narrative": None, "verified_lift_pct": None, "verified_revenue_delta": None}
    except Exception as exc:
        logger.error("LLM narrative generation failed: %s", exc, exc_info=True)
        return {"narrative": None, "verified_lift_pct": None, "verified_revenue_delta": None}


def get_outcomes_for_sku(variant_id: str) -> list[dict[str, Any]]:
    return get_snapshots_for_variant(variant_id)


def get_accuracy(decision_type: str | None = None) -> dict[str, Any]:
    try:
        return get_portfolio_accuracy(decision_type)
    except DatabaseUnavailable:
        return {"avg_accuracy": None, "decision_count": 0, "by_type": {}}


def get_daily_series(snapshot_id: int) -> list[dict[str, Any]]:
    """Return the 21-day daily sales series (7d before + 14d after) for the velocity chart."""
    snapshot = get_snapshot_by_id(snapshot_id)
    if not snapshot:
        return []

    variant_id = snapshot["variant_id"]
    approved_at_raw = snapshot["approved_at"]

    if isinstance(approved_at_raw, str):
        approved_at = datetime.fromisoformat(approved_at_raw)
        if approved_at.tzinfo is None:
            approved_at = approved_at.replace(tzinfo=timezone.utc)
    else:
        approved_at = approved_at_raw
        if approved_at.tzinfo is None:
            approved_at = approved_at.replace(tzinfo=timezone.utc)

    series_start = approved_at - timedelta(days=7)
    series_end = approved_at + timedelta(days=14)

    return query_daily_sales_series(variant_id, series_start, series_end)
