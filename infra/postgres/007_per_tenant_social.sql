-- ─────────────────────────────────────────────────────────────────────────────
-- 007_per_tenant_social.sql
-- Extends marketing.tenant_social_accounts to support per-tenant Telegram bots.
-- Safe to run multiple times (idempotent).
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Add 'telegram' to the allowed platforms
ALTER TABLE marketing.tenant_social_accounts
    DROP CONSTRAINT IF EXISTS tenant_social_accounts_platform_check;

ALTER TABLE marketing.tenant_social_accounts
    ADD CONSTRAINT tenant_social_accounts_platform_check
    CHECK (platform IN ('facebook', 'instagram', 'tiktok', 'telegram'));

-- 2. Track when the Telegram webhook was last successfully registered
--    NULL  = not registered yet (or not a Telegram entry)
--    value = timestamp of last successful setWebhook call
ALTER TABLE marketing.tenant_social_accounts
    ADD COLUMN IF NOT EXISTS webhook_registered_at timestamptz;

-- For Telegram rows:
--   access_token  = bot token from BotFather  (e.g. 123456:ABCdef…)
--   page_id       = NULL
--   user_id       = NULL
--   account_name  = bot username for display (e.g. @ShopBotName) — optional
