from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


async def ensure_closed_loop_tables(db_url: str) -> None:
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute("create schema if not exists telegram")
            await cur.execute("create schema if not exists outcome_tracking")
            await cur.execute(
                """
                create table if not exists outcome_tracking.decision_snapshots (
                    id bigserial primary key,
                    tenant_id uuid not null references core.tenants(id) on delete cascade,
                    variant_id uuid not null references core.sku_variants(id) on delete cascade,
                    recommendation_id uuid references marketing.recommendations(id) on delete set null,
                    decision_type text not null check (decision_type in ('HOLD','MARKDOWN','PROMOTE','CLEAR')),
                    approved_at timestamptz not null default now(),
                    baseline_velocity_daily numeric(10,4),
                    baseline_revenue_7d numeric(12,2),
                    baseline_avg_price numeric(12,2),
                    baseline_qty_on_hand integer,
                    baseline_margin_pct numeric(6,2),
                    baseline_dos numeric(10,2),
                    predicted_lift_pct numeric(8,2),
                    ie2_confidence numeric(5,4),
                    ie2_explanation text,
                    suggested_discount_pct numeric(6,2),
                    check_7d_at timestamptz,
                    check_14d_at timestamptz,
                    status text not null default 'tracking'
                        check (status in ('tracking','measured_7d','completed','insufficient_data')),
                    created_at timestamptz not null default now()
                )
                """
            )
            await cur.execute(
                """
                create index if not exists idx_outcome_snapshots_variant
                    on outcome_tracking.decision_snapshots (variant_id, approved_at desc)
                """
            )
            await cur.execute(
                """
                create index if not exists idx_outcome_snapshots_status
                    on outcome_tracking.decision_snapshots (status, check_7d_at)
                """
            )
            await cur.execute(
                """
                create table if not exists outcome_tracking.outcome_measurements (
                    id bigserial primary key,
                    snapshot_id bigint not null references outcome_tracking.decision_snapshots(id) on delete cascade,
                    measured_at timestamptz not null default now(),
                    window_days integer not null check (window_days in (7, 14)),
                    actual_velocity_daily numeric(10,4),
                    actual_revenue_total numeric(12,2),
                    actual_qty_sold integer,
                    actual_avg_price numeric(12,2),
                    actual_margin_pct numeric(6,2),
                    velocity_lift_pct numeric(8,2),
                    revenue_delta_usd numeric(12,2),
                    campaign_roi_usd numeric(12,2),
                    accuracy_score numeric(5,4),
                    narrative text,
                    llm_computed_lift_pct numeric(8,2),
                    llm_computed_revenue_delta numeric(12,2),
                    data_available boolean not null default true,
                    unique (snapshot_id, window_days)
                )
                """
            )
            await cur.execute(
                """
                create table if not exists telegram.promote_notifications (
                    id                       bigserial    primary key,
                    tenant_id                uuid         not null references core.tenants(id) on delete cascade,
                    recommendation_id        uuid         references marketing.recommendations(id) on delete set null,
                    sku_id                   text         not null,
                    chat_id             text         not null,
                    message_text             text         not null,
                    outcome                  text         not null default 'pending'
                                                check (outcome in ('pending','approved','rejected','expired')),
                    modification_instructions text,
                    outcome_at               timestamptz,
                    expires_at               timestamptz  not null,
                    created_at               timestamptz  not null default now()
                )
                """
            )
            await cur.execute(
                """
                create index if not exists idx_promote_notifications_recommendation
                    on telegram.promote_notifications (recommendation_id)
                where outcome = 'pending'
                """
            )
            await cur.execute(
                """
                create table if not exists telegram.closed_loop_notifications (
                    id bigserial primary key,
                    tenant_id uuid not null references core.tenants(id) on delete cascade,
                    chat_id text not null,
                    snapshot_id bigint not null references outcome_tracking.decision_snapshots(id) on delete cascade,
                    window_days integer not null check (window_days in (0, 7, 14)),
                    notification_type text not null,
                    message_text text not null,
                    sent_at timestamptz not null default now(),
                    unique (chat_id, snapshot_id, window_days, notification_type)
                )
                """
            )
        await conn.commit()
    finally:
        await conn.close()


