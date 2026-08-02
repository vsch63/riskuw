import { useState, useEffect, useCallback } from 'react'
import DocumentUploadPanel from './DocumentUploadPanel'
import Icd10Lookup from './Icd10Lookup'
import {
  Form, Input, InputNumber, Select, DatePicker,
  Checkbox, Button, Spin, Tooltip, Collapse, Tag, Divider, message, Tabs,
} from 'antd'
import {
  ThunderboltOutlined, InfoCircleOutlined, DownloadOutlined,
  ReloadOutlined, CheckCircleFilled, CloseCircleFilled,
  PauseCircleFilled, SwapOutlined, WarningFilled,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, productsAPI, uwAPI } from '../api/client'
import type { Product, UWDecision, EvaluatePayload, RuleFired } from '../types'
import { SessionAnalyticsTab, PlatformAnalyticsTab } from './WorkbenchAnalyticsTabs'

const { Option } = Select
const { Panel } = Collapse

// ─── Helpers ────────────────────────────────────────────────────
const fmt = (n: number) => new Intl.NumberFormat('en-IN').format(n)
const fmtCurr = (n: number) => `₹${fmt(Math.round(n))}`

function bmi(h: number, w: number) {
  return ((w / (h * h)) * 703).toFixed(1)
}

const OUTCOME_CONFIG: Record<string, {
  bg: string; border: string; glow: string;
  icon: React.ReactNode; label: string; textColor: string
}> = {
  APPROVED: {
    bg: 'linear-gradient(145deg, #052d1a 0%, #083d24 100%)',
    border: 'rgba(34,197,94,0.35)',
    glow: '0 0 40px rgba(34,197,94,0.2)',
    icon: <CheckCircleFilled style={{ fontSize: 40, color: '#4ade80' }} />,
    label: 'APPROVED',
    textColor: '#4ade80',
  },
  DECLINED: {
    bg: 'linear-gradient(145deg, #2d0505 0%, #3d0808 100%)',
    border: 'rgba(239,68,68,0.35)',
    glow: '0 0 40px rgba(239,68,68,0.18)',
    icon: <CloseCircleFilled style={{ fontSize: 40, color: '#f87171' }} />,
    label: 'DECLINED',
    textColor: '#f87171',
  },
  POSTPONED: {
    bg: 'linear-gradient(145deg, #130d2d 0%, #1e1244 100%)',
    border: 'rgba(192,132,252,0.35)',
    glow: '0 0 40px rgba(192,132,252,0.18)',
    icon: <PauseCircleFilled style={{ fontSize: 40, color: '#c084fc' }} />,
    label: 'POSTPONED',
    textColor: '#c084fc',
  },
  REFERRED: {
    bg: 'linear-gradient(145deg, #1a1505 0%, #2a2008 100%)',
    border: 'rgba(251,191,36,0.35)',
    glow: '0 0 40px rgba(251,191,36,0.15)',
    icon: <SwapOutlined style={{ fontSize: 40, color: '#fbbf24' }} />,
    label: 'REFERRED',
    textColor: '#fbbf24',
  },
}

function outcomeKey(outcome: string): keyof typeof OUTCOME_CONFIG {
  if (outcome?.includes('APPROVED')) return 'APPROVED'
  if (outcome?.includes('DECLIN'))   return 'DECLINED'
  if (outcome?.includes('POSTPON'))  return 'POSTPONED'
  return 'REFERRED'
}

// ─── Sub-components ──────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
      color: 'var(--slate-500)', textTransform: 'uppercase',
      margin: '18px 0 10px', paddingBottom: 8,
      borderBottom: '1px solid rgba(255,255,255,0.06)',
    }}>
      {children}
    </div>
  )
}

function DataRow({ label, value, mono = false, highlight = false }: {
  label: string; value: React.ReactNode; mono?: boolean; highlight?: boolean
}) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '7px 0', borderBottom: '1px solid rgba(255,255,255,0.05)',
    }}>
      <span style={{ fontSize: 12, color: 'var(--slate-400)' }}>{label}</span>
      <span style={{
        fontSize: highlight ? 14 : 13,
        fontFamily: mono ? 'var(--font-mono)' : 'var(--font-body)',
        fontWeight: highlight ? 700 : 500,
        color: highlight ? 'var(--teal-400)' : '#fff',
      }}>
        {value}
      </span>
    </div>
  )
}

// ─── Decision Panel ──────────────────────────────────────────────

// ── AI Assessment Panel ───────────────────────────────────────────────────────
function AIAssessmentPanel({ aiScore, loading }: { aiScore: any; loading: boolean }) {
  if (!loading && !aiScore) return null

  const RISK_COLOR: Record<string, string> = {
    LOW: '#22c55e', MEDIUM: '#f59e0b', HIGH: '#ef4444',
    VERY_HIGH: '#dc2626', DECLINED: '#dc2626',
  }
  const REC_COLOR: Record<string, string> = {
    APPROVE: '#22c55e', RATE: '#f59e0b', REFER: '#f59e0b',
    DECLINE: '#ef4444', DECLINED: '#ef4444',
  }

  return (
    <div style={{
      background: 'linear-gradient(135deg, rgba(15,118,110,0.08), rgba(8,145,178,0.06))',
      border: '1px solid rgba(0,212,170,0.2)',
      borderRadius: 12, padding: '16px 18px', marginBottom: 14, flexShrink: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 16 }}>🤖</span>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#00d4aa', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          AI Risk Assessment
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 10, color: '#6b7280' }}>XGBoost ML Engine</div>
      </div>

      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#6b7280', fontSize: 12 }}>
          <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</span>
          Analysing risk profile...
        </div>
      ) : aiScore?.error ? (
        <div style={{ fontSize: 12, color: '#f87171' }}>{aiScore.error}</div>
      ) : aiScore && (
        <>
          {/* Score bar */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11, color: '#9ca3af' }}>AI Risk Score</span>
              <span style={{ fontSize: 20, fontWeight: 800, color: RISK_COLOR[aiScore.risk_tier] || '#e2e8f0' }}>
                {aiScore.risk_score?.toFixed(1)}<span style={{ fontSize: 12, fontWeight: 400, color: '#6b7280' }}>/100</span>
              </span>
            </div>
            <div style={{ height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{
                height: '100%', borderRadius: 3,
                width: `${aiScore.risk_score ?? 0}%`,
                background: `linear-gradient(90deg, #22c55e, ${RISK_COLOR[aiScore.risk_tier] || '#00d4aa'})`,
                transition: 'width 0.8s ease',
              }}/>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3 }}>
              <span style={{ fontSize: 9, color: '#6b7280' }}>Low Risk (0)</span>
              <span style={{ fontSize: 9, color: '#6b7280' }}>High Risk (100)</span>
            </div>
          </div>

          {/* Recommendation + confidence */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
            <div style={{
              flex: 1, background: 'rgba(0,0,0,0.2)', borderRadius: 8, padding: '10px 12px',
              border: `1px solid ${REC_COLOR[aiScore.recommendation] || '#374151'}33`,
            }}>
              <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4 }}>AI Recommendation</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: REC_COLOR[aiScore.recommendation] || '#e2e8f0' }}>
                {aiScore.recommendation}
              </div>
            </div>
            <div style={{ flex: 1, background: 'rgba(0,0,0,0.2)', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4 }}>Confidence</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0' }}>
                {((aiScore.confidence ?? 0) * 100).toFixed(0)}%
              </div>
            </div>
            <div style={{ flex: 1, background: 'rgba(0,0,0,0.2)', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4 }}>Risk Tier</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: RISK_COLOR[aiScore.risk_tier] || '#e2e8f0' }}>
                {aiScore.risk_tier}
              </div>
            </div>
          </div>

          {/* Concerns & positives */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
            {aiScore.primary_concerns?.length > 0 && (
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 10, color: '#f87171', fontWeight: 600, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  ⚠ Primary Concerns
                </div>
                {aiScore.primary_concerns.map((c: string, i: number) => (
                  <div key={i} style={{
                    fontSize: 11, color: '#fca5a5', padding: '4px 8px', marginBottom: 4,
                    background: 'rgba(239,68,68,0.08)', borderRadius: 5,
                    borderLeft: '2px solid rgba(239,68,68,0.4)',
                  }}>{c}</div>
                ))}
              </div>
            )}
            {aiScore.positive_factors?.length > 0 && (
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 10, color: '#4ade80', fontWeight: 600, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  ✓ Positive Factors
                </div>
                {aiScore.positive_factors.map((f: string, i: number) => (
                  <div key={i} style={{
                    fontSize: 11, color: '#86efac', padding: '4px 8px', marginBottom: 4,
                    background: 'rgba(34,197,94,0.08)', borderRadius: 5,
                    borderLeft: '2px solid rgba(34,197,94,0.4)',
                  }}>{f}</div>
                ))}
              </div>
            )}
          </div>

          {/* Narrative */}
          {aiScore.narrative && (
            <div style={{
              background: 'rgba(0,0,0,0.2)', borderRadius: 8, padding: '10px 12px',
              border: '1px solid rgba(255,255,255,0.06)', marginBottom: aiScore.loading_suggestion ? 10 : 0,
            }}>
              <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                AI Narrative
              </div>
              <div style={{ fontSize: 12, color: '#d1d5db', lineHeight: 1.7 }}>{aiScore.narrative}</div>
            </div>
          )}

          {/* Loading suggestion */}
          {aiScore.loading_suggestion && aiScore.recommendation !== 'DECLINE' && (
            <div style={{
              marginTop: 10, padding: '8px 12px',
              background: 'rgba(245,158,11,0.08)', borderRadius: 7,
              border: '1px solid rgba(245,158,11,0.2)',
              fontSize: 11, color: '#fcd34d',
            }}>
              💡 <strong>Loading Suggestion:</strong> {aiScore.loading_suggestion}
            </div>
          )}

          {/* Audit note */}
          <div style={{ marginTop: 10, fontSize: 10, color: '#374151', textAlign: 'right' }}>
            AI assessment logged to audit trail · Human decision takes precedence
          </div>
        </>
      )}
    </div>
  )
}

