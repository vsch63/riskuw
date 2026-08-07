-- ============================================================
-- V001b__seed_demo_tenant.sql
-- Seed the canonical demo/default tenant so the many data-seeding
-- migrations that FK to tenant.id (V018 system_user_label, V021-V022
-- integrations, V025-V029 formula/SAR) succeed on a fresh database.
-- Dev databases created the same tenant via older bootstrap scripts,
-- so this is idempotent (ON CONFLICT) and a no-op where it exists.
-- ============================================================

INSERT INTO public.tenant
    (id, tenant_code, tenant_name, status, plan_tier, timezone, created_by)
VALUES
    ('00000000-0000-0000-0000-000000000001',
     'DEMO', 'Demo Tenant', 'ACTIVE', 'STANDARD', 'UTC', 'system')
ON CONFLICT (id) DO NOTHING;
