-- ============================================================
-- Run this SQL to add rule metadata to product_rules
-- ============================================================

-- Step 1: Add rule_name and category columns
ALTER TABLE product_rules
    ADD COLUMN IF NOT EXISTS rule_name     VARCHAR(120),
    ADD COLUMN IF NOT EXISTS category      VARCHAR(40),
    ADD COLUMN IF NOT EXISTS default_debit INTEGER DEFAULT 0;

-- Step 2: Update existing rows with names from seed
UPDATE product_rules SET rule_name='Age Loading 46–55',           category='AGE',       default_debit=15  WHERE rule_id='R001';
UPDATE product_rules SET rule_name='Age Loading 56+',             category='AGE',       default_debit=30  WHERE rule_id='R002';
UPDATE product_rules SET rule_name='Tobacco / Smoker Loading',    category='LIFESTYLE', default_debit=50  WHERE rule_id='R005';
UPDATE product_rules SET rule_name='Heavy Alcohol Use',           category='LIFESTYLE', default_debit=50  WHERE rule_id='R040';
UPDATE product_rules SET rule_name='Hazardous Activity',          category='LIFESTYLE', default_debit=30  WHERE rule_id='R045';
UPDATE product_rules SET rule_name='Elevated BMI (30–35)',        category='BUILD',     default_debit=25  WHERE rule_id='R010';
UPDATE product_rules SET rule_name='Elevated BMI (>35)',          category='BUILD',     default_debit=75  WHERE rule_id='R011';
UPDATE product_rules SET rule_name='Diabetes Type 2',             category='MEDICAL',   default_debit=50  WHERE rule_id='R015';
UPDATE product_rules SET rule_name='Diabetes Type 1',             category='MEDICAL',   default_debit=100 WHERE rule_id='R016';
UPDATE product_rules SET rule_name='Cardiac Event < 2 years',     category='MEDICAL',   default_debit=125 WHERE rule_id='R020';
UPDATE product_rules SET rule_name='Cardiac Event 2–5 years',     category='MEDICAL',   default_debit=75  WHERE rule_id='R021';
UPDATE product_rules SET rule_name='Cardiac Event > 5 years',     category='MEDICAL',   default_debit=40  WHERE rule_id='R022';
UPDATE product_rules SET rule_name='Stage 2 Hypertension',        category='MEDICAL',   default_debit=25  WHERE rule_id='R025';
UPDATE product_rules SET rule_name='Uncontrolled Hypertension',   category='MEDICAL',   default_debit=50  WHERE rule_id='R026';
UPDATE product_rules SET rule_name='Stroke History',              category='MEDICAL',   default_debit=75  WHERE rule_id='R030';
UPDATE product_rules SET rule_name='Kidney Disease',              category='MEDICAL',   default_debit=75  WHERE rule_id='R031';
UPDATE product_rules SET rule_name='Depression — Hospitalized',   category='MEDICAL',   default_debit=75  WHERE rule_id='R032';
UPDATE product_rules SET rule_name='Depression — Outpatient',     category='MEDICAL',   default_debit=25  WHERE rule_id='R033';
UPDATE product_rules SET rule_name='Epilepsy / Seizure Disorder', category='MEDICAL',   default_debit=50  WHERE rule_id='R034';
UPDATE product_rules SET rule_name='COPD / Emphysema',            category='MEDICAL',   default_debit=75  WHERE rule_id='R035';
UPDATE product_rules SET rule_name='Family History — CVD < 60',   category='FAMILY',    default_debit=15  WHERE rule_id='R050';
UPDATE product_rules SET rule_name='Family History — Stroke < 65',category='FAMILY',    default_debit=15  WHERE rule_id='R051';
UPDATE product_rules SET rule_name='Family History — Cancer',     category='FAMILY',    default_debit=10  WHERE rule_id='R052';
UPDATE product_rules SET rule_name='Family History — Diabetes',   category='FAMILY',    default_debit=10  WHERE rule_id='R053';
UPDATE product_rules SET rule_name='HIV Positive — Hard Stop',    category='HARD_STOP', default_debit=999 WHERE rule_id='R100';
UPDATE product_rules SET rule_name='Liver Cirrhosis — Hard Stop', category='HARD_STOP', default_debit=999 WHERE rule_id='R101';
UPDATE product_rules SET rule_name='2+ DUI/DWI in 5 Years',      category='HARD_STOP', default_debit=999 WHERE rule_id='R102';
UPDATE product_rules SET rule_name='Declined Occupation Class',   category='HARD_STOP', default_debit=999 WHERE rule_id='R103';
UPDATE product_rules SET rule_name='Age Outside Product Range',   category='HARD_STOP', default_debit=999 WHERE rule_id='R104';
UPDATE product_rules SET rule_name='Major Traffic Violation',     category='DRIVING',   default_debit=25  WHERE rule_id='R060';
UPDATE product_rules SET rule_name='At-Fault Accident',           category='DRIVING',   default_debit=15  WHERE rule_id='R061';
UPDATE product_rules SET rule_name='License Suspended',           category='DRIVING',   default_debit=50  WHERE rule_id='R062';

-- Fill any remaining nulls with rule_id as fallback
UPDATE product_rules SET rule_name=rule_id WHERE rule_name IS NULL;

-- Verify
SELECT rule_id, rule_name, category, default_debit, COUNT(*) as product_count
FROM product_rules
GROUP BY rule_id, rule_name, category, default_debit
ORDER BY category, rule_id;

