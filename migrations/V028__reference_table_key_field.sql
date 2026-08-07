-- ============================================================
-- V028__reference_table_key_field.sql
-- Reference tables now declare which applicant field they are
-- keyed on (key_field). The formula builder uses this to
-- pre-fill the step's lookup key when a table is picked, so the
-- builder never shows a generic "Label / key" for REFERENCE_TABLE.
--
-- Also seeds the demo lookup tables the design docs reference
-- (FCL Age / Salary / Member-Count / Employer) so the builder's
-- Ref Table dropdown is not empty on a fresh install.
-- ============================================================

-- ── 1. key_field column ──────────────────────────────────────────────────────
ALTER TABLE public.uw_reference_table
    ADD COLUMN IF NOT EXISTS key_field VARCHAR(50);

COMMENT ON COLUMN public.uw_reference_table.key_field IS
    'Applicant input field this table is keyed on (age, annual_salary, scheme_member_count, employer_code, ...). Pre-fills the formula step lookup key.';

-- ── 2. Seed demo tables ──────────────────────────────────────────────────────
INSERT INTO public.uw_reference_table
    (id, tenant_id, table_code, table_name, description, key_field, is_active, created_by, updated_by)
VALUES
    ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
     'FCL_AGE_SCALE', 'FCL Age Scale',
     'Free cover limit multiple by applicant age', 'age', true, 'system', 'system'),
    ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001',
     'FCL_SALARY_SCALE', 'FCL Salary Scale',
     'Free cover limit multiple by annual salary', 'annual_salary', true, 'system', 'system'),
    ('10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001',
     'FCL_MEMBER_COUNT_SCALE', 'FCL Member Count Scale',
     'Free cover limit multiple by scheme member count', 'scheme_member_count', true, 'system', 'system'),
    ('10000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001',
     'EMPLOYER_FCL_TABLE', 'Employer FCL Table',
     'Employer-specific free cover limit (EXACT match on employer_code)', 'employer_code', true, 'system', 'system')
ON CONFLICT (tenant_id, table_code) DO NOTHING;

-- ── 3. Seed rows (idempotent: wipe + reinsert for the seeded tables) ────────
DELETE FROM public.uw_reference_table_row
WHERE reference_table_id IN (
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000004'
);

INSERT INTO public.uw_reference_table_row
    (reference_table_id, match_type, band_min, band_max, match_value, output_value, is_active, sort_order)
VALUES
    -- FCL_AGE_SCALE (keyed on age)
    ('10000000-0000-0000-0000-000000000001', 'BAND', 0,   25, NULL, 1.0, true, 10),
    ('10000000-0000-0000-0000-000000000001', 'BAND', 26,  35, NULL, 1.2, true, 20),
    ('10000000-0000-0000-0000-000000000001', 'BAND', 36,  45, NULL, 1.5, true, 30),
    ('10000000-0000-0000-0000-000000000001', 'BAND', 46,  55, NULL, 2.0, true, 40),
    ('10000000-0000-0000-0000-000000000001', 'BAND', 56,  NULL, NULL, 3.0, true, 50),
    -- FCL_SALARY_SCALE (keyed on annual_salary)
    ('10000000-0000-0000-0000-000000000002', 'BAND', 0,      100000, NULL, 1.0, true, 10),
    ('10000000-0000-0000-0000-000000000002', 'BAND', 100001, 500000, NULL, 2.0, true, 20),
    ('10000000-0000-0000-0000-000000000002', 'BAND', 500001, NULL,   NULL, 4.0, true, 30),
    -- FCL_MEMBER_COUNT_SCALE (keyed on scheme_member_count)
    ('10000000-0000-0000-0000-000000000003', 'BAND', 0,   10, NULL, 1.0, true, 10),
    ('10000000-0000-0000-0000-000000000003', 'BAND', 11,  50, NULL, 1.5, true, 20),
    ('10000000-0000-0000-0000-000000000003', 'BAND', 51,  200, NULL, 2.5, true, 30),
    ('10000000-0000-0000-0000-000000000003', 'BAND', 201, NULL, NULL, 4.0, true, 40),
    -- EMPLOYER_FCL_TABLE (EXACT on employer_code)
    ('10000000-0000-0000-0000-000000000004', 'EXACT', NULL, NULL, 'TECHM',    10000000, true, 10),
    ('10000000-0000-0000-0000-000000000004', 'EXACT', NULL, NULL, 'INFY',     5000000,  true, 20),
    ('10000000-0000-0000-0000-000000000004', 'EXACT', NULL, NULL, 'RELIANCE', 20000000, true, 30);
