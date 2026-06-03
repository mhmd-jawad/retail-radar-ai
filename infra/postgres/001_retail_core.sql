create extension if not exists pgcrypto;

create schema if not exists core;
create schema if not exists intel;
create schema if not exists marketing;

create table if not exists core.tenants (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    slug text not null unique,
    default_currency text not null default 'USD',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists core.stores (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    code text not null,
    name text not null,
    timezone text not null default 'Asia/Beirut',
    currency text not null default 'USD',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, code)
);

create table if not exists core.app_users (
    id uuid primary key default gen_random_uuid(),
    email text not null,
    password_hash text not null,
    full_name text not null,
    global_role text not null default 'shop' check (global_role in ('admin', 'shop')),
    is_active boolean not null default true,
    email_verified boolean not null default false,
    last_login_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists ux_app_users_email_lower
    on core.app_users (lower(email));

create table if not exists core.user_memberships (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references core.app_users(id) on delete cascade,
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    role text not null default 'owner' check (role in ('owner', 'manager', 'staff')),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, tenant_id)
);

create index if not exists idx_user_memberships_tenant
    on core.user_memberships (tenant_id, is_active);

create table if not exists core.shop_profiles (
    tenant_id uuid primary key references core.tenants(id) on delete cascade,
    owner_user_id uuid references core.app_users(id) on delete set null,
    business_name text not null,
    legal_name text,
    contact_email text,
    phone text,
    website_url text,
    address text,
    country text not null default 'Lebanon',
    timezone text not null default 'Asia/Beirut',
    onboarding_status text not null default 'pending' check (
        onboarding_status in ('pending', 'active', 'suspended', 'archived')
    ),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists core.auth_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references core.app_users(id) on delete cascade,
    token_hash text not null unique,
    expires_at timestamptz not null,
    revoked_at timestamptz,
    user_agent text,
    ip_address text,
    created_at timestamptz not null default now()
);

create index if not exists idx_auth_sessions_user_active
    on core.auth_sessions (user_id, expires_at)
    where revoked_at is null;

create table if not exists core.suppliers (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    name text not null,
    contact_name text,
    phone text,
    email text,
    notes text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, name)
);

