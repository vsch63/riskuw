import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Select, Spin, Drawer, Input, Form, Modal,
  message, Tabs, Badge, Empty, Popconfirm,
} from 'antd'
import {
  UserAddOutlined, FileTextOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined,
  PlusOutlined, SendOutlined,
} from '@ant-design/icons'
import { Titled } from '../components/ColHint'

const { Option } = Select
const { TextArea } = Input

// Direct fetch helper for /workbench/* routes
const _tok = () => localStorage.getItem('riskuw_token') || ''
const wbApi = {
  get: (path: string) =>
    fetch(path, { headers: { Authorization: `Bearer ${_tok()}` } }).then(r => r.json()),
  post: (path: string, body?: any) =>
    fetch(path, { method: 'POST', headers: { Authorization: `Bearer ${_tok()}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json()),
  patch: (path: string, body?: any) =>
    fetch(path, { method: 'PATCH', headers: { Authorization: `Bearer ${_tok()}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json()),
}

const fmt = (v: number) => '₹' + new Intl.NumberFormat('en-IN').format(v || 0)

// ── Types ────────────────────────────────────────────────────────────────────
interface QueueCase {
  case_ref_id: number
  applicant_ref: string
  applicant_name?: string
  product_code: string
  face_amount: number
  age: number
  gender: string
  outcome: string
  risk_class: string
  net_debit_points: number
  reason: string
  decision_date: string
  assignment_id?: number
  assigned_to?: string
  workbench_status: string
  priority: string
  sla_due_at?: string
  sla_breached: boolean
  final_outcome?: string
  note_count: number
  pending_requirements: number
}

const STATUS_COLOR: Record<string, string> = {
  OPEN: '#94a3b8', IN_PROGRESS: '#60a5fa', PENDING_REQUIREMENTS: '#fbbf24',
  READY_FOR_DECISION: '#00d4aa', APPROVED: '#22c55e', DECLINED: '#ef4444', CLOSED: '#6b7280',
}
const PRIORITY_COLOR: Record<string, string> = {
  LOW: '#6b7280', NORMAL: '#94a3b8', HIGH: '#fbbf24', URGENT: '#ef4444',
}
const REQ_TYPES = ['MEDICAL_TEST', 'APS', 'FINANCIAL_DOC', 'ID_PROOF', 'OTHER']
const REQ_LABELS: Record<string,string> = {
  MEDICAL_TEST: '🩺 Medical Test', APS: '📋 APS (Attending Physician Statement)',
  FINANCIAL_DOC: '💰 Financial Document', ID_PROOF: '🪪 ID Proof', OTHER: '📎 Other',
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function WorkbenchPage() {
  const [cases, setCases]       = useState<QueueCase[]>([])
  const [loading, setLoading]   = useState(true)
  const [underwriters, setUw]   = useState<{username:string; full_name?:string; role:string}[]>([])
  const [statusF, setStatusF]   = useState('ALL')
  const [assignedF, setAssignedF] = useState('ALL')
  const [priorityF, setPriorityF] = useState('ALL')
  const [selCase, setSelCase]   = useState<QueueCase | null>(null)
  const [sla, setSla] = useState<{ stats?: Record<string, number>; breached_cases?: any[] } | null>(null)
  const [slaOpen, setSlaOpen] = useState(false)

  const loadSla = () => {
    wbApi.get('/workbench/sla-dashboard')
      .then((d: any) => setSla(d ?? null))
      .catch(() => setSla(null))
  }
  useEffect(() => { loadSla() }, [])

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams({ status: statusF, assigned_to: assignedF, priority: priorityF })
    wbApi.get(`/workbench/queue?${params}`)
      .then(d => setCases(Array.isArray(d?.cases) ? d.cases : []))
      .catch(() => setCases([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [statusF, assignedF, priorityF])
  useEffect(() => {
    wbApi.get('/workbench/underwriters').then(d => setUw(Array.isArray(d) ? d : [])).catch(() => {})
  }, [])

  const columns = [
    {
      title: 'Priority', width: 90,
      render: (_:any, c:QueueCase) => (
        <Tag style={{ color: PRIORITY_COLOR[c.priority]||'#94a3b8', borderColor: (PRIORITY_COLOR[c.priority]||'#94a3b8')+'40',
          background:(PRIORITY_COLOR[c.priority]||'#94a3b8')+'15', fontSize:11 }}>
          {c.priority}
        </Tag>
      )
    },
    {
      title: Titled('Applicant', 'applicant_ref'), dataIndex: 'applicant_ref',
      render: (v:string, c:QueueCase) => (
        <div>
          <div style={{ fontWeight:600, color:'#e2e8f0', fontSize:13 }}>{c.applicant_name || v}</div>
          <div style={{ fontSize:11, color:'#6b7280', fontFamily:'var(--font-mono,monospace)' }}>{v}</div>
        </div>
      )
    },
    {
      title: 'Product / SA', width:170,
      render: (_:any, c:QueueCase) => (
        <div>
          <div style={{ fontSize:12, color:'#9ca3af' }}>{c.product_code}</div>
          <div style={{ fontSize:13, fontFamily:'var(--font-mono,monospace)', color:'#e2e8f0' }}>{fmt(c.face_amount)}</div>
        </div>
      )
    },
    {
      title: 'Age/Gender', width:90,
      render: (_:any,c:QueueCase) => <span style={{ fontSize:12, color:'#9ca3af' }}>{c.age} / {c.gender?.[0]}</span>
    },
    {
      title: Titled('NDP', 'net_debit_points'), dataIndex:'net_debit_points', width:60,
      render: (v:number) => <span style={{ fontFamily:'var(--font-mono,monospace)', fontSize:12, color:'#fbbf24' }}>{v}</span>
    },
    {
      title: 'Status', width:160,
      render: (_:any, c:QueueCase) => (
        <Tag style={{ color: STATUS_COLOR[c.workbench_status]||'#94a3b8', borderColor:(STATUS_COLOR[c.workbench_status]||'#94a3b8')+'40',
          background:(STATUS_COLOR[c.workbench_status]||'#94a3b8')+'15', fontSize:11 }}>
          {c.workbench_status?.replace(/_/g,' ')}
        </Tag>
      )
    },
    {
      title: Titled('Assigned To', 'assigned_to'), dataIndex:'assigned_to', width:140,
      render: (v:string) => v ? <span style={{ fontSize:12, color:'#9ca3af' }}>{v}</span> : <span style={{ color:'#4b5563', fontSize:12 }}>Unassigned</span>
    },
    {
      title: 'SLA', width:110,
      render: (_:any, c:QueueCase) => {
        if (!c.sla_due_at) return <span style={{ color:'#4b5563' }}>—</span>
        const due = new Date(c.sla_due_at)
        const hrs = Math.round((due.getTime() - Date.now())/3600000)
        if (c.sla_breached) return <Tag color="error" icon={<ExclamationCircleOutlined/>}>Breached</Tag>
        return <span style={{ fontSize:11, color: hrs<6 ? '#fbbf24':'#6b7280' }}><ClockCircleOutlined/> {hrs}h left</span>
      }
    },
    {
      title: '', width:90,
      render: (_:any, c:QueueCase) => (
        <div style={{ display:'flex', gap:6 }}>
          {c.note_count>0 && <Badge count={c.note_count} size="small" style={{ background:'#374151' }}><FileTextOutlined style={{ color:'#9ca3af' }}/></Badge>}
          {c.pending_requirements>0 && <Badge count={c.pending_requirements} size="small" style={{ background:'#fbbf24' }}><ExclamationCircleOutlined style={{ color:'#fbbf24' }}/></Badge>}
        </div>
      )
    },
  ]

  return (
    <div style={{ padding:'32px 36px' }}>
      <div style={{ marginBottom:24 }}>
        <h1 style={{ fontWeight:700, fontSize:22, color:'#e2e8f0', margin:0, letterSpacing:'-0.02em' }}>
          🗂️ Underwriter Workbench
        </h1>
        <p style={{ color:'#6b7280', fontSize:13, marginTop:4, marginBottom:0 }}>
          Cases referred by the rules engine for manual underwriting review.
        </p>
      </div>

      {/* ── SLA health strip ── */}
      {sla?.stats && (
        <div style={{ display:'flex', gap:12, marginBottom:16, flexWrap:'wrap' }}>
          <div style={{ flex:1, minWidth:150, padding:'14px 16px', borderRadius:10,
            background:'#111827', border:'1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize:11, color:'#6b7280', textTransform:'uppercase', letterSpacing:'0.06em' }}>SLA Breached</div>
            <div style={{ fontSize:24, fontWeight:700, color:'#ef4444' }}>{sla.stats.sla_breached}</div>
          </div>
          <div style={{ flex:1, minWidth:150, padding:'14px 16px', borderRadius:10,
            background:'#111827', border:'1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize:11, color:'#6b7280', textTransform:'uppercase', letterSpacing:'0.06em' }}>Within SLA</div>
            <div style={{ fontSize:24, fontWeight:700, color:'#22c55e' }}>{sla.stats.within_sla}</div>
          </div>
          <div style={{ flex:1, minWidth:150, padding:'14px 16px', borderRadius:10,
            background:'#111827', border:'1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize:11, color:'#6b7280', textTransform:'uppercase', letterSpacing:'0.06em' }}>Open Cases</div>
            <div style={{ fontSize:24, fontWeight:700, color:'#e2e8f0' }}>{sla.stats.open_cases}</div>
          </div>
          <div style={{ flex:1, minWidth:150, padding:'14px 16px', borderRadius:10,
            background:'#111827', border:'1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize:11, color:'#6b7280', textTransform:'uppercase', letterSpacing:'0.06em' }}>Avg TAT (hrs)</div>
            <div style={{ fontSize:24, fontWeight:700, color:'#e2e8f0' }}>{sla.stats.avg_tat_hours}</div>
          </div>
          {(sla.stats.sla_breached ?? 0) > 0 && (
            <button onClick={() => setSlaOpen(true)} style={{ padding:'14px 16px', borderRadius:10,
              background:'rgba(239,68,68,0.1)', border:'1px solid rgba(239,68,68,0.3)',
              color:'#ef4444', cursor:'pointer', fontWeight:600, fontSize:13 }}>
              View {sla.stats.sla_breached} breached
            </button>
          )}
        </div>
      )}

      <div style={{ display:'flex', gap:12, marginBottom:16 }}>
        <Select value={statusF} onChange={setStatusF} style={{ width:200 }} size="small">
          <Option value="ALL">All statuses</Option>
          {['OPEN','IN_PROGRESS','PENDING_REQUIREMENTS','READY_FOR_DECISION','APPROVED','DECLINED','CLOSED'].map(s =>
            <Option key={s} value={s}>{s.replace(/_/g,' ')}</Option>)}
        </Select>
        <Select value={assignedF} onChange={setAssignedF} style={{ width:200 }} size="small">
          <Option value="ALL">All assignees</Option>
          <Option value="UNASSIGNED">Unassigned</Option>
          {underwriters.map(u => <Option key={u.username} value={u.username}>{u.full_name || u.username}</Option>)}
        </Select>
        <Select value={priorityF} onChange={setPriorityF} style={{ width:160 }} size="small">
          <Option value="ALL">All priorities</Option>
          {['URGENT','HIGH','NORMAL','LOW'].map(p => <Option key={p} value={p}>{p}</Option>)}
        </Select>
        <Button size="small" onClick={load}>🔄 Refresh</Button>
      </div>

      {loading ? <div style={{ textAlign:'center', padding:60 }}><Spin/></div> : (
        <Table
          dataSource={cases}
          columns={columns}
          rowKey="case_ref_id"
          size="middle"
          pagination={{ pageSize: 20 }}
          onRow={(c) => ({ style:{ cursor:'pointer' }, onClick: () => setSelCase(c) })}
          locale={{ emptyText: <Empty description="No referred cases match these filters" /> }}
        />
      )}

      <CaseDrawer caseRow={selCase} underwriters={underwriters} onClose={() => setSelCase(null)} onChanged={load}/>

      {/* ── Breached SLA modal ── */}
      <Modal
        open={slaOpen} onCancel={() => setSlaOpen(false)} footer={null}
        title={`Breached SLA — ${sla?.stats?.sla_breached ?? 0} case(s)`} width={680}
      >
        {(!sla?.breached_cases || sla.breached_cases.length === 0) ? (
          <Empty description="No breached cases" />
        ) : (
          <Table
            dataSource={sla.breached_cases} rowKey="case_ref_id" size="small"
            pagination={false}
            columns={[
              { title: Titled('Case', 'case_ref_id'), dataIndex: 'case_ref_id', width: 60 },
              { title: Titled('Applicant', 'applicant_name'), dataIndex: 'applicant_name' },
              { title: Titled('Product', 'product_code'), dataIndex: 'product_code', width: 90 },
              { title: Titled('Assignee', 'assigned_to'), dataIndex: 'assigned_to', width: 110 },
              { title: Titled('Priority', 'priority'), dataIndex: 'priority', width: 90,
                render: (p: string) => <Tag style={{ color: PRIORITY_COLOR[p] || '#94a3b8' }}>{p}</Tag> },
              { title: Titled('Due', 'sla_due_at'), dataIndex: 'sla_due_at', width: 170,
                render: (d: string) => <span style={{ color:'#ef4444' }}>{d ? new Date(d).toLocaleString() : '—'}</span> },
            ]}
          />
        )}
      </Modal>
    </div>
  )
}

// ── Case Detail Drawer ──────────────────────────────────────────────────────
function CaseDrawer({ caseRow, underwriters, onClose, onChanged }:{
  caseRow: QueueCase | null; underwriters: {username:string; full_name?:string}[];
  onClose: () => void; onChanged: () => void
}) {
  const [detail, setDetail] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [noteText, setNoteText] = useState('')
  const [savingNote, setSavingNote] = useState(false)
  const [reqType, setReqType] = useState('MEDICAL_TEST')
  const [reqDesc, setReqDesc] = useState('')
  const [addingReq, setAddingReq] = useState(false)
  const [decForm] = Form.useForm()
  const [decSaving, setDecSaving] = useState(false)

  const load = () => {
    if (!caseRow) return
    setLoading(true)
    wbApi.get(`/workbench/cases/${caseRow.case_ref_id}`)
      .then(d => setDetail(d))
      .catch(() => message.error('Failed to load case'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { setDetail(null); load() }, [caseRow?.case_ref_id])

  if (!caseRow) return null
  const c = detail?.case || caseRow
  const a = detail?.assignment

  const refreshAll = () => { load(); onChanged() }

  const assign = (username: string) => {
    wbApi.post(`/workbench/cases/${caseRow.case_ref_id}/assign`, { assigned_to: username })
      .then(() => { message.success('Assigned'); refreshAll() })
      .catch(() => message.error('Assign failed'))
  }

  const setStatus = (workbench_status: string) => {
    wbApi.post(`/workbench/cases/${caseRow.case_ref_id}/status`, { workbench_status })
      .then(() => { message.success('Status updated'); refreshAll() })
      .catch(() => message.error('Update failed'))
  }

  const setPriority = (priority: string) => {
    wbApi.post(`/workbench/cases/${caseRow.case_ref_id}/status`, { priority })
      .then(() => { message.success('Priority updated'); refreshAll() })
      .catch(() => message.error('Update failed'))
  }

  const addNote = async () => {
    if (!noteText.trim()) return
    setSavingNote(true)
    try {
      await wbApi.post(`/workbench/cases/${caseRow.case_ref_id}/notes`, { note: noteText.trim() })
      setNoteText(''); refreshAll()
    } catch { message.error('Failed to add note') }
    finally { setSavingNote(false) }
  }

  const addRequirement = async () => {
    setAddingReq(true)
    try {
      await wbApi.post(`/workbench/cases/${caseRow.case_ref_id}/requirements`, { requirement_type: reqType, description: reqDesc })
      setReqDesc(''); refreshAll()
    } catch { message.error('Failed to add requirement') }
    finally { setAddingReq(false) }
  }

  const updateRequirement = async (rid: number, status: string) => {
    try {
      await wbApi.patch(`/workbench/requirements/${rid}`, { status, notes: '' })
      message.success(`Marked as ${status}`); refreshAll()
    } catch { message.error('Update failed') }
  }

  const submitDecision = async () => {
    const v = await decForm.validateFields()
    setDecSaving(true)
    try {
      const r = await wbApi.post(`/workbench/cases/${caseRow.case_ref_id}/decision`, v)
      if (r?.detail) throw new Error(r.detail)
      message.success(`Case ${v.final_outcome}`)
      decForm.resetFields()
      refreshAll()
    } catch(e:any) { message.error(e.message || 'Decision failed') }
    finally { setDecSaving(false) }
  }

  const card: React.CSSProperties = {
    background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.07)',
    borderRadius:10, padding:16, marginBottom:16,
  }
  const label: React.CSSProperties = { fontSize:11, color:'#6b7280', marginBottom:4, textTransform:'uppercase', letterSpacing:'0.06em' }

  return (
    <Drawer
      title={<span style={{ color:'#e2e8f0' }}>{c.applicant_name || c.applicant_ref} — {c.product_code}</span>}
      open={!!caseRow} onClose={onClose} width={620}
      styles={{ body:{ background:'var(--navy-900,#0a1628)' }, header:{ background:'var(--navy-900,#0a1628)', borderColor:'rgba(255,255,255,0.08)' } }}
    >
      {loading && !detail ? <div style={{ textAlign:'center', padding:40 }}><Spin/></div> : (
        <>
          {/* Summary */}
          <div style={card}>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12, marginBottom:12 }}>
              <div><div style={label}>Face Amount</div><div style={{ fontSize:15, fontWeight:700, color:'#e2e8f0' }}>{fmt(c.face_amount)}</div></div>
              <div><div style={label}>Age / Gender</div><div style={{ fontSize:15, color:'#e2e8f0' }}>{c.age} / {c.gender}</div></div>
              <div><div style={label}>Net Debit Pts</div><div style={{ fontSize:15, fontWeight:700, color:'#fbbf24' }}>{c.net_debit_points}</div></div>
            </div>
            <div style={{ marginBottom:12 }}>
              <div style={label}>Rules Engine Reason</div>
              <div style={{ fontSize:13, color:'#9ca3af', lineHeight:1.6 }}>{c.reason || '—'}</div>
            </div>

            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
              <div>
                <div style={label}>Assigned To</div>
                <Select value={a?.assigned_to || undefined} placeholder="Unassigned" style={{ width:'100%' }} size="small"
                  onChange={assign} suffixIcon={<UserAddOutlined/>}>
                  {underwriters.map(u => <Option key={u.username} value={u.username}>{u.full_name || u.username}</Option>)}
                </Select>
              </div>
              <div>
                <div style={label}>Priority</div>
                <Select value={a?.priority || 'NORMAL'} style={{ width:'100%' }} size="small" onChange={setPriority}>
                  {['LOW','NORMAL','HIGH','URGENT'].map(p => <Option key={p} value={p}>{p}</Option>)}
                </Select>
              </div>
            </div>
            <div style={{ marginTop:12 }}>
              <div style={label}>Workbench Status</div>
              <Select value={a?.workbench_status || 'OPEN'} style={{ width:'100%' }} size="small" onChange={setStatus}>
                {['OPEN','IN_PROGRESS','PENDING_REQUIREMENTS','READY_FOR_DECISION','APPROVED','DECLINED','CLOSED'].map(s =>
                  <Option key={s} value={s}>{s.replace(/_/g,' ')}</Option>)}
              </Select>
            </div>
          </div>

          {/* AI History */}
          {detail?.ai_history?.length > 0 && (
            <div style={card}>
              <div style={label}>AI Risk Assessment History</div>
              {detail.ai_history.map((h:any, i:number) => (
                <div key={i} style={{ fontSize:12, color:'#9ca3af', marginBottom:8, paddingBottom:8,
                  borderBottom: i<detail.ai_history.length-1 ? '1px solid rgba(255,255,255,0.05)':'none' }}>
                  <Tag style={{ fontSize:10 }}>{h.ai_engine}</Tag>
                  <span style={{ color:'#e2e8f0', fontWeight:600 }}> {h.ai_risk_tier}</span> · Score {h.ai_risk_score}/100 · {h.ai_decision}
                  {h.ai_narrative && <div style={{ marginTop:4 }}>{h.ai_narrative}</div>}
                </div>
              ))}
            </div>
          )}

          {/* Requirements */}
          <div style={card}>
            <div style={label}>Requirements / Pending Items</div>
            {detail?.requirements?.length > 0 ? detail.requirements.map((r:any) => (
              <div key={r.id} style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
                padding:'8px 0', borderBottom:'1px solid rgba(255,255,255,0.05)' }}>
                <div>
                  <div style={{ fontSize:12, color:'#e2e8f0' }}>{REQ_LABELS[r.requirement_type] || r.requirement_type}</div>
                  {r.description && <div style={{ fontSize:11, color:'#6b7280' }}>{r.description}</div>}
                </div>
                {r.status === 'REQUESTED' ? (
                  <div style={{ display:'flex', gap:6 }}>
                    <Button size="small" onClick={() => updateRequirement(r.id,'RECEIVED')} style={{ borderColor:'rgba(34,197,94,0.3)', color:'#22c55e', fontSize:11 }}>Received</Button>
                    <Button size="small" onClick={() => updateRequirement(r.id,'WAIVED')} style={{ fontSize:11 }}>Waive</Button>
                  </div>
                ) : (
                  <Tag color={r.status==='RECEIVED'?'success':'default'} style={{ fontSize:10 }}>{r.status}</Tag>
                )}
              </div>
            )) : <div style={{ fontSize:12, color:'#4b5563' }}>No requirements added yet.</div>}

            <div style={{ display:'flex', gap:8, marginTop:12 }}>
              <Select value={reqType} onChange={setReqType} size="small" style={{ width:180 }}>
                {REQ_TYPES.map(t => <Option key={t} value={t}>{REQ_LABELS[t]}</Option>)}
              </Select>
              <Input size="small" placeholder="Description (optional)" value={reqDesc} onChange={e=>setReqDesc(e.target.value)}/>
              <Button size="small" icon={<PlusOutlined/>} loading={addingReq} onClick={addRequirement}>Add</Button>
            </div>
          </div>

          {/* Notes timeline */}
          <div style={card}>
            <div style={label}>Notes</div>
            <div style={{ maxHeight:180, overflowY:'auto', marginBottom:10 }}>
              {detail?.notes?.length > 0 ? detail.notes.map((n:any) => (
                <div key={n.id} style={{ fontSize:12, color:'#9ca3af', marginBottom:8, paddingBottom:8,
                  borderBottom:'1px solid rgba(255,255,255,0.05)' }}>
                  <div style={{ display:'flex', justifyContent:'space-between' }}>
                    <strong style={{ color:'#e2e8f0', fontSize:11 }}>{n.author}</strong>
                    <span style={{ fontSize:10, color:'#4b5563' }}>{n.created_at?.slice(0,16).replace('T',' ')}</span>
                  </div>
                  <div style={{ marginTop:2, whiteSpace:'pre-wrap' }}>{n.note}</div>
                </div>
              )) : <div style={{ fontSize:12, color:'#4b5563' }}>No notes yet.</div>}
            </div>
            <div style={{ display:'flex', gap:8 }}>
              <TextArea rows={2} value={noteText} onChange={e=>setNoteText(e.target.value)} placeholder="Add a note for this case..."/>
              <Button icon={<SendOutlined/>} loading={savingNote} onClick={addNote}/>
            </div>
          </div>

          {/* Final decision */}
          <div style={{ ...card, border:'1px solid rgba(0,212,170,0.2)', background:'rgba(0,212,170,0.03)' }}>
            <div style={label}>Final Underwriting Decision</div>
            {a?.final_outcome && (
              <div style={{ fontSize:12, color:'#6b7280', marginBottom:10 }}>
                Current: <strong style={{ color: a.final_outcome.includes('APPROV')?'#22c55e':'#ef4444' }}>{a.final_outcome}</strong>
                {a.decided_by && <> by {a.decided_by} on {a.decided_at?.slice(0,16).replace('T',' ')}</>}
              </div>
            )}
            <Form form={decForm} layout="vertical">
              <Form.Item name="final_outcome" label="Decision" rules={[{required:true,message:'Required'}]}>
                <Select placeholder="Select final outcome">
                  <Option value="APPROVED">✅ Approved (Standard)</Option>
                  <Option value="APPROVED_RATED">✅ Approved (Rated / Loading applied)</Option>
                  <Option value="DECLINED">❌ Declined</Option>
                  <Option value="POSTPONED">⏸️ Postponed</Option>
                </Select>
              </Form.Item>
              <Form.Item name="final_reason" label="Reason / Justification" rules={[{required:true,message:'A reason is required'}]}>
                <TextArea rows={3} placeholder="Explain the underwriting decision — this becomes part of the audit trail"/>
              </Form.Item>
              <Popconfirm title="Record this decision? This will update the case outcome." onConfirm={submitDecision} okText="Confirm" cancelText="Cancel">
                <Button type="primary" icon={<CheckCircleOutlined/>} loading={decSaving} block>
                  Record Final Decision
                </Button>
              </Popconfirm>
            </Form>
          </div>
        </>
      )}
    </Drawer>
  )
}
