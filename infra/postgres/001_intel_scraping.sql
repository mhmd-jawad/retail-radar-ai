create schema if not exists intel;

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
