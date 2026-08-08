/*
frontend/src/components/ColHint.tsx
────────────────────────────────────
Shared tooltip helpers for table columns.

* Titled(label, dataIndex)  — wrap a column header; tooltip text comes from
  COLUMN_HINTS keyed by dataIndex, so the explanation lives in one place.
* ColTip                     — the raw header wrapper (dashed underline + help
  cursor, the standard "hover for a hint" affordance).
* CellHint(dataIndex)       — a column `render` fn for cryptic enum cells;
  tooltip comes from VALUE_HINTS[key](value), renders the value unchanged.
* CellTip                    — the raw cell wrapper.

Every dataIndex used across the app's tables is in COLUMN_HINTS (see the
coverage check in scripts), so no data-bearing column is left untooltipped.
*/
import React from 'react'
import { Tooltip } from 'antd'

const tooltipProps = {
  placement: 'top' as const,
  mouseEnterDelay: 0.3,
  styles: { root: { maxWidth: 320 } },
}

const hintStyle: React.CSSProperties = {
  borderBottom: '1px dashed #8a94a6',
  cursor: 'help',
  whiteSpace: 'nowrap',
}

/** Raw header wrapper: renders the label; dashed underline signals the hint. */
export function ColTip({ label, tip }: { label: React.ReactNode; tip?: string }) {
  if (!tip) return <>{label}</>
  return (
    <Tooltip title={tip} {...tooltipProps}>
      <span style={hintStyle}>{label}</span>
    </Tooltip>
  )
}

/** Wrap a column header with the hint for its dataIndex (from COLUMN_HINTS). */
export function Titled(label: React.ReactNode, key?: string): React.ReactNode {
  return <ColTip label={label} tip={key ? COLUMN_HINTS[key] : undefined} />
}

/** Raw cell wrapper: renders the value (or fallback) and adds a tooltip when a hint exists. */
export function CellTip({
  value, hint, fallback = '—',
}: {
  value: React.ReactNode
  hint?: string | null
  fallback?: React.ReactNode
}) {
  if (value === null || value === undefined || value === '') return <span>{fallback}</span>
  if (!hint) return <span>{value}</span>
  return (
    <Tooltip title={hint} {...tooltipProps}>
      <span style={hintStyle}>{value}</span>
    </Tooltip>
  )
}

/** Column `render` fn for cryptic enum cells — tooltip from VALUE_HINTS[key]. */
export function CellHint(key: string) {
  const fn = VALUE_HINTS[key]
  return (v: React.ReactNode) => <CellTip value={v} hint={fn ? fn(v as any) : null} />
}

