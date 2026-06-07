// DocumentUploadPanel.tsx
// Drop this component at the top of EvaluatePage form
// When a document is uploaded, it pre-fills the UW form fields

import { useState } from 'react'
import { Upload, Button, Alert, Spin, Tag, Tooltip } from 'antd'
import {
  UploadOutlined, FileTextOutlined, CheckCircleOutlined,
  ExclamationCircleOutlined, SyncOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

const { Dragger } = Upload

interface ExtractedFields {
  [key: string]: any
}

interface Props {
  onExtracted: (fields: ExtractedFields) => void
}

// Human-readable labels for extracted fields
const FIELD_LABELS: Record<string, string> = {
  applicant_ref:      'Applicant Ref',
  product_code:       'Product Code',
  age:                'Age',
  gender:             'Gender',
  state:              'State',
  face_amount:        'Sum Assured (₹)',
  coverage_term_yrs:  'Coverage Term',
  tobacco_status:     'Tobacco Status',
  height_inches:      'Height (in)',
  weight_lbs:         'Weight (lbs)',
  systolic_bp:        'Systolic BP',
  diastolic_bp:       'Diastolic BP',
  diabetes_type:      'Diabetes',
  heart_condition:    'Heart Condition',
  annual_income:      'Annual Income (₹)',
  existing_coverage:  'Existing Cover (₹)',
  hiv_positive:       'HIV',
  stroke_history:     'Stroke History',
  kidney_disease:     'Kidney Disease',
  copd:               'COPD',
  hazardous_activity: 'Hazardous Activity',
  alcohol_drinks_week:'Alcohol (drinks/wk)',
  a1c:                'HbA1c',
  occupation_title:   'Occupation',
  full_name:          'Full Name',
  date_of_birth:      'Date of Birth',
  email:              'Email',
}

export default function DocumentUploadPanel({ onExtracted }: Props) {
  const [extracting, setExtracting]   = useState(false)
  const [result, setResult]           = useState<any>(null)
  const [error, setError]             = useState('')
  const [applied, setApplied]         = useState(false)

  const handleUpload = async (file: File) => {
    setExtracting(true)
    setError('')
    setResult(null)
    setApplied(false)

    try {
      const formData = new FormData()
      formData.append('file', file)
      const r = await api.post('/underwriting/extract-document', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(r.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Extraction failed — check file format')
    } finally {
      setExtracting(false)
    }
    return false // prevent default upload
  }

  const applyToForm = () => {
    if (result?.extracted) {
      onExtracted(result.extracted)
      setApplied(true)
    }
  }

  const formatValue = (key: string, val: any): string => {
    if (typeof val === 'boolean') return val ? 'Yes' : 'No'
    if (key === 'face_amount' || key === 'annual_income' || key === 'existing_coverage') {
      return `₹${Number(val).toLocaleString('en-IN')}`
    }
    return String(val)
  }

  // Separate UW fields from personal info
  const uwFields = result?.extracted
    ? Object.entries(result.extracted).filter(([k]) =>
        !['full_name','date_of_birth','email','phone'].includes(k))
    : []
  const personalFields = result?.extracted
    ? Object.entries(result.extracted).filter(([k]) =>
        ['full_name','date_of_birth','email','phone'].includes(k))
    : []

  return (
    <div style={{
      background: 'rgba(0,212,170,0.04)',
      border: '1px solid rgba(0,212,170,0.2)',
      borderRadius: 12,
      padding: '20px 24px',
      marginBottom: 24,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16,
      }}>
        <FileTextOutlined style={{ fontSize: 18, color: '#00d4aa' }}/>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0' }}>
            📄 Auto-fill from Document
          </div>
          <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
            Upload a proposal form, APS letter, or medical report to auto-fill the fields below
          </div>
        </div>
      </div>

      {!result && !extracting && (
        <Dragger
          accept=".pdf,.jpg,.jpeg,.png,.tiff"
          maxCount={1}
          showUploadList={false}
          beforeUpload={handleUpload}
          style={{
            background: 'rgba(255,255,255,0.02)',
            border: '1px dashed rgba(0,212,170,0.3)',
            borderRadius: 8,
          }}
        >
          <div style={{ padding: '12px 0' }}>
            <UploadOutlined style={{ fontSize: 24, color: '#00d4aa', marginBottom: 8 }}/>
            <div style={{ fontSize: 13, color: '#9ca3af' }}>
              Drop PDF or image here, or <span style={{ color: '#00d4aa' }}>click to browse</span>
            </div>
            <div style={{ fontSize: 11, color: '#4b5563', marginTop: 4 }}>
              Supports: PDF, JPG, PNG, TIFF · Max 10MB
            </div>
          </div>
        </Dragger>
      )}

      {extracting && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12,
          padding: '16px', background: 'rgba(0,212,170,0.05)',
          borderRadius: 8, border: '1px solid rgba(0,212,170,0.15)',
        }}>
          <Spin size="small"/>
          <div>
            <div style={{ fontSize: 13, color: '#00d4aa', fontWeight: 600 }}>
              Extracting fields...
            </div>
            <div style={{ fontSize: 11, color: '#6b7280' }}>
              Claude AI is reading your document and mapping UW fields
            </div>
          </div>
        </div>
      )}

      {error && (
        <Alert message={error} type="error" showIcon
          style={{ marginBottom: 12 }}
          action={
            <Button size="small" onClick={() => setError('')}>Try Again</Button>
          }
        />
      )}

      {result && !error && (
        <div>
          {/* Summary bar */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '10px 14px',
            background: 'rgba(34,197,94,0.08)',
            border: '1px solid rgba(34,197,94,0.2)',
            borderRadius: 8, marginBottom: 16,
          }}>
            <CheckCircleOutlined style={{ color: '#22c55e', fontSize: 16 }}/>
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 13, color: '#22c55e', fontWeight: 600 }}>
                {result.uw_fields_found} UW fields extracted
              </span>
              <span style={{ fontSize: 12, color: '#6b7280', marginLeft: 8 }}>
                from {result.filename} ({result.char_count?.toLocaleString()} chars read)
              </span>
            </div>
            <Button
              size="small"
              onClick={() => { setResult(null); setApplied(false) }}
              style={{ fontSize: 11, color: '#6b7280' }}
            >
              Upload Different
            </Button>
          </div>

          {/* Personal info */}
          {personalFields.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 6,
                textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Personal Info (not used in UW)
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {personalFields.map(([k, v]) => (
                  <Tag key={k} style={{
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    color: '#9ca3af', fontSize: 11,
                  }}>
                    <span style={{ color: '#6b7280' }}>{FIELD_LABELS[k] || k}: </span>
                    {String(v)}
                  </Tag>
                ))}
              </div>
            </div>
          )}

          {/* UW fields grid */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 8,
              textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Underwriting Fields — will be applied to form
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
              gap: 6,
            }}>
              {uwFields.map(([k, v]) => (
                <div key={k} style={{
                  background: 'rgba(0,212,170,0.06)',
                  border: '1px solid rgba(0,212,170,0.2)',
                  borderRadius: 6, padding: '6px 10px',
                }}>
                  <div style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase',
                    letterSpacing: '0.06em' }}>
                    {FIELD_LABELS[k] || k}
                  </div>
                  <div style={{ fontSize: 13, color: '#00d4aa', fontWeight: 600,
                    marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap' }}>
                    {formatValue(k, v)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Apply button */}
          {!applied ? (
            <Button
              type="primary"
              icon={<SyncOutlined/>}
              onClick={applyToForm}
              style={{ fontWeight: 600 }}
            >
              ✅ Apply {uwFields.length} Fields to Form
            </Button>
          ) : (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              color: '#22c55e', fontSize: 13,
            }}>
              <CheckCircleOutlined/>
              <span>Fields applied — review below and submit when ready</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
