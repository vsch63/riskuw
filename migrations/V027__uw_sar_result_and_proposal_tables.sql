-- ============================================================
-- V027__uw_sar_result_and_proposal_tables.sql
--
-- 1. Creates proposal / proposal_benefit / product_benefit_config —
--    referenced by POST /underwriting/evaluate-proposal and the
--    rider-config endpoint but previously missing from every migration
--    (persistence was silently failing on fresh environments).
--    Uses CREATE TABLE IF NOT EXISTS so existing deployed databases
--    (where these were created ad hoc) are left untouched.
-- 2. Creates uw_sar_result — persists gross/fcl/excess SAR per
--    proposal + risk_group (+ exposure_group) instead of being
--    computed-and-discarded (SAR design §13).
-- 3. Backfills RIDER_* benefits into uw_benefit_master from
--    product_benefit_config.
-- ============================================================

-- ── 1. proposal ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.proposal (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_ref        VARCHAR(50) NOT NULL,
    tenant_id           UUID NOT NULL,
    applicant_ref       VARCHAR(100) NOT NULL,
    overall_status      VARCHAR(30),
    total_annual_premium NUMERIC(15,2),
    premium_mode        VARCHAR(20),
    source              VARCHAR(20) NOT NULL DEFAULT 'ONLINE',
    submitted_by        VARCHAR(100),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, proposal_ref)
);
CREATE INDEX IF NOT EXISTS idx_proposal_tenant ON public.proposal(tenant_id, applicant_ref);

-- ── 2. proposal_benefit ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.proposal_benefit (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id        UUID NOT NULL REFERENCES public.proposal(id) ON DELETE CASCADE,
    benefit_type       VARCHAR(30) NOT NULL,
    product_code       VARCHAR(20) NOT NULL,
    face_amount        NUMERIC(15,2) NOT NULL,
    outcome            VARCHAR(30),
    risk_class         VARCHAR(20),
    net_debit_points   INTEGER,
    annual_premium     NUMERIC(15,2),
    exclusions         JSONB,
    rules_fired        JSONB,
    linked_decline     BOOLEAN NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_proposal_benefit_proposal ON public.proposal_benefit(proposal_id);

-- ── 3. product_benefit_config (base product -> compatible riders) ──────────────
CREATE TABLE IF NOT EXISTS public.product_benefit_config (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL,
    base_product_code  VARCHAR(20) NOT NULL,
    rider_product_code VARCHAR(20) NOT NULL,
    benefit_type       VARCHAR(30) NOT NULL,            -- RIDER_CI / RIDER_ADB / ...
    inherits_medical   BOOLEAN NOT NULL DEFAULT true,
    max_rider_sa_pct   NUMERIC(5,2),
    is_active          BOOLEAN NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, base_product_code, rider_product_code)
);
CREATE INDEX IF NOT EXISTS idx_product_benefit_config_base
    ON public.product_benefit_config(tenant_id, base_product_code, is_active);

-- ── 4. uw_sar_result ───────────────────────────────────────────────────────────
CREATE TABLE public.uw_sar_result (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL,
    proposal_id        UUID NOT NULL,                   -- FK to proposal.id enforced in service layer
    risk_group         VARCHAR(20) NOT NULL,
    exposure_group     VARCHAR(20),
    gross_sar          NUMERIC(15,2) NOT NULL DEFAULT 0,
    fcl_applied        NUMERIC(15,2) NOT NULL DEFAULT 0,
    excess_sar         NUMERIC(15,2) NOT NULL DEFAULT 0,
    cumulative_sar     NUMERIC(15,2),                   -- filled in Phase 3
    source_benefit_ids  JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_uw_sar_result_proposal ON public.uw_sar_result(tenant_id, proposal_id);
CREATE INDEX idx_uw_sar_result_risk_group ON public.uw_sar_result(tenant_id, risk_group);

-- ── 5. Backfill RIDER_* benefits into uw_benefit_master ───────────────────────
-- Runs only if product_benefit_config has rows (it may be empty on a fresh
-- DB; carriers configure rider compatibility in the UI).
INSERT INTO public.uw_benefit_master (
    tenant_id, benefit_code, benefit_type, risk_type, uw_exposure_group, risk_group,
    premium_payer, underwriting_required, include_in_sar, sar_formula, sar_percentage,
    sar_expression, processing_sequence, is_active, created_by, updated_by
)
SELECT
    pbc.tenant_id,
    pbc.rider_product_code,
    pbc.benefit_type,
    CASE
        WHEN pbc.rider_product_code ILIKE '%CI%' OR pbc.rider_product_code ILIKE '%CRITICAL%' OR pbc.rider_product_code ILIKE '%HEALTH%' THEN 'HEALTH'
        WHEN pbc.rider_product_code ILIKE '%PA%' OR pbc.rider_product_code ILIKE '%ACCIDENT%' OR pbc.rider_product_code ILIKE '%ADB%' THEN 'ACCIDENT'
        ELSE 'MORTALITY'
    END,
    'OPTIONAL_RIDER',
    CASE
        WHEN pbc.rider_product_code ILIKE '%CI%' OR pbc.rider_product_code ILIKE '%CRITICAL%' OR pbc.rider_product_code ILIKE '%HEALTH%' THEN 'HEALTH'
        WHEN pbc.rider_product_code ILIKE '%PA%' OR pbc.rider_product_code ILIKE '%ACCIDENT%' OR pbc.rider_product_code ILIKE '%ADB%' THEN 'ACCIDENT'
        ELSE 'LIFE'
    END,
    'EMPLOYEE',
    true, true, 'FACE_AMOUNT', NULL, NULL, 20, pbc.is_active, 'system', 'system'
FROM public.product_benefit_config pbc
WHERE pbc.is_active = true
  AND NOT EXISTS (SELECT 1 FROM public.uw_benefit_master bm
                  WHERE bm.tenant_id = pbc.tenant_id AND bm.benefit_code = pbc.rider_product_code)
ON CONFLICT (tenant_id, benefit_code) DO NOTHING;

-- Map backfilled rider benefits into their default risk group.
INSERT INTO public.uw_benefit_group_map (benefit_id, risk_group_id, weight_pct, priority, is_active)
SELECT bm.id, rg.id, 100.00, 100, true
FROM public.uw_benefit_master bm
JOIN public.uw_risk_group rg
  ON rg.group_code = bm.risk_group AND rg.tenant_id = bm.tenant_id
WHERE bm.tenant_id = '00000000-0000-0000-0000-000000000001'
  AND bm.risk_group IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.uw_benefit_group_map m
                  WHERE m.benefit_id = bm.id AND m.risk_group_id = rg.id);

-- ── Comments ──────────────────────────────────────────────────────────────────
COMMENT ON TABLE public.uw_sar_result IS
    'Persisted Sum-at-Risk output per proposal + risk_group (+ exposure_group): gross SAR, FCL applied, excess SAR. source_benefit_ids maps to the contributing proposal_benefit rows.';
