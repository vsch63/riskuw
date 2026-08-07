-- V034 — data-driven underwriting standards (Phase 2).
--
-- The R001–R080 catalogue previously lived as Python if/elif in
-- backend/services/uw_engine.py. This migration makes it table-driven:
--
--   uw_medical_standard        — a tunable standard group (one row per
--                                code+tenant+product; NULL tenant/product =
--                                system level).
--   uw_medical_standard_rule   — evaluation variants under a standard:
--                                'FLAT'  (condition -> fixed points) or
--                                'RANGE' (numeric param -> banded points).
--                                Conditions are the typed condition tree the
--                                formula engine evaluates (op: EQ/NEQ/GT/
--                                GTE/LT/LTE/IN/NOT_IN/BETWEEN/CONTAINS_ANY).
--   uw_medical_standard_range  — point bands for RANGE rules (min/max are
--                                inclusive unless min_exclusive/max_exclusive).
--
-- The system-level seed below mirrors the engine's current hardcoded
-- behaviour exactly (verified against backend/tests/test_evaluate.py), so
-- risk outcomes are identical until an insurer tunes a range or rule. The
-- engine falls back to built-in defaults when the DB has no rows (pure unit
-- path), so unit tests pass without a database.

-- ── Schema ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS uw_medical_standard (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenant(id) ON DELETE CASCADE,   -- NULL = system
    product_code    TEXT,                                           -- NULL = all products
    standard_code   TEXT NOT NULL,      -- e.g. 'R001', 'R010' (repeats across levels)
    family          TEXT NOT NULL,      -- display grouping (Build / Tobacco / ...)
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,      -- AGE/TOBACCO/BUILD/DIABETES/CARDIAC/...
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    effective_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date     DATE,
    created_by      TEXT,
    updated_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    version         INT NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_medical_standard_scope
    ON uw_medical_standard (standard_code, COALESCE(tenant_id::text, ''), COALESCE(product_code, ''));
CREATE INDEX IF NOT EXISTS ix_medical_standard_active
    ON uw_medical_standard (is_active, effective_date, expiry_date);

CREATE TABLE IF NOT EXISTS uw_medical_standard_rule (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    standard_id     UUID NOT NULL REFERENCES uw_medical_standard(id) ON DELETE CASCADE,
    seq             INT NOT NULL DEFAULT 10,
    rule_type       TEXT NOT NULL DEFAULT 'FLAT',     -- FLAT | RANGE
    condition       JSONB,                            -- typed condition tree (prefilter)
    param           TEXT,                             -- RANGE: numeric context key
    name            TEXT,
    description     TEXT,                             -- detail line (may be a {field} template)
    debit_points    INT NOT NULL DEFAULT 0,
    credit_points   INT NOT NULL DEFAULT 0,
    rating_class    TEXT,
    requires_aps    BOOLEAN NOT NULL DEFAULT FALSE,
    aps_reason      TEXT
);

CREATE TABLE IF NOT EXISTS uw_medical_standard_range (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id             UUID NOT NULL REFERENCES uw_medical_standard_rule(id) ON DELETE CASCADE,
    seq                 INT NOT NULL DEFAULT 10,
    min_value           NUMERIC,       -- inclusive unless min_exclusive
    max_value           NUMERIC,       -- inclusive unless max_exclusive; NULL = open
    min_exclusive       BOOLEAN NOT NULL DEFAULT FALSE,
    max_exclusive       BOOLEAN NOT NULL DEFAULT FALSE,
    name                TEXT,
    description         TEXT,          -- detail line ({field} template)
    debit_points        INT NOT NULL DEFAULT 0,
    credit_points       INT NOT NULL DEFAULT 0,
    rating_class        TEXT,
    requires_aps        BOOLEAN NOT NULL DEFAULT FALSE,
    aps_reason          TEXT,
    medical_requirements TEXT[]
);

-- ── System seed (mirrors the previous hardcoded R001–R080 catalogue) ──────

INSERT INTO uw_medical_standard
    (id, tenant_id, product_code, standard_code, family, name, category)
VALUES
    ('00000000-0000-4000-8000-000000000001', NULL, NULL, 'R001', 'Age',            'Age loading',            'AGE'),
    ('00000000-0000-4000-8000-000000000002', NULL, NULL, 'R005', 'Tobacco',        'Tobacco use',            'TOBACCO'),
    ('00000000-0000-4000-8000-000000000003', NULL, NULL, 'R010', 'Build',          'Body mass index',        'BUILD'),
    ('00000000-0000-4000-8000-000000000004', NULL, NULL, 'R015', 'Diabetes',       'Diabetes / A1c',         'DIABETES'),
    ('00000000-0000-4000-8000-000000000005', NULL, NULL, 'R020', 'Cardiac',        'Cardiac history',        'CARDIAC'),
    ('00000000-0000-4000-8000-000000000006', NULL, NULL, 'R030', 'Medical',        'Medical history',        'MEDICAL'),
    ('00000000-0000-4000-8000-000000000007', NULL, NULL, 'R040', 'Alcohol',        'Alcohol use',            'LIFESTYLE'),
    ('00000000-0000-4000-8000-000000000008', NULL, NULL, 'R045', 'Hazardous',      'Hazardous activities',   'LIFESTYLE'),
    ('00000000-0000-4000-8000-000000000009', NULL, NULL, 'R050', 'Family History', 'Family history',         'FAMILY_HISTORY'),
    ('00000000-0000-4000-8000-00000000000a', NULL, NULL, 'R055', 'Occupation',     'Occupation class',       'OCCUPATION'),
    ('00000000-0000-4000-8000-00000000000b', NULL, NULL, 'R060', 'Driving',        'Driving record',         'DRIVING'),
    ('00000000-0000-4000-8000-00000000000c', NULL, NULL, 'R070', 'Financial',      'Coverage-to-income',     'FINANCIAL'),
    ('00000000-0000-4000-8000-00000000000d', NULL, NULL, 'R080', 'Labs',           'Lab values',             'LABS');

-- ── Rules + ranges ─────────────────────────────────────────────────────────

-- R001 Age loading (RANGE on age)
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, param, name, description)
VALUES
    ('00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000001', 10, 'RANGE', 'age', 'Age loading', 'Age {age}');
