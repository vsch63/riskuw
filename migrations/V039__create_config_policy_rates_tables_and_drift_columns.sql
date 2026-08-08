-- ============================================================
-- V039__create_config_policy_rates_tables_and_drift_columns.sql
--
-- Systematic drift fix found by the code-vs-fresh-schema audit
-- (scripts in the hardening pass): 8 tables and 25 columns the
-- code writes to exist only on the dev database (added by hand),
-- never in a migration, so a fresh-DB deploy (CI / make ci-test)
-- fails those writes — silently where wrapped in try/except.
--
--   * gst_config / modal_factor_config / icd10_codes — config
--     pages (gst_modal.py, icd10.py). DDL from dev DB, incl. the
--     daterange EXCLUDE constraints (btree_gist enabled here).
--   * password_reset_tokens — auth.py lazy-creates it at runtime;
--     now created properly in the schema.
--   * policy / policy_premium_history / policy_status_history —
--     ported from the tracked policy_schema.sql (policy_admin.py).
--   * premium_rates — the dev table (age_band_min / rate_per_thousand)
--     matches NO active code; system.py and proposal_uw.py use the
--     newer schema (age_min / rate_per_thou / risk_class / table_rating
--     / flat_extra_rate / rate_label), so the code-aligned table is
--     created. (Dev's legacy premium_rates is dropped separately.)
--   * applicant_master / batch_job_records / proposal_benefit —
--     25 dev-drift columns added idempotently.
--
-- All statements are idempotent (IF NOT EXISTS / ADD COLUMN IF
-- NOT EXISTS), matching the migration style of V037/V038.
-- ============================================================

-- ── Extension for the daterange EXCLUDE constraints ──────────────────────────
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ── gst_config (dev DDL) ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.gst_config (
    id             uuid DEFAULT gen_random_uuid() NOT NULL,
    product_code   varchar(50),
    category       varchar(50) DEFAULT 'LIFE' NOT NULL,
    first_year_rate numeric(5,2) NOT NULL,
    renewal_rate   numeric(5,2) NOT NULL,
    effective_date date NOT NULL,
    expiry_date    date,
    is_active      boolean DEFAULT true NOT NULL,
    created_by     varchar(100) DEFAULT 'system',
    updated_by     varchar(100) DEFAULT 'system',
    created_at     timestamptz DEFAULT now(),
    updated_at     timestamptz DEFAULT now(),
    CONSTRAINT gst_config_pkey PRIMARY KEY (id),
    CONSTRAINT gst_no_overlap EXCLUDE USING gist (
        COALESCE(product_code, '__SYSTEM__') WITH =,
        daterange(effective_date, COALESCE(expiry_date, '9999-12-31'::date), '[]') WITH &&
    )
);

-- ── modal_factor_config (dev DDL) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.modal_factor_config (
    id             uuid DEFAULT gen_random_uuid() NOT NULL,
    product_code   varchar(50),
    mode           varchar(20) NOT NULL,
    factor         numeric(10,4) NOT NULL,
    effective_date date NOT NULL,
    expiry_date    date,
    is_active      boolean DEFAULT true NOT NULL,
    created_by     varchar(100) DEFAULT 'system',
    updated_by     varchar(100) DEFAULT 'system',
    created_at     timestamptz DEFAULT now(),
    updated_at     timestamptz DEFAULT now(),
    CONSTRAINT modal_factor_config_pkey PRIMARY KEY (id),
    CONSTRAINT modal_no_overlap EXCLUDE USING gist (
        COALESCE(product_code, '__SYSTEM__') WITH =,
        mode WITH =,
        daterange(effective_date, COALESCE(expiry_date, '9999-12-31'::date), '[]') WITH &&
    )
);

-- ── icd10_codes (dev DDL; SERIAL id + UNIQUE code) ───────────────────────────
CREATE TABLE IF NOT EXISTS public.icd10_codes (
    id              SERIAL PRIMARY KEY,
    code            varchar(10) NOT NULL UNIQUE,
    description     varchar(300) NOT NULL,
    category        varchar(100),
    debit_points    smallint DEFAULT 0,
    is_hard_decline boolean DEFAULT false,
    severity        varchar(20) DEFAULT 'MODERATE',
    uw_notes        text,
    is_active       boolean DEFAULT true,
    created_at      timestamptz DEFAULT now()
);

-- ── password_reset_tokens (dev DDL; auth.py also lazy-creates it) ────────────
CREATE TABLE IF NOT EXISTS public.password_reset_tokens (
    token        text NOT NULL,
    username     text NOT NULL,
    mfa_verified boolean DEFAULT false NOT NULL,
    expires_at   timestamptz NOT NULL,
    used_at      timestamptz,
    created_at   timestamptz DEFAULT now() NOT NULL
);

-- ── policy tables (ported from tracked policy_schema.sql) ────────────────────
CREATE SEQUENCE IF NOT EXISTS policy_number_seq START 1;

CREATE TABLE IF NOT EXISTS public.policy (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_number           VARCHAR(30) UNIQUE NOT NULL,
    application_id          UUID NOT NULL REFERENCES application(id),
    case_id                 UUID REFERENCES uw_case(id),
    decision_id             UUID REFERENCES uw_decision(id),

    product_code            VARCHAR(20) NOT NULL,
    applicant_ref           VARCHAR(100) NOT NULL,
    applicant_name          VARCHAR(200),

    sum_assured             NUMERIC(15,2) NOT NULL,
    annual_premium          NUMERIC(12,2) NOT NULL,
    premium_mode            VARCHAR(20) DEFAULT 'ANNUAL',
    modal_premium           NUMERIC(12,2),

    risk_class              VARCHAR(30),
    coverage_term_yrs       INT,

    status                  VARCHAR(30) NOT NULL DEFAULT 'PENDING_ACCEPTANCE',
    issue_date              DATE,
    commencement_date       DATE,
    maturity_date           DATE,

    next_premium_due        DATE,
    grace_period_end        DATE,
    last_premium_paid_date  DATE,
    total_premiums_paid     NUMERIC(15,2) DEFAULT 0,

    lapsed_at               TIMESTAMPTZ,
    revived_at              TIMESTAMPTZ,
    surrendered_at          TIMESTAMPTZ,
    surrender_value         NUMERIC(15,2),

    nominee_name            VARCHAR(200),
    nominee_relation        VARCHAR(50),

    tenant_id               UUID NOT NULL,
    created_by              VARCHAR(100) NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT chk_policy_status CHECK (status IN (
        'PENDING_ACCEPTANCE', 'PENDING_FIRST_PREMIUM', 'IN_FORCE',
        'LAPSED', 'REVIVED', 'SURRENDERED', 'MATURED', 'CLAIMED'
    ))
);

CREATE INDEX IF NOT EXISTS idx_policy_status ON policy(status);
CREATE INDEX IF NOT EXISTS idx_policy_tenant ON policy(tenant_id);
CREATE INDEX IF NOT EXISTS idx_policy_applicant_ref ON policy(applicant_ref);
CREATE INDEX IF NOT EXISTS idx_policy_next_premium ON policy(next_premium_due) WHERE status = 'IN_FORCE';

CREATE TABLE IF NOT EXISTS public.policy_premium_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id       UUID NOT NULL REFERENCES policy(id) ON DELETE CASCADE,
    due_date        DATE NOT NULL,
    amount_due      NUMERIC(12,2) NOT NULL,
    amount_paid     NUMERIC(12,2),
    paid_date       DATE,
    status          VARCHAR(20) DEFAULT 'DUE',
    payment_mode    VARCHAR(30),
    receipt_number  VARCHAR(50),
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT chk_premium_status CHECK (status IN ('DUE', 'PAID', 'OVERDUE', 'WAIVED'))
);

