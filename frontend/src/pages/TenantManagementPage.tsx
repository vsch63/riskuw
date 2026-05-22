import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, InputNumber,
  Spin, message, Popconfirm, Tabs, Switch,
} from 'antd'
import {
  PlusOutlined, EditOutlined, StopOutlined, CheckOutlined,
  ReloadOutlined, SearchOutlined, BankOutlined, AuditOutlined,
  GlobalOutlined, ApiOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAuthStore } from '../context/authStore'

const { Option } = Select

// ── Types ──────────────────────────────────────────────────────────────────────
interface Tenant {
  id: string
  tenant_code: string
  tenant_name: string
  status: string
  plan_tier: string
  contact_name?: string
  contact_email?: string
  contact_phone?: string
  company_type?: string
  state_of_domicile?: string
  naic_code?: string
  max_users?: number
  max_decisions_per_month?: number
  decisions_this_month?: number
  sso_enabled?: boolean
  api_enabled?: boolean
  timezone?: string
  date_format?: string
  notes?: string
  trial_ends_at?: string
  contract_start?: string
  contract_end?: string
  created_at?: string
  logo_url?: string
}

interface AuditRow {
  id: string
  occurred_at: string
  event_type: string
  actor: string
  notes?: string
}

// ── Constants — match exactly what the DB stores ────────────────────────────────
const PLAN_TIERS    = ['STANDARD', 'PROFESSIONAL', 'ENTERPRISE', 'TRIAL']
const COMPANY_TYPES = ['Life Insurance', 'Health Insurance', 'P&C Insurance', 'Reinsurer', 'MGA', 'Broker', 'Other']
const STATUSES      = ['ACTIVE', 'SUSPENDED', 'TRIAL', 'INACTIVE']
const TIMEZONES     = ['Asia/Kolkata', 'UTC', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Europe/London']
const DATE_FORMATS  = ['DD/MM/YYYY', 'DD-MMM-YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD']

const planColor: Record<string, React.CSSProperties> = {
  TRIAL:        { background: 'rgba(251,191,36,0.1)',  color: '#fbbf24', border: '1px solid rgba(251,191,36,0.25)' },
  STANDARD:     { background: 'rgba(96,165,250,0.1)',  color: '#60a5fa', border: '1px solid rgba(96,165,250,0.25)' },
  PROFESSIONAL: { background: 'rgba(0,212,170,0.1)',   color: '#00d4aa', border: '1px solid rgba(0,212,170,0.25)'  },
  ENTERPRISE:   { background: 'rgba(168,85,247,0.1)',  color: '#c084fc', border: '1px solid rgba(168,85,247,0.25)' },
}

const statusColor: Record<string, string> = {
  ACTIVE: '#22c55e', SUSPENDED: '#ef4444', TRIAL: '#fbbf24', INACTIVE: '#6b7280',
}

// ── Helpers ────────────────────────────────────────────────────────────────────
const MS = {
  content: { background: '#0d1521', border: '1px solid rgba(255,255,255,0.09)' },
  header:  { background: '#0d1521' },
  footer:  { background: '#0d1521' },
}

const sectionStyle: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 10, padding: '20px 24px', marginBottom: 16,
}
const sectionTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#6b7280',
  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16,
}

function PlanBadge({ tier }: { tier: string }) {
  const s = planColor[tier] || { background: 'rgba(255,255,255,0.05)', color: '#9ca3af', border: '1px solid rgba(255,255,255,0.1)' }
  return (
    <span style={{ ...s, padding: '3px 9px', borderRadius: 5, fontSize: 11, fontWeight: 600, fontFamily: 'var(--font-mono, monospace)' }}>
      {tier}
    </span>
  )
}

function StatusDot({ status }: { status: string }) {
  const color = statusColor[status] || '#6b7280'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, display: 'inline-block',
        boxShadow: status === 'ACTIVE' ? `0 0 0 2px ${color}33` : 'none' }}/>
      <span style={{ color }}>{status}</span>
    </span>
  )
}

function TenantAvatar({ name }: { name: string }) {
  const initials = name.split(' ').map((w: string) => w[0]).join('').slice(0, 2).toUpperCase()
  return (
    <div style={{
      width: 34, height: 34, borderRadius: 8,
      background: 'rgba(0,212,170,0.12)', color: '#00d4aa',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 12, fontWeight: 700, flexShrink: 0,
    }}>
      {initials}
    </div>
  )
}