INSERT INTO uw_medical_standard_range
    (id, rule_id, seq, min_value, max_value, name, description, debit_points)
VALUES
    ('00000000-0000-4000-8000-000000000201', '00000000-0000-4000-8000-000000000101', 10, 61, NULL, 'Age loading 61+',      'Age {age}', 40),
    ('00000000-0000-4000-8000-000000000202', '00000000-0000-4000-8000-000000000101', 20, 56, 60,  'Age loading 56–60',     'Age {age}', 25),
    ('00000000-0000-4000-8000-000000000203', '00000000-0000-4000-8000-000000000101', 30, 46, 55,  'Age loading 46–55',     'Age {age}', 15);

-- R005 Tobacco use (FLAT rules)
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, condition, name, debit_points)
VALUES
    ('00000000-0000-4000-8000-000000000102', '00000000-0000-4000-8000-000000000002', 10, 'FLAT',
     '{"clauses":[{"field":"tobacco_status","op":"IN","value":["SMOKER"]}],"logic":"AND"}',
     'Current smoker', 75),
    ('00000000-0000-4000-8000-000000000103', '00000000-0000-4000-8000-000000000002', 20, 'FLAT',
     '{"clauses":[{"field":"tobacco_status","op":"IN","value":["CIGAR","PIPE"]}],"logic":"AND"}',
     'Cigar/pipe user', 50),
    ('00000000-0000-4000-8000-000000000104', '00000000-0000-4000-8000-000000000002', 30, 'FLAT',
     '{"clauses":[{"field":"tobacco_status","op":"IN","value":["CHEW","VAPE"]}],"logic":"AND"}',
     'Smokeless/vape tobacco', 50),
    ('00000000-0000-4000-8000-000000000105', '00000000-0000-4000-8000-000000000002', 40, 'FLAT',
     '{"clauses":[{"field":"tobacco_status","op":"EQ","value":"NON_SMOKER"},{"field":"tobacco_quit_years","op":"LT","value":1}],"logic":"AND"}',
     'Recent tobacco cessation <1yr', 50),
    ('00000000-0000-4000-8000-000000000106', '00000000-0000-4000-8000-000000000002', 50, 'FLAT',
     '{"clauses":[{"field":"tobacco_status","op":"EQ","value":"NON_SMOKER"},{"field":"tobacco_quit_years","op":"GTE","value":1},{"field":"tobacco_quit_years","op":"LT","value":2}],"logic":"AND"}',
     'Tobacco cessation 1–2yr', 25);

