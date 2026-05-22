import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Select, Spin, Switch, InputNumber,
  message, Form, Input, Popconfirm, Tabs,
} from 'antd'
import {
  ReloadOutlined, SettingOutlined, SaveOutlined, PlusOutlined,
  EditOutlined, DeleteOutlined, SearchOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import PremiumFormulaTab from './PremiumFormulaTab'

const { Option } = Select
const { TextArea } = Input

// ── Types ──────────────────────────────────────────────────────────────────────
interface Product {
  product_code: string
  product_name?: string; name?: string
  product_type?: string; category?: string; uw_method?: string
  min_age?: number; max_age?: number
  min_face_amount?: number; max_face_amount?: number
  min_face?: number; max_face?: number
  stp_threshold?: number; refer_threshold?: number; decline_threshold?: number
  is_active?: boolean; is_guaranteed_issue?: boolean; is_gi?: boolean
  is_group_product?: boolean
  description?: string; uw_notes?: string
  available_terms?: number[]
  exam_required?: string; non_medical_limit?: number
  reinsurance_threshold?: number; max_issue_age?: number
  effective_date?: string; expire_date?: string
}

interface Rule {
  rule_id: string; rule_name?: string; is_enabled: boolean
  debit_points_override?: number; debit_override_active?: boolean
  flat_extra_override?: number; flat_extra_override_active?: boolean
}

interface Threshold {
  stp_threshold: number; refer_threshold: number; decline_threshold: number
  max_table_rating: number; max_flat_extra: number
  effective_date?: string; expire_date?: string; change_reason?: string
}

interface BuildBand {
  bmi_min: number; bmi_max: number; debit_points: number
  is_decline: boolean; band_label?: string
}

// ── Constants ──────────────────────────────────────────────────────────────────
const PRODUCT_TYPES = ['INDIVIDUAL_TERM','INDIVIDUAL_UL','INDIVIDUAL_WL','INDIVIDUAL_FE','GROUP_TERM','GROUP_SUPP','KEY_PERSON']
const UW_METHODS    = ['FULL_UW','SIMPLIFIED','GUARANTEED_ISSUE','ACCELERATED']
const CATEGORIES    = ['Individual Life','Group Life','Final Expense','Key Person','Other']
const EXAM_OPTIONS  = ['NONE','PARAMEDICAL','FULL_MEDICAL','ATTENDING_PHYSICIAN']
const TABLE_RATINGS = [0,2,4,6,8,10,12,14,16]

// ── Styles ─────────────────────────────────────────────────────────────────────
const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 10, padding: '20px 24px', marginBottom: 16,
}
const secTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#6b7280',
  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14,
}

