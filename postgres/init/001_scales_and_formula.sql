-- UW Rate Scale
CREATE TABLE IF NOT EXISTS public.uw_rate_scale (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(120) NOT NULL,
    scale_type      VARCHAR(30) NOT NULL DEFAULT 'UW',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.uw_scale_tranche (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scale_id        UUID NOT NULL REFERENCES public.uw_rate_scale(id) ON DELETE CASCADE,
    description     VARCHAR(200),
    parameter_logic VARCHAR(20) NOT NULL DEFAULT 'AND',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    effective_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date     DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.uw_tranche_parameter (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tranche_id      UUID NOT NULL REFERENCES public.uw_scale_tranche(id) ON DELETE CASCADE,
    parameter_name  VARCHAR(80) NOT NULL,
    min_value       NUMERIC(14,4),
    max_value       NUMERIC(14,4),
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS public.uw_product_scale (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code    VARCHAR(50) NOT NULL,
    scale_id        UUID NOT NULL REFERENCES public.uw_rate_scale(id) ON DELETE CASCADE,
    UNIQUE(product_code, scale_id)
);

CREATE TABLE IF NOT EXISTS public.premium_formula_step (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    formula_id      UUID NOT NULL REFERENCES public.premium_formula(id) ON DELETE CASCADE,
    seq_no          INTEGER NOT NULL,
    description     VARCHAR(200),
    operator        VARCHAR(5) NOT NULL CHECK (operator IN ('+', '-', '*', '/', '%')),
    factor          NUMERIC(14,6) NOT NULL DEFAULT 1,
    parameter_type  VARCHAR(30) NOT NULL CHECK (parameter_type IN (
        'USER_VALUE','USER_LABEL','SUM_ASSURED','FACE_AMOUNT',
        'RATE_SCALE','DEBIT_POINTS','POLICY_TERM',
        'ANNUAL_INCOME','AGE','PREVIOUS_RESULT'
    )),
    user_value      NUMERIC(14,6),
    user_label      VARCHAR(80),
    scale_id        UUID REFERENCES public.uw_rate_scale(id) ON DELETE SET NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(formula_id, seq_no)
);

CREATE TABLE IF NOT EXISTS public.system_user_label (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    label_key       VARCHAR(80) NOT NULL,
    label_name      VARCHAR(120) NOT NULL,
    data_type       VARCHAR(20) NOT NULL DEFAULT 'CURRENCY',
    default_value   VARCHAR(200),
    description     TEXT,
    prefix          VARCHAR(10),
    suffix          VARCHAR(10),
    is_required     BOOLEAN NOT NULL DEFAULT false,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    effective_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date     DATE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_by      VARCHAR(80),
    updated_by      VARCHAR(80),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, label_key)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_uw_scale_tranche_scale    ON public.uw_scale_tranche(scale_id);
CREATE INDEX IF NOT EXISTS idx_uw_tranche_param          ON public.uw_tranche_parameter(tranche_id);
CREATE INDEX IF NOT EXISTS idx_uw_product_scale          ON public.uw_product_scale(product_code);
CREATE INDEX IF NOT EXISTS idx_premium_formula_step      ON public.premium_formula_step(formula_id);
CREATE INDEX IF NOT EXISTS idx_formula_step_user_label   ON public.premium_formula_step(formula_id, user_label) WHERE user_label IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_system_user_label_tenant  ON public.system_user_label(tenant_id);
