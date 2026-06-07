-- Tenant-scoped monthly USD financial snapshots.
-- One editable row per retailer per month. Inventory value remains derived from
-- live inventory tables; this table stores retailer-entered financial context.

CREATE TABLE IF NOT EXISTS core.tenant_financial_snapshots (
    id                         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                  uuid        NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    period_month               date        NOT NULL,
    currency                   text        NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),

    cash_on_hand_usd           numeric(12,2) NOT NULL DEFAULT 0 CHECK (cash_on_hand_usd >= 0),
    bank_balance_usd           numeric(12,2) NOT NULL DEFAULT 0 CHECK (bank_balance_usd >= 0),
    receivables_usd            numeric(12,2) NOT NULL DEFAULT 0 CHECK (receivables_usd >= 0),
    inventory_at_cost_usd      numeric(12,2) NOT NULL DEFAULT 0 CHECK (inventory_at_cost_usd >= 0),
    equipment_fixtures_usd     numeric(12,2) NOT NULL DEFAULT 0 CHECK (equipment_fixtures_usd >= 0),
    other_assets_usd           numeric(12,2) NOT NULL DEFAULT 0 CHECK (other_assets_usd >= 0),

    supplier_payables_usd      numeric(12,2) NOT NULL DEFAULT 0 CHECK (supplier_payables_usd >= 0),
    rent_payable_usd           numeric(12,2) NOT NULL DEFAULT 0 CHECK (rent_payable_usd >= 0),
    salary_payable_usd         numeric(12,2) NOT NULL DEFAULT 0 CHECK (salary_payable_usd >= 0),
    loan_balance_usd           numeric(12,2) NOT NULL DEFAULT 0 CHECK (loan_balance_usd >= 0),
    tax_vat_payable_usd        numeric(12,2) NOT NULL DEFAULT 0 CHECK (tax_vat_payable_usd >= 0),
    customer_deposits_usd      numeric(12,2) NOT NULL DEFAULT 0 CHECK (customer_deposits_usd >= 0),
    other_liabilities_usd      numeric(12,2) NOT NULL DEFAULT 0 CHECK (other_liabilities_usd >= 0),

    monthly_sales_usd          numeric(12,2) NOT NULL DEFAULT 0 CHECK (monthly_sales_usd >= 0),
    monthly_expenses_usd       numeric(12,2) NOT NULL DEFAULT 0 CHECK (monthly_expenses_usd >= 0),
    owner_draw_usd             numeric(12,2) NOT NULL DEFAULT 0 CHECK (owner_draw_usd >= 0),

    notes                      text,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, period_month)
);

CREATE INDEX IF NOT EXISTS idx_tenant_fin_snapshots_tenant_month
    ON core.tenant_financial_snapshots (tenant_id, period_month DESC);

CREATE INDEX IF NOT EXISTS idx_tenant_fin_snapshots_tenant_updated
    ON core.tenant_financial_snapshots (tenant_id, updated_at DESC);
