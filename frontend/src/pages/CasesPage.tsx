import { useEffect, useState } from 'react'
import { Table, Tag, Input, Spin, Button, Drawer, Descriptions, message } from 'antd'
import { SearchOutlined, FileTextOutlined, DownloadOutlined } from '@ant-design/icons'
import { uwAPI } from '../api/client'
import { useCurrency } from '../context/CurrencyContext'
import type { QueueCase } from '../types'
import { Titled } from '../components/ColHint'

const outcomeColor = (o?: string) => {
  if (!o) return 'default'
  if (o.includes('APPROVED')) return 'success'
  if (o.includes('DECLIN'))   return 'error'
  if (o.includes('REFER'))    return 'warning'
  return 'purple'
}

const tok = () => localStorage.getItem('riskuw_token') || ''

export default function CasesPage() {
  const { fmt } = useCurrency()
  const [cases, setCases]       = useState<QueueCase[]>([])
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState('')
  const [selected, setSelected] = useState<QueueCase | null>(null)
  const [policy, setPolicy]     = useState<any>(null)
  const [policyLoading, setPL]  = useState(false)
  const [drawerOpen, setDrawer] = useState(false)

  useEffect(() => {
    uwAPI.getCases(200)
      .then((r) => {
        const data = Array.isArray(r.data) ? r.data : (r.data.cases ?? r.data.items ?? [])
        setCases(data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const openCase = async (c: QueueCase) => {
    setSelected(c)
    setPolicy(null)
    setDrawer(true)
    // Look up policy by applicant_ref
    if (c.applicant_ref) {
      setPL(true)
      try {
        const r = await fetch(
          `/policy/list?applicant_ref=${encodeURIComponent(c.applicant_ref)}&limit=1`,
          { headers: { Authorization: `Bearer ${tok()}` } }
        )
        const d = await r.json()
        const pols = d.policies || d.items || (Array.isArray(d) ? d : [])
        if (pols.length > 0) setPolicy(pols[0])
      } catch {}
      finally { setPL(false) }
    }
  }

  const downloadLetter = async () => {
    if (!policy?.id) { message.warning('No policy found for this case'); return }
    try {
      const r = await fetch(`/policy/${policy.id}/letter`,
        { headers: { Authorization: `Bearer ${tok()}` } })
      if (!r.ok) throw new Error(await r.text())
      const blob = await r.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `PolicySchedule_${policy.policy_number}.pdf`
      a.click()
      URL.revokeObjectURL(url)
      message.success('Policy letter downloaded')
    } catch (e: any) {
      message.error(`Download failed: ${e.message}`)
    }
  }

  const filtered = cases.filter((c) => {
    const q = search.toLowerCase()
    return !q
      || c.applicant_ref?.toLowerCase().includes(q)
      || c.product_code?.toLowerCase().includes(q)
      || c.outcome?.toLowerCase().includes(q)
  })

  const columns = [
    {
      title: Titled('Ref', 'applicant_ref'), dataIndex: 'applicant_ref', key: 'ref',
      render: (v: string) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{v ?? '—'}</span>
      ),
    },
    {
      title: Titled('Product', 'product_code'), dataIndex: 'product_code', key: 'product',
      render: (v: string) => (
        <Tag style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{v ?? '—'}</Tag>
      ),
    },
    {
      title: Titled('Face Amount', 'face_amount'), dataIndex: 'face_amount', key: 'face',
      render: (v: number) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          {v ? fmt(v) : '—'}
        </span>
      ),
    },
    {
      title: Titled('Outcome', 'outcome'), dataIndex: 'outcome', key: 'outcome',
      render: (v: string) => (
        <Tag color={outcomeColor(v)}
          style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.05em' }}>
          {v ?? '—'}
        </Tag>
      ),
    },
    {
      title: Titled('Risk Class', 'risk_class'), dataIndex: 'risk_class', key: 'risk',
      render: (v: string) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--teal-400)' }}>{v ?? '—'}</span>
      ),
    },
    {
      title: Titled('Debit Pts', 'net_debit_points'), dataIndex: 'net_debit_points', key: 'debits',
      render: (v: number) => (
        <span style={{
          fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12,
          color: v > 150 ? '#f87171' : v > 75 ? '#fbbf24' : '#94a3b8',
        }}>
          {v ?? 0}
        </span>
      ),
    },
    {
      title: Titled('Status', 'status'), dataIndex: 'status', key: 'status',
      render: (v: string) => v ? <Tag color="blue" style={{ fontSize: 10 }}>{v}</Tag> : null,
    },
    {
      title: '', key: 'action', width: 60,
      render: (_: any, record: QueueCase) => (
        <Button size="small" icon={<FileTextOutlined />}
          style={{ borderColor: 'rgba(0,212,170,0.3)', color: 'var(--teal-400)' }}
          onClick={e => { e.stopPropagation(); openCase(record) }}
        />
      ),
    },
  ]

  return (
    <div style={{ padding: '32px 36px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{
          fontFamily: 'var(--font-display)', fontWeight: 700,
          fontSize: 22, color: '#fff', margin: 0, letterSpacing: '-0.02em',
        }}>
          Case Queue
        </h1>
        <p style={{ color: 'var(--slate-500)', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          All underwriting decisions · {cases.length} records
        </p>
      </div>

      <div style={{ marginBottom: 16, maxWidth: 360 }}>
        <Input
          prefix={<SearchOutlined style={{ color: 'var(--slate-500)' }} />}
          placeholder="Search ref, product, outcome…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
        />
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 60 }}>
          <Spin size="large" />
        </div>
      ) : (
        <Table
          dataSource={filtered}
          columns={columns}
          rowKey={(r) => r.id ?? Math.random().toString()}
          size="middle"
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `${t} cases` }}
          locale={{ emptyText: <span style={{ color: 'var(--slate-500)' }}>No cases found</span> }}
          scroll={{ x: 700 }}
          onRow={record => ({ onClick: () => openCase(record) })}
          rowClassName={() => 'cursor-pointer'}
        />
      )}

      {/* Case Detail Drawer */}
      <Drawer
        title={
          <span style={{ color: '#e2e8f0', fontFamily: 'var(--font-display)', fontWeight: 700 }}>
            Case Detail — {selected?.applicant_ref}
          </span>
        }
        open={drawerOpen}
        onClose={() => setDrawer(false)}
        width={480}
        styles={{
          body: { background: 'var(--navy-800,#0a1628)', padding: 20 },
          header: { background: 'var(--navy-800,#0a1628)', borderBottom: '1px solid rgba(255,255,255,0.08)' },
        }}
      >
        {selected && (
          <div>
            {/* UW Decision */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, color: '#6b7280', fontWeight: 600, marginBottom: 8, letterSpacing: '0.08em' }}>
                UNDERWRITING DECISION
              </div>
              <Tag color={outcomeColor(selected.outcome)}
                style={{ fontSize: 13, fontWeight: 700, padding: '4px 10px' }}>
                {selected.outcome?.replace(/_/g,' ') || '—'}
              </Tag>
            </div>

            <Descriptions column={2} size="small"
              labelStyle={{ color: '#6b7280', fontSize: 12 }}
              contentStyle={{ color: '#e2e8f0', fontSize: 12 }}>
              <Descriptions.Item label="Product">{selected.product_code || '—'}</Descriptions.Item>
              <Descriptions.Item label="Risk Class">{selected.risk_class || '—'}</Descriptions.Item>
              <Descriptions.Item label="Face Amount">{selected.face_amount ? fmt(selected.face_amount) : '—'}</Descriptions.Item>
              <Descriptions.Item label="Debit Points">{selected.net_debit_points ?? 0}</Descriptions.Item>
              <Descriptions.Item label="Status">{selected.status || '—'}</Descriptions.Item>
              <Descriptions.Item label="Source">{(selected as any).source || '—'}</Descriptions.Item>
            </Descriptions>

            {/* Policy Details */}
            <div style={{
              marginTop: 20, padding: '14px 16px',
              background: 'rgba(0,212,170,0.05)',
              border: '1px solid rgba(0,212,170,0.15)',
              borderRadius: 8,
            }}>
              <div style={{ fontSize: 11, color: '#6b7280', fontWeight: 600, marginBottom: 10, letterSpacing: '0.08em' }}>
                POLICY
              </div>
              {policyLoading ? (
                <Spin size="small" />
              ) : policy ? (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: '#00d4aa', fontFamily: 'var(--font-mono)' }}>
                        {policy.policy_number}
                      </div>
                      <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
                        Status: <Tag color={policy.status === 'IN_FORCE' ? 'success' : 'warning'}
                          style={{ fontSize: 10 }}>{policy.status?.replace(/_/g,' ')}</Tag>
                      </div>
                    </div>
                    <Button
                      type="primary"
                      icon={<DownloadOutlined />}
                      onClick={downloadLetter}
                      style={{ background: 'var(--teal-400)', border: 'none' }}
                    >
                      Policy Letter
                    </Button>
                  </div>
                  <Descriptions column={2} size="small"
                    labelStyle={{ color: '#6b7280', fontSize: 11 }}
                    contentStyle={{ color: '#e2e8f0', fontSize: 11 }}>
                    <Descriptions.Item label="Issue Date">{policy.issue_date || '—'}</Descriptions.Item>
                    <Descriptions.Item label="Modal Premium">{policy.modal_premium ? fmt(policy.modal_premium) : '—'}</Descriptions.Item>
                    <Descriptions.Item label="Next Due">{policy.next_premium_due || '—'}</Descriptions.Item>
                    <Descriptions.Item label="Maturity">{policy.maturity_date || '—'}</Descriptions.Item>
                  </Descriptions>
                </div>
              ) : (
                <div style={{ fontSize: 12, color: '#6b7280' }}>
                  No policy issued yet for this case.
                  {selected.outcome?.includes('APPROVED') && (
                    <div style={{ marginTop: 6, color: '#fbbf24', fontSize: 11 }}>
                      ⚠ Case is approved — go to Policy Administration to issue a policy.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  )
}
