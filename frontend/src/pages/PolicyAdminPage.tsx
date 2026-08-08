// PolicyAdminPage.tsx
import { useState, useEffect } from 'react'
import {
  Table, Tag, Button, Input, Select, Modal, Form, InputNumber,
  DatePicker, message, Spin, Drawer, Descriptions, Timeline,
  Popconfirm,
} from 'antd'
import {
  SearchOutlined, ReloadOutlined, DollarOutlined,
  FileTextOutlined, StopOutlined, RedoOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { Titled, CellHint } from '../components/ColHint'

const { Option } = Select

const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 12, padding: '20px 24px', marginBottom: 16,
}

const STATUS_COLOR: Record<string, string> = {
  PENDING_ACCEPTANCE:    'default',
  PENDING_FIRST_PREMIUM: 'gold',
  IN_FORCE:              'success',
  LAPSED:                'error',
  REVIVED:               'processing',
  SURRENDERED:           'default',
  MATURED:               'purple',
  CLAIMED:               'magenta',
}

const STATUS_LABEL: Record<string, string> = {
  PENDING_ACCEPTANCE:    'Pending Acceptance',
  PENDING_FIRST_PREMIUM: 'Awaiting Premium',
  IN_FORCE:              'In Force',
  LAPSED:                'Lapsed',
  REVIVED:               'Revived',
  SURRENDERED:           'Surrendered',
  MATURED:               'Matured',
  CLAIMED:               'Claimed',
}

function PolicyListTab() {
  const [policies, setPolicies]   = useState<any[]>([])
  const [statusCounts, setCounts] = useState<Record<string, number>>({})
  const [loading, setLoading]     = useState(true)
  const [total, setTotal]         = useState(0)
  const [page, setPage]           = useState(1)
  const [status, setStatus]       = useState('')
  const [search, setSearch]       = useState('')
  const [selectedPolicy, setSelected] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get('/policy/list', { params: { page, per_page: 30, status, search } })
      setPolicies(r.data.policies || [])
      setTotal(r.data.total || 0)
      setCounts(r.data.status_counts || {})
    } catch { setPolicies([]) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, status])

  const totalAll = Object.values(statusCounts).reduce((s, c) => s + c, 0)

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 20 }}>
        <div style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 8, padding: 12 }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#00d4aa' }}>{totalAll}</div>
          <div style={{ fontSize: 10, color: '#6b7280' }}>Total Policies</div>
        </div>
        {Object.entries(statusCounts).map(([s, c]) => (
          <div key={s} style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 18, fontWeight: 700,
              color: s === 'IN_FORCE' ? '#22c55e' : s === 'LAPSED' ? '#ef4444' : '#9ca3af' }}>
              {c}
            </div>
            <div style={{ fontSize: 10, color: '#6b7280' }}>{STATUS_LABEL[s] || s}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Input
          prefix={<SearchOutlined style={{ color: '#6b7280' }}/>}
          placeholder="Search policy number, applicant ref, name..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          onPressEnter={() => { setPage(1); load() }}
          style={{ maxWidth: 320 }}
        />
        <Select value={status || undefined} onChange={(v: any) => { setStatus(v || ''); setPage(1) }}
          placeholder="All statuses" allowClear style={{ width: 200 }}>
          {Object.keys(STATUS_LABEL).map(s => (
            <Option key={s} value={s}>{STATUS_LABEL[s]}</Option>
          ))}
        </Select>
        <Button icon={<ReloadOutlined/>} onClick={load} loading={loading}>Refresh</Button>
      </div>

      <Table
        dataSource={policies} rowKey="id" loading={loading} size="small"
        onRow={(r: any) => ({ onClick: () => setSelected(r.id), style: { cursor: 'pointer' } })}
        pagination={{ current: page, pageSize: 30, total, onChange: (p: number) => setPage(p), showSizeChanger: false }}
        columns={[
          { title: Titled('Policy Number', 'policy_number'), dataIndex: 'policy_number', width: 160,
            render: (v: string) => <code style={{ fontSize: 12, color: '#00d4aa', fontWeight: 600 }}>{v}</code> },
          { title: 'Applicant', width: 180,
            render: (_: any, r: any) => r.applicant_name || r.applicant_ref },
          { title: Titled('Product', 'product_code'), dataIndex: 'product_code', width: 130 },
          { title: Titled('Sum Assured', 'sum_assured'), dataIndex: 'sum_assured', width: 130,
            render: (v: number) => `₹${Number(v).toLocaleString('en-IN')}` },
          { title: Titled('Premium', 'annual_premium'), dataIndex: 'annual_premium', width: 120,
            render: (v: number) => `₹${Number(v).toLocaleString('en-IN')}` },
          { title: Titled('Status', 'status'), dataIndex: 'status', width: 150,
            render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_LABEL[v] || v}</Tag> },
          { title: Titled('Next Premium Due', 'next_premium_due'), dataIndex: 'next_premium_due', width: 140,
            render: (v: string) => v || '—' },
          { title: Titled('Issue Date', 'issue_date'), dataIndex: 'issue_date', width: 120,
            render: (v: string) => v || '—' },
        ]}
      />

      {selectedPolicy && (
        <PolicyDetailDrawer
          policyId={selectedPolicy}
          onClose={() => setSelected(null)}
          onUpdate={load}
        />
      )}
    </div>
  )
}

