-- V030 — IF/ELSE/ENDIF structural operators + JSONB condition on formula steps
-- ---------------------------------------------------------------------------
-- Phase B of the Business Formula Engine: conditional (branching) formulas.
--   * widen operator so IF / ELSE / ENDIF fit (and leave headroom)
--   * recreate the operator CHECK to allow the three structural operators
--   * add a typed condition tree (JSONB) carried by IF steps:
--       {
--         "logic": "AND",          -- AND | OR
--         "negate": false,         -- optional NOT
--         "clauses": [             -- comparisons and/or nested conditions
--           {"field": "age", "op": "GTE", "value": 40},
--           {"field": "annual_salary", "op": "BETWEEN", "min": 25000, "max": 500000},
--           {"logic": "OR", "negate": true, "clauses": [...]}
--         ]
--       }
-- op values: EQ, NEQ, GT, GTE, LT, LTE, BETWEEN.

ALTER TABLE public.uw_formula_step
    ALTER COLUMN operator TYPE VARCHAR(10);

ALTER TABLE public.uw_formula_step
    DROP CONSTRAINT IF EXISTS premium_formula_step_operator_check;

ALTER TABLE public.uw_formula_step
    ADD CONSTRAINT premium_formula_step_operator_check
    CHECK (operator::text = ANY (ARRAY[
        '+', '-', '*', '/', '%',
        'IF', 'ELSE', 'ENDIF'
    ]::text[]));

ALTER TABLE public.uw_formula_step
    ADD COLUMN IF NOT EXISTS condition JSONB;
