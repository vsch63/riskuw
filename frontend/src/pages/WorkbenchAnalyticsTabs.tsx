/**
 * WorkbenchAnalyticsTabs.tsx
 * ──────────────────────────
 * Drop-in Session Analytics + Platform Analytics tabs for the UW Workbench.
 *
 * USAGE — add to your existing workbench page tabs array:
 *
 *   import { SessionAnalyticsTab, PlatformAnalyticsTab } from './WorkbenchAnalyticsTabs'
 *
 *   // in your tabs array:
 *   { key: 'session',  label: '📊 Session Analytics',  children: <SessionAnalyticsTab cases={sessionCases}/> },
 *   { key: 'platform', label: '📈 Platform Analytics',  children: <PlatformAnalyticsTab/> },
 *
 * WHERE sessionCases is the array of evaluated cases from your workbench state.
 */

import { useEffect, useState } from 'react'
import { Button, Spin, Table } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import {
  PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, LineChart, Line,
} from 'recharts'

// ── Types ──────────────────────────────────────────────────────────────────────
export interface SessionCase {
  Ref?:     string; ref?: string; applicant_ref?: string; case_number?: string
  Outcome?: string; outcome?: string
  Pathway?: string; pathway?: string; decision_pathway?: string
  Debits?:  number; net_debit_points?: number
  Product?: string; product_code?: string
  ms?:      number; decision_cycle_ms?: number
}

interface AnalyticsData {
  period?:       { from: string; to: string }
  outcomes?:     { outcome: string; count: number; uw_pathway?: string; avg_ms?: number }[]
  trend?:        { day: string; total: number; approved: number; declined: number }[]
  risk_classes?: { risk_class: string; count: number }[]
  top_rules?:    { rule_code: string; fire_count: number }[]
  sla?:          { open_cases: number; breached: number; avg_sla_hours: number }
  batch?:        { total_jobs: number; total_records: number; total_processed: number; error?: string }
}

// ── Colors ─────────────────────────────────────────────────────────────────────
const OUTCOME_COLORS = ['#10b981','#ef4444','#f59e0b','#818cf8','#64748b','#06b6d4','#f97316','#a3e635']

// ── Styles ─────────────────────────────────────────────────────────────────────
const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 10, padding: '20px 24px', marginBottom: 16,
}
const secTitle: React.CSSProperties = {
  fontSize: 12, fontWeight: 700, color: '#9ca3af', marginBottom: 16,
}
const statBlock: React.CSSProperties = {
  background: 'rgba(255,255,255,0.025)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 8, padding: '14px 16px',
}