async def get_closed_loop_summary(db_url: str, tenant_id: UUID) -> dict[str, Any]:
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                select
                    count(*) filter (where s.status = 'tracking') as tracking,
                    count(*) filter (where s.status = 'measured_7d') as measured_7d,
                    count(*) filter (where s.status = 'completed') as completed,
                    count(*) filter (
                        where s.status in ('tracking','measured_7d')
                          and (
                            (s.status = 'tracking' and s.check_7d_at <= now())
                            or (s.status = 'measured_7d' and s.check_14d_at <= now())
                          )
                    ) as due_checks,
                    avg(m.accuracy_score) filter (where m.window_days = 7 and m.data_available = true) as avg_accuracy
                from outcome_tracking.decision_snapshots s
                left join outcome_tracking.outcome_measurements m on m.snapshot_id = s.id
                where s.tenant_id = %s
                """,
                (str(tenant_id),),
            )
            summary = await cur.fetchone() or {}

            await cur.execute(
                """
                select s.id as snapshot_id, s.decision_type, s.status, s.approved_at,
                       s.predicted_lift_pct, s.ie2_confidence,
                       v.sku_id, p.name as product_name, p.brand,
                       coalesce(json_agg(
                           json_build_object(
                               'window_days', m.window_days,
                               'velocity_lift_pct', m.velocity_lift_pct,
                               'revenue_delta_usd', m.revenue_delta_usd,
                               'campaign_roi_usd', m.campaign_roi_usd,
                               'accuracy_score', m.accuracy_score,
                               'data_available', m.data_available,
                               'narrative', m.narrative
                           ) order by m.window_days
                       ) filter (where m.id is not null), '[]'::json) as measurements
                from outcome_tracking.decision_snapshots s
                join core.sku_variants v on v.id = s.variant_id
                join core.products p on p.id = v.product_id
                left join outcome_tracking.outcome_measurements m on m.snapshot_id = s.id
                where s.tenant_id = %s
                group by s.id, v.sku_id, p.name, p.brand
                order by s.approved_at desc
                limit 5
                """,
                (str(tenant_id),),
            )
            recent = await cur.fetchall()
    finally:
        await conn.close()

    return {
        "tracking": int(summary.get("tracking") or 0),
        "measured_7d": int(summary.get("measured_7d") or 0),
        "completed": int(summary.get("completed") or 0),
        "due_checks": int(summary.get("due_checks") or 0),
        "avg_accuracy": float(summary["avg_accuracy"]) if summary.get("avg_accuracy") is not None else None,
        "recent": [dict(row) for row in recent],
    }


def format_closed_loop_summary(summary: dict[str, Any]) -> str:
    avg_accuracy = summary.get("avg_accuracy")
    accuracy_line = f"{avg_accuracy * 100:.0f}%" if avg_accuracy is not None else "not enough measured data yet"
    lines = [
        "*Decision progress*",
        f"- Tracking now: *{summary.get('tracking', 0)}*",
        f"- Measured at 7 days: *{summary.get('measured_7d', 0)}*",
        f"- Completed: *{summary.get('completed', 0)}*",
        f"- Due checks: *{summary.get('due_checks', 0)}*",
        f"- Avg model accuracy: *{accuracy_line}*",
    ]
    recent = summary.get("recent") or []
    if recent:
        lines.append("\n*Recent decisions:*")
        for item in recent[:3]:
            measurements = item.get("measurements") or []
            result = "tracking"
            if measurements:
                latest = measurements[-1]
                if latest.get("data_available"):
                    result = (
                        f"{latest.get('window_days')}d lift {latest.get('velocity_lift_pct')}%, "
                        f"revenue delta ${float(latest.get('revenue_delta_usd') or 0):,.2f}"
                    )
                else:
                    result = f"{latest.get('window_days')}d check has no sales data"
            lines.append(
                f"- {item.get('decision_type')} {item.get('brand')} {item.get('product_name')} "
                f"({item.get('sku_id')}): {result}"
            )
    lines.append("\nNext step: ask *AI recommendations* or *generate ad for SKU-ID*.")
    return "\n".join(lines)


async def record_decision_snapshot(
    sku_id: str,
    decision_type: str,
    recommendation_id: str | None,
    cost_price_usd: float,
    tenant_id: UUID | str | None = None,
) -> int | None:
    def _run() -> int | None:
        from eep.outcome_tracking import snapshot_decision
        from eep.retail_db import get_variant_id_for_sku

        variant_id = get_variant_id_for_sku(sku_id, tenant_id=tenant_id)
        if not variant_id:
            return None
        return snapshot_decision(
            sku_id=sku_id,
            variant_id=variant_id,
            decision_type=decision_type,
            recommendation_id=recommendation_id,
            cost_price_usd=cost_price_usd,
            tenant_id=tenant_id,
        )

    return await asyncio.to_thread(_run)


async def due_progress_notifications(
    db_url: str,
    tenant_id: UUID,
    chat_id: str,
) -> list[dict[str, Any]]:
    await ensure_closed_loop_tables(db_url)
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                with due as (
                    select s.id as snapshot_id,
                           case when s.status = 'tracking' then 7 else 14 end as window_days,
                           s.decision_type,
                           s.approved_at,
                           v.sku_id,
                           p.name as product_name,
                           p.brand
                    from outcome_tracking.decision_snapshots s
                    join core.sku_variants v on v.id = s.variant_id
                    join core.products p on p.id = v.product_id
                    where s.tenant_id = %s
                      and (
                        (s.status = 'tracking' and s.check_7d_at <= now())
                        or (s.status = 'measured_7d' and s.check_14d_at <= now())
                      )
                )
                select d.*
                from due d
                left join telegram.closed_loop_notifications n
                  on n.snapshot_id = d.snapshot_id
                 and n.window_days = d.window_days
                 and n.chat_id = %s
                 and n.notification_type = 'measurement_due'
                where n.id is null
                order by d.approved_at asc
                limit 3
                """,
                (str(tenant_id), chat_id),
            )
            rows = await cur.fetchall()
    finally:
        await conn.close()

    notifications: list[dict[str, Any]] = []
    for row in rows:
        message = (
            f"*Decision progress check due*\n"
            f"{row['decision_type']} {row['brand']} {row['product_name']} ({row['sku_id']}) "
            f"is ready for its {row['window_days']}-day outcome check.\n\n"
            "Next step: ask *decision progress* to see all tracked decisions."
        )
        notifications.append({**dict(row), "message": message})
    return notifications


