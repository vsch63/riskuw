-- ════════════════════════════════════════════════════════════════════════════
-- V021__external_integrations.sql
-- Pluggable external data integration framework.
-- Supports: CKYC, CIBIL/Experian, Lab/Diagnostic, AML, Pharmacy DB, Driving
--
-- Tables:
--   integration_config    — per-tenant provider config (keys, endpoint, enabled)
--   integration_requests  — every verification call made
--   integration_results   — structured result from provider
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS integration_config (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    tenant_id       VARCHAR(40)  NOT NULL,
    provider_code   VARCHAR(40)  NOT NULL,
        -- CKYC_MOCK | CKYC_CDSL | CIBIL | EXPERIAN | LAB_MOCK | LAB_HEALTHIANS
        -- | LAB_1MG | AML_MOCK | PHARMACY_MOCK | DRIVING_MOCK
    provider_name   VARCHAR(100) NOT NULL,
    integration_type VARCHAR(30) NOT NULL,
        -- IDENTITY | CREDIT | LAB | AML | PHARMACY | DRIVING
    is_enabled      BOOLEAN      NOT NULL DEFAULT true,
    is_mock         BOOLEAN      NOT NULL DEFAULT true,
    api_endpoint    TEXT,
    api_key_enc     TEXT,                  -- encrypted API key (store-only, never returned)
    config_json     JSONB,                 -- extra provider-specific config
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_integration_config UNIQUE (tenant_id, provider_code)
);

-- Sequence for request_ref — must be created BEFORE integration_requests table
CREATE SEQUENCE IF NOT EXISTS integration_req_seq START 1;

CREATE TABLE IF NOT EXISTS integration_requests (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    request_ref     VARCHAR(40)  NOT NULL UNIQUE DEFAULT
                        ('IREQ-' || to_char(now(),'YYYYMMDD') || '-' ||
                         lpad(nextval('integration_req_seq'::regclass)::text,6,'0')),
    tenant_id       VARCHAR(40),
    case_ref_id     INTEGER,               -- policy_admin_queue.id (nullable for standalone calls)
    applicant_ref   VARCHAR(100),
    integration_type VARCHAR(30) NOT NULL, -- IDENTITY | CREDIT | LAB | AML | PHARMACY | DRIVING
    provider_code   VARCHAR(40)  NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
        -- PENDING | SUBMITTED | COMPLETED | FAILED | TIMEOUT | MOCK
    request_payload JSONB,
    requested_by    VARCHAR(100),
    requested_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS integration_results (
    id                  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    request_id          INTEGER NOT NULL REFERENCES integration_requests(id) ON DELETE CASCADE,
    provider_code       VARCHAR(40)  NOT NULL,
    integration_type    VARCHAR(30)  NOT NULL,
    applicant_ref       VARCHAR(100),
    case_ref_id         INTEGER,
    -- Identity / KYC fields
    kyc_verified        BOOLEAN,
    kyc_name            VARCHAR(200),
    kyc_dob             DATE,
    kyc_pan             VARCHAR(20),
    kyc_aadhaar_masked  VARCHAR(20),
    kyc_address         TEXT,
    -- Credit fields
    credit_score        INTEGER,
    credit_bureau       VARCHAR(50),
    credit_report_ref   VARCHAR(100),
    credit_flags        JSONB,             -- ["LOAN_DEFAULT_2022","MULTIPLE_ENQUIRIES"]
    -- Lab fields
    lab_order_ref       VARCHAR(100),
    lab_tests           JSONB,             -- [{"test":"HbA1c","value":6.2,"unit":"%","normal_range":"<5.7","flag":"HIGH"}]
    lab_report_url      TEXT,
    -- AML fields
    aml_status          VARCHAR(20),       -- CLEAR | HIT | MANUAL_REVIEW
    aml_flags           JSONB,
    -- General
    confidence_score    NUMERIC(4,2),      -- 0.0-1.0
    raw_response        JSONB,
    verified_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ,       -- result validity period
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_int_req_applicant  ON integration_requests(applicant_ref);
CREATE INDEX IF NOT EXISTS idx_int_req_case        ON integration_requests(case_ref_id);
CREATE INDEX IF NOT EXISTS idx_int_req_type        ON integration_requests(integration_type);
CREATE INDEX IF NOT EXISTS idx_int_req_status      ON integration_requests(status);
CREATE INDEX IF NOT EXISTS idx_int_res_request     ON integration_results(request_id);
CREATE INDEX IF NOT EXISTS idx_int_res_applicant   ON integration_results(applicant_ref);
CREATE INDEX IF NOT EXISTS idx_int_res_type        ON integration_results(integration_type);

-- ── Seed default mock providers for demo tenant ───────────────────────────────
INSERT INTO integration_config (tenant_id, provider_code, provider_name, integration_type, is_enabled, is_mock)
VALUES
  ('00000000-0000-0000-0000-000000000001','CKYC_MOCK',      'CKYC (Mock)',             'IDENTITY', true, true),
  ('00000000-0000-0000-0000-000000000001','CIBIL_MOCK',     'CIBIL (Mock)',             'CREDIT',   true, true),
  ('00000000-0000-0000-0000-000000000001','LAB_MOCK',       'Lab (Mock)',               'LAB',      true, true),
  ('00000000-0000-0000-0000-000000000001','AML_MOCK',       'AML Check (Mock)',         'AML',      true, true),
  ('00000000-0000-0000-0000-000000000001','PHARMACY_MOCK',  'Pharmacy DB (Mock)',       'PHARMACY', true, true),
  ('00000000-0000-0000-0000-000000000001','DRIVING_MOCK',   'Driving Record (Mock)',    'DRIVING',  true, true),
  ('00000000-0000-0000-0000-000000000001','CKYC_CDSL',      'CKYC (CDSL Live)',        'IDENTITY', false, false),
  ('00000000-0000-0000-0000-000000000001','LAB_HEALTHIANS', 'Healthians',              'LAB',      false, false),
  ('00000000-0000-0000-0000-000000000001','LAB_1MG',        '1mg',                     'LAB',      false, false),
  ('00000000-0000-0000-0000-000000000001','CIBIL_LIVE',     'CIBIL (Live)',            'CREDIT',   false, false)
ON CONFLICT (tenant_id, provider_code) DO NOTHING;

