-- ════════════════════════════════════════════════════════════════════════════
-- V022__integrations_country_code.sql
-- Adds country_code to integration_config and integration_requests.
-- Seeds providers for UAE, Singapore, UK, US alongside existing India providers.
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE integration_config
    ADD COLUMN IF NOT EXISTS country_code VARCHAR(3) NOT NULL DEFAULT 'IN';

ALTER TABLE integration_requests
    ADD COLUMN IF NOT EXISTS country_code VARCHAR(3) DEFAULT 'IN';

ALTER TABLE integration_results
    ADD COLUMN IF NOT EXISTS country_code VARCHAR(3) DEFAULT 'IN';

-- Update existing India providers
UPDATE integration_config SET country_code = 'IN';

-- Index for country filtering
CREATE INDEX IF NOT EXISTS idx_int_config_country ON integration_config(country_code);
CREATE INDEX IF NOT EXISTS idx_int_req_country    ON integration_requests(country_code);

-- Unique constraint now includes country_code
ALTER TABLE integration_config
    DROP CONSTRAINT IF EXISTS uq_integration_config;
ALTER TABLE integration_config
    ADD CONSTRAINT uq_integration_config
    UNIQUE (tenant_id, provider_code, country_code);

-- ── Seed UAE providers ────────────────────────────────────────────────────────
INSERT INTO integration_config
    (tenant_id, provider_code, provider_name, integration_type, country_code, is_enabled, is_mock)
VALUES
  ('00000000-0000-0000-0000-000000000001','EMIRATES_ID_MOCK', 'Emirates ID (Mock)',          'IDENTITY', 'AE', true,  true),
  ('00000000-0000-0000-0000-000000000001','AECB_MOCK',        'AECB Credit Bureau (Mock)',   'CREDIT',   'AE', true,  true),
  ('00000000-0000-0000-0000-000000000001','RTA_MOCK',         'RTA Driving Record (Mock)',   'DRIVING',  'AE', true,  true),
  ('00000000-0000-0000-0000-000000000001','AECB_LIVE',        'AECB Credit (Live)',          'CREDIT',   'AE', false, false),
  ('00000000-0000-0000-0000-000000000001','UAEPAS_LIVE',      'UAE PASS (Live)',             'IDENTITY', 'AE', false, false)
ON CONFLICT (tenant_id, provider_code, country_code) DO NOTHING;

-- ── Seed Singapore providers ──────────────────────────────────────────────────
INSERT INTO integration_config
    (tenant_id, provider_code, provider_name, integration_type, country_code, is_enabled, is_mock)
VALUES
  ('00000000-0000-0000-0000-000000000001','MYINFO_MOCK',      'MyInfo / SingPass (Mock)',    'IDENTITY', 'SG', true,  true),
  ('00000000-0000-0000-0000-000000000001','CBS_MOCK',         'CBS Credit Bureau (Mock)',    'CREDIT',   'SG', true,  true),
  ('00000000-0000-0000-0000-000000000001','LTA_MOCK',         'LTA Driving Record (Mock)',   'DRIVING',  'SG', true,  true),
  ('00000000-0000-0000-0000-000000000001','MYINFO_LIVE',      'MyInfo (Live)',               'IDENTITY', 'SG', false, false)
ON CONFLICT (tenant_id, provider_code, country_code) DO NOTHING;

-- ── Seed UK providers ─────────────────────────────────────────────────────────
INSERT INTO integration_config
    (tenant_id, provider_code, provider_name, integration_type, country_code, is_enabled, is_mock)
VALUES
  ('00000000-0000-0000-0000-000000000001','DVLA_MOCK',        'DVLA Driving Record (Mock)',  'DRIVING',  'GB', true,  true),
  ('00000000-0000-0000-0000-000000000001','EXPERIAN_UK_MOCK', 'Experian UK Credit (Mock)',   'CREDIT',   'GB', true,  true),
  ('00000000-0000-0000-0000-000000000001','YOTI_MOCK',        'Yoti Identity (Mock)',        'IDENTITY', 'GB', true,  true),
  ('00000000-0000-0000-0000-000000000001','EXPERIAN_UK_LIVE', 'Experian UK (Live)',          'CREDIT',   'GB', false, false),
  ('00000000-0000-0000-0000-000000000001','DVLA_LIVE',        'DVLA (Live)',                 'DRIVING',  'GB', false, false)
ON CONFLICT (tenant_id, provider_code, country_code) DO NOTHING;

-- ── Seed US providers ─────────────────────────────────────────────────────────
INSERT INTO integration_config
    (tenant_id, provider_code, provider_name, integration_type, country_code, is_enabled, is_mock)
VALUES
  ('00000000-0000-0000-0000-000000000001','SOCURE_MOCK',      'Socure Identity (Mock)',      'IDENTITY', 'US', true,  true),
  ('00000000-0000-0000-0000-000000000001','EQUIFAX_MOCK',     'Equifax Credit (Mock)',       'CREDIT',   'US', true,  true),
  ('00000000-0000-0000-0000-000000000001','DMV_MOCK',         'DMV Driving Record (Mock)',   'DRIVING',  'US', true,  true),
  ('00000000-0000-0000-0000-000000000001','EQUIFAX_LIVE',     'Equifax (Live)',              'CREDIT',   'US', false, false),
  ('00000000-0000-0000-0000-000000000001','SOCURE_LIVE',      'Socure (Live)',               'IDENTITY', 'US', false, false)
ON CONFLICT (tenant_id, provider_code, country_code) DO NOTHING;