-- R010 BMI (RANGE on bmi; severe obesity + underweight require APS)
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, param, name, description)
VALUES
    ('00000000-0000-4000-8000-000000000107', '00000000-0000-4000-8000-000000000003', 10, 'RANGE', 'bmi', 'Body mass index', 'BMI {bmi:.1f}');
INSERT INTO uw_medical_standard_range
    (id, rule_id, seq, min_value, max_value, name, description, debit_points, requires_aps, aps_reason)
VALUES
    ('00000000-0000-4000-8000-000000000204', '00000000-0000-4000-8000-000000000107', 10, 40,   NULL,  'Severe obesity BMI ≥40',    'BMI {bmi:.1f}', 100, TRUE,  'Severe obesity — APS required'),
    ('00000000-0000-4000-8000-000000000205', '00000000-0000-4000-8000-000000000107', 20, 35,   39.9, 'Obesity BMI 35–39.9',       'BMI {bmi:.1f}', 75,  FALSE, NULL),
    ('00000000-0000-4000-8000-000000000206', '00000000-0000-4000-8000-000000000107', 30, 30,   34.9, 'Overweight BMI 30–34.9',    'BMI {bmi:.1f}', 25,  FALSE, NULL),
    ('00000000-0000-4000-8000-000000000207', '00000000-0000-4000-8000-000000000107', 40, NULL, 16.99,'Underweight BMI <17',       'BMI {bmi:.1f}', 50,  TRUE,  'Underweight — APS required');

-- R015 Diabetes — T1 / T2 banded on A1c, T2 duration adder, pre-diabetic
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, condition, param, name, debit_points, requires_aps, aps_reason)
VALUES
    ('00000000-0000-4000-8000-000000000108', '00000000-0000-4000-8000-000000000004', 10, 'RANGE',
     '{"clauses":[{"field":"diabetes_type","op":"EQ","value":"TYPE1"}],"logic":"AND"}',
     'a1c', 'Type 1 diabetes A1c={a1c}%', 0, TRUE, 'Type 1 diabetes — APS and latest labs required'),
    ('00000000-0000-4000-8000-000000000109', '00000000-0000-4000-8000-000000000004', 20, 'RANGE',
     '{"clauses":[{"field":"diabetes_type","op":"EQ","value":"TYPE2"}],"logic":"AND"}',
     'a1c', 'Type 2 diabetes A1c={a1c}%', 0, FALSE, NULL),
    ('00000000-0000-4000-8000-00000000010a', '00000000-0000-4000-8000-000000000004', 30, 'FLAT',
     '{"clauses":[{"field":"diabetes_type","op":"EQ","value":"TYPE2"},{"field":"diabetes_duration_years","op":"GT","value":10}],"logic":"AND"}',
     NULL, 'Type 2 diabetes duration >10yr', 25, FALSE, NULL),
    ('00000000-0000-4000-8000-00000000010b', '00000000-0000-4000-8000-000000000004', 40, 'FLAT',
     '{"clauses":[{"field":"diabetes_type","op":"EQ","value":"PRE_DIABETIC"}],"logic":"AND"}',
     NULL, 'Pre-diabetic', 15, FALSE, NULL);
INSERT INTO uw_medical_standard_range
    (id, rule_id, seq, min_value, max_value, min_exclusive, name, debit_points)
