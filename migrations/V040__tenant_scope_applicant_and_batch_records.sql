-- ============================================================
-- V040__tenant_scope_applicant_and_batch_records.sql
--
-- Tenant-scoping sweep (Phase 2): add tenant_id to tables that
-- the codebase now filters by tenant but which lack the column:
--
--   * applicant_master — every router that touches applicants
--     (agent_portal, proposal_uw, members, underwriting) must
--     scope reads/writes by tenant.  Backfills from application.tenant_id
--     where applicant_ref matches.
--   * batch_job_records — analytics / workbench / batch_processor
--     query these without a tenant gate today.  Backfills from
--     batch_jobs.tenant_id via job_id FK.
--
-- All statements are idempotent (IF NOT EXISTS / ADD COLUMN IF
-- NOT EXISTS).
-- ============================================================

-- ── applicant_master ─────────────────────────────────────────────────────────
ALTER TABLE public.applicant_master
    ADD COLUMN IF NOT EXISTS tenant_id uuid;

-- Backfill from application table (best-effort; orphan applicants keep NULL).
UPDATE public.applicant_master am
SET tenant_id = a.tenant_id
FROM public.application a
WHERE am.applicant_ref = a.applicant_ref
  AND am.tenant_id IS NULL
  AND a.tenant_id IS NOT NULL;

-- Default remaining NULLs to the demo tenant so NOT NULL can be added.
UPDATE public.applicant_master
SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE tenant_id IS NULL;

-- Now enforce NOT NULL (safe after backfill).
ALTER TABLE public.applicant_master
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN tenant_id SET DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;

-- Unique constraint: one applicant_ref per tenant. The legacy single-column
-- unique on applicant_ref must go — it would otherwise block the same ref
-- existing in two different tenants.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_applicant_master_tenant_ref'
    ) THEN
        ALTER TABLE public.applicant_master
            ADD CONSTRAINT uq_applicant_master_tenant_ref
            UNIQUE (tenant_id, applicant_ref);
    END IF;
END $$;

ALTER TABLE public.applicant_master
    DROP CONSTRAINT IF EXISTS applicant_master_applicant_ref_key;

-- Index for tenant-scoped lookups.
CREATE INDEX IF NOT EXISTS idx_applicant_master_tenant
    ON public.applicant_master (tenant_id, applicant_ref);

-- ── batch_job_records ────────────────────────────────────────────────────────
ALTER TABLE public.batch_job_records
    ADD COLUMN IF NOT EXISTS tenant_id uuid;

-- Backfill from parent batch_jobs table.
UPDATE public.batch_job_records bjr
SET tenant_id = bj.tenant_id
FROM public.batch_jobs bj
WHERE bjr.job_id = bj.id
  AND bjr.tenant_id IS NULL
  AND bj.tenant_id IS NOT NULL;

-- Default remaining NULLs to the demo tenant so NOT NULL can be added.
UPDATE public.batch_job_records
SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE tenant_id IS NULL;

-- Enforce NOT NULL.
ALTER TABLE public.batch_job_records
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN tenant_id SET DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;

-- Index for tenant-scoped analytics queries.
CREATE INDEX IF NOT EXISTS idx_batch_job_records_tenant
    ON public.batch_job_records (tenant_id, job_id);

-- ── Comments ─────────────────────────────────────────────────────────────────
COMMENT ON COLUMN public.applicant_master.tenant_id IS
    'Tenant isolation key — every read/write on applicant data must filter by this column.';

COMMENT ON COLUMN public.batch_job_records.tenant_id IS
    'Tenant isolation key — backfilled from batch_jobs.tenant_id via job_id.';