async def mark_progress_notification_sent(
    db_url: str,
    tenant_id: UUID,
    chat_id: str,
    snapshot_id: int,
    window_days: int,
    message: str,
) -> None:
    conn = await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into telegram.closed_loop_notifications
                    (tenant_id, chat_id, snapshot_id, window_days, notification_type, message_text)
                values (%s, %s, %s, %s, 'measurement_due', %s)
                on conflict (chat_id, snapshot_id, window_days, notification_type) do nothing
                """,
                (str(tenant_id), chat_id, snapshot_id, window_days, message),
            )
        await conn.commit()
    finally:
        await conn.close()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def advance_roadmap_on_measurement(
    db_url: str,
    recommendation_id: str | None,
    snapshot_id: int,
    window_days: int,
    velocity_lift_pct: float | None,
    revenue_delta_usd: float | None,
) -> None:
    """
    Called after an outcome measurement is recorded.
    Advances the roadmap stage: 7d → reviewing, 14d → completed.
    """
    if not recommendation_id:
        return
    from services.telegram_assistant.recommendation_roadmap import (
        get_roadmap_id_for_recommendation, advance_stage, close_with_outcome,
    )
    try:
        roadmap_id = await get_roadmap_id_for_recommendation(db_url, recommendation_id)
        if not roadmap_id:
            return
        if window_days == 7:
            await advance_stage(db_url, roadmap_id, "reviewing", actor="system",
                                notes=f"7-day measurement complete — lift {velocity_lift_pct}%")
        elif window_days == 14:
            await close_with_outcome(
                db_url, recommendation_id, snapshot_id,
                velocity_lift_pct, revenue_delta_usd,
            )
    except Exception as exc:
        import logging
        logging.getLogger("telegram_assistant.outcome_tracking").warning(
            "Roadmap advance on measurement failed for rec %s: %s", recommendation_id, exc
        )
