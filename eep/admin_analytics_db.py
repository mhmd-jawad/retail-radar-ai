"""
Admin Analytics DB — cross-tenant aggregate queries for the Platform Operations suite.

All functions require admin context (enforced in main.py before calling here).
No tenant_id filter is applied — these span every tenant.
"""

from __future__ import annotations

from typing import Any

from eep.retail_db import _connect, DatabaseUnavailable


# ─── Model Intelligence (Outcomes) ───────────────────────────────────────────

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

                return {
                    "tenant_count": tenant_count,
                    "pending_competitor_requests": pending_requests,
                }
    except Exception as exc:
        if isinstance(exc, DatabaseUnavailable):
            raise
        raise DatabaseUnavailable(str(exc)) from exc

