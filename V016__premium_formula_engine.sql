-- ============================================================
-- V016__premium_formula_engine.sql
-- Configurable premium calculation formula per product
-- ============================================================

-- ── 1. Formula header (one per product, can have multiple named formulas) ────
CREATE TABLE public.premium_formula (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code    VARCHAR(20) NOT NULL,
    formula_name    VARCHAR(120) NOT NULL,
    description     TEXT,
    formula_type    VARCHAR(30) NOT NULL DEFAULT 'BASE_PREMIUM'
                        CHECK (formula_type IN ('BASE_PREMIUM', 'SUBSTANDARD_LOADING', 'FLAT_EXTRA', 'GST')),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    effective_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date     DATE,
    created_by      VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by      VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 2. Formula steps (sequential calculation steps) ──────────────────────────
CREATE TABLE public.premium_formula_step (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    formula_id      UUID NOT NULL REFERENCES public.premium_formula(id) ON DELETE CASCADE,
    seq_no          INTEGER NOT NULL,               -- execution order: 10, 20, 30...
    description     VARCHAR(200),                   -- human label e.g. "Multiply by Sum Assured"
    operator        VARCHAR(5) NOT NULL             -- +  -  *  /  %
                        CHECK (operator IN ('+', '-', '*', '/', '%')),
    factor          NUMERIC(14, 6) NOT NULL DEFAULT 1,  -- scalar multiplier e.g. 1, 0.001, 100
    parameter_type  VARCHAR(30) NOT NULL            -- what the step acts on
                        CHECK (parameter_type IN (
                            'USER_VALUE',       -- hardcoded number
                            'SUM_ASSURED',      -- from application
                            'RATE_SCALE',       -- lookup from uw_rate_scale
                            'DEBIT_POINTS',     -- net debit points from UW
                            'POLICY_TERM',      -- coverage_term_yrs
                            'ANNUAL_INCOME',    -- applicant annual income
                            'AGE',              -- applicant age
                            'PREVIOUS_RESULT',  -- result of previous step
                            'FACE_AMOUNT'       -- alias for SUM_ASSURED
                        )),
    user_value      NUMERIC(14, 6),                -- used when parameter_type = USER_VALUE
    scale_id        UUID REFERENCES public.uw_rate_scale(id) ON DELETE SET NULL,
                                                    -- used when parameter_type = RATE_SCALE
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (formula_id, seq_no)
);

-- ── 3. Modal factor config per product ───────────────────────────────────────
CREATE TABLE public.premium_modal_factor (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code    VARCHAR(20) NOT NULL,
    mode            VARCHAR(20) NOT NULL            -- ANNUAL HALF_YEARLY QUARTERLY MONTHLY
                        CHECK (mode IN ('ANNUAL', 'HALF_YEARLY', 'QUARTERLY', 'MONTHLY')),
    factor          NUMERIC(6, 4) NOT NULL,         -- 1.00, 0.51, 0.26, 0.09
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_code, mode)
);

-- ── 4. GST config ─────────────────────────────────────────────────────────────
CREATE TABLE public.premium_gst_config (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code    VARCHAR(20) NOT NULL,
    first_year_rate NUMERIC(5, 2) NOT NULL DEFAULT 18.00,  -- % GST first year
    renewal_rate    NUMERIC(5, 2) NOT NULL DEFAULT 5.00,   -- % GST renewal
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_code)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX idx_premium_formula_product  ON public.premium_formula(product_code);
CREATE INDEX idx_premium_formula_step     ON public.premium_formula_step(formula_id);
CREATE INDEX idx_premium_modal_product    ON public.premium_modal_factor(product_code);

-- ── Seed default modal factors for all products ───────────────────────────────
INSERT INTO public.premium_modal_factor (product_code, mode, factor)
SELECT p.product_code, m.mode, m.factor
FROM public.products p
CROSS JOIN (VALUES
    ('ANNUAL',      1.0000),
    ('HALF_YEARLY', 0.5100),
    ('QUARTERLY',   0.2600),
    ('MONTHLY',     0.0900)
) AS m(mode, factor)
ON CONFLICT (product_code, mode) DO NOTHING;

-- ── Seed default GST config for all products ──────────────────────────────────
INSERT INTO public.premium_gst_config (product_code, first_year_rate, renewal_rate)
SELECT product_code, 18.00, 5.00
FROM public.products
ON CONFLICT (product_code) DO NOTHING;

-- ── Comments ──────────────────────────────────────────────────────────────────
COMMENT ON TABLE public.premium_formula      IS 'Named premium calculation formulas per product';
COMMENT ON TABLE public.premium_formula_step IS 'Sequential steps in a premium formula';
COMMENT ON TABLE public.premium_modal_factor IS 'Modal premium factors per product (annual/quarterly/monthly)';
COMMENT ON TABLE public.premium_gst_config   IS 'GST rates per product (first year vs renewal)';
