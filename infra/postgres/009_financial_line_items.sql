-- Financial line items: itemized assets and liabilities per tenant
create table if not exists core.financial_line_items (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references core.tenants(id) on delete cascade,
    item_type   text not null check (item_type in ('asset', 'liability')),
    label       text not null,
    amount_usd  numeric(15,2) not null default 0,
    sort_order  int not null default 0,
    updated_at  timestamptz not null default now()
);

create index if not exists idx_financial_line_items_tenant
    on core.financial_line_items (tenant_id, item_type);