function DecisionCard({ result, loading, appRef }: {
  result: UWDecision | null; loading: boolean; appRef: string
}) {
  if (loading) {
    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: 16, color: 'var(--teal-400)',
      }}>
        <Spin size="large" />
        <div style={{ fontSize: 13, color: 'var(--slate-400)' }}>
          Running underwriting rules…
        </div>
      </div>
    )
  }

  if (!result) {
    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: 12, padding: 32, textAlign: 'center',
      }}>
        {/* Idle illustration */}
        <div style={{
          width: 80, height: 80, borderRadius: '50%',
          background: 'rgba(0,212,170,0.07)',
          border: '1.5px dashed rgba(0,212,170,0.2)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          marginBottom: 8,
        }}>
          <ThunderboltOutlined style={{ fontSize: 32, color: 'var(--teal-600)' }} />
        </div>
        <div style={{
          fontFamily: 'var(--font-display)', fontWeight: 600,
          fontSize: 17, color: 'var(--slate-300)',
        }}>
          Decision panel
        </div>
        <div style={{ fontSize: 13, color: 'var(--slate-500)', lineHeight: 1.6 }}>
          Fill the intake form and click<br />
          <span style={{ color: 'var(--teal-500)' }}>Run Underwriting Evaluation</span><br />
          to see the instant decision here.
        </div>
        <div style={{
          marginTop: 16, fontSize: 11, fontFamily: 'var(--font-mono)',
          color: 'var(--slate-600)', padding: '8px 14px',
          background: 'rgba(255,255,255,0.03)', borderRadius: 6,
          border: '1px solid rgba(255,255,255,0.07)',
        }}>
          POST /underwriting/evaluate
        </div>
      </div>
    )
  }

  const ok = outcomeKey(result.outcome)
  const cfg = OUTCOME_CONFIG[ok]
  const debits = result.net_debit_points ?? result.total_debits ?? 0
  const rulesFired: RuleFired[] = result.rules_fired ?? []

  return (
    <div style={{ height: '100%', overflow: 'hidden auto', display: 'flex', flexDirection: 'column' }}>
      {/* Outcome hero */}
      <div style={{
        background: cfg.bg,
        border: `1.5px solid ${cfg.border}`,
        boxShadow: cfg.glow,
        borderRadius: 16, padding: '28px 24px',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        gap: 12, marginBottom: 16, flexShrink: 0,
      }}>
        {cfg.icon}
        <div style={{
          fontFamily: 'var(--font-display)', fontWeight: 700,
          fontSize: 32, color: cfg.textColor, letterSpacing: '-0.02em',
          lineHeight: 1,
        }}>
          {cfg.label}
        </div>

        {result.is_stp && (
          <Tag color="green" style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            letterSpacing: '0.1em', padding: '2px 10px',
          }}>
            ⚡ STP — STRAIGHT THROUGH
          </Tag>
        )}
        {!result.is_stp && (
          <Tag color="gold" style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            letterSpacing: '0.1em', padding: '2px 10px',
          }}>
            👤 REFERRED TO UW
          </Tag>
        )}

        {/* Score bar */}
        <div style={{ width: '100%', marginTop: 4 }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            fontSize: 11, color: 'var(--slate-400)', marginBottom: 6,
          }}>
            <span>Net Debit Points</span>
            <span style={{
              fontFamily: 'var(--font-mono)', fontWeight: 700,
              color: debits > 150 ? '#f87171' : debits > 75 ? '#fbbf24' : '#4ade80',
            }}>
              {debits}
            </span>
          </div>
          <div style={{
            height: 6, background: 'rgba(255,255,255,0.08)',
            borderRadius: 3, overflow: 'hidden',
          }}>
            <div style={{
              height: '100%',
              width: `${Math.min(100, (debits / 300) * 100)}%`,
              background: debits > 150
                ? 'linear-gradient(90deg, #f59e0b, #ef4444)'
                : debits > 75
                ? 'linear-gradient(90deg, #22c55e, #f59e0b)'
                : '#00d4aa',
              borderRadius: 3,
              transition: 'width 800ms cubic-bezier(0.4,0,0.2,1)',
            }} />
          </div>
        </div>
      </div>

      {/* Details */}
      <div style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 12, padding: '0 16px',
        marginBottom: 14, flexShrink: 0,
      }}>
        <SectionLabel>Decision Details</SectionLabel>
        {result.risk_class && <DataRow label="Risk Class" value={result.risk_class} mono highlight />}
        {result.table_rating != null && result.table_rating > 0 &&
          <DataRow label="Table Rating" value={`Table ${result.table_rating}`} mono />}
        {result.flat_extra_per_thou != null && result.flat_extra_per_thou > 0 &&
          <DataRow label="Flat Extra" value={`₹${result.flat_extra_per_thou}/₹1000`} mono />}
        {result.pathway &&
          <DataRow label="Pathway" value={result.pathway.replace(/_/g, ' ')} />}
        <div style={{ height: 10 }} />
      </div>

      {/* ── Premium Breakdown ── */}
      {(result.approved_premium != null && result.approved_premium > 0) && (() => {
        const pd = (result as any).premium_detail
        const annual     = pd?.annual_premium     ?? result.approved_premium
        const monthly    = pd?.monthly_premium
        const quarterly  = pd?.quarterly_premium
        const halfYearly = pd?.half_yearly_premium
        const firstYear  = pd?.total_first_year
        const renewal    = pd?.total_renewal
        const gstFY      = pd?.gst_first_year
        const gstRen     = pd?.gst_renewal
        const steps      = pd?.steps as Array<{ step_name?: string; result?: number; description?: string }> | undefined
        const formulaName = pd?.formula_name
        const premError  = pd?.error
        return (
          <div style={{
            background: 'linear-gradient(145deg, #041f12, #062a19)',
            border: '1.5px solid rgba(0,212,170,0.25)',
            borderRadius: 12, padding: '16px 18px',
            marginBottom: 14, flexShrink: 0,
          }}>
            <div style={{
              fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
              color: 'var(--teal-500)', textTransform: 'uppercase',
              marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <span>💰</span> Premium Calculation
              {formulaName && (
                <span style={{ fontSize: 9, color: 'var(--slate-500)', fontWeight: 400,
                  letterSpacing: '0.05em', marginLeft: 'auto', textTransform: 'none' }}>
                  {formulaName}
                </span>
              )}
            </div>

            {premError ? (
              <div style={{ fontSize: 12, color: '#f87171' }}>
                Premium engine error: {String(premError)}
              </div>
            ) : (
              <>
                {/* Annual — hero */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                  paddingBottom: 10, marginBottom: 10,
                  borderBottom: '1px solid rgba(0,212,170,0.15)' }}>
                  <span style={{ fontSize: 13, color: 'var(--slate-300)', fontWeight: 600 }}>Annual Premium</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, color: 'var(--teal-400)' }}>
                    {fmtCurr(annual)}
                  </span>
                </div>
                {/* GST Breakdown */}
                {(gstFY != null || firstYear != null) && (
                  <div style={{ marginBottom: 10, padding: '8px 10px',
                    background: 'rgba(251,191,36,0.06)',
                    border: '1px solid rgba(251,191,36,0.15)',
                    borderRadius: 8 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: '#fbbf24',
                      textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
                      GST Breakdown (IRDAI Norms)
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 2 }}>BASE PREMIUM</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--slate-200)' }}>
                          {fmtCurr(annual)}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 2 }}>GST FIRST YEAR (18%)</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: '#fbbf24' }}>
                          + {fmtCurr(gstFY ?? 0)}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 2 }}>TOTAL FIRST YEAR</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: '#34d399' }}>
                          {fmtCurr(firstYear ?? (annual + (gstFY ?? 0)))}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 2 }}>TOTAL RENEWAL (5% GST)</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: 'var(--teal-400)' }}>
                          {fmtCurr(renewal ?? annual)}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Modal grid */}
                {(monthly != null || quarterly != null || halfYearly != null) && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 10 }}>
                    {monthly != null && (
                      <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 4 }}>Monthly</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: '#fff' }}>{fmtCurr(monthly)}</div>
                      </div>
                    )}
                    {quarterly != null && (
                      <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 4 }}>Quarterly</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: '#fff' }}>{fmtCurr(quarterly)}</div>
                      </div>
                    )}
                    {halfYearly != null && (
                      <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 4 }}>Half-Yearly</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: '#fff' }}>{fmtCurr(halfYearly)}</div>
                      </div>
                    )}
                  </div>
                )}

                {/* First year / renewal */}
                {(firstYear != null || renewal != null) && (
                  <div style={{ display: 'flex', gap: 8, marginBottom: steps?.length ? 10 : 0 }}>
                    {firstYear != null && (
                      <div style={{ flex: 1, background: 'rgba(255,255,255,0.04)', borderRadius: 8, padding: '8px 10px' }}>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 3 }}>Total First Year</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{fmtCurr(firstYear)}</div>
                      </div>
                    )}
                    {renewal != null && (
                      <div style={{ flex: 1, background: 'rgba(255,255,255,0.04)', borderRadius: 8, padding: '8px 10px' }}>
                        <div style={{ fontSize: 10, color: 'var(--slate-500)', marginBottom: 3 }}>Renewal Premium</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{fmtCurr(renewal)}</div>
                      </div>
                    )}
                  </div>
                )}

                {/* Formula steps */}
                {steps && steps.length > 0 && (
                  <Collapse ghost size="small" style={{ marginTop: 4 }}>
                    <Panel key="steps" header={
                      <span style={{ fontSize: 11, color: 'var(--slate-400)' }}>
                        Formula Steps
                        <Tag style={{ marginLeft: 6, fontSize: 9 }} color="cyan">{steps.length}</Tag>
                      </span>
                    }>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {steps.map((s, i) => (
                          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                            padding: '5px 8px', background: 'rgba(255,255,255,0.03)', borderRadius: 6 }}>
                            <span style={{ fontSize: 11, color: 'var(--slate-400)' }}>
                              {s.step_name ?? s.description ?? `Step ${i + 1}`}
                            </span>
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--teal-400)', fontWeight: 600 }}>
                              {s.result != null ? fmtCurr(s.result) : '—'}
                            </span>
                          </div>
                        ))}
                      </div>
                    </Panel>
                  </Collapse>
                )}
              </>
            )}
          </div>
        )
      })()}

      {/* Premium note — shown when premium couldn't be calculated */}
      {(result as any).premium_note && !(result.approved_premium != null && result.approved_premium > 0) && (
        <div style={{
          background: 'rgba(251,191,36,0.07)',
          border: '1px solid rgba(251,191,36,0.25)',
          borderRadius: 10, padding: '10px 14px',
          marginBottom: 14, flexShrink: 0,
          display: 'flex', alignItems: 'flex-start', gap: 8,
        }}>
          <WarningFilled style={{ color: '#fbbf24', marginTop: 2 }} />
          <div>
            <div style={{ fontSize: 11, color: '#fbbf24', fontWeight: 700, marginBottom: 3 }}>
              Premium Not Calculated
            </div>
            <div style={{ fontSize: 12, color: 'var(--slate-300)', lineHeight: 1.6 }}>
              {(result as any).premium_note}
            </div>
          </div>
        </div>
      )}
      <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 12, padding: '0 16px', marginBottom: 14, flexShrink: 0 }}>
        <SectionLabel>Reference</SectionLabel>
        {result.application_id && <DataRow label="Application ID" value={result.application_id} mono />}
        {result.case_number && <DataRow label="Case Number" value={result.case_number} mono />}
        {result.case_id && <DataRow label="Case ID" value={result.case_id} mono />}
        {result.decision_id && <DataRow label="Decision ID" value={result.decision_id} mono />}
        {result.rules_version && <DataRow label="Rules Version" value={result.rules_version} mono />}
        {result.evaluated_at && (
          <DataRow
            label="Evaluated At"
            value={result.evaluated_at.slice(0, 19).replace('T', ' ')}
          />
        )}
        <div style={{ height: 10 }} />
      </div>

      {/* Adverse action */}
      {result.adverse_action_text && (
        <div style={{
          background: 'rgba(239,68,68,0.07)',
          border: '1px solid rgba(239,68,68,0.2)',
          borderRadius: 10, padding: '12px 14px',
          marginBottom: 14, flexShrink: 0,
        }}>
          <div style={{ fontSize: 11, color: '#f87171', fontWeight: 700, marginBottom: 6 }}>
            <WarningFilled style={{ marginRight: 6 }} />
            ADVERSE ACTION REASON
          </div>
          <div style={{ fontSize: 12, color: 'var(--slate-300)', lineHeight: 1.7 }}>
            {result.adverse_action_text}
          </div>
        </div>
      )}

      {/* Rules fired */}
      {rulesFired.length > 0 && (
        <Collapse
          ghost
          style={{ marginBottom: 14, flexShrink: 0 }}
          items={[{
            key: '1',
            label: (
              <span style={{ fontSize: 12, color: 'var(--slate-300)', fontWeight: 600 }}>
                Rules Fired
                <Tag style={{ marginLeft: 8, fontSize: 10 }} color="blue">
                  {rulesFired.length}
                </Tag>
              </span>
            ),
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {rulesFired.map((r, i) => {
                  const name = r.rule_name ?? r.name ?? r.rule_code ?? `Rule ${i + 1}`
                  const pts = r.debit_points ?? 0
                  return (
                    <div key={i} style={{
                      display: 'flex', justifyContent: 'space-between',
                      alignItems: 'flex-start', gap: 8,
                      padding: '8px 10px',
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid rgba(255,255,255,0.07)',
                      borderRadius: 7,
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, color: '#fff', fontWeight: 500 }}>
                          {name}
                        </div>
                        {r.description && (
                          <div style={{ fontSize: 11, color: 'var(--slate-500)', marginTop: 2 }}>
                            {r.description}
                          </div>
                        )}
                        {r.category && (
                          <Tag style={{ marginTop: 4, fontSize: 9 }}>{r.category}</Tag>
                        )}
                      </div>
                      <div style={{
                        fontFamily: 'var(--font-mono)', fontWeight: 700,
                        fontSize: 13,
                        color: pts > 50 ? '#f87171' : pts > 25 ? '#fbbf24' : '#94a3b8',
                        flexShrink: 0,
                      }}>
                        {pts > 0 ? `+${pts}` : pts}
                      </div>
                    </div>
                  )
                })}
              </div>
            ),
          }]}
        />
      )}

      {/* Download report button */}
      {result && (
        <>
        <Button
          icon={<DownloadOutlined />}
          onClick={() => {
            const content = [
              '=== UNDERWRITING DECISION REPORT ===',
              '',
              `Applicant Ref : ${result.application_id || '-'}`,
              `Product       : ${(result as any).product_code || '-'}`,
              `Decision      : ${result.outcome}`,
              `Risk Class    : ${result.risk_class}`,
              `Debit Points  : ${result.net_debit_points}`,
              `Evaluated At  : ${result.evaluated_at}`,
              '',
              '=== PREMIUM BREAKDOWN ===',
              `Annual Premium    : ${(result as any).approved_premium ?? '-'}`,
              `GST (First Year)  : ${(result as any).premium_detail?.gst_first_year ?? '-'}`,
              `Total First Year  : ${(result as any).premium_detail?.total_first_year ?? '-'}`,
              `Total Renewal     : ${(result as any).premium_detail?.total_renewal ?? '-'}`,
              `Monthly Premium   : ${(result as any).premium_detail?.monthly_premium ?? '-'}`,
              `Formula           : ${(result as any).premium_detail?.formula_name ?? '-'}`,
              '',
              '=== RULES FIRED ===',
              ...(result.rules_fired || []).map((r: any) =>
                `  ${r.rule_name}: ${r.debit_points > 0 ? '+' : ''}${r.debit_points} pts`
              ),
              ].join('\n')
            const blob = new Blob([content], { type: 'text/plain' })
            const url  = URL.createObjectURL(blob)
            const a    = document.createElement('a')
            a.href     = url
            a.download = `decision-${result.application_id || 'report'}.txt`
            a.click()
            URL.revokeObjectURL(url)
          }}
          style={{
            width: '100%', marginBottom: 8, flexShrink: 0,
            borderColor: 'rgba(0,212,170,0.3)', color: 'var(--teal-400)',
            background: 'rgba(0,212,170,0.05)',
          }}
        >
          Download Decision Report
        </Button>
        <Button
          onClick={() => {
              const outcome = result.outcome || ''
              const tplMap: Record<string,string> = {
                'APPROVED_STP': 'TPL-APPROVED-001',
                'APPROVED':     'TPL-APPROVED-001',
                'DECLINED':     'TPL-DECLINED-001',
                'REFERRED':     'TPL-REFERRED-001',
              }
              const tplId = tplMap[outcome] || 'TPL-APPROVED-001'
              const params = new URLSearchParams({
                applicant_ref:  result.application_id || '',
                product_code:   result.product_code || '',
                face_amount:    String(result.face_amount || 0),
                premium:        String(result.approved_premium || 0),
                risk_class:     result.risk_class || '',
                outcome:        outcome,
                case_number:    result.case_number || '',
              })
              const token = localStorage.getItem('riskuw_token')
              fetch(`/system/letter-templates/${tplId}/generate?${params}`, {
                headers: { Authorization: `Bearer ${token}` }
              }).then(r => r.blob()).then(blob => {
                const url = URL.createObjectURL(blob)
                window.open(url, '_blank')
              })
            }}
            style={{
              width: '100%', marginBottom: 8,
              borderColor: 'rgba(59,130,246,0.3)', color: '#60a5fa',
              background: 'rgba(59,130,246,0.05)',
            }}
          >
            📄 Generate Decision Letter
          </Button>
        </>
      )}
    </div>
  )
}