VALUES
    ('00000000-0000-4000-8000-000000000208', '00000000-0000-4000-8000-000000000108', 10, NULL, 7.5, FALSE, 'T1 A1c <=7.5', 75),
    ('00000000-0000-4000-8000-000000000209', '00000000-0000-4000-8000-000000000108', 20, 7.5,  9,   FALSE, 'T1 A1c 7.5–9',  100),
    ('00000000-0000-4000-8000-00000000020a', '00000000-0000-4000-8000-000000000108', 30, 9,    NULL, TRUE,  'T1 A1c >9',     150),
    ('00000000-0000-4000-8000-00000000020b', '00000000-0000-4000-8000-000000000109', 10, NULL, 7.5, FALSE, 'T2 A1c <=7.5', 25),
    ('00000000-0000-4000-8000-00000000020c', '00000000-0000-4000-8000-000000000109', 20, 7.5,  9,   FALSE, 'T2 A1c 7.5–9',  50),
    ('00000000-0000-4000-8000-00000000020d', '00000000-0000-4000-8000-000000000109', 30, 9,    NULL, TRUE,  'T2 A1c >9',     75);

-- R020 Cardiac — MI and revascularisation banded on years-since, angina & arrhythmia flat
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, condition, param, name, debit_points, requires_aps, aps_reason)
VALUES
    ('00000000-0000-4000-8000-00000000010c', '00000000-0000-4000-8000-000000000005', 10, 'RANGE',
     '{"clauses":[{"field":"heart_condition","op":"EQ","value":"MI"}],"logic":"AND"}',
     'heart_event_years_ago', 'Myocardial infarction {heart_event_years_ago}yr ago', 0, TRUE, 'Post-MI — full cardiac APS required'),
    ('00000000-0000-4000-8000-00000000010d', '00000000-0000-4000-8000-000000000005', 20, 'RANGE',
     '{"clauses":[{"field":"heart_condition","op":"IN","value":["CABG","STENT"]}],"logic":"AND"}',
     'heart_event_years_ago', '{heart_condition} {heart_event_years_ago}yr ago', 0, TRUE, 'Post cardiac procedure — APS required'),
    ('00000000-0000-4000-8000-00000000010e', '00000000-0000-4000-8000-000000000005', 30, 'FLAT',
     '{"clauses":[{"field":"heart_condition","op":"EQ","value":"ANGINA"}],"logic":"AND"}',
     NULL, 'Angina', 75, FALSE, NULL),
    ('00000000-0000-4000-8000-00000000010f', '00000000-0000-4000-8000-000000000005', 40, 'FLAT',
     '{"clauses":[{"field":"heart_condition","op":"EQ","value":"ARRHYTHMIA"}],"logic":"AND"}',
     NULL, 'Arrhythmia', 50, FALSE, NULL);
INSERT INTO uw_medical_standard_range
    (id, rule_id, seq, min_value, max_value, name, debit_points)
VALUES
    ('00000000-0000-4000-8000-00000000020e', '00000000-0000-4000-8000-00000000010c', 10, NULL, 2, 'Post-MI <2yr', 150),
    ('00000000-0000-4000-8000-00000000020f', '00000000-0000-4000-8000-00000000010c', 20, 2,    5, 'Post-MI 2–5yr', 100),
    ('00000000-0000-4000-8000-000000000210', '00000000-0000-4000-8000-00000000010c', 30, 5,   NULL, 'Post-MI >5yr', 50),
    ('00000000-0000-4000-8000-000000000211', '00000000-0000-4000-8000-00000000010d', 10, NULL, 2, 'Post-procedure <2yr', 125),
    ('00000000-0000-4000-8000-000000000212', '00000000-0000-4000-8000-00000000010d', 20, 2,    5, 'Post-procedure 2–5yr', 75),
    ('00000000-0000-4000-8000-000000000213', '00000000-0000-4000-8000-00000000010d', 30, 5,   NULL, 'Post-procedure >5yr', 40);

