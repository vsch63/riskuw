-- ============================================================
-- V018__system_user_labels.sql
-- System-level configurable user labels for proposals
-- ============================================================

CREATE TABLE public.system_user_label (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES public.tenant(id),
    label_key       VARCHAR(60)  NOT NULL,          -- machine name: rider_sa
    label_name      VARCHAR(120) NOT NULL,           -- display: Rider Sum Assured
    data_type       VARCHAR(20)  NOT NULL DEFAULT 'CURRENCY'
                        CHECK (data_type IN ('CURRENCY','INTEGER','DECIMAL','PERCENTAGE','TEXT')),
    default_value   VARCHAR(100),                   -- pre-filled value
    description     TEXT,                           -- help text for agent
    prefix          VARCHAR(10),                    -- ₹ for CURRENCY
    suffix          VARCHAR(10),                    -- % for PERCENTAGE
    is_required     BOOLEAN NOT NULL DEFAULT false,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    effective_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date     DATE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_by      VARCHAR(80) NOT NULL DEFAULT 'system',
    updated_by      VARCHAR(80) NOT NULL DEFAULT 'system',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, label_key),
    CONSTRAINT chk_expiry CHECK (expiry_date IS NULL OR expiry_date > effective_date)
);

CREATE INDEX idx_system_user_label_tenant  ON public.system_user_label(tenant_id);
CREATE INDEX idx_system_user_label_active  ON public.system_user_label(tenant_id, is_active)
    WHERE is_active = true;

-- updated_at trigger
CREATE TRIGGER trg_system_user_label_updated
    BEFORE UPDATE ON public.system_user_label
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- Seed common labels for demo tenant
INSERT INTO public.system_user_label
    (tenant_id, label_key, label_name, data_type, default_value,
     description, prefix, suffix, is_required, is_active, sort_order)
VALUES
    ('00000000-0000-0000-0000-000000000001',
     'rider_sa', 'Rider Sum Assured', 'CURRENCY', '500000',
     'Additional rider sum assured opted by proposer', '₹', NULL, false, true, 10),

    ('00000000-0000-0000-0000-000000000001',
     'per_mille_divisor', 'Per Mille Divisor', 'INTEGER', '1000',
     'Divisor used in rate per thousand calculation', NULL, NULL, false, true, 20),

    ('00000000-0000-0000-0000-000000000001',
     'admin_charge', 'Annual Admin Charge', 'CURRENCY', '250',
     'Annual policy administration charge', '₹', NULL, false, true, 30),

    ('00000000-0000-0000-0000-000000000001',
     'loading_pct', 'Substandard Loading %', 'PERCENTAGE', '25',
     'Extra loading percentage for substandard lives', NULL, '%', false, true, 40),

    ('00000000-0000-0000-0000-000000000001',
     'policy_term_override', 'Policy Term Override', 'INTEGER', '20',
     'Override policy term in years if different from product default', NULL, 'yrs', false, true, 50)
ON CONFLICT (tenant_id, label_key) DO NOTHING;

COMMENT ON TABLE public.system_user_label IS
    'System-level configurable input labels — available on proposals, batch CSV, and premium formula steps';
