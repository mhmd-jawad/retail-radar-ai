-- Financial profiles: one row per tenant, user-entered balance sheet & cashflow figures
create table if not exists core.financial_profiles (
    tenant_id                       uuid primary key references core.tenants(id) on delete cascade,
    total_assets_usd                numeric(15,2),
    total_liabilities_usd           numeric(15,2),
    monthly_fixed_opex_usd          numeric(12,2),
    annual_revenue_projected_usd    numeric(15,2),
    cash_runway_months              numeric(6,2),
    breakeven_monthly_revenue_usd   numeric(12,2),
    updated_at                      timestamptz not null default now()
);