-- R030 Medical history — depression (hospitalised vs not), epilepsy, COPD
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, condition, name, debit_points, requires_aps, aps_reason)
VALUES
    ('00000000-0000-4000-8000-000000000110', '00000000-0000-4000-8000-000000000006', 10, 'FLAT',
     '{"clauses":[{"field":"depression_history","op":"EQ","value":true},{"field":"depression_hospitalized","op":"EQ","value":true}],"logic":"AND"}',
     'Depression history (hospitalised)', 75, FALSE, NULL),
    ('00000000-0000-4000-8000-000000000111', '00000000-0000-4000-8000-000000000006', 20, 'FLAT',
     '{"clauses":[{"field":"depression_history","op":"EQ","value":true},{"field":"depression_hospitalized","op":"NOT_IN","value":[true]}],"logic":"AND"}',
     'Depression history', 30, FALSE, NULL),
    ('00000000-0000-4000-8000-000000000112', '00000000-0000-4000-8000-000000000006', 30, 'FLAT',
     '{"clauses":[{"field":"epilepsy","op":"EQ","value":true}],"logic":"AND"}',
     'Epilepsy / seizure disorder', 50, TRUE, 'Epilepsy — neurology APS required'),
    ('00000000-0000-4000-8000-000000000113', '00000000-0000-4000-8000-000000000006', 40, 'FLAT',
     '{"clauses":[{"field":"copd","op":"EQ","value":true}],"logic":"AND"}',
     'COPD', 50, TRUE, 'COPD — pulmonary APS required');

-- R040 Alcohol (RANGE on weekly units)
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, param, name)
VALUES
    ('00000000-0000-4000-8000-000000000114', '00000000-0000-4000-8000-000000000007', 10, 'RANGE', 'alcohol_drinks_week', 'Alcohol use');
INSERT INTO uw_medical_standard_range
    (id, rule_id, seq, min_value, max_value, name, description, debit_points)
VALUES
    ('00000000-0000-4000-8000-000000000214', '00000000-0000-4000-8000-000000000114', 10, 28, NULL, 'Heavy alcohol use ≥28 units/week', '{alcohol_drinks_week} units/wk', 75),
    ('00000000-0000-4000-8000-000000000215', '00000000-0000-4000-8000-000000000114', 20, 21, 27,  'Moderate-heavy alcohol use 21–27 units/week', NULL, 40);

-- R045 Hazardous activities — high-hazard set vs other
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, condition, name, description, debit_points)
VALUES
    ('00000000-0000-4000-8000-000000000115', '00000000-0000-4000-8000-000000000008', 10, 'FLAT',
     '{"clauses":[{"field":"hazardous_activity","op":"EQ","value":true},{"field":"hazard_types","op":"CONTAINS_ANY","value":["BASE_JUMPING","MOTOR_RACING","PRIVATE_PILOT"]}],"logic":"AND"}',
     'Hazardous activity flat extra (high)', 'Activities: {hazard_types}', 50),
    ('00000000-0000-4000-8000-000000000116', '00000000-0000-4000-8000-000000000008', 20, 'FLAT',
     '{"clauses":[{"field":"hazardous_activity","op":"EQ","value":true},{"field":"hazard_types","op":"NOT_CONTAINS_ANY","value":["BASE_JUMPING","MOTOR_RACING","PRIVATE_PILOT"]}],"logic":"AND"}',
     'Hazardous activity flat extra', 'Activities: {hazard_types}', 30);

-- R050 Family history
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, condition, name, debit_points)
VALUES
    ('00000000-0000-4000-8000-000000000117', '00000000-0000-4000-8000-000000000009', 10, 'FLAT',
     '{"clauses":[{"field":"family_history.cardiovascular_before_60","op":"EQ","value":true}],"logic":"AND"}',
     'Family history CVD before age 60', 15),
    ('00000000-0000-4000-8000-000000000118', '00000000-0000-4000-8000-000000000009', 20, 'FLAT',
     '{"clauses":[{"field":"family_history.stroke_before_65","op":"EQ","value":true}],"logic":"AND"}',
     'Family history stroke before age 65', 10),
    ('00000000-0000-4000-8000-000000000119', '00000000-0000-4000-8000-000000000009', 30, 'FLAT',
     '{"clauses":[{"field":"family_history.cancer_history","op":"EQ","value":true}],"logic":"AND"}',
     'Family history cancer', 10);

