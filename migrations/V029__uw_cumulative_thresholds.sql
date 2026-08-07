-- ============================================================
-- V029__uw_cumulative_thresholds.sql
-- Cumulative SAR escalation thresholds per risk group.
--
-- The SAR engine step 8 (_apply_cumulative_thresholds) reads
-- auto_refer / senior_uw / ri_approval / decline thresholds from
-- CumulativeConfig, but the columns never existed on uw_risk_group
-- and load_cumulative_config never populated them — so escalation
-- could never trigger. This adds the columns and seeds sensible
-- defaults so the feature is usable immediately.
--
-- Semantics (total = cumulative existing/pending + current gross SAR):
--   auto_refer_threshold   -> escalation REFER
--   senior_uw_threshold    -> escalation SENIOR_UW
--   ri_approval_threshold  -> escalation RI_APPROVAL
--   decline_threshold      -> escalation DECLINE
--   (higher threshold wins; engine checks in severity order)
-- ============================================================

-- ── 1. Columns ──────────────────────────────────────────────────────────────
ALTER TABLE public.uw_risk_group
    ADD COLUMN IF NOT EXISTS auto_refer_threshold    NUMERIC(15,2),
    ADD COLUMN IF NOT EXISTS senior_uw_threshold     NUMERIC(15,2),
    ADD COLUMN IF NOT EXISTS ri_approval_threshold   NUMERIC(15,2),
    ADD COLUMN IF NOT EXISTS decline_threshold       NUMERIC(15,2);

COMMENT ON COLUMN public.uw_risk_group.auto_refer_threshold IS
    'Cumulative SAR (existing + current) at/above which the case auto-refers to a human underwriter';
COMMENT ON COLUMN public.uw_risk_group.senior_uw_threshold IS
    'Cumulative SAR at/above which the case escalates to senior underwriting';
COMMENT ON COLUMN public.uw_risk_group.ri_approval_threshold IS
    'Cumulative SAR at/above which reinsurer approval is required';
COMMENT ON COLUMN public.uw_risk_group.decline_threshold IS
    'Cumulative SAR at/above which the risk is declined';

-- ── 2. Seed defaults (idempotent: only when the group has no thresholds) ─────
-- Kept conservative: REFER at 1Cr, SENIOR at 1.5Cr, RI at 2Cr, DECLINE at 3Cr.
UPDATE public.uw_risk_group
SET auto_refer_threshold  = 10000000,
    senior_uw_threshold   = 15000000,
    ri_approval_threshold = 20000000,
    decline_threshold     = 30000000
WHERE auto_refer_threshold IS NULL
  AND senior_uw_threshold  IS NULL
  AND ri_approval_threshold IS NULL
  AND decline_threshold    IS NULL
  AND tenant_id = '00000000-0000-0000-0000-000000000001';
