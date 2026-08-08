// PdfBatchUploadTab.tsx
// Drag-and-drop multiple PDFs → OCR extract → preview table → submit as batch job
import { useState, useRef } from 'react'
import {
  Button, Table, Tag, Alert, Progress, Spin, Tooltip,
  Input, Select, message,
} from 'antd'
import {
  UploadOutlined, FileTextOutlined, CheckCircleOutlined,
  CloseCircleOutlined, SyncOutlined, SendOutlined,
  DeleteOutlined, EditOutlined, EyeOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { Titled } from '../components/ColHint'

const { Option } = Select

// ── Types ────────────────────────────────────────────────────────────────────
interface ExtractedRow {
  filename:    string
  status:      'pending' | 'extracting' | 'success' | 'error' | 'edited'
  extracted:   Record<string, any>
  error:       string | null
  fields_found: number
  char_count:  number
  // editable overrides
  applicant_ref?: string
  product_code?:  string
}

interface Props {
  onSubmitted: (jobId: string) => void
}

// ── Field display config ──────────────────────────────────────────────────────
const KEY_FIELDS = [
  { key: 'applicant_ref', label: 'Ref' },
  { key: 'product_code',  label: 'Product' },
  { key: 'age',           label: 'Age' },
  { key: 'gender',        label: 'Gender' },
  { key: 'face_amount',   label: 'Sum Assured' },
  { key: 'tobacco_status', label: 'Tobacco' },
  { key: 'diabetes_type', label: 'Diabetes' },
  { key: 'systolic_bp',   label: 'Sys BP' },
]

// ── Component ─────────────────────────────────────────────────────────────────
export default function PdfBatchUploadTab({ onSubmitted }: Props) {
  const [rows, setRows]         = useState<ExtractedRow[]>([])
  const [extracting, setExtr]   = useState(false)
  const [submitting, setSubmit] = useState(false)
  const [jobName, setJobName]   = useState('')
  const [aiEngine, setAiEngine] = useState('rules_only')
  const [products, setProducts] = useState<any[]>([])
  const [editingRow, setEditing] = useState<number | null>(null)
  const fileInputRef            = useRef<HTMLInputElement>(null)

  // Load products for dropdown
  useState(() => {
    api.get('/products').then(r => setProducts(Array.isArray(r.data) ? r.data : [])).catch(() => {})
  })

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    if (files.length > 50) {
      message.error('Maximum 50 files per batch')
      return
    }

    // Add pending rows immediately
    const newRows: ExtractedRow[] = Array.from(files).map(f => ({
      filename:    f.name,
      status:      'extracting',
      extracted:   {},
      error:       null,
      fields_found: 0,
      char_count:  0,
    }))
    setRows(prev => [...prev, ...newRows])
    setExtr(true)

    try {
      // Process in batches of 5 to avoid timeout
      const allFiles = Array.from(files)
      const BATCH_SIZE = 5
      const startIdx = rows.length

      for (let i = 0; i < allFiles.length; i += BATCH_SIZE) {
        const batch = allFiles.slice(i, i + BATCH_SIZE)
        const formData = new FormData()
        batch.forEach(f => formData.append('files', f))

        try {
          const r = await api.post('/underwriting/extract-documents-batch', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            timeout: 120000, // 2 min timeout for batch
          })

          const batchResults = r.data.results || []
          setRows(prev => {
            const updated = [...prev]
            batchResults.forEach((result: any, j: number) => {
              const rowIdx = startIdx + i + j
              if (updated[rowIdx]) {
                updated[rowIdx] = {
                  ...updated[rowIdx],
                  status:      result.status === 'success' ? 'success' : 'error',
                  extracted:   result.extracted || {},
                  error:       result.error || null,
                  fields_found: result.fields_found || 0,
                  char_count:  result.char_count || 0,
                  applicant_ref: result.extracted?.applicant_ref || `PDF-${String(rowIdx+1).padStart(4,'0')}`,
                  product_code:  result.extracted?.product_code || '',
                }
              }
            })
            return updated
          })
        } catch (batchErr: any) {
          // Mark this batch as errored
          setRows(prev => {
            const updated = [...prev]
            batch.forEach((_, j) => {
              const rowIdx = startIdx + i + j
              if (updated[rowIdx]) {
                updated[rowIdx] = {
                  ...updated[rowIdx],
                  status: 'error',
                  error:  batchErr?.response?.data?.detail || 'Extraction failed',
                }
              }
            })
            return updated
          })
        }
      }
    } finally {
      setExtr(false)
    }
  }

  const removeRow = (idx: number) => {
    setRows(prev => prev.filter((_, i) => i !== idx))
  }

  const updateRow = (idx: number, field: string, value: any) => {
    setRows(prev => {
      const updated = [...prev]
      updated[idx] = { ...updated[idx], [field]: value, status: 'edited' }
      return updated
    })
  }

  const successRows = rows.filter(r => r.status === 'success' || r.status === 'edited')
  const errorRows   = rows.filter(r => r.status === 'error')

  const submitBatch = async () => {
    if (successRows.length === 0) {
      message.error('No successfully extracted rows to submit')
      return
    }

    // Build CSV from extracted rows
    const headers = [
      'applicant_ref', 'product_code', 'age', 'gender', 'state',
      'face_amount', 'coverage_term_yrs', 'tobacco_status',
      'height_inches', 'weight_lbs', 'systolic_bp', 'diastolic_bp',
      'diabetes_type', 'heart_condition', 'annual_income', 'existing_coverage',
      'hiv_positive', 'cirrhosis', 'stroke_history', 'kidney_disease',
      'depression_history', 'copd', 'hazardous_activity',
      'alcohol_drinks_week', 'a1c', 'occupation_title',
    ]

    const csvLines = [headers.join(',')]
    successRows.forEach((row, i) => {
      const d = row.extracted
      const ref = row.applicant_ref || d.applicant_ref || `PDF-${String(i+1).padStart(4,'0')}`
      const prod = row.product_code || d.product_code || ''
      const vals = headers.map(h => {
        if (h === 'applicant_ref') return ref
        if (h === 'product_code')  return prod
        const v = d[h]
        if (v === undefined || v === null) return ''
        if (typeof v === 'boolean') return v ? 'true' : 'false'
        return String(v).replace(/,/g, ';')
      })
      csvLines.push(vals.join(','))
    })

    const csvContent = csvLines.join('\n')
    const csvBlob    = new Blob(['\ufeff' + csvContent], { type: 'text/csv' })
    const csvFile    = new File([csvBlob], `pdf_batch_${Date.now()}.csv`, { type: 'text/csv' })

    setSubmit(true)
    try {
      const formData = new FormData()
      formData.append('file', csvFile)
      const params = new URLSearchParams({
        job_name:  jobName || `PDF Batch — ${successRows.length} documents`,
        ai_engine: aiEngine,
        dry_run:   'false',
        skip_product_errors: 'true',
      })
      const r = await api.post(`/batch/upload?${params}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      message.success(`✅ Batch job queued: ${r.data.job_number}`)
      onSubmitted(r.data.job_id || r.data.id || '')
      setRows([])
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Batch submission failed')
    } finally {
      setSubmit(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  const card: React.CSSProperties = {
    background: 'rgba(255,255,255,0.02)',
    border: '1px solid rgba(255,255,255,0.07)',
    borderRadius: 10, padding: '20px 24px', marginBottom: 16,
  }
  const secTitle: React.CSSProperties = {
    fontSize: 11, fontWeight: 600, color: '#6b7280',
    textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 12,
  }

  return (
    <div>
      {/* Drop zone */}
      <div style={card}>
        <div style={secTitle}>📄 Upload Proposal PDFs</div>
        <div
          onDragOver={e => { e.preventDefault(); e.currentTarget.style.borderColor = '#00d4aa' }}
          onDragLeave={e => { e.currentTarget.style.borderColor = 'rgba(0,212,170,0.2)' }}
          onDrop={e => {
            e.preventDefault()
            e.currentTarget.style.borderColor = 'rgba(0,212,170,0.2)'
            handleFiles(e.dataTransfer.files)
          }}
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: '2px dashed rgba(0,212,170,0.2)',
            borderRadius: 10, padding: '32px',
            textAlign: 'center', cursor: 'pointer',
            background: 'rgba(0,212,170,0.02)',
            transition: 'border-color 200ms',
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.jpg,.jpeg,.png"
            style={{ display: 'none' }}
            onChange={e => handleFiles(e.target.files)}
          />
          <UploadOutlined style={{ fontSize: 32, color: '#00d4aa', marginBottom: 12 }}/>
          <div style={{ fontSize: 14, color: '#e2e8f0', marginBottom: 4 }}>
            Drop proposal PDF files here or <span style={{ color: '#00d4aa' }}>click to browse</span>
          </div>
          <div style={{ fontSize: 12, color: '#6b7280' }}>
            Supports PDF, JPG, PNG · Max 50 files · 10MB each
          </div>
          <div style={{ fontSize: 11, color: '#4b5563', marginTop: 8 }}>
            Claude AI will extract UW fields from each document automatically
          </div>
        </div>

        {extracting && (
          <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
            <Spin size="small"/>
            <span style={{ fontSize: 13, color: '#00d4aa' }}>
              Extracting fields from documents using Claude AI...
            </span>
          </div>
        )}
      </div>

      {/* Results table */}
      {rows.length > 0 && (
        <div style={card}>
          {/* Summary */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
            <div style={secTitle}>Extracted Documents ({rows.length})</div>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
              <Tag color="success">{successRows.length} ready</Tag>
              {errorRows.length > 0 && <Tag color="error">{errorRows.length} failed</Tag>}
              <Button size="small" danger onClick={() => setRows([])}
                icon={<DeleteOutlined/>}>Clear All</Button>
            </div>
          </div>

          <Table
            dataSource={rows}
            rowKey="filename"
            size="small"
            pagination={false}
            scroll={{ x: 900 }}
            rowClassName={r =>
              r.status === 'error' ? 'ant-table-row-error' : ''
            }
            columns={[
              {
                title: Titled('File', 'filename'),
                dataIndex: 'filename',
                width: 180,
                render: (v: string, r: ExtractedRow) => (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <FileTextOutlined style={{ color: '#6b7280' }}/>
                    <span style={{ fontSize: 12, color: '#e2e8f0',
                      maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap' }} title={v}>{v}</span>
                  </div>
                ),
              },
              {
                title: Titled('Status', 'status'),
                dataIndex: 'status',
                width: 110,
                render: (v: string, r: ExtractedRow) => {
                  if (v === 'extracting') return <><Spin size="small"/> <span style={{ fontSize: 11, color: '#00d4aa' }}>Reading...</span></>
                  if (v === 'success')    return <Tag color="success" icon={<CheckCircleOutlined/>}>{r.fields_found} fields</Tag>
                  if (v === 'edited')     return <Tag color="processing" icon={<EditOutlined/>}>Edited</Tag>
                  if (v === 'error')      return (
                    <Tooltip title={r.error}>
                      <Tag color="error" icon={<CloseCircleOutlined/>}>Failed</Tag>
                    </Tooltip>
                  )
                  return <Tag>{v}</Tag>
                },
              },
              {
                title: Titled('Applicant Ref', 'applicant_ref'),
                dataIndex: 'applicant_ref',
                width: 140,
                render: (v: string, r: ExtractedRow, idx: number) => (
                  <Input
                    size="small"
                    value={v || r.extracted?.applicant_ref || ''}
                    onChange={e => updateRow(idx, 'applicant_ref', e.target.value)}
                    style={{ fontSize: 12 }}
                    placeholder="APP-001"
                    disabled={r.status === 'extracting' || r.status === 'error'}
                  />
                ),
              },
              {
                title: Titled('Product Code', 'product_code'),
                dataIndex: 'product_code',
                width: 160,
                render: (v: string, r: ExtractedRow, idx: number) => (
                  <Select
                    size="small"
                    value={v || r.extracted?.product_code || undefined}
                    onChange={val => updateRow(idx, 'product_code', val)}
                    style={{ width: '100%', fontSize: 12 }}
                    placeholder="Select product"
                    disabled={r.status === 'extracting' || r.status === 'error'}
                    showSearch
                  >
                    {products.map(p => (
                      <Option key={p.product_code} value={p.product_code}>
                        {p.product_code}
                      </Option>
                    ))}
                  </Select>
                ),
              },
              ...KEY_FIELDS.slice(2).map(f => ({
                title: f.label,
                width: 90,
                render: (_: any, r: ExtractedRow) => {
                  const v = r.extracted?.[f.key]
                  if (v === undefined || v === null) return <span style={{ color: '#4b5563' }}>—</span>
                  if (f.key === 'face_amount') return <span style={{ fontSize: 11 }}>₹{Number(v).toLocaleString('en-IN')}</span>
                  return <span style={{ fontSize: 12 }}>{String(v)}</span>
                },
              })),
              {
                title: '',
                width: 50,
                render: (_: any, r: ExtractedRow, idx: number) => (
                  <Button
                    size="small" danger type="text"
                    icon={<DeleteOutlined/>}
                    onClick={() => removeRow(idx)}
                  />
                ),
              },
            ]}
          />

          {/* Error summary */}
          {errorRows.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              message={`${errorRows.length} file(s) could not be extracted`}
              description={
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {errorRows.map(r => (
                    <li key={r.filename} style={{ fontSize: 12 }}>
                      <strong>{r.filename}</strong>: {r.error}
                    </li>
                  ))}
                </ul>
              }
            />
          )}
        </div>
      )}

      {/* Submit section */}
      {successRows.length > 0 && (
        <div style={card}>
          <div style={secTitle}>Submit Batch Job</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div>
              <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Job Name</div>
              <Input
                value={jobName}
                onChange={e => setJobName(e.target.value)}
                placeholder={`PDF Batch — ${successRows.length} documents`}
              />
            </div>
            <div>
              <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>AI Scoring Engine</div>
              <Select value={aiEngine} onChange={setAiEngine} style={{ width: '100%' }}>
                <Option value="rules_only">📋 Rules Engine Only</Option>
                <Option value="xgboost">⚡ XGBoost ML</Option>
                <Option value="ollama">🦙 Ollama LLM</Option>
                <Option value="claude">🧠 Claude AI</Option>
              </Select>
            </div>
          </div>

          <div style={{
            background: 'rgba(0,212,170,0.05)',
            border: '1px solid rgba(0,212,170,0.15)',
            borderRadius: 8, padding: '12px 16px', marginBottom: 16,
          }}>
            <div style={{ fontSize: 13, color: '#e2e8f0', marginBottom: 4 }}>
              📊 <strong>{successRows.length}</strong> documents ready ·{' '}
              {errorRows.length > 0 && <><strong style={{ color: '#f59e0b' }}>{errorRows.length}</strong> will be skipped · </>}
              Fields will be converted to CSV and submitted as a normal batch job
            </div>
            <div style={{ fontSize: 11, color: '#6b7280' }}>
              ⚠️ Verify product codes above before submitting — OCR may not always detect the correct product
            </div>
          </div>

          <Button
            type="primary"
            icon={<SendOutlined/>}
            loading={submitting}
            onClick={submitBatch}
            size="large"
            style={{ height: 44, fontWeight: 600, minWidth: 220 }}
          >
            🚀 Submit {successRows.length} Documents as Batch Job
          </Button>
        </div>
      )}
    </div>
  )
}
