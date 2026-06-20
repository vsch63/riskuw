CREATE OR REPLACE FUNCTION public.trg_auto_ri_cession()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_case           record;
    v_reinsurer_id   integer;
    v_retention      numeric;
    v_cession_amount numeric;
BEGIN
    IF NEW.is_final = false OR NEW.outcome NOT ILIKE '%APPROVED%' THEN
        RETURN NEW;
    END IF;

    SELECT c.face_amount, c.product_code, c.tenant_id, c.application_id
    INTO   v_case
    FROM   uw_case c
    WHERE  c.id = NEW.case_id;

    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    v_retention := public.get_ri_retention_limit(v_case.tenant_id, v_case.product_code);

    IF v_case.face_amount <= v_retention THEN
        RETURN NEW;
    END IF;

    v_cession_amount := v_case.face_amount - v_retention;

    SELECT id INTO v_reinsurer_id
    FROM   ri_reinsurer
    WHERE  is_active   = true
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

    INSERT INTO ri_cession
        (case_id, application_id, reinsurer_id, cession_type,
         gross_face_amount, retention_amount, ceded_amount,
         status, created_at)
    VALUES
        (NEW.case_id::text,
         v_case.application_id,
         v_reinsurer_id,
         'AUTOMATIC',
         v_case.face_amount,
         v_retention,
         v_cession_amount,
         'PENDING',
         now())
    ON CONFLICT DO NOTHING;

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
$function$;
