-- ============================================================
-- V017__formula_step_user_label.sql
-- Add user_label to premium_formula_step
-- Replace USER_VALUE with USER_LABEL in parameter_type check
-- ============================================================

-- 1. Add user_label column
ALTER TABLE public.premium_formula_step
    ADD COLUMN IF NOT EXISTS user_label VARCHAR(80);

-- 2. Drop old check constraint
ALTER TABLE public.premium_formula_step
    DROP CONSTRAINT IF EXISTS premium_formula_step_parameter_type_check;

-- 3. Add updated check constraint including USER_LABEL
ALTER TABLE public.premium_formula_step
    ADD CONSTRAINT premium_formula_step_parameter_type_check
    CHECK (parameter_type::text = ANY (ARRAY[
        'USER_VALUE'::text,       -- true constant baked into formula (÷1000 etc)
        'USER_LABEL'::text,       -- named value, provided per proposal / batch row
        'SUM_ASSURED'::text,
        'FACE_AMOUNT'::text,
        'RATE_SCALE'::text,
        'DEBIT_POINTS'::text,
        'POLICY_TERM'::text,
        'ANNUAL_INCOME'::text,
        'AGE'::text,
        'PREVIOUS_RESULT'::text
    ]));

-- 4. Index for quick USER_LABEL lookups per formula
CREATE INDEX IF NOT EXISTS idx_formula_step_user_label
    ON public.premium_formula_step(formula_id, user_label)
    WHERE user_label IS NOT NULL;

-- Verify
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'premium_formula_step'
ORDER BY ordinal_position;
