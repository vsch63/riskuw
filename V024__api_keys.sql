-- ════════════════════════════════════════════════════════════════════════════
-- V024__api_keys.sql
-- Self-service API key management for the Developer Portal.
-- Keys are hashed (never stored plaintext) — only shown once at creation.
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    key_hash        VARCHAR(128) NOT NULL,   -- SHA-256 hash of the full key
    key_prefix      VARCHAR(20)  NOT NULL,   -- e.g. "ruw_live_a1b2c3d4" — shown in UI for identification
    name            VARCHAR(100) NOT NULL,   -- user-given label, e.g. "Production - HDFC Bank"
    environment     VARCHAR(10)  NOT NULL DEFAULT 'live',  -- live | sandbox
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    last_used_at    TIMESTAMPTZ,
    last_used_ip    VARCHAR(64),
    request_count   BIGINT       NOT NULL DEFAULT 0,
    expires_at      TIMESTAMPTZ,
    created_by      VARCHAR(100) NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ,
    revoked_by      VARCHAR(100),
    CONSTRAINT uq_api_key_hash UNIQUE (key_hash)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant   ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash     ON api_keys(key_hash) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_api_keys_active   ON api_keys(tenant_id, is_active);

-- Track daily API usage per tenant for the usage dashboard
CREATE TABLE IF NOT EXISTS api_usage_daily (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    api_key_id      INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    usage_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    endpoint        VARCHAR(100) NOT NULL,
    request_count   INTEGER NOT NULL DEFAULT 0,
    error_count     INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_api_usage_daily UNIQUE (tenant_id, api_key_id, usage_date, endpoint)
);

CREATE INDEX IF NOT EXISTS idx_api_usage_tenant_date ON api_usage_daily(tenant_id, usage_date);