-- R055 Occupation class
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, condition, name, debit_points)
VALUES
    ('00000000-0000-4000-8000-00000000011a', '00000000-0000-4000-8000-00000000000a', 10, 'FLAT',
     '{"clauses":[{"field":"occupation_class","op":"EQ","value":"2"}],"logic":"AND"}',
     'Occupation class 2', 10),
    ('00000000-0000-4000-8000-00000000011b', '00000000-0000-4000-8000-00000000000a', 20, 'FLAT',
     '{"clauses":[{"field":"occupation_class","op":"EQ","value":"3"}],"logic":"AND"}',
     'Occupation class 3', 25),
    ('00000000-0000-4000-8000-00000000011c', '00000000-0000-4000-8000-00000000000a', 30, 'FLAT',
     '{"clauses":[{"field":"occupation_class","op":"EQ","value":"4"}],"logic":"AND"}',
     'Occupation class 4', 50);

-- R060 Driving record
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, condition, name, debit_points)
VALUES
    ('00000000-0000-4000-8000-00000000011d', '00000000-0000-4000-8000-00000000000b', 10, 'FLAT',
     '{"clauses":[{"field":"license_suspended","op":"EQ","value":true}],"logic":"AND"}',
     'Licence suspended', 100),
    ('00000000-0000-4000-8000-00000000011e', '00000000-0000-4000-8000-00000000000b', 20, 'FLAT',
     '{"clauses":[{"field":"dui_dwi_count_5yr","op":"EQ","value":1}],"logic":"AND"}',
     '1 DUI/DWI in last 5 years', 50),
    ('00000000-0000-4000-8000-00000000011f', '00000000-0000-4000-8000-00000000000b', 30, 'FLAT',
     '{"clauses":[{"field":"major_violations_3yr","op":"GTE","value":3}],"logic":"AND"}',
     '{major_violations_3yr} major driving violations in last 3 years', 50),
    ('00000000-0000-4000-8000-000000000120', '00000000-0000-4000-8000-00000000000b', 40, 'FLAT',
     '{"clauses":[{"field":"major_violations_3yr","op":"EQ","value":2}],"logic":"AND"}',
     '2 major driving violations in last 3 years', 25);

-- R070 Financial — coverage exceeds income multiple (strictly above 20x)
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, param, name, description)
VALUES
    ('00000000-0000-4000-8000-000000000121', '00000000-0000-4000-8000-00000000000c', 10, 'RANGE', 'coverage_multiple',
     'Financial underwriting — coverage exceeds 20× income',
     'Total coverage {total_coverage:,.0f} vs max {max_coverage:,.0f}');
INSERT INTO uw_medical_standard_range
    (id, rule_id, seq, min_value, max_value, min_exclusive, name, debit_points, requires_aps, aps_reason)
VALUES
    ('00000000-0000-4000-8000-000000000216', '00000000-0000-4000-8000-000000000121', 10, 20, NULL, TRUE,
     'Financial underwriting — coverage exceeds 20× income',
     30, TRUE, 'Excess coverage — financial justification required');

-- R080 Labs — total cholesterol, chol/HDL ratio, LDL
INSERT INTO uw_medical_standard_rule
    (id, standard_id, seq, rule_type, param, name)
VALUES
    ('00000000-0000-4000-8000-000000000122', '00000000-0000-4000-8000-00000000000d', 10, 'RANGE', 'total_cholesterol', 'Total cholesterol'),
    ('00000000-0000-4000-8000-000000000123', '00000000-0000-4000-8000-00000000000d', 20, 'RANGE', 'chol_hdl_ratio',   'Cholesterol ratio'),
    ('00000000-0000-4000-8000-000000000124', '00000000-0000-4000-8000-00000000000d', 30, 'RANGE', 'ldl',              'LDL cholesterol');
INSERT INTO uw_medical_standard_range
    (id, rule_id, seq, min_value, max_value, min_exclusive, name, description, debit_points)
VALUES
    ('00000000-0000-4000-8000-000000000217', '00000000-0000-4000-8000-000000000122', 10, 260, NULL, FALSE, 'High total cholesterol {total_cholesterol} mg/dL', NULL, 25),
    ('00000000-0000-4000-8000-000000000218', '00000000-0000-4000-8000-000000000123', 10, 6,   NULL, TRUE,  'High cholesterol ratio {chol_hdl_ratio:.1f}', NULL, 25),
    ('00000000-0000-4000-8000-000000000219', '00000000-0000-4000-8000-000000000124', 10, 190, NULL, FALSE, 'Very high LDL {ldl} mg/dL', NULL, 25);
