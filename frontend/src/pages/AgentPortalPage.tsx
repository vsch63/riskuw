// AgentPortalPage.tsx - Full version with navbar, logout, change password
import { useState, useEffect } from 'react'
import { Tabs, Button, Input, Select, InputNumber, Table, Tag, message, Spin, Form, Alert } from 'antd'
import { SendOutlined, FileTextOutlined, DashboardOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { useAuthStore } from '../context/authStore'

const { Option } = Select

const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 12, padding: '20px 24px', marginBottom: 16,
}

const STATUS_COLOR: Record<string, string> = {
  APPROVED_STP: 'success', APPROVED: 'success', DECLINED: 'error',
  REFERRED: 'warning', PENDING: 'processing', OPEN: 'processing', IN_PROGRESS: 'processing',
}
const STATUS_LABEL: Record<string, string> = {
  APPROVED_STP: 'Approved', APPROVED: 'Approved (Rated)', DECLINED: 'Declined',
  REFERRED: 'Under Review', PENDING: 'Pending', OPEN: 'Pending', IN_PROGRESS: 'In Progress',
}

function DashboardTab() {
  const [stats, setStats]   = useState<any>(null)
  const [recent, setRecent] = useState<any[]>([])
  const [loading, setLoad]  = useState(true)
  const user = useAuthStore(s => s.user)

  useEffect(() => {
    api.get('/agent/dashboard').then(r => {
      setStats(r.data.stats); setRecent(r.data.recent || [])
    }).catch(() => {}).finally(() => setLoad(false))
  }, [])

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><Spin/></div>

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ color: '#e2e8f0', fontSize: 18, fontWeight: 700, margin: 0 }}>
          Welcome, {user?.full_name || user?.username}
          {user?.full_name && <span style={{ fontSize: 13, color: '#6b7280', fontWeight: 400, marginLeft: 8 }}>({user?.username})</span>}
        </h2>
        <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          Submit proposals and track underwriting decisions
        </p>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: 'Total Submitted', value: stats?.total_submitted || 0, color: '#00d4aa' },
          { label: 'Approved',        value: stats?.approved || 0,        color: '#22c55e' },
          { label: 'Declined',        value: stats?.declined || 0,        color: '#ef4444' },
          { label: 'Under Review',    value: stats?.pending || 0,         color: '#f59e0b' },
          { label: 'In Progress',     value: stats?.in_progress || 0,     color: '#6b7280' },
        ].map(s => (
          <div key={s.label} style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: s.color }}>{s.value}</div>
            <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>{s.label}</div>
          </div>
        ))}
      </div>
      <div style={card}>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 12 }}>Recent Submissions</div>
        {recent.length === 0 ? (
          <div style={{ color: '#6b7280', fontSize: 13 }}>No submissions yet. Use the Submit Proposal tab to get started.</div>
        ) : (
          <Table dataSource={recent} rowKey="applicant_ref" size="small" pagination={false}
            columns={[
              { title: 'Ref', dataIndex: 'applicant_ref', width: 130, render: (v: string) => <code style={{ fontSize: 11, color: '#00d4aa' }}>{v}</code> },
              { title: 'Product', dataIndex: 'product_code', width: 130 },
              { title: 'Age/Gender', width: 100, render: (_: any, r: any) => `${r.age} / ${r.gender?.charAt(0)}` },
              { title: 'Sum Assured', dataIndex: 'face_amount', width: 130, render: (v: number) => `₹${Number(v).toLocaleString('en-IN')}` },
              { title: 'Status', dataIndex: 'status', width: 130, render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'} style={{ fontSize: 11 }}>{STATUS_LABEL[v] || v}</Tag> },
              { title: 'Submitted', dataIndex: 'created_at', width: 150, render: (v: string) => v?.slice(0, 16).replace('T', ' ') },
            ]}
          />
        )}
      </div>
    </div>
  )
}

