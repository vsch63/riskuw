-- ============================================================
-- V038__add_queue_premium_mode_applicant_mobile.sql
-- Two columns the code writes but no migration ever created —
-- both were only ever added by hand on the dev database, so a
-- fresh-DB run (CI / make ci-test) failed the writes:
--
--   * policy_admin_queue.premium_mode  — _persist_to_queue inserts
--     it (underwriting.py), default 'ANNUAL'
--   * applicant_master.mobile          — _upsert_applicant_master /
--     _persist_decision upsert it (agent_portal.py, underwriting.py)
--   * application.submitted_by_agent / agent_name / applicant_name —
--     agent_submit stamps these on the application after persisting
--
-- All failures were silently swallowed by try/except, so the queue
-- never received REFERRED agent cases and the applicant contact/agent
-- stamps silently no-op'd. Idempotent — re-apply-safe.
-- ============================================================

ALTER TABLE public.policy_admin_queue
    ADD COLUMN IF NOT EXISTS premium_mode VARCHAR(20) NOT NULL DEFAULT 'ANNUAL';

ALTER TABLE public.applicant_master
    ADD COLUMN IF NOT EXISTS mobile VARCHAR(20);

ALTER TABLE public.application
    ADD COLUMN IF NOT EXISTS submitted_by_agent VARCHAR(100);

ALTER TABLE public.application
    ADD COLUMN IF NOT EXISTS agent_name VARCHAR(200);

ALTER TABLE public.application
    ADD COLUMN IF NOT EXISTS applicant_name VARCHAR(200);