CREATE INDEX IF NOT EXISTS idx_premium_history_policy ON policy_premium_history(policy_id);
CREATE INDEX IF NOT EXISTS idx_premium_history_due ON policy_premium_history(due_date) WHERE status = 'DUE';

CREATE TABLE IF NOT EXISTS public.policy_status_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id       UUID NOT NULL REFERENCES policy(id) ON DELETE CASCADE,
    from_status     VARCHAR(30),
    to_status       VARCHAR(30) NOT NULL,
    reason          TEXT,
    changed_by      VARCHAR(100),
    changed_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_status_history_policy ON policy_status_history(policy_id);

-- ── premium_rates — CODE-aligned schema ──────────────────────────────────────
-- The legacy dev table (age_band_min / rate_per_thousand) matches no active
-- code. system.py RateAdd writes age_min/age_max/term_years/risk_class/
-- table_rating/rate_per_thou/flat_extra_rate/rate_label/effective_date/
-- expiry_date and proposal_uw.py reads rate_per_thou. On dev this table is
-- dropped separately so this CREATE takes effect there too.
CREATE TABLE IF NOT EXISTS public.premium_rates (
    id               SERIAL PRIMARY KEY,
    product_code     varchar(20) NOT NULL,
    gender           varchar(10) NOT NULL,
    tobacco_status   varchar(20) DEFAULT 'NON_TOBACCO',
    age_min          integer NOT NULL,
    age_max          integer NOT NULL,
    term_years       integer,
    risk_class       varchar(30) DEFAULT 'STANDARD',
    table_rating     integer DEFAULT 0,
    rate_per_thou    numeric(10,4) NOT NULL,
    flat_extra_rate  numeric(10,4) DEFAULT 0,
    rate_label       varchar(50),
    effective_date   date,
    expiry_date      date,
    created_at       timestamptz DEFAULT now()
);

