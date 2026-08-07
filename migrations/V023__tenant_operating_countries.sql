-- ════════════════════════════════════════════════════════════════════════════
-- V023__tenant_operating_countries.sql
-- Adds operating_countries (array) and default_country to tenant table.
-- Currency becomes derived from default_country (with override capability
-- retained in system_config for edge cases — e.g. UAE entity invoicing in USD).
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE tenant
    ADD COLUMN IF NOT EXISTS operating_countries VARCHAR(3)[] NOT NULL DEFAULT '{IN}',
    ADD COLUMN IF NOT EXISTS default_country      VARCHAR(3)  NOT NULL DEFAULT 'IN';

-- Backfill existing tenants to India (current single-market assumption)
UPDATE tenant SET operating_countries = '{IN}', default_country = 'IN'
WHERE operating_countries IS NULL OR default_country IS NULL;

CREATE INDEX IF NOT EXISTS idx_tenant_default_country ON tenant(default_country);
