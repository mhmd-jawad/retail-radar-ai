create schema if not exists telegram;

create table if not exists telegram.registered_chats (
    id           uuid primary key default gen_random_uuid(),
    tenant_id    uuid not null references core.tenants(id) on delete cascade,
    chat_id text not null unique,
    display_name text,
    role         text not null default 'owner' check (role in ('owner','manager','staff')),
    is_active    boolean not null default true,
    created_at   timestamptz not null default now()
);

create table if not exists telegram.conversations (
    chat_id              text primary key,
    tenant_id            uuid not null references core.tenants(id) on delete cascade,
    message_history      jsonb not null default '[]',
    active_flow          text,
    flow_context         jsonb,
    cached_business_data jsonb,
    cached_at            timestamptz,
    last_message_at      timestamptz not null default now(),
    created_at           timestamptz not null default now()
);

create index if not exists idx_tg_conv_chat_id
    on telegram.conversations (chat_id, last_message_at desc);

create table if not exists telegram.promote_notifications (
    id                        uuid primary key default gen_random_uuid(),
    tenant_id                 uuid not null references core.tenants(id) on delete cascade,
    recommendation_id         uuid references marketing.recommendations(id) on delete set null,
    sku_id                    text not null,
    chat_id              text not null,
    message_text              text not null,
    sent_at                   timestamptz not null default now(),
    response                  text,
    response_received_at      timestamptz,
    outcome                   text check (outcome in ('pending','approved','approved_modified','rejected','expired')),
    outcome_at                timestamptz,
    modification_instructions text,
    campaign_id               uuid references marketing.campaigns(id) on delete set null,
    expires_at                timestamptz not null default (now() + interval '24 hours'),
    created_at                timestamptz not null default now()
);

create index if not exists idx_tg_promote_pending
    on telegram.promote_notifications (tenant_id, outcome, expires_at)
    where outcome = 'pending';

create table if not exists telegram.alert_dispatch_log (
    id                uuid primary key default gen_random_uuid(),
    tenant_id         uuid not null references core.tenants(id) on delete cascade,
    alert_fingerprint text not null,
    alert_name        text not null,
    message_sent      text,
    chat_id      text not null,
    sent_at           timestamptz not null default now(),
    resolved_at       timestamptz,
    unique (alert_fingerprint, chat_id)
);