// ═════════════════════════════════════════════════════════════════════════════
// COLUMN_HINTS — header tooltips keyed by dataIndex. Covers every dataIndex
// used in the app's tables (kept in sync with frontend/src/pages/*.tsx).
// ═════════════════════════════════════════════════════════════════════════════
export const COLUMN_HINTS: Record<string, string> = {
  // ── Generic ────────────────────────────────────────────────────────────────
  name: 'Name of the entity.',
  code: 'Code that identifies this entity.',
  category: 'Category or classification.',
  type: 'Type or kind of the record.',
  description: 'Human-readable description.',
  status: 'Current state of the record.',
  priority: 'Priority of the record.',
  version: 'Version of this config/rule.',
  is_active: 'Whether the record is currently active.',
  is_enabled: 'Whether this rule/feature is switched on.',
  is_required: 'Whether the field must be provided.',
  is_current: 'Whether this is the current (latest) version.',
  is_decline: 'Whether this outcome/flag is a decline.',
  created_at: 'When the record was created.',
  created_by: 'Who created the record.',
  updated_at: 'When the record was last updated.',
  updated_by: 'Who last updated the record.',
  submitted_at: 'When the record was submitted.',
  effective_date: 'Date this takes effect.',
  effective_from: 'Date this becomes active from.',
  expiry_date: 'Date this ceases to be valid.',
  expires_at: 'When this expires.',
  hard_stop: 'Hard-stop rules instant-decline the case regardless of other rules.',

  // ── Underwriting / scoring ─────────────────────────────────────────────────
  net_debit_points: 'Net Debit Points — total underwriting score after all rule loadings. Higher = higher risk.',
  debit_points: 'Debit points — risk loading this rule adds. Higher = higher risk.',
  debits: 'Debit points — risk loading applied to the case.',
  credit_points: 'Credit points — favourable factors that reduce the net risk score.',
  debit_points_override: 'Manual override of the rule’s default debit points.',
  flat_extra: 'Flat extra loading, per mille of sum assured per year, for elevated risk.',
  flat_extra_override: 'Manual override of the rule’s default flat extra loading.',
  flat_extra_rate: 'Flat extra rate applied per mille of sum assured.',
  table_rating: 'Table rating — rate-up class (0 = standard; higher = more expensive).',
  risk_class: 'Underwriting risk class — how the case was rated (STANDARD / SUB-STANDARD / …).',
  risk_tier: 'Automated risk tier assigned by the engine.',
  risk_score: 'Numeric risk score from the model/engine.',
  risk_group: 'Group of risks that share the same underwriting treatment.',
  risk_group_code: 'Code of the risk group.',
  credit_score: 'Applicant’s credit score (financial underwriting input).',
  auto_refer_threshold: 'Debit-point score at or above which a case auto-refers to an underwriter.',
  decline_threshold: 'Debit-point score at or above which a case is auto-declined.',
  senior_uw_threshold: 'Score threshold that escalates a case to a senior underwriter.',
  ri_approval_threshold: 'Score threshold that routes a case to reinsurance approval.',
  outcome: 'Underwriting decision outcome (APPROVED_STP / APPROVED_RATED / REFERRED / DECLINED).',
  rules_outcome: 'Combined outcome across all engine rules.',
  human_decision: 'The underwriter’s final decision on the case.',
  recommendation: 'AI/engine recommendation for the case.',
  confidence_score: 'Model confidence in the AI recommendation (0–100%).',
  matches_ai: 'Whether the final decision matched the AI recommendation.',
  engine: 'Which engine produced the result (AI model vs rules engine).',

  // ── Applicant / policy ─────────────────────────────────────────────────────
  applicant_name: 'Applicant’s full name.',
  applicant_ref: 'Applicant reference — unique per applicant.',
  ref: 'Applicant reference — unique per applicant.',
  case_number: 'Case reference number for the underwriting file.',
  case_ref_id: 'Case reference number for the underwriting file.',
  assigned_to: 'Underwriter the case is assigned to.',
  decision_date: 'Date the underwriting decision was made.',
  issue_date: 'Date the policy was issued.',
  face_amount: 'Sum assured — the policy face amount (₹).',
  sum_assured: 'Sum assured — the policy face amount (₹).',
  annual_premium: 'Annualized premium in ₹.',
  approved_premium: 'Premium accepted at decision time (₹).',
  premium: 'Premium amount in ₹.',
  premium_mode: 'How often premium is paid — ANNUAL / HALF_YEARLY / QUARTERLY / MONTHLY.',
  payment_mode: 'How often premium is paid — ANNUAL / HALF_YEARLY / QUARTERLY / MONTHLY.',
  premium_payer: 'Who pays the premium — policyholder or a third party.',
  premium_output_type: 'How the premium value is computed/presented.',
  modal_premium: 'Premium per payment mode (monthly/quarterly/…).',
  policy_number: 'Unique policy number assigned at issuance.',
  term_years: 'Policy term in years.',
  next_premium_due: 'Next date a premium instalment is due.',
  due_date: 'Date the premium instalment is due.',
  paid_date: 'Date the premium was paid.',
  amount_paid: 'Amount paid toward the premium.',
  receipt_number: 'Receipt number for the premium payment.',
  benefit_code: 'Code of the benefit/rider.',
  benefit_type: 'Type of benefit/rider (BASE, RIDER, …).',
  gender: 'Applicant’s gender.',
  tobacco_status: 'Tobacco/nicotine use status — NEVER / NON_SMOKER / SMOKER / CHEW / VAPE.',
  medical_tests_required: 'Number of medical tests the underwriting rules require.',
  family: 'Family history factor evaluated by the rules.',
  condition: 'Medical condition the rule checks.',
  severity: 'Severity of the flag — ERROR / WARNING / INFO.',

  // ── Reinsurance ────────────────────────────────────────────────────────────
  ceded_amount: 'Portion of the risk passed to the reinsurer (sum assured − retention).',
  retention_limit: 'Amount the insurer keeps before reinsurance kicks in.',
  gross_face_amount: 'Full sum assured before any cession.',
  cession_ref: 'Reference number of the reinsurance cession record.',
  cession_type: 'Type of cession — FACULTATIVE / QUOTA_SHARE / SURPLUS.',
  treaty_code: 'Code of the reinsurance treaty applied.',
  ri_premium: 'Premium paid to the reinsurer for the ceded portion.',
  ri_decision: 'Reinsurer’s decision on the cession (ACCEPTED / DECLINED / …).',
  ri_decision_date: 'Date the reinsurer made its decision.',
  reinsurer_name: 'Name of the reinsurer.',
  reinsurer_code: 'Code identifying the reinsurer.',

  // ── Rates / build tables / formulas ────────────────────────────────────────
  rate_per_thou: 'Premium rate per thousand of sum assured (₹ per ₹1,000).',
  rate_label: 'Human-readable label for the rate band.',
  rate_count: 'Number of rate records in the band.',
  table_code: 'Code of the rate table.',
  table_name: 'Name of the rate table.',
  key_field: 'Field the rate table keys on.',
  scheme_id: 'Scheme this product/rule belongs to.',
  default_value: 'Fallback value used when nothing matches.',
  band_label: 'Label of the build (BMI) band.',
  band_min: 'Lower bound of the band.',
  band_max: 'Upper bound of the band.',
  bmi_min: 'Body Mass Index band lower bound.',
  bmi_max: 'Body Mass Index band upper bound.',
  fcl_basis: 'Basis on which the FCL (flat commission loading) is computed.',
  flat_fcl_amount: 'Flat FCL amount applied.',
  formula_name: 'Name of the premium formula.',
  formula_type: 'Type of premium formula.',
  parameter_type: 'Type of the formula parameter.',
  operator: 'Operator applied in the formula/condition (AND, >, ≤, …).',
  seq_no: 'Sequence number within the formula.',
  factor: 'Multiplier applied by this formula step.',
  aggregation_method: 'How metric values are aggregated (sum, max, average, …).',
  output_value: 'Value produced by this output step.',
  scaleId: 'Underwriting scale identifier.',
  scaleType: 'Type of the underwriting scale.',
  scale_name: 'Name of the underwriting scale.',
  scale_type: 'Type of the underwriting scale.',
  tranches: 'Number of tranches in the underwriting scale.',
  tranche_count: 'Number of tranches in the underwriting scale.',
  step_count: 'Number of steps in the scale.',
  data_type: 'Data type of the custom field.',
  field: 'Field the custom field maps to.',
  label_key: 'Key/label used to reference this field.',
  label_name: 'Display label for this field.',

  // ── SAR / AML / KYC ────────────────────────────────────────────────────────
  sar_formula: 'SAR scoring formula applied.',
  include_in_sar: 'Whether the case is flagged for a Suspicious Activity Report.',
  uw_exposure_group: 'Underwriting exposure group used by the SAR rules.',
  exposure_group: 'Group of products/exposures sharing the same SAR treatment.',
  exposure_group_code: 'Code of the exposure group.',
  exposure_name: 'Name of the exposure group.',
  exposure_code: 'Code of the exposure.',
  pathway: 'SAR pathway / decision branch taken for this case.',
  nml_category: 'Category used by the no-medical-limit (NML) logic.',
  plan_tier: 'Plan tier — determines benefits and limits.',
  aml_status: 'Anti-Money-Laundering screening status (CLEAR / FLAGGED / PENDING).',
  kyc_verified: 'Whether KYC documents have been verified.',
  verified_at: 'When verification was completed.',

  // ── Batch jobs / schedules / pushes ────────────────────────────────────────
  cron_expression: 'Cron schedule for recurring runs (e.g. "0 2 * * *" = daily 2am).',
  schedule_name: 'Name of the recurring schedule.',
  last_run_at: 'When the schedule last ran.',
  next_run_at: 'When the schedule next runs.',
  sla_due_at: 'When the SLA deadline expires.',
  push_status: 'Push delivery status (PENDING / SENT / FAILED).',
  push_attempts: 'Number of delivery attempts made.',
  push_last_at: 'Time of the last push attempt.',
  push_last_error: 'Error from the last failed push.',
  row_number: 'Row number in the batch upload.',
  row_count: 'Number of rows/records.',
  errors: 'Error message or error count for the item.',
  message: 'Message / details.',
  ms: 'Processing time in milliseconds.',
  request_count: 'Number of requests.',
  requests: 'Number of requests.',
  processing_sequence: 'Order in which items are processed.',
  filename: 'Uploaded file name.',

  // ── Users / tenants / integrations ─────────────────────────────────────────
  username: 'Login username.',
  full_name: 'User’s display name.',
  role: 'Access role — admin, underwriter, senior_underwriter, agent, broker, viewer, api_client…',
  email: 'Email address.',
  contact_email: 'Contact email address.',
  tenant_name: 'The tenant (organization) the record belongs to.',
  max_users: 'Maximum number of users allowed.',
  last_login_at: 'Time of the user’s last sign-in.',
  last_used_at: 'When the API key/credential was last used.',
  usage_date: 'Date the API key/credential was used.',
  integration_type: 'Type of external integration.',
  provider_code: 'Code of the external provider/system.',
  endpoint: 'API endpoint the integration calls.',
  environment: 'Environment — dev, staging, prod, …',

  // ── Audit / events ─────────────────────────────────────────────────────────
  actor: 'User who performed the action.',
  actor_username: 'User who performed the action.',
  entity_type: 'Type of entity affected (application, policy, user, …).',
  event_category: 'Category of the audit event.',
  event_type: 'Type of the audit event.',
  occurred_at: 'When the event occurred.',
  source: 'Where the action originated — UI, API, system.',
  resolution: 'How the issue/event was resolved.',

  // ── Products / rules / misc ────────────────────────────────────────────────
  product: 'Product the record refers to.',
  product_code: 'Product code the record refers to.',
  product_codes: 'Product codes this rule applies to.',
  rule_id: 'Identifier of the rule.',
  rule_code: 'Code of the rule.',
  rule_name: 'Name of the rule.',
  group_name: 'Name of the group this record belongs to.',
  group_code: 'Code of the group this record belongs to.',
  country_code: 'Country code.',
  state_code: 'State (Indian) code.',
  state_name: 'State (Indian) name.',
  currency: 'Currency of the amounts shown.',
  match_type: 'How the match was made — EXACT / FUZZY / PARTIAL.',
  match_value: 'The value that was matched.',
  confidence: 'Confidence in the match.',
  requested_by: 'Who requested the action.',
  requires_aps: 'Whether an Attending Physician Statement (APS) is required.',

  // ── Upload / registry / GST (sweep additions) ─────────────────────────────
  col: 'Field being described in this upload-requirements row.',
  note: 'Explanatory note for this field or file.',
  notes: 'Free-text note recorded on the record.',
  upload_ref: 'Reference of the batch upload that imported this record.',
  total_rows: 'Total number of rows in the uploaded file.',
  inserted: 'Rows inserted by the upload.',
  updated: 'Rows updated by the upload.',
  skipped: 'Rows skipped by the upload.',
  uploaded_at: 'When the file was uploaded.',
  uploaded_by: 'Who uploaded the file.',
  clinic_name: 'Clinic/facility the physician is attached to.',
  physician_name: 'Name of the physician.',
  specialisation: 'Physician’s medical specialisation.',
  mode: 'Application mode of this factor (GST / modal factor).',
  first_year_rate: 'Rate/factor applied to the first policy year.',
  renewal_rate: 'Rate/factor applied from the second year onwards.',
}

