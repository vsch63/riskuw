-- ============================================================
-- V026__uw_sar_config.sql
-- Sum-at-Risk (SAR) configuration schema — RiskUW_SAR_Framework_v2.3
--
--  * uw_risk_group        — actuarial aggregation buckets (was "clubbing")
--  * uw_exposure_group    — underwriting-treatment buckets (FCL/excess)
--  * uw_benefit_master    — per-benefit SAR config (formula, payer, exposure)
--  * uw_benefit_group_map — many-to-many benefit -> risk group (weight, priority)
--  * uw_aggregation_rule  — per (risk_group, exposure_group, product) method
--  * uw_fcl_config        — Free Cover Limit rules (FLAT or FORMULA via uw_formula)
--  * uw_nml_config        — Non-Medical Limit bands (excess-SAR driven)
--
-- Seeds standard risk/exposure groups, backfills uw_benefit_master from
-- existing products, and maps each benefit into its default risk group.
-- ============================================================

-- ── 1. uw_risk_group ─────────────────────────────────────────────────────────
CREATE TABLE public.uw_risk_group (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                 UUID NOT NULL,
    group_code                VARCHAR(20) NOT NULL,          -- LIFE / ACCIDENT / HEALTH / SAVINGS ...
    group_name                VARCHAR(100) NOT NULL,
    description               TEXT,
    aggregation_method        VARCHAR(30) NOT NULL DEFAULT 'SUM'
                                CHECK (aggregation_method IN
                                       ('SUM','MAXIMUM','WEIGHTED_SUM','CUSTOM_EXPRESSION')),
    -- v2.2: INDIVIDUAL / GROUP / EXPOSURE_GROUP / PROPOSAL / CUSTOMER / GROUP_SCHEME
    uw_threshold_basis        VARCHAR(30) NOT NULL DEFAULT 'INDIVIDUAL',
    include_existing_policies BOOLEAN NOT NULL DEFAULT true,
    include_pending_proposals BOOLEAN NOT NULL DEFAULT true,
    is_active                 BOOLEAN NOT NULL DEFAULT true,
    created_by                VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by                VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, group_code)
);
CREATE INDEX idx_uw_risk_group_tenant ON public.uw_risk_group(tenant_id);

-- ── 2. uw_exposure_group ─────────────────────────────────────────────────────
CREATE TABLE public.uw_exposure_group (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL,
    exposure_code VARCHAR(20) NOT NULL,   -- FREE_COVER / EXCESS_COVER / EMPLOYER_BASE / VOLUNTARY_TOPUP / INDIVIDUAL / OPTIONAL_RIDER ...
    exposure_name VARCHAR(100) NOT NULL,
    description   TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_by    VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by    VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, exposure_code)
);
CREATE INDEX idx_uw_exposure_group_tenant ON public.uw_exposure_group(tenant_id);

-- ── 3. uw_benefit_master ─────────────────────────────────────────────────────
CREATE TABLE public.uw_benefit_master (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL,
    benefit_code       VARCHAR(20) NOT NULL,
    benefit_type       VARCHAR(30) NOT NULL,               -- BASE / RIDER_CI / RIDER_ADB ...
    risk_type          VARCHAR(20) NOT NULL,               -- MORTALITY / MORBIDITY / ACCIDENT / SAVINGS
    uw_exposure_group  VARCHAR(20),                        -- FREE_COVER / EXCESS_COVER / EMPLOYER_BASE / VOLUNTARY_TOPUP / INDIVIDUAL / OPTIONAL_RIDER
    risk_group         VARCHAR(20),                        -- denormalized default risk group (authoritative in uw_benefit_group_map)
    premium_payer      VARCHAR(20) NOT NULL DEFAULT 'ANY'  -- EMPLOYER / EMPLOYEE / JOINT / ANY
                          CHECK (premium_payer IN ('EMPLOYER','EMPLOYEE','JOINT','ANY')),
    underwriting_required BOOLEAN NOT NULL DEFAULT true,
    include_in_sar     BOOLEAN NOT NULL DEFAULT true,
    sar_formula        VARCHAR(30) NOT NULL DEFAULT 'FACE_AMOUNT'
                          CHECK (sar_formula IN
                                 ('FACE_AMOUNT','SUM_OF_SELECTED','MAXIMUM_BENEFIT',
                                  'MORTALITY_PORTION','NET_AMOUNT_AT_RISK','PERCENTAGE','EXPRESSION')),
    sar_percentage     NUMERIC(5,2),
    sar_expression     TEXT,
    processing_sequence INTEGER NOT NULL DEFAULT 0,
    is_active          BOOLEAN NOT NULL DEFAULT true,
    effective_date     DATE,
    expiry_date        DATE,
    created_by         VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by         VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, benefit_code)
);
CREATE INDEX idx_uw_benefit_master_tenant ON public.uw_benefit_master(tenant_id);
CREATE INDEX idx_uw_benefit_master_active ON public.uw_benefit_master(tenant_id, is_active);

