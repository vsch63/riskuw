-- ============================================================
-- V025__uw_formula_system_level.sql
-- Move the formula engine from product level to system level.
--
--  * premium_formula  -> uw_formula       (tenant-level, product_code NULLABLE:
--    NULL = shared system formula used across all products via formula_type;
--    non-NULL = product-specific override)
--  * premium_formula_step -> uw_formula_step
--  * formula_type expanded: PREMIUM variants + FCL / SAR / MEDICAL /
--    FINANCIAL / REINSURANCE / DECISION (Business Formula Engine, SAR design §6C)
--  * parameter_type expanded: ANNUAL_SALARY / SCHEME_MEMBER_COUNT /
--    EMPLOYER_CODE / POLICY_RESERVE / FUND_VALUE / REFERENCE_TABLE
--  * NEW uw_reference_table / uw_reference_table_row — reusable BAND/EXACT
--    lookups for any formula (FCL age/salary/member-count/employer scales, etc.)
--  * uw_formula_step.reference_table_id FK added
-- ============================================================

-- ── 1. Rename formula tables ──────────────────────────────────────────────────
ALTER TABLE IF EXISTS public.premium_formula      RENAME TO uw_formula;
ALTER TABLE IF EXISTS public.premium_formula_step RENAME TO uw_formula_step;

-- ── 2. tenant_id (backfill demo tenant, then enforce NOT NULL) ─────────────────
ALTER TABLE public.uw_formula
    ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE public.uw_formula
   SET tenant_id = '00000000-0000-0000-0000-000000000001'
 WHERE tenant_id IS NULL;
ALTER TABLE public.uw_formula
    ALTER COLUMN tenant_id SET NOT NULL;

-- ── 3. product_code becomes nullable (NULL = system-level/shared formula) ──────
ALTER TABLE public.uw_formula
    ALTER COLUMN product_code DROP NOT NULL;

-- ── 4. Relax formula_type CHECK ────────────────────────────────────────────────
ALTER TABLE public.uw_formula
    DROP CONSTRAINT IF EXISTS premium_formula_formula_type_check;
ALTER TABLE public.uw_formula
    ADD CONSTRAINT uw_formula_formula_type_check
    CHECK (formula_type::text = ANY (ARRAY[
        'BASE_PREMIUM'::text,     -- legacy premium formula
        'SUBSTANDARD_LOADING'::text,
        'FLAT_EXTRA'::text,
        'GST'::text,
        'PREMIUM'::text,          -- generic premium (alias bucket)
        'FCL'::text,              -- Free Cover Limit (SAR step 5)
        'SAR'::text,              -- reserved — per-benefit SAR formulas
        'MEDICAL'::text,          -- reserved
        'FINANCIAL'::text,        -- reserved — income-multiple checks
        'REINSURANCE'::text,      -- reserved — RI retention
        'DECISION'::text          -- reserved — decision matrix
    ]));

-- ── 5. Relax parameter_type CHECK on steps ─────────────────────────────────────
ALTER TABLE public.uw_formula_step
    DROP CONSTRAINT IF EXISTS premium_formula_step_parameter_type_check;
ALTER TABLE public.uw_formula_step
    ADD CONSTRAINT uw_formula_step_parameter_type_check
    CHECK (parameter_type::text = ANY (ARRAY[
        'USER_VALUE'::text,         -- true constant baked into formula (÷1000 etc)
        'USER_LABEL'::text,         -- named value, provided per proposal / batch row
        'SUM_ASSURED'::text,
        'FACE_AMOUNT'::text,
        'RATE_SCALE'::text,         -- lookup from uw_rate_scale (rich scales)
        'REFERENCE_TABLE'::text,    -- lookup from uw_reference_table (BAND/EXACT)
        'DEBIT_POINTS'::text,
        'POLICY_TERM'::text,
        'ANNUAL_INCOME'::text,
        'ANNUAL_SALARY'::text,      -- FCL salary multiples
        'SCHEME_MEMBER_COUNT'::text,-- FCL member-count scales
        'EMPLOYER_CODE'::text,      -- FCL employer tables (EXACT)
        'POLICY_RESERVE'::text,     -- endowment MORTALITY_PORTION SAR
        'FUND_VALUE'::text,         -- ULIP NET_AMOUNT_AT_RISK SAR
        'AGE'::text,
        'PREVIOUS_RESULT'::text
    ]));

