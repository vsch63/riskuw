import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Select, Spin, Tabs, Badge, Switch,
  message, Input, Collapse, Modal, Form,
} from 'antd'
import { Titled } from '../components/ColHint'
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  ClockCircleOutlined, SafetyCertificateOutlined, ReloadOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'

const { Option } = Select
const { Panel } = Collapse

const _tok = () => localStorage.getItem('riskuw_token') || ''
const intApi = {
  get: (path: string, params?: any) => {
    const url = params ? `${path}?${new URLSearchParams(params)}` : path
    return fetch(url, { headers: { Authorization: `Bearer ${_tok()}` } }).then(r => r.json())
  },
  post: (path: string, body?: any) =>
    fetch(path, { method: 'POST', headers: { Authorization: `Bearer ${_tok()}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json()),
  patch: (path: string, body?: any) =>
    fetch(path, { method: 'PATCH', headers: { Authorization: `Bearer ${_tok()}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json()),
}

const COUNTRIES = [
  { code: 'IN', flag: '🇮🇳', name: 'India' },
  { code: 'AE', flag: '🇦🇪', name: 'UAE' },
  { code: 'SG', flag: '🇸🇬', name: 'Singapore' },
  { code: 'GB', flag: '🇬🇧', name: 'United Kingdom' },
  { code: 'US', flag: '🇺🇸', name: 'United States' },
]

// ── Type colours / icons ───────────────────────────────────────────────────
const TYPE_META: Record<string, { icon: string; label: string; color: string }> = {
  IDENTITY: { icon: '🪪', label: 'Identity / KYC',    color: '#60a5fa' },
  CREDIT:   { icon: '💳', label: 'Credit / CIBIL',    color: '#fbbf24' },
  LAB:      { icon: '🧪', label: 'Lab / Diagnostics', color: '#34d399' },
  AML:      { icon: '🛡️', label: 'AML / Sanctions',   color: '#c084fc' },
  PHARMACY: { icon: '💊', label: 'Pharmacy DB',        color: '#f97316' },
  DRIVING:  { icon: '🚗', label: 'Driving Record',     color: '#94a3b8' },
}

// ══════════════════════════════════════════════════════════════════════════════
// Provider Config Tab
// ══════════════════════════════════════════════════════════════════════════════
function ProviderConfigTab() {
  const [providers, setProviders] = useState<any[]>([])
  const [loading, setLoading]     = useState(true)
  const [editModal, setEditModal] = useState<any>(null)
  const [countryF, setCountryF]   = useState('ALL')
  const [tenantCtx, setTenantCtx] = useState<any>(null)
  const [form]                    = Form.useForm()

  useEffect(() => {
    intApi.get('/integrations/tenant-context').then(d => setTenantCtx(d)).catch(() => {})
  }, [])

  const load = () => {
    setLoading(true)
    intApi.get('/integrations/providers', countryF !== 'ALL' ? { country_code: countryF } : undefined)
      .then(d => setProviders(Array.isArray(d) ? d : []))
      .catch(() => setProviders([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [countryF])

  // Default-filter to tenant's operating countries unless user explicitly broadens
  const operatingCodes: string[] = tenantCtx?.operating_countries || []
  const visibleProviders = countryF === 'ALL' && operatingCodes.length
    ? providers.filter(p => operatingCodes.includes(p.country_code))
    : providers

  const toggleEnabled = async (provider: any, val: boolean) => {
    try {
      await intApi.patch(`/integrations/config/${provider.id}`, { is_enabled: val })
      message.success(`${provider.provider_name} ${val ? 'enabled' : 'disabled'}`)
      load()
    } catch { message.error('Update failed') }
  }

  const saveEdit = async () => {
    const v = form.getFieldsValue()
    try {
      await intApi.patch(`/integrations/config/${editModal.id}`, {
        is_enabled:   v.is_enabled,
        api_endpoint: v.api_endpoint || undefined,
        api_key:      v.api_key      || undefined,
      })
      message.success('Provider updated')
      setEditModal(null)
      load()
    } catch { message.error('Save failed') }
  }

  const grouped = visibleProviders.reduce((acc: any, p: any) => {
    const key = `${p.country_code}__${p.integration_type}`
    ;(acc[key] = acc[key] || { country: p.country_code, type: p.integration_type, items: [] }).items.push(p)
    return acc
  }, {})

  const countryName = (code: string) => COUNTRIES.find(c => c.code === code)?.name || code
  const countryFlag = (code: string) => COUNTRIES.find(c => c.code === code)?.flag || '🌍'

  // Group by country first
  const byCountry: Record<string, any[]> = {}
  Object.values(grouped).forEach((g: any) => {
    ;(byCountry[g.country] = byCountry[g.country] || []).push(g)
  })

  const card: React.CSSProperties = {
    background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)',
    borderRadius: 10, padding: '14px 18px', marginBottom: 10,
    display: 'flex', alignItems: 'center', gap: 16,
  }

  return (
    <div>
      {countryF === 'ALL' && operatingCodes.length > 0 && (
        <div style={{ background: 'rgba(0,212,170,0.05)', border: '1px solid rgba(0,212,170,0.15)',
          borderRadius: 8, padding: '8px 14px', marginBottom: 14, fontSize: 12, color: '#9ca3af' }}>
          Showing providers for your tenant's operating countries
          ({operatingCodes.map((c: string) => COUNTRIES.find(x => x.code === c)?.flag).join(' ')}).
          Use the filter below to browse other countries (e.g. before adding a new region).
        </div>
      )}
      <div style={{ display:'flex', gap:10, marginBottom:16 }}>
        <Select value={countryF} onChange={v => { setCountryF(v) }} style={{ width:200 }} size="small">
          <Option value="ALL">🌍 Tenant's Countries</Option>
          {COUNTRIES.map(c => <Option key={c.code} value={c.code}>{c.flag} {c.name}</Option>)}
        </Select>
        <Button size="small" onClick={load}>🔄 Refresh</Button>
      </div>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 20 }}>
        Configure external data providers. Enable mock providers for demos/dev.
        Add live credentials when vendor sandbox/production access is available.
      </div>
      {loading ? <Spin/> : Object.entries(byCountry).map(([country, groups]: any) => (
        <div key={country} style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', marginBottom: 12,
            paddingBottom: 8, borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
            {countryFlag(country)} {countryName(country)}
          </div>
          {groups.map((g: any) => {
            const meta = TYPE_META[g.type] || { icon: '🔌', label: g.type, color: '#94a3b8' }
            return (
              <div key={g.type} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: meta.color, marginBottom: 8 }}>
                  {meta.icon} {meta.label}
                </div>
                {g.items.map((p: any) => (
                  <div key={p.id} style={card}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>
                        {p.provider_name}
                        {p.is_mock && <Tag style={{ marginLeft: 8, fontSize: 10 }}>MOCK</Tag>}
                      </div>
                      <div style={{ fontSize: 11, color: '#6b7280', fontFamily: 'var(--font-mono,monospace)', marginTop: 2 }}>
                        {p.provider_code}
                        {p.api_endpoint && ` · ${p.api_endpoint}`}
                      </div>
                    </div>
                    <Switch checked={p.is_enabled} onChange={val => toggleEnabled(p, val)}
                      checkedChildren="ON" unCheckedChildren="OFF"/>
                    {!p.is_mock && (
                      <Button size="small" onClick={() => { setEditModal(p); form.setFieldsValue({ is_enabled: p.is_enabled, api_endpoint: p.api_endpoint || '' }) }}>
                        Configure
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      ))}

      <Modal
        title={`Configure — ${editModal?.provider_name}`}
        open={!!editModal} onCancel={() => setEditModal(null)} onOk={saveEdit}
        styles={{ content: { background: 'var(--navy-800,#0a1628)' }, header: { background: 'var(--navy-800,#0a1628)' } }}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="api_endpoint" label="API Endpoint">
            <Input placeholder="https://api.vendor.com/v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key (leave blank to keep existing)">
            <Input.Password placeholder="Enter new API key..." />
          </Form.Item>
          <Form.Item name="is_enabled" label="Enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Verification Panel (used both in standalone page and Workbench drawer)
// ══════════════════════════════════════════════════════════════════════════════
export function VerificationPanel({
  applicantRef, caseRefId, compact = false,
}: {
  applicantRef: string; caseRefId?: number; compact?: boolean
}) {
  const [summary, setSummary]   = useState<any>(null)
  const [loading, setLoading]   = useState(false)
  const [running, setRunning]   = useState<string | null>(null)

  const load = () => {
    if (!applicantRef) return
    setLoading(true)
    intApi.get(`/integrations/summary/${applicantRef}`)
      .then(d => setSummary(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [applicantRef])

  const runCheck = async (type: string) => {
    setRunning(type)
    try {
      const r = await intApi.post('/integrations/verify', {
        integration_type: type,
        applicant_ref:    applicantRef,
        case_ref_id:      caseRefId,
      })
      if (r.status === 'COMPLETED') {
        message.success(`${TYPE_META[type]?.label || type} check completed`)
        load()
      } else {
        message.error(r.result?.error || 'Check failed')
      }
    } catch { message.error('Verification failed') }
    finally { setRunning(null) }
  }

  if (!applicantRef) return null

  const completed: any[]  = summary?.completed || []
  const pendingTypes: string[] = summary?.pending_types || []
  const allFlags: string[] = summary?.all_risk_flags || []
  const overallStatus: string = summary?.overall_status || 'PENDING'

  const statusColor = {
    CLEAR: '#22c55e', PENDING: '#6b7280', FLAGGED: '#ef4444', REVIEW_NEEDED: '#fbbf24'
  }[overallStatus] || '#6b7280'

  const statusIcon = {
    CLEAR: <CheckCircleOutlined/>, PENDING: <ClockCircleOutlined/>,
    FLAGGED: <CloseCircleOutlined/>, REVIEW_NEEDED: <ExclamationCircleOutlined/>
  }[overallStatus] || <ClockCircleOutlined/>

  return (
    <div>
      {/* Overall status */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: statusColor, fontSize: 16 }}>{statusIcon}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: statusColor }}>
            {overallStatus.replace('_', ' ')}
          </span>
          {allFlags.length > 0 && (
            <span style={{ fontSize: 11, color: '#6b7280' }}>
              ({allFlags.length} flag{allFlags.length > 1 ? 's' : ''})
            </span>
          )}
        </div>
        <Button size="small" icon={<ReloadOutlined/>} onClick={load} loading={loading}/>
      </div>

      {/* Risk flags */}
      {allFlags.length > 0 && (
        <div style={{ marginBottom: 12, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {allFlags.map((f: string) => (
            <Tag key={f} color="error" style={{ fontSize: 10 }}>⚠ {f.replace(/_/g, ' ')}</Tag>
          ))}
        </div>
      )}

      {loading && !summary ? <Spin size="small"/> : (
        <>
          {/* Completed checks */}
          {completed.map((r: any) => {
            const meta = TYPE_META[r.integration_type] || { icon: '🔌', label: r.integration_type, color: '#94a3b8' }
            return (
              <div key={r.integration_type} style={{
                background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: 8, padding: compact ? '8px 12px' : '12px 14px', marginBottom: 8,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>{meta.icon}</span>
                    <span style={{ fontSize: 12, fontWeight: 600, color: '#e2e8f0' }}>{meta.label}</span>
                    <Tag style={{ fontSize: 9 }}>{r.provider_code}</Tag>
                  </div>
                  <CheckCircleOutlined style={{ color: '#22c55e' }}/>
                </div>

                {!compact && (
                  <div style={{ marginTop: 8 }}>
                    {/* IDENTITY */}
                    {r.integration_type === 'IDENTITY' && (
                      <div style={{ fontSize: 11, color: '#9ca3af' }}>
                        ✅ KYC Verified · Name: {r.kyc_name} · PAN: {r.kyc_pan} · Aadhaar: {r.kyc_aadhaar_masked}
                      </div>
                    )}
                    {/* CREDIT */}
                    {r.integration_type === 'CREDIT' && (
                      <div style={{ fontSize: 11, color: '#9ca3af' }}>
                        Score: <strong style={{ color: r.credit_score >= 750 ? '#22c55e' : r.credit_score >= 650 ? '#fbbf24' : '#ef4444', fontSize: 13 }}>{r.credit_score}</strong>
                        {' '}({r.credit_bureau})
                        {(r.credit_flags?.length > 0) && (
                          <div style={{ marginTop: 4 }}>
                            {(typeof r.credit_flags === 'string' ? JSON.parse(r.credit_flags) : r.credit_flags)
                              .map((f: string) => <Tag key={f} color="warning" style={{ fontSize: 9 }}>{f}</Tag>)}
                          </div>
                        )}
                      </div>
                    )}
                    {/* LAB */}
                    {r.integration_type === 'LAB' && (() => {
                      const tests = typeof r.lab_tests === 'string' ? JSON.parse(r.lab_tests || '[]') : (r.lab_tests || [])
                      const abnormal = tests.filter((t: any) => t.flag !== 'NORMAL')
                      return (
                        <div style={{ fontSize: 11 }}>
                          <div style={{ color: '#9ca3af' }}>
                            Order: {r.lab_order_ref} · {tests.length} tests · {abnormal.length} abnormal
                          </div>
                          <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                            {tests.map((t: any) => (
                              <div key={t.test} style={{
                                background: t.flag === 'HIGH' ? 'rgba(239,68,68,0.1)' : t.flag === 'LOW' ? 'rgba(251,191,36,0.1)' : 'rgba(255,255,255,0.03)',
                                border: `1px solid ${t.flag !== 'NORMAL' ? (t.flag === 'HIGH' ? 'rgba(239,68,68,0.3)' : 'rgba(251,191,36,0.3)') : 'rgba(255,255,255,0.06)'}`,
                                borderRadius: 6, padding: '3px 8px', fontSize: 10,
                              }}>
                                <span style={{ color: '#9ca3af' }}>{t.test}</span>
                                {' '}<strong style={{ color: t.flag !== 'NORMAL' ? (t.flag === 'HIGH' ? '#ef4444' : '#fbbf24') : '#e2e8f0' }}>
                                  {t.value}{t.unit}
                                </strong>
                                {t.flag !== 'NORMAL' && <span style={{ color: '#ef4444', marginLeft: 4 }}>▲</span>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )
                    })()}
                    {/* AML */}
                    {r.integration_type === 'AML' && (
                      <div style={{ fontSize: 11, color: '#9ca3af' }}>
                        Status: <strong style={{ color: r.aml_status === 'CLEAR' ? '#22c55e' : '#ef4444' }}>{r.aml_status}</strong>
                        {(r.aml_flags?.length > 0) && (
                          <span style={{ marginLeft: 8 }}>
                            {(typeof r.aml_flags === 'string' ? JSON.parse(r.aml_flags) : r.aml_flags)
                              .map((f: string) => <Tag key={f} color="error" style={{ fontSize: 9 }}>{f}</Tag>)}
                          </span>
                        )}
                      </div>
                    )}
                    {/* PHARMACY / DRIVING */}
                    {(r.integration_type === 'PHARMACY' || r.integration_type === 'DRIVING') && (
                      <div style={{ fontSize: 11, color: '#9ca3af' }}>
                        {r.notes}
                        {(r.aml_flags?.length > 0) && (
                          <div style={{ marginTop: 4 }}>
                            {(typeof r.aml_flags === 'string' ? JSON.parse(r.aml_flags) : r.aml_flags)
                              .map((f: string) => <Tag key={f} color="warning" style={{ fontSize: 9 }}>{f.replace(/_/g,' ')}</Tag>)}
                          </div>
                        )}
                      </div>
                    )}
                    <div style={{ fontSize: 10, color: '#4b5563', marginTop: 6 }}>
                      Verified: {r.verified_at?.slice(0,16).replace('T',' ')}
                      {r.expires_at && ` · Expires: ${r.expires_at?.slice(0,10)}`}
                      {' · '}Confidence: {Math.round((r.confidence_score||0)*100)}%
                    </div>
                  </div>
                )}
              </div>
            )
          })}

          {/* Pending checks */}
          {pendingTypes.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 8 }}>
                Not yet verified:
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {pendingTypes.map((type: string) => {
                  const meta = TYPE_META[type] || { icon: '🔌', label: type, color: '#94a3b8' }
                  return (
                    <Button
                      key={type}
                      size="small"
                      icon={<PlayCircleOutlined/>}
                      loading={running === type}
                      onClick={() => runCheck(type)}
                      style={{ fontSize: 11, borderColor: meta.color + '40', color: meta.color }}
                    >
                      {meta.icon} {compact ? type : `Run ${meta.label}`}
                    </Button>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Verification History Tab
// ══════════════════════════════════════════════════════════════════════════════
function VerificationHistoryTab() {
  const [search, setSearch]   = useState('')
  const [typeF, setTypeF]     = useState('ALL')
  const [results, setResults] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const load = () => {
    if (!search.trim()) return
    setLoading(true)
    intApi.get('/integrations/results', {
      applicant_ref:    search.trim(),
      integration_type: typeF === 'ALL' ? undefined : typeF,
    })
      .then(d => setResults(Array.isArray(d) ? d : []))
      .catch(() => setResults([]))
      .finally(() => setLoading(false))
  }

  const columns = [
    { title: Titled('Type', 'integration_type'), dataIndex:'integration_type', width:120,
      render:(v:string) => {
        const m = TYPE_META[v] || { icon:'🔌', label:v, color:'#94a3b8' }
        return <span style={{ color:m.color }}>{m.icon} {v}</span>
      }},
    { title: Titled('Provider', 'provider_code'), dataIndex:'provider_code', width:140,
      render:(v:string) => <Tag style={{ fontSize:10 }}>{v}</Tag> },
    { title: Titled('KYC', 'kyc_verified'), dataIndex:'kyc_verified', width:70,
      render:(v:boolean|null, r:any) => r.integration_type !== 'IDENTITY' ? '—' :
        v===null?'—':v?<CheckCircleOutlined style={{ color:'#22c55e'}}/>:<CloseCircleOutlined style={{ color:'#ef4444'}}/> },
    { title: Titled('Credit', 'credit_score'), dataIndex:'credit_score', width:80,
      render:(v:number) => v ? <strong style={{ color:v>=750?'#22c55e':v>=650?'#fbbf24':'#ef4444' }}>{v}</strong> : '—' },
    { title: Titled('AML', 'aml_status'), dataIndex:'aml_status', width:110,
      render:(v:string) => v ? <Tag color={v==='CLEAR'?'success':v==='HIT'?'error':'warning'} style={{ fontSize:10 }}>{v}</Tag>:'—' },
    { title: Titled('Confidence', 'confidence_score'), dataIndex:'confidence_score', width:100,
      render:(v:number) => `${Math.round((v||0)*100)}%` },
    { title: Titled('Verified', 'verified_at'), dataIndex:'verified_at', width:140,
      render:(v:string) => <span style={{ fontSize:11, color:'#6b7280' }}>{v?.slice(0,16).replace('T',' ')}</span> },
    { title: Titled('Expires', 'expires_at'), dataIndex:'expires_at', width:120,
      render:(v:string) => {
        if (!v) return '—'
        const expired = new Date(v) < new Date()
        return <span style={{ fontSize:11, color:expired?'#ef4444':'#6b7280' }}>{v?.slice(0,10)}</span>
      }},
    { title: Titled('By', 'requested_by'), dataIndex:'requested_by', width:100,
      render:(v:string) => <span style={{ fontSize:11, color:'#6b7280' }}>{v||'—'}</span> },
  ]

  return (
    <div>
      <div style={{ display:'flex', gap:10, marginBottom:16 }}>
        <Input.Search
          placeholder="Enter applicant ref (e.g. APP-001)"
          value={search} onChange={e => setSearch(e.target.value)}
          onSearch={load} enterButton="Search" style={{ maxWidth:320 }}
        />
        <Select value={typeF} onChange={setTypeF} style={{ width:180 }} size="middle">
          <Option value="ALL">All types</Option>
          {Object.entries(TYPE_META).map(([k,v]) => <Option key={k} value={k}>{v.icon} {v.label}</Option>)}
        </Select>
      </div>
      {loading ? <Spin/> : (
        <Table dataSource={results} columns={columns} rowKey="id" size="small"
          locale={{ emptyText: search ? 'No verification results found' : 'Enter an applicant ref and click Search' }}
          expandable={{
            expandedRowRender:(r:any) => (
              <div style={{ padding:'8px 16px' }}>
                {r.integration_type==='LAB' && (() => {
                  const tests = typeof r.lab_tests==='string' ? JSON.parse(r.lab_tests||'[]') : (r.lab_tests||[])
                  return (
                    <div style={{ display:'flex', flexWrap:'wrap', gap:8 }}>
                      {tests.map((t:any) => (
                        <div key={t.test} style={{ fontSize:11, background:'rgba(255,255,255,0.03)',
                          border:'1px solid rgba(255,255,255,0.06)', borderRadius:6, padding:'4px 10px' }}>
                          <span style={{ color:'#6b7280' }}>{t.test}:</span>
                          {' '}<strong style={{ color:t.flag!=='NORMAL'?'#ef4444':'#e2e8f0' }}>{t.value} {t.unit}</strong>
                          {' '}<span style={{ fontSize:9, color:t.flag!=='NORMAL'?'#ef4444':'#22c55e' }}>[{t.flag}]</span>
                        </div>
                      ))}
                    </div>
                  )
                })()}
                {r.notes && <div style={{ fontSize:11, color:'#6b7280', marginTop:6 }}>{r.notes}</div>}
              </div>
            ),
            rowExpandable:(r:any) => r.integration_type==='LAB',
          }}
        />
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Run Verification Tab
// ══════════════════════════════════════════════════════════════════════════════
function RunVerificationTab() {
  const [appRef, setAppRef]       = useState('')
  const [type, setType]           = useState('IDENTITY')
  const [country, setCountry]     = useState('')
  const [tenantCtx, setTenantCtx] = useState<any>(null)
  const [countryTypes, setCountryTypes] = useState<Record<string, string[]>>({})
  const [running, setRunning]     = useState(false)
  const [result, setResult]       = useState<any>(null)

  // Provider matrix per country — built from /integrations/providers
  const loadCountryTypes = () => {
    intApi.get('/integrations/providers')
      .then((d: any[]) => {
        const matrix: Record<string, string[]> = {}
        if (Array.isArray(d)) {
          d.filter(p => p.is_enabled).forEach(p => {
            if (!matrix[p.country_code]) matrix[p.country_code] = []
            if (!matrix[p.country_code].includes(p.integration_type)) {
              matrix[p.country_code].push(p.integration_type)
            }
          })
        }
        setCountryTypes(matrix)
      })
      .catch(() => {})
  }

  useEffect(() => {
    intApi.get('/integrations/tenant-context')
      .then(d => { setTenantCtx(d); if (d?.default_country) setCountry(d.default_country) })
      .catch(() => {})
    loadCountryTypes()
  }, [])

  // When country changes, reset type to first available for that country
  useEffect(() => {
    if (country && countryTypes[country]) {
      const available = countryTypes[country]
      if (!available.includes(type)) setType(available[0] || 'IDENTITY')
    }
  }, [country, countryTypes])

  const run = async () => {
    if (!appRef.trim()) { message.error('Enter an applicant ref'); return }
    setRunning(true); setResult(null)
    try {
      const r = await intApi.post('/integrations/verify', {
        integration_type: type,
        applicant_ref:    appRef.trim(),
        ...(tenantCtx?.is_multi_country ? { country_code: country } : {}),
      })
      setResult(r)
      if (r.status === 'COMPLETED') message.success('Verification completed')
      else message.error(r.result?.error || 'Verification failed')
    } catch { message.error('Request failed') }
    finally { setRunning(false) }
  }

  const meta = TYPE_META[type] || { icon: '🔌', label: type, color: '#94a3b8' }
  const availableCountries = tenantCtx?.available_countries || []

  // Types available for currently selected country
  const availableTypes = country && countryTypes[country]
    ? countryTypes[country]
    : Object.keys(TYPE_META)

  return (
    <div style={{ maxWidth: 600 }}>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 16 }}>
        Manually trigger a verification check for any applicant.
        Used when re-verifying after data update or running additional checks.
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Input value={appRef} onChange={e => setAppRef(e.target.value)}
          placeholder="Applicant Ref (e.g. APP-001)" style={{ flex: 1 }}/>
        {tenantCtx?.is_multi_country && (
          <Select value={country} onChange={setCountry} style={{ width: 170 }}>
            {availableCountries.map((c: any) => <Option key={c.code} value={c.code}>{c.flag} {c.country_name}</Option>)}
          </Select>
        )}
        <Select value={type} onChange={setType} style={{ width: 200 }}>
          {Object.entries(TYPE_META).map(([k, v]) => {
            const isAvailable = availableTypes.includes(k)
            return (
              <Option key={k} value={k} disabled={!isAvailable}>
                <span style={{ opacity: isAvailable ? 1 : 0.4 }}>
                  {v.icon} {v.label}
                  {!isAvailable && ' (no provider)'}
                </span>
              </Option>
            )
          })}
        </Select>
        <Button type="primary" loading={running} onClick={run} icon={<PlayCircleOutlined/>}>
          Run Check
        </Button>
      </div>
      {tenantCtx && !tenantCtx.is_multi_country && (
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 12, marginTop: -8 }}>
          Using {tenantCtx.available_countries?.[0]?.flag || '🌍'} {tenantCtx.available_countries?.[0]?.country_name || tenantCtx.default_country} ·{' '}
          {availableTypes.length} verification type{availableTypes.length !== 1 ? 's' : ''} available ·{' '}
          <a href="/system-config" style={{ color: '#00d4aa' }}>change in System Config</a>
        </div>
      )}
      {tenantCtx?.is_multi_country && country && (
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 12, marginTop: -8 }}>
          {availableTypes.length} verification type{availableTypes.length !== 1 ? 's' : ''} available for {availableCountries.find((c: any) => c.code === country)?.country_name || country}
          {availableTypes.length < 6 && ' · Add providers in Provider Config to enable more types'}
        </div>
      )}

      {result && (
        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 10, padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <span style={{ fontSize: 20 }}>{meta.icon}</span>
            <span style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>{meta.label}</span>
            <Tag color={result.status === 'COMPLETED' ? 'success' : 'error'}>{result.status}</Tag>
            {result.is_mock && <Tag style={{ fontSize: 10 }}>MOCK</Tag>}
          </div>
          <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 10 }}>
            Request ref: <strong style={{ fontFamily: 'var(--font-mono,monospace)', color: '#9ca3af' }}>{result.request_ref}</strong>
            {' · '}Provider: {result.provider_code}
          </div>
          {/* Show key result fields */}
          {type === 'IDENTITY' && result.result?.kyc_verified !== undefined && (
            <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 6 }}>
              KYC Verified: <strong style={{ color: result.result.kyc_verified ? '#22c55e' : '#ef4444' }}>
                {result.result.kyc_verified ? '✅ Yes' : '❌ No'}
              </strong>
              {result.result.kyc_name && ` · Name: ${result.result.kyc_name}`}
              {result.result.kyc_pan && ` · PAN: ${result.result.kyc_pan}`}
              {result.result.kyc_aadhaar_masked && ` · Aadhaar: ${result.result.kyc_aadhaar_masked}`}
              {result.result.kyc_address && <div style={{ marginTop: 4 }}>Address: {result.result.kyc_address}</div>}
            </div>
          )}
          {result.result?.credit_score && (
            <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 6 }}>
              Credit Score: <strong style={{ fontSize: 18, color: result.result.credit_score >= 750 ? '#22c55e' : result.result.credit_score >= 650 ? '#fbbf24' : '#ef4444' }}>
                {result.result.credit_score}
              </strong>
              {' '}({result.result.credit_bureau})
            </div>
          )}
          {result.result?.aml_status && (
            <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 6 }}>
              AML Status: <Tag color={result.result.aml_status === 'CLEAR' ? 'success' : 'error'}>{result.result.aml_status}</Tag>
            </div>
          )}
          {result.result?.lab_tests?.length > 0 && (
            <div style={{ fontSize: 11, marginBottom: 6 }}>
              <div style={{ color: '#6b7280', marginBottom: 6 }}>Lab Results:</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {result.result.lab_tests.map((t: any) => (
                  <div key={t.test} style={{ fontSize: 10, background: t.flag !== 'NORMAL' ? 'rgba(239,68,68,0.1)' : 'rgba(255,255,255,0.03)',
                    border: `1px solid ${t.flag !== 'NORMAL' ? 'rgba(239,68,68,0.3)' : 'rgba(255,255,255,0.06)'}`,
                    borderRadius: 6, padding: '3px 8px' }}>
                    {t.test}: <strong style={{ color: t.flag !== 'NORMAL' ? '#ef4444' : '#e2e8f0' }}>{t.value}{t.unit}</strong>
                  </div>
                ))}
              </div>
            </div>
          )}
          {result.result?.notes && (
            <div style={{ fontSize: 11, color: '#4b5563', marginTop: 8, fontStyle: 'italic' }}>
              {result.result.notes}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Page
// ══════════════════════════════════════════════════════════════════════════════
export default function IntegrationsPage() {
  const tabs = [
    { key: 'run',     label: '▶️ Run Verification',  children: <RunVerificationTab /> },
    { key: 'history', label: '📋 Verification History', children: <VerificationHistoryTab /> },
    { key: 'config',  label: '⚙️ Provider Config',   children: <ProviderConfigTab /> },
  ]

  return (
    <div style={{ padding: '32px 36px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontWeight: 700, fontSize: 22, color: '#e2e8f0', margin: 0, letterSpacing: '-0.02em' }}>
          🔌 External Data Integrations
        </h1>
        <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          CKYC · CIBIL · Lab/Diagnostics · AML · Pharmacy DB · Driving Records
        </p>
      </div>
      <Tabs defaultActiveKey="run" items={tabs}
        tabBarStyle={{ borderBottom: '1px solid rgba(255,255,255,0.07)', marginBottom: 20 }}/>
    </div>
  )
}