-- ── 4. uw_benefit_group_map (many-to-many benefit -> risk group) ──────────────
CREATE TABLE public.uw_benefit_group_map (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    benefit_id    UUID NOT NULL REFERENCES public.uw_benefit_master(id) ON DELETE CASCADE,
    risk_group_id UUID NOT NULL REFERENCES public.uw_risk_group(id) ON DELETE CASCADE,
    weight_pct    NUMERIC(5,2) NOT NULL DEFAULT 100.00,   -- e.g. DD: 60 LIFE / 40 HEALTH
    priority      INTEGER NOT NULL DEFAULT 100,           -- lower = higher; MAXIMUM tie-break
    is_active     BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (benefit_id, risk_group_id)
);
CREATE INDEX idx_uw_benefit_group_map_risk ON public.uw_benefit_group_map(risk_group_id);

-- ── 5. uw_aggregation_rule (v2.2 — method per risk_group + exposure_group + product) ──
CREATE TABLE public.uw_aggregation_rule (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    risk_group_id     UUID NOT NULL REFERENCES public.uw_risk_group(id) ON DELETE CASCADE,
    product_code      VARCHAR(20),          -- NULL = all products
    exposure_group    VARCHAR(20),          -- NULL = all exposure groups
    aggregation_method VARCHAR(30) NOT NULL
                          CHECK (aggregation_method IN
                                 ('SUM','MAXIMUM','WEIGHTED_SUM','CUSTOM_EXPRESSION')),
    is_active         BOOLEAN NOT NULL DEFAULT true,
    effective_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date       DATE,
    created_by        VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by        VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_uw_aggregation_rule_risk ON public.uw_aggregation_rule(tenant_id, risk_group_id);

-- ── 6. uw_fcl_config (Free Cover Limit) ───────────────────────────────────────
CREATE TABLE public.uw_fcl_config (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    product_code          VARCHAR(20) NOT NULL,
    scheme_id             VARCHAR(50),      -- NULL = all schemes
    exposure_group        VARCHAR(20),      -- NULL = applies at product/scheme level (v2.0 behaviour)
    fcl_basis             VARCHAR(20) NOT NULL DEFAULT 'FLAT'
                              CHECK (fcl_basis IN ('FLAT','FORMULA')),
    flat_fcl_amount       NUMERIC(15,2),    -- used when fcl_basis = FLAT
    formula_id            UUID REFERENCES public.uw_formula(id) ON DELETE SET NULL,  -- fcl_basis = FORMULA
    apply_fcl_per_benefit BOOLEAN NOT NULL DEFAULT false,
    premium_payer_filter  VARCHAR(20) NOT NULL DEFAULT 'ANY'
                              CHECK (premium_payer_filter IN ('ANY','EMPLOYER','EMPLOYEE','JOINT','EXCLUDE_EMPLOYER')),
    is_active             BOOLEAN NOT NULL DEFAULT true,
    effective_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date           DATE,
    created_by            VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by            VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_uw_fcl_config_product ON public.uw_fcl_config(tenant_id, product_code, is_active);

-- ── 7. uw_nml_config (Non-Medical Limit — excess-SAR driven) ──────────────────
CREATE TABLE public.uw_nml_config (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                 UUID NOT NULL,
    product_code              VARCHAR(20) NOT NULL,
    age_min                   INTEGER,
    age_max                   INTEGER,
    sar_min                   NUMERIC(15,2) NOT NULL DEFAULT 0,   -- excess-SAR band lower bound
    sar_max                   NUMERIC(15,2),                      -- NULL = no upper bound
    nml_category              VARCHAR(30) NOT NULL
                                  CHECK (nml_category IN
                                         ('NON_MEDICAL','BASIC_MEDICAL','FULL_MEDICAL','JUMBO')),
    medical_tests_required    TEXT[] NOT NULL DEFAULT '{}',
    reinsurer_approval_required BOOLEAN NOT NULL DEFAULT false,
    is_active                 BOOLEAN NOT NULL DEFAULT true,
    effective_date            DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date               DATE,
    created_by                VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by                VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, product_code, age_min, age_max, sar_min, sar_max)
);
CREATE INDEX idx_uw_nml_config_product ON public.uw_nml_config(tenant_id, product_code, is_active);

-- ============================================================
-- SEEDS
-- ============================================================
-- Standard risk groups + exposure groups (idempotent).
INSERT INTO public.uw_risk_group (tenant_id, group_code, group_name, description, aggregation_method, created_by, updated_by)
SELECT '00000000-0000-0000-0000-000000000001', v.code, v.name, v."desc", v.method, 'system', 'system'
FROM (VALUES
    ('LIFE',     'Life Risk',     'Mortality risk — term, whole life, endowment',       'SUM'),
    ('ACCIDENT', 'Accident Risk', 'Accidental death / permanent disablement',            'MAXIMUM'),
    ('HEALTH',   'Health Risk',   'Critical illness, hospital, medical',                 'SUM'),
    ('SAVINGS',  'Savings Risk',  'Endowment / ULIP / pure-savings accumulation',        'SUM'),
    ('CUSTOM',   'Custom Group',  'Carrier-defined actuarial aggregation bucket',        'SUM')
) AS v(code, name, "desc", method)
WHERE NOT EXISTS (SELECT 1 FROM public.uw_risk_group rg
                  WHERE rg.group_code = v.code AND rg.tenant_id = '00000000-0000-0000-0000-000000000001');

INSERT INTO public.uw_exposure_group (tenant_id, exposure_code, exposure_name, description, created_by, updated_by)
SELECT '00000000-0000-0000-0000-000000000001', v.code, v.name, v."desc", 'system', 'system'
FROM (VALUES
    ('FREE_COVER',      'Free Cover',      'Cover provided without medical underwriting'),
    ('EXCESS_COVER',    'Excess Cover',    'Cover above free cover limit'),
    ('EMPLOYER_BASE',   'Employer Base',   'Employer-paid base benefit'),
    ('VOLUNTARY_TOPUP', 'Voluntary Top-Up','Member-paid voluntary cover'),
    ('INDIVIDUAL',      'Individual',      'Individual-policy exposure'),
    ('OPTIONAL_RIDER',  'Optional Rider',  'Optional add-on rider benefit')
) AS v(code, name, "desc")
WHERE NOT EXISTS (SELECT 1 FROM public.uw_exposure_group eg
                  WHERE eg.exposure_code = v.code AND eg.tenant_id = '00000000-0000-0000-0000-000000000001');

-- ── Benefit master backfill from existing products (idempotent) ────────────────
INSERT INTO public.uw_benefit_master (
    tenant_id, benefit_code, benefit_type, risk_type, uw_exposure_group, risk_group,
    premium_payer, underwriting_required, include_in_sar, sar_formula, sar_percentage,
    sar_expression, processing_sequence, is_active, effective_date, expiry_date,
    created_by, updated_by
)
SELECT
    '00000000-0000-0000-0000-000000000001',
    p.product_code,
    'BASE',
    CASE
        WHEN p.product_code ILIKE '%ENDOW%' OR p.product_code ILIKE '%ULIP%' OR p.product_code ILIKE '%SAV%' THEN 'SAVINGS'
        WHEN p.product_code ILIKE '%CI%'    OR p.product_code ILIKE '%CRITICAL%' OR p.product_code ILIKE '%HEALTH%' OR p.product_code ILIKE '%HOSP%' THEN 'HEALTH'
        WHEN p.product_code ILIKE '%PA%'    OR p.product_code ILIKE '%ACCIDENT%' OR p.product_code ILIKE '%ADB%' THEN 'ACCIDENT'
        ELSE 'MORTALITY'
    END,
    CASE WHEN p.is_group_product THEN 'EMPLOYER_BASE' ELSE 'INDIVIDUAL' END,
    CASE
        WHEN p.product_code ILIKE '%ENDOW%' OR p.product_code ILIKE '%ULIP%' OR p.product_code ILIKE '%SAV%' THEN 'SAVINGS'
        WHEN p.product_code ILIKE '%PA%'    OR p.product_code ILIKE '%ACCIDENT%' OR p.product_code ILIKE '%ADB%' THEN 'ACCIDENT'
        WHEN p.product_code ILIKE '%CI%'    OR p.product_code ILIKE '%CRITICAL%' OR p.product_code ILIKE '%HEALTH%' THEN 'HEALTH'
        ELSE 'LIFE'
    END,
    CASE WHEN p.is_group_product THEN 'EMPLOYER' ELSE 'EMPLOYEE' END,
    true, true,
    CASE WHEN p.product_code ILIKE '%ENDOW%' OR p.product_code ILIKE '%ULIP%' THEN 'MORTALITY_PORTION' ELSE 'FACE_AMOUNT' END,
    NULL, NULL, 10, p.is_active, p.effective_date, p.expire_date, 'system', 'system'
FROM public.products p
WHERE p.is_active = true
ON CONFLICT (tenant_id, benefit_code) DO NOTHING;

-- ── Benefit -> risk group default mapping (100% to the benefit's denorm group) ──
INSERT INTO public.uw_benefit_group_map (benefit_id, risk_group_id, weight_pct, priority, is_active)
SELECT bm.id, rg.id, 100.00, 100, true
FROM public.uw_benefit_master bm
JOIN public.uw_risk_group rg
  ON rg.group_code = bm.risk_group AND rg.tenant_id = bm.tenant_id
WHERE bm.tenant_id = '00000000-0000-0000-0000-000000000001'
  AND bm.risk_group IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.uw_benefit_group_map m
                  WHERE m.benefit_id = bm.id AND m.risk_group_id = rg.id);

-- ── NML baseline: mirror each product's existing non_medical_limit ──────────────
-- (a NON_MEDICAL band up to the limit; carriers refine via config UI)
INSERT INTO public.uw_nml_config (
    tenant_id, product_code, age_min, age_max, sar_min, sar_max, nml_category,
    medical_tests_required, reinsurer_approval_required, is_active, effective_date,
    created_by, updated_by
)
SELECT
    '00000000-0000-0000-0000-000000000001', p.product_code, NULL, NULL, 0, p.non_medical_limit,
    'NON_MEDICAL', ARRAY[]::text[], false, true, CURRENT_DATE, 'system', 'system'
FROM public.products p
WHERE p.is_active = true AND p.non_medical_limit IS NOT NULL
ON CONFLICT (tenant_id, product_code, age_min, age_max, sar_min, sar_max) DO NOTHING;

-- ── Comments ──────────────────────────────────────────────────────────────────
COMMENT ON TABLE public.uw_benefit_master IS
    'Per-benefit SAR configuration. benefit_code usually == products.product_code for base plans; riders are RIDER_* benefit_type rows added via product_benefit_config.';
COMMENT ON TABLE public.uw_fcl_config IS
    'Free Cover Limit. fcl_basis=FLAT uses flat_fcl_amount (fast path); FORMULA references a uw_formula row with formula_type=FCL (salary multiples, age bands, member-count scales, employer tables).';
COMMENT ON TABLE public.uw_nml_config IS
    'Non-Medical Limit bands keyed on excess SAR (post-FCL), age and product. Category + required medical tests drive Step 6 of the SAR pipeline.';
