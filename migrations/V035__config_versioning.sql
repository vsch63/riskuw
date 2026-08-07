-- V035: Config versioning — effective-dated, append-only config rows.
--
-- Every SAR / pipeline config table gains a `version` counter. Saving a
-- config no longer mutates the row in place: it inserts a NEW row with
-- version = prev + 1 and its own effective/expiry dates. The loaders read
-- the row that is currently effective (effective_date <= today AND
-- (expiry_date IS NULL OR expiry_date > today)).
--
-- Unique keys that previously blocked a second row per (tenant, code) are
-- widened to include `version` so multiple versions can coexist.

-- ── Add version counters ──────────────────────────────────────────────────────
ALTER TABLE uw_benefit_master          ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
ALTER TABLE uw_risk_group              ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
ALTER TABLE uw_exposure_group          ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
ALTER TABLE uw_aggregation_rule        ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
ALTER TABLE uw_fcl_config              ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
ALTER TABLE uw_nml_config              ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
ALTER TABLE uw_medical_standard_rule   ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
ALTER TABLE uw_medical_standard_range  ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;
ALTER TABLE uw_formula                 ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;

-- ── Widen unique keys so multiple versions can coexist ────────────────────────
ALTER TABLE uw_benefit_master
    DROP CONSTRAINT IF EXISTS uw_benefit_master_tenant_id_benefit_code_key;
ALTER TABLE uw_benefit_master
    ADD CONSTRAINT uw_benefit_master_tenant_id_benefit_code_version_key
    UNIQUE (tenant_id, benefit_code, version);

ALTER TABLE uw_risk_group
    DROP CONSTRAINT IF EXISTS uw_risk_group_tenant_id_group_code_key;
ALTER TABLE uw_risk_group
    ADD CONSTRAINT uw_risk_group_tenant_id_group_code_version_key
    UNIQUE (tenant_id, group_code, version);

ALTER TABLE uw_exposure_group
    DROP CONSTRAINT IF EXISTS uw_exposure_group_tenant_id_exposure_code_key;
ALTER TABLE uw_exposure_group
    ADD CONSTRAINT uw_exposure_group_tenant_id_exposure_code_version_key
    UNIQUE (tenant_id, exposure_code, version);

ALTER TABLE uw_nml_config
    DROP CONSTRAINT IF EXISTS uw_nml_config_tenant_id_product_code_age_min_age_max_sar_mi_key;
ALTER TABLE uw_nml_config
    ADD CONSTRAINT uw_nml_config_tenant_id_product_code_age_min_age_max_sar_mi_v_key
    UNIQUE (tenant_id, product_code, age_min, age_max, sar_min, sar_max, version);

-- ── Loader indexes: active-version lookup ─────────────────────────────────────
-- Reference tables (risk/exposure groups) have no dates — supersede marks old
-- versions is_active=false, so index on the tenant-key + is_active.
CREATE INDEX IF NOT EXISTS ix_risk_group_active_version
    ON uw_risk_group (tenant_id, group_code, is_active);
CREATE INDEX IF NOT EXISTS ix_exposure_group_active_version
    ON uw_exposure_group (tenant_id, exposure_code, is_active);
-- Effective-dated tables: index the active-window lookup.
CREATE INDEX IF NOT EXISTS ix_benefit_master_active_version
    ON uw_benefit_master (tenant_id, benefit_code, effective_date, expiry_date);
CREATE INDEX IF NOT EXISTS ix_aggregation_rule_active_version
    ON uw_aggregation_rule (tenant_id, product_code, effective_date, expiry_date);
CREATE INDEX IF NOT EXISTS ix_fcl_config_active_version
    ON uw_fcl_config (tenant_id, product_code, effective_date, expiry_date);
CREATE INDEX IF NOT EXISTS ix_nml_config_active_version
    ON uw_nml_config (tenant_id, product_code, age_min, age_max, effective_date, expiry_date);
