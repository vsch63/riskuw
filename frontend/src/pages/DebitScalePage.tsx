/**
 * DebitScalePage.tsx
 *
 * Unified configurable scale builder — handles both:
 *   - Medical Debit Scales  (replaces hardcoded debit tables)
 *   - Premium Rate Scales   (replaces hardcoded premium rate tables)
 *
 * Drop-in replacement: add to router + sidebar. API endpoints assumed:
 *   GET/POST/PUT/DELETE  /scales
 *   GET                  /scales/{id}
 *   GET                  /products          (reuse existing)
 *
 * Style: matches RuleConfigPage.tsx / ProductConfigPage.tsx exactly.
 *   - Ant Design 5
 *   - Same card / secTitle / dark-theme variables
 *   - api client from ../api/client
 */

import { useEffect, useState, useCallback } from 'react'
import {
  Table, Tag, Button, Select, Spin, Switch, InputNumber,
  message, Input, Tabs, Popconfirm, Modal, Divider, Space,
  Tooltip, Alert,
} from 'antd'
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, SearchOutlined,
  EditOutlined, SaveOutlined, EyeOutlined, CopyOutlined,
  CalculatorOutlined, DollarOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

const { Option } = Select

// ── Shared styles (matches existing pages) ─────────────────────────────────────
const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 10, padding: '20px 24px', marginBottom: 16,
}
const secTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#6b7280',
  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14,
}
const mono: React.CSSProperties = {
  fontFamily: 'var(--font-mono, monospace)',
}

// ── Parameter catalogue ────────────────────────────────────────────────────────
type ParamInputType = 'range' | 'dropdown' | 'multiselect'

interface ParamDef {
  type:    ParamInputType
  unit?:   string
  min?:    number
  max?:    number
  step?:   number
  default?: [number, number]
  options?: string[]
}

const PARAM_CATALOGUE: Record<string, ParamDef> = {
  // ── Cardiovascular ────────────────────
  'Blood Pressure — Systolic (mmHg)':  { type:'range', unit:'mmHg', min:80,  max:220, default:[130,160] },
  'Blood Pressure — Diastolic (mmHg)': { type:'range', unit:'mmHg', min:50,  max:140, default:[85,100]  },
  'Total Cholesterol (mg/dL)':         { type:'range', unit:'mg/dL', min:100, max:400, default:[200,240] },
  'LDL Cholesterol (mg/dL)':           { type:'range', unit:'mg/dL', min:50,  max:300, default:[130,160] },
  'HDL Cholesterol (mg/dL)':           { type:'range', unit:'mg/dL', min:20,  max:100, default:[40,60]   },
  'LVEF — Left Ventricular EF (%)':    { type:'range', unit:'%',     min:10,  max:80,  default:[35,55]   },
  'Heart Condition':                   { type:'dropdown', options:['None','Hypertension','CAD','CHF','Arrhythmia','Post-MI','Cardiomyopathy','Congenital'] },
  // ── Endocrine / Metabolic ─────────────
  'HbA1c (%):':                        { type:'range', unit:'%',      min:4,   max:15,  step:0.1, default:[7.0,8.5] },
  'Fasting Blood Sugar (mg/dL)':       { type:'range', unit:'mg/dL',  min:70,  max:500, default:[126,200] },
  'BMI (kg/m²)':                       { type:'range', unit:'kg/m²',  min:14,  max:65,  step:0.1, default:[30,35]   },
  'Diabetes Type':                     { type:'dropdown', options:['None','Pre-diabetic','Type 1','Type 2','Gestational','MODY'] },
  'Insulin Use':                       { type:'dropdown', options:['None','Oral only','Insulin + oral','Insulin only'] },
  'TSH — Thyroid (mIU/L)':             { type:'range', unit:'mIU/L', min:0.1, max:25,  step:0.1, default:[0.4,4.0]  },
  'Diabetes Complications':            { type:'multiselect', options:['None','Neuropathy','Nephropathy','Retinopathy','Peripheral vascular disease','Cardiovascular disease'] },
  // ── Renal ─────────────────────────────
  'eGFR (mL/min/1.73m²)':             { type:'range', unit:'mL/min', min:5,   max:130, default:[45,60]   },
  'Creatinine (mg/dL)':               { type:'range', unit:'mg/dL',  min:0.4, max:15,  step:0.1, default:[1.2,2.0] },
  'CKD Stage':                        { type:'dropdown', options:['None (eGFR≥90)','Stage 1','Stage 2','Stage 3a','Stage 3b','Stage 4','Stage 5 / ESRD'] },
  // ── Respiratory ───────────────────────
  'FEV1 (% predicted)':               { type:'range', unit:'%',      min:20,  max:120, default:[60,80]   },
  'AHI — Sleep Apnea (events/hr)':    { type:'range', unit:'ev/hr',  min:0,   max:120, default:[15,30]   },
  'CPAP Compliance':                  { type:'dropdown', options:['Compliant (>4hr/night)','Partial','Non-compliant','Not prescribed'] },
  'Respiratory Condition':            { type:'dropdown', options:['None','Asthma — mild','Asthma — moderate','Asthma — severe','COPD','Pulmonary fibrosis','OSA'] },
  // ── Oncology ──────────────────────────
  'Cancer Status':                    { type:'dropdown', options:['No history','In remission <2yr','In remission 2–5yr','In remission 5yr+','Active treatment','Palliative'] },
  'Cancer Type':                      { type:'dropdown', options:['Not applicable','Skin (non-melanoma)','Breast','Prostate','Colorectal','Lung','Haematological','Melanoma','Other solid tumour'] },
  // ── Mental Health ─────────────────────
  'Mental Health Severity':           { type:'dropdown', options:['None','Mild — no medication','Moderate — medicated','Severe','Hospitalised in last 2yr','In remission'] },
  // ── Lifestyle ─────────────────────────
  'Tobacco / Smoking Status':         { type:'dropdown', options:['Never','Ex-smoker (quit 5yr+)','Ex-smoker (quit <5yr)','Occasional (<5/day)','Regular (5–19/day)','Heavy (20+/day)'] },
  'Alcohol Consumption':              { type:'dropdown', options:['None','Social / occasional','Moderate (1–2 units/day)','Heavy (3–5 units/day)','Excessive / dependent'] },
  'Hazardous Activities':             { type:'dropdown', options:['None','Recreational flying','Motorsport','Mountaineering','Scuba diving','Extreme sports'] },
  // ── Occupation ────────────────────────
  'Occupation Class':                 { type:'dropdown', options:['Class 1 — office / professional','Class 2 — light manual','Class 3 — manual','Class 4 — hazardous','Class 5 — very hazardous'] },
  // ── Duration ─────────────────────────
  'Duration of Condition (years)':    { type:'range', unit:'yrs', min:0, max:50, default:[2,10] },
  // ── Premium rate dimensions ───────────
  'Gender':                           { type:'dropdown', options:['MALE','FEMALE','OTHER'] },
  'Tobacco Status (rating)':          { type:'dropdown', options:['NON_TOBACCO','TOBACCO'] },
  'Risk Class':                       { type:'dropdown', options:['PREFERRED_PLUS','PREFERRED','STANDARD_PLUS','STANDARD','SUBSTANDARD','TABLE_RATED'] },
  'Policy Term (years)':              { type:'range', unit:'yrs', min:5, max:40, default:[10,30] },
}