function relTime(iso?: string) {
  if (!iso) return '—'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60)      return 'Just now'
  if (diff < 3600)    return `${Math.floor(diff/60)}m ago`
  if (diff < 86400)   return `${Math.floor(diff/3600)}h ago`
  if (diff < 7*86400) return `${Math.floor(diff/86400)}d ago`
  return new Date(iso).toLocaleDateString()
}

// ── Shared Tenant Form ─────────────────────────────────────────────────────────
function TenantForm({ form }: { form: any }) {
  return (
    <>
      {/* Carrier Information */}
      <div style={sectionStyle}>
        <div style={sectionTitle}>Carrier Information</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <Form.Item name="tenant_code" label="Tenant Code *"
            rules={[{ required: true, message: 'Required' }, { pattern: /^[A-Z0-9_-]+$/, message: 'Uppercase, numbers, dashes only. e.g. ABC-LIFE' }]}>
            <Input placeholder="e.g. ABC-LIFE" style={{ fontFamily: 'var(--font-mono, monospace)' }}/>
          </Form.Item>
          <Form.Item name="contact_name" label="Contact Name *" rules={[{ required: true, message: 'Required' }]}>
            <Input placeholder="Jane Smith"/>
          </Form.Item>
          <Form.Item name="tenant_name" label="Carrier Name *" rules={[{ required: true, message: 'Required' }]}>
            <Input placeholder="e.g. ABC Life Insurance Co."/>
          </Form.Item>
          <Form.Item name="contact_email" label="Contact Email *"
            rules={[{ required: true, message: 'Required' }, { type: 'email', message: 'Valid email required' }]}>
            <Input placeholder="admin@carrier.com"/>
          </Form.Item>
          <Form.Item name="company_type" label="Company Type" initialValue="Life Insurance" help="Type of insurance carrier">
            <Select placeholder="Select type…">
              {COMPANY_TYPES.map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select>
          </Form.Item>
          <Form.Item name="contact_phone" label="Contact Phone">
            <Input placeholder="+91 98765 43210"/>
          </Form.Item>
          <Form.Item name="naic_code" label="NAIC Code" help="IRDAI or NAIC registration number of the carrier">
            <Input placeholder="e.g. 12345"/>
          </Form.Item>
          <Form.Item name="plan_tier" label="Plan Tier" initialValue="STANDARD" help="Controls feature access and API rate limits for this tenant">
            <Select placeholder="Select plan…">
              {PLAN_TIERS.map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select>
          </Form.Item>
          <Form.Item name="state_of_domicile" label="State of Domicile" help="2-letter state code where the carrier is registered (e.g. MH, DL, KA)">
            <Input placeholder="e.g. MH" maxLength={2}/>
          </Form.Item>
          <Form.Item name="max_users" label="Max Users" initialValue={50} help="Maximum number of user accounts allowed for this tenant">
            <InputNumber min={1} max={1000} style={{ width: '100%' }} placeholder="e.g. 50"/>
          </Form.Item>
        </div>
      </div>

      {/* Limits & Contract */}
      <div style={sectionStyle}>
        <div style={sectionTitle}>Limits &amp; Contract</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
          <Form.Item name="max_decisions_per_month" label="Max Decisions / Month" initialValue={10000} help="Monthly proposal evaluation quota — alerts fire at 80% usage">
            <InputNumber min={100} max={1000000} style={{ width: '100%' }}
              formatter={v => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
              parser={(v: any) => Number(v!.replace(/,/g, ''))}/>
          </Form.Item>
          <Form.Item name="contract_start" label="Contract Start" help="Start date of the platform subscription agreement">
            <Input type="date"/>
          </Form.Item>
          <Form.Item name="contract_end" label="Contract End" help="End date of the subscription — tenant is flagged for renewal 30 days before">
            <Input type="date"/>
          </Form.Item>
        </div>
        <Form.Item name="trial_ends_at" label="Trial Ends At" style={{ maxWidth: 320 }} help="If set, tenant switches to read-only mode after this datetime until a plan is confirmed">
          <Input type="datetime-local"/>
        </Form.Item>
        <Form.Item name="notes" label="Notes">
          <Input.TextArea rows={3} placeholder="Internal notes about this tenant…"/>
        </Form.Item>
      </div>

      {/* Settings */}
      <div style={sectionStyle}>
        <div style={sectionTitle}>Settings</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <Form.Item name="timezone" label="Timezone" initialValue="Asia/Kolkata" help="All timestamps in reports and logs will use this timezone">
            <Select>{TIMEZONES.map(t => <Option key={t} value={t}>{t}</Option>)}</Select>
          </Form.Item>
          <Form.Item name="date_format" label="Date Format" initialValue="DD-MMM-YYYY" help="Format used across all dates shown in the UI and exported files">
            <Select>{DATE_FORMATS.map(f => <Option key={f} value={f}>{f}</Option>)}</Select>
          </Form.Item>
          <Form.Item name="sso_enabled" label="SSO Enabled" valuePropName="checked" initialValue={false}>
            <Switch/>
          </Form.Item>
          <Form.Item name="api_enabled" label="API Access" valuePropName="checked" initialValue={true}>
            <Switch/>
          </Form.Item>
        </div>
        <Form.Item name="logo_url" label="Logo URL">
          <Input placeholder="https://cdn.example.com/logo.png"/>
        </Form.Item>
      </div>
    </>
  )
}

// ── All Tenants Tab ────────────────────────────────────────────────────────────
function AllTenantsTab({ onSelect, refresh }: { onSelect: (t: Tenant) => void; refresh: number }) {
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch]   = useState('')
  const [statusF, setStatusF] = useState('ALL')
  const [planF, setPlanF]     = useState('ALL')
  const [editT, setEditT]     = useState<Tenant|null>(null)
  const [saving, setSaving]   = useState(false)
  const [ef]                  = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { const r = await api.get('/tenants/'); setTenants(Array.isArray(r.data) ? r.data : []) }
    catch(e: any) { message.error(e?.response?.data?.detail || 'Failed to load tenants') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [refresh])

  const filtered = tenants.filter(t => {
    const q    = search.toLowerCase()
    const sOk  = !q || t.tenant_name.toLowerCase().includes(q) || t.tenant_code.toLowerCase().includes(q) || (t.contact_email||'').toLowerCase().includes(q)
    const stOk = statusF === 'ALL' || t.status === statusF
    const pOk  = planF   === 'ALL' || t.plan_tier === planF
    return sOk && stOk && pOk
  })

  const openEdit = (t: Tenant) => {
    setEditT(t)
    ef.setFieldsValue({
      ...t,
      contract_start: t.contract_start?.slice(0, 10),
      contract_end:   t.contract_end?.slice(0, 10),
      trial_ends_at:  t.trial_ends_at?.slice(0, 16),
    })
  }

  const doEdit = async () => {
    if (!editT) return
    setSaving(true)
    try {
      await api.patch(`/tenants/${editT.id}`, ef.getFieldsValue())
      message.success('Tenant updated'); setEditT(null); load()
    } catch(e: any) { message.error(e?.response?.data?.detail || 'Update failed') }
    finally { setSaving(false) }
  }

  const toggleStatus = async (t: Tenant) => {
    const action = t.status === 'ACTIVE' ? 'suspend' : 'activate'
    try { await api.post(`/tenants/${t.id}/${action}`); message.success(`Tenant ${action}d`); load() }
    catch(e: any) { message.error(e?.response?.data?.detail || 'Failed') }
  }

  const cols = [
    {
      title: 'Carrier', dataIndex: 'tenant_name', width: 240,
      render: (v: string, t: Tenant) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <TenantAvatar name={v}/>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{v}</div>
            <div style={{ fontSize: 11, color: '#6b7280', fontFamily: 'var(--font-mono, monospace)' }}>{t.tenant_code}</div>
          </div>
        </div>
      ),
    },
    { title: 'Plan',   dataIndex: 'plan_tier', width: 130, render: (v: string) => <PlanBadge tier={v}/> },
    { title: 'Status', dataIndex: 'status',    width: 110, render: (v: string) => <StatusDot status={v}/> },
    {
      title: 'Contact', dataIndex: 'contact_email', width: 190,
      render: (v: string, t: Tenant) => (
        <div>
          <div style={{ fontSize: 12, color: '#9ca3af' }}>{t.contact_name || '—'}</div>
          <div style={{ fontSize: 11, color: '#6b7280' }}>{v || '—'}</div>
        </div>
      ),
    },
    {
      title: 'Usage', width: 150,
      render: (_: any, t: Tenant) => {
        const pct = t.max_decisions_per_month ? Math.round((t.decisions_this_month||0) / t.max_decisions_per_month * 100) : 0
        const barColor = pct > 90 ? '#ef4444' : pct > 70 ? '#fbbf24' : '#00d4aa'
        return (
          <div>
            <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4 }}>
              {(t.decisions_this_month||0).toLocaleString()} / {(t.max_decisions_per_month||0).toLocaleString()}
            </div>
            <div style={{ height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${Math.min(pct,100)}%`, background: barColor, borderRadius: 2, transition: 'width 0.3s' }}/>
            </div>
          </div>
        )
      },
    },
    {
      title: 'Users', dataIndex: 'max_users', width: 80,
      render: (v: number) => <span style={{ fontSize: 12, color: '#9ca3af' }}>max {v}</span>,
    },
    {
      title: 'Features', width: 90,
      render: (_: any, t: Tenant) => (
        <div style={{ display: 'flex', gap: 6 }}>
          {t.api_enabled && <span title="API enabled"><ApiOutlined style={{ color: '#00d4aa', fontSize: 14 }}/></span>}
          {t.sso_enabled && <span title="SSO enabled"><GlobalOutlined style={{ color: '#60a5fa', fontSize: 14 }}/></span>}
        </div>
      ),
    },
    {
      title: 'Actions', width: 130,
      render: (_: any, t: Tenant) => (
        <div style={{ display: 'flex', gap: 5 }}>
          <Button size="small" icon={<AuditOutlined/>} onClick={() => onSelect(t)}
            style={{ borderColor: 'rgba(96,165,250,0.25)', color: '#60a5fa', background: 'transparent' }}
            title="View detail"/>
          <Button size="small" icon={<EditOutlined/>} onClick={() => openEdit(t)}
            style={{ borderColor: 'rgba(0,212,170,0.25)', color: '#00d4aa', background: 'transparent' }}
            title="Edit"/>
          <Popconfirm
            title={`${t.status === 'ACTIVE' ? 'Suspend' : 'Activate'} ${t.tenant_name}?`}
            onConfirm={() => toggleStatus(t)} okText="Yes" cancelText="No">
            <Button size="small"
              icon={t.status === 'ACTIVE' ? <StopOutlined/> : <CheckOutlined/>}
              style={{
                borderColor: t.status === 'ACTIVE' ? 'rgba(239,68,68,0.25)' : 'rgba(34,197,94,0.25)',
                color: t.status === 'ACTIVE' ? '#f87171' : '#4ade80', background: 'transparent',
              }}
              title={t.status === 'ACTIVE' ? 'Suspend' : 'Activate'}
            />
          </Popconfirm>
        </div>
      ),
    },
  ]

  return (
    <>
      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: 'Total Tenants', value: tenants.length,                                                    color: '#00d4aa' },
          { label: 'Active',        value: tenants.filter(t => t.status === 'ACTIVE').length,                 color: '#22c55e' },
          { label: 'Suspended',     value: tenants.filter(t => t.status === 'SUSPENDED').length,              color: '#ef4444' },
          { label: 'Enterprise',    value: tenants.filter(t => t.plan_tier === 'ENTERPRISE').length,          color: '#c084fc' },
        ].map(s => (
          <div key={s.label} style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 10, padding: '14px 16px' }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: s.color, fontVariantNumeric: 'tabular-nums' }}>{s.value}</div>
            <div style={{ fontSize: 11, color: '#6b7280', marginTop: 3 }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}>
        <Input
          prefix={<SearchOutlined style={{ color: '#6b7280' }}/>}
          placeholder="Search by name, code or email…"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ maxWidth: 280 }} allowClear
        />
        <Select value={statusF} onChange={setStatusF} style={{ width: 150 }}>
          <Option value="ALL">All statuses</Option>
          {STATUSES.map(s => <Option key={s} value={s}>{s}</Option>)}
        </Select>
        <Select value={planF} onChange={setPlanF} style={{ width: 150 }}>
          <Option value="ALL">All plans</Option>
          {PLAN_TIERS.map(p => <Option key={p} value={p}>{p}</Option>)}
        </Select>
        <Button icon={<ReloadOutlined/>} onClick={load} loading={loading} style={{ marginLeft: 'auto' }}>
          Refresh
        </Button>
      </div>

      {/* Table */}
      {loading
        ? <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}><Spin size="large"/></div>
        : <Table dataSource={filtered} columns={cols} rowKey="id" size="middle"
            pagination={{ pageSize: 15, showSizeChanger: false }}
            locale={{ emptyText: 'No tenants found — create your first carrier in New Tenant tab.' }}/>
      }

      {/* Edit Modal */}
      <Modal
        title={<span style={{ color: '#e2e8f0', fontWeight: 600 }}>Edit Tenant — {editT?.tenant_name}</span>}
        open={!!editT} onCancel={() => setEditT(null)} onOk={doEdit}
        confirmLoading={saving} okText="Save changes" width={800} styles={MS}>
        <div style={{ maxHeight: '70vh', overflowY: 'auto', paddingRight: 8 }}>
          <Form form={ef} layout="vertical" requiredMark={false} style={{ marginTop: 16 }}>
            <TenantForm form={ef}/>
          </Form>
        </div>
      </Modal>
    </>
  )
}

// ── New Tenant Tab ─────────────────────────────────────────────────────────────
function NewTenantTab({ onCreated }: { onCreated: () => void }) {
  const [form]                = Form.useForm()
  const [loading, setLoading] = useState(false)
  const { user: me }          = useAuthStore()

  const go = async () => {
    try { await form.validateFields() } catch { return }
    setLoading(true)
    try {
      const v = form.getFieldsValue()
      v.tenant_code = (v.tenant_code || '').toUpperCase()
      await api.post('/tenants/', { ...v, created_by: me?.username })
      message.success(`✅ Tenant ${v.tenant_name} created. System config defaults auto-provisioned.`)
      form.resetFields()
      onCreated()
    } catch(e: any) { message.error(e?.response?.data?.detail || 'Failed to create tenant') }
    finally { setLoading(false) }
  }

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 20 }}>
        Register a new insurance carrier. System config and defaults are auto-provisioned.
      </div>
      <Form form={form} layout="vertical" requiredMark={false}>
        <TenantForm form={form}/>
        <Button type="primary" icon={<PlusOutlined/>} loading={loading} onClick={go} size="large" block
          style={{ height: 44, fontWeight: 600 }}>
          Register Tenant
        </Button>
      </Form>
    </div>
  )
}

// ── Tenant Detail Tab ──────────────────────────────────────────────────────────
function TenantDetailTab({ tenant, onRefresh }: { tenant: Tenant|null; onRefresh: () => void }) {
  const [detail, setDetail]     = useState<Tenant|null>(null)
  const [audit, setAudit]       = useState<AuditRow[]>([])
  const [loading, setLoading]   = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [saving, setSaving]     = useState(false)
  const [ef]                    = Form.useForm()

  useEffect(() => {
    if (!tenant) return
    setLoading(true)
    Promise.all([
      api.get(`/tenants/${tenant.id}`),
      api.get(`/tenants/${tenant.id}/audit`),
    ]).then(([d, a]) => {
      setDetail(d.data)
      setAudit(Array.isArray(a.data) ? a.data : [])
    }).catch(() => message.error('Failed to load tenant detail'))
    .finally(() => setLoading(false))
  }, [tenant])

  const openEdit = () => {
    if (!detail) return
    ef.setFieldsValue({
      ...detail,
      contract_start: detail.contract_start?.slice(0, 10),
      contract_end:   detail.contract_end?.slice(0, 10),
      trial_ends_at:  detail.trial_ends_at?.slice(0, 16),
    })
    setEditOpen(true)
  }

  const doEdit = async () => {
    if (!detail) return
    setSaving(true)
    try {
      await api.patch(`/tenants/${detail.id}`, ef.getFieldsValue())
      message.success('Tenant updated')
      setEditOpen(false)
      const r = await api.get(`/tenants/${detail.id}`)
      setDetail(r.data)
      onRefresh()
    } catch(e: any) { message.error(e?.response?.data?.detail || 'Update failed') }
    finally { setSaving(false) }
  }

  if (!tenant) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0', color: '#6b7280' }}>
        <BankOutlined style={{ fontSize: 40, marginBottom: 16, display: 'block' }}/>
        <div style={{ fontSize: 14 }}>
          Click <strong style={{ color: '#60a5fa' }}>View Detail</strong> on any tenant in the All Tenants tab
        </div>
      </div>
    )
  }

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}><Spin size="large"/></div>
  if (!detail) return null

  const pct = detail.max_decisions_per_month
    ? Math.round((detail.decisions_this_month||0) / detail.max_decisions_per_month * 100) : 0
  const barColor = pct > 90 ? '#ef4444' : pct > 70 ? '#fbbf24' : '#00d4aa'

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 20 }}>
      {/* Left */}
      <div>
        {/* Header */}
        <div style={{ ...sectionStyle, display: 'flex', alignItems: 'center', gap: 16 }}>
          <TenantAvatar name={detail.tenant_name}/>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 17, fontWeight: 700, color: '#e2e8f0' }}>{detail.tenant_name}</div>
            <div style={{ fontSize: 12, color: '#6b7280', fontFamily: 'var(--font-mono, monospace)', marginTop: 2 }}>
              {detail.tenant_code} · ID: {detail.id?.slice(0, 8)}…
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <PlanBadge tier={detail.plan_tier}/>
            <StatusDot status={detail.status}/>
            <Button size="small" icon={<EditOutlined/>} onClick={openEdit}
              style={{ borderColor: 'rgba(0,212,170,0.25)', color: '#00d4aa', background: 'transparent' }}>
              Edit
            </Button>
          </div>
        </div>

        {/* Usage bar */}
        <div style={sectionStyle}>
          <div style={sectionTitle}>Monthly Usage</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: '#9ca3af' }}>Decisions this month</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: pct > 90 ? '#ef4444' : '#e2e8f0' }}>
              {(detail.decisions_this_month||0).toLocaleString()} / {(detail.max_decisions_per_month||0).toLocaleString()}
              <span style={{ fontSize: 11, color: '#6b7280', marginLeft: 6 }}>({pct}%)</span>
            </span>
          </div>
          <div style={{ height: 6, borderRadius: 3, background: 'rgba(255,255,255,0.08)' }}>
            <div style={{ height: '100%', width: `${Math.min(pct,100)}%`, background: barColor, borderRadius: 3, transition: 'width 0.4s' }}/>
          </div>
        </div>

        {/* Info grid */}
        <div style={sectionStyle}>
          <div style={sectionTitle}>Carrier Information</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 24px' }}>
            {[
              { label: 'Company Type',      value: detail.company_type },
              { label: 'NAIC Code',         value: detail.naic_code },
              { label: 'State of Domicile', value: detail.state_of_domicile },
              { label: 'Timezone',          value: detail.timezone },
              { label: 'Date Format',       value: detail.date_format },
              { label: 'Max Users',         value: detail.max_users },
              { label: 'Contract Start',    value: detail.contract_start?.slice(0,10) },
              { label: 'Contract End',      value: detail.contract_end?.slice(0,10) },
              { label: 'Trial Ends',        value: detail.trial_ends_at?.slice(0,10) },
              { label: 'SSO',               value: detail.sso_enabled ? '✓ Enabled' : 'Disabled' },
              { label: 'API Access',        value: detail.api_enabled ? '✓ Enabled' : 'Disabled' },
              { label: 'Created',           value: relTime(detail.created_at) },
            ].map(f => (
              <div key={f.label} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: 8 }}>
                <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 2 }}>{f.label}</div>
                <div style={{ fontSize: 13, color: '#e2e8f0' }}>{f.value ?? '—'}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Contact */}
        <div style={sectionStyle}>
          <div style={sectionTitle}>Primary Contact</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
            {[
              { label: 'Name',  value: detail.contact_name },
              { label: 'Email', value: detail.contact_email },
              { label: 'Phone', value: detail.contact_phone },
            ].map(f => (
              <div key={f.label}>
                <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 2 }}>{f.label}</div>
                <div style={{ fontSize: 13, color: '#e2e8f0' }}>{f.value || '—'}</div>
              </div>
            ))}
          </div>
          {detail.notes && (
            <div style={{ marginTop: 12, padding: '10px 14px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, fontSize: 13, color: '#9ca3af' }}>
              {detail.notes}
            </div>
          )}
        </div>
      </div>

      {/* Right — audit log */}
      <div>
        <div style={sectionStyle}>
          <div style={sectionTitle}>Audit Log</div>
          {audit.length === 0
            ? <div style={{ color: '#6b7280', fontSize: 13 }}>No audit events recorded.</div>
            : audit.map(a => (
              <div key={a.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: 10, marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#e2e8f0' }}>{a.event_type}</span>
                  <span style={{ fontSize: 11, color: '#6b7280' }}>{relTime(a.occurred_at)}</span>
                </div>
                <div style={{ fontSize: 11, color: '#6b7280' }}>by {a.actor}</div>
                {a.notes && <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 3 }}>{a.notes}</div>}
              </div>
            ))
          }
        </div>
      </div>

      {/* Edit Modal */}
      <Modal
        title={<span style={{ color: '#e2e8f0', fontWeight: 600 }}>Edit Tenant — {detail.tenant_name}</span>}
        open={editOpen} onCancel={() => setEditOpen(false)} onOk={doEdit}
        confirmLoading={saving} okText="Save changes" width={800} styles={MS}>
        <div style={{ maxHeight: '70vh', overflowY: 'auto', paddingRight: 8 }}>
          <Form form={ef} layout="vertical" requiredMark={false} style={{ marginTop: 16 }}>
            <TenantForm form={ef}/>
          </Form>
        </div>
      </Modal>
    </div>
  )
}

// ── Page Shell ─────────────────────────────────────────────────────────────────
export default function TenantManagementPage() {
  const [refreshKey, setRefreshKey]   = useState(0)
  const [selectedTenant, setSelected] = useState<Tenant|null>(null)
  const [activeTab, setActiveTab]     = useState('list')
  const { user: me }                  = useAuthStore()

  if (me && me.role !== 'super_admin' && me.role !== 'admin') {
    return (
      <div style={{ padding: '60px 36px', textAlign: 'center', color: '#6b7280' }}>
        <BankOutlined style={{ fontSize: 48, marginBottom: 16, display: 'block' }}/>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#e2e8f0', marginBottom: 8 }}>Access Restricted</div>
        <div style={{ fontSize: 13 }}>Tenant management is only available to Admin users.</div>
      </div>
    )
  }

  const handleSelect = (t: Tenant) => { setSelected(t); setActiveTab('detail') }

  const tabs = [
    {
      key: 'list',
      label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}><BankOutlined/>All Tenants</span>,
      children: <AllTenantsTab onSelect={handleSelect} refresh={refreshKey}/>,
    },
    {
      key: 'create',
      label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}><PlusOutlined/>New Tenant</span>,
      children: <NewTenantTab onCreated={() => { setRefreshKey(k => k+1); setActiveTab('list') }}/>,
    },
    {
      key: 'detail',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <AuditOutlined/>
          {selectedTenant ? selectedTenant.tenant_name : 'Tenant Detail'}
        </span>
      ),
      children: <TenantDetailTab tenant={selectedTenant} onRefresh={() => setRefreshKey(k => k+1)}/>,
    },
  ]

  return (
    <div style={{ padding: '32px 36px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontWeight: 700, fontSize: 20, color: '#e2e8f0', margin: 0, letterSpacing: '-0.02em', display: 'flex', alignItems: 'center', gap: 10 }}>
          <BankOutlined style={{ color: '#00d4aa' }}/>Tenant Management
        </h1>
        <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          Register and manage insurance carrier tenants. Admin and Super Admin only.
        </p>
      </div>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabs}
        tabBarStyle={{ borderBottom: '1px solid rgba(255,255,255,0.07)', marginBottom: 24 }}
      />
    </div>
  )
}
