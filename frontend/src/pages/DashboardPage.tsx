import { useEffect, useState } from 'react'
import { Spin } from 'antd'
import {
  ThunderboltOutlined, CheckCircleOutlined,
  CloseCircleOutlined, SwapOutlined,
} from '@ant-design/icons'
import { uwAPI } from '../api/client'
import type { QueueCase } from '../types'
import { useNavigate } from 'react-router-dom'

const METRIC_ICONS: Record<string, React.ReactNode> = {
  total:    <ThunderboltOutlined />,
  approved: <CheckCircleOutlined />,
  declined: <CloseCircleOutlined />,
  referred: <SwapOutlined />,
}

interface Metrics {
  total: number; approved: number; declined: number;
  referred: number; stp_rate: number;
}

function MetricCard({ label, value, icon, color }: {
  label: string; value: string | number; icon: React.ReactNode; color: string
}) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 14, padding: '22px 24px',
      display: 'flex', alignItems: 'center', gap: 18,
    }}>
      <div style={{
        width: 48, height: 48, borderRadius: 12,
        background: `${color}18`,
        border: `1.5px solid ${color}30`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 20, color,
      }}>
        {icon}
      </div>
      <div>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 26,
          fontWeight: 700, color: '#fff', lineHeight: 1,
        }}>
          {value}
        </div>
        <div style={{ fontSize: 12, color: 'var(--slate-500)', marginTop: 5 }}>{label}</div>
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const [cases, setCases] = useState<QueueCase[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    uwAPI.getCases(100)
      .then((r) => {
        const data = Array.isArray(r.data) ? r.data : (r.data.cases ?? r.data.items ?? [])
        setCases(data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const metrics: Metrics = {
    total:    cases.length,
    approved: cases.filter(c => c.outcome?.includes('APPROVED')).length,
    declined: cases.filter(c => c.outcome?.includes('DECLIN')).length,
    referred: cases.filter(c => c.outcome?.includes('REFER')).length,
    stp_rate: cases.length
      ? Math.round((cases.filter(c => c.outcome?.includes('APPROVED')).length / cases.length) * 100)
      : 0,
  }

  const recent = [...cases].reverse().slice(0, 8)

  return (
    <div style={{ padding: '32px 36px', maxWidth: 1100 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{
          fontFamily: 'var(--font-display)', fontWeight: 700,
          fontSize: 22, color: '#fff', margin: 0, letterSpacing: '-0.02em',
        }}>
          Dashboard
        </h1>
        <p style={{ color: 'var(--slate-500)', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          Platform overview · live from API
        </p>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}>
          <Spin size="large" />
        </div>
      ) : (
        <>
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 16, marginBottom: 32,
          }}>
            <MetricCard label="Total Decisions" value={metrics.total} icon={<ThunderboltOutlined />} color="#00d4aa" />
            <MetricCard label="Approved" value={metrics.approved} icon={<CheckCircleOutlined />} color="#22c55e" />
            <MetricCard label="Declined" value={metrics.declined} icon={<CloseCircleOutlined />} color="#ef4444" />
            <MetricCard label="Referred" value={metrics.referred} icon={<SwapOutlined />} color="#fbbf24" />
          </div>

          {/* STP rate bar */}
          <div style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 14, padding: '20px 24px', marginBottom: 28,
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12,
            }}>
              <span style={{ fontSize: 13, color: 'var(--slate-300)', fontWeight: 500 }}>
                Approval / STP rate
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 20,
                fontWeight: 700, color: '#00d4aa',
              }}>
                {metrics.stp_rate}%
              </span>
            </div>
            <div style={{ height: 8, background: 'rgba(255,255,255,0.07)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{
                height: '100%', width: `${metrics.stp_rate}%`,
                background: 'linear-gradient(90deg, #00d4aa, #22c55e)',
                borderRadius: 4, transition: 'width 1s ease',
              }} />
            </div>
          </div>

          {/* Recent cases */}
          {recent.length > 0 && (
            <div style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: 14, overflow: 'hidden',
            }}>
              <div style={{
                padding: '16px 22px', borderBottom: '1px solid rgba(255,255,255,0.07)',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                <span style={{ fontWeight: 600, color: '#fff', fontSize: 14 }}>Recent Decisions</span>
                <button
                  onClick={() => navigate('/cases')}
                  style={{
                    background: 'none', border: 'none', color: 'var(--teal-400)',
                    cursor: 'pointer', fontSize: 12,
                  }}
                >
                  View all →
                </button>
              </div>
              {recent.map((c, i) => {
                const oc = c.outcome ?? '—'
                const col = oc.includes('APPROVED') ? '#22c55e'
                  : oc.includes('DECLIN') ? '#ef4444'
                  : oc.includes('REFER') ? '#fbbf24' : '#c084fc'
                return (
                  <div key={c.id ?? i} style={{
                    display: 'flex', alignItems: 'center',
                    padding: '11px 22px',
                    borderBottom: i < recent.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                    gap: 16,
                  }}>
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%', background: col, flexShrink: 0,
                    }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, color: '#fff', fontWeight: 500 }}>
                        {c.applicant_ref ?? c.id}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--slate-500)' }}>
                        {c.product_code} · ₹{c.face_amount ? new Intl.NumberFormat('en-IN').format(c.face_amount) : '—'}
                      </div>
                    </div>
                    <span style={{
                      fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
                      color: col, letterSpacing: '0.06em',
                    }}>
                      {oc}
                    </span>
                  </div>
                )
              })}
            </div>
          )}

          {/* CTA */}
          <div style={{
            marginTop: 24, display: 'flex', justifyContent: 'center',
          }}>
            <button
              onClick={() => navigate('/evaluate')}
              style={{
                background: 'rgba(0,212,170,0.1)',
                border: '1.5px solid rgba(0,212,170,0.3)',
                borderRadius: 10, padding: '12px 28px',
                color: 'var(--teal-400)', cursor: 'pointer',
                fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 14,
                display: 'flex', alignItems: 'center', gap: 8,
              }}
            >
              <ThunderboltOutlined /> Evaluate a new application
            </button>
          </div>
        </>
      )}
    </div>
  )
}
