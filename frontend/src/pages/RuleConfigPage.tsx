import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Select, Spin, Switch, InputNumber,
  message, Form, Input, Tabs, Popconfirm, Modal,
} from 'antd'
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, SearchOutlined,
  LinkOutlined, SettingOutlined, BookOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

const { Option } = Select
const { TextArea } = Input

// ── Constants ──────────────────────────────────────────────────────────────────
const DEFAULT_FIELDS = [
  'age','bmi','gender','state','face_amount','occupation_class',
  'tobacco_status','dui_count','major_violation_count','systolic_bp',
  'diastolic_bp','diabetes_type','heart_condition','cancer_status',
  'hiv_positive','alcohol_use','hazardous_activity','cholesterol',
  'hdl','ldl','egfr','a1c','family_hx_cvd','family_hx_stroke',
  'annual_income','existing_coverage',
]
const OPERATORS  = ['>','<','>=','<=','==','!=','in','not_in']
const CATEGORIES = ['CUSTOM','BUILD','MEDICAL','FINANCIAL','LIFESTYLE','OCCUPATION','DRIVING','PRODUCT','STATE']
const OUTCOMES   = ['REFER','DECLINE','APPROVE','FLAT_EXTRA','TABLE_RATING','DEBIT_ONLY']
const STATUSES   = ['DRAFT','IN_REVIEW','APPROVED','DEPLOYED','ARCHIVED']
const TABLE_RATINGS = [0,2,4,6,8,10,12,14,16]

const WORKFLOW: Record<string, string[]> = {
  DRAFT:     ['IN_REVIEW'],
  IN_REVIEW: ['APPROVED','DRAFT'],
  APPROVED:  ['DEPLOYED','IN_REVIEW'],
  DEPLOYED:  ['ARCHIVED'],
  ARCHIVED:  [],
}
const STATUS_COLOR: Record<string, string> = {
  DRAFT:'#64748b', IN_REVIEW:'#f59e0b', APPROVED:'#3b82f6', DEPLOYED:'#22c55e', ARCHIVED:'#ef4444',
}
const STATUS_EMOJI: Record<string, string> = {
  DRAFT:'📝', IN_REVIEW:'🔍', APPROVED:'✅', DEPLOYED:'🚀', ARCHIVED:'📦',
}

// ── Styles ─────────────────────────────────────────────────────────────────────
const card: React.CSSProperties = {
  background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.07)',
  borderRadius:10, padding:'20px 24px', marginBottom:16,
}
const secTitle: React.CSSProperties = {
  fontSize:11, fontWeight:600, color:'#6b7280',
  textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:14,
}