// ── Product selector header ────────────────────────────────────────────────────
function ProductSelector({ products, selected, onSelect, loading, onRefresh }: {
  products: Product[]; selected: string; onSelect: (v: string) => void
  loading: boolean; onRefresh: () => void
}) {
  const prod = products.find(p => p.product_code === selected)
  const name = prod?.product_name || prod?.name || ''
  const minFace = prod?.min_face_amount ?? prod?.min_face ?? 0
  const maxFace = prod?.max_face_amount ?? prod?.max_face ?? 0

  return (
    <div style={card}>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom: prod ? 12 : 0 }}>
        <div style={{ flex:1 }}>
          <div style={secTitle}>Select Product</div>
          {loading ? <Spin size="small"/> : (
            <Select value={selected || undefined} onChange={onSelect}
              style={{ width:'100%' }} size="large" showSearch
              placeholder="Select a product…"
              optionFilterProp="label"
              options={products.map(p => ({
                value: p.product_code,
                label: `${p.product_code}  —  ${p.product_name || p.name || p.product_code}`,
              }))}/>
          )}
        </div>
        <Button icon={<ReloadOutlined/>} onClick={onRefresh} style={{ marginTop:20 }}>Refresh</Button>
      </div>
      {prod && (
        <div style={{ display:'flex', flexWrap:'wrap', gap:8 }}>
          <Tag color="blue" style={{ fontFamily:'var(--font-mono, monospace)', fontSize:11 }}>
            Ages {prod.min_age}–{prod.max_age}
          </Tag>
          <Tag color="purple" style={{ fontFamily:'var(--font-mono, monospace)', fontSize:11 }}>
            ₹{(minFace/100000).toFixed(0)}L – ₹{(maxFace/100000).toFixed(0)}L
          </Tag>
          <Tag style={{ fontSize:11 }}>{prod.uw_method || 'FULL_UW'}</Tag>
          {prod.product_type && <Tag style={{ fontSize:11 }}>{prod.product_type}</Tag>}
          {(prod.is_guaranteed_issue || prod.is_gi) && <Tag color="green" style={{ fontSize:11 }}>Guaranteed Issue</Tag>}
          <Tag color={prod.is_active ? 'success' : 'error'} style={{ fontSize:11 }}>
            {prod.is_active ? 'Active' : 'Inactive'}
          </Tag>
        </div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1 — Rules & Overrides
// ══════════════════════════════════════════════════════════════════════════════
function RulesTab({ code, prod }: { code: string; prod?: Product }) {
  const [rules, setRules]     = useState<Rule[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch]   = useState('')
  const [filter, setFilter]   = useState('ALL')

  const load = async () => {
    setLoading(true)
    try { const r = await api.get(`/products/${code}/rules`); setRules(Array.isArray(r.data) ? r.data : []) }
    catch { setRules([]) }
    finally { setLoading(false) }
  }
  useEffect(() => { if (code) load() }, [code])

  const toggle = async (rule: Rule) => {
    try {
      await api.put(`/products/${code}/rules/${rule.rule_id}`, { ...rule, is_enabled: !rule.is_enabled })
      setRules(prev => prev.map(r => r.rule_id === rule.rule_id ? { ...r, is_enabled: !r.is_enabled } : r))
      message.success(`Rule ${rule.rule_id} ${!rule.is_enabled ? 'enabled' : 'disabled'}`)
    } catch { message.error('Failed to update rule') }
  }

  const filtered = rules.filter(r => {
    const q = search.toLowerCase()
    const matchQ = !q || r.rule_id.toLowerCase().includes(q) || (r.rule_name||'').toLowerCase().includes(q)
    const matchF = filter === 'ALL'
      || (filter === 'DISABLED' && !r.is_enabled)
      || (filter === 'OVERRIDDEN' && (r.debit_override_active || r.flat_extra_override_active))
    return matchQ && matchF
  })

  const cols = [
    { title:'Rule ID', dataIndex:'rule_id', width:120,
      render:(v:string) => <span style={{ fontFamily:'var(--font-mono, monospace)', fontSize:12, color:'#00d4aa' }}>{v}</span> },
    { title:'Rule Name', dataIndex:'rule_name',
      render:(v:string) => v || <span style={{ color:'#6b7280' }}>—</span> },
    { title:'Enabled', dataIndex:'is_enabled', width:90,
      render:(v:boolean, r:Rule) => <Switch checked={v} size="small" onChange={() => toggle(r)}/> },
    { title:'Debit Override', dataIndex:'debit_points_override', width:130,
      render:(v:number, r:Rule) => r.debit_override_active && v != null
        ? <Tag style={{ fontFamily:'var(--font-mono, monospace)' }}>{v} pts</Tag>
        : <span style={{ color:'#6b7280', fontSize:11 }}>default</span> },
    { title:'Flat Extra Override', dataIndex:'flat_extra_override', width:150,
      render:(v:number, r:Rule) => r.flat_extra_override_active && v != null
        ? <Tag color="gold" style={{ fontFamily:'var(--font-mono, monospace)' }}>₹{v}/₹1k</Tag>
        : <span style={{ color:'#6b7280', fontSize:11 }}>default</span> },
  ]

  return (
    <div>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        Enable/disable rules and override debit points per product.
      </div>

      {rules.length > 0 && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:16 }}>
          {[
            { label:'Total Rules',  value:rules.length,                                    color:'#00d4aa' },
            { label:'Disabled',     value:rules.filter(r=>!r.is_enabled).length,           color:'#ef4444' },
            { label:'Overridden',   value:rules.filter(r=>r.debit_override_active||r.flat_extra_override_active).length, color:'#fbbf24' },
          ].map(s => (
            <div key={s.label} style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:10, padding:'12px 16px' }}>
              <div style={{ fontSize:20, fontWeight:700, color:s.color }}>{s.value}</div>
              <div style={{ fontSize:11, color:'#6b7280', marginTop:2 }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display:'flex', gap:10, marginBottom:16 }}>
        <Input prefix={<SearchOutlined style={{ color:'#6b7280' }}/>}
          placeholder="Search rule name or ID"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ maxWidth:280 }} allowClear/>
        <Select value={filter} onChange={setFilter} style={{ width:160 }}>
          <Option value="ALL">All rules</Option>
          <Option value="DISABLED">Disabled only</Option>
          <Option value="OVERRIDDEN">Overridden only</Option>
        </Select>
        <Button icon={<ReloadOutlined/>} onClick={load} loading={loading} style={{ marginLeft:'auto' }}/>
      </div>

      {loading ? <Spin/> : rules.length === 0 ? (
        <div style={{ ...card, borderColor:'rgba(0,212,170,0.2)', background:'rgba(0,212,170,0.04)' }}>
          <div style={{ fontSize:13, color:'#9ca3af' }}>
            ℹ No rules configured yet for <strong style={{ color:'#00d4aa' }}>{code}</strong>.
            Rules can be assigned via the <strong style={{ color:'#e2e8f0' }}>Rule Builder</strong> page.
          </div>
          {prod && (
            <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:16, marginTop:16 }}>
              {[
                { label:'Min Age',  value:prod.min_age },
                { label:'Max Age',  value:prod.max_age },
                { label:'Min Face', value:`₹${((prod.min_face_amount||prod.min_face||0)/100000).toFixed(0)}L` },
                { label:'Max Face', value:`₹${((prod.max_face_amount||prod.max_face||0)/100000).toFixed(0)}L` },
                { label:'STP Threshold',     value:prod.stp_threshold ?? '—' },
                { label:'Refer Threshold',   value:prod.refer_threshold ?? '—' },
                { label:'Decline Threshold', value:prod.decline_threshold ?? '—' },
                { label:'UW Method',         value:prod.uw_method || '—' },
              ].map(f => (
                <div key={f.label}>
                  <div style={{ fontSize:11, color:'#6b7280', marginBottom:2 }}>{f.label}</div>
                  <div style={{ fontSize:14, fontWeight:600, color:'#e2e8f0' }}>{f.value}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <Table dataSource={filtered} columns={cols} rowKey="rule_id" size="small"
          pagination={{ pageSize:20, showSizeChanger:false }}
          locale={{ emptyText:'No rules match your filter' }}/>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2 — Thresholds
// ══════════════════════════════════════════════════════════════════════════════
function ThresholdsTab({ code }: { code: string }) {
  const [form]              = Form.useForm()
  const [loading, setLoad]  = useState(true)
  const [saving, setSaving] = useState(false)
  const [current, setCurrent] = useState<Threshold|null>(null)

  const load = async () => {
    setLoad(true)
    try {
      const r = await api.get(`/products/${code}/thresholds`)
      const d = r.data || {}
      setCurrent(d)
      form.setFieldsValue({
        stp_threshold:    d.stp_threshold    ?? 50,
        refer_threshold:  d.refer_threshold  ?? 150,
        decline_threshold:d.decline_threshold?? 300,
        max_table_rating: d.max_table_rating ?? 16,
        max_flat_extra:   d.max_flat_extra   ?? 10.0,
        effective_date:   d.effective_date   || '',
        expire_date:      d.expire_date      || '',
        change_reason:    '',
      })
    } catch { message.error('Failed to load thresholds') }
    finally { setLoad(false) }
  }
  useEffect(() => { if (code) load() }, [code])

  const save = async () => {
    const v = form.getFieldsValue()
    if (!(v.stp_threshold < v.refer_threshold && v.refer_threshold < v.decline_threshold)) {
      message.error('Must satisfy: STP < Refer < Decline'); return
    }
    setSaving(true)
    try {
      await api.put(`/products/${code}/thresholds`, v)
      message.success('Thresholds saved'); load()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ maxWidth: 700 }}>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        Set STP, refer, and decline thresholds for this product. Changes are audit-logged.
      </div>
      {current?.effective_date && (
        <div style={{ fontSize:12, color:'#9ca3af', marginBottom:12 }}>
          📅 Current thresholds — Effective: <strong>{current.effective_date}</strong>
          {current.expire_date ? ` | Expires: ${current.expire_date}` : ' | No expiry'}
        </div>
      )}
      {loading ? <Spin/> : (
        <Form form={form} layout="vertical" requiredMark={false}>
          <div style={card}>
            <div style={secTitle}>Decision Thresholds</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16 }}>
              <Form.Item name="stp_threshold" label={<span style={{ color:'#22c55e' }}>STP Threshold (pts)</span>}
                extra={<span style={{ fontSize:11 }}>At or below → auto-approved</span>}>
                <InputNumber min={0} max={200} style={{ width:'100%', fontFamily:'var(--font-mono, monospace)' }}/>
              </Form.Item>
              <Form.Item name="refer_threshold" label={<span style={{ color:'#fbbf24' }}>Refer Threshold (pts)</span>}
                extra={<span style={{ fontSize:11 }}>Between STP and this → referred</span>}>
                <InputNumber min={0} max={400} style={{ width:'100%', fontFamily:'var(--font-mono, monospace)' }}/>
              </Form.Item>
              <Form.Item name="decline_threshold" label={<span style={{ color:'#ef4444' }}>Decline Threshold (pts)</span>}
                extra={<span style={{ fontSize:11 }}>Above this → auto-declined</span>}>
                <InputNumber min={50} max={1000} style={{ width:'100%', fontFamily:'var(--font-mono, monospace)' }}/>
              </Form.Item>
              <Form.Item name="max_table_rating" label="Max Table Rating"
                extra={<span style={{ fontSize:11 }}>Cap — above this → decline</span>}>
                <Select style={{ fontFamily:'var(--font-mono, monospace)' }}>
                  {TABLE_RATINGS.map(t => <Option key={t} value={t}>{t}</Option>)}
                </Select>
              </Form.Item>
              <Form.Item name="max_flat_extra" label="Max Flat Extra (₹/₹1k)"
                extra={<span style={{ fontSize:11 }}>Cap on flat extra surcharge</span>}>
                <InputNumber min={0} max={20} step={0.5} style={{ width:'100%' }}/>
              </Form.Item>
            </div>
          </div>

          <div style={card}>
            <div style={secTitle}>Validity &amp; Audit</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
              <Form.Item name="effective_date" label="Effective Date"
                extra={<span style={{ fontSize:11 }}>Allows future-dating changes</span>}>
                <Input type="date"/>
              </Form.Item>
              <Form.Item name="expire_date" label="Expire Date"
                extra={<span style={{ fontSize:11 }}>Leave blank for indefinite</span>}>
                <Input type="date"/>
              </Form.Item>
            </div>
            <Form.Item name="change_reason" label="Reason for change *"
              rules={[{required:true, message:'Audit reason is required'}]}>
              <Input placeholder="e.g. Annual rate review 2026"/>
            </Form.Item>
          </div>

          <Button type="primary" icon={<SaveOutlined/>} loading={saving} onClick={save} size="large">
            Save Thresholds
          </Button>
        </Form>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3 — Build Table
// ══════════════════════════════════════════════════════════════════════════════
function BuildTableTab({ code }: { code: string }) {
  const [bands, setBands]   = useState<BuildBand[]>([])
  const [loading, setLoad]  = useState(true)
  const [form]              = Form.useForm()
  const [adding, setAdding] = useState(false)

  const load = async () => {
    setLoad(true)
    try { const r = await api.get(`/products/${code}/build-table`); setBands(Array.isArray(r.data) ? r.data : []) }
    catch { setBands([]) }
    finally { setLoad(false) }
  }
  useEffect(() => { if (code) load() }, [code])

  const addBand = async () => {
    setAdding(true)
    try {
      const v = form.getFieldsValue()
      if (v.bmi_min >= v.bmi_max) { message.error('BMI Min must be less than BMI Max'); return }
      await api.post(`/products/${code}/build-table`, v)
      message.success(`Band BMI ${v.bmi_min}–${v.bmi_max} saved`)
      form.resetFields(); load()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Failed') }
    finally { setAdding(false) }
  }

  const deleteBand = async (b: BuildBand) => {
    try {
      await api.delete(`/products/${code}/build-table`, { data: { bmi_min: b.bmi_min, bmi_max: b.bmi_max } })
      message.success('Band deleted'); load()
    } catch { message.error('Delete failed') }
  }

  const cols = [
    { title:'BMI Min',      dataIndex:'bmi_min',      width:100, render:(v:number) => <span style={{ fontFamily:'var(--font-mono, monospace)' }}>{v}</span> },
    { title:'BMI Max',      dataIndex:'bmi_max',      width:100, render:(v:number) => <span style={{ fontFamily:'var(--font-mono, monospace)' }}>{v}</span> },
    { title:'Band Label',   dataIndex:'band_label',   render:(v:string) => v || '—' },
    { title:'Debit Points', dataIndex:'debit_points',
      render:(v:number) => <span style={{ fontFamily:'var(--font-mono, monospace)', fontWeight:700, color: v > 50 ? '#f87171' : v > 25 ? '#fbbf24' : '#9ca3af' }}>{v}</span> },
    { title:'Decision', dataIndex:'is_decline',
      render:(v:boolean) => v ? <Tag color="error">AUTO-DECLINE</Tag> : <Tag color="success">RATE</Tag> },
    { title:'', width:60, render:(_:any, b:BuildBand) => (
      <Popconfirm title="Delete this band?" onConfirm={() => deleteBand(b)} okText="Delete" cancelText="Cancel">
        <Button size="small" danger icon={<DeleteOutlined/>}/>
      </Popconfirm>
    )},
  ]

  return (
    <div>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        The BMI Build Table maps height/weight (BMI) ranges to debit points.
        A <strong style={{ color:'#ef4444' }}>Decline</strong> band triggers an instant decline regardless of thresholds.
      </div>

      {loading ? <Spin/> : bands.length === 0 ? (
        <div style={{ ...card, color:'#9ca3af', fontSize:13 }}>
          No BMI build table configured for <strong style={{ color:'#00d4aa' }}>{code}</strong> yet. Add bands below.
        </div>
      ) : (
        <>
          <div style={{ marginBottom:16, fontSize:13, color:'#9ca3af' }}>
            {bands.length} BMI bands configured for <strong style={{ color:'#00d4aa' }}>{code}</strong>
          </div>
          <Table dataSource={bands} columns={cols}
            rowKey={r => `${r.bmi_min}-${r.bmi_max}`}
            size="small" pagination={false} style={{ marginBottom:16 }}/>

          {/* Visual guide */}
          <div style={card}>
            <div style={secTitle}>Band Guide</div>
            {bands.map(b => (
              <div key={`${b.bmi_min}-${b.bmi_max}`} style={{
                padding:'6px 12px', borderRadius:6, marginBottom:6,
                background: b.is_decline ? 'rgba(239,68,68,0.1)' : b.debit_points === 0 ? 'rgba(34,197,94,0.08)' : 'rgba(251,191,36,0.08)',
                border: `1px solid ${b.is_decline ? 'rgba(239,68,68,0.25)' : b.debit_points === 0 ? 'rgba(34,197,94,0.2)' : 'rgba(251,191,36,0.2)'}`,
                fontSize:13,
                color: b.is_decline ? '#f87171' : b.debit_points === 0 ? '#4ade80' : '#fbbf24',
              }}>
                BMI {b.bmi_min} – {b.bmi_max} →{' '}
                {b.is_decline ? '🔴 AUTO-DECLINE' : b.debit_points === 0 ? `✅ 0 debits` : `⚠ +${b.debit_points} debits`}
                {b.band_label && <span style={{ color:'#6b7280', marginLeft:8 }}>({b.band_label})</span>}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Add band form */}
      <div style={card}>
        <div style={secTitle}>Add BMI Band</div>
        <div style={{ fontSize:12, color:'#6b7280', marginBottom:12 }}>
          Typical: Preferred (18–25, 0pts) · Standard (25–32, 25pts) · Substandard (32–40, 75pts) · Decline (40+)
        </div>
        <Form form={form} layout="vertical" requiredMark={false}>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:12 }}>
            <Form.Item name="bmi_min" label="BMI Min" initialValue={18}>
              <InputNumber min={10} max={80} step={0.5} style={{ width:'100%' }}/>
            </Form.Item>
            <Form.Item name="bmi_max" label="BMI Max" initialValue={25}>
              <InputNumber min={10} max={99} step={0.5} style={{ width:'100%' }}/>
            </Form.Item>
            <Form.Item name="debit_points" label="Debit Points" initialValue={0}>
              <InputNumber min={0} max={500} step={5} style={{ width:'100%' }}/>
            </Form.Item>
            <Form.Item name="band_label" label="Label">
              <Input placeholder="e.g. Preferred"/>
            </Form.Item>
            <Form.Item name="is_decline" label="Auto-Decline" valuePropName="checked" initialValue={false}>
              <Switch checkedChildren="DECLINE" unCheckedChildren="RATE"/>
            </Form.Item>
          </div>
          <Button type="primary" icon={<PlusOutlined/>} loading={adding} onClick={addBand}>
            Save Band
          </Button>
        </Form>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4 — Edit Product
// ══════════════════════════════════════════════════════════════════════════════
function EditProductTab({ code, onSaved }: { code: string; onSaved: () => void }) {
  const [form]              = Form.useForm()
  const [loading, setLoad]  = useState(true)
  const [saving, setSaving] = useState(false)

  const load = async () => {
    setLoad(true)
    try {
      const r = await api.get(`/products/${code}`)
      const d = r.data
      form.setFieldsValue({
        ...d,
        available_terms: d.available_terms?.join(',') || '',
        effective_date:  d.effective_date?.slice(0,10) || '',
        expire_date:     d.expire_date?.slice(0,10)    || '',
      })
    } catch { message.error('Failed to load product') }
    finally { setLoad(false) }
  }
  useEffect(() => { if (code) load() }, [code])

  const parseTerms = (s: string) => {
    if (!s?.trim()) return null
    return s.split(',').map(t => parseInt(t.trim())).filter(n => !isNaN(n))
  }

  const save = async () => {
    const v = form.getFieldsValue()
    const errs = []
    if (!v.product_name?.trim()) errs.push('Product Name is required')
    if (v.min_age >= v.max_age)  errs.push('Min Age must be less than Max Age')
    if (v.min_face_amount >= v.max_face_amount) errs.push('Min Face must be less than Max Face')
    if (!(v.stp_threshold < v.refer_threshold && v.refer_threshold < v.decline_threshold))
      errs.push('Thresholds must satisfy: STP < Refer < Decline')
    if (errs.length) { errs.forEach(e => message.error(e)); return }

    setSaving(true)
    try {
      const payload = {
        ...v,
        available_terms: parseTerms(v.available_terms),
        effective_date:  v.effective_date || null,
        expire_date:     v.expire_date || null,
      }
      await api.patch(`/products/${code}`, payload)
      message.success('Product updated'); onSaved()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSaving(false) }
  }

  if (loading) return <div style={{ display:'flex', justifyContent:'center', padding:40 }}><Spin size="large"/></div>

  return (
    <div style={{ maxWidth: 860 }}>
      <Form form={form} layout="vertical" requiredMark={false}>
        {/* Identity */}
        <div style={card}>
          <div style={secTitle}>Product Identity</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <Form.Item name="product_name" label="Product Name *" rules={[{required:true}]} help="Full marketing name of the product"><Input placeholder="e.g. Individual Term Life 20yr"/></Form.Item>
            <Form.Item name="product_type" label="Product Type *" help="Broad classification — Term, Endowment, ULIP, etc.">
              <Select placeholder="Select type…">{PRODUCT_TYPES.map(t => <Option key={t} value={t}>{t}</Option>)}</Select>
            </Form.Item>
            <Form.Item name="category" label="Product Category *" help="Individual, Group, or Micro-insurance">
              <Select placeholder="Select category…">{CATEGORIES.map(c => <Option key={c} value={c}>{c}</Option>)}</Select>
            </Form.Item>
            <Form.Item name="uw_method" label="UW Method *" help="FULL_UW runs all rules; GI skips medical underwriting entirely">
              <Select placeholder="Select method…">{UW_METHODS.map(m => <Option key={m} value={m}>{m}</Option>)}</Select>
            </Form.Item>
          </div>
        </div>

        {/* Eligibility */}
        <div style={card}>
          <div style={secTitle}>Eligibility</div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:16 }}>
            <Form.Item name="min_age" label="Min Age" help="Minimum entry age in years"><InputNumber min={0} max={99} style={{ width:'100%' }} placeholder="e.g. 18"/></Form.Item>
            <Form.Item name="max_age" label="Max Age" help="Maximum entry age in years"><InputNumber min={1} max={100} style={{ width:'100%' }} placeholder="e.g. 65"/></Form.Item>
            <Form.Item name="min_face_amount" label="Min Face (₹)">
              <InputNumber min={0} step={10000} style={{ width:'100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v:any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
            <Form.Item name="max_face_amount" label="Max Face (₹)">
              <InputNumber min={0} step={100000} style={{ width:'100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v:any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
          </div>
        </div>

        {/* Terms */}
        <div style={card}>
          <div style={secTitle}>Term Configuration</div>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:12 }}>
            Enter comma-separated years. Leave blank for permanent/whole life products.
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <Form.Item name="available_terms" label="Available Terms (years, comma-separated)"
              extra={<span style={{ fontSize:11 }}>e.g. 10,20,30</span>}>
              <Input placeholder="10,20,30"/>
            </Form.Item>
            <Form.Item name="exam_required" label="Exam Required" help="When a medical exam is mandatory for this product">
              <Select placeholder="Select…">{EXAM_OPTIONS.map(e => <Option key={e} value={e}>{e}</Option>)}</Select>
            </Form.Item>

          </div>
        </div>

        {/* Financial Limits */}
        <div style={card}>
          <div style={secTitle}>Financial Limits</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16 }}>
            <Form.Item name="non_medical_limit" label="Non-Medical Limit (₹)" help="Proposals below this face amount do not require a medical exam">
              <InputNumber min={0} step={50000} style={{ width:'100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v:any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
            <Form.Item name="reinsurance_threshold" label="Reinsurance Threshold (₹)" help="Face amounts above this threshold are automatically flagged for reinsurance cession">
              <InputNumber min={0} step={500000} style={{ width:'100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v:any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
            <Form.Item name="max_issue_age" label="Max Issue Age" help="Maximum age at which the policy can be issued (may differ from max entry age)">
              <InputNumber min={1} max={100} style={{ width:'100%' }} placeholder="e.g. 65"/>
            </Form.Item>
          </div>
        </div>

        {/* Decision Thresholds */}
        <div style={card}>
          <div style={secTitle}>Decision Thresholds</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16 }}>
            <Form.Item name="stp_threshold"     label={<span style={{ color:'#22c55e' }}>STP Threshold</span>} help="Cases with debit points ≤ this value are auto-approved (straight-through)"><InputNumber min={0} max={200} style={{ width:'100%' }} placeholder="e.g. 75"/></Form.Item>
            <Form.Item name="refer_threshold"   label={<span style={{ color:'#fbbf24' }}>Refer Threshold</span>} help="Cases with debit points ≤ this value are referred to manual review"><InputNumber min={0} max={400} style={{ width:'100%' }} placeholder="e.g. 150"/></Form.Item>
            <Form.Item name="decline_threshold" label={<span style={{ color:'#ef4444' }}>Decline Threshold</span>} help="Cases exceeding this debit point total are automatically declined"><InputNumber min={50} max={1000} style={{ width:'100%' }} placeholder="e.g. 300"/></Form.Item>
          </div>
        </div>

        {/* Validity */}
        <div style={card}>
          <div style={secTitle}>Product Validity</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16 }}>
            <Form.Item name="effective_date" label="Effective Date" help="Date from which this product is available for new proposals"><Input type="date"/></Form.Item>
            <Form.Item name="expire_date"    label="Expire Date" help="Date after which no new proposals can be issued — leave blank for no expiry"><Input type="date"/></Form.Item>
            <Form.Item name="is_active" label="Product Active" valuePropName="checked">
              <Switch checkedChildren="Active" unCheckedChildren="Inactive"/>
            </Form.Item>
          </div>
        </div>

        {/* Additional Settings */}
        <div style={card}>
          <div style={secTitle}>Additional Settings</div>
          <div style={{ display:'flex', gap:24, marginBottom:16 }}>
            <Form.Item name="is_guaranteed_issue" valuePropName="checked" style={{ margin:0 }}>
              <Switch/> <span style={{ fontSize:13, color:'#9ca3af', marginLeft:8 }}>Guaranteed Issue</span>
            </Form.Item>
            <Form.Item name="is_group_product" valuePropName="checked" style={{ margin:0 }}>
              <Switch/> <span style={{ fontSize:13, color:'#9ca3af', marginLeft:8 }}>Group Product</span>
            </Form.Item>
          </div>
          <Form.Item name="description" label="Product Description" help="Customer-facing description shown on proposal forms and letters">
            <TextArea rows={3} placeholder="e.g. A pure protection term plan providing life cover for a specified period…"/>
          </Form.Item>
          <Form.Item name="uw_notes" label="UW Notes / Exam Notes" help="Internal underwriter notes — not visible to agents or applicants">
            <TextArea rows={2} placeholder="e.g. Medical exam required for sum assured above ₹50L. Non-smoker discount applies."/>
          </Form.Item>
        </div>

        <div style={{ display:'flex', gap:10 }}>
          <Button type="primary" icon={<SaveOutlined/>} loading={saving} onClick={save} size="large">
            Save Changes
          </Button>
          <Button onClick={load}>Reset</Button>
        </div>
      </Form>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 5 — Add Product
// ══════════════════════════════════════════════════════════════════════════════
// ══════════════════════════════════════════════════════════════════════════════
// TAB 5 — UW Scales Attachment
// ══════════════════════════════════════════════════════════════════════════════
interface ScaleAttachment {
  id: string
  scale_id: string
  scale_name: string
  scale_type: 'UW' | 'PREMIUM'
  premium_output_type?: string | null
  effective_from: string
  created_by: string
}

interface AvailableScale {
  id: string
  name: string
  scale_type: 'UW' | 'PREMIUM'
  premium_output_type?: string | null
  tranche_count: number
}

function ProductScalesTab({ code }: { code: string }) {
  const [attachments, setAttachments]   = useState<ScaleAttachment[]>([])
  const [available, setAvailable]       = useState<AvailableScale[]>([])
  const [loading, setLoading]           = useState(true)
  const [attaching, setAttaching]       = useState(false)
  const [selectedScale, setSelectedScale] = useState<string | undefined>(undefined)

  const load = async () => {
    setLoading(true)
    try {
      const [attRes, scaleRes] = await Promise.all([
        api.get('/uw-scales/product-attachments/', { params: { product_code: code } }),
        api.get('/uw-scales/', { params: { active_only: true } }),
      ])
      setAttachments(Array.isArray(attRes.data) ? attRes.data : [])
      setAvailable(Array.isArray(scaleRes.data) ? scaleRes.data : [])
    } catch { message.error('Failed to load scales') }
    finally { setLoading(false) }
  }

  useEffect(() => { if (code) load() }, [code])

  const attach = async () => {
    if (!selectedScale) { message.error('Select a scale to attach'); return }
    setAttaching(true)
    try {
      await api.post('/uw-scales/product-attachments/', {
        product_code: code,
        scale_id: selectedScale,
        effective_from: new Date().toISOString().split('T')[0],
      })
      message.success('Scale attached to product')
      setSelectedScale(undefined)
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Failed to attach scale')
    } finally { setAttaching(false) }
  }

  const detach = async (id: string, name: string) => {
    try {
      await api.delete(`/uw-scales/product-attachments/${id}`)
      message.success(`Removed: ${name}`)
      load()
    } catch { message.error('Failed to remove attachment') }
  }

  // Filter out already-attached scales
  const attachedIds = new Set(attachments.map(a => a.scale_id))
  const unattached  = available.filter(s => !attachedIds.has(s.id))

  const cols = [
    {
      title: 'Scale Name', dataIndex: 'scale_name',
      render: (v: string) => <span style={{ fontWeight: 600, color: '#e2e8f0' }}>{v}</span>,
    },
    {
      title: 'Type', dataIndex: 'scale_type', width: 90,
      render: (v: string) => <Tag color={v === 'UW' ? 'cyan' : 'gold'} style={{ fontWeight: 700, fontSize: 11 }}>{v}</Tag>,
    },
    {
      title: 'Output', dataIndex: 'premium_output_type', width: 150,
      render: (v: string | null) => v
        ? <span style={{ fontSize: 11, color: '#9ca3af' }}>{v === 'RATE_PER_THOUSAND' ? 'Rate / ₹1k SA' : 'Multiplier'}</span>
        : <span style={{ fontSize: 11, color: '#4b5563' }}>Debit Points</span>,
    },
    {
      title: 'Effective From', dataIndex: 'effective_from', width: 130,
      render: (v: string) => <span style={{ fontSize: 12, color: '#9ca3af' }}>{v}</span>,
    },
    {
      title: 'Attached By', dataIndex: 'created_by', width: 120,
      render: (v: string) => <span style={{ fontSize: 11, color: '#6b7280' }}>{v}</span>,
    },
    {
      title: '', width: 80,
      render: (_: any, r: ScaleAttachment) => (
        <Popconfirm
          title={`Remove "${r.scale_name}" from this product?`}
          onConfirm={() => detach(r.id, r.scale_name)}
          okText="Remove" cancelText="Cancel"
        >
          <Button size="small" danger icon={<DeleteOutlined/>}/>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 20 }}>
        Attach UW debit scales and premium rate scales to this product.
        The UW engine uses attached scales when evaluating applications.
      </div>

      {/* Attach new scale */}
      <div style={card}>
        <div style={secTitle}>Attach Scale to Product</div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 6 }}>Select Scale</div>
            <Select
              value={selectedScale}
              onChange={setSelectedScale}
              placeholder="Select a scale to attach…"
              style={{ width: '100%' }}
              showSearch
              optionFilterProp="label"
              options={unattached.map(s => ({
                value: s.id,
                label: `[${s.scale_type}] ${s.name} — ${s.tranche_count} tranches`,
              }))}
            />
          </div>
          <Button
            type="primary"
            icon={<PlusOutlined/>}
            loading={attaching}
            onClick={attach}
            disabled={!selectedScale}
          >
            Attach
          </Button>
        </div>
        {unattached.length === 0 && !loading && (
          <div style={{ fontSize: 12, color: '#4b5563', fontStyle: 'italic', marginTop: 10 }}>
            All available scales are already attached, or no scales exist.
            Create scales in <strong style={{ color: '#e2e8f0' }}>System Config → UW Scales</strong>.
          </div>
        )}
      </div>

      {/* Attached scales list */}
      <div style={card}>
        <div style={secTitle}>Attached Scales ({attachments.length})</div>
        {loading
          ? <div style={{ textAlign: 'center', padding: 24 }}><Spin/></div>
          : attachments.length === 0
            ? <div style={{ fontSize: 13, color: '#4b5563', fontStyle: 'italic', padding: '8px 0' }}>
                No scales attached to this product yet.
              </div>
            : <Table
                dataSource={attachments}
                columns={cols}
                rowKey="id"
                size="small"
                pagination={false}
              />
        }
      </div>
    </div>
  )
}

function AddProductTab({ onCreated }: { onCreated: () => void }) {
  const [form]              = Form.useForm()
  const [saving, setSaving] = useState(false)

  const parseTerms = (s: string) => {
    if (!s?.trim()) return null
    return s.split(',').map(t => parseInt(t.trim())).filter(n => !isNaN(n))
  }

  const save = async () => {
    try { await form.validateFields() } catch { return }
    const v = form.getFieldsValue()
    const errs = []
    if (v.min_age >= v.max_age) errs.push('Min Age must be less than Max Age')
    if (v.min_face_amount >= v.max_face_amount) errs.push('Min Face must be less than Max Face')
    if (!(v.stp_threshold < v.refer_threshold && v.refer_threshold < v.decline_threshold))
      errs.push('Thresholds must satisfy: STP < Refer < Decline')
    if (errs.length) { errs.forEach(e => message.error(e)); return }

    setSaving(true)
    try {
      const payload = {
        ...v,
        product_code:    v.product_code.trim().toUpperCase(),
        available_terms: parseTerms(v.available_terms),
        effective_date:  v.effective_date || null,
        expire_date:     v.expire_date    || null,
      }
      await api.post('/products', payload)
      message.success(`✅ Product ${payload.product_code} created`)
      form.resetFields(); onCreated()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Failed to create product') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ maxWidth: 860 }}>
      <Form form={form} layout="vertical" requiredMark={false}
        initialValues={{
          product_type:'INDIVIDUAL_TERM', category:'Individual Life',
          uw_method:'FULL_UW', exam_required:'NONE',
          min_age:18, max_age:65, min_face_amount:500000, max_face_amount:5000000,
          non_medical_limit:500000, reinsurance_threshold:5000000, max_issue_age:65,
          stp_threshold:50, refer_threshold:150, decline_threshold:300,
          is_active:true, is_guaranteed_issue:false, is_group_product:false,
        }}>

        {/* Identity */}
        <div style={card}>
          <div style={secTitle}>Product Identity</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <Form.Item name="product_code" label="Product Code *"
              rules={[{required:true},{pattern:/^[A-Z0-9_-]+$/,message:'Uppercase, numbers, dashes only'}]}
              extra={<span style={{ fontSize:11 }}>e.g. IND-TERM-20, GRP-BASIC-1x</span>}>
              <Input placeholder="e.g. IND-TERM-20" style={{ textTransform:'uppercase', fontFamily:'var(--font-mono, monospace)' }}/>
            </Form.Item>
            <Form.Item name="product_name" label="Product Name *" rules={[{required:true}]}>
              <Input placeholder="e.g. Individual Term Life 20yr"/>
            </Form.Item>
            <Form.Item name="product_type" label="Product Type *">
              <Select>{PRODUCT_TYPES.map(t => <Option key={t} value={t}>{t}</Option>)}</Select>
            </Form.Item>
            <Form.Item name="category" label="Product Category *">
              <Select>{CATEGORIES.map(c => <Option key={c} value={c}>{c}</Option>)}</Select>
            </Form.Item>
            <Form.Item name="uw_method" label="UW Method *">
              <Select>{UW_METHODS.map(m => <Option key={m} value={m}>{m}</Option>)}</Select>
            </Form.Item>
          </div>
        </div>

        {/* Eligibility */}
        <div style={card}>
          <div style={secTitle}>Eligibility</div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:16 }}>
            <Form.Item name="min_age" label="Min Age"><InputNumber min={0} max={99} style={{ width:'100%' }}/></Form.Item>
            <Form.Item name="max_age" label="Max Age"><InputNumber min={1} max={100} style={{ width:'100%' }}/></Form.Item>
            <Form.Item name="min_face_amount" label="Min Face (₹)">
              <InputNumber min={0} step={10000} style={{ width:'100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v:any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
            <Form.Item name="max_face_amount" label="Max Face (₹)">
              <InputNumber min={0} step={100000} style={{ width:'100%' }}
                formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(v:any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
            </Form.Item>
          </div>
        </div>

        {/* Terms */}
        <div style={card}>
          <div style={secTitle}>Term Configuration</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <Form.Item name="available_terms" label="Available Terms (comma-separated years)"
              extra={<span style={{ fontSize:11 }}>e.g. 10,20,30 — leave blank for permanent</span>}>
              <Input placeholder="10,20,30"/>
            </Form.Item>
            <Form.Item name="exam_required" label="Exam Required">
              <Select>{EXAM_OPTIONS.map(e => <Option key={e} value={e}>{e}</Option>)}</Select>
            </Form.Item>

          </div>
        </div>

        {/* Financial + Thresholds */}
        <div style={card}>
          <div style={secTitle}>Financial Limits &amp; Decision Thresholds</div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:16 }}>
            <Form.Item name="non_medical_limit"     label="Non-Medical Limit (₹)">
              <InputNumber min={0} step={50000} style={{ width:'100%' }} formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
            </Form.Item>
            <Form.Item name="reinsurance_threshold" label="Reinsurance Threshold (₹)">
              <InputNumber min={0} step={500000} style={{ width:'100%' }} formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
            </Form.Item>
            <Form.Item name="max_issue_age"         label="Max Issue Age"><InputNumber min={1} max={100} style={{ width:'100%' }}/></Form.Item>
            <Form.Item name="stp_threshold"         label={<span style={{ color:'#22c55e' }}>STP Threshold</span>}><InputNumber min={0} max={200} style={{ width:'100%' }}/></Form.Item>
            <Form.Item name="refer_threshold"       label={<span style={{ color:'#fbbf24' }}>Refer Threshold</span>}><InputNumber min={0} max={400} style={{ width:'100%' }}/></Form.Item>
            <Form.Item name="decline_threshold"     label={<span style={{ color:'#ef4444' }}>Decline Threshold</span>}><InputNumber min={50} max={1000} style={{ width:'100%' }}/></Form.Item>
          </div>
        </div>

        {/* Validity + Settings */}
        <div style={card}>
          <div style={secTitle}>Validity &amp; Settings</div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <Form.Item name="effective_date" label="Effective Date"><Input type="date"/></Form.Item>
            <Form.Item name="expire_date"    label="Expire Date"><Input type="date"/></Form.Item>
          </div>
          <div style={{ display:'flex', gap:24, marginBottom:16 }}>
            <Form.Item name="is_active" valuePropName="checked" style={{ margin:0 }}>
              <Switch/> <span style={{ fontSize:13, color:'#9ca3af', marginLeft:8 }}>Product Active</span>
            </Form.Item>
            <Form.Item name="is_guaranteed_issue" valuePropName="checked" style={{ margin:0 }}>
              <Switch/> <span style={{ fontSize:13, color:'#9ca3af', marginLeft:8 }}>Guaranteed Issue</span>
            </Form.Item>
            <Form.Item name="is_group_product" valuePropName="checked" style={{ margin:0 }}>
              <Switch/> <span style={{ fontSize:13, color:'#9ca3af', marginLeft:8 }}>Group Product</span>
            </Form.Item>
          </div>
          <Form.Item name="description" label="Product Description"><TextArea rows={3}/></Form.Item>
          <Form.Item name="uw_notes"    label="UW Notes / Exam Notes"><TextArea rows={2}/></Form.Item>
        </div>

        <Button type="primary" icon={<PlusOutlined/>} loading={saving} onClick={save} size="large" block
          style={{ height:44, fontWeight:600 }}>
          Create Product
        </Button>
      </Form>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE SHELL
// ══════════════════════════════════════════════════════════════════════════════
export default function ProductConfigPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [selected, setSelected] = useState('')
  const [loading, setLoading]   = useState(true)
  const [activeTab, setTab]     = useState('rules')

  const loadProducts = async () => {
    setLoading(true)
    try {
      const r = await api.get('/products')
      const list = Array.isArray(r.data) ? r.data : []
      setProducts(list)
      if (list.length > 0 && !selected) setSelected(list[0].product_code)
    } catch { message.error('Failed to load products') }
    finally { setLoading(false) }
  }

  useEffect(() => { loadProducts() }, [])

  const prod = products.find(p => p.product_code === selected)

  const tabs = [
    {
      key: 'rules',
      label: '📋 Rules & Overrides',
      children: selected ? <RulesTab code={selected} prod={prod}/> : null,
    },
    {
      key: 'thresholds',
      label: '⚖️ Thresholds',
      children: selected ? <ThresholdsTab code={selected}/> : null,
    },
    {
      key: 'build',
      label: '📐 Build Table',
      children: selected ? <BuildTableTab code={selected}/> : null,
    },
    {
      key: 'uw-scales',
      label: '⚖️ UW Scales',
      children: selected ? <ProductScalesTab code={selected}/> : null,
    },
    {
      key: 'premium-formula',
      label: '💰 Premium Formula',
      children: selected ? <PremiumFormulaTab code={selected}/> : null,
    },
    {
      key: 'edit',
      label: <span><EditOutlined/> Edit Product</span>,
      children: selected ? <EditProductTab code={selected} onSaved={loadProducts}/> : null,
    },
    {
      key: 'add',
      label: <span><PlusOutlined/> Add Product</span>,
      children: <AddProductTab onCreated={() => { loadProducts(); setTab('rules') }}/>,
    },
  ]

  return (
    <div style={{ padding:'32px 36px' }}>
      <div style={{ marginBottom:24 }}>
        <h1 style={{ fontWeight:700, fontSize:20, color:'#e2e8f0', margin:0, letterSpacing:'-0.02em', display:'flex', alignItems:'center', gap:10 }}>
          <SettingOutlined style={{ color:'#00d4aa' }}/>Product Configuration
        </h1>
        <p style={{ color:'#6b7280', fontSize:13, marginTop:4, marginBottom:0 }}>
          Configure products, underwriting rules, thresholds, and build tables.
        </p>
      </div>

      <ProductSelector
        products={products} selected={selected}
        onSelect={code => { setSelected(code); setTab('rules') }}
        loading={loading} onRefresh={loadProducts}
      />

      {!selected && !loading ? (
        <div style={{ textAlign:'center', padding:'40px 0 20px', color:'#6b7280', fontSize:13 }}>
          No products found — create your first product in the <strong style={{ color:'#e2e8f0' }}>Add Product</strong> tab below.
        </div>
      ) : null}

      {(!loading) && (
        <Tabs activeKey={selected ? activeTab : 'add'} onChange={setTab} items={tabs}
          tabBarStyle={{ borderBottom:'1px solid rgba(255,255,255,0.07)', marginBottom:24 }}/>
      )}
    </div>
  )
}

