-- V031 — align the `products` table with the ProductCreate / ProductUpdate
-- models and the ProductConfigPage frontend. The router has been inserting
-- `benefit_terms` / `premium_terms` columns that never existed (a silent
-- 500 on every product create) and treating `exam_required` as a text label
-- ("NONE" / "APS" / "MEDICAL") while the column was boolean. This migration
-- brings the schema to the code's intent:
--   * benefit_terms / premium_terms  → TEXT (comma-joined years)
--   * exam_required                  → TEXT ('NONE' default)

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS benefit_terms TEXT,
    ADD COLUMN IF NOT EXISTS premium_terms TEXT;

ALTER TABLE public.products
    ALTER COLUMN exam_required TYPE TEXT
    USING CASE WHEN exam_required THEN 'MEDICAL' ELSE 'NONE' END;

ALTER TABLE public.products
    ALTER COLUMN exam_required SET DEFAULT 'NONE';
