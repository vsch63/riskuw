// ─── Auth ────────────────────────────────────────────────────────
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  mfa_required?: boolean;
  mfa_session_token?: string;
  username?: string;
  role?: string;
}

export interface MFAVerifyRequest {
  totp_code: string;
  session_token?: string;
  username?: string;
}

export interface AuthUser {
  username: string;
  role: string;
  token: string;
}

// ─── Products ────────────────────────────────────────────────────
export interface Product {
  product_code: string;
  product_name?: string;
  name?: string;
  product_type?: string;
  category?: string;
  min_age?: number;
  max_age?: number;
  min_face?: number;
  max_face?: number;
  min_face_amount?: number;
  max_face_amount?: number;
  terms?: number[];
  uw_method?: string;
  exam_note?: string;
  notes?: string;
  is_gi?: boolean;
}

// ─── Underwriting Evaluate ───────────────────────────────────────
export interface BuildInfo {
  height_inches: number;
  weight_lbs: number;
}

export interface BloodPressure {
  systolic: number;
  diastolic: number;
  on_medication: boolean;
  medication_count: number;
}

export interface FinancialInfo {
  annual_income: number;
  existing_life_coverage: number;
}

export interface FamilyHistory {
  cardiovascular_before_60: boolean;
  stroke_before_65: boolean;
  cancer_history: boolean;
  diabetes_history: boolean;
}

export interface DrivingRecord {
  dui_dwi_count_5yr: number;
  major_violations_3yr: number;
  minor_violations_3yr: number;
  at_fault_accidents_3yr: number;
  license_suspended: boolean;
}

export interface LabValues {
  total_cholesterol?: number;
  hdl?: number;
  ldl?: number;
  egfr?: number;
}

export interface EvaluatePayload {
  applicant_ref: string;
  age: number;
  gender: 'MALE' | 'FEMALE';
  state: string;
  product_type: string;
  product_code: string;
  face_amount: number;
  coverage_term_yrs: number;
  policy_effective_date?: string;
  policy_expire_date?: string;
  tobacco_status: string;
  tobacco_quit_years?: number | null;
  heart_condition?: string;
  heart_event_years_ago?: number | null;
  diabetes_type?: string;
  diabetes_dx_age?: number | null;
  a1c?: number | null;
  hiv_positive?: boolean;
  cirrhosis?: boolean;
  stroke_history?: boolean;
  kidney_disease?: boolean;
  depression_history?: boolean;
  depression_hospitalized?: boolean;
  epilepsy?: boolean;
  copd?: boolean;
  occupation_class?: string;
  occupation_title?: string;
  alcohol_drinks_week?: number;
  hazardous_activity?: boolean;
  hazard_types?: string[];
  build?: BuildInfo;
  blood_pressure?: BloodPressure;
  lab_values?: LabValues;
  financial?: FinancialInfo;
  family_history?: FamilyHistory;
  driving_record?: DrivingRecord;
}

// ─── Decision Result ─────────────────────────────────────────────
export type OutcomeType = 'APPROVED' | 'DECLINED' | 'POSTPONED' | 'REFERRED' | string;

export interface RuleFired {
  rule_id?: string;
  rule_code?: string;
  rule_name?: string;
  name?: string;
  debit_points?: number;
  severity?: string;
  description?: string;
  category?: string;
}

export interface UWDecision {
  outcome: OutcomeType;
  risk_class?: string;
  net_debit_points?: number;
  total_debits?: number;
  approved_premium?: number;
  table_rating?: number;
  flat_extra_per_thou?: number;
  adverse_action_text?: string;
  rules_fired?: RuleFired[];
  pathway?: string;
  is_stp?: boolean;
  application_id?: string;
  case_id?: string;
  decision_id?: string;
  rules_version?: string;
  evaluated_at?: string;
  applicant_name?: string;
  policy_effective_date?: string;
  policy_expire_date?: string;
  error_codes?: string[];
  error?: string;
  detail?: string;
}

// ─── Queue / Cases ───────────────────────────────────────────────
export interface QueueCase {
  id: string;
  applicant_ref?: string;
  applicant_name?: string;
  product_code?: string;
  face_amount?: number;
  outcome?: string;
  risk_class?: string;
  net_debit_points?: number;
  status?: string;
  created_at?: string;
  assigned_to?: string;
}