function SubmitProposalTab() {
  const [form]              = Form.useForm()
  const [submitting, setSub] = useState(false)
  const [result, setResult]  = useState<any>(null)
  const [products, setProd]  = useState<any[]>([])

  useEffect(() => {
    api.get('/agent/products').then(r => setProd(Array.isArray(r.data) ? r.data : [])).catch(() => {})
  }, [])

  const submit = async () => {
    try { await form.validateFields() } catch { return }
    const v = form.getFieldsValue()
    setSub(true); setResult(null)
    try {
      const r = await api.post('/agent/submit', v)
      setResult(r.data)
      message.success('Proposal submitted successfully')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Submission failed')
    } finally { setSub(false) }
  }

  const [extracting, setExtracting] = useState(false)

  const handleDocUpload = async (file: File) => {
    setExtracting(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api.post('/underwriting/extract-document', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      const f = r.data.extracted || {}
      const mapped: Record<string,any> = {}
      if (f.age)              mapped.age = f.age
      if (f.gender)           mapped.gender = f.gender
      if (f.state)            mapped.state = f.state
      if (f.face_amount)      mapped.face_amount = f.face_amount
      if (f.coverage_term_yrs) mapped.coverage_term_yrs = f.coverage_term_yrs
      if (f.tobacco_status)   mapped.tobacco_status = f.tobacco_status
      if (f.height_inches)    mapped.height_inches = f.height_inches
      if (f.weight_lbs)       mapped.weight_lbs = f.weight_lbs
      if (f.systolic_bp)      mapped.systolic_bp = f.systolic_bp
      if (f.diastolic_bp)     mapped.diastolic_bp = f.diastolic_bp
      if (f.diabetes_type)    mapped.diabetes_type = f.diabetes_type
      if (f.heart_condition)  mapped.heart_condition = f.heart_condition
      if (f.annual_income)    mapped.annual_income = f.annual_income
      if (f.applicant_ref)    mapped.applicant_ref = f.applicant_ref
      if (f.product_code)     mapped.product_code = f.product_code
      form.setFieldsValue(mapped)
      message.success(r.data.uw_fields_found + ' fields extracted from document')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Extraction failed')
    } finally { setExtracting(false) }
    return false
  }

  return (
    <div style={{ maxWidth: 800 }}>
      {/* AI Document Upload */}
      <div style={{ background: 'rgba(0,212,170,0.04)', border: '1px solid rgba(0,212,170,0.2)', borderRadius: 12, padding: '16px 20px', marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#00d4aa', marginBottom: 6 }}>📄 Auto-fill from Proposal Document</div>
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 10 }}>Upload a scanned proposal form PDF or image — Claude AI will extract and fill the fields below automatically.</div>
        <input type="file" accept=".pdf,.jpg,.jpeg,.png" style={{ display: 'none' }} id="agent-doc-upload"
          onChange={e => e.target.files?.[0] && handleDocUpload(e.target.files[0])}/>
        <Button loading={extracting} onClick={() => document.getElementById('agent-doc-upload')?.click()}
          style={{ borderColor: 'rgba(0,212,170,0.3)', color: '#00d4aa' }}>
          {extracting ? 'Extracting fields...' : '📎 Upload Proposal PDF / Image'}
        </Button>
        {extracting && <span style={{ fontSize: 12, color: '#6b7280', marginLeft: 12 }}>Claude AI is reading your document...</span>}
      </div>

      {result && (
        <>
        <Alert type={result.outcome?.includes('APPROVED') ? 'success' : result.outcome?.includes('DECLINED') ? 'error' : 'info'}
          message={result.message}
          description={<div>
            <div style={{ marginTop: 8 }}>
              <strong>Case No:</strong> {result.case_number || '—'} &nbsp;|&nbsp;
              <strong>Outcome:</strong> {STATUS_LABEL[result.outcome] || result.outcome}
              {result.approved_premium && <> &nbsp;|&nbsp;<strong>Premium:</strong> ₹{Number(result.approved_premium).toLocaleString('en-IN')} p.a.</>}
            </div>
            <div style={{ marginTop: 4, color: '#6b7280', fontSize: 12 }}>{result.next_steps}</div>
          </div>}
          showIcon closable onClose={() => setResult(null)} style={{ marginBottom: 8 }}
        />
        {result?.sar?.configured && (
          <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 10, padding: '12px 14px', marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--teal-400)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>
              Sum-at-Risk · Free Cover Limit
              {(result.medical_requirements || []).length > 0 && (
                <span style={{ float: 'right', color: '#f59e0b', fontWeight: 600 }}>
                  NML: {(result.medical_requirements || []).join(' · ')}
                </span>
              )}
            </div>
            <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ color: '#6b7280', textAlign: 'left' }}>
                  <th style={{ padding: '4px 6px' }}>Exposure Group</th>
                  <th style={{ padding: '4px 6px' }}>Gross SAR</th>
                  <th style={{ padding: '4px 6px' }}>Excess SAR</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(result.sar.gross_sar || {}).map((eg: string) => (
                  <tr key={eg}>
                    <td style={{ padding: '4px 6px' }}>{eg}</td>
                    <td style={{ padding: '4px 6px' }}>₹{Number(result.sar.gross_sar[eg]).toLocaleString('en-IN')}</td>
                    <td style={{ padding: '4px 6px' }}>₹{Number(result.sar.excess_sar?.[eg] || 0).toLocaleString('en-IN')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {result?.outcome?.includes('APPROVED') && (
          <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button type="primary"
              onClick={() => {
                const params = new URLSearchParams({
                  applicant_ref: result.applicant_ref || '',
                  outcome:       result.outcome || '',
                  case_number:   result.case_number || '',
                  premium:       String(result.approved_premium || 0),
                  risk_class:    result.risk_class || '',
                })
                const token = localStorage.getItem('riskuw_token')
                fetch('/system/letter-templates/TPL-APPROVED-001/generate?' + params, {
                  headers: { Authorization: 'Bearer ' + token }
                }).then(r => r.blob()).then(blob => {
                  window.open(URL.createObjectURL(blob), '_blank')
                })
              }}>
              📄 Print Approval Letter
            </Button>
            <span style={{ fontSize: 12, color: '#6b7280' }}>Opens in new tab — use browser Print to save as PDF</span>
          </div>
        )}
        </>
      )}
      <Form form={form} layout="vertical" requiredMark={false}>
        <div style={card}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16 }}>Applicant Details</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Form.Item name="applicant_ref" label="Application Reference *" rules={[{ required: true }]}><Input placeholder="e.g. AGT-2026-001"/></Form.Item>
            <Form.Item name="applicant_name" label="Applicant Full Name *" rules={[{ required: true }]}><Input placeholder="e.g. Rajesh Kumar"/></Form.Item>
            <Form.Item name="product_code" label="Product *" rules={[{ required: true }]}>
              <Select placeholder="Select product" showSearch>
                {products.map(p => <Option key={p.product_code} value={p.product_code}>{p.product_code} — {p.product_name}</Option>)}
              </Select>
            </Form.Item>
            <Form.Item name="age" label="Age *" rules={[{ required: true }]}><InputNumber min={18} max={70} style={{ width: '100%' }}/></Form.Item>
            <Form.Item name="gender" label="Gender *" rules={[{ required: true }]}>
              <Select><Option value="MALE">Male</Option><Option value="FEMALE">Female</Option></Select>
            </Form.Item>
            <Form.Item name="state" label="State Code *" rules={[{ required: true }]}><Input placeholder="e.g. MH, DL" maxLength={2}/></Form.Item>
            <Form.Item name="tobacco_status" label="Tobacco Status" initialValue="NON_TOBACCO">
              <Select>
                <Option value="NEVER">Never Used</Option>
                <Option value="NON_TOBACCO">Non-Tobacco</Option>
                <Option value="SMOKER">Smoker</Option>
              </Select>
            </Form.Item>
          </div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16 }}>Coverage Details</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Form.Item name="face_amount" label="Sum Assured (₹) *" rules={[{ required: true }]}>
              <InputNumber min={100000} step={100000} style={{ width: '100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v: any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
            <Form.Item name="coverage_term_yrs" label="Coverage Term" initialValue={20}>
              <Select>{[5,10,15,20,25,30].map(t => <Option key={t} value={t}>{t} years</Option>)}</Select>
            </Form.Item>
            <Form.Item name="annual_income" label="Annual Income (₹)">
              <InputNumber min={0} step={100000} style={{ width: '100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v: any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
            <Form.Item name="existing_coverage" label="Existing Coverage (₹)" initialValue={0}>
              <InputNumber min={0} step={100000} style={{ width: '100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v: any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
          </div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16 }}>Basic Medical Information</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Form.Item name="height_inches" label="Height (inches)"><InputNumber min={48} max={96} style={{ width: '100%' }} placeholder="e.g. 68"/></Form.Item>
            <Form.Item name="weight_lbs" label="Weight (lbs)"><InputNumber min={50} max={500} style={{ width: '100%' }} placeholder="e.g. 170"/></Form.Item>
            <Form.Item name="systolic_bp" label="Systolic BP"><InputNumber min={80} max={250} style={{ width: '100%' }} placeholder="e.g. 120"/></Form.Item>
            <Form.Item name="diastolic_bp" label="Diastolic BP"><InputNumber min={50} max={150} style={{ width: '100%' }} placeholder="e.g. 80"/></Form.Item>
            <Form.Item name="diabetes_type" label="Diabetes" initialValue="NONE">
              <Select><Option value="NONE">None</Option><Option value="TYPE2">Type 2</Option><Option value="TYPE1">Type 1</Option></Select>
            </Form.Item>
            <Form.Item name="heart_condition" label="Heart Condition" initialValue="NONE">
              <Select><Option value="NONE">None</Option><Option value="HYPERTENSION">Hypertension</Option><Option value="CAD">CAD</Option></Select>
            </Form.Item>
          </div>
        </div>
        <Button type="primary" icon={<SendOutlined/>} loading={submitting} onClick={submit} size="large" block style={{ height: 48, fontWeight: 600 }}>
          Submit Proposal for Underwriting
        </Button>
        <div style={{ textAlign: 'center', fontSize: 12, color: '#4b5563', marginTop: 8 }}>
          Instant decision for most cases · Referred cases reviewed within 48 hours
        </div>
      </Form>
    </div>
  )
}

function MyCasesTab() {
  const [submissions, setSub] = useState<any[]>([])
  const [loading, setLoad]    = useState(true)
  const [total, setTotal]     = useState(0)
  const [page, setPage]       = useState(1)
  const [status, setStatus]   = useState('')

  const load = async () => {
    setLoad(true)
    try {
      const r = await api.get('/agent/submissions', { params: { page, per_page: 20, status } })
      setSub(r.data.submissions || []); setTotal(r.data.total || 0)
    } catch { setSub([]) }
    finally { setLoad(false) }
  }
  useEffect(() => { load() }, [page, status])

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
        <Select value={status || undefined} onChange={v => { setStatus(v || ''); setPage(1) }}
          placeholder="All statuses" allowClear style={{ width: 180 }}>
          <Option value="APPROVED">Approved</Option>
          <Option value="DECLINED">Declined</Option>
          <Option value="REFERRED">Under Review</Option>
          <Option value="PENDING">Pending</Option>
        </Select>
        <Button onClick={load} loading={loading}>🔄 Refresh</Button>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#6b7280' }}>{total} total submissions</span>
      </div>
      <Table dataSource={submissions} rowKey="application_number" loading={loading} size="small"
        pagination={{ current: page, pageSize: 20, total, onChange: p => setPage(p), showSizeChanger: false }}
        columns={[
          { title: 'Reference', dataIndex: 'applicant_ref', width: 150, render: (v: string) => <code style={{ fontSize: 11, color: '#00d4aa' }}>{v}</code> },
          { title: 'Product', dataIndex: 'product_code', width: 130 },
          { title: 'Applicant', width: 150, render: (_: any, r: any) => r.applicant_name || `${r.age}y ${r.gender?.charAt(0)}` },
          { title: 'Sum Assured', dataIndex: 'face_amount', width: 140, render: (v: number) => `₹${Number(v).toLocaleString('en-IN')}` },
          { title: 'Premium p.a.', dataIndex: 'approved_premium', width: 130, render: (v: number) => v ? `₹${Number(v).toLocaleString('en-IN')}` : '—' },
          { title: 'Status', dataIndex: 'status', width: 130, render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'} style={{ fontSize: 11 }}>{STATUS_LABEL[v] || v}</Tag> },
          { title: 'Risk Class', dataIndex: 'risk_class', width: 110, render: (v: string) => v || '—' },
          { title: 'Case No.', dataIndex: 'case_number', width: 160, render: (v: string) => v ? <code style={{ fontSize: 10, color: '#6b7280' }}>{v}</code> : '—' },
          { title: 'Submitted', dataIndex: 'created_at', width: 140, render: (v: string) => v?.slice(0, 16).replace('T', ' ') },
        ]}
      />
    </div>
  )
}

export default function AgentPortalPage() {
  const user   = useAuthStore(s => s.user)
  const logout = useAuthStore(s => s.logout)

  const tabs = [
    { key: 'dashboard', label: <span><DashboardOutlined/> Dashboard</span>,      children: <DashboardTab/> },
    { key: 'submit',    label: <span><SendOutlined/> Submit Proposal</span>,       children: <SubmitProposalTab/> },
    { key: 'cases',     label: <span><FileTextOutlined/> My Submissions</span>,   children: <MyCasesTab/> },
  ]

  return (
    <div style={{ minHeight: '100vh', background: '#0f1117' }}>
      {/* Navbar */}
      <div style={{ height: 56, background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid rgba(255,255,255,0.07)', display: 'flex', alignItems: 'center', padding: '0 32px', gap: 16 }}>
        <span style={{ fontSize: 20 }}>🛡️</span>
        <span style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>RiskUW</span>
        <span style={{ fontSize: 10, background: 'rgba(0,212,170,0.15)', color: '#00d4aa', padding: '2px 8px', borderRadius: 4, fontWeight: 600, letterSpacing: '0.08em' }}>
          {user?.role?.toUpperCase()} PORTAL
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 13, color: '#9ca3af' }}>
            👤 {user?.full_name || user?.username}
            {user?.full_name && <span style={{ color: '#6b7280', fontSize: 11, marginLeft: 6 }}>({user?.username})</span>}
          </span>
          <Button size="small"
            onClick={() => {
              const newPwd = prompt('Enter new password (min 8 chars):')
              if (newPwd && newPwd.length >= 8) {
                api.post(`/auth/users/${user?.username}/reset-password`, { new_password: newPwd })
                  .then(() => message.success('Password changed successfully'))
                  .catch(() => message.error('Password change failed'))
              } else if (newPwd) {
                message.warning('Password must be at least 8 characters')
              }
            }}
            style={{ fontSize: 12, color: '#9ca3af', borderColor: 'rgba(255,255,255,0.1)' }}>
            🔑 Change Password
          </Button>
          <Button size="small" onClick={() => { logout(); window.location.href = '/login' }}
            style={{ fontSize: 12, color: '#f87171', borderColor: 'rgba(239,68,68,0.3)' }}>
            Sign Out
          </Button>
        </div>
      </div>
      {/* Content */}
      <div style={{ padding: '32px 36px' }}>
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <h1 style={{ fontWeight: 700, fontSize: 20, color: '#e2e8f0', margin: 0 }}>
              {user?.role === 'broker' ? '🏢 Broker Portal' : '👤 Agent Portal'}
            </h1>
            <Tag color="cyan" style={{ fontSize: 11 }}>{user?.role?.toUpperCase()}</Tag>
          </div>
          <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
            Submit proposals and track underwriting decisions
          </p>
        </div>
        <Tabs items={tabs} tabBarStyle={{ borderBottom: '1px solid rgba(255,255,255,0.07)', marginBottom: 24 }}/>
      </div>
    </div>
  )
}