const PARAM_KEYS = Object.keys(PARAM_CATALOGUE)

// ── Scale types + categories ───────────────────────────────────────────────────
const SCALE_TYPES = ['DEBIT_SCALE', 'PREMIUM_RATE'] as const
type ScaleType = typeof SCALE_TYPES[number]

const SCALE_CATEGORIES: Record<ScaleType, string[]> = {
  DEBIT_SCALE:  ['Cardiovascular','Endocrine','Respiratory','Renal','Oncology','Neurological','Mental Health','Musculoskeletal','Lifestyle','Occupation','Build','Other'],
  PREMIUM_RATE: ['Individual Term','Individual UL','Individual WL','Final Expense','Group Term','Key Person','Motor','Health','Other'],
}

const DECISION_TYPES = ['DEBIT_ONLY','FLAT_EXTRA_ONLY','DEBIT_AND_FLAT_EXTRA','DECLINE','POSTPONE','STANDARD']

const STATUS_COLOR: Record<string, string> = {
  DRAFT:'#64748b', ACTIVE:'#22c55e', SUPERSEDED:'#f59e0b', ARCHIVED:'#ef4444',
}

// ── Types ──────────────────────────────────────────────────────────────────────
interface ScaleParam {
  id:           string
  paramName:    string
  inputType:    ParamInputType
  rangeMin?:    number
  rangeMax?:    number
  dropdownVal?: string
  multiVals?:   string[]
  weight:       number
}

interface AgeBand {
  label:       string
  value?:      number   // debit points (DEBIT_SCALE) OR rate per 1000 (PREMIUM_RATE)
}

interface Tranche {
  id:           string
  description:  string
  effectiveDate:string
  expireDate?:  string
  matchLogic:   'ALL' | 'ANY'
  params:       ScaleParam[]
  ageBands:     AgeBand[]
  flatExtra?:   number
  decisionType: string
}

interface Scale {
  id?:          string
  scaleId:      string
  description:  string
  scaleType:    ScaleType
  category:     string
  products:     string
  status:       string
  version:      string
  tranches:     Tranche[]
  createdAt?:   string
}

// ── Age band presets ───────────────────────────────────────────────────────────
const AGE_BANDS_GROUPED  = ['18–25','26–30','31–35','36–40','41–45','46–50','51–55','56–60','61–65','66–70']
const AGE_BANDS_SINGLE   = ['18','20','25','30','35','40','45','50','55','60','65','70']

function defaultBands(type: 'grouped' | 'single'): AgeBand[] {
  return (type === 'grouped' ? AGE_BANDS_GROUPED : AGE_BANDS_SINGLE)
    .map(label => ({ label, value: undefined }))
}

function nextId() { return Math.random().toString(36).slice(2, 9) }

