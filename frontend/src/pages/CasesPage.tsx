import { useEffect, useState } from 'react'
import { Table, Tag, Input, Spin } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { uwAPI } from '../api/client'
import type { QueueCase } from '../types'

const fmt = (n: number) => `₹${new Intl.NumberFormat('en-IN').format(n)}`

const outcomeColor = (o?: string) => {
  if (!o) return 'default'
  if (o.includes('APPROVED')) return 'success'
  if (o.includes('DECLIN'))   return 'error'
  if (o.includes('REFER'))    return 'warning'
  return 'purple'
}

export default function CasesPage() {
  const [cases, setCases] = useState<QueueCase[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  useEffect(() => {
    uwAPI.getCases(200)
      .then((r) => {
        const data = Array.isArray(r.data) ? r.data : (r.data.cases ?? r.data.items ?? [])
        setCases(data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = cases.filter((c) => {
    const q = search.toLowerCase()
    return !q
      || c.applicant_ref?.toLowerCase().includes(q)
      || c.product_code?.toLowerCase().includes(q)
      || c.outcome?.toLowerCase().includes(q)
  })

  const columns = [
    {
      title: 'Ref',
      dataIndex: 'applicant_ref',
      key: 'ref',
      render: (v: string) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{v ?? '—'}</span>
      ),
    },
    {
      title: 'Product',
      dataIndex: 'product_code',
      key: 'product',
      render: (v: string) => (
        <Tag style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{v ?? '—'}</Tag>
      ),
    },
    {
      title: 'Face Amount',
      dataIndex: 'face_amount',
      key: 'face',
      render: (v: number) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          {v ? fmt(v) : '—'}
        </span>
      ),
    },
    {
      title: 'Outcome',
      dataIndex: 'outcome',
      key: 'outcome',
      render: (v: string) => (
        <Tag color={outcomeColor(v)} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.05em' }}>
          {v ?? '—'}
        </Tag>
      ),
    },
    {
      title: 'Risk Class',
      dataIndex: 'risk_class',
      key: 'risk',
      render: (v: string) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--teal-400)' }}>{v ?? '—'}</span>
      ),
    },
    {
      title: 'Debit Pts',
      dataIndex: 'net_debit_points',
      key: 'debits',
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
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => v ? (
        <Tag color="blue" style={{ fontSize: 10 }}>{v}</Tag>
      ) : null,
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
        />
      )}
    </div>
  )
}