create table if not exists core.products (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    brand text not null,
    name text not null,
    category text not null default 'uncategorized',
    gender_target text,
    season text,
    status text not null default 'active' check (status in ('active', 'archived')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_products_tenant_category
    on core.products (tenant_id, category);

create table if not exists core.sku_variants (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    product_id uuid not null references core.products(id) on delete cascade,
    sku_id text not null,
    barcode text,
    style_code text,
    color text,
    size text,
    cost_price_usd numeric(12,2) not null default 0,
    reorder_point integer not null default 0,
    reorder_quantity integer not null default 0,
    supplier_id uuid references core.suppliers(id) on delete set null,
    notes text,
    status text not null default 'active' check (status in ('active', 'archived')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, sku_id)
);

create index if not exists idx_sku_variants_style_code
    on core.sku_variants (tenant_id, style_code);

create index if not exists idx_sku_variants_supplier
    on core.sku_variants (tenant_id, supplier_id);

create unique index if not exists ux_sku_variants_barcode
    on core.sku_variants (tenant_id, barcode)
    where barcode is not null and barcode <> '';

create table if not exists core.prices (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    variant_id uuid not null references core.sku_variants(id) on delete cascade,
    price_type text not null default 'retail' check (price_type in ('retail', 'sale')),
    currency text not null default 'USD',
    amount numeric(12,2) not null check (amount >= 0),
    valid_from timestamptz not null default now(),
    valid_to timestamptz,
    created_at timestamptz not null default now()
);

create unique index if not exists ux_prices_current
    on core.prices (variant_id, price_type)
    where valid_to is null;

create table if not exists core.inventory_balances (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    store_id uuid not null references core.stores(id) on delete cascade,
    variant_id uuid not null references core.sku_variants(id) on delete cascade,
    quantity_on_hand integer not null default 0 check (quantity_on_hand >= 0),
    quantity_reserved integer not null default 0 check (quantity_reserved >= 0),
    updated_at timestamptz not null default now(),
    unique (tenant_id, store_id, variant_id)
);

create table if not exists core.inventory_movements (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    store_id uuid not null references core.stores(id) on delete cascade,
    variant_id uuid not null references core.sku_variants(id) on delete cascade,
    movement_type text not null check (
        movement_type in (
            'initial_stock',
            'purchase_receipt',
            'sale',
            'return',
            'adjustment_in',
            'adjustment_out',
            'transfer_in',
            'transfer_out',
            'damaged',
            'full_import_adjustment'
        )
    ),
    quantity_delta integer not null,
    unit_cost_usd numeric(12,2),
    reference_type text,
    reference_id text,
    notes text,
    created_by text not null default 'system',
    created_at timestamptz not null default now()
);

create index if not exists idx_inventory_movements_variant_created
    on core.inventory_movements (variant_id, created_at desc);

create table if not exists core.purchase_orders (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    supplier_id uuid references core.suppliers(id) on delete set null,
    store_id uuid references core.stores(id) on delete set null,
    po_number text not null,
    status text not null default 'draft' check (status in ('draft', 'ordered', 'partially_received', 'received', 'cancelled')),
    expected_at date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, po_number)
);

create table if not exists core.purchase_order_lines (
    id uuid primary key default gen_random_uuid(),
    purchase_order_id uuid not null references core.purchase_orders(id) on delete cascade,
    variant_id uuid not null references core.sku_variants(id) on delete restrict,
    quantity_ordered integer not null check (quantity_ordered > 0),
    quantity_received integer not null default 0 check (quantity_received >= 0),
    unit_cost_usd numeric(12,2) not null default 0,
    created_at timestamptz not null default now()
);

create table if not exists core.sales_transactions (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    store_id uuid references core.stores(id) on delete set null,
    external_sale_id text,
    sold_at timestamptz not null default now(),
    channel text not null default 'manual',
    total_amount_usd numeric(12,2) not null default 0,
    created_at timestamptz not null default now(),
    unique (tenant_id, external_sale_id)
);

create table if not exists core.sales_transaction_lines (
    id uuid primary key default gen_random_uuid(),
    sales_transaction_id uuid not null references core.sales_transactions(id) on delete cascade,
    variant_id uuid not null references core.sku_variants(id) on delete restrict,
    quantity integer not null check (quantity > 0),
    unit_price_usd numeric(12,2) not null default 0,
    unit_cost_usd numeric(12,2) not null default 0,
    discount_pct numeric(6,2) not null default 0,
    created_at timestamptz not null default now()
);

create table if not exists intel.shops (
    shop_code text primary key,
    shop_name text not null,
    apify_actor_id text,
    apify_task_id text,
    is_active boolean not null default true,
    expected_frequency text not null default 'daily',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists intel.tenant_competitors (
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    shop_code text not null references intel.shops(shop_code) on delete restrict,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (tenant_id, shop_code)
);

create index if not exists idx_tenant_competitors_active
    on intel.tenant_competitors (tenant_id, is_active);

create table if not exists intel.competitor_requests (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    requested_by_user_id uuid references core.app_users(id) on delete set null,
    competitor_name text not null,
    website_url text,
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'onboarded')),
    admin_notes text,
    created_at timestamptz not null default now(),
    reviewed_at timestamptz,
    reviewed_by_user_id uuid references core.app_users(id) on delete set null
);

create index if not exists idx_competitor_requests_status
    on intel.competitor_requests (status, created_at desc);

create index if not exists idx_competitor_requests_tenant
    on intel.competitor_requests (tenant_id, created_at desc);

create table if not exists intel.scrape_runs (
    id bigserial primary key,
    shop_code text not null references intel.shops(shop_code) on delete restrict,
    apify_run_id text not null unique,
    apify_dataset_id text,
    status text not null default 'succeeded',
    started_at timestamptz,
    finished_at timestamptz,
    item_count integer not null default 0,
    ingest_status text not null default 'pending',
    ingest_error text,
    raw_webhook_payload jsonb,
    created_at timestamptz not null default now()
);

