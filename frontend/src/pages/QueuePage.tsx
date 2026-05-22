import { useEffect, useState, useCallback } from 'react'
import {
  Table, Tag, Button, Select, Input, Modal, Form,
  Input, Spin, Badge, Tooltip, Divider, message,
} from 'antd'
import {
  UserOutlined, CheckCircleOutlined, CloseCircleOutlined,
  SwapOutlined, SearchOutlined, ReloadOutlined,
  FileTextOutlined, MedicineBoxOutlined,
} from '@ant-design/icons'
import { uwAPI } from '../api/client'
import type { QueueCase } from '../types'

const { Option } = Select
const { TextArea } = Input

const fmt = (n: number) => `₹${new Intl.NumberFormat('en-IN').format(n)}`

const outcomeColor = (o?: string) => {
  if (!o) return 'default'
  if (o.includes('APPROVED')) return 'success'
  if (o.includes('DECLIN'))   return 'error'
  if (o.includes('REFER'))    return 'warning'
  if (o.includes('POSTPON'))  return 'purple'
  return 'default'
}

const statusColor = (s?: string) => {
  if (!s) return 'default'
  if (s === 'PROCESSED')  return 'success'
  if (s === 'IN_REVIEW')  return 'processing'
  if (s === 'UNPROCESSED') return 'default'
  return 'default'
}

interface Underwriter { username: string; full_name?: string; role: string }

