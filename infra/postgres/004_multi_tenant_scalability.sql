-- Migration 004: Full multi-tenant scalability
-- Adds per-tenant financial records, social accounts, Telegram registration codes,
-- and fixes conversation/processed-message isolation.

-- ─── 1. Telegram: registration codes ───────────────────────────────────────────
-- Retailers generate a one-time code in the dashboard, then /register <code>
-- in Telegram to bind their chat_id to their tenant.
CREATE SCHEMA IF NOT EXISTS telegram;

CREATE TABLE IF NOT EXISTS telegram.registration_codes (
    code             text        PRIMARY KEY,
    tenant_id        uuid        NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    created_by       uuid        REFERENCES core.app_users(id) ON DELETE SET NULL,
    expires_at       timestamptz NOT NULL DEFAULT now() + interval '7 days',
    used_at          timestamptz,
    used_by_chat_id  text
);

-- ─── 2. Telegram: fix conversations PRIMARY KEY to (tenant_id, chat_id) ────────
-- Currently chat_id is the sole PK.  Drop it and add the composite key so
-- two different tenants could theoretically share a Telegram group chat
-- without colliding, and so all lookups can be enforced per-tenant.
DO $$
BEGIN
    -- Drop the old single-column PK (constraint name matches what PostgreSQL auto-generates)
    ALTER TABLE telegram.conversations DROP CONSTRAINT IF EXISTS conversations_pkey;
EXCEPTION WHEN others THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE telegram.conversations ADD PRIMARY KEY (tenant_id, chat_id);
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;

-- ─── 3. Telegram: add tenant_id to processed_messages ──────────────────────────
-- processed_messages is created by the Python app at startup via CREATE TABLE IF
-- NOT EXISTS, so it may or may not exist.  We handle both cases.
DO $$
BEGIN
    -- Add column if table exists and column is missing
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'telegram' AND table_name = 'processed_messages'
    ) THEN
        ALTER TABLE telegram.processed_messages
            ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES core.tenants(id) ON DELETE CASCADE;

        -- Back-fill existing rows with the default tenant so the PK change can proceed
        UPDATE telegram.processed_messages
        SET tenant_id = (SELECT id FROM core.tenants WHERE slug = 'default' LIMIT 1)
        WHERE tenant_id IS NULL;

        -- Make it NOT NULL now that all rows are filled
        ALTER TABLE telegram.processed_messages
            ALTER COLUMN tenant_id SET NOT NULL;

        -- Swap PK: message_id → (tenant_id, message_id)
        ALTER TABLE telegram.processed_messages DROP CONSTRAINT IF EXISTS processed_messages_pkey;
        ALTER TABLE telegram.processed_messages ADD PRIMARY KEY (tenant_id, message_id);
    END IF;
END $$;

-- ─── 4. Telegram: tighten closed_loop_notifications unique constraint ────────────
-- The table is also created at runtime by Python.  The current unique constraint
-- is (chat_id, snapshot_id, window_days, notification_type) which doesn't include
-- tenant_id.  We drop and recreate it.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'telegram' AND table_name = 'closed_loop_notifications'
    ) THEN
        -- Drop the old constraint (name derived from CREATE TABLE in outcome_tracking.py)
        ALTER TABLE telegram.closed_loop_notifications
            DROP CONSTRAINT IF EXISTS closed_loop_notifications_chat_id_snapshot_id_window_days_noti_key;

        -- Add new constraint that includes tenant_id
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'closed_loop_notifications_tenant_unique'
              AND conrelid = 'telegram.closed_loop_notifications'::regclass
        ) THEN
            ALTER TABLE telegram.closed_loop_notifications
                ADD CONSTRAINT closed_loop_notifications_tenant_unique
                UNIQUE (tenant_id, chat_id, snapshot_id, window_days, notification_type);
        END IF;
    END IF;
END $$;

-- ─── 5. Per-tenant financial config (mutable OpEx settings) ─────────────────────
CREATE TABLE IF NOT EXISTS core.tenant_financial_config (
    tenant_id              uuid        PRIMARY KEY REFERENCES core.tenants(id) ON DELETE CASCADE,
    currency               text        NOT NULL DEFAULT 'USD',
    opex_categories        jsonb       NOT NULL DEFAULT '[]',
    monthly_fixed_opex_usd numeric(12,2),
    blended_margin_pct     numeric(5,2),
    payment_processing_pct numeric(5,2) NOT NULL DEFAULT 1.5,
    marketing_pct          numeric(5,2) NOT NULL DEFAULT 3.5,
    logistics_pct          numeric(5,2) NOT NULL DEFAULT 2.0,
    shrinkage_pct          numeric(5,2) NOT NULL DEFAULT 0.8,
    updated_at             timestamptz NOT NULL DEFAULT now()
);

-- ─── 6. Per-inventory-event financial records (immutable) ───────────────────────
-- Written once, never updated.  One row per inventory_movement row.
CREATE TABLE IF NOT EXISTS core.inventory_financial_records (
    id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid        NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    movement_id          uuid        NOT NULL REFERENCES core.inventory_movements(id) ON DELETE CASCADE,
    variant_id           uuid        NOT NULL REFERENCES core.sku_variants(id) ON DELETE CASCADE,
    store_id             uuid        REFERENCES core.stores(id) ON DELETE SET NULL,
    movement_type        text        NOT NULL,
    quantity             integer     NOT NULL,
    cost_price_usd       numeric(12,2),
    total_cost_usd       numeric(12,2),
    retail_price_usd     numeric(12,2),
    expected_revenue_usd numeric(12,2),
    expected_margin_pct  numeric(5,2),
    recorded_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (movement_id)  -- one financial record per movement
);

CREATE INDEX IF NOT EXISTS idx_inv_fin_records_tenant_date
    ON core.inventory_financial_records (tenant_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_inv_fin_records_tenant_variant
    ON core.inventory_financial_records (tenant_id, variant_id);

-- ─── 7. Per-tenant social media accounts (campaign publishing) ──────────────────
CREATE TABLE IF NOT EXISTS marketing.tenant_social_accounts (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid        NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    platform         text        NOT NULL CHECK (platform IN ('facebook','instagram','tiktok','whatsapp')),
    account_name     text,
    page_id          text,
    user_id          text,
    access_token     text        NOT NULL,
    token_expires_at timestamptz,
    is_active        boolean     NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, platform)
);