-- ── dev-drift columns (present only on dev; verified identical in dev) ───────

ALTER TABLE public.applicant_master
    ADD COLUMN IF NOT EXISTS aadhar_masked     varchar(20),
    ADD COLUMN IF NOT EXISTS alternate_phone   varchar(20),
    ADD COLUMN IF NOT EXISTS annual_income     numeric,
    ADD COLUMN IF NOT EXISTS department        varchar(100),
    ADD COLUMN IF NOT EXISTS employee_id       varchar(50),
    ADD COLUMN IF NOT EXISTS group_name        varchar(150),
    ADD COLUMN IF NOT EXISTS is_active         boolean DEFAULT true,
    ADD COLUMN IF NOT EXISTS middle_name       varchar(100),
    ADD COLUMN IF NOT EXISTS nationality       varchar(50) DEFAULT 'Indian',
    ADD COLUMN IF NOT EXISTS nominee_dob       date,
    ADD COLUMN IF NOT EXISTS nominee_name      varchar(150),
    ADD COLUMN IF NOT EXISTS nominee_relation  varchar(50),
    ADD COLUMN IF NOT EXISTS occupation        varchar(100),
    ADD COLUMN IF NOT EXISTS pan_number        varchar(20),
    ADD COLUMN IF NOT EXISTS salutation        varchar(20);

ALTER TABLE public.batch_job_records
    ADD COLUMN IF NOT EXISTS ai_decision     varchar(30),
    ADD COLUMN IF NOT EXISTS ai_engine       varchar(20),
    ADD COLUMN IF NOT EXISTS ai_narrative    text,
    ADD COLUMN IF NOT EXISTS ai_risk_score   numeric,
    ADD COLUMN IF NOT EXISTS ai_risk_tier    varchar(20),
    ADD COLUMN IF NOT EXISTS input_data      text,
    ADD COLUMN IF NOT EXISTS premium         numeric,
    ADD COLUMN IF NOT EXISTS premium_note    text;

ALTER TABLE public.proposal_benefit
    ADD COLUMN IF NOT EXISTS coverage_term_yrs integer,
    ADD COLUMN IF NOT EXISTS processing_ms     integer;
