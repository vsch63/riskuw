-- ============================================================
-- V042__tenant_scope_products.sql
--
-- Tenant-scoping sweep (Phase 2, final gap): add tenant_id to the
-- products catalog.  products.py create/list/get read and wrote it
-- without any tenant gate, so every tenant could see and mutate the
-- whole catalog.
--
-- Backfill: products predates tenancy and has no parent table to
-- inherit from — all pre-existing rows belong to the demo tenant
-- (00000000-0000-0000-0000-000000000001), which is also where the
-- dev admin account lives, so existing dev data stays visible.
--
-- All statements are idempotent (IF NOT EXISTS / ADD COLUMN IF
-- NOT EXISTS).  Matches the V040/V041 pattern exactly.
-- ============================================================

-- ── products ────────────────────────────────────────────────────────────────
ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS tenant_id uuid;

-- Backfill: legacy catalog rows are the demo tenant's products.
UPDATE public.products
SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
WHERE tenant_id IS NULL;

-- Enforce NOT NULL.
ALTER TABLE public.products
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN tenant_id SET DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;

-- Index for tenant-scoped catalog lookups.
CREATE INDEX IF NOT EXISTS idx_products_tenant
    ON public.products (tenant_id, product_code);

-- ── Comments ─────────────────────────────────────────────────────────────────
COMMENT ON COLUMN public.products.tenant_id IS
    'Tenant isolation key — every read/write on the product catalog must filter by this column.';