function emptyTranche(scaleType: ScaleType): Tranche {
  return {
    id:           nextId(),
    description:  '',
    effectiveDate:'',
    expireDate:   '',
    matchLogic:   'ALL',
    params:       [],
    ageBands:     defaultBands('grouped'),
    flatExtra:    undefined,
    decisionType: scaleType === 'DEBIT_SCALE' ? 'DEBIT_ONLY' : 'STANDARD',
  }
}

function emptyScale(): Scale {
  return {
    scaleId:     '',
    description: '',
    scaleType:   'DEBIT_SCALE',
    category:    'Cardiovascular',
    products:    '',
    status:      'DRAFT',
    version:     '1.0',
    tranches:    [],
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// PARAMETER ROW COMPONENT
// ══════════════════════════════════════════════════════════════════════════════
function ParamRow({ param, onChange, onRemove }: {
  param:    ScaleParam
  onChange: (updated: ScaleParam) => void
  onRemove: () => void
}) {
  const def = PARAM_CATALOGUE[param.paramName]

  const handleParamChange = (name: string) => {
    const newDef = PARAM_CATALOGUE[name]
    onChange({
      ...param,
      paramName:   name,
      inputType:   newDef.type,
      rangeMin:    newDef.default?.[0],
      rangeMax:    newDef.default?.[1],
      dropdownVal: newDef.options?.[0],
      multiVals:   [],
    })
  }

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '220px 220px 1fr 70px 32px',
      gap: 8, alignItems: 'center', marginBottom: 8,
      padding: '8px 12px',
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid rgba(255,255,255,0.05)',
      borderRadius: 6,
    }}>
      {/* Parameter name */}
      <Select
        value={param.paramName}
        onChange={handleParamChange}
        size="small"
        showSearch
        style={{ ...mono, fontSize: 12 }}
      >
        {PARAM_KEYS.map(k => <Option key={k} value={k}>{k}</Option>)}
      </Select>

      {/* Input type badge */}
      <div style={{ fontSize: 11, color: '#6b7280' }}>
        {def?.type === 'range' ? (
          <Tag style={{ fontSize: 10 }}>Min / Max ({def.unit})</Tag>
        ) : def?.type === 'multiselect' ? (
          <Tag color="purple" style={{ fontSize: 10 }}>Multi-select</Tag>
        ) : (
          <Tag color="blue" style={{ fontSize: 10 }}>Dropdown</Tag>
        )}
      </div>

      {/* Value input */}
      <div>
        {def?.type === 'range' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <InputNumber
              size="small" placeholder="Min"
              value={param.rangeMin}
              onChange={v => onChange({ ...param, rangeMin: v ?? undefined })}
              step={def.step ?? 1} min={def.min} max={def.max}
              style={{ width: 90, ...mono }}
            />
            <span style={{ color: '#6b7280' }}>—</span>
            <InputNumber
              size="small" placeholder="Max"
              value={param.rangeMax}
              onChange={v => onChange({ ...param, rangeMax: v ?? undefined })}
              step={def.step ?? 1} min={def.min} max={def.max}
              style={{ width: 90, ...mono }}
            />
            <span style={{ fontSize: 11, color: '#6b7280' }}>{def.unit}</span>
          </div>
        ) : def?.type === 'multiselect' ? (
          <Select
            mode="multiple" size="small"
            value={param.multiVals || []}
            onChange={vals => onChange({ ...param, multiVals: vals })}
            style={{ width: '100%' }} allowClear
          >
            {def.options?.map(o => <Option key={o} value={o}>{o}</Option>)}
          </Select>
        ) : (
          <Select
            size="small"
            value={param.dropdownVal}
            onChange={v => onChange({ ...param, dropdownVal: v })}
            style={{ width: '100%' }}
          >
            {def?.options?.map(o => <Option key={o} value={o}>{o}</Option>)}
          </Select>
        )}
      </div>

      {/* Weight */}
      <Tooltip title="Weight (1–10): how much this parameter's match contributes to tranche selection. Higher weight = stronger influence on which tranche is selected.">
        <InputNumber
          size="small" min={1} max={10} value={param.weight}
          onChange={v => onChange({ ...param, weight: v ?? 1 })}
          style={{ width: '100%', ...mono }}
        />
      </Tooltip>

      {/* Remove */}
      <Button
        size="small" danger type="text" icon={<DeleteOutlined/>}
        onClick={onRemove}
      />
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TRANCHE EDITOR COMPONENT
// ══════════════════════════════════════════════════════════════════════════════
function TrancheEditor({ tranche, scaleType, index, onChange, onRemove }: {
  tranche:   Tranche
  scaleType: ScaleType
  index:     number
  onChange:  (t: Tranche) => void
  onRemove:  () => void
}) {
  const [ageMode, setAgeMode] = useState<'grouped' | 'single'>('grouped')

  const updateParam = (paramId: string, updated: ScaleParam) =>
    onChange({ ...tranche, params: tranche.params.map(p => p.id === paramId ? updated : p) })

  const removeParam = (paramId: string) =>
    onChange({ ...tranche, params: tranche.params.filter(p => p.id !== paramId) })

  const addParam = () => {
    const first = PARAM_KEYS[0]
    const def   = PARAM_CATALOGUE[first]
    onChange({
      ...tranche,
      params: [...tranche.params, {
        id:           nextId(),
        paramName:    first,
        inputType:    def.type,
        rangeMin:     def.default?.[0],
        rangeMax:     def.default?.[1],
        dropdownVal:  def.options?.[0],
        multiVals:    [],
        weight:       1,
      }],
    })
  }

  const updateBandValue = (idx: number, val: number | null) => {
    const bands = [...tranche.ageBands]
    bands[idx] = { ...bands[idx], value: val ?? undefined }
    onChange({ ...tranche, ageBands: bands })
  }

  const fillDecreasing = () => {
    const start = 200, step = 15
    const bands = tranche.ageBands.map((b, i) => ({
      ...b, value: Math.max(0, start - i * step)
    }))
    onChange({ ...tranche, ageBands: bands })
  }

  const clearBands = () =>
    onChange({ ...tranche, ageBands: tranche.ageBands.map(b => ({ ...b, value: undefined })) })

  const switchAgeMode = (mode: 'grouped' | 'single') => {
    setAgeMode(mode)
    onChange({ ...tranche, ageBands: defaultBands(mode) })
  }

  const filledCount = tranche.ageBands.filter(b => b.value !== undefined).length
  const valueLabel  = scaleType === 'PREMIUM_RATE' ? 'Rate per ₹1,000 SA' : 'Debit Points'

  return (
    <div style={{
      border: '1px solid rgba(255,255,255,0.09)',
      borderRadius: 10, marginBottom: 16, overflow: 'hidden',
    }}>
      {/* Tranche header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px',
        background: 'rgba(0,212,170,0.04)',
        borderBottom: '1px solid rgba(255,255,255,0.07)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Tag style={{ ...mono, fontSize: 10, background: 'rgba(0,212,170,0.15)', color: '#00d4aa', border: 'none' }}>
            TRANCHE {String(index + 1).padStart(2, '0')}
          </Tag>
          <Input
            value={tranche.description}
            onChange={e => onChange({ ...tranche, description: e.target.value })}
            placeholder="Tranche description (e.g. Well controlled — low risk)"
            bordered={false}
            style={{ color: '#e2e8f0', fontWeight: 500, fontSize: 13, padding: 0, width: 380 }}
          />
        </div>
        <Popconfirm title="Remove this tranche?" onConfirm={onRemove} okText="Remove" cancelText="No">
          <Button size="small" danger icon={<DeleteOutlined/>}/>
        </Popconfirm>
      </div>

      <div style={{ padding: '16px 20px' }}>
        {/* Dates */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          <div>
            <div style={{ ...secTitle, marginBottom: 6 }}>Effective Date *</div>
            <Input type="date" size="small"
              value={tranche.effectiveDate}
              onChange={e => onChange({ ...tranche, effectiveDate: e.target.value })}/>
          </div>
          <div>
            <div style={{ ...secTitle, marginBottom: 6 }}>Expiry Date</div>
            <Input type="date" size="small"
              value={tranche.expireDate || ''}
              onChange={e => onChange({ ...tranche, expireDate: e.target.value })}/>
          </div>
          <div>
            <div style={{ ...secTitle, marginBottom: 6 }}>Decision Type</div>
            <Select size="small" value={tranche.decisionType} style={{ width: '100%' }}
              onChange={v => onChange({ ...tranche, decisionType: v })}>
              {DECISION_TYPES.map(d => <Option key={d} value={d}>{d}</Option>)}
            </Select>
          </div>
          {(tranche.decisionType === 'FLAT_EXTRA_ONLY' || tranche.decisionType === 'DEBIT_AND_FLAT_EXTRA') && (
            <div>
              <div style={{ ...secTitle, marginBottom: 6 }}>Flat Extra (₹/₹1K/yr)</div>
              <InputNumber size="small" min={0} max={50} step={0.25}
                value={tranche.flatExtra}
                onChange={v => onChange({ ...tranche, flatExtra: v ?? undefined })}
                style={{ width: '100%', ...mono }}/>
            </div>
          )}
        </div>

        {/* Parameters */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <div style={secTitle}>
              Parameter Criteria
              <span style={{ color: '#4b5563', fontWeight: 400, textTransform: 'none', letterSpacing: 0, marginLeft: 8 }}>
                ({tranche.params.length} condition{tranche.params.length !== 1 ? 's' : ''})
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: '#6b7280' }}>Match:</span>
              <Button
                size="small"
                type={tranche.matchLogic === 'ALL' ? 'primary' : 'default'}
                onClick={() => onChange({ ...tranche, matchLogic: 'ALL' })}
                style={tranche.matchLogic === 'ALL' ? {} : { color: '#6b7280' }}
              >ALL (AND)</Button>
              <Button
                size="small"
                type={tranche.matchLogic === 'ANY' ? 'primary' : 'default'}
                onClick={() => onChange({ ...tranche, matchLogic: 'ANY' })}
                style={tranche.matchLogic === 'ANY' ? {} : { color: '#6b7280' }}
              >ANY (OR)</Button>
            </div>
          </div>

          {tranche.params.length === 0 && (
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 10 }}>
              No parameters — this tranche will match all cases (catch-all). Add parameters to narrow the criteria.
            </div>
          )}

          {/* Column headers */}
          {tranche.params.length > 0 && (
            <div style={{
              display: 'grid',
              gridTemplateColumns: '220px 220px 1fr 70px 32px',
              gap: 8, marginBottom: 4, padding: '0 12px',
            }}>
              {['Parameter', 'Input Type', 'Value / Range', 'Weight', ''].map(h => (
                <div key={h} style={{ fontSize: 10, color: '#6b7280', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{h}</div>
              ))}
            </div>
          )}

          {tranche.params.map(p => (
            <ParamRow
              key={p.id} param={p}
              onChange={updated => updateParam(p.id, updated)}
              onRemove={() => removeParam(p.id)}
            />
          ))}

          <Button
            icon={<PlusOutlined/>} size="small"
            onClick={addParam}
            style={{ borderColor: 'rgba(0,212,170,0.25)', color: '#00d4aa', marginTop: 6 }}
          >
            Add Parameter
          </Button>
        </div>

        {/* Age / debit table */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <div style={secTitle}>
              Age → {valueLabel}
              <span style={{ color: '#4b5563', fontWeight: 400, textTransform: 'none', letterSpacing: 0, marginLeft: 8 }}>
                ({filledCount} of {tranche.ageBands.length} set)
              </span>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <Button
                size="small"
                type={ageMode === 'grouped' ? 'primary' : 'default'}
                onClick={() => switchAgeMode('grouped')}
                style={ageMode === 'grouped' ? {} : { color: '#6b7280' }}
              >Bands</Button>
              <Button
                size="small"
                type={ageMode === 'single' ? 'primary' : 'default'}
                onClick={() => switchAgeMode('single')}
                style={ageMode === 'single' ? {} : { color: '#6b7280' }}
              >Single Ages</Button>
              {scaleType === 'DEBIT_SCALE' && (
                <Button size="small" onClick={fillDecreasing} style={{ color: '#6b7280' }}>
                  ↘ Fill decreasing
                </Button>
              )}
              <Button size="small" onClick={clearBands} style={{ color: '#6b7280' }}>
                ✕ Clear
              </Button>
            </div>
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))',
            gap: 8,
          }}>
            {tranche.ageBands.map((band, i) => (
              <div
                key={i}
                style={{
                  background: band.value !== undefined ? 'rgba(0,212,170,0.04)' : 'rgba(255,255,255,0.01)',
                  border: `1px solid ${band.value !== undefined ? 'rgba(0,212,170,0.2)' : 'rgba(255,255,255,0.06)'}`,
                  borderRadius: 6, padding: '8px 10px',
                }}
              >
                <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4, ...mono }}>Age {band.label}</div>
                <InputNumber
                  size="small"
                  value={band.value}
                  onChange={v => updateBandValue(i, v)}
                  min={0}
                  step={scaleType === 'PREMIUM_RATE' ? 0.01 : 5}
                  placeholder={scaleType === 'PREMIUM_RATE' ? '0.00' : 'pts'}
                  style={{ width: '100%', ...mono, textAlign: 'center' }}
                />
              </div>
            ))}
          </div>

          <div style={{
            fontSize: 11, color: '#6b7280', marginTop: 8,
            padding: '8px 12px',
            background: 'rgba(0,212,170,0.03)',
            border: '1px solid rgba(0,212,170,0.08)',
            borderRadius: 6,
          }}>
            💡 {scaleType === 'DEBIT_SCALE'
              ? 'Leave blank to apply a flat debit (no age variation). Typical: higher debits at younger ages for most impairments.'
              : 'Enter premium rate per ₹1,000 sum assured per year. Leave blank to inherit from base rate table.'}
          </div>
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// SCALE LIBRARY TAB
// ══════════════════════════════════════════════════════════════════════════════
function ScaleLibraryTab({ onEdit }: { onEdit: (scale: Scale) => void }) {
  const [scales, setScales]   = useState<Scale[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch]   = useState('')
  const [typeF, setTypeF]     = useState<'ALL' | ScaleType>('ALL')
  const [statusF, setStatusF] = useState('ALL')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.get('/scales')
      setScales(Array.isArray(r.data) ? r.data : [])
    } catch { setScales([]) }
    finally   { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const doDelete = async (id: string) => {
    try {
      await api.delete(`/scales/${id}`)
      message.success('Scale deleted'); load()
    } catch (e: any) { message.error(e?.response?.data?.detail || 'Delete failed') }
  }

  const doDuplicate = async (scale: Scale) => {
    const copy = {
      ...scale,
      scaleId:     scale.scaleId + '_COPY',
      description: scale.description + ' (Copy)',
      status:      'DRAFT',
      id:          undefined,
    }
    try {
      await api.post('/scales', copy)
      message.success('Scale duplicated as DRAFT'); load()
    } catch (e: any) { message.error(e?.response?.data?.detail || 'Duplicate failed') }
  }

  const filtered = scales.filter(s => {
    const q  = search.toLowerCase()
    const mQ = !q || s.scaleId.toLowerCase().includes(q) || s.description.toLowerCase().includes(q) || s.category.toLowerCase().includes(q)
    const mT = typeF   === 'ALL' || s.scaleType === typeF
    const mS = statusF === 'ALL' || s.status    === statusF
    return mQ && mT && mS
  })

  const debitCount   = scales.filter(s => s.scaleType === 'DEBIT_SCALE').length
  const premiumCount = scales.filter(s => s.scaleType === 'PREMIUM_RATE').length
  const activeCount  = scales.filter(s => s.status    === 'ACTIVE').length

  const cols = [
    {
      title: 'Scale ID', dataIndex: 'scaleId', width: 160,
      render: (v: string) => <span style={{ ...mono, color: '#00d4aa', fontWeight: 600 }}>{v}</span>,
    },
    { title: 'Description', dataIndex: 'description' },
    {
      title: 'Type', dataIndex: 'scaleType', width: 130,
      render: (v: ScaleType) => v === 'DEBIT_SCALE'
        ? <Tag icon={<CalculatorOutlined/>} color="blue" style={{ fontSize: 11 }}>Debit Scale</Tag>
        : <Tag icon={<DollarOutlined/>} color="green" style={{ fontSize: 11 }}>Premium Rate</Tag>,
    },
    { title: 'Category', dataIndex: 'category', width: 140 },
    {
      title: 'Tranches', dataIndex: 'tranches', width: 90,
      render: (v: Tranche[]) => <Tag style={{ ...mono }}>{v?.length ?? 0}</Tag>,
    },
    {
      title: 'Status', dataIndex: 'status', width: 110,
      render: (v: string) => (
        <Tag style={{ background: STATUS_COLOR[v] || '#64748b', color: '#fff', border: 'none', fontSize: 11 }}>
          {v}
        </Tag>
      ),
    },
    { title: 'Ver', dataIndex: 'version', width: 60, render: (v: string) => <span style={{ ...mono, fontSize: 11 }}>{v}</span> },
    {
      title: 'Actions', width: 170,
      render: (_: any, s: Scale) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined/>} onClick={() => onEdit(s)}
            style={{ borderColor: 'rgba(0,212,170,0.25)', color: '#00d4aa' }}
          >Edit</Button>
          <Tooltip title="Duplicate as draft">
            <Button size="small" icon={<CopyOutlined/>} onClick={() => doDuplicate(s)}/>
          </Tooltip>
          {(s.status === 'DRAFT' || s.status === 'ARCHIVED') && (
            <Popconfirm title="Delete scale?" onConfirm={() => doDelete(s.id!)} okText="Delete" cancelText="No">
              <Button size="small" danger icon={<DeleteOutlined/>}/>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
        {[
          { label: 'Total Scales',  value: scales.length,  color: '#00d4aa' },
          { label: 'Debit Scales',  value: debitCount,     color: '#3b82f6' },
          { label: 'Premium Rates', value: premiumCount,   color: '#22c55e' },
          { label: 'Active',        value: activeCount,    color: '#f59e0b' },
        ].map(s => (
          <div key={s.label} style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 10, padding: '12px 16px' }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
            <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <Input
          prefix={<SearchOutlined style={{ color: '#6b7280' }}/>}
          placeholder="Search scale ID, description, category…"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ maxWidth: 320 }} allowClear
        />
        <Select value={typeF} onChange={v => setTypeF(v)} style={{ width: 160 }}>
          <Option value="ALL">All types</Option>
          <Option value="DEBIT_SCALE">Debit Scales</Option>
          <Option value="PREMIUM_RATE">Premium Rates</Option>
        </Select>
        <Select value={statusF} onChange={setStatusF} style={{ width: 140 }}>
          {['ALL','DRAFT','ACTIVE','SUPERSEDED','ARCHIVED'].map(s => (
            <Option key={s} value={s}>{s}</Option>
          ))}
        </Select>
        <Button icon={<ReloadOutlined/>} onClick={load} loading={loading} style={{ marginLeft: 'auto' }}/>
      </div>

      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
        Showing {filtered.length} of {scales.length} scales
      </div>

      {loading ? <Spin/> : scales.length === 0 ? (
        <div style={{ ...card, color: '#9ca3af', fontSize: 13 }}>
          No scales configured yet. Use the <strong style={{ color: '#e2e8f0' }}>Create Scale</strong> tab to build your first debit or premium rate scale.
        </div>
      ) : (
        <Table
          dataSource={filtered} columns={cols}
          rowKey={r => String(r.id || r.scaleId)}
          size="small" pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{ emptyText: 'No scales match your filters' }}
        />
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// CREATE / EDIT SCALE TAB
// ══════════════════════════════════════════════════════════════════════════════
function CreateScaleTab({ editingScale, onSaved }: {
  editingScale?: Scale | null
  onSaved:       () => void
}) {
  const [scale, setScale]   = useState<Scale>(editingScale || emptyScale())
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState(false)
  const isEdit = !!editingScale?.id

  useEffect(() => {
    if (editingScale) setScale(editingScale)
    else setScale(emptyScale())
  }, [editingScale])

  const update = (partial: Partial<Scale>) => setScale(prev => ({ ...prev, ...partial }))

  const addTranche = () =>
    update({ tranches: [...scale.tranches, emptyTranche(scale.scaleType)] })

  const updateTranche = (id: string, t: Tranche) =>
    update({ tranches: scale.tranches.map(x => x.id === id ? t : x) })

  const removeTranche = (id: string) =>
    update({ tranches: scale.tranches.filter(x => x.id !== id) })

  const onScaleTypeChange = (type: ScaleType) => {
    const cats = SCALE_CATEGORIES[type]
    update({
      scaleType: type,
      category:  cats[0],
      tranches:  scale.tranches.map(t => ({
        ...t,
        ageBands:     defaultBands('grouped'),
        decisionType: type === 'DEBIT_SCALE' ? 'DEBIT_ONLY' : 'STANDARD',
      })),
    })
  }

  const validate = (): string[] => {
    const errs: string[] = []
    if (!scale.scaleId.trim())      errs.push('Scale ID is required')
    if (!scale.description.trim())  errs.push('Scale Description is required')
    if (scale.tranches.length === 0) errs.push('At least one tranche is required')
    scale.tranches.forEach((t, i) => {
      if (!t.description.trim())    errs.push(`Tranche ${i+1}: Description is required`)
      if (!t.effectiveDate)         errs.push(`Tranche ${i+1}: Effective date is required`)
    })
    return errs
  }

  const save = async () => {
    const errs = validate()
    if (errs.length) { errs.forEach(e => message.error(e)); return }

    setSaving(true)
    try {
      const payload = {
        ...scale,
        scaleId: scale.scaleId.trim().toUpperCase(),
      }
      if (isEdit) {
        await api.put(`/scales/${scale.id}`, payload)
        message.success(`Scale ${payload.scaleId} updated`)
      } else {
        await api.post('/scales', payload)
        message.success(`Scale ${payload.scaleId} saved as DRAFT`)
      }
      onSaved()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const previewJson = JSON.stringify(scale, null, 2)

  return (
    <div style={{ maxWidth: 1000 }}>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 16 }}>
        {isEdit
          ? `Editing scale: ${editingScale?.scaleId} · ${editingScale?.description}`
          : 'Build a configurable debit scale or premium rate scale. Works for both medical impairment ratings and product premium tables.'}
      </div>

      {/* ── BLOCK 1: Scale Identity ─────────────────────────────────────────── */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <div style={secTitle}>Block 1 — Scale Identity</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Tag
              style={{
                cursor: 'pointer', fontSize: 11,
                background: scale.scaleType === 'DEBIT_SCALE' ? 'rgba(59,130,246,0.2)' : 'rgba(255,255,255,0.04)',
                border: scale.scaleType === 'DEBIT_SCALE' ? '1px solid rgba(59,130,246,0.4)' : '1px solid rgba(255,255,255,0.07)',
                color: scale.scaleType === 'DEBIT_SCALE' ? '#3b82f6' : '#6b7280',
              }}
              onClick={() => onScaleTypeChange('DEBIT_SCALE')}
            >
              <CalculatorOutlined/> Medical Debit Scale
            </Tag>
            <Tag
              style={{
                cursor: 'pointer', fontSize: 11,
                background: scale.scaleType === 'PREMIUM_RATE' ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.04)',
                border: scale.scaleType === 'PREMIUM_RATE' ? '1px solid rgba(34,197,94,0.4)' : '1px solid rgba(255,255,255,0.07)',
                color: scale.scaleType === 'PREMIUM_RATE' ? '#22c55e' : '#6b7280',
              }}
              onClick={() => onScaleTypeChange('PREMIUM_RATE')}
            >
              <DollarOutlined/> Premium Rate Scale
            </Tag>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr 180px', gap: 12, marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Scale ID *</div>
            <Input
              value={scale.scaleId}
              onChange={e => update({ scaleId: e.target.value })}
              placeholder="e.g. DIAB-T2-2026"
              style={{ ...mono, textTransform: 'uppercase' }}
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Scale Description *</div>
            <Input
              value={scale.description}
              onChange={e => update({ description: e.target.value })}
              placeholder="e.g. Diabetes Mellitus Type 2 — Debit Scale 2026"
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Version</div>
            <Input
              value={scale.version}
              onChange={e => update({ version: e.target.value })}
              placeholder="1.0"
              style={{ ...mono }}
            />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          <div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Category</div>
            <Select
              value={scale.category}
              onChange={v => update({ category: v })}
              style={{ width: '100%' }}
            >
              {SCALE_CATEGORIES[scale.scaleType].map(c => <Option key={c} value={c}>{c}</Option>)}
            </Select>
          </div>
          <div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Product Codes (comma-separated)</div>
            <Input
              value={scale.products}
              onChange={e => update({ products: e.target.value })}
              placeholder="IND-TERM-20, IND-TERM-30 (blank = applies to all products)"
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Status</div>
            <Select value={scale.status} onChange={v => update({ status: v })} style={{ width: '100%' }} placeholder="Select status…">
              {['DRAFT','ACTIVE','ARCHIVED'].map(s => (
                <Option key={s} value={s}>
                  <Tag style={{ background: STATUS_COLOR[s], color: '#fff', border: 'none', fontSize: 10, marginRight: 6 }}>{s}</Tag>
                </Option>
              ))}
            </Select>
          </div>
        </div>
      </div>

      {/* ── BLOCK 2 + 3 + 4: Tranches ──────────────────────────────────────── */}
      <div style={{ ...card, padding: '16px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div>
            <div style={secTitle}>Blocks 2 · 3 · 4 — Tranches, Parameters &amp; Age Table</div>
            <div style={{ fontSize: 12, color: '#6b7280' }}>
              Each tranche has its own parameter criteria and age-based {scale.scaleType === 'PREMIUM_RATE' ? 'rate' : 'debit'} table.
              Tranches are evaluated top-to-bottom — first match wins.
            </div>
          </div>
          <Button
            type="primary" icon={<PlusOutlined/>}
            onClick={addTranche}
            style={{ background: 'rgba(0,212,170,0.15)', borderColor: 'rgba(0,212,170,0.4)', color: '#00d4aa' }}
          >
            Add Tranche
          </Button>
        </div>

        {scale.tranches.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: '40px 0',
            color: '#6b7280', fontSize: 13,
            border: '1px dashed rgba(255,255,255,0.1)',
            borderRadius: 8,
          }}>
            No tranches yet — click <strong style={{ color: '#e2e8f0' }}>Add Tranche</strong> to begin.<br/>
            <span style={{ fontSize: 12 }}>
              Tip: Create separate tranches for each risk band (e.g. well-controlled, moderate, poor control).
            </span>
          </div>
        ) : (
          scale.tranches.map((t, i) => (
            <TrancheEditor
              key={t.id}
              tranche={t}
              scaleType={scale.scaleType}
              index={i}
              onChange={updated => updateTranche(t.id, updated)}
              onRemove={() => removeTranche(t.id)}
            />
          ))
        )}
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 24 }}>
        <Button
          type="primary" icon={<SaveOutlined/>}
          loading={saving} onClick={save} size="large"
          style={{ fontWeight: 600, minWidth: 180 }}
        >
          {isEdit ? 'Update Scale' : 'Save Scale as DRAFT'}
        </Button>
        <Button
          icon={<EyeOutlined/>} size="large"
          onClick={() => setPreview(true)}
          style={{ color: '#6b7280' }}
        >
          Preview JSON
        </Button>
        {!isEdit && (
          <Button size="large" onClick={() => setScale(emptyScale())} style={{ color: '#6b7280' }}>
            Reset
          </Button>
        )}
      </div>

      {/* JSON preview modal */}
      <Modal
        title={<span style={{ color: '#e2e8f0' }}>Scale JSON — {scale.scaleId || 'Untitled'}</span>}
        open={preview}
        onCancel={() => setPreview(false)}
        footer={null} width={700}
        styles={{
          content: { background: '#0d1521', border: '1px solid rgba(255,255,255,0.09)' },
          header:  { background: '#0d1521' },
        }}
      >
        <pre style={{
          fontSize: 11, color: '#9ca3af',
          overflow: 'auto', maxHeight: 500, margin: 0,
          fontFamily: 'var(--font-mono, monospace)',
        }}>
          {previewJson}
        </pre>
      </Modal>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE SHELL
// ══════════════════════════════════════════════════════════════════════════════
export default function DebitScalePage() {
  const [activeTab, setTab]         = useState('library')
  const [editingScale, setEditing]  = useState<Scale | null>(null)

  const handleEdit = (scale: Scale) => {
    setEditing(scale)
    setTab('create')
  }

  const handleSaved = () => {
    setEditing(null)
    setTab('library')
  }

  const tabs = [
    {
      key: 'library',
      label: (
        <span><ThunderboltOutlined/> Scale Library</span>
      ),
      children: <ScaleLibraryTab onEdit={handleEdit}/>,
    },
    {
      key: 'create',
      label: (
        <span>
          {editingScale ? <EditOutlined/> : <PlusOutlined/>}
          {editingScale ? ' Edit Scale' : ' Create Scale'}
        </span>
      ),
      children: (
        <CreateScaleTab
          editingScale={editingScale}
          onSaved={handleSaved}
        />
      ),
    },
  ]

  return (
    <div style={{ padding: '32px 36px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{
          fontWeight: 700, fontSize: 20, color: '#e2e8f0',
          margin: 0, letterSpacing: '-0.02em',
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <CalculatorOutlined style={{ color: '#00d4aa' }}/>
          Scale Builder
        </h1>
        <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          Configure medical debit scales and premium rate scales. Replaces hardcoded debit tables and premium rate tables.
        </p>
      </div>

      <Alert
        type="info" showIcon closable
        style={{ marginBottom: 20, background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.2)' }}
        message={
          <span style={{ fontSize: 12, color: '#93c5fd' }}>
            <strong>Unified builder:</strong> Use <strong>Medical Debit Scale</strong> for impairment ratings (diabetes, hypertension, BMI etc.) and <strong>Premium Rate Scale</strong> to replace hardcoded premium tables.
            Both share the same tranche → parameter → age table architecture.
          </span>
        }
      />

      <Tabs
        activeKey={activeTab}
        onChange={key => { if (key !== 'create') setEditing(null); setTab(key) }}
        items={tabs}
        tabBarStyle={{ borderBottom: '1px solid rgba(255,255,255,0.07)', marginBottom: 24 }}
      />
    </div>
  )
}