// ═════════════════════════════════════════════════════════════════════════════
// VALUE_HINTS — cell-value tooltips for cryptic enums. Only applied to columns
// whose cells render the raw code; rich renders (Tag/Badge) are left as-is.
// Returns null → no tooltip.
// ═════════════════════════════════════════════════════════════════════════════
export const VALUE_HINTS: Record<string, (v: any) => string | null> = {
  outcome: (v) => ({
    APPROVED_STP: 'Approved automatically — risk within Straight-Through Processing limits.',
    APPROVED_RATED: 'Approved with extra premium (rated) — over STP limit but within refer limit.',
    REFERRED: 'Sent to an underwriter for manual review.',
    DECLINED: 'Declined — risk is outside the product appetite.',
    PENDING: 'Decision not yet final.',
  })[String(v)] ?? null,
  tobacco_status: (v) => ({
    NEVER: 'Never used tobacco or nicotine.',
    NON_SMOKER: 'Non-smoker (may use other nicotine forms).',
    SMOKER: 'Current smoker.',
    CIGAR: 'Cigar smoker.',
    CHEW: 'Chews tobacco / pan masala.',
    VAPE: 'Vapes / e-cigarette user.',
  })[String(v)] ?? null,
  cession_type: (v) => ({
    FACULTATIVE: 'Risk ceded on a case-by-case basis.',
    QUOTA_SHARE: 'Fixed proportion of every case is ceded.',
    SURPLUS: 'Portion above the retention limit is ceded.',
  })[String(v)] ?? null,
  risk_class: (v) => ({
    STANDARD: 'Standard rates — no loading.',
    SUB_STANDARD: 'Sub-standard risk — extra premium applies.',
    PREFERRED: 'Preferred risk — better than standard rates.',
    DECLINED: 'Declined.',
  })[String(v)] ?? null,
  aml_status: (v) => ({
    CLEAR: 'AML screening passed.',
    FLAGGED: 'Flagged for manual review.',
    PENDING: 'AML screening not yet complete.',
  })[String(v)] ?? null,
  payment_mode: (v) => ({
    ANNUAL: 'Paid once a year.',
    HALF_YEARLY: 'Paid twice a year.',
    QUARTERLY: 'Paid four times a year.',
    MONTHLY: 'Paid every month.',
  })[String(v)] ?? null,
  premium_mode: (v) => ({
    ANNUAL: 'Paid once a year.',
    HALF_YEARLY: 'Paid twice a year.',
    QUARTERLY: 'Paid four times a year.',
    MONTHLY: 'Paid every month.',
  })[String(v)] ?? null,
  match_type: (v) => ({
    EXACT: 'Exact match on the key field.',
    FUZZY: 'Fuzzy/near match.',
    PARTIAL: 'Partial match.',
  })[String(v)] ?? null,
  engine: (v) => ({
    AI: 'Decision from the AI/ML model.',
    RULES: 'Decision from the rules engine.',
    MANUAL: 'Decision entered by a human.',
  })[String(v)] ?? null,
  human_decision: (v) => ({
    APPROVE: 'Underwriter approved the case.',
    APPROVED: 'Underwriter approved the case.',
    REFER: 'Underwriter referred the case back for more info.',
    DECLINE: 'Underwriter declined the case.',
    DECLINED: 'Underwriter declined the case.',
  })[String(v)] ?? null,
  pathway: (v) => ({
    AUTO: 'Handled automatically by the engine.',
    STANDARD: 'Standard underwriting pathway.',
    ESCALATED: 'Escalated to a senior underwriter.',
    RI: 'Routed to reinsurance.',
  })[String(v)] ?? null,
  ri_decision: (v) => ({
    ACCEPTED: 'Reinsurer accepted the cession.',
    DECLINED: 'Reinsurer declined the cession.',
    PENDING: 'Awaiting the reinsurer’s decision.',
    COUNTERED: 'Reinsurer countered with modified terms.',
  })[String(v)] ?? null,
  severity: (v) => ({
    ERROR: 'Critical — action required.',
    WARNING: 'Caution — review recommended.',
    INFO: 'Informational only.',
    LOW: 'Low severity.',
    MODERATE: 'Moderate severity.',
    HIGH: 'High severity.',
  })[String(v)] ?? null,
  plan_tier: (v) => {
    const t = String(v).toUpperCase()
    if (!t) return null
    return `Plan tier "${t}" — determines the benefits and limits of the plan.`
  },
  status: (v) => ({
    // Policy lifecycle
    PENDING_ACCEPTANCE: 'Awaiting the customer’s acceptance of the issued policy.',
    PENDING_FIRST_PREMIUM: 'Waiting for the first premium payment before cover starts.',
    IN_FORCE: 'Policy is active and cover is in force.',
    LAPSED: 'Policy lapsed due to non-payment.',
    REVIVED: 'Lapsed policy reinstated.',
    SURRENDERED: 'Policy surrendered before maturity.',
    MATURED: 'Policy reached its maturity date.',
    CLAIMED: 'A claim has been paid on this policy.',
    // Job lifecycle
    QUEUED: 'Waiting in the queue to run.',
    RUNNING: 'Currently processing.',
    COMPLETED: 'Processing finished successfully.',
    FAILED: 'Processing failed.',
    CANCELLED: 'Cancelled before completion.',
    // Rule/config lifecycle
    DRAFT: 'Draft — not yet deployed.',
    DEPLOYED: 'Deployed and in effect.',
    ARCHIVED: 'Archived — no longer in effect.',
    // Schedule
    ACTIVE: 'Schedule is active and will run.',
    INACTIVE: 'Schedule is paused / inactive.',
    // Case/application
    SUBMITTED: 'Application submitted and awaiting underwriting.',
    REFERRED: 'Sent to an underwriter for manual review.',
    ASSIGNED: 'Assigned to an underwriter.',
    REQUIREMENT_ISSUED: 'A requirement (APS, medicals) has been issued.',
    DECISION_RECORDED: 'A decision has been recorded on the case.',
    APPROVED: 'Approved.',
    DECLINED: 'Declined.',
  })[String(v)] ?? null,
}