// ── Types ──────────────────────────────────────────────────────────────────────
interface CustomRule {
  id?: string; rule_id?: string; rule_code?: string; rule_name?: string
  category?: string; status?: string; version?: string; priority?: number
  description?: string; product_code?: string; condition_logic?: string
  debit_points?: number; hard_stop?: boolean; requires_aps?: boolean
  effective_date?: string; expire_date?: string; created_at?: string
  conditions?: any; action?: any
}
interface CustomField {
  field_name: string; label?: string; data_type?: string; description?: string
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1 — Rule Library (built-in)
// ══════════════════════════════════════════════════════════════════════════════
function RuleLibraryTab() {
  const [rules, setRules]       = useState<any[]>([])
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState('')
  const [catFilter, setCat]     = useState('All')
  const [showFilter, setShow]   = useState('All')

  useEffect(() => {
    api.get('/rules/library').then(r => setRules(Array.isArray(r.data) ? r.data : []))
      .catch(() => setRules([]))
      .finally(() => setLoading(false))
  }, [])

  const cats = ['All', ...Array.from(new Set(rules.map(r => r.category || '—'))).sort()]

  const filtered = rules.filter(r => {
    const q   = search.toLowerCase()
    const mQ  = !q || (r.rule_id||'').toLowerCase().includes(q) || (r.rule_name||'').toLowerCase().includes(q) || (r.category||'').toLowerCase().includes(q)
    const mC  = catFilter === 'All' || r.category === catFilter
    const mS  = showFilter === 'All'
      || (showFilter === 'Hard stops'   && r.hard_stop)
      || (showFilter === 'Debits only'  && r.debit_points > 0 && !r.hard_stop)
      || (showFilter === 'Credits only' && r.credit_points > 0)
      || (showFilter === 'APS required' && r.requires_aps)
    return mQ && mC && mS
  })

  const cols = [
    { title:'Rule ID',   dataIndex:'rule_id',   width:100, render:(v:string) => <span style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa', fontWeight:600 }}>{v}</span> },
    { title:'Rule Name', dataIndex:'rule_name'  },
    { title:'Category',  dataIndex:'category',  width:140 },
    { title:'Debits',    dataIndex:'debit_points',  width:80  },
    { title:'Credits',   dataIndex:'credit_points', width:80  },
    { title:'Flat Extra',dataIndex:'flat_extra', width:100, render:(v:number) => v ? `$${v}/K` : '—' },
    { title:'Hard Stop', dataIndex:'hard_stop',  width:90,  render:(v:boolean) => v ? <Tag color="error">🔴</Tag> : '' },
    { title:'APS',       dataIndex:'requires_aps', width:70, render:(v:boolean) => v ? <Tag color="purple">📋</Tag> : '' },
  ]

  return (
    <div>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        Core medical impairment rules — <strong style={{ color:'#e2e8f0' }}>{rules.length} rules</strong> built into the engine. Read-only reference.
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:20 }}>
        {[
          { label:'Total Rules',  value:rules.length,                           color:'#00d4aa' },
          { label:'Hard Stops',   value:rules.filter(r=>r.hard_stop).length,    color:'#ef4444' },
          { label:'APS Required', value:rules.filter(r=>r.requires_aps).length, color:'#c084fc' },
        ].map(s => (
          <div key={s.label} style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:10, padding:'12px 16px' }}>
            <div style={{ fontSize:20, fontWeight:700, color:s.color }}>{s.value}</div>
            <div style={{ fontSize:11, color:'#6b7280', marginTop:2 }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ display:'flex', gap:10, marginBottom:16 }}>
        <Input prefix={<SearchOutlined style={{ color:'#6b7280' }}/>}
          placeholder="name, ID, category…" value={search}
          onChange={e => setSearch(e.target.value)} style={{ maxWidth:300 }} allowClear/>
        <Select value={catFilter} onChange={setCat} style={{ width:180 }}>
          {cats.map(c => <Option key={c} value={c}>{c}</Option>)}
        </Select>
        <Select value={showFilter} onChange={setShow} style={{ width:160 }}>
          {['All','Hard stops','Debits only','Credits only','APS required'].map(s => <Option key={s} value={s}>{s}</Option>)}
        </Select>
      </div>

      <div style={{ fontSize:12, color:'#6b7280', marginBottom:8 }}>Showing {filtered.length} of {rules.length} rules</div>

      {loading ? <Spin/> : (
        <Table dataSource={filtered} columns={cols} rowKey="rule_id" size="small"
          pagination={{ pageSize:20, showSizeChanger:false }}
          locale={{ emptyText: rules.length === 0 ? 'Rule library endpoint not available — rules are active in the engine.' : 'No rules match your filters' }}/>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2 — Custom Rules list + manage
// ══════════════════════════════════════════════════════════════════════════════
function CustomRulesTab({ rules, loading, onRefresh }: {
  rules: CustomRule[]; loading: boolean; onRefresh: () => void
}) {
  const [search, setSearch]       = useState('')
  const [statusF, setStatusF]     = useState('All')
  const [selected, setSelected]   = useState<CustomRule|null>(null)
  const [transitioning, setTrans] = useState(false)
  const [newStatus, setNewStatus] = useState('')
  const [reason, setReason]       = useState('')
  const [deleting, setDeleting]   = useState(false)

  const filtered = rules.filter(r => {
    const q  = search.toLowerCase()
    const mQ = !q || (r.rule_name||'').toLowerCase().includes(q) || (r.rule_code||r.rule_id||'').toLowerCase().includes(q)
    const mS = statusF === 'All' || r.status === statusF
    return mQ && mS
  })

  const statuses = rules.map(r => r.status || 'DRAFT')

  const doTransition = async () => {
    if (!selected || !newStatus || !reason.trim()) { message.warning('Reason is required'); return }
    setTrans(true)
    try {
      const id = selected.id || selected.rule_id || selected.rule_code
      await api.post(`/custom-rules/${id}/workflow`, { new_status: newStatus, reason })
      message.success(`Status → ${newStatus}`); setSelected(null); setReason(''); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Transition failed') }
    finally { setTrans(false) }
  }

  const doDelete = async (rule: CustomRule) => {
    setDeleting(true)
    try {
      const id = rule.id || rule.rule_id || rule.rule_code
      await api.delete(`/custom-rules/${id}`)
      message.success('Rule deleted'); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Delete failed') }
    finally { setDeleting(false) }
  }

  const cols = [
    { title:'Status', dataIndex:'status', width:130,
      render:(v:string) => <Tag style={{ background:STATUS_COLOR[v]||'#64748b', color:'#fff', border:'none', fontSize:11 }}>
        {STATUS_EMOJI[v]||''} {v}
      </Tag> },
    { title:'Code', dataIndex:'rule_code', width:110,
      render:(v:string, r:CustomRule) => <span style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa', fontWeight:600 }}>{v || r.rule_id}</span> },
    { title:'Name', dataIndex:'rule_name' },
    { title:'Category', dataIndex:'category', width:110 },
    { title:'Debits', dataIndex:'debit_points', width:70 },
    { title:'Hard Stop', dataIndex:'hard_stop', width:90, render:(v:boolean) => v ? <Tag color="error">YES</Tag> : '' },
    { title:'Effective', dataIndex:'effective_date', width:110, render:(v:string) => v?.slice(0,10) || 'Immediate' },
    { title:'Actions', width:150,
      render:(_:any, r:CustomRule) => (
        <div style={{ display:'flex', gap:5 }}>
          <Button size="small" onClick={() => { setSelected(r); setNewStatus(WORKFLOW[r.status||'DRAFT']?.[0]||'') }}
            style={{ borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa' }}>Manage</Button>
          {(r.status === 'DRAFT' || r.status === 'ARCHIVED') && (
            <Popconfirm title="Delete this rule?" onConfirm={() => doDelete(r)} okText="Delete" cancelText="No">
              <Button size="small" danger icon={<DeleteOutlined/>} loading={deleting}/>
            </Popconfirm>
          )}
        </div>
      )},
  ]

  return (
    <div>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:12, marginBottom:20 }}>
        {[
          { label:'Total',     value:rules.length,                               color:'#00d4aa' },
          { label:'Draft',     value:statuses.filter(s=>s==='DRAFT').length,     color:'#64748b' },
          { label:'In Review', value:statuses.filter(s=>s==='IN_REVIEW').length, color:'#f59e0b' },
          { label:'Deployed',  value:statuses.filter(s=>s==='DEPLOYED').length,  color:'#22c55e' },
          { label:'Archived',  value:statuses.filter(s=>s==='ARCHIVED').length,  color:'#ef4444' },
        ].map(s => (
          <div key={s.label} style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:10, padding:'12px 16px' }}>
            <div style={{ fontSize:18, fontWeight:700, color:s.color }}>{s.value}</div>
            <div style={{ fontSize:11, color:'#6b7280', marginTop:2 }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ display:'flex', gap:10, marginBottom:16 }}>
        <Input prefix={<SearchOutlined style={{ color:'#6b7280' }}/>}
          placeholder="Search name or code…" value={search}
          onChange={e => setSearch(e.target.value)} style={{ maxWidth:280 }} allowClear/>
        <Select value={statusF} onChange={setStatusF} style={{ width:160 }}>
          <Option value="All">All statuses</Option>
          {STATUSES.map(s => <Option key={s} value={s}>{STATUS_EMOJI[s]} {s}</Option>)}
        </Select>
        <Button icon={<ReloadOutlined/>} onClick={onRefresh} loading={loading} style={{ marginLeft:'auto' }}/>
      </div>

      {loading ? <Spin/> : rules.length === 0 ? (
        <div style={{ color:'#6b7280', fontSize:13 }}>No custom rules yet. Use the <strong style={{ color:'#e2e8f0' }}>Create Rule</strong> tab to add one.</div>
      ) : (
        <Table dataSource={filtered} columns={cols} rowKey={r => String(r.id||r.rule_id||r.rule_code||'')} size="small"
          pagination={{ pageSize:20, showSizeChanger:false }}/>
      )}

      {/* Manage Rule Modal */}
      <Modal
        title={<span style={{ color:'#e2e8f0' }}>Manage — {selected?.rule_name}</span>}
        open={!!selected} onCancel={() => setSelected(null)} footer={null} width={560}
        styles={{ content:{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.09)' }, header:{ background:'#0d1521' } }}>
        {selected && (
          <div style={{ marginTop:16 }}>
            <div style={{ marginBottom:16 }}>
              <Tag style={{ background:STATUS_COLOR[selected.status||'DRAFT'], color:'#fff', border:'none' }}>
                {STATUS_EMOJI[selected.status||'DRAFT']} {selected.status}
              </Tag>
              <span style={{ fontSize:13, color:'#9ca3af', marginLeft:8 }}>
                {selected.rule_name} · v{selected.version||'1.0'}
              </span>
            </div>

            {(WORKFLOW[selected.status||'DRAFT']||[]).length > 0 && (
              <div style={{ ...card, marginBottom:16 }}>
                <div style={secTitle}>Change Status</div>
                <Select value={newStatus} onChange={setNewStatus} style={{ width:'100%', marginBottom:10 }}>
                  {(WORKFLOW[selected.status||'DRAFT']||[]).map(s =>
                    <Option key={s} value={s}>{STATUS_EMOJI[s]} {s}</Option>)}
                </Select>
                <Input placeholder="Reason for status change (required for audit log)"
                  value={reason} onChange={e => setReason(e.target.value)} style={{ marginBottom:10 }}/>
                <Button type="primary" loading={transitioning} onClick={doTransition} block>
                  Apply Transition
                </Button>
              </div>
            )}

            <div style={card}>
              <div style={secTitle}>Rule JSON</div>
              <pre style={{ fontSize:11, color:'#9ca3af', overflow:'auto', maxHeight:300, margin:0 }}>
                {JSON.stringify(selected, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3 — Create Rule (condition builder)
// ══════════════════════════════════════════════════════════════════════════════
function CreateRuleTab({ customFields, onCreated }: { customFields: CustomField[]; onCreated: () => void }) {
  const allFields = [...new Set([...DEFAULT_FIELDS, ...customFields.map(f => f.field_name)])].sort()

  const [numConds, setNumConds]   = useState(1)
  const [conditions, setConds]    = useState<{field:string;op:string;value:string;search:string}[]>(
    [{ field: allFields[0]||'age', op:'>', value:'', search:'' }]
  )
  const [saving, setSaving]       = useState(false)
  const [ruleId, setRuleId]       = useState('')
  const [ruleName, setRuleName]   = useState('')
  const [version, setVersion]     = useState('1.0')
  const [category, setCategory]   = useState('CUSTOM')
  const [logic, setLogic]         = useState('AND')
  const [priority, setPriority]   = useState(100)
  const [desc, setDesc]           = useState('')
  const [prodCode, setProdCode]   = useState('')
  const [outcome, setOutcome]     = useState('REFER')
  const [debits, setDebits]       = useState(0)
  const [flatExtra, setFlatExtra] = useState(0)
  const [tableRat, setTableRat]   = useState(0)
  const [hardStop, setHardStop]   = useState(false)
  const [aps, setAps]             = useState(false)
  const [reason, setReason]       = useState('')
  const [effDate, setEff]         = useState('')
  const [expDate, setExp]         = useState('')

  const addCond = () => {
    if (numConds >= 10) return
    setNumConds(n => n+1)
    setConds(c => [...c, { field:allFields[0]||'age', op:'>', value:'', search:'' }])
  }
  const remCond = () => {
    if (numConds <= 1) return
    setNumConds(n => n-1)
    setConds(c => c.slice(0,-1))
  }
  const updateCond = (i:number, k:string, v:string) => {
    setConds(c => c.map((x,j) => j===i ? {...x,[k]:v} : x))
  }

  const save = async () => {
    const errs: string[] = []
    if (!ruleId.trim())   errs.push('Rule ID is required')
    if (!ruleName.trim()) errs.push('Rule Name is required')
    const parsedConds = conditions.slice(0, numConds).map((c,i) => {
      if (!c.value.trim()) { errs.push(`Condition ${i+1}: Value is required`); return null }
      let v: any = c.value.trim()
      if (!isNaN(Number(v))) v = Number(v)
      else if (v.includes(',')) v = v.split(',').map((x:string) => x.trim())
      return { field: c.field, operator: c.op, value: v }
    }).filter(Boolean)

    if (errs.length) { errs.forEach(e => message.error(e)); return }

    const condJson = parsedConds.length > 1
      ? { logic, conditions: parsedConds }
      : parsedConds[0] || {}

    const actionJson = {
      outcome, debit_points: debits,
      flat_extra:   flatExtra > 0 ? flatExtra : null,
      table_rating: tableRat  > 0 ? tableRat  : null,
      hard_stop: hardStop, reason: reason.trim() || null,
    }

    setSaving(true)
    try {
      await api.post('/custom-rules', {
        rule_id:        ruleId.trim().toUpperCase(),
        rule_name:      ruleName.trim(),
        rule_code:      ruleId.trim().toUpperCase(),
        version:        version.trim() || '1.0',
        category, priority,
        description:    desc.trim() || null,
        product_code:   prodCode.trim() || null,
        condition_logic:logic,
        debit_points:   debits,
        hard_stop:      hardStop,
        requires_aps:   aps,
        effective_date: effDate || null,
        expire_date:    expDate || null,
        conditions:     condJson,
        action:         actionJson,
        status:         'DRAFT',
      })
      message.success(`Rule ${ruleId.toUpperCase()} saved as DRAFT`)
      onCreated()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ maxWidth:900 }}>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        Build a rule with conditions and actions. Rules run after the built-in library.
      </div>

      {/* Identity */}
      <div style={card}>
        <div style={secTitle}>Rule Identity</div>
        <div style={{ display:'grid', gridTemplateColumns:'2fr 2fr 1fr', gap:12, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Rule ID *</div>
            <Input value={ruleId} onChange={e => setRuleId(e.target.value)} placeholder="e.g. CUST001"
              style={{ fontFamily:'var(--font-mono,monospace)', textTransform:'uppercase' }}/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Rule Name *</div>
            <Input value={ruleName} onChange={e => setRuleName(e.target.value)} placeholder="e.g. High BMI Refer"/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Version</div>
            <Input value={version} onChange={e => setVersion(e.target.value)} placeholder="1.0"/>
          </div>
        </div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Category</div>
            <Select value={category} onChange={setCategory} style={{ width:'100%' }} placeholder="Select category…">
              {CATEGORIES.map(c => <Option key={c} value={c}>{c}</Option>)}
            </Select>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Condition Logic</div>
            <Select value={logic} onChange={setLogic} style={{ width:'100%' }} placeholder="Select logic…">
              <Option value="AND">AND — all must match</Option>
              <Option value="OR">OR — any must match</Option>
            </Select>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Priority</div>
            <InputNumber value={priority} onChange={v => setPriority(v||100)} min={1} max={9999} style={{ width:'100%' }} placeholder="e.g. 100"/>
          </div>
        </div>
        <div style={{ marginBottom:12 }}>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Description (optional)</div>
          <Input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Brief description of when this rule fires"/>
        </div>
        <div>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Product Code (blank = all products)</div>
          <Input value={prodCode} onChange={e => setProdCode(e.target.value)} placeholder="e.g. IND-TERM-20 (blank = applies to all products)" style={{ maxWidth:280 }}/>
        </div>
      </div>

      {/* Conditions */}
      <div style={card}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:14 }}>
          <div style={{ ...secTitle, marginBottom:0 }}>
            Conditions <span style={{ color:'#4b5563', fontWeight:400, textTransform:'none', letterSpacing:0 }}>
              ({numConds} row{numConds>1?'s':''} · max 10)
            </span>
          </div>
          <div style={{ display:'flex', gap:8 }}>
            <Button icon={<PlusOutlined/>} onClick={addCond} disabled={numConds>=10}
              style={{ borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa' }}>Add Condition</Button>
            <Button onClick={remCond} disabled={numConds<=1} style={{ color:'#6b7280' }}>Remove Last</Button>
          </div>
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'160px 1fr 130px 1fr', gap:8, marginBottom:6 }}>
          <div style={{ fontSize:11, color:'#6b7280' }}>🔍 Search field</div>
          <div style={{ fontSize:11, color:'#6b7280' }}>Field</div>
          <div style={{ fontSize:11, color:'#6b7280' }}>Operator</div>
          <div style={{ fontSize:11, color:'#6b7280' }}>Value</div>
        </div>

        {conditions.slice(0, numConds).map((c, i) => {
          const filteredFields = c.search
            ? allFields.filter(f => f.toLowerCase().includes(c.search.toLowerCase()))
            : allFields
          return (
            <div key={i} style={{ display:'grid', gridTemplateColumns:'160px 1fr 130px 1fr', gap:8, marginBottom:8 }}>
              <Input value={c.search} onChange={e => updateCond(i,'search',e.target.value)}
                placeholder="type to filter…" size="small"
                prefix={<SearchOutlined style={{ color:'#6b7280', fontSize:11 }}/>}/>
              <Select value={filteredFields.includes(c.field)?c.field:filteredFields[0]}
                onChange={v => updateCond(i,'field',v)} size="small"
                style={{ fontFamily:'var(--font-mono,monospace)' }}>
                {filteredFields.map(f => <Option key={f} value={f}>{f}</Option>)}
              </Select>
              <Select value={c.op} onChange={v => updateCond(i,'op',v)} size="small">
                {OPERATORS.map(o => <Option key={o} value={o}>{o}</Option>)}
              </Select>
              <Input value={c.value} onChange={e => updateCond(i,'value',e.target.value)}
                placeholder="e.g. 35" size="small"/>
            </div>
          )
        })}
      </div>

      {/* Actions */}
      <div style={card}>
        <div style={secTitle}>Actions</div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Outcome</div>
            <Select value={outcome} onChange={setOutcome} style={{ width:'100%' }} placeholder="Select outcome…">
              {OUTCOMES.map(o => <Option key={o} value={o}>{o}</Option>)}
            </Select>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Debit Points</div>
            <InputNumber value={debits} onChange={v => setDebits(v||0)} min={0} max={999} style={{ width:'100%' }} placeholder="e.g. 50"/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Flat Extra ($/K/yr)</div>
            <InputNumber value={flatExtra} onChange={v => setFlatExtra(v||0)} min={0} max={20} step={0.5} style={{ width:'100%' }} placeholder="e.g. 2.5"/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Table Rating</div>
            <Select value={tableRat} onChange={setTableRat} style={{ width:'100%' }} placeholder="Select table rating…">
              {TABLE_RATINGS.map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select>
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:10, paddingTop:20 }}>
            <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer' }}>
              <input type="checkbox" checked={hardStop} onChange={e => setHardStop(e.target.checked)}/>
              Hard Stop (instant decline)
            </label>
            <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer' }}>
              <input type="checkbox" checked={aps} onChange={e => setAps(e.target.checked)}/>
              Requires APS
            </label>
          </div>
        </div>
        <div>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Reason / Message</div>
          <Input value={reason} onChange={e => setReason(e.target.value)}
            placeholder="e.g. BMI exceeds maximum threshold for STP"/>
        </div>
      </div>

      {/* Validity */}
      <div style={card}>
        <div style={secTitle}>Validity Period</div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Effective Date</div>
            <Input type="date" value={effDate} onChange={e => setEff(e.target.value)}/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Expire Date <span style={{ color:'#4b5563' }}>(blank = never)</span></div>
            <Input type="date" value={expDate} onChange={e => setExp(e.target.value)}/>
          </div>
        </div>
      </div>

      <Button type="primary" loading={saving} onClick={save} size="large" block style={{ height:44, fontWeight:600 }}>
        ✅ Save Rule as DRAFT
      </Button>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4 — Assign to Product
// ══════════════════════════════════════════════════════════════════════════════
function AssignToProductTab() {
  const [products, setProducts]   = useState<any[]>([])
  const [selProd, setSelProd]     = useState('')
  const [assigned, setAssigned]   = useState<any[]>([])
  const [ruleInput, setRuleInput] = useState('')
  const [enabled, setEnabled]     = useState(true)
  const [replace, setReplace]     = useState(false)
  const [loading, setLoading]     = useState(false)
  const [assigning, setAssigning] = useState(false)

  useEffect(() => {
    api.get('/products').then(r => {
      const list = Array.isArray(r.data) ? r.data : []
      setProducts(list)
      if (list.length > 0) setSelProd(list[0].product_code)
    }).catch(() => {})
  }, [])

  const loadAssigned = (code: string) => {
    setLoading(true)
    api.get(`/products/${code}/rules`)
      .then(r => setAssigned(Array.isArray(r.data) ? r.data : []))
      .catch(() => setAssigned([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { if (selProd) loadAssigned(selProd) }, [selProd])

  const assign = async () => {
    if (!ruleInput.trim()) { message.warning('Enter at least one Rule ID'); return }
    const ruleIds = ruleInput.split(',').map(r => r.trim().toUpperCase()).filter(Boolean)
    setAssigning(true)
    try {
      await api.post(`/products/${selProd}/rules/assign`, {
        product_code: selProd, rule_ids: ruleIds, is_enabled: enabled, replace,
      })
      message.success(`${ruleIds.length} rule(s) assigned to ${selProd}`)
      setRuleInput(''); loadAssigned(selProd)
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Assign failed') }
    finally { setAssigning(false) }
  }

  const cols = [
    { title:'Rule ID', dataIndex:'rule_id', width:120, render:(v:string) => <span style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa' }}>{v}</span> },
    { title:'Rule Name', dataIndex:'rule_name', render:(v:string) => v || '—' },
    { title:'Enabled', dataIndex:'is_enabled', width:110, render:(v:boolean) => <Tag color={v?'success':'error'}>{v?'✅ Enabled':'🔴 Disabled'}</Tag> },
  ]

  return (
    <div>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        Select a product and assign built-in or custom rules to it. Assigned rules appear in Product Config → Rules &amp; Overrides.
      </div>

      <div style={card}>
        <div style={secTitle}>Select Product</div>
        <div style={{ display:'flex', gap:10 }}>
          <Select value={selProd} onChange={v => setSelProd(v)} style={{ flex:1 }} showSearch>
            {products.map(p => <Option key={p.product_code} value={p.product_code}>
              {p.product_code} — {p.product_name}
            </Option>)}
          </Select>
          <Button icon={<ReloadOutlined/>} loading={loading} onClick={() => loadAssigned(selProd)}/>
        </div>
      </div>

      <div style={card}>
        <div style={secTitle}>Currently Assigned — {selProd} ({assigned.length} rules)</div>
        {loading ? <Spin/> : assigned.length === 0
          ? <div style={{ color:'#6b7280', fontSize:13 }}>No rules assigned to {selProd} yet.</div>
          : <Table dataSource={assigned} columns={cols} rowKey="rule_id" size="small" pagination={false}/>
        }
      </div>

      <div style={card}>
        <div style={secTitle}>Assign Rules from Library</div>
        <div style={{ fontSize:12, color:'#6b7280', marginBottom:12 }}>
          Enter comma-separated rule IDs from the Rule Library tab (e.g. R010, R020, R060)
        </div>
        <Input value={ruleInput} onChange={e => setRuleInput(e.target.value)}
          placeholder="e.g. R010, R020, R060, R070" style={{ marginBottom:12 }}/>
        <div style={{ display:'flex', gap:20, marginBottom:16 }}>
          <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer' }}>
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}/>
            Enable rules immediately
          </label>
          <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer' }}>
            <input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)}/>
            Replace existing assignments
          </label>
        </div>
        <Button type="primary" icon={<LinkOutlined/>} loading={assigning} onClick={assign}>
          Assign Rules
        </Button>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 5 — Manage Fields
// ══════════════════════════════════════════════════════════════════════════════
function ManageFieldsTab({ customFields, onRefresh }: { customFields: CustomField[]; onRefresh: () => void }) {
  const [fname, setFname]   = useState('')
  const [label, setLabel]   = useState('')
  const [dtype, setDtype]   = useState('numeric')
  const [fdesc, setFdesc]   = useState('')
  const [saving, setSaving] = useState(false)

  const allDisplay = [
    ...DEFAULT_FIELDS.map(f => ({ field: f, source: '🔒 Built-in', type: '—', description: '—' })),
    ...customFields.map(f => ({ field: f.field_name, source: '✏️ Custom', type: f.data_type||'—', description: f.description||'—' })),
  ]

  const add = async () => {
    const clean = fname.trim().toLowerCase().replace(/\s+/g,'_')
    if (!clean) { message.error('Field name is required'); return }
    if (DEFAULT_FIELDS.includes(clean)) { message.error(`${clean} is already a built-in field`); return }
    if (!/^[a-z0-9_]+$/.test(clean)) { message.error('Field name can only contain letters, numbers and underscores'); return }
    setSaving(true)
    try {
      await api.post('/rules/custom-fields', { field_name: clean, label: label.trim()||clean, data_type: dtype, description: fdesc.trim() })
      message.success(`Field ${clean} added`); setFname(''); setLabel(''); setFdesc(''); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Failed to add field') }
    finally { setSaving(false) }
  }

  const remove = async (fieldName: string) => {
    try {
      await api.delete(`/rules/custom-fields/${fieldName}`)
      message.success(`Field ${fieldName} removed`); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Failed') }
  }

  const cols = [
    { title:'Field', dataIndex:'field', render:(v:string) => <span style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa' }}>{v}</span> },
    { title:'Source', dataIndex:'source', width:110 },
    { title:'Type',   dataIndex:'type',   width:100 },
    { title:'Description', dataIndex:'description' },
    { title:'', width:60, render:(_:any, r:any) => r.source === '✏️ Custom' ? (
      <Popconfirm title={`Remove field ${r.field}?`} onConfirm={() => remove(r.field)} okText="Remove" cancelText="No">
        <Button size="small" danger icon={<DeleteOutlined/>}/>
      </Popconfirm>
    ) : null },
  ]

  return (
    <div>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        Add custom fields to the rule condition builder. New fields appear immediately in the Field dropdown when creating rules.
      </div>

      <div style={card}>
        <div style={secTitle}>
          {DEFAULT_FIELDS.length} built-in · {customFields.length} custom · {DEFAULT_FIELDS.length + customFields.length} total
        </div>
        <Table dataSource={allDisplay} columns={cols} rowKey="field" size="small"
          pagination={{ pageSize:15, showSizeChanger:false }}/>
      </div>

      <div style={card}>
        <div style={secTitle}>Add Custom Field</div>
        <div style={{ fontSize:12, color:'#6b7280', marginBottom:12 }}>
          The field name must exactly match the JSON key your underwriting engine sends — e.g. if the engine payload has <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa' }}>"creatinine": 1.2</code>, the field name is <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa' }}>creatinine</code>.
        </div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Field Name *</div>
            <Input value={fname} onChange={e => setFname(e.target.value)} placeholder="e.g. creatinine"
              style={{ fontFamily:'var(--font-mono,monospace)' }}/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Display Label</div>
            <Input value={label} onChange={e => setLabel(e.target.value)} placeholder="e.g. Creatinine Level"/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Data Type</div>
            <Select value={dtype} onChange={setDtype} style={{ width:'100%' }}>
              <Option value="numeric">numeric — numbers (age, BMI, creatinine)</Option>
              <Option value="text">text — string values (state, occupation)</Option>
              <Option value="boolean">boolean — true/false flags</Option>
              <Option value="enum">enum — fixed set of values (gender, diabetes_type)</Option>
            </Select>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Description (optional)</div>
            <Input value={fdesc} onChange={e => setFdesc(e.target.value)} placeholder="e.g. Serum creatinine in mg/dL"/>
          </div>
        </div>
        <Button type="primary" icon={<PlusOutlined/>} loading={saving} onClick={add}>
          Add Field
        </Button>
      </div>

      {customFields.length > 0 && (
        <div style={{ ...card, borderColor:'rgba(251,191,36,0.2)', background:'rgba(251,191,36,0.04)' }}>
          <div style={{ fontSize:12, color:'#fbbf24' }}>
            ⚠ Removing a field does not update existing rules that use it. Those rules will continue to reference the old field name — edit or delete them manually in the Custom Rules tab.
          </div>
        </div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE SHELL
// ══════════════════════════════════════════════════════════════════════════════
export default function RuleConfigPage() {
  const [customRules, setRules]   = useState<CustomRule[]>([])
  const [customFields, setFields] = useState<CustomField[]>([])
  const [loading, setLoading]     = useState(false)
  const [activeTab, setTab]       = useState('library')

  const loadRules = async () => {
    setLoading(true)
    try { const r = await api.get('/custom-rules'); setRules(Array.isArray(r.data) ? r.data : []) }
    catch { setRules([]) }
    finally { setLoading(false) }
  }

  const loadFields = async () => {
    try { const r = await api.get('/rules/custom-fields'); setFields(Array.isArray(r.data) ? r.data : []) }
    catch { setFields([]) }
  }

  useEffect(() => { loadRules(); loadFields() }, [])

  const tabs = [
    {
      key: 'library',
      label: <span><BookOutlined/> Rule Library</span>,
      children: <RuleLibraryTab/>,
    },
    {
      key: 'custom',
      label: <span><ThunderboltOutlined/> Custom Rules</span>,
      children: <CustomRulesTab rules={customRules} loading={loading} onRefresh={loadRules}/>,
    },
    {
      key: 'create',
      label: <span><PlusOutlined/> Create Rule</span>,
      children: <CreateRuleTab customFields={customFields} onCreated={() => { loadRules(); setTab('custom') }}/>,
    },
    {
      key: 'assign',
      label: <span><LinkOutlined/> Assign to Product</span>,
      children: <AssignToProductTab/>,
    },
    {
      key: 'fields',
      label: <span><SettingOutlined/> Manage Fields</span>,
      children: <ManageFieldsTab customFields={customFields} onRefresh={loadFields}/>,
    },
  ]

  return (
    <div style={{ padding:'32px 36px' }}>
      <div style={{ marginBottom:24 }}>
        <h1 style={{ fontWeight:700, fontSize:20, color:'#e2e8f0', margin:0, letterSpacing:'-0.02em', display:'flex', alignItems:'center', gap:10 }}>
          <SettingOutlined style={{ color:'#00d4aa' }}/>Rule Builder
        </h1>
        <p style={{ color:'#6b7280', fontSize:13, marginTop:4, marginBottom:0 }}>
          View the built-in medical impairment library and create custom JSON-based underwriting rules.
        </p>
      </div>
      <Tabs activeKey={activeTab} onChange={setTab} items={tabs}
        tabBarStyle={{ borderBottom:'1px solid rgba(255,255,255,0.07)', marginBottom:24 }}/>
    </div>
  )
}
