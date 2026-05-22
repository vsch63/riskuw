-- ============================================================
-- V014__uw_scales.sql
-- UW Scales & Premium Rate Scales
-- ============================================================

-- ── 1. Master scale ──────────────────────────────────────────
CREATE TABLE public.uw_rate_scale (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES public.tenant(id),
    name                VARCHAR(120) NOT NULL,
    description         TEXT,
    scale_type          VARCHAR(20) NOT NULL
                            CHECK (scale_type IN ('UW', 'PREMIUM')),
    -- only relevant when scale_type = 'PREMIUM'; null for UW scales
    premium_output_type VARCHAR(20)
                            CHECK (premium_output_type IN ('RATE_PER_THOUSAND', 'MULTIPLIER')),
    is_active           BOOLEAN NOT NULL DEFAULT true,
    created_by          VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by          VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_premium_output_type
        CHECK (scale_type <> 'PREMIUM' OR premium_output_type IS NOT NULL)
);

-- ── 2. Tranches ───────────────────────────────────────────────
CREATE TABLE public.uw_scale_tranche (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scale_id         UUID NOT NULL REFERENCES public.uw_rate_scale(id) ON DELETE CASCADE,
    description      VARCHAR(200) NOT NULL,
    effective_date   DATE NOT NULL,
    expiry_date      DATE,                       -- NULL = open-ended
    parameter_logic  VARCHAR(3) NOT NULL DEFAULT 'AND'
                         CHECK (parameter_logic IN ('AND', 'OR')),
    sort_order       INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_tranche_dates
        CHECK (expiry_date IS NULL OR expiry_date > effective_date)
);

-- ── 3. Parameters per tranche ─────────────────────────────────
CREATE TABLE public.uw_tranche_parameter (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tranche_id       UUID NOT NULL REFERENCES public.uw_scale_tranche(id) ON DELETE CASCADE,
    parameter_name   VARCHAR(60) NOT NULL,        -- age | gender | smoker | bmi | ...
    parameter_type   VARCHAR(10) NOT NULL DEFAULT 'RANGE'
                         CHECK (parameter_type IN ('RANGE', 'DISCRETE')),
    min_value        NUMERIC(10,4),
    max_value        NUMERIC(10,4),
    sort_order       INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 4. Age-band output details per tranche ────────────────────
CREATE TABLE public.uw_tranche_detail (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tranche_id       UUID NOT NULL REFERENCES public.uw_scale_tranche(id) ON DELETE CASCADE,
    age_from         INTEGER NOT NULL CHECK (age_from >= 0),
    age_to           INTEGER NOT NULL CHECK (age_to >= 0),
    value            NUMERIC(12,4) NOT NULL,      -- debit pts / rate per 1k / multiplier
    sort_order       INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_age_band CHECK (age_to >= age_from)
);

-- ── 5. Product ↔ Scale attachment ────────────────────────────
CREATE TABLE public.uw_product_scale (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code     VARCHAR(40) NOT NULL,
    scale_id         UUID NOT NULL REFERENCES public.uw_rate_scale(id) ON DELETE CASCADE,
    effective_from   DATE NOT NULL DEFAULT CURRENT_DATE,
    created_by       VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- one active scale per type per product
    UNIQUE (product_code, scale_id)
);

-- ── Indexes ───────────────────────────────────────────────────
CREATE INDEX idx_uw_rate_scale_tenant    ON public.uw_rate_scale(tenant_id);
CREATE INDEX idx_uw_rate_scale_type      ON public.uw_rate_scale(scale_type);
CREATE INDEX idx_uw_scale_tranche_scale  ON public.uw_scale_tranche(scale_id);
CREATE INDEX idx_uw_tranche_param        ON public.uw_tranche_parameter(tranche_id);
CREATE INDEX idx_uw_tranche_detail       ON public.uw_tranche_detail(tranche_id);
CREATE INDEX idx_uw_product_scale_prod   ON public.uw_product_scale(product_code);

-- ── updated_at triggers ───────────────────────────────────────
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

CREATE TRIGGER trg_uw_rate_scale_updated
    BEFORE UPDATE ON public.uw_rate_scale
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER trg_uw_scale_tranche_updated
    BEFORE UPDATE ON public.uw_scale_tranche
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ── Comments ──────────────────────────────────────────────────
COMMENT ON TABLE public.uw_rate_scale      IS 'Master UW and Premium rate scales';
COMMENT ON TABLE public.uw_scale_tranche   IS 'Date-effective tranches within a scale';
COMMENT ON TABLE public.uw_tranche_parameter IS 'Parameter conditions (age/gender/smoker/BMI…) per tranche';
COMMENT ON TABLE public.uw_tranche_detail  IS 'Age-band output values per tranche';
COMMENT ON TABLE public.uw_product_scale   IS 'Product ↔ scale attachments';
