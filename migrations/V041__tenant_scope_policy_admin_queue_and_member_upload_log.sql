-- ============================================================
-- V041__tenant_scope_policy_admin_queue_and_member_upload_log.sql
--
-- Tenant-scoping sweep (Phase 2, second pass): add tenant_id to
-- the two remaining work-stream tables that lack it:
--
--   * policy_admin_queue  — the single-case decision queue read by
--     /workbench, /queue, dashboard_stats and the push service.  A
--     cross-tenant id fetch here would leak another tenant's case.
--     Backfills from applicant_master.tenant_id via applicant_ref
--     (every row carries an applicant_ref; batch job ids are not
--     uuids in current data, so the job_id path is omitted).
--   * member_upload_log   — the members upload-history table.  The
--     uploading user is recorded as a username; backfills from
--     uw_user.tenant_id via uploaded_by.
--
-- All statements are idempotent (IF NOT EXISTS / ADD COLUMN IF
-- NOT EXISTS).  Matches the V040 pattern exactly.
-- ============================================================

-- ── policy_admin_queue ──────────────────────────────────────────────────────
ALTER TABLE public.policy_admin_queue
    ADD COLUMN IF NOT EXISTS tenant_id uuid;

-- Backfill from applicant_master (best-effort; orphan rows keep NULL).
UPDATE public.policy_admin_queue pq
SET tenant_id = am.tenant_id
FROM public.applicant_master am
WHERE pq.applicant_ref = am.applicant_ref
  AND pq.tenant_id IS NULL
  AND am.tenant_id IS NOT NULL;

-- Default remaining NULLs to the demo tenant so NOT NULL can be added.
UPDATE public.policy_admin_queue
SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE tenant_id IS NULL;

-- Enforce NOT NULL.
ALTER TABLE public.policy_admin_queue
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN tenant_id SET DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;

-- Index for tenant-scoped queue lookups (status feeds the workbench filter).
CREATE INDEX IF NOT EXISTS idx_policy_admin_queue_tenant
    ON public.policy_admin_queue (tenant_id, status, created_at);

-- ── member_upload_log ────────────────────────────────────────────────────────
ALTER TABLE public.member_upload_log
    ADD COLUMN IF NOT EXISTS tenant_id uuid;

-- Backfill from the uploading user's tenant.
UPDATE public.member_upload_log mul
SET tenant_id = u.tenant_id
FROM public.uw_user u
WHERE mul.uploaded_by = u.username
  AND mul.tenant_id IS NULL
  AND u.tenant_id IS NOT NULL;

-- Default remaining NULLs to the demo tenant so NOT NULL can be added.
UPDATE public.member_upload_log
SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE tenant_id IS NULL;

-- Enforce NOT NULL.
ALTER TABLE public.member_upload_log
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN tenant_id SET DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;

-- Index for tenant-scoped upload-history queries.
CREATE INDEX IF NOT EXISTS idx_member_upload_log_tenant
    ON public.member_upload_log (tenant_id, uploaded_at);

-- ── Comments ─────────────────────────────────────────────────────────────────
COMMENT ON COLUMN public.policy_admin_queue.tenant_id IS
    'Tenant isolation key — every read/write on the decision queue must filter by this column.';

COMMENT ON COLUMN public.member_upload_log.tenant_id IS
    'Tenant isolation key — backfilled from uw_user.tenant_id via uploaded_by.';