export default function QueuePage() {
  const [cases, setCases]           = useState<QueueCase[]>([])
  const [filtered, setFiltered]     = useState<QueueCase[]>([])
  const [loading, setLoading]       = useState(true)
  const [search, setSearch]         = useState('')
  const [statusFilter, setStatus]   = useState<string>('ALL')
  const [underwriters, setUW]       = useState<Underwriter[]>([])
  const [decideOpen, setDecideOpen] = useState(false)
  const [apsOpen, setApsOpen]       = useState(false)
  const [selected, setSelected]     = useState<QueueCase | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [decideForm] = Form.useForm()
  const [apsForm]    = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [qRes, uwRes] = await Promise.all([
        uwAPI.getCases(200),
        fetch('/queue/underwriters', {
          headers: { Authorization: `Bearer ${localStorage.getItem('riskuw_token')}` }
        }).then(r => r.json()).catch(() => []),
      ])
      const data = Array.isArray(qRes.data) ? qRes.data
        : (qRes.data.cases ?? qRes.data.items ?? [])
      setCases(data)
      setFiltered(data)
      setUW(Array.isArray(uwRes) ? uwRes : [])
    } catch {
      message.error('Failed to load queue')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    let out = cases
    if (statusFilter !== 'ALL') out = out.filter(c => c.status === statusFilter)
    if (search.trim()) {
      const q = search.toLowerCase()
      out = out.filter(c =>
        c.applicant_ref?.toLowerCase().includes(q) ||
        c.product_code?.toLowerCase().includes(q) ||
        c.outcome?.toLowerCase().includes(q)
      )
    }
    setFiltered(out)
  }, [cases, search, statusFilter])

  const openDecide = (c: QueueCase) => {
    setSelected(c)
    decideForm.setFieldsValue({ outcome: c.outcome ?? 'APPROVED_STP', risk_class: c.risk_class ?? 'STANDARD' })
    setDecideOpen(true)
  }

  const openAPS = (c: QueueCase) => {
    setSelected(c)
    apsForm.resetFields()
    setApsOpen(true)
  }

  const handleDecide = async () => {
    if (!selected) return
    try {
      await decideForm.validateFields()
    } catch { return }
    setSubmitting(true)
    try {
      const v = decideForm.getFieldsValue()
      const token = localStorage.getItem('riskuw_token')
      await fetch('/queue/decide', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ case_id: String(selected.id), ...v }),
      })
      message.success(`Decision recorded: ${v.outcome}`)
      setDecideOpen(false)
      load()
    } catch {
      message.error('Failed to save decision')
    } finally {
      setSubmitting(false)
    }
  }

  const handleAPS = async () => {
    if (!selected) return
    setSubmitting(true)
    try {
      const v = apsForm.getFieldsValue()
      const token = localStorage.getItem('riskuw_token')
      await fetch('/queue/aps/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ case_id: String(selected.id), ...v }),
      })
      message.success('APS request created')
      setApsOpen(false)
    } catch {
      message.error('Failed to create APS request')
    } finally {
      setSubmitting(false)
    }
  }

  // Metrics
  const total    = cases.length
  const pending  = cases.filter(c => c.status === 'UNPROCESSED').length
  const approved = cases.filter(c => c.outcome?.includes('APPROVED')).length
  const referred = cases.filter(c => c.outcome?.includes('REFER')).length

  const columns = [
    {
      title: 'Ref',
      dataIndex: 'applicant_ref',
      width: 140,
      render: (v: string) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--teal-400)' }}>
          {v ?? '—'}
        </span>
      ),
    },
    {
      title: 'Product',
      dataIndex: 'product_code',
      width: 140,
      render: (v: string) => (
        <Tag style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{v ?? '—'}</Tag>
      ),
    },
    {
      title: 'Face Amount',
      dataIndex: 'face_amount',
      width: 140,
      render: (v: number) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          {v ? fmt(v) : '—'}
        </span>
      ),
    },
    {
      title: 'Outcome',
      dataIndex: 'outcome',
      width: 160,
      render: (v: string) => (
        <Tag color={outcomeColor(v)}
          style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700 }}>
          {v?.replace(/_/g, ' ') ?? '—'}
        </Tag>
      ),
    },
    {
      title: 'Risk Class',
      dataIndex: 'risk_class',
      width: 120,
      render: (v: string) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{v ?? '—'}</span>
      ),
    },
    {
      title: 'Debits',
      dataIndex: 'net_debit_points',
      width: 80,
      render: (v: number) => (
        <span style={{
          fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12,
          color: v > 150 ? '#f87171' : v > 75 ? '#fbbf24' : '#94a3b8',
        }}>{v ?? 0}</span>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 120,
      render: (v: string) => (
        <Badge status={statusColor(v) as any}
          text={<span style={{ fontSize: 11, color: 'var(--slate-300)' }}>{v ?? '—'}</span>} />
      ),
    },
    {
      title: 'Actions',
      width: 140,
      render: (_: unknown, record: QueueCase) => (
        <div style={{ display: 'flex', gap: 6 }}>
          {record.outcome?.includes('REFER') && (
            <Tooltip title="Record decision">
              <Button
                size="small"
                icon={<CheckCircleOutlined />}
                style={{ borderColor: 'rgba(0,212,170,0.3)', color: 'var(--teal-400)' }}
                onClick={() => openDecide(record)}
              />
            </Tooltip>
          )}
          <Tooltip title="Request APS">
            <Button
              size="small"
              icon={<MedicineBoxOutlined />}
              style={{ borderColor: 'rgba(251,191,36,0.3)', color: '#fbbf24' }}
              onClick={() => openAPS(record)}
            />
          </Tooltip>
        </div>
      ),
    },
  ]

  return (
    <div style={{ padding: '32px 36px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <h1 style={{
            fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: 22, color: '#fff', margin: 0, letterSpacing: '-0.02em',
          }}>
            UW Workbench
          </h1>
          <p style={{ color: 'var(--slate-500)', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
            Manual underwriting queue · {total} cases
          </p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}
          style={{ borderColor: 'rgba(255,255,255,0.12)', color: 'var(--slate-400)' }}>
          Refresh
        </Button>
      </div>

      {/* Metrics strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: 'Total cases',   value: total,    color: '#00d4aa' },
          { label: 'Pending review',value: pending,  color: '#fbbf24' },
          { label: 'Approved',      value: approved, color: '#22c55e' },
          { label: 'Referred',      value: referred, color: '#fbbf24' },
        ].map(m => (
          <div key={m.label} style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 10, padding: '14px 18px',
          }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, color: m.color }}>{m.value}</div>
            <div style={{ fontSize: 11, color: 'var(--slate-500)', marginTop: 4 }}>{m.label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Input
          prefix={<SearchOutlined style={{ color: 'var(--slate-500)' }} />}
          placeholder="Search ref, product, outcome…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          allowClear
          style={{ maxWidth: 300 }}
        />
        <Select value={statusFilter} onChange={setStatus} style={{ width: 160 }}>
          <Option value="ALL">All statuses</Option>
          <Option value="UNPROCESSED">Pending</Option>
          <Option value="IN_REVIEW">In review</Option>
          <Option value="PROCESSED">Processed</Option>
        </Select>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 60 }}>
          <Spin size="large" />
        </div>
      ) : (
        <Table
          dataSource={filtered}
          columns={columns}
          rowKey={r => String(r.id ?? Math.random())}
          size="middle"
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: t => `${t} cases` }}
          scroll={{ x: 900 }}
          locale={{ emptyText: <span style={{ color: 'var(--slate-500)' }}>No cases found</span> }}
        />
      )}

      {/* Decide modal */}
      <Modal
        title={<span style={{ color: '#fff', fontFamily: 'var(--font-display)', fontWeight: 700 }}>
          Record Manual Decision — {selected?.applicant_ref}
        </span>}
        open={decideOpen}
        onCancel={() => setDecideOpen(false)}
        onOk={handleDecide}
        confirmLoading={submitting}
        okText="Save Decision"
        styles={{ content: { background: 'var(--navy-800)', border: '1px solid rgba(255,255,255,0.1)' },
                  header: { background: 'var(--navy-800)' },
                  footer: { background: 'var(--navy-800)' } }}
      >
        <Form form={decideForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="outcome" label="Outcome" rules={[{ required: true }]} help="Final underwriting decision for this case">
            <Select placeholder="Select decision…">
              {['APPROVED_STP','APPROVED_RATED','REFERRED','DECLINED','POSTPONED'].map(o => (
                <Option key={o} value={o}>{o.replace(/_/g, ' ')}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="risk_class" label="Risk Class" help="Classification that determines premium rating — Standard is baseline">
            <Select placeholder="Select class…">
              {['PREFERRED','STANDARD','SUBSTANDARD','TABLE_2','TABLE_4','TABLE_6','TABLE_8','DECLINE'].map(r => (
                <Option key={r} value={r}>{r.replace(/_/g, ' ')}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="notes" label="Underwriter Notes" help="Recorded in the audit trail — visible to supervisors and auditors">
            <TextArea rows={3} placeholder="e.g. Approved with exclusion for pre-existing diabetes. A1c 7.4 — borderline acceptable." />
          </Form.Item>
        </Form>
      </Modal>

      {/* APS modal */}
      <Modal
        title={<span style={{ color: '#fff', fontFamily: 'var(--font-display)', fontWeight: 700 }}>
          Request APS — {selected?.applicant_ref}
        </span>}
        open={apsOpen}
        onCancel={() => setApsOpen(false)}
        onOk={handleAPS}
        confirmLoading={submitting}
        okText="Send APS Request"
        styles={{ content: { background: 'var(--navy-800)', border: '1px solid rgba(255,255,255,0.1)' },
                  header: { background: 'var(--navy-800)' },
                  footer: { background: 'var(--navy-800)' } }}
      >
        <Form form={apsForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="physician_name" label="Physician Name">
            <Input placeholder="Dr. Ramesh Kumar" />
          </Form.Item>
          <Form.Item name="physician_phone" label="Physician Phone">
            <Input placeholder="+91 98765 43210" />
          </Form.Item>
          <Form.Item name="rule_name" label="Reason for APS" help="The underwriting rule or medical condition that triggered this APS request">
            <Input placeholder="e.g. Type 1 diabetes — latest HbA1c and kidney panel required" />
          </Form.Item>
          <Form.Item name="notes" label="Additional Notes" help="Specific tests, records, or questions to include in the APS letter sent to the physician">
            <TextArea rows={3} placeholder="e.g. Please include latest ECG, creatinine panel, and medication list from the past 12 months." />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
