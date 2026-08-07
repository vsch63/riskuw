-- ============================================================
-- V037__add_agent_broker_roles.sql
-- The agent portal (/agent/*) requires role 'agent' | 'broker'
-- (routers/agent_portal.py AGENT_ROLES), and MFA enforcement lists
-- 'agent' (routers/auth.py MFA_ENFORCED_ROLES) — but V001's
-- chk_user_role constraint only allowed the six original roles, so
-- no agent/broker user could ever be created and the whole portal
-- was unreachable. Add the two roles to the constraint.
--
-- Idempotent: re-apply-safe via the guard block.
-- ============================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_user_role') THEN
        ALTER TABLE public.uw_user DROP CONSTRAINT chk_user_role;
        ALTER TABLE public.uw_user ADD CONSTRAINT chk_user_role CHECK (
            role IN ('super_admin', 'admin', 'senior_underwriter', 'underwriter',
                     'api_client', 'readonly', 'agent', 'broker')
        );
    END IF;
END $$;
