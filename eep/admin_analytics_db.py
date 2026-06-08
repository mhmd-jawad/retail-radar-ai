"""
Admin Analytics DB — cross-tenant aggregate queries for the Platform Operations suite.

All functions require admin context (enforced in main.py before calling here).
No tenant_id filter is applied — these span every tenant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from eep.retail_db import _connect, DatabaseUnavailable


# ─── Model Intelligence (Outcomes) ───────────────────────────────────────────

def get_outcomes_aggregate() -> dict[str, Any]:
    """
    Cross-tenant summary of recommendation accuracy and outcome measurements.
    Used by /admin/outcomes/aggregate.
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                # Platform-wide totals
                cur.execute("""
                    select
                        count(*)                                         as total_decisions,
                        count(*) filter (where status in ('measured_7d','completed'))
                                                                         as measured_count,
                        count(*) filter (
                            where status = 'tracking'
                              and (check_7d_at <= now() or check_14d_at <= now())
                        )                                                as pending_measurements,
                        coalesce(sum(
                            case when m.window_days = 14 then m.revenue_delta_usd else 0 end
                        ), 0)                                            as total_revenue_impact_usd,
                        coalesce(avg(m.accuracy_score), 0)              as avg_accuracy_pct
                    from outcome_tracking.decision_snapshots s
                    left join outcome_tracking.outcome_measurements m
                        on m.snapshot_id = s.id
                """)
                row = cur.fetchone()
                totals = {
                    "total_decisions": int(row["total_decisions"] or 0),
                    "avg_accuracy_pct": round(float(row["avg_accuracy_pct"] or 0), 1),
                    "pending_measurements": int(row["pending_measurements"] or 0),
                    "total_revenue_impact_usd": round(float(row["total_revenue_impact_usd"] or 0), 2),
                }

                # Accuracy by decision type
                cur.execute("""
                    select
                        s.decision_type,
                        count(distinct s.id)                as decision_count,
                        coalesce(avg(m.accuracy_score), 0)  as avg_accuracy
                    from outcome_tracking.decision_snapshots s
                    left join outcome_tracking.outcome_measurements m on m.snapshot_id = s.id
                    group by s.decision_type
                """)
                by_type = {}
                for r in cur.fetchall():
                    by_type[r["decision_type"]] = {
                        "count": int(r["decision_count"]),
                        "avg_accuracy": round(float(r["avg_accuracy"]), 1),
                    }

                # Confidence calibration scatter (max 200 points)
                cur.execute("""
                    select
                        s.ie2_confidence      as confidence,
                        m.accuracy_score      as accuracy
                    from outcome_tracking.decision_snapshots s
                    join outcome_tracking.outcome_measurements m on m.snapshot_id = s.id
                    where s.ie2_confidence is not null and m.accuracy_score is not null
                    order by m.measured_at desc
                    limit 200
                """)
                calibration = [
                    {"confidence": round(float(r["confidence"]), 3), "accuracy": round(float(r["accuracy"]), 1)}
                    for r in cur.fetchall()
                ]

                # Per-tenant performance
                cur.execute("""
                    select
                        t.name                              as tenant_name,
                        t.id                               as tenant_id,
                        count(distinct s.id)               as decisions,
                        coalesce(avg(m.accuracy_score), 0) as avg_accuracy,
                        coalesce(sum(case when m.window_days=14 then m.revenue_delta_usd else 0 end), 0)
                                                           as revenue_delta_usd,
                        max(s.approved_at)                 as last_decision_at
                    from core.tenants t
                    join outcome_tracking.decision_snapshots s on s.tenant_id = t.id
                    left join outcome_tracking.outcome_measurements m on m.snapshot_id = s.id
                    group by t.id, t.name
                    order by avg(m.accuracy_score) desc nulls last
                """)
                per_tenant = [
                    {
                        "tenant_id": str(r["tenant_id"]),
                        "tenant_name": r["tenant_name"],
                        "decisions": int(r["decisions"]),
                        "avg_accuracy": round(float(r["avg_accuracy"]), 1),
                        "revenue_delta_usd": round(float(r["revenue_delta_usd"]), 2),
                        "last_decision_at": r["last_decision_at"].isoformat() if r["last_decision_at"] else None,
                    }
                    for r in cur.fetchall()
                ]

                # Pending measurements (snapshots due for 7d or 14d check)
                cur.execute("""
                    select
                        t.name                  as tenant_name,
                        t.id                    as tenant_id,
                        s.id                    as snapshot_id,
                        s.decision_type,
                        coalesce(p.name || ' ' || coalesce(sv.color,'') || ' ' || coalesce(sv.size,''), sv.sku_id)
                                                as product_name,
                        case
                            when s.check_7d_at <= now() and s.status = 'tracking' then 7
                            else 14
                        end                     as window_days,
                        least(s.check_7d_at, s.check_14d_at) as check_due_at
                    from outcome_tracking.decision_snapshots s
                    join core.tenants t on t.id = s.tenant_id
                    join core.sku_variants sv on sv.id = s.variant_id
                    join core.products p on p.id = sv.product_id
                    where s.status in ('tracking', 'measured_7d')
                      and (s.check_7d_at <= now() + interval '1 day'
                           or s.check_14d_at <= now() + interval '1 day')
                    order by check_due_at asc
                    limit 50
                """)
                pending = [
                    {
                        "snapshot_id": r["snapshot_id"],
                        "tenant_id": str(r["tenant_id"]),
                        "tenant_name": r["tenant_name"],
                        "product_name": r["product_name"].strip(),
                        "decision_type": r["decision_type"],
                        "window_days": r["window_days"],
                        "check_due_at": r["check_due_at"].isoformat() if r["check_due_at"] else None,
                    }
                    for r in cur.fetchall()
                ]

                # 30-day accuracy trend (daily avg)
                cur.execute("""
                    select
                        date_trunc('day', m.measured_at)::date  as day,
                        avg(m.accuracy_score)                   as avg_accuracy
                    from outcome_tracking.outcome_measurements m
                    where m.measured_at >= now() - interval '30 days'
                    group by 1
                    order by 1 asc
                """)
                accuracy_trend = [
                    {"date": str(r["day"]), "avg_accuracy": round(float(r["avg_accuracy"]), 1)}
                    for r in cur.fetchall()
                ]

                return {
                    **totals,
                    "by_decision_type": by_type,
                    "calibration": calibration,
                    "per_tenant": per_tenant,
                    "pending": pending,
                    "accuracy_trend": accuracy_trend,
                }
    except Exception as exc:
        if isinstance(exc, DatabaseUnavailable):
            raise
        raise DatabaseUnavailable(str(exc)) from exc