// ══════════════════════════════════════════════════════════════════════════════
// Session Analytics Tab
// ══════════════════════════════════════════════════════════════════════════════
export function SessionAnalyticsTab({ cases }: { cases: SessionCase[] }) {
  // Normalise cases to consistent shape
  const rows = cases.map(c => ({
    ref:     c.Ref || c.ref || c.applicant_ref || c.case_number || '—',
    outcome: c.Outcome || c.outcome || '—',
    pathway: c.Pathway || c.pathway || c.decision_pathway || '—',
    debits:  c.Debits ?? c.net_debit_points ?? 0,
    product: c.Product || c.product_code || '—',
    ms:      c.ms || c.decision_cycle_ms || 0,
  }))

  if (rows.length === 0) {
    return (
      <div style={{ color:'#6b7280', fontSize:13, padding:'24px 0' }}>
        Submit evaluations to see analytics, or visit the Case History tab to load from database.
      </div>
    )
  }

  const total    = rows.length
  const approved = rows.filter(r => r.outcome.includes('APPROVED')).length
  const declined = rows.filter(r => r.outcome.includes('DECLIN')).length
  const stp      = rows.filter(r => /STRAIGHT_THROUGH|INSTANT/i.test(r.pathway)).length
  const stpRate  = `${Math.round(stp / total * 100)}%`
  const avgMs    = rows.length > 0 ? Math.round(rows.reduce((s,r) => s + (r.ms||0), 0) / rows.length) : 0

  // Outcome pie data
  const outcomeCounts: Record<string,number> = {}
  rows.forEach(r => { outcomeCounts[r.outcome] = (outcomeCounts[r.outcome]||0) + 1 })
  const pieData = Object.entries(outcomeCounts).map(([name,value]) => ({ name, value }))

  // Debits bar data
  const barData = rows.map(r => ({ name: r.ref.slice(0,12), debits: r.debits, product: r.product }))

  return (
    <div>
      {/* KPI row */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:12, marginBottom:24 }}>
        {[
          { label:'Total Evaluated', value:total,    color:'#00d4aa' },
          { label:'Approved',        value:approved, color:'#22c55e' },
          { label:'Declined',        value:declined, color:'#ef4444' },
          { label:'STP Rate',        value:stpRate,  color:'#3b82f6' },
          { label:'Avg Decision',    value:avgMs ? `${avgMs}ms` : '—', color:'#9ca3af' },
        ].map(s => (
          <div key={s.label} style={statBlock}>
            <div style={{ fontSize:22, fontWeight:700, color:s.color }}>{s.value}</div>
            <div style={{ fontSize:11, color:'#6b7280', marginTop:3 }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
        {/* Decision Outcomes pie */}
        <div style={card}>
          <div style={secTitle}>Decision Outcomes</div>
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100}
                label={({ name, percent }: { name?: string; percent?: number }) => `${(name ?? '').slice(0,12)} ${((percent ?? 0)*100).toFixed(1)}%`}
                labelLine={false}>
                {pieData.map((_, i) => <Cell key={i} fill={OUTCOME_COLORS[i % OUTCOME_COLORS.length]}/>)}
              </Pie>
              <Tooltip contentStyle={{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8 }}/>
              <Legend wrapperStyle={{ fontSize:11, color:'#9ca3af' }}/>
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Net Debit Points bar */}
        <div style={card}>
          <div style={secTitle}>Net Debit Points by Application</div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={barData} margin={{ top:5, right:10, bottom:20, left:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)"/>
              <XAxis dataKey="name" tick={{ fill:'#6b7280', fontSize:10 }} angle={-30} textAnchor="end"/>
              <YAxis tick={{ fill:'#6b7280', fontSize:11 }}/>
              <Tooltip contentStyle={{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8 }}/>
              <Bar dataKey="debits" fill="#818cf8" radius={[4,4,0,0]}/>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Detailed table */}
      <div style={card}>
        <div style={secTitle}>Session Details ({total} evaluations)</div>
        <Table
          dataSource={rows} rowKey="ref" size="small"
          pagination={{ pageSize:10, showSizeChanger:false }}
          columns={[
            { title:'Ref',     dataIndex:'ref',     width:160 },
            { title:'Outcome', dataIndex:'outcome', render:(v:string) => (
              <span style={{ color: v.includes('APPROVED') ? '#22c55e' : v.includes('DECLIN') ? '#ef4444' : '#f59e0b', fontWeight:600, fontSize:12 }}>{v}</span>
            )},
            { title:'Product', dataIndex:'product', width:130 },
            { title:'Debits',  dataIndex:'debits',  width:80,
              render:(v:number) => <span style={{ fontFamily:'var(--font-mono,monospace)', color: v > 150 ? '#ef4444' : v > 75 ? '#f59e0b' : '#9ca3af' }}>{v}</span> },
            { title:'Pathway', dataIndex:'pathway', width:180, render:(v:string) => <span style={{ fontSize:11, color:'#6b7280' }}>{v}</span> },
            { title:'Time',    dataIndex:'ms',      width:80,  render:(v:number) => v ? <span style={{ fontSize:11, color:'#6b7280' }}>{v}ms</span> : '—' },
          ]}
        />
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Platform Analytics Tab
// ══════════════════════════════════════════════════════════════════════════════
export function PlatformAnalyticsTab() {
  const today   = new Date().toISOString().slice(0,10)
  const month30 = new Date(Date.now() - 30*24*60*60*1000).toISOString().slice(0,10)

  const [dateFrom, setFrom]   = useState(month30)
  const [dateTo, setTo]       = useState(today)
  const [data, setData]       = useState<AnalyticsData|null>(null)
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded]   = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get('/analytics/summary', {
        params: { date_from: dateFrom, date_to: dateTo }
      })
      setData(r.data)
    } catch(e:any) {
      // Try alternative endpoint
      try {
        const r2 = await api.get('/underwriting/analytics', {
          params: { date_from: dateFrom, date_to: dateTo }
        })
        setData(r2.data)
      } catch {
        setData(null)
      }
    }
    finally { setLoading(false); setLoaded(true) }
  }

  // KPIs
  const outcomes   = data?.outcomes || []
  const total      = outcomes.reduce((s,o) => s + o.count, 0)
  const approved   = outcomes.filter(o => o.outcome?.startsWith('APPROVED')).reduce((s,o) => s + o.count, 0)
  const declined   = outcomes.filter(o => o.outcome?.startsWith('DECLIN')).reduce((s,o) => s + o.count, 0)
  const stpCount   = outcomes.filter(o => ['STRAIGHT_THROUGH','INSTANT_DECLINE'].includes(o.uw_pathway||'')).reduce((s,o) => s + o.count, 0)
  const stpRate    = total ? `${Math.round(stpCount/total*100)}%` : '—'
  const avgMs      = total ? outcomes.reduce((s,o) => s + (o.avg_ms||0)*o.count, 0) / total : 0

  // Pie data
  const pieData = outcomes.map(o => ({ name: o.outcome, value: o.count }))

  // Trend
  const trend = data?.trend || []
  const riskClasses = (data?.risk_classes || []).map(r => ({ name: r.risk_class, count: r.count }))
  const topRules    = (data?.top_rules || []).slice(0,10).map(r => ({ name: r.rule_code, count: r.fire_count }))

  return (
    <div>
      <div style={{ fontSize:14, fontWeight:700, color:'#e2e8f0', marginBottom:16 }}>
        📈 Platform Analytics Dashboard
      </div>

      {/* Date range + load */}
      <div style={{ display:'flex', gap:12, alignItems:'flex-end', marginBottom:16 }}>
        <div>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>From</div>
          <input type="date" value={dateFrom} onChange={e => setFrom(e.target.value)}
            style={{ background:'rgba(255,255,255,0.04)', border:'1px solid rgba(255,255,255,0.1)', borderRadius:6, padding:'6px 10px', color:'#e2e8f0', fontSize:13 }}/>
        </div>
        <div>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>To</div>
          <input type="date" value={dateTo} onChange={e => setTo(e.target.value)}
            style={{ background:'rgba(255,255,255,0.04)', border:'1px solid rgba(255,255,255,0.1)', borderRadius:6, padding:'6px 10px', color:'#e2e8f0', fontSize:13 }}/>
        </div>
        <Button type="primary" icon={<ReloadOutlined/>} loading={loading} onClick={load}>
          Load Analytics
        </Button>
      </div>

      {!loaded && !loading && (
        <div style={{ color:'#6b7280', fontSize:13 }}>Click <strong style={{ color:'#e2e8f0' }}>Load Analytics</strong> to fetch platform data.</div>
      )}

      {loading && <Spin/>}

      {loaded && !loading && !data && (
        <div style={{ color:'#f87171', fontSize:13 }}>
          Could not load analytics — check that the <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#fbbf24' }}>/analytics/summary</code> endpoint is available.
        </div>
      )}

      {data && !loading && (
        <>
          {/* Period label */}
          {data.period && (
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:16 }}>
              Period: {data.period.from} → {data.period.to}
            </div>
          )}

          {/* KPI row */}
          <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:12, marginBottom:24 }}>
            {[
              { label:'Total Cases',  value:total.toLocaleString(),          color:'#00d4aa' },
              { label:'Approved',     value:approved.toLocaleString(),        color:'#22c55e' },
              { label:'Declined',     value:declined.toLocaleString(),        color:'#ef4444' },
              { label:'STP Rate',     value:stpRate,                          color:'#3b82f6' },
              { label:'Avg Decision', value:avgMs ? `${Math.round(avgMs)}ms` : '—', color:'#9ca3af' },
            ].map(s => (
              <div key={s.label} style={statBlock}>
                <div style={{ fontSize:22, fontWeight:700, color:s.color }}>{s.value}</div>
                <div style={{ fontSize:11, color:'#6b7280', marginTop:3 }}>{s.label}</div>
              </div>
            ))}
          </div>

          {/* Row 1: Pie + Trend */}
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20, marginBottom:20 }}>
            <div style={card}>
              <div style={secTitle}>Decision Outcomes</div>
              {pieData.length === 0
                ? <div style={{ color:'#6b7280', fontSize:13 }}>No outcome data</div>
                : <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100}>
                        {pieData.map((_, i) => <Cell key={i} fill={OUTCOME_COLORS[i % OUTCOME_COLORS.length]}/>)}
                      </Pie>
                      <Tooltip contentStyle={{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8 }}/>
                      <Legend wrapperStyle={{ fontSize:11, color:'#9ca3af' }}/>
                    </PieChart>
                  </ResponsiveContainer>
              }
            </div>

            <div style={card}>
              <div style={secTitle}>Daily Volume Trend</div>
              {trend.length === 0
                ? <div style={{ color:'#6b7280', fontSize:13 }}>No trend data</div>
                : <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={trend} margin={{ top:5, right:10, bottom:20, left:0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)"/>
                      <XAxis dataKey="day" tick={{ fill:'#6b7280', fontSize:9 }} angle={-30} textAnchor="end"/>
                      <YAxis tick={{ fill:'#6b7280', fontSize:11 }}/>
                      <Tooltip contentStyle={{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8 }}/>
                      <Legend wrapperStyle={{ fontSize:11, color:'#9ca3af' }}/>
                      <Bar dataKey="total" fill="#818cf8" name="Total"/>
                      <Line type="monotone" dataKey="approved" stroke="#10b981" strokeWidth={2} name="Approved" dot={false}/>
                      <Line type="monotone" dataKey="declined" stroke="#ef4444" strokeWidth={2} name="Declined" dot={false}/>
                    </BarChart>
                  </ResponsiveContainer>
              }
            </div>
          </div>

          {/* Row 2: Risk class + Top rules */}
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20, marginBottom:20 }}>
            <div style={card}>
              <div style={secTitle}>Risk Class Distribution</div>
              {riskClasses.length === 0
                ? <div style={{ color:'#6b7280', fontSize:13 }}>No risk class data</div>
                : <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={riskClasses} margin={{ top:5, right:10, bottom:20, left:0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)"/>
                      <XAxis dataKey="name" tick={{ fill:'#6b7280', fontSize:10 }} angle={-20} textAnchor="end"/>
                      <YAxis tick={{ fill:'#6b7280', fontSize:11 }}/>
                      <Tooltip contentStyle={{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8 }}/>
                      <Bar dataKey="count" radius={[4,4,0,0]}>
                        {riskClasses.map((_, i) => <Cell key={i} fill={`hsl(${210 + i*15},70%,${55-i*4}%)`}/>)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
              }
            </div>

            <div style={card}>
              <div style={secTitle}>Top Fired Rules</div>
              {topRules.length === 0
                ? <div style={{ background:'rgba(59,130,246,0.06)', border:'1px solid rgba(59,130,246,0.15)', borderRadius:8, padding:'10px 14px', fontSize:13, color:'#9ca3af' }}>
                    No rule firing data for this period
                  </div>
                : <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={topRules} layout="vertical" margin={{ top:5, right:30, bottom:5, left:60 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)"/>
                      <XAxis type="number" tick={{ fill:'#6b7280', fontSize:11 }}/>
                      <YAxis dataKey="name" type="category" tick={{ fill:'#9ca3af', fontSize:10 }} width={55}/>
                      <Tooltip contentStyle={{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.1)', borderRadius:8 }}/>
                      <Bar dataKey="count" fill="#f97316" radius={[0,4,4,0]}/>
                    </BarChart>
                  </ResponsiveContainer>
              }
            </div>
          </div>

          {/* Row 3: SLA + Batch */}
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20 }}>
            <div style={card}>
              <div style={secTitle}>SLA Performance</div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12 }}>
                {[
                  { label:'Open Cases',     value:data.sla?.open_cases ?? 0,                  color:'#00d4aa' },
                  { label:'SLA Breached',   value:data.sla?.breached ?? 0,                    color:(data.sla?.breached||0) > 0 ? '#ef4444' : '#22c55e' },
                  { label:'Avg SLA Hours',  value:data.sla ? `${(data.sla.avg_sla_hours||0).toFixed(1)}h` : '—', color:'#9ca3af' },
                ].map(s => (
                  <div key={s.label} style={statBlock}>
                    <div style={{ fontSize:18, fontWeight:700, color:s.color }}>{s.value}</div>
                    <div style={{ fontSize:11, color:'#6b7280', marginTop:2 }}>{s.label}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={card}>
              <div style={secTitle}>Batch Job Stats</div>
              {data.batch?.error
                ? <div style={{ color:'#fbbf24', fontSize:13 }}>⚠ {data.batch.error}</div>
                : <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12 }}>
                    {[
                      { label:'Total Jobs',  value:(data.batch?.total_jobs||0).toLocaleString(),      color:'#00d4aa' },
                      { label:'Records',     value:(data.batch?.total_records||0).toLocaleString(),   color:'#9ca3af' },
                      { label:'Processed',   value:(data.batch?.total_processed||0).toLocaleString(), color:'#22c55e' },
                    ].map(s => (
                      <div key={s.label} style={statBlock}>
                        <div style={{ fontSize:18, fontWeight:700, color:s.color }}>{s.value}</div>
                        <div style={{ fontSize:11, color:'#6b7280', marginTop:2 }}>{s.label}</div>
                      </div>
                    ))}
                  </div>
              }
            </div>
          </div>
        </>
      )}
    </div>
  )
}
