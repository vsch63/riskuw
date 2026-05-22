-- migrations/V002__ri_cession_trigger.sql  (fixed)
-- Fix: cast uuid to text in backfill query (ri_cession.case_id is varchar, uw_decision.case_id is uuid)
-- Fix: use SET ROLE to avoid ownership errors when running as non-owner user

-- ── 1. Helper: get retention limit for a tenant/product ──────────────────────
CREATE OR REPLACE FUNCTION public.get_ri_retention_limit(
    p_tenant_id  uuid,
    p_product_code character varying
) RETURNS numeric
LANGUAGE plpgsql STABLE
AS $$
DECLARE
    v_limit numeric;
BEGIN
    SELECT COALESCE(r.retention_limit, 5000000)
    INTO   v_limit
    FROM   ri_reinsurer r
    WHERE  r.tenant_id    = p_tenant_id
    AND    (r.product_code = p_product_code OR r.product_code IS NULL)
    AND    r.is_active     = true
    AND    (r.treaty_expiry_date IS NULL OR r.treaty_expiry_date > CURRENT_DATE)
    ORDER  BY r.retention_limit ASC
    LIMIT  1;

    RETURN COALESCE(v_limit, 5000000);
END;
$$;

-- ── 2. Trigger function ───────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.trg_auto_ri_cession()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_case           record;
    v_reinsurer_id   integer;
    v_retention      numeric;
    v_cession_amount numeric;
BEGIN
    -- Only fire on final APPROVED decisions
    IF NEW.is_final = false OR NEW.outcome NOT ILIKE '%APPROVED%' THEN
        RETURN NEW;
    END IF;

    -- Load case for face_amount + product_code
    SELECT c.face_amount, c.product_code, c.tenant_id
    INTO   v_case
    FROM   uw_case c
    WHERE  c.id = NEW.case_id;

    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    -- Get retention threshold
    v_retention := public.get_ri_retention_limit(v_case.tenant_id, v_case.product_code);

    -- Only cede if face_amount > retention limit
    IF v_case.face_amount <= v_retention THEN
        RETURN NEW;
    END IF;

    v_cession_amount := v_case.face_amount - v_retention;

    -- Find active reinsurer
    SELECT id INTO v_reinsurer_id
    FROM   ri_reinsurer
    WHERE  tenant_id  = v_case.tenant_id
    AND    is_active   = true
    AND    (treaty_expiry_date IS NULL OR treaty_expiry_date > CURRENT_DATE)
    ORDER  BY retention_limit ASC
    LIMIT  1;

    IF v_reinsurer_id IS NULL THEN
        INSERT INTO audit_trail
            (event_category, event_type, actor_username, entity_type,
             entity_id, after_state, source)
        VALUES
            ('REINSURANCE', 'RI_CESSION_SKIPPED_NO_REINSURER',
             'system', 'uw_decision', NEW.id::text,
             jsonb_build_object(
                 'case_id',        NEW.case_id::text,
                 'face_amount',    v_case.face_amount,
                 'retention_used', v_retention
             ),
             'TRIGGER');
        RETURN NEW;
    END IF;

    -- Insert cession row  (case_id stored as text to match ri_cession.case_id varchar)
    INSERT INTO ri_cession
        (case_id, reinsurer_id, cession_type, face_amount, cession_amount,
         risk_class, treaty_reference, status, created_at)
    VALUES
        (NEW.case_id::text,
         v_reinsurer_id,
         'AUTOMATIC',
         v_case.face_amount,
         v_cession_amount,
         NEW.risk_class,
         'AUTO-' || to_char(now(), 'YYYYMMDD'),
         'PENDING',
         now())
    ON CONFLICT DO NOTHING;

    -- Audit
    INSERT INTO audit_trail
        (event_category, event_type, actor_username, entity_type,
         entity_id, after_state, source)
    VALUES
        ('REINSURANCE', 'RI_CESSION_CREATED',
         'system', 'uw_decision', NEW.id::text,
         jsonb_build_object(
             'case_id',         NEW.case_id::text,
             'reinsurer_id',    v_reinsurer_id,
             'face_amount',     v_case.face_amount,
             'cession_amount',  v_cession_amount,
             'retention_limit', v_retention
         ),
         'TRIGGER');

    RETURN NEW;
END;
$$;

-- ── 3. Attach trigger ─────────────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trg_uw_decision_ri_cession ON public.uw_decision;

CREATE TRIGGER trg_uw_decision_ri_cession
AFTER INSERT ON public.uw_decision
FOR EACH ROW
EXECUTE FUNCTION public.trg_auto_ri_cession();

-- ── 4. Backfill flag for historical high-face approved decisions ──────────────
-- FIX: cast paq.id::text to match ri_cession.case_id (varchar)
INSERT INTO audit_trail
    (event_category, event_type, actor_username, entity_type,
     entity_id, after_state, source)
SELECT
    'REINSURANCE',
    'RI_CESSION_BACKFILL_FLAGGED',
    'migration_V002',
    'policy_admin_queue',
    paq.id::text,
    jsonb_build_object(
        'case_id',     paq.id,
        'face_amount', paq.face_amount,
        'note',        'Manual review required — auto-trigger not applied retroactively'
    ),
    'MIGRATION'
FROM  policy_admin_queue paq
WHERE paq.face_amount > 5000000
AND   paq.outcome ILIKE '%APPROVED%'
AND   NOT EXISTS (
    SELECT 1 FROM ri_cession ri
    WHERE ri.case_id = paq.id::text      -- FIX: cast integer id to text
)
ON CONFLICT DO NOTHING;