create table if not exists intel.competitor_product_snapshots (
    id bigserial primary key,
    shop_code text not null references intel.shops(shop_code) on delete restrict,
    scrape_run_id bigint not null references intel.scrape_runs(id) on delete cascade,
    snapshot_at timestamptz not null default now(),
    product_key text not null,
    competitor_product_id text,
    style_code text,
    sku_id text,
    brand_name text,
    product_name text not null,
    category text,
    gender_target text,
    competitor_price numeric(12,2),
    competitor_sale_price numeric(12,2),
    discount_pct numeric(6,2),
    is_on_sale boolean not null default false,
    availability text,
    currency text not null default 'USD',
    sizes_available jsonb,
    source_url text,
    data_valid boolean not null default true,
    raw_record jsonb,
    unique (scrape_run_id, product_key)
);

create index if not exists idx_competitor_snapshots_style
    on intel.competitor_product_snapshots (style_code);

create index if not exists idx_competitor_snapshots_shop_snapshot
    on intel.competitor_product_snapshots (shop_code, snapshot_at desc);

create table if not exists intel.competitor_products_latest (
    shop_code text not null references intel.shops(shop_code) on delete restrict,
    product_key text not null,
    last_scrape_run_id bigint not null references intel.scrape_runs(id) on delete cascade,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    competitor_product_id text,
    style_code text,
    sku_id text,
    brand_name text,
    product_name text not null,
    category text,
    gender_target text,
    competitor_price numeric(12,2),
    competitor_sale_price numeric(12,2),
    discount_pct numeric(6,2),
    is_on_sale boolean not null default false,
    availability text,
    currency text not null default 'USD',
    sizes_available jsonb,
    source_url text,
    data_valid boolean not null default true,
    raw_record jsonb,
    primary key (shop_code, product_key)
);

create index if not exists idx_competitor_latest_style
    on intel.competitor_products_latest (style_code);

create table if not exists marketing.recommendations (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    variant_id uuid references core.sku_variants(id) on delete set null,
    recommendation text not null check (recommendation in ('HOLD', 'MARKDOWN', 'PROMOTE', 'CLEAR')),
    confidence numeric(5,4) not null default 0,
    suggested_price_usd numeric(12,2),
    suggested_discount_pct numeric(6,2),
    status text not null default 'pending' check (status in ('pending', 'approved', 'edited', 'rejected', 'snoozed')),
    explanation text,
    generated_by text not null default 'ie2',
    generated_at timestamptz not null default now(),
    reviewed_by text,
    reviewed_at timestamptz
);

create table if not exists marketing.campaigns (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references core.tenants(id) on delete cascade,
    recommendation_id uuid references marketing.recommendations(id) on delete set null,
    variant_id uuid references core.sku_variants(id) on delete set null,
    channel text not null,
    status text not null default 'draft' check (status in ('draft', 'approved', 'scheduled', 'published', 'archived')),
    headline text,
    body text,
    starts_at timestamptz,
    ends_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists core.audit_logs (
    id bigserial primary key,
    tenant_id uuid references core.tenants(id) on delete cascade,
    actor text not null default 'system',
    entity_type text not null,
    entity_id text not null,
    action text not null,
    before_state jsonb,
    after_state jsonb,
    created_at timestamptz not null default now()
);

insert into core.tenants (id, name, slug, default_currency)
values ('00000000-0000-0000-0000-000000000001', 'Default Retailer', 'default', 'USD')
on conflict (slug) do update set
    name = excluded.name,
    default_currency = excluded.default_currency,
    updated_at = now();

insert into core.stores (id, tenant_id, code, name, currency)
values (
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000001',
    'MAIN',
    'Main Store',
    'USD'
)
on conflict (tenant_id, code) do update set
    name = excluded.name,
    currency = excluded.currency,
    is_active = true,
    updated_at = now();

insert into intel.shops (shop_code, shop_name)
values
    ('adidas_lb', 'Adidas Lebanon'),
    ('mikesport', 'Mike Sport'),
    ('tchooz', 'Tchooz'),
    ('shoesworld', 'ShoesWorld'),
    ('citysport', 'CitySport'),
    ('kix', 'KIX'),
    ('marka_store', 'Marka Store')
on conflict (shop_code) do update set
    shop_name = excluded.shop_name,
    is_active = true,
    updated_at = now();
