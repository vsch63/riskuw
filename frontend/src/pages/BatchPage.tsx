import { useEffect, useState, useRef } from 'react'
import {
  Button, Table, Tag, Progress, Upload, Spin,
  message, Modal, Divider,
} from 'antd'
import {
  UploadOutlined, DownloadOutlined, ReloadOutlined,
  CheckCircleFilled, CloseCircleFilled, LoadingOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

interface BatchJob {
  id: string
  job_number: string
  job_name?: string
  status: string
  total_records: number
  processed_count: number
  approved_count: number
  declined_count: number
  referred_count: number
  errored_count: number
  submitted_by?: string
  submitted_at?: string
  completed_at?: string
  error_message?: string
}

const statusColor = (s: string) => {
  if (s === 'COMPLETED') return '#22c55e'
  if (s === 'FAILED')    return '#ef4444'
  if (s === 'RUNNING')   return '#00d4aa'
  if (s === 'QUEUED')    return '#fbbf24'
  return '#94a3b8'
}

const statusIcon = (s: string) => {
  if (s === 'COMPLETED') return <CheckCircleFilled style={{ color: '#22c55e' }} />
  if (s === 'FAILED')    return <CloseCircleFilled style={{ color: '#ef4444' }} />
  if (s === 'RUNNING')   return <LoadingOutlined  style={{ color: '#00d4aa' }} spin />
  return null
}

export default function BatchPage() {
  const [jobs, setJobs]         = useState<BatchJob[]>([])
  const [loading, setLoading]   = useState(true)
  const [uploading, setUploading] = useState(false)
  const [selected, setSelected] = useState<BatchJob | null>(null)
  const [detailOpen, setDetail] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadJobs = async () => {
    try {
      const res = await api.get('/batch/jobs')
      setJobs(Array.isArray(res.data) ? res.data : [])
    } catch {
      message.error('Failed to load batch jobs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadJobs()
    // Poll every 4 seconds if any job is running
    pollRef.current = setInterval(() => {
      setJobs(prev => {
        const hasRunning = prev.some(j => j.status === 'RUNNING' || j.status === 'QUEUED')
        if (hasRunning) loadJobs()
        return prev
      })
    }, 4000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const handleUpload = async (file: File) => {
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const token = localStorage.getItem('riskuw_token')
      const res = await fetch('/batch/upload', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      message.success(`Job queued: ${data.job_number}`)
      loadJobs()
    } catch (e: unknown) {
      message.error(`Upload failed: ${(e as Error).message}`)
    } finally {
      setUploading(false)
    }
    return false  // prevent antd auto-upload
  }

  const downloadTemplate = async () => {
    try {
      const token = localStorage.getItem('riskuw_token')
      const res = await fetch('/batch/template', {
        headers: { Authorization: `Bearer ${token}` },
      })
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'riskuw_batch_template.csv'; a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('Failed to download template')
    }
  }

  const pct = (j: BatchJob) => j.total_records > 0
    ? Math.round((j.processed_count / j.total_records) * 100) : 0

  const columns = [
    {
      title: 'Job',
      render: (_: unknown, j: BatchJob) => (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {statusIcon(j.status)}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--teal-400)' }}>
              {j.job_number}
            </span>
          </div>
          {j.job_name && (
            <div style={{ fontSize: 11, color: 'var(--slate-500)', marginTop: 2 }}>{j.job_name}</div>
          )}
        </div>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (v: string) => (
        <Tag style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: statusColor(v),
          borderColor: statusColor(v) + '40', background: statusColor(v) + '15' }}>
          {v}
        </Tag>
      ),
    },
    {
      title: 'Progress',
      render: (_: unknown, j: BatchJob) => (
        <div style={{ minWidth: 160 }}>
          <Progress
            percent={pct(j)}
            size="small"
            strokeColor={j.status === 'FAILED' ? '#ef4444' : '#00d4aa'}
            trailColor="rgba(255,255,255,0.06)"
            format={p => <span style={{ color: 'var(--slate-400)', fontSize: 11 }}>{p}%</span>}
          />
          <div style={{ fontSize: 10, color: 'var(--slate-500)', marginTop: 2 }}>
            {j.processed_count} / {j.total_records} records
          </div>
        </div>
      ),
    },
    {
      title: 'Results',
      render: (_: unknown, j: BatchJob) => (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {j.approved_count > 0 && (
            <span style={{ fontSize: 11, color: '#22c55e', fontFamily: 'var(--font-mono)' }}>
              ✓ {j.approved_count}
            </span>
          )}
          {j.referred_count > 0 && (
            <span style={{ fontSize: 11, color: '#fbbf24', fontFamily: 'var(--font-mono)' }}>
              → {j.referred_count}
            </span>
          )}
          {j.declined_count > 0 && (
            <span style={{ fontSize: 11, color: '#f87171', fontFamily: 'var(--font-mono)' }}>
              ✗ {j.declined_count}
            </span>
          )}
          {j.errored_count > 0 && (
            <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'var(--font-mono)' }}>
              ! {j.errored_count}
            </span>
          )}
        </div>
      ),
    },
    {
      title: 'Submitted',
      render: (_: unknown, j: BatchJob) => (
        <div style={{ fontSize: 11, color: 'var(--slate-500)' }}>
          <div>{j.submitted_by ?? '—'}</div>
          <div>{j.submitted_at?.slice(0, 16).replace('T', ' ') ?? '—'}</div>
        </div>
      ),
    },
    {
      title: '',
      render: (_: unknown, j: BatchJob) => (
        <Button
          size="small"
          onClick={() => { setSelected(j); setDetail(true) }}
          style={{ borderColor: 'rgba(255,255,255,0.12)', color: 'var(--slate-400)' }}
        >
          Detail
        </Button>
      ),
    },
  ]

  return (
    <div style={{ padding: '32px 36px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: 22, color: '#fff', margin: 0, letterSpacing: '-0.02em' }}>
            Batch Processing
          </h1>
          <p style={{ color: 'var(--slate-500)', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
            Upload CSV / Excel · automatic underwriting at scale
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Button icon={<DownloadOutlined />} onClick={downloadTemplate}
            style={{ borderColor: 'rgba(255,255,255,0.12)', color: 'var(--slate-400)' }}>
            Download template
          </Button>
          <Upload beforeUpload={handleUpload} showUploadList={false} accept=".csv,.xlsx,.xls">
            <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
              Upload batch file
            </Button>
          </Upload>
          <Button icon={<ReloadOutlined />} onClick={loadJobs}
            style={{ borderColor: 'rgba(255,255,255,0.12)', color: 'var(--slate-400)' }} />
        </div>
      </div>

      {/* Upload instructions */}
      <div style={{
        background: 'rgba(0,212,170,0.05)', border: '1px solid rgba(0,212,170,0.15)',
        borderRadius: 10, padding: '14px 18px', marginBottom: 24,
        fontSize: 12, color: 'var(--slate-400)', lineHeight: 1.8,
      }}>
        <strong style={{ color: 'var(--teal-400)' }}>Required columns:</strong>{' '}
        applicant_ref · product_code · age · gender · state · face_amount
        <span style={{ marginLeft: 16, color: 'var(--slate-600)' }}>
          Optional: tobacco_status · height_inches · weight_lbs · diabetes_type · heart_condition
          · annual_income · coverage_term_yrs
        </span>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 60 }}>
          <Spin size="large" />
        </div>
      ) : (
        <Table
          dataSource={jobs}
          columns={columns}
          rowKey="id"
          size="middle"
          pagination={{ pageSize: 15, showSizeChanger: true }}
          locale={{ emptyText: <span style={{ color: 'var(--slate-500)' }}>No batch jobs yet — upload a file to start</span> }}
        />
      )}

      {/* Detail modal */}
      <Modal
        title={<span style={{ color: '#fff', fontFamily: 'var(--font-display)', fontWeight: 700 }}>
          {selected?.job_number} — Detail
        </span>}
        open={detailOpen}
        onCancel={() => setDetail(false)}
        footer={null}
        width={560}
        styles={{ content: { background: 'var(--navy-800)', border: '1px solid rgba(255,255,255,0.1)' },
                  header: { background: 'var(--navy-800)' } }}
      >
        {selected && (
          <div style={{ padding: '8px 0' }}>
            {[
              ['Status',     selected.status],
              ['Total',      selected.total_records],
              ['Processed',  selected.processed_count],
              ['Approved',   selected.approved_count],
              ['Referred',   selected.referred_count],
              ['Declined',   selected.declined_count],
              ['Errors',     selected.errored_count],
              ['Submitted',  selected.submitted_at?.slice(0,19).replace('T',' ')],
              ['Completed',  selected.completed_at?.slice(0,19).replace('T',' ')],
              ['Submitted by', selected.submitted_by],
            ].map(([k, v]) => v != null && (
              <div key={String(k)} style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '7px 0', borderBottom: '1px solid rgba(255,255,255,0.05)',
              }}>
                <span style={{ fontSize: 12, color: 'var(--slate-400)' }}>{k}</span>
                <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: '#fff' }}>{String(v)}</span>
              </div>
            ))}
            {selected.error_message && (
              <div style={{
                marginTop: 12, background: 'rgba(239,68,68,0.07)',
                border: '1px solid rgba(239,68,68,0.2)',
                borderRadius: 6, padding: '10px 12px',
                fontSize: 12, color: '#f87171',
              }}>
                {selected.error_message}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