def admin_trigger_measurement(snapshot_id: int, window_days: int) -> dict[str, Any]:
    """
    Admin can trigger a measurement for any tenant's snapshot.
    Bypasses tenant_id scope check — admin sees all tenants.
    """
    from eep.outcome_tracking import measure_outcome
    # measure_outcome accepts tenant_id=None to skip the ownership check
    try:
        # fetch tenant_id for this snapshot
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select tenant_id from outcome_tracking.decision_snapshots where id = %s",
                    (snapshot_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Snapshot {snapshot_id} not found")
                tenant_id = str(row["tenant_id"])

        return measure_outcome(snapshot_id, window_days, tenant_id=tenant_id)
    except ValueError:
        raise
    except Exception as exc:
        raise DatabaseUnavailable(str(exc)) from exc



# ─── Content Operations (Campaigns) ──────────────────────────────────────────

def get_campaigns_overview() -> dict[str, Any]:
    """
    Cross-tenant campaign activity summary.
    Used by /admin/campaigns/overview.
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                # Totals
                cur.execute("""
                    select
                        count(*)                                                    as total_campaigns,
                        count(*) filter (where c.created_at >= now() - interval '30 days')
                                                                                    as last_30_days,
                        coalesce(avg(c.generation_confidence), 0)                   as avg_confidence,
                        coalesce(
                            count(*) filter (where c.fallback_used = true)::float
                            / nullif(count(*),0) * 100,
                            0
                        )                                                           as fallback_rate_pct
                    from marketing.campaigns c
                    where c.channel is not null
                """)
                row = cur.fetchone()
                totals = {
                    "total_campaigns": int(row["total_campaigns"] or 0),
                    "last_30_days": int(row["last_30_days"] or 0),
                    "avg_confidence_pct": round(float(row["avg_confidence"] or 0) * 100, 1),
                    "fallback_rate_pct": round(float(row["fallback_rate_pct"] or 0), 1),
                }

                # By channel
                cur.execute("""
                    select coalesce(lower(channel), 'unknown') as channel, count(*) as cnt
                    from marketing.campaigns
                    where channel is not null
                    group by 1
                """)
                by_channel: dict[str, int] = {}
                for r in cur.fetchall():
                    by_channel[r["channel"]] = int(r["cnt"])

                # By decision type (via recommendations join)
                cur.execute("""
                    select
                        coalesce(rec.recommendation, 'UNKNOWN') as decision_type,
                        count(*) as cnt
                    from marketing.campaigns c
                    left join marketing.recommendations rec on rec.id = c.recommendation_id
                    group by 1
                """)
                by_decision: dict[str, int] = {}
                for r in cur.fetchall():
                    by_decision[r["decision_type"]] = int(r["cnt"])

                # Fallback rate trend (last 30 days, daily)
                cur.execute("""
                    select
                        date_trunc('day', created_at)::date as day,
                        coalesce(
                            count(*) filter (where fallback_used = true)::float
                            / nullif(count(*), 0) * 100,
                            0
                        ) as fallback_rate_pct
                    from marketing.campaigns
                    where created_at >= now() - interval '30 days'
                    group by 1
                    order by 1 asc
                """)
                fallback_trend = [
                    {"date": str(r["day"]), "fallback_rate_pct": round(float(r["fallback_rate_pct"]), 1)}
                    for r in cur.fetchall()
                ]

                # Per-tenant activity
                cur.execute("""
                    select
                        t.id                                        as tenant_id,
                        t.name                                      as tenant_name,
                        count(c.id)                                 as total,
                        count(c.id) filter (where c.created_at >= now() - interval '30 days')
                                                                    as last_30d,
                        mode() within group (order by c.channel)    as most_used_channel,
                        max(c.created_at)                           as last_campaign_at
                    from core.tenants t
                    left join marketing.campaigns c on c.tenant_id = t.id
                    group by t.id, t.name
                    order by count(c.id) desc
                """)
                per_tenant = [
                    {
                        "tenant_id": str(r["tenant_id"]),
                        "tenant_name": r["tenant_name"],
                        "total": int(r["total"] or 0),
                        "last_30d": int(r["last_30d"] or 0),
                        "most_used_channel": r["most_used_channel"],
                        "last_campaign_at": r["last_campaign_at"].isoformat() if r["last_campaign_at"] else None,
                    }
                    for r in cur.fetchall()
                ]

                # Recent campaigns (last 20)
                cur.execute("""
                    select
                        t.name                              as tenant_name,
                        coalesce(p.name, sv.sku_id)        as product_name,
                        c.channel,
                        c.headline,
                        coalesce(c.tone, 'unknown')         as tone,
                        coalesce(c.generation_confidence, 0) as confidence,
                        coalesce(c.fallback_used, false)    as fallback_used,
                        c.created_at
                    from marketing.campaigns c
                    join core.tenants t on t.id = c.tenant_id
                    left join core.sku_variants sv on sv.id = c.variant_id
                    left join core.products p on p.id = sv.product_id
                    order by c.created_at desc
                    limit 20
                """)
                recent = [
                    {
                        "tenant_name": r["tenant_name"],
                        "product_name": r["product_name"],
                        "channel": r["channel"],
                        "headline": r["headline"],
                        "tone": r["tone"],
                        "confidence_pct": round(float(r["confidence"]) * 100, 1),
                        "fallback_used": bool(r["fallback_used"]),
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in cur.fetchall()
                ]

                # Channels active count
                channels_live = len([k for k, v in by_channel.items() if v > 0])

                return {
                    **totals,
                    "channels_live": channels_live,
                    "by_channel": by_channel,
                    "by_decision_type": by_decision,
                    "fallback_trend": fallback_trend,
                    "per_tenant": per_tenant,
                    "recent": recent,
                }
    except Exception as exc:
        if isinstance(exc, DatabaseUnavailable):
            raise
        raise DatabaseUnavailable(str(exc)) from exc


def persist_campaign(
    tenant_id: str,
    variant_id: str | None,
    recommendation_id: str | None,
    channel: str,
    headline: str,
    body: str,
    tone: str | None,
    generation_confidence: float | None,
    fallback_used: bool,
) -> dict[str, Any]:
    """
    Persist a generated campaign to marketing.campaigns.
    Called after a successful IE3 campaign generation by the shop.
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    insert into marketing.campaigns
                        (tenant_id, variant_id, recommendation_id, channel, status,
                         headline, body, tone, generation_confidence, fallback_used)
                    values (%s, %s, %s, %s, 'published', %s, %s, %s, %s, %s)
                    returning id, created_at
                """, (
                    tenant_id,
                    variant_id,
                    recommendation_id,
                    channel,
                    headline,
                    body,
                    tone,
                    generation_confidence,
                    fallback_used,
                ))
                row = cur.fetchone()
                return {
                    "campaign_id": row["id"],
                    "created_at": row["created_at"].isoformat(),
                    "ok": True,
                }
    except Exception as exc:
        if isinstance(exc, DatabaseUnavailable):
            raise
        raise DatabaseUnavailable(str(exc)) from exc


# ─── Admin Platform Assistant ─────────────────────────────────────────────────

def get_admin_assistant_context() -> dict[str, Any]:
    """
    Fetch a lightweight summary to prime the admin assistant system prompt.
    Returns counts and top-level signals only.
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) as n from core.tenants")
                tenant_count = int(cur.fetchone()["n"])

                cur.execute("""
                    select count(*) as n from intel.competitor_requests
                    where status = 'pending'
                """)
                pending_requests = int(cur.fetchone()["n"])

                cur.execute("""
                    select count(*) as n
                    from outcome_tracking.decision_snapshots
                    where status in ('tracking','measured_7d')
                      and (check_7d_at <= now() + interval '1 day'
                           or check_14d_at <= now() + interval '1 day')
                """)
                pending_measurements = int(cur.fetchone()["n"])

                return {
                    "tenant_count": tenant_count,
                    "pending_competitor_requests": pending_requests,
                    "pending_outcome_measurements": pending_measurements,
                }
    except Exception as exc:
        if isinstance(exc, DatabaseUnavailable):
            raise
        raise DatabaseUnavailable(str(exc)) from exc