-- ── 6. Rename indexes for the renamed tables ───────────────────────────────────
ALTER INDEX IF EXISTS public.idx_premium_formula_product
    RENAME TO idx_uw_formula_product;
ALTER INDEX IF EXISTS public.idx_premium_formula_step
    RENAME TO idx_uw_formula_step;
ALTER INDEX IF EXISTS public.idx_formula_step_user_label
    RENAME TO idx_uw_formula_step_user_label;

-- ── 7. NEW uw_reference_table / uw_reference_table_row ─────────────────────────
-- Reusable lookup for any formula: FCL Age Scale, FCL Salary Scale, Member Count
-- Scale, Employer FCL Table today; Premium Rate, BMI Debit, Medical Requirement,
-- RI Retention tables in later phases (Business Formula Engine design).
CREATE TABLE public.uw_reference_table (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    table_code      VARCHAR(50) NOT NULL,     -- e.g. FCL_MEMBER_COUNT_SCALE
    table_name      VARCHAR(150) NOT NULL,    -- display name
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_by      VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by      VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, table_code)
);
CREATE INDEX idx_uw_reference_table_tenant ON public.uw_reference_table(tenant_id);
CREATE INDEX idx_uw_reference_table_active ON public.uw_reference_table(tenant_id, is_active);

CREATE TABLE public.uw_reference_table_row (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_table_id  UUID NOT NULL REFERENCES public.uw_reference_table(id) ON DELETE CASCADE,
    match_type          VARCHAR(10) NOT NULL DEFAULT 'BAND'
                            CHECK (match_type IN ('BAND', 'EXACT')),
    band_min            NUMERIC(15,2),        -- used when match_type = BAND
    band_max            NUMERIC(15,2),        -- NULL = no upper bound
    match_value         VARCHAR(50),          -- used when match_type = EXACT (e.g. employer_code)
    output_value        NUMERIC(15,2) NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_reference_row_match
        CHECK (
            (match_type = 'BAND'  AND band_min IS NOT NULL) OR
            (match_type = 'EXACT' AND match_value IS NOT NULL)
        )
);
CREATE INDEX idx_uw_reference_table_row_table ON public.uw_reference_table_row(reference_table_id);

-- ── 8. uw_formula_step.reference_table_id FK ───────────────────────────────────
ALTER TABLE public.uw_formula_step
    ADD COLUMN IF NOT EXISTS reference_table_id UUID
    REFERENCES public.uw_reference_table(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_uw_formula_step_ref_table
    ON public.uw_formula_step(reference_table_id) WHERE reference_table_id IS NOT NULL;

-- ── updated_at triggers ────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

DROP TRIGGER IF EXISTS trg_uw_formula_updated ON public.uw_formula;
CREATE TRIGGER trg_uw_formula_updated
    BEFORE UPDATE ON public.uw_formula
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
DROP TRIGGER IF EXISTS trg_uw_reference_table_updated ON public.uw_reference_table;
CREATE TRIGGER trg_uw_reference_table_updated
    BEFORE UPDATE ON public.uw_reference_table
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ── Comments ──────────────────────────────────────────────────────────────────
COMMENT ON TABLE public.uw_formula IS
    'System-level business formula engine — shared across premium, FCL, SAR, medical, RI (product_code NULL = system-level, non-NULL = product override)';
COMMENT ON TABLE public.uw_formula_step IS
    'Sequential steps in a formula (operator + factor x value); value resolves from constant, input field, rate scale or reference table';
COMMENT ON TABLE public.uw_reference_table IS
    'Reusable BAND/EXACT lookup tables for formula steps (FCL scales, employer tables, etc.)';
COMMENT ON TABLE public.uw_reference_table_row IS
    'Rows of a reference table: BAND (band_min/band_max) or EXACT (match_value) -> output_value';