// ─── Field helpers ───────────────────────────────────────────────
const TOBACCO_OPTIONS = ['NEVER', 'NON_SMOKER', 'SMOKER', 'CIGAR', 'CHEW', 'VAPE']
const DIABETES_OPTIONS = ['NONE', 'PRE_DIABETIC', 'TYPE2', 'TYPE1']
const CARDIAC_OPTIONS = [
  'NONE', 'HYPERTENSION', 'HYPERTENSION_UNCONTROLLED',
  'MI', 'ANGINA', 'CABG', 'STENT', 'ARRHYTHMIA',
]
const OCC_CLASSES = ['1', '2', '3', '4', 'D']
const HAZARD_TYPES = [
  'SKYDIVING', 'BASE_JUMPING', 'SCUBA_DEEP', 'MOTOR_RACING',
  'MOTORCYCLES', 'MOUNTAINEERING', 'HANG_GLIDING', 'PRIVATE_PILOT',
]

// ─── Main page ───────────────────────────────────────────────────
export default function EvaluatePage() {
  const [form] = Form.useForm()
  const [products, setProducts] = useState<Record<string, Product>>({})
  const [productList, setProductList] = useState<Product[]>([])
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [selectedProd, setSelectedProd] = useState<Product | null>(null)
  const [loading, setLoading] = useState(false)
  const [prodLoading, setProdLoading] = useState(true)
  const [result, setResult] = useState<UWDecision | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [evalMode, setEvalMode] = useState<'single'|'multi'>('single')
  // Multi-benefit proposal state
  const [proposalResult, setProposalResult] = useState<any>(null)
  const [multiBaseCode, setMultiBaseCode] = useState<string>('')
  const [multiFaceAmount, setMultiFaceAmount] = useState<number>(1000000)
  const [multiTermYrs, setMultiTermYrs] = useState<number>(20)
  const [riderLines, setRiderLines] = useState<any[]>([])
  const [appRef, setAppRef] = useState('APP-001')
  const [sessionCases, setSessionCases] = useState<any[]>([])
  const [activeTab, setActiveTab] = useState('evaluate')
  const [userLabels, setUserLabels] = useState<{
    label_key: string; label_name: string; data_type: string;
    default_value?: string; prefix?: string; suffix?: string; description?: string
  }[]>([])

  // AI Assist state
  const [aiEngine, setAiEngine]     = useState('claude')
  const [aiResult, setAiResult]     = useState<any>(null)
  const [aiLoading, setAiLoading]   = useState(false)
  const [lastPayload, setLastPayload] = useState<any>(null)

  // Load active user labels for premium formula inputs
  useEffect(() => {
    const token = localStorage.getItem('riskuw_token')
    fetch('/system/user-labels/keys', {
      headers: { 'Authorization': `Bearer ${token}` }
    }).then(r => r.json()).then(data => {
      setUserLabels(Array.isArray(data) ? data : [])
    }).catch(() => {})
  }, [])

  // Watched form values for conditional rendering
  const tobacco    = Form.useWatch('tobacco_status', form) ?? 'NEVER'
  const [icd10Codes, setIcd10Codes] = useState<any[]>([])
  const [icd10Debits, setIcd10Debits] = useState(0)
  const diabetes   = Form.useWatch('diabetes_type', form) ?? 'NONE'
  const cardiac    = Form.useWatch('heart_condition', form) ?? 'NONE'
  const useBuild   = Form.useWatch('use_build', form) ?? true
  const useBP      = Form.useWatch('use_bp', form) ?? true
  const bpMed      = Form.useWatch('bp_on_med', form) ?? false
  const useLabs    = Form.useWatch('use_labs', form) ?? false
  const isHazard   = Form.useWatch('hazardous_activity', form) ?? false
  const heightVal  = Form.useWatch('height_inches', form) ?? 70
  const weightVal  = Form.useWatch('weight_lbs', form) ?? 175

  // Load products
  const loadProducts = useCallback(async () => {
    setProdLoading(true)
    try {
      const res = await productsAPI.list()
      const data = Array.isArray(res.data) ? res.data : (res.data.products ?? [])
      const map: Record<string, Product> = {}
      const list: Product[] = []
      for (const p of data) {
        const code = p.product_code ?? p.code
        if (!code) continue
        const prod: Product = {
          ...p,
          product_code: code,
          name: p.product_name ?? p.name ?? code,
          min_face: p.min_face_amount ?? p.min_face ?? 100_000,
          max_face: p.max_face_amount ?? p.max_face ?? 5_000_000,
          terms: p.terms ?? [],
          is_gi: p.is_gi ?? false,
        }
        map[code] = prod
        list.push(prod)
      }
      setProducts(map)
      setProductList(list)
      if (list.length > 0) {
        const first = list[0].product_code
        setSelectedCode(first)
        setSelectedProd(list[0])
        form.setFieldValue('product_code', first)
      }
    } catch {
      message.error('Could not load products — check API connection')
    } finally {
      setProdLoading(false)
    }
  }, [form])

  useEffect(() => { loadProducts() }, [loadProducts])

  const handleProductChange = (code: string) => {
    setSelectedCode(code)
    setSelectedProd(products[code] ?? null)
    setResult(null)
  }

  const handleSubmit = async () => {
    try {
      await form.validateFields()
    } catch {
      message.warning('Please fill all required fields')
      return
    }

    const v = form.getFieldsValue(true)
    const prod = selectedProd

    const payload: EvaluatePayload = {
      applicant_ref:    v.applicant_ref ?? 'APP-001',
      premium_mode:     v.premium_mode ?? 'ANNUAL',
      first_name:       v.first_name ?? '',
      middle_name:      v.middle_name ?? '',
      last_name:        v.last_name ?? '',
      email:            v.email ?? '',
      mobile:           v.mobile ?? '',
      address_line1:    v.address_line1 ?? '',
      city:             v.city ?? '',
      pincode:          v.pincode ?? '',
      age:              v.age,
      gender:           v.gender,
      state:            v.state,
      product_type:     'INDIVIDUAL_TERM',
      product_code:     selectedCode,
      face_amount:      v.face_amount,
      coverage_term_yrs: v.term_yrs ?? 20,
      policy_effective_date: v.policy_eff ? dayjs(v.policy_eff).format('YYYY-MM-DD') : undefined,
      policy_expire_date:    v.policy_exp ? dayjs(v.policy_exp).format('YYYY-MM-DD') : undefined,
      tobacco_status:   v.tobacco_status,
      tobacco_quit_years: v.tobacco_status === 'NON_SMOKER' ? v.tobacco_quit : null,
      heart_condition:  v.heart_condition ?? 'NONE',
      heart_event_years_ago: cardiac !== 'NONE' ? v.heart_yrs : null,
      diabetes_type:    v.diabetes_type ?? 'NONE',
      icd10_codes:      icd10Codes.map((c: any) => c.code),
      extra_debit_points: icd10Debits,
      diabetes_dx_age:  diabetes !== 'NONE' ? v.diabetes_dx_age : null,
      a1c:              diabetes !== 'NONE' ? v.a1c : null,
      hiv_positive:     v.hiv_positive ?? false,
      cirrhosis:        v.cirrhosis ?? false,
      stroke_history:   v.stroke_history ?? false,
      kidney_disease:   v.kidney_disease ?? false,
      depression_history: v.depression_history ?? false,
      depression_hospitalized: v.dep_hosp ?? false,
      epilepsy:         v.epilepsy ?? false,
      copd:             v.copd ?? false,
      occupation_class: v.occ_class ?? '1',
      occupation_title: v.occ_title ?? '',
      alcohol_drinks_week: v.alcohol_drinks_week ?? 0,
      hazardous_activity: v.hazardous_activity ?? false,
      hazard_types:     v.hazard_types ?? [],
      financial: {
        annual_income:          v.annual_income ?? 100_000,
        existing_life_coverage: v.existing_coverage ?? 0,
      },
      family_history: {
        cardiovascular_before_60: v.fh_cardio ?? false,
        stroke_before_65:         v.fh_stroke ?? false,
        cancer_history:   false,
        diabetes_history: false,
      },
      driving_record: {
        dui_dwi_count_5yr:    v.dui_count ?? 0,
        major_violations_3yr: v.major_vio ?? 0,
        minor_violations_3yr: 0,
        at_fault_accidents_3yr: 0,
        license_suspended: false,
      },
    }

    if (useBuild && v.height_inches && v.weight_lbs) {
      payload.build = { height_inches: v.height_inches, weight_lbs: v.weight_lbs }
    }
    if (useBP && v.systolic) {
      payload.blood_pressure = {
        systolic:        v.systolic,
        diastolic:       v.diastolic ?? 80,
        on_medication:   v.bp_on_med ?? false,
        medication_count: v.bp_med_cnt ?? 0,
      }
    }
    if (useLabs) {
      payload.lab_values = {
        total_cholesterol: v.total_chol,
        hdl: v.hdl, ldl: v.ldl, egfr: v.egfr,
      }
    }

    setAppRef(v.applicant_ref ?? 'APP-001')
    setSubmitting(true)
    setResult(null)
    setAiResult(null)

    // Inject user label values into payload so premium formula can use them
    for (const ul of userLabels) {
      const val = v[`ul_${ul.label_key}`]
      if (val !== undefined && val !== null && val !== '') {
        ;(payload as any)[ul.label_key] = val
      }
    }

    // Store payload for AI scoring
    setLastPayload({
      ...payload,
      age:             v.age,
      gender:          v.gender,
      face_amount:     v.face_amount,
      tobacco_status:  v.tobacco_status,
      height_inches:   v.height_inches,
      weight_lbs:      v.weight_lbs,
      systolic_bp:     v.systolic,
      diastolic_bp:    v.diastolic,
      diabetes_type:   v.diabetes_type ?? 'NONE',
      heart_condition: v.heart_condition ?? 'NONE',
      hiv_positive:    v.hiv_positive ?? false,
      stroke_history:  v.stroke_history ?? false,
      kidney_disease:  v.kidney_disease ?? false,
      copd:            v.copd ?? false,
      depression_history: v.depression_history ?? false,
      alcohol_drinks_week: v.alcohol_drinks_week ?? 0,
      hazardous_activity: v.hazardous_activity ?? false,
      occupation_class: v.occ_class ?? 1,
      annual_income:   v.annual_income ?? 0,
      product_code:    selectedCode,
    })

    try {
      const res = await uwAPI.evaluate(payload)
      setResult(res.data)
      setLastPayload((p: any) => ({ ...p, uw_outcome: res.data?.outcome || '', net_debit_points: res.data?.net_debit_points || 0 }))
      // Fetch AI assessment in background
      setAiLoading(true)
      setAiResult(null)
      uwAPI.aiScore({ ...payload, engine: 'xgboost' }).then((r: any) => {
        setAiResult(r.data)
      }).catch(() => {}).finally(() => setAiLoading(false))
      // Accumulate for Session Analytics
      setSessionCases(prev => [...prev, {
        Ref:     payload.applicant_ref ?? appRef,
        Outcome: res.data.outcome ?? '—',
        Pathway: res.data.uw_pathway ?? res.data.pathway ?? '—',
        Debits:  res.data.net_debit_points ?? 0,
        Product: payload.product_code ?? '',
        ms:      res.data.decision_cycle_ms ?? 0,
      }])
    } catch (e: unknown) {
      const err = e as { response?: { data?: UWDecision & { detail?: string } } }
      const d = err.response?.data
      if (d?.outcome) {
        setResult(d)
      } else {
        message.error(d?.detail ?? 'Evaluation failed — check API connection')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const prod = selectedProd
  const isGI = prod?.is_gi ?? false
  const terms = prod?.terms ?? []
  const minFace = prod?.min_face ?? prod?.min_face_amount ?? 100_000
  const maxFace = prod?.max_face ?? prod?.max_face_amount ?? 5_000_000

  const workbenchTabs = [
    {
      key: 'evaluate',
      label: <span>⚡ Evaluate Application</span>,
      children: (
        <div style={{
          display: 'flex', height: 'calc(100vh - 108px)',
          overflow: 'visible',
        }}>
      {/* ── Left: Form ── */}
      <div style={{
        width: '58%', overflow: 'hidden auto',
        borderRight: '1px solid rgba(255,255,255,0.06)',
        padding: '28px 32px',
      }}>
        {/* Page header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: 24,
        }}>
          <div>
            <h1 style={{
              fontFamily: 'var(--font-display)', fontWeight: 700,
              fontSize: 22, color: '#fff', letterSpacing: '-0.02em', margin: 0,
            }}>
              <ThunderboltOutlined style={{ color: 'var(--teal-400)', marginRight: 10 }} />
              Evaluate Application
            </h1>
            <p style={{ color: 'var(--slate-500)', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
              {evalMode === 'single' ? 'Single benefit · Real-time decision' : 'Base plan + riders · Single underwriting call'}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div style={{ display: 'flex', background: 'rgba(255,255,255,0.05)', borderRadius: 8, padding: 3 }}>
              <button onClick={() => { setEvalMode('single'); setProposalResult(null); }}
                style={{ padding: '5px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, transition: 'all 0.2s',
                  background: evalMode === 'single' ? '#0f766e' : 'transparent',
                  color: evalMode === 'single' ? '#fff' : '#6b7280' }}>
                Single
              </button>
              <button onClick={() => { setEvalMode('multi'); setResult(null); setAiResult(null); }}
                style={{ padding: '5px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, transition: 'all 0.2s',
                  background: evalMode === 'multi' ? '#0f766e' : 'transparent',
                  color: evalMode === 'multi' ? '#fff' : '#6b7280' }}>
                Multi-Benefit
              </button>
            </div>
            <Button
              icon={<ReloadOutlined />}
              size="small"
              onClick={loadProducts}
              loading={prodLoading}
              style={{ borderColor: 'rgba(255,255,255,0.12)', color: 'var(--slate-400)' }}
            >
              Reload
            </Button>
          </div>
        </div>

        {/* Multi-benefit: base plan + riders — shown at TOP when in multi mode */}
        {evalMode === 'multi' && (
          <div style={{ marginBottom: 20 }}>
            {/* Base plan selector */}
            <div style={{ background: 'rgba(0,212,170,0.05)', border: '1px solid rgba(0,212,170,0.2)',
              borderRadius: 10, padding: '14px 16px', marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#00d4aa',
                textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
                Primary Benefit (Base Plan)
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 10 }}>
                <div>
                  <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4 }}>Product</div>
                  <select value={multiBaseCode} onChange={e => setMultiBaseCode(e.target.value)}
                    style={{ width: '100%', background: '#1e293b', color: '#fff',
                      border: '1px solid rgba(255,255,255,0.15)', borderRadius: 7,
                      padding: '8px 10px', fontSize: 13 }}>
                    <option value="">Select base plan...</option>
                    {productList.filter(p => p.product_type !== 'rider' && p.category !== 'RIDER').map(p => (
                      <option key={p.product_code} value={p.product_code}>
                        {p.product_code} — {p.name || p.product_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4 }}>Sum Assured (₹)</div>
                  <input type="number" value={multiFaceAmount}
                    onChange={e => setMultiFaceAmount(Number(e.target.value))}
                    style={{ width: '100%', background: '#1e293b', color: '#fff',
                      border: '1px solid rgba(255,255,255,0.15)', borderRadius: 7,
                      padding: '8px 10px', fontSize: 13 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4 }}>Term (Years)</div>
                  <input type="number" value={multiTermYrs}
                    onChange={e => setMultiTermYrs(Number(e.target.value))}
                    style={{ width: '100%', background: '#1e293b', color: '#fff',
                      border: '1px solid rgba(255,255,255,0.15)', borderRadius: 7,
                      padding: '8px 10px', fontSize: 13 }} />
                </div>
              </div>
            </div>

            {/* Riders */}
            <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 10, padding: '14px 16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#9ca3af',
                  textTransform: 'uppercase', letterSpacing: '0.08em' }}>Additional Benefits / Riders</div>
                <Button size="small" type="dashed"
                  onClick={() => setRiderLines([...riderLines,
                    { product_code: '', benefit_type: 'RIDER_ADB', face_amount: 500000, coverage_term_yrs: 20 }])}>
                  + Add Benefit / Rider
                </Button>
              </div>
              {riderLines.length === 0 && (
                <div style={{ fontSize: 12, color: '#4b5563', textAlign: 'center', padding: '10px 0' }}>
                  No additional benefits added. Click + Add Benefit / Rider to add a rider or a second base plan (e.g. Endowment, PA).
                </div>
              )}
              {riderLines.map((r, i) => (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr auto',
                  gap: 8, marginBottom: 8, alignItems: 'end' }}>
                  <div>
                    <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 3 }}>Rider Product</div>
                    <select value={r.product_code}
                      onChange={e => { const l=[...riderLines]; l[i]={...l[i],product_code:e.target.value}; setRiderLines(l); }}
                      style={{ width: '100%', background: '#1e293b', color: '#fff',
                        border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 8px', fontSize: 12 }}>
                      <option value="">Select rider...</option>
                      {productList.map(p => (
                        <option key={p.product_code} value={p.product_code}>
                          {p.product_code} — {p.name || p.product_name}
                          {(p.product_type === 'rider' || p.category === 'RIDER') ? ' (Rider)' : ' (Base)'}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 3 }}>Type</div>
                    <select value={r.benefit_type}
                      onChange={e => { const l=[...riderLines]; l[i]={...l[i],benefit_type:e.target.value}; setRiderLines(l); }}
                      style={{ width: '100%', background: '#1e293b', color: '#fff',
                        border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 8px', fontSize: 12 }}>
                      <optgroup label="Base Plans">
                        <option value="BASE">Base Plan</option>
                        <option value="BASE_ENDOW">Endowment</option>
                        <option value="BASE_WHOLELIFE">Whole Life</option>
                        <option value="BASE_PA">Personal Accident</option>
                      </optgroup>
                      <optgroup label="Riders">
                        <option value="RIDER_CI">Critical Illness</option>
                        <option value="RIDER_ADB">Accidental Death</option>
                        <option value="RIDER_WOP">Waiver of Premium</option>
                        <option value="RIDER_ATPD">ATPD</option>
                      </optgroup>
                    </select>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 3 }}>Sum Assured</div>
                    <input type="number" value={r.face_amount} placeholder="SA"
                      onChange={e => { const l=[...riderLines]; l[i]={...l[i],face_amount:Number(e.target.value)}; setRiderLines(l); }}
                      style={{ width: '100%', background: '#1e293b', color: '#fff',
                        border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 8px', fontSize: 12 }} />
                  </div>
                  <Button size="small" danger
                    onClick={() => setRiderLines(riderLines.filter((_,j)=>j!==i))}>✕</Button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Product selector — shown only in single mode */}
        {evalMode === 'single' && (
        <div style={{
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 12, padding: '16px 18px', marginBottom: 20,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--slate-500)', marginBottom: 10, textTransform: 'uppercase' }}>
            Product
          </div>
          <Select
            showSearch
            loading={prodLoading}
            value={selectedCode || undefined}
            onChange={handleProductChange}
            style={{ width: '100%' }}
            size="large"
            placeholder="Select a product…"
            optionFilterProp="label"
            options={productList.map((p) => ({
              value: p.product_code,
              label: `${p.product_code}  —  ${p.name ?? p.product_name ?? p.product_code}`,
            }))}
          />
          {prod && (
            <div style={{
              marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
            }}>
              <Tag color="blue" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                Ages {prod.min_age ?? '?'}–{prod.max_age ?? '?'}
              </Tag>
              <Tag color="purple" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                ₹{fmt(minFace)} – ₹{fmt(maxFace)}
              </Tag>
              {terms.length > 0 && (
                <Tag color="cyan" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  {terms.join(', ')} yr terms
                </Tag>
              )}
              {isGI && <Tag color="green">Guaranteed Issue</Tag>}
              {prod.uw_method && (
                <Tag style={{ fontSize: 11 }}>{prod.uw_method}</Tag>
              )}
            </div>
          )}
        </div>
        )}

        {/* Document Upload Panel */}
        <DocumentUploadPanel onExtracted={(fields) => {
          const formFields: Record<string, any> = {}
          if (fields.age !== undefined)              formFields.age = fields.age
          if (fields.gender)                         formFields.gender = fields.gender
          if (fields.state)                          formFields.state = fields.state
          if (fields.face_amount !== undefined)      formFields.face_amount = fields.face_amount
          if (fields.coverage_term_yrs !== undefined) formFields.term_yrs = fields.coverage_term_yrs
          if (fields.tobacco_status)                 formFields.tobacco_status = fields.tobacco_status
          if (fields.height_inches !== undefined)    formFields.height_inches = fields.height_inches
          if (fields.weight_lbs !== undefined)       formFields.weight_lbs = fields.weight_lbs
          if (fields.systolic_bp !== undefined)      formFields.systolic_bp = fields.systolic_bp
          if (fields.diastolic_bp !== undefined)     formFields.diastolic_bp = fields.diastolic_bp
          if (fields.diabetes_type)                  formFields.diabetes_type = fields.diabetes_type
          if (fields.heart_condition)                formFields.heart_condition = fields.heart_condition
          if (fields.annual_income !== undefined)    formFields.annual_income = fields.annual_income
          if (fields.existing_coverage !== undefined) formFields.existing_coverage = fields.existing_coverage
          if (fields.applicant_ref)                  formFields.applicant_ref = fields.applicant_ref
          if (fields.product_code)                   formFields.product_code = fields.product_code
          form.setFieldsValue(formFields)
        }}/>

        <Form
          form={form}
          layout="vertical"
          initialValues={{
            applicant_ref: 'APP-001',
            age: 40,
            gender: 'MALE',
            state: 'MH',
            face_amount: 500_000,
            term_yrs: terms[0] ?? 20,
            policy_eff: dayjs(),
            tobacco_status: 'NEVER',
            heart_condition: 'NONE',
            diabetes_type: 'NONE',
            use_build: true,
            height_inches: 68,
            weight_lbs: 170,
            use_bp: true,
            systolic: 120,
            diastolic: 78,
            bp_on_med: false,
            bp_med_cnt: 0,
            use_labs: false,
            occ_class: '1',
            occ_title: 'Software Engineer',
            annual_income: 800_000,
            existing_coverage: 0,
            dui_count: 0,
            major_vio: 0,
            alcohol_drinks_week: 0,
            hazardous_activity: false,
            fh_cardio: false,
            fh_stroke: false,
          }}
          requiredMark={false}
        >
          {/* ── APPLICANT ── */}
          <SectionLabel>Applicant</SectionLabel>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
            <Form.Item name="applicant_ref" label="Ref No." rules={[{ required: true }]}>
              <Input placeholder="APP-001" />
            </Form.Item>
            <Form.Item name="age" label="Age" rules={[{ required: true }]} help="Age at policy inception (1–100)">
              <InputNumber min={1} max={100} style={{ width: '100%' }} placeholder="e.g. 35" />
            </Form.Item>
            <Form.Item name="gender" label="Gender" help="Biological sex used for mortality rating">
              <Select placeholder="Select…">
                <Option value="MALE">Male</Option>
                <Option value="FEMALE">Female</Option>
              </Select>
            </Form.Item>
            <Form.Item name="state" label="State" help="Applicant's state of residence">
              <Select showSearch placeholder="Select state…">
                {['MH','DL','KA','TN','GJ','UP','WB','RJ','TS','AP','KL','MP',
                   'HR','PB','BR','OR','UK','HP','GA','AS','JK','CG','JH'].map(s => (
                  <Option key={s} value={s}>{s}</Option>
                ))}
              </Select>
            </Form.Item>
          </div>

          {/* ── APPLICANT NAME ── */}
          <SectionLabel>Applicant Name</SectionLabel>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <Form.Item name="first_name" label="First Name" rules={[{ required: true, message: 'First name required' }]}>
              <Input placeholder="e.g. Rahul" />
            </Form.Item>
            <Form.Item name="middle_name" label="Middle Name">
              <Input placeholder="Optional" />
            </Form.Item>
            <Form.Item name="last_name" label="Last Name" rules={[{ required: true, message: 'Last name required' }]}>
              <Input placeholder="e.g. Sharma" />
            </Form.Item>
          </div>

          {/* ── CONTACT DETAILS ── */}
          <SectionLabel>Contact Details</SectionLabel>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
            <Form.Item name="email" label="Email" rules={[{ type: 'email', message: 'Enter valid email' }]}
              style={{ gridColumn: 'span 2' }}>
              <Input placeholder="applicant@email.com" />
            </Form.Item>
            <Form.Item name="mobile" label="Mobile">
              <Input placeholder="+91 98765 43210" />
            </Form.Item>
            <Form.Item name="pincode" label="Pincode">
              <Input placeholder="400001" />
            </Form.Item>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Form.Item name="address_line1" label="Address Line 1">
              <Input placeholder="House/Flat No., Street" />
            </Form.Item>
            <Form.Item name="city" label="City">
              <Input placeholder="Mumbai" />
            </Form.Item>
          </div>

          {/* ── COVERAGE ── */}
          <SectionLabel>Coverage</SectionLabel>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
            <Form.Item
              name="face_amount" label="Face Amount (₹)"
              rules={[{ required: true }]}
              style={{ gridColumn: 'span 2' }}
              help="Sum assured — must be within product min/max limits"
            >
              <InputNumber
                min={minFace} max={maxFace} step={50_000}
                formatter={(v) => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v: any) => Number(v!.replace(/₹\s?|(,*)/g, '')) as any}
                style={{ width: '100%' }}
              />
            </Form.Item>
            <Form.Item name="premium_mode" label="Premium Mode" help="Payment frequency for premium collection">
              <Select placeholder="Select mode…" defaultValue="ANNUAL">
                <Option value="ANNUAL">Annual</Option>
                <Option value="HALF_YEARLY">Half Yearly</Option>
                <Option value="QUARTERLY">Quarterly</Option>
                <Option value="MONTHLY">Monthly</Option>
              </Select>
            </Form.Item>
            <Form.Item name="term_yrs" label="Term (years)" help="Policy duration in years">
              {terms.length > 0 ? (
                <Select>
                  {terms.map(t => <Option key={t} value={t}>{t} yr</Option>)}
                </Select>
              ) : (
                <Input value="Permanent" disabled />
              )}
            </Form.Item>
            <Form.Item name="policy_eff" label="Effective Date" help="Date from which coverage begins">
              <DatePicker style={{ width: '100%' }} format="DD-MMM-YYYY" />
            </Form.Item>
          </div>

          {!isGI && (
            <>
              {/* ── BUILD ── */}
              <SectionLabel>Build</SectionLabel>
              <Form.Item name="use_build" valuePropName="checked" style={{ marginBottom: 10 }}>
                <Checkbox style={{ color: 'var(--slate-300)', fontSize: 13 }}>
                  Enter height &amp; weight
                </Checkbox>
              </Form.Item>
              {useBuild && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                  <Form.Item name="height_inches" label="Height (inches)" help={'54–84 in (4\'6" to 7\')'}>
                    <InputNumber min={54} max={84} style={{ width: '100%' }} placeholder="e.g. 68" />
                  </Form.Item>
                  <Form.Item name="weight_lbs" label="Weight (lbs)" help="80–400 lbs">
                    <InputNumber min={80} max={400} style={{ width: '100%' }} placeholder="e.g. 165" />
                  </Form.Item>
                  <Form.Item label="BMI">
                    <div style={{
                      height: 32, background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.12)',
                      borderRadius: 6, display: 'flex', alignItems: 'center',
                      padding: '0 12px', fontFamily: 'var(--font-mono)',
                      fontSize: 15, color: 'var(--teal-400)', fontWeight: 600,
                    }}>
                      {heightVal && weightVal ? bmi(heightVal, weightVal) : '—'}
                    </div>
                  </Form.Item>
                </div>
              )}

              {/* ── TOBACCO ── */}
              <SectionLabel>Tobacco</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Form.Item name="tobacco_status" label="Status">
                  <Select>
                    {TOBACCO_OPTIONS.map(o => <Option key={o} value={o}>{o}</Option>)}
                  </Select>
                </Form.Item>
                {tobacco === 'NON_SMOKER' && (
                  <Form.Item name="tobacco_quit" label="Years since quit" help="How many years ago tobacco use stopped">
                    <InputNumber min={0} max={30} step={0.5} style={{ width: '100%' }} placeholder="e.g. 3" />
                  </Form.Item>
                )}
              </div>

              {/* ── BLOOD PRESSURE ── */}
              <SectionLabel>Blood Pressure</SectionLabel>
              <Form.Item name="use_bp" valuePropName="checked" style={{ marginBottom: 10 }}>
                <Checkbox style={{ color: 'var(--slate-300)', fontSize: 13 }}>
                  Enter blood pressure readings
                </Checkbox>
              </Form.Item>
              {useBP && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
                  <Form.Item name="systolic" label="Systolic" help="Upper reading in mmHg (80–220)">
                    <InputNumber min={80} max={220} style={{ width: '100%' }} placeholder="e.g. 120" />
                  </Form.Item>
                  <Form.Item name="diastolic" label="Diastolic" help="Lower reading in mmHg (50–140)">
                    <InputNumber min={50} max={140} style={{ width: '100%' }} placeholder="e.g. 80" />
                  </Form.Item>
                  <Form.Item name="bp_on_med" valuePropName="checked" label="On BP meds">
                    <Checkbox style={{ marginTop: 4 }} />
                  </Form.Item>
                  {bpMed && (
                    <Form.Item name="bp_med_cnt" label="# Meds" help="Number of BP medications currently taken">
                      <InputNumber min={0} max={5} style={{ width: '100%' }} placeholder="e.g. 1" />
                    </Form.Item>
                  )}
                </div>
              )}

              {/* ── DIABETES ── */}
              <SectionLabel>ICD-10 Diagnosis Codes</SectionLabel>
              <Icd10Lookup onChange={(codes, debits) => {
                setIcd10Codes(codes)
                setIcd10Debits(debits)
              }}/>
              {icd10Debits > 0 && (
                <div style={{ fontSize:12, color:'#f87171', marginBottom:12 }}>
                  ⚠️ ICD-10 codes add <strong>+{icd10Debits} debit points</strong> to this evaluation
                </div>
              )}
              <SectionLabel>Diabetes</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                <Form.Item name="diabetes_type" label="Type">
                  <Select>
                    {DIABETES_OPTIONS.map(o => <Option key={o} value={o}>{o}</Option>)}
                  </Select>
                </Form.Item>
                {diabetes !== 'NONE' && (
                  <>
                    <Form.Item name="diabetes_dx_age" label="Dx Age" help="Age at diagnosis">
                      <InputNumber min={1} max={100} style={{ width: '100%' }} placeholder="e.g. 42" />
                    </Form.Item>
                    <Form.Item name="a1c" label="A1c (%)" help="Latest HbA1c reading — ideally within 6 months (4–15%)">
                      <InputNumber min={4} max={15} step={0.1} style={{ width: '100%' }} placeholder="e.g. 7.2" />
                    </Form.Item>
                  </>
                )}
              </div>

              {/* ── CARDIAC ── */}
              <SectionLabel>Cardiac History</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Form.Item name="heart_condition" label="Condition">
                  <Select>
                    {CARDIAC_OPTIONS.map(o => <Option key={o} value={o}>{o.replace(/_/g, ' ')}</Option>)}
                  </Select>
                </Form.Item>
                {cardiac !== 'NONE' && (
                  <Form.Item name="heart_yrs" label="Years ago" initialValue={2} help="How many years ago the cardiac event occurred">
                    <InputNumber min={0} max={30} step={0.5} style={{ width: '100%' }} placeholder="e.g. 2" />
                  </Form.Item>
                )}
              </div>

              {/* ── MEDICAL FLAGS ── */}
              <SectionLabel>Medical Flags</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
                {[
                  ['hiv_positive',       'HIV+'],
                  ['cirrhosis',          'Cirrhosis'],
                  ['stroke_history',     'Stroke'],
                  ['kidney_disease',     'Kidney disease'],
                  ['depression_history', 'Depression'],
                  ['dep_hosp',           'Dep. hospitalised'],
                  ['epilepsy',           'Epilepsy'],
                  ['copd',               'COPD'],
                ].map(([name, label]) => (
                  <Form.Item key={name} name={name} valuePropName="checked" style={{ marginBottom: 0 }}>
                    <Checkbox style={{ color: 'var(--slate-300)', fontSize: 12 }}>{label}</Checkbox>
                  </Form.Item>
                ))}
              </div>

              {/* ── OCCUPATION ── */}
              <SectionLabel>Occupation</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
                <Form.Item name="occ_class" label="Class">
                  <Select>
                    {OCC_CLASSES.map(c => (
                      <Option key={c} value={c}>
                        Class {c}{c === 'D' ? ' — Declined' : ''}
                      </Option>
                    ))}
                  </Select>
                </Form.Item>
                <Form.Item name="occ_title" label="Job Title">
                  <Input placeholder="Software Engineer" />
                </Form.Item>
              </div>

              {/* ── DRIVING ── */}
              <SectionLabel>Driving Record</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Form.Item name="dui_count" label="DUI / DWI (last 5yr)" help="Number of drunk-driving convictions in the past 5 years">
                  <InputNumber min={0} max={5} style={{ width: '100%' }} placeholder="0" />
                </Form.Item>
                <Form.Item name="major_vio" label="Major violations (last 3yr)" help="Reckless driving, speeding 30+ over limit, etc.">
                  <InputNumber min={0} max={5} style={{ width: '100%' }} placeholder="0" />
                </Form.Item>
              </div>

              {/* ── LIFESTYLE ── */}
              <SectionLabel>Lifestyle</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Form.Item name="alcohol_drinks_week" label="Alcohol drinks / week" help="Standard drinks per week (1 drink = 30ml spirits / 150ml wine / 360ml beer)">
                  <InputNumber min={0} max={100} style={{ width: '100%' }} placeholder="e.g. 7" />
                </Form.Item>
                <Form.Item name="hazardous_activity" valuePropName="checked" label=" " style={{ paddingTop: 8 }}>
                  <Checkbox style={{ color: 'var(--slate-300)', fontSize: 13 }}>
                    Hazardous activity
                  </Checkbox>
                </Form.Item>
              </div>
              {isHazard && (
                <Form.Item name="hazard_types" label="Activity types">
                  <Select mode="multiple">
                    {HAZARD_TYPES.map(h => <Option key={h} value={h}>{h.replace(/_/g, ' ')}</Option>)}
                  </Select>
                </Form.Item>
              )}

              {/* ── LAB VALUES ── */}
              <SectionLabel>Lab Values</SectionLabel>
              <Form.Item name="use_labs" valuePropName="checked" style={{ marginBottom: 10 }}>
                <Checkbox style={{ color: 'var(--slate-300)', fontSize: 13 }}>
                  Enter lab results
                </Checkbox>
              </Form.Item>
              {useLabs && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
                  <Form.Item name="total_chol" label="Total Chol (mg/dL)" initialValue={190} help="Total cholesterol in mg/dL (100–400)">
                    <InputNumber min={100} max={400} style={{ width: '100%' }} placeholder="e.g. 190" />
                  </Form.Item>
                  <Form.Item name="hdl" label="HDL (mg/dL)" initialValue={55} help="Good cholesterol — higher is better (20–150)">
                    <InputNumber min={20} max={150} style={{ width: '100%' }} placeholder="e.g. 55" />
                  </Form.Item>
                  <Form.Item name="ldl" label="LDL (mg/dL)" initialValue={110} help="Bad cholesterol — lower is better (50–300)">
                    <InputNumber min={50} max={300} style={{ width: '100%' }} placeholder="e.g. 110" />
                  </Form.Item>
                  <Form.Item name="egfr" label="eGFR (mL/min)" initialValue={75} help="Estimated kidney filtration rate — normal &gt;60 (5–150)">
                    <InputNumber min={5} max={150} style={{ width: '100%' }} placeholder="e.g. 75" />
                  </Form.Item>
                </div>
              )}

              {/* ── FAMILY HISTORY ── */}
              <SectionLabel>Family History</SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
                <Form.Item name="fh_cardio" valuePropName="checked" style={{ marginBottom: 0 }}>
                  <Checkbox style={{ color: 'var(--slate-300)', fontSize: 12 }}>
                    CVD in parent / sibling before age 60
                  </Checkbox>
                </Form.Item>
                <Form.Item name="fh_stroke" valuePropName="checked" style={{ marginBottom: 0 }}>
                  <Checkbox style={{ color: 'var(--slate-300)', fontSize: 12 }}>
                    Stroke in parent / sibling before age 65
                  </Checkbox>
                </Form.Item>
              </div>
            </>
          )}

          {/* ── USER LABELS (premium formula inputs) ── */}
          {userLabels.length > 0 && (
            <>
              <SectionLabel>
                Premium Formula Inputs
                <Tooltip title="These fields are used by the product's premium formula. Fill in the values that apply to this proposal.">
                  <InfoCircleOutlined style={{ marginLeft: 6, color: 'var(--slate-500)', cursor: 'help' }} />
                </Tooltip>
              </SectionLabel>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {userLabels.map(ul => (
                  <Form.Item
                    key={ul.label_key}
                    name={`ul_${ul.label_key}`}
                    label={ul.label_name}
                    help={ul.description || undefined}
                  >
                    {ul.data_type === 'TEXT' ? (
                      <Input placeholder={ul.default_value || ul.label_name} />
                    ) : (
                      <InputNumber
                        style={{ width: '100%' }}
                        placeholder={ul.default_value || '0'}
                        min={0}
                        step={ul.data_type === 'PERCENTAGE' ? 0.1 : ul.data_type === 'CURRENCY' ? 1000 : 1}
                        formatter={v => ul.prefix ? `${ul.prefix} ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : ul.suffix ? `${v}${ul.suffix}` : `${v}`}
                        parser={(v: any) => Number(v!.replace(/[^\d.]/g, '')) as any}
                      />
                    )}
                  </Form.Item>
                ))}
              </div>
            </>
          )}

          {/* ── FINANCIAL ── */}
          <SectionLabel>Financial</SectionLabel>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Form.Item name="annual_income" label="Annual Income (₹)" help="Gross annual income — used for financial underwriting checks">
              <InputNumber
                min={0} step={50_000}
                formatter={(v) => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v: any) => Number(v!.replace(/₹\s?|(,*)/g, '')) as any}
                style={{ width: '100%' }}
              />
            </Form.Item>
            <Form.Item name="existing_coverage" label="Existing Coverage (₹)" help="Total life cover already in force across all policies">
              <InputNumber
                min={0} step={100_000}
                formatter={(v) => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v: any) => Number(v!.replace(/₹\s?|(,*)/g, '')) as any}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </div>

          {/* Submit */}
          <Divider />

          {/* Mode-aware submit button */}
          {evalMode === 'single' ? (
            <>
              <Button type="primary" size="large" block loading={submitting}
                onClick={handleSubmit} icon={<ThunderboltOutlined />}
                style={{ height: 52, fontSize: 16, fontWeight: 700,
                  letterSpacing: '0.02em', fontFamily: 'var(--font-display)' }}>
                Run Underwriting Evaluation
              </Button>
              <div style={{ textAlign: 'center', marginTop: 10, fontSize: 11,
                color: 'var(--slate-600)', fontFamily: 'var(--font-mono)' }}>
                POST /underwriting/evaluate · instant decision
              </div>
            </>
          ) : (
            <>
              <Button type="primary" size="large" block loading={submitting}
                disabled={!multiBaseCode}
                icon={<ThunderboltOutlined />}
                style={{ height: 52, fontSize: 16, fontWeight: 700,
                  letterSpacing: '0.02em', fontFamily: 'var(--font-display)',
                  background: multiBaseCode ? '#0f766e' : undefined }}
                onClick={async () => {
                  if (!multiBaseCode) { message.warning('Select a primary benefit first'); return; }
                  if (riderLines.filter(r => r.product_code).length === 0) {
                    message.warning('Add at least one additional benefit or rider. Use Single mode for a single benefit evaluation.');
                    return;
                  }
                  setSubmitting(true); setProposalResult(null);
                  try {
                    const v = form.getFieldsValue()
                    const token = localStorage.getItem('riskuw_token')
                    const benefits = [
                      { benefit_type: 'BASE', product_code: multiBaseCode,
                        face_amount: multiFaceAmount, coverage_term_yrs: multiTermYrs,
                        is_base_plan: true, benefit_label: multiBaseCode,
                        premium_mode: v.premium_mode || 'ANNUAL' },
                      ...riderLines.filter(r => r.product_code).map(r => ({
                        benefit_type: r.benefit_type, product_code: r.product_code,
                        face_amount: r.face_amount, coverage_term_yrs: r.coverage_term_yrs || 20,
                        // BASE* types are independent base plans, RIDER_* are linked riders
                        is_base_plan: r.benefit_type.startsWith('BASE'),
                        benefit_label: r.benefit_label || r.product_code,
                      }))
                    ]
                    const payload = {
                      proposal_ref: (v.applicant_ref || 'APP') + '-PROP-' + Date.now(),
                      applicant_ref: v.applicant_ref || 'APP-001',
                      age: v.age, gender: v.gender, state: v.state || 'MH',
                      annual_income: v.annual_income || 0,
                      existing_coverage: v.existing_coverage || 0,
                      tobacco_status: v.tobacco_status || 'NEVER',
                      height_inches: v.height_inches, weight_lbs: v.weight_lbs,
                      systolic_bp: v.systolic_bp, diastolic_bp: v.diastolic_bp,
                      diabetes_type: v.diabetes_type || 'NONE',
                      heart_condition: v.heart_condition || 'NONE',
                      occupation_class: v.occ_class || 1,
                      benefits,
                    }
                    const res = await fetch('/underwriting/evaluate-proposal', {
                      method: 'POST',
                      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
                      body: JSON.stringify(payload)
                    })
                    const data = await res.json()
                    if (data.detail) throw new Error(Array.isArray(data.detail)
                      ? data.detail.map((d:any) => d.msg).join(', ') : data.detail)
                    setProposalResult(data)
                    message.success('Proposal evaluated: ' + data.overall_status)
                  } catch(e: any) {
                    message.error(e.message || 'Proposal evaluation failed')
                  } finally { setSubmitting(false) }
                }}>
                Run Multi-Benefit Evaluation
              </Button>
              <div style={{ textAlign: 'center', marginTop: 10, fontSize: 11,
                color: 'var(--slate-600)', fontFamily: 'var(--font-mono)' }}>
                POST /underwriting/evaluate-proposal · base plan + riders
              </div>
            </>
          )}
        </Form>
      </div>

      {/* ── Right: Decision ── */}
      <div style={{
        flex: 1, padding: '28px 24px',
        overflow: 'hidden', display: 'flex', flexDirection: 'column',
      }}>
        <div style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
          color: 'var(--slate-500)', textTransform: 'uppercase',
          marginBottom: 14, flexShrink: 0,
        }}>
          Decision
          {result && (
            <span style={{ marginLeft: 10, fontFamily: 'var(--font-mono)', color: 'var(--slate-600)', textTransform: 'none' }}>
              · {appRef}
            </span>
          )}
        </div>
        <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          {evalMode === 'single' && (
            <>
              <DecisionCard result={result} loading={submitting} appRef={appRef} />
              <AIAssessmentPanel aiScore={aiResult} loading={aiLoading} />
            </>
          )}

          {evalMode === 'multi' && (
            <>
              {!proposalResult && !submitting && (
                <div style={{ textAlign: 'center', color: 'var(--slate-500)', marginTop: 80 }}>
                  <div style={{ fontSize: 40, marginBottom: 12 }}>📦</div>
                  <div style={{ fontSize: 14, marginBottom: 6 }}>Multi-Benefit Proposal</div>
                  <div style={{ fontSize: 12 }}>Select base plan and riders below, then click Run Multi-Benefit Evaluation</div>
                </div>
              )}
              {submitting && (
                <div style={{ textAlign: 'center', color: 'var(--slate-500)', marginTop: 80 }}>
                  <Spin size="large" />
                  <div style={{ fontSize: 13, marginTop: 16 }}>Evaluating all benefits...</div>
                </div>
              )}
              {proposalResult && (
                <div style={{ overflowY: 'auto' }}>
                  {/* Overall status */}
                  <div style={{
                    background: proposalResult.overall_status === 'ALL_APPROVED' ? 'rgba(34,197,94,0.08)' :
                      proposalResult.overall_status?.includes('PARTIAL') ? 'rgba(245,158,11,0.08)' : 'rgba(239,68,68,0.08)',
                    border: '1px solid ' + (proposalResult.overall_status === 'ALL_APPROVED' ? 'rgba(34,197,94,0.3)' :
                      proposalResult.overall_status?.includes('PARTIAL') ? 'rgba(245,158,11,0.3)' : 'rgba(239,68,68,0.3)'),
                    borderRadius: 10, padding: '14px 18px', marginBottom: 14, flexShrink: 0,
                  }}>
                    <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Proposal Outcome</div>
                    <div style={{ fontSize: 22, fontWeight: 800,
                      color: proposalResult.overall_status === 'ALL_APPROVED' ? '#22c55e' :
                        proposalResult.overall_status?.includes('PARTIAL') ? '#f59e0b' : '#ef4444' }}>
                      {proposalResult.overall_status?.replace(/_/g, ' ')}
                    </div>
                    <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                      Ref: {proposalResult.proposal_ref} &nbsp;·&nbsp; {proposalResult.benefit_count} benefits evaluated
                    </div>
                  </div>

                  {/* Benefits table */}
                  <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: 10, padding: '14px 16px', marginBottom: 14, flexShrink: 0 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--teal-400)', textTransform: 'uppercase',
                      letterSpacing: '0.08em', marginBottom: 10 }}>Benefit Decisions</div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                      <thead>
                        <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
                          {['Benefit', 'Outcome', 'Risk Class', 'Debits', 'Annual Premium'].map(h => (
                            <th key={h} style={{ padding: '7px 10px', textAlign: 'left', color: '#6b7280',
                              fontWeight: 600, borderBottom: '1px solid rgba(255,255,255,0.08)', fontSize: 11 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(proposalResult.benefits || []).map((b: any, i: number) => {
                          const color = b.outcome?.includes('APPROVED') ? '#22c55e' :
                            b.outcome?.includes('DECLINED') ? '#ef4444' : '#f59e0b'
                          return (
                            <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                              <td style={{ padding: '8px 10px' }}>
                                <Tag color={b.benefit_type === 'BASE' ? 'cyan' : 'blue'} style={{ fontSize: 10 }}>
                                  {b.benefit_type?.replace('RIDER_', '')}
                                </Tag>
                                <div style={{ fontSize: 10, color: '#6b7280', marginTop: 2 }}>{b.product_code}</div>
                              </td>
                              <td style={{ padding: '8px 10px' }}>
                                <span style={{ color, fontWeight: 700, fontSize: 11 }}>
                                  {b.outcome?.replace(/_/g, ' ')}
                                </span>
                                {b.linked_decline && (
                                  <Tag color="error" style={{ fontSize: 9, marginLeft: 4 }}>linked</Tag>
                                )}
                              </td>
                              <td style={{ padding: '8px 10px', color: '#9ca3af', fontSize: 11 }}>{b.risk_class || '—'}</td>
                              <td style={{ padding: '8px 10px', fontFamily: 'var(--font-mono)', fontSize: 11,
                                color: (b.net_debit_points || 0) > 150 ? '#f87171' : '#9ca3af' }}>
                                {b.net_debit_points ?? 0}
                              </td>
                              <td style={{ padding: '8px 10px', fontFamily: 'var(--font-mono)', color: '#00d4aa', fontWeight: 600 }}>
                                {b.annual_premium
                                  ? new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(b.annual_premium)
                                  : '—'}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                      <tfoot>
                        <tr style={{ background: 'rgba(0,212,170,0.05)', borderTop: '2px solid rgba(0,212,170,0.2)' }}>
                          <td colSpan={4} style={{ padding: '8px 10px', fontWeight: 700, color: '#e2e8f0', fontSize: 13 }}>
                            Total Annual Premium
                          </td>
                          <td style={{ padding: '8px 10px', fontFamily: 'var(--font-mono)', fontWeight: 700,
                            color: '#00d4aa', fontSize: 15 }}>
                            {proposalResult.total_annual_premium
                              ? new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(proposalResult.total_annual_premium)
                              : '—'}
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>

                  {/* Frequency breakdown */}
                  {(proposalResult.total_annual_premium || 0) > 0 && (
                    <div style={{ background: 'rgba(0,212,170,0.04)', borderRadius: 10, padding: '14px 16px',
                      border: '1px solid rgba(0,212,170,0.15)', marginBottom: 14, flexShrink: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: '#00d4aa', textTransform: 'uppercase',
                        letterSpacing: '0.08em', marginBottom: 10 }}>
                        Premium by Payment Frequency
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8 }}>
                        {[
                          { label: 'Annual',      value: proposalResult.total_annual_premium,       note: 'Best value' },
                          { label: 'Half-Yearly', value: proposalResult.total_annual_premium / 2,   note: 'x2 / year' },
                          { label: 'Quarterly',   value: proposalResult.total_annual_premium / 4,   note: 'x4 / year' },
                          { label: 'Monthly',     value: proposalResult.total_annual_premium / 12,  note: 'x12 / year' },
                        ].map(({ label, value, note }) => (
                          <div key={label} style={{ background: 'rgba(0,0,0,0.2)', borderRadius: 8,
                            padding: '10px 12px', textAlign: 'center' }}>
                            <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4 }}>{label}</div>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: '#00d4aa' }}>
                              {new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(Math.round(value))}
                            </div>
                            <div style={{ fontSize: 9, color: '#4b5563', marginTop: 2 }}>{note}</div>
                          </div>
                        ))}
                      </div>
                      <div style={{ marginTop: 8, fontSize: 10, color: '#4b5563', textAlign: 'right' }}>
                        * Approximate. GST and exact loading may vary by payment mode.
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* ── AI Assist Panel ── */}
        {result && (
          <div style={{
            flexShrink: 0, marginTop: 16,
            background: 'rgba(0,212,170,0.04)',
            border: '1px solid rgba(0,212,170,0.15)',
            borderRadius: 12, padding: '16px 18px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <span style={{ fontSize: 16 }}>🧠</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: '#00d4aa' }}>LLM Second Opinion</span>
              <span style={{ fontSize: 11, color: '#4b5563', marginLeft: 4 }}>Claude AI · Ollama · on-demand</span>
            </div>

            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <Select value={aiEngine} onChange={setAiEngine} size="small" style={{ flex: 1 }}>
                <Option value="claude">🧠 Claude AI (Anthropic)</Option>
                <Option value="ollama">🦙 Ollama LLM (Local)</Option>
              </Select>
              {aiEngine === 'ollama' && (
                <Select defaultValue="llava-llama3:latest" size="small" style={{ flex: 1 }}
                  onChange={v => setLastPayload((p: any) => ({ ...p, ollama_model: v }))}>
                  <Option value="llava-llama3:latest">llava-llama3 (8B)</Option>
                  <Option value="llava:latest">llava (7B)</Option>
                  <Option value="minicpm-v:latest">minicpm-v (7.6B)</Option>
                </Select>
              )}
              <Button size="small" type="primary" loading={aiLoading}
                style={{ background: '#065f46', borderColor: '#00d4aa', color: '#00d4aa', fontWeight: 600 }}
                onClick={async () => {
                  if (!lastPayload) return
                  setAiLoading(true); setAiResult(null)
                  try {
                    const token = localStorage.getItem('riskuw_token')
                    const r = await fetch('/underwriting/ai-score', {
                      method: 'POST',
                      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                      body: JSON.stringify({ ...lastPayload, engine: aiEngine }),
                    }).then(r => r.json())
                    setAiResult(r)
                  } catch(e: any) { message.error('AI scoring failed') }
                  finally { setAiLoading(false) }
                }}>
                Get AI Opinion
              </Button>
            </div>

            {aiLoading && (
              <div style={{ textAlign: 'center', padding: '12px 0', color: '#6b7280', fontSize: 12 }}>
                <Spin size="small" style={{ marginRight: 8 }}/>
                {aiEngine === 'claude' ? 'Asking Claude AI...' : 'Querying Ollama LLM...'}
              </div>
            )}

            {aiResult && !aiResult.error && (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                  <span style={{ fontSize: 22, fontWeight: 700, color: {
                    STANDARD: '#22c55e', SUBSTANDARD: '#f59e0b',
                    RATED: '#f97316', DECLINED: '#ef4444'
                  }[aiResult.risk_tier as string] || '#9ca3af' }}>
                    {aiResult.risk_tier}
                  </span>
                  <span style={{ fontSize: 12, color: '#6b7280' }}>
                    Risk Score: <strong style={{ color: '#e2e8f0' }}>{aiResult.risk_score}</strong>/100
                  </span>
                  <span style={{ fontSize: 12, color: '#6b7280' }}>
                    Confidence: <strong style={{ color: '#e2e8f0' }}>{Math.round((aiResult.confidence || 0) * 100)}%</strong>
                  </span>
                  <Tag style={{ marginLeft: 'auto', fontSize: 11, borderColor: 'rgba(0,212,170,0.3)', color: '#00d4aa' }}>
                    {aiResult.engine === 'xgboost' ? '⚡ XGBoost' : aiResult.engine === 'claude' ? '🧠 Claude' : `🦙 ${aiResult.model || 'Ollama'}`}
                  </Tag>
                </div>

                {aiResult.narrative && (
                  <div style={{ fontSize: 12, color: '#9ca3af', lineHeight: 1.6, marginBottom: 10,
                    background: 'rgba(255,255,255,0.03)', borderRadius: 6, padding: '8px 12px' }}>
                    {aiResult.narrative}
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                  {aiResult.primary_concerns?.length > 0 && (
                    <div>
                      <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Concerns</div>
                      {aiResult.primary_concerns.map((c: string, i: number) => (
                        <div key={i} style={{ fontSize: 11, color: '#f87171' }}>⚠ {c}</div>
                      ))}
                    </div>
                  )}
                  {aiResult.positive_factors?.length > 0 && (
                    <div>
                      <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Positives</div>
                      {aiResult.positive_factors.map((f: string, i: number) => (
                        <div key={i} style={{ fontSize: 11, color: '#22c55e' }}>✓ {f}</div>
                      ))}
                    </div>
                  )}
                </div>

                {aiResult.loading_suggestion && (
                  <div style={{ fontSize: 11, color: '#6b7280', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 8 }}>
                    💡 <strong style={{ color: '#9ca3af' }}>Loading:</strong> {aiResult.loading_suggestion}
                  </div>
                )}
              </div>
            )}

            {aiResult?.error && (
              <div style={{ fontSize: 12, color: '#f87171', background: 'rgba(239,68,68,0.07)',
                border: '1px solid rgba(239,68,68,0.2)', borderRadius: 6, padding: '8px 12px' }}>
                ❌ {aiResult.error}
              </div>
            )}
          </div>
        )}
      </div>
        </div>
      ),
    },
    {
      key: 'session',
      label: <span>📊 Session Analytics</span>,
      children: <div style={{ padding: '24px 32px' }}><SessionAnalyticsTab cases={sessionCases}/></div>,
    },
    {
      key: 'platform',
      label: <span>📈 Platform Analytics</span>,
      children: <div style={{ padding: '24px 32px' }}><PlatformAnalyticsTab/></div>,
    },
  ]

  return (
    <div style={{ height: 'calc(100vh - 56px)', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={workbenchTabs}
        style={{ flex: 1, overflow: 'auto' }}
        tabBarStyle={{
          padding: '0 32px',
          borderBottom: '1px solid rgba(255,255,255,0.07)',
          marginBottom: 0,
          background: 'rgba(0,0,0,0.2)',
        }}
      />
    </div>
  )
}