function PolicyDetailDrawer({ policyId, onClose, onUpdate }: {
  policyId: string; onClose: () => void; onUpdate: () => void
}) {
  const [data, setData]       = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [premiumModal, setPremiumModal] = useState(false)
  const [premiumForm]         = Form.useForm()
  const [actionLoading, setActionLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get(`/policy/${policyId}`)
      setData(r.data)
    } catch { message.error('Failed to load policy') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [policyId])

  const recordPremium = async () => {
    try {
      const v = await premiumForm.validateFields()
      setActionLoading(true)
      await api.post(`/policy/${policyId}/premium`, {
        amount_paid: v.amount_paid,
        paid_date: v.paid_date.format('YYYY-MM-DD'),
        payment_mode: v.payment_mode,
        receipt_number: v.receipt_number,
      })
      message.success('Premium recorded')
      setPremiumModal(false)
      premiumForm.resetFields()
      load(); onUpdate()
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || 'Failed')
    } finally { setActionLoading(false) }
  }

  const doAction = async (action: 'lapse' | 'revive' | 'surrender') => {
    const reason = prompt(`Reason for ${action}:`)
    if (!reason) return
    setActionLoading(true)
    try {
      await api.post(`/policy/${policyId}/${action}`, { reason })
      message.success(`Policy ${action}d`)
      load(); onUpdate()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Action failed')
    } finally { setActionLoading(false) }
  }

  const openLetter = () => {
    const p = data?.policy
    const params = new URLSearchParams({
      applicant_ref: p.applicant_ref || '',
      product_code:  p.product_code || '',
      face_amount:   String(p.sum_assured || 0),
      premium:       String(p.annual_premium || 0),
      risk_class:    p.risk_class || '',
      outcome:       'APPROVED',
      case_number:   p.policy_number || '',
    })
    const token = localStorage.getItem('riskuw_token')
    fetch(`/system/letter-templates/TPL-APPROVED-001/generate?${params}`, {
      headers: { Authorization: `Bearer ${token}` }
    }).then(r => r.blob()).then(blob => window.open(URL.createObjectURL(blob), '_blank'))
  }

  const p = data?.policy

  return (
    <Drawer
      title={p ? <span>Policy <code style={{ color: '#00d4aa' }}>{p.policy_number}</code></span> : 'Loading...'}
      open width={640} onClose={onClose}
    >
      {loading || !p ? <Spin/> : (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Tag color={STATUS_COLOR[p.status]} style={{ fontSize: 13, padding: '4px 12px' }}>
              {STATUS_LABEL[p.status]}
            </Tag>
            {p.applicant_name && <span style={{ fontSize: 14, color: '#e2e8f0' }}>{p.applicant_name}</span>}
          </div>

          <Descriptions column={2} size="small" bordered style={{ marginBottom: 20 }}>
            <Descriptions.Item label="Applicant Ref">{p.applicant_ref}</Descriptions.Item>
            <Descriptions.Item label="Product">{p.product_code}</Descriptions.Item>
            <Descriptions.Item label="Sum Assured">₹{Number(p.sum_assured).toLocaleString('en-IN')}</Descriptions.Item>
            <Descriptions.Item label="Annual Premium">₹{Number(p.annual_premium).toLocaleString('en-IN')}</Descriptions.Item>
            <Descriptions.Item label="Premium Mode">{p.premium_mode}</Descriptions.Item>
            <Descriptions.Item label="Modal Premium">₹{Number(p.modal_premium || 0).toLocaleString('en-IN')}</Descriptions.Item>
            <Descriptions.Item label="Risk Class">{p.risk_class || '—'}</Descriptions.Item>
            <Descriptions.Item label="Term">{p.coverage_term_yrs || '—'} years</Descriptions.Item>
            <Descriptions.Item label="Issue Date">{p.issue_date || '—'}</Descriptions.Item>
            <Descriptions.Item label="Commencement">{p.commencement_date || '—'}</Descriptions.Item>
            <Descriptions.Item label="Maturity Date">{p.maturity_date || '—'}</Descriptions.Item>
            <Descriptions.Item label="Next Premium Due">{p.next_premium_due || '—'}</Descriptions.Item>
            <Descriptions.Item label="Grace Period End">{p.grace_period_end || '—'}</Descriptions.Item>
            <Descriptions.Item label="Total Premiums Paid">₹{Number(p.total_premiums_paid || 0).toLocaleString('en-IN')}</Descriptions.Item>
            {p.nominee_name && <>
              <Descriptions.Item label="Nominee">{p.nominee_name}</Descriptions.Item>
              <Descriptions.Item label="Relation">{p.nominee_relation}</Descriptions.Item>
            </>}
            {p.surrender_value && (
              <Descriptions.Item label="Surrender Value" span={2}>
                ₹{Number(p.surrender_value).toLocaleString('en-IN')}
              </Descriptions.Item>
            )}
          </Descriptions>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 }}>
            {(p.status === 'PENDING_ACCEPTANCE' || p.status === 'PENDING_FIRST_PREMIUM' || p.status === 'LAPSED') && (
              <Button type="primary" icon={<DollarOutlined/>} onClick={() => setPremiumModal(true)}>
                Record Premium
              </Button>
            )}
            <Button icon={<FileTextOutlined/>} onClick={openLetter}>Policy Letter</Button>
            {p.status === 'IN_FORCE' && (
              <Popconfirm title="Lapse this policy?" onConfirm={() => doAction('lapse')}>
                <Button danger icon={<StopOutlined/>} loading={actionLoading}>Lapse</Button>
              </Popconfirm>
            )}
            {p.status === 'LAPSED' && (
              <Button icon={<RedoOutlined/>} onClick={() => doAction('revive')} loading={actionLoading}>
                Revive
              </Button>
            )}
            {(p.status === 'IN_FORCE' || p.status === 'LAPSED') && (
              <Popconfirm title="Surrender this policy? This is irreversible." onConfirm={() => doAction('surrender')}>
                <Button danger loading={actionLoading}>Surrender</Button>
              </Popconfirm>
            )}
          </div>

          <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase',
            letterSpacing: '0.08em', marginBottom: 10 }}>
            Premium History
          </div>
          {data.premium_history?.length === 0 ? (
            <div style={{ color: '#6b7280', fontSize: 13, marginBottom: 24 }}>No premiums recorded yet.</div>
          ) : (
            <Table
              dataSource={data.premium_history} rowKey={(r: any) => r.due_date + r.receipt_number}
              size="small" pagination={false} style={{ marginBottom: 24 }}
              columns={[
                { title: Titled('Due Date', 'due_date'), dataIndex: 'due_date', width: 110 },
                { title: Titled('Paid Date', 'paid_date'), dataIndex: 'paid_date', width: 110, render: (v: string) => v || '—' },
                { title: Titled('Amount', 'amount_paid'), dataIndex: 'amount_paid', width: 110,
                  render: (v: number) => v ? `₹${Number(v).toLocaleString('en-IN')}` : '—' },
                { title: Titled('Mode', 'payment_mode'), dataIndex: 'payment_mode', width: 100, render: CellHint('payment_mode') },
                { title: Titled('Receipt', 'receipt_number'), dataIndex: 'receipt_number', width: 110 },
                { title: Titled('Status', 'status'), dataIndex: 'status', width: 90,
                  render: (v: string) => <Tag color={v === 'PAID' ? 'success' : 'default'} style={{ fontSize: 10 }}>{v}</Tag> },
              ]}
            />
          )}

          <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase',
            letterSpacing: '0.08em', marginBottom: 10 }}>
            Status History
          </div>
          <Timeline
            items={data.status_history?.map((h: any) => ({
              children: (
                <div>
                  <div style={{ fontSize: 13, color: '#e2e8f0' }}>
                    {h.from_status ? `${STATUS_LABEL[h.from_status]} → ` : ''}{STATUS_LABEL[h.to_status] || h.to_status}
                  </div>
                  <div style={{ fontSize: 11, color: '#6b7280' }}>{h.reason}</div>
                  <div style={{ fontSize: 10, color: '#4b5563' }}>{h.changed_by} · {h.changed_at}</div>
                </div>
              )
            }))}
          />
        </div>
      )}

      <Modal
        title="Record Premium Payment"
        open={premiumModal}
        onCancel={() => setPremiumModal(false)}
        onOk={recordPremium}
        confirmLoading={actionLoading}
      >
        <Form form={premiumForm} layout="vertical">
          <Form.Item name="amount_paid" label="Amount Paid (₹)" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={0}/>
          </Form.Item>
          <Form.Item name="paid_date" label="Payment Date" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }}/>
          </Form.Item>
          <Form.Item name="payment_mode" label="Payment Mode" initialValue="ONLINE">
            <Select>
              <Option value="ONLINE">Online</Option>
              <Option value="CHEQUE">Cheque</Option>
              <Option value="CASH">Cash</Option>
              <Option value="AUTO_DEBIT">Auto Debit</Option>
            </Select>
          </Form.Item>
          <Form.Item name="receipt_number" label="Receipt Number">
            <Input placeholder="Optional"/>
          </Form.Item>
        </Form>
      </Modal>
    </Drawer>
  )
}

export default function PolicyAdminPage() {
  return (
    <div style={{ padding: '32px 36px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontWeight: 700, fontSize: 20, color: '#e2e8f0', margin: 0 }}>
          📋 Policy Administration
        </h1>
        <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          Manage issued policies, premium collection, and policy lifecycle
        </p>
      </div>
      <PolicyListTab/>
    </div>
  )
}
