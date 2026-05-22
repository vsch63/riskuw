import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Select, Spin, Switch, InputNumber,
  message, Form, Input, Tabs, Popconfirm, Modal,
} from 'antd'
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined,
  SaveOutlined, DownloadOutlined, SendOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

const { Option } = Select
const { TextArea } = Input

// ── Types ──────────────────────────────────────────────────────────────────────
interface RICase {
  case_id: string; case_number: string; case_status: string
  applicant_ref: string; applicant_name: string
  face_amount: number; product_code: string; age: number; gender: string
  outcome: string; approved_premium: number; risk_class: string
  table_rating: number; flat_extra: number; net_debit_points: number
  cession_id?: string; cession_ref?: string; ri_status: string
  reinsurer_id?: string; reinsurer_name?: string
  ceded_amount: number; ri_premium: number; ri_decision: string
}
interface Reinsurer {
  id: string; code: string; name: string
  treaty_code: string; treaty_type: string
  email: string; retention_limit: number
  currency: string; is_active: boolean; notes: string
  product_codes: string[]; treaty_effective_date?: string; treaty_expiry_date?: string
}
interface Stats {
  total_flagged: number; pending_submission: number; submitted: number
  accepted: number; ri_declined: number
  total_exposure: number; total_ceded: number; total_ri_prem: number
}
interface Cession {
  cession_ref: string; case_number: string; reinsurer_name: string
  cession_type: string; status: string; ri_decision: string
  gross_face_amount: number; ceded_amount: number
  gross_premium: number; ri_premium: number; net_retained_premium: number
  submitted_at: string; ri_decision_date: string
  submitted_by: string; ri_reference: string
  cession_effective_date: string; cession_expiry_date: string
}

// ── Styles ─────────────────────────────────────────────────────────────────────
const card: React.CSSProperties = {
  background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.07)',
  borderRadius:10, padding:'20px 24px', marginBottom:16,
}
const secTitle: React.CSSProperties = {
  fontSize:11, fontWeight:600, color:'#6b7280',
  textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:12,
}

const RI_STATUS_COLOR: Record<string,string> = {
  NOT_SUBMITTED:'#ef4444', SLIP_GENERATED:'#f59e0b',
  SUBMITTED:'#3b82f6', DECISION_RECEIVED:'#22c55e', CLOSED:'#6b7280',
}
const RI_STATUS_ICON: Record<string,string> = {
  NOT_SUBMITTED:'🔴', SLIP_GENERATED:'🟡', SUBMITTED:'🔵',
  DECISION_RECEIVED:'🟢', CLOSED:'⚫',
}

const fmt = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits:0 })}`

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1 — RI Queue
// ══════════════════════════════════════════════════════════════════════════════
function RIQueueTab({ cases, reinsurers, onRefresh }: {
  cases: RICase[]; reinsurers: Reinsurer[]; onRefresh: () => void
}) {
  const [statusF, setStatusF]   = useState('All')
  const [outcomeF, setOutcomeF] = useState('All')
  const [expanded, setExpanded] = useState<string|null>(null)
  const [submitting, setSub]    = useState(false)
  const [decModal, setDecModal] = useState<RICase|null>(null)
  const [submitModal, setSubModal] = useState<RICase|null>(null)

  // Submit cession form state
  const [riSel, setRiSel]         = useState('')
  const [riType, setRiType]       = useState('FACULTATIVE')
  const [retention, setRetention] = useState(0)
  const [ceded, setCeded]         = useState(0)
  const [riPrem, setRiPrem]       = useState(0)
  const [cessEff, setCessEff]     = useState('')
  const [cessExp, setCessExp]     = useState('')
  const [notes, setNotes]         = useState('')

  // Decision form state
  const [decDecision, setDecDec]  = useState('ACCEPTED')
  const [decRef, setDecRef]       = useState('')
  const [decMod, setDecMod]       = useState('')
  const [decDate, setDecDate]     = useState(new Date().toISOString().slice(0,10))
  const [savingDec, setSavingDec] = useState(false)

  const filtered = cases.filter(c => {
    const mS = statusF === 'All' || c.ri_status === statusF
    const mO = outcomeF === 'All' || c.outcome.startsWith(outcomeF)
    return mS && mO
  })

  const openSubmit = (c: RICase) => {
    const ri = reinsurers[0]
    const ret = ri?.retention_limit || 0
    setRiSel(ri?.id || '')
    setRetention(ret)
    setCeded(Math.max(0, c.face_amount - ret))
    setRiPrem(0); setNotes('')
    setCessEff(new Date().toISOString().slice(0,10))
    setCessExp('')
    setSubModal(c)
  }

  const submitCession = async () => {
    if (!submitModal || !riSel) { message.warning('Select a reinsurer'); return }
    setSub(true)
    try {
      await api.post('/reinsurance/cessions', {
        case_id: submitModal.case_id,
        reinsurer_id: riSel, cession_type: riType,
        gross_face_amount: submitModal.face_amount,
        retention_amount: retention, ceded_amount: ceded,
        gross_premium: submitModal.approved_premium,
        ri_premium: riPrem, net_retained_premium: submitModal.approved_premium - riPrem,
        status: 'SUBMITTED',
        cession_effective_date: cessEff || null,
        cession_expiry_date: cessExp || null,
        notes: notes || null,
      })
      message.success('Cession submitted'); setSubModal(null); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Submit failed') }
    finally { setSub(false) }
  }

  const recordDecision = async () => {
    if (!decModal?.cession_id) return
    setSavingDec(true)
    try {
      await api.patch(`/reinsurance/cessions/${decModal.cession_id}`, {
        ri_decision: decDecision, ri_reference: decRef,
        ri_modified_terms: decMod || null,
        ri_decision_date: decDate,
        status: 'DECISION_RECEIVED',
      })
      message.success(`RI decision recorded: ${decDecision}`)
      setDecModal(null); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSavingDec(false) }
  }

  const markSubmitted = async (c: RICase) => {
    if (!c.cession_id) return
    try {
      await api.patch(`/reinsurance/cessions/${c.cession_id}`, { status: 'SUBMITTED' })
      message.success('Marked as submitted'); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Failed') }
  }

  return (
    <div>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        All cases flagged for reinsurance. Cases without a cession entry need to be submitted to your reinsurer.
      </div>

      <div style={{ display:'flex', gap:12, marginBottom:16 }}>
        <div style={{ flex:1 }}>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Filter by RI status</div>
          <Select value={statusF} onChange={setStatusF} style={{ width:'100%' }}>
            {['All','NOT_SUBMITTED','SLIP_GENERATED','SUBMITTED','DECISION_RECEIVED','CLOSED'].map(s =>
              <Option key={s} value={s}>{s === 'All' ? 'All' : `${RI_STATUS_ICON[s]||''} ${s}`}</Option>)}
          </Select>
        </div>
        <div style={{ flex:1 }}>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Filter by UW outcome</div>
          <Select value={outcomeF} onChange={setOutcomeF} style={{ width:'100%' }}>
            {['All','APPROVED','REFERRED','DECLINED','POSTPONED'].map(s => <Option key={s} value={s}>{s}</Option>)}
          </Select>
        </div>
        <Button icon={<ReloadOutlined/>} onClick={onRefresh} style={{ marginTop:20 }}/>
      </div>

      <div style={{ fontSize:12, color:'#6b7280', marginBottom:12 }}>{filtered.length} case(s)</div>

      {filtered.map(c => (
        <div key={c.case_id} style={{ ...card, cursor:'pointer' }} onClick={() => setExpanded(expanded===c.case_id?null:c.case_id)}>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <span style={{ fontSize:16 }}>{RI_STATUS_ICON[c.ri_status]||'⚪'}</span>
            <strong style={{ color:'#e2e8f0', fontFamily:'var(--font-mono,monospace)', fontSize:13 }}>{c.case_number}</strong>
            <span style={{ color:'#6b7280', fontSize:13 }}>— {fmt(c.face_amount)}</span>
            <Tag style={{ fontFamily:'var(--font-mono,monospace)', fontSize:11 }}>{c.product_code}</Tag>
            {c.outcome && <Tag color="blue" style={{ fontSize:11 }}>{c.outcome}</Tag>}
            {c.reinsurer_name && <span style={{ fontSize:12, color:'#6b7280' }}>{c.reinsurer_name}</span>}
            <Tag style={{ marginLeft:'auto', background:RI_STATUS_COLOR[c.ri_status]||'#6b7280', color:'#fff', border:'none', fontSize:11 }}>
              {c.ri_status}
            </Tag>
          </div>

          {expanded === c.case_id && (
            <div style={{ marginTop:16 }} onClick={e => e.stopPropagation()}>
              {/* Metrics */}
              <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12, marginBottom:16 }}>
                {[
                  { label:'Face Amount',    value:fmt(c.face_amount) },
                  { label:'Outcome',        value:c.outcome||'—' },
                  { label:'Risk Class',     value:c.risk_class||'—' },
                  { label:'Approved Prem',  value:c.approved_premium ? fmt(c.approved_premium) : '—' },
                ].map(f => (
                  <div key={f.label} style={{ background:'rgba(255,255,255,0.03)', borderRadius:8, padding:'10px 14px' }}>
                    <div style={{ fontSize:11, color:'#6b7280', marginBottom:2 }}>{f.label}</div>
                    <div style={{ fontSize:14, fontWeight:700, color:'#e2e8f0' }}>{f.value}</div>
                  </div>
                ))}
              </div>

              {/* Existing cession */}
              {c.cession_id ? (
                <div style={{ marginBottom:12 }}>
                  <div style={{ display:'flex', gap:12, marginBottom:12 }}>
                    <div style={{ ...card, flex:1, margin:0 }}>
                      <div style={{ fontSize:11, color:'#6b7280' }}>Cession ref</div>
                      <div style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa', fontSize:13 }}>{c.cession_ref}</div>
                    </div>
                    <div style={{ ...card, flex:1, margin:0 }}>
                      <div style={{ fontSize:11, color:'#6b7280' }}>RI Status</div>
                      <div style={{ fontSize:13, fontWeight:600, color:RI_STATUS_COLOR[c.ri_status] }}>{c.ri_status}</div>
                    </div>
                    <div style={{ ...card, flex:1, margin:0 }}>
                      <div style={{ fontSize:11, color:'#6b7280' }}>RI Decision</div>
                      <div style={{ fontSize:13, fontWeight:600, color: c.ri_decision === 'ACCEPTED' ? '#22c55e' : c.ri_decision === 'DECLINED' ? '#ef4444' : '#9ca3af' }}>
                        {c.ri_decision || 'Pending'}
                      </div>
                    </div>
                  </div>
                  {c.ceded_amount > 0 && (
                    <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:12 }}>
                      {[
                        { label:'Ceded Amount',   value:fmt(c.ceded_amount) },
                        { label:'RI Premium',     value:fmt(c.ri_premium) },
                        { label:'Net Retained',   value:c.approved_premium && c.ri_premium ? fmt(c.approved_premium - c.ri_premium) : '—' },
                      ].map(f => (
                        <div key={f.label} style={{ background:'rgba(255,255,255,0.03)', borderRadius:8, padding:'10px 14px' }}>
                          <div style={{ fontSize:11, color:'#6b7280', marginBottom:2 }}>{f.label}</div>
                          <div style={{ fontSize:13, fontWeight:700, color:'#e2e8f0' }}>{f.value}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  {c.ri_status === 'SLIP_GENERATED' && (
                    <Button type="primary" icon={<SendOutlined/>} onClick={() => markSubmitted(c)}>
                      📤 Mark as Submitted to Reinsurer
                    </Button>
                  )}
                  {c.ri_status === 'SUBMITTED' && (
                    <Button type="primary" icon={<SaveOutlined/>} onClick={() => { setDecModal(c); setDecDec('ACCEPTED'); setDecRef(''); setDecMod(''); setDecDate(new Date().toISOString().slice(0,10)) }}>
                      ✅ Record RI Decision
                    </Button>
                  )}
                </div>
              ) : (
                <div>
                  {reinsurers.length === 0 ? (
                    <div style={{ color:'#fbbf24', fontSize:13 }}>⚠ No reinsurers configured. Add one in the Reinsurer Registry tab.</div>
                  ) : (
                    <Button type="primary" icon={<SendOutlined/>} onClick={() => openSubmit(c)}>
                      📤 Submit Cession
                    </Button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ))}

      {filtered.length === 0 && (
        <div style={{ color:'#6b7280', fontSize:13, padding:'24px 0' }}>No cases match your filters.</div>
      )}

      {/* Submit Cession Modal */}
      <Modal title={<span style={{ color:'#e2e8f0' }}>Submit Cession — {submitModal?.case_number}</span>}
        open={!!submitModal} onCancel={() => setSubModal(null)} footer={null} width={600}
        styles={{ content:{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.09)' }, header:{ background:'#0d1521' } }}>
        {submitModal && (
          <div style={{ marginTop:16 }}>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Reinsurer *</div>
                <Select value={riSel} onChange={v => {
                  setRiSel(v)
                  const ri = reinsurers.find(r => r.id === v)
                  const ret = ri?.retention_limit || 0
                  setRetention(ret); setCeded(Math.max(0, submitModal.face_amount - ret))
                }} style={{ width:'100%' }}>
                  {reinsurers.map(r => <Option key={r.id} value={r.id}>{r.name}</Option>)}
                </Select>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Cession type</div>
                <Select value={riType} onChange={setRiType} style={{ width:'100%' }} placeholder="Select treaty type…">
                  <Option value="FACULTATIVE">FACULTATIVE</Option>
                  <Option value="TREATY">TREATY</Option>
                </Select>
              </div>
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12, marginBottom:12 }}>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Retention (₹)</div>
                <InputNumber value={retention} onChange={v => { setRetention(v||0); setCeded(Math.max(0, submitModal.face_amount - (v||0))) }} min={0} step={100000} style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Ceded Amount (₹)</div>
                <InputNumber value={ceded} onChange={v => setCeded(v||0)} min={0} step={100000} style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>RI Premium (₹)</div>
                <InputNumber value={riPrem} onChange={v => setRiPrem(v||0)} min={0} step={1000} style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
              </div>
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Cession Effective Date</div>
                <Input type="date" value={cessEff} onChange={e => setCessEff(e.target.value)}/>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Cession Expiry Date</div>
                <Input type="date" value={cessExp} onChange={e => setCessExp(e.target.value)}/>
              </div>
            </div>
            <div style={{ marginBottom:16 }}>
              <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Notes</div>
              <TextArea value={notes} onChange={e => setNotes(e.target.value)} rows={2} placeholder="e.g. Special terms agreed with reinsurer — rated up to Table 4"/>
            </div>
            <Button type="primary" icon={<SendOutlined/>} loading={submitting} onClick={submitCession} block>
              📤 Submit Cession
            </Button>
          </div>
        )}
      </Modal>

      {/* Record Decision Modal */}
      <Modal title={<span style={{ color:'#e2e8f0' }}>Record RI Decision — {decModal?.case_number}</span>}
        open={!!decModal} onCancel={() => setDecModal(null)} footer={null} width={520}
        styles={{ content:{ background:'#0d1521', border:'1px solid rgba(255,255,255,0.09)' }, header:{ background:'#0d1521' } }}>
        {decModal && (
          <div style={{ marginTop:16 }}>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>RI Decision *</div>
                <Select value={decDecision} onChange={setDecDec} style={{ width:'100%' }}>
                  <Option value="ACCEPTED">ACCEPTED</Option>
                  <Option value="DECLINED">DECLINED</Option>
                  <Option value="MODIFIED">MODIFIED</Option>
                </Select>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>RI Reference</div>
                <Input value={decRef} onChange={e => setDecRef(e.target.value)} placeholder="Reinsurer's own reference"/>
              </div>
            </div>
            <div style={{ marginBottom:12 }}>
              <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Modified terms (if applicable)</div>
              <TextArea value={decMod} onChange={e => setDecMod(e.target.value)} rows={2} placeholder="e.g. Accepted at Table 4 instead of Table 2 — flat extra waived"/>
            </div>
            <div style={{ marginBottom:16 }}>
              <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Decision date</div>
              <Input type="date" value={decDate} onChange={e => setDecDate(e.target.value)}/>
            </div>
            <Button type="primary" loading={savingDec} onClick={recordDecision} block>✅ Record Decision</Button>
          </div>
        )}
      </Modal>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2 — Generate RI Slip
// ══════════════════════════════════════════════════════════════════════════════
function GenerateSlipTab({ cases, reinsurers, onRefresh }: {
  cases: RICase[]; reinsurers: Reinsurer[]; onRefresh: () => void
}) {
  const [selCase, setSelCase]     = useState('')
  const [riSel, setRiSel]         = useState('')
  const [treaty, setTreaty]       = useState('')
  const [slipDate, setSlipDate]   = useState(new Date().toISOString().slice(0,10))
  const [retention, setRetention] = useState(0)
  const [ceded, setCeded]         = useState(0)
  const [riPrem, setRiPrem]       = useState(0)
  const [effDate, setEff]         = useState(new Date().toISOString().slice(0,10))
  const [expDate, setExp]         = useState('')
  const [slipNotes, setSlipNotes] = useState('')
  const [saving, setSaving]       = useState(false)

  const c = cases.find(x => x.case_id === selCase)
  const ri = reinsurers.find(x => x.id === riSel)

  useEffect(() => {
    if (ri) {
      setTreaty(ri.treaty_code || '')
      const ret = ri.retention_limit || 0
      setRetention(ret)
      if (c) setCeded(Math.max(0, c.face_amount - ret))
    }
  }, [riSel, ri, c?.case_id])

  useEffect(() => {
    if (!riSel && reinsurers.length > 0) setRiSel(reinsurers[0].id)
  }, [reinsurers])

  const slipHTML = c ? `
<div style="font-family:'Segoe UI',Arial,sans-serif;max-width:720px;border:1px solid #d1d5db;border-radius:8px;padding:32px;background:#fff;color:#111827;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #1d4ed8;padding-bottom:16px;margin-bottom:24px;">
    <div>
      <div style="font-size:20px;font-weight:700;color:#1d4ed8;">REINSURANCE CESSION SLIP</div>
      <div style="font-size:12px;color:#6b7280;margin-top:4px;">RiskUW — Underwriting Department</div>
    </div>
    <div style="text-align:right;font-size:12px;color:#6b7280;">
      <div><b>Slip date:</b> ${slipDate}</div>
      <div><b>Case ref:</b> ${c.case_number}</div>
      <div><b>Treaty:</b> ${treaty||'—'}</div>
      <div><b>Cover from:</b> ${effDate||'—'}</div>
      <div><b>Cover to:</b> ${expDate||'Per policy term'}</div>
    </div>
  </div>
  <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
    <tr style="background:#eff6ff;"><td colspan="4" style="padding:8px 12px;font-weight:700;color:#1d4ed8;font-size:13px;">RISK DETAILS</td></tr>
    <tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:8px 12px;font-size:12px;color:#6b7280;width:25%;">Applicant ref</td><td style="padding:8px 12px;font-size:13px;font-weight:600;">${c.applicant_ref}</td><td style="padding:8px 12px;font-size:12px;color:#6b7280;width:25%;">Applicant name</td><td style="padding:8px 12px;font-size:13px;">${c.applicant_name||'—'}</td></tr>
    <tr style="border-bottom:1px solid #e5e7eb;background:#f9fafb;"><td style="padding:8px 12px;font-size:12px;color:#6b7280;">Product</td><td style="padding:8px 12px;font-size:13px;font-weight:600;">${c.product_code}</td><td style="padding:8px 12px;font-size:12px;color:#6b7280;">Age / Gender</td><td style="padding:8px 12px;font-size:13px;">${c.age} / ${c.gender}</td></tr>
    <tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:8px 12px;font-size:12px;color:#6b7280;">UW decision</td><td style="padding:8px 12px;font-size:13px;font-weight:600;">${c.outcome}</td><td style="padding:8px 12px;font-size:12px;color:#6b7280;">Risk class</td><td style="padding:8px 12px;font-size:13px;">${c.risk_class}</td></tr>
    <tr style="border-bottom:1px solid #e5e7eb;background:#f9fafb;"><td style="padding:8px 12px;font-size:12px;color:#6b7280;">Table rating</td><td style="padding:8px 12px;font-size:13px;">${c.table_rating||'—'}</td><td style="padding:8px 12px;font-size:12px;color:#6b7280;">Flat extra</td><td style="padding:8px 12px;font-size:13px;">${c.flat_extra ? `₹${c.flat_extra.toFixed(2)}/K` : '—'}</td></tr>
    <tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:8px 12px;font-size:12px;color:#6b7280;">Net debit pts</td><td style="padding:8px 12px;font-size:13px;">${c.net_debit_points}</td><td></td><td></td></tr>
  </table>
  <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
    <tr style="background:#eff6ff;"><td colspan="4" style="padding:8px 12px;font-weight:700;color:#1d4ed8;font-size:13px;">FINANCIAL TERMS</td></tr>
    <tr style="border-bottom:1px solid #e5e7eb;background:#f9fafb;"><td style="padding:8px 12px;font-size:12px;color:#6b7280;width:25%;">Gross face amount</td><td style="padding:8px 12px;font-size:13px;font-weight:700;">₹${c.face_amount.toLocaleString()}</td><td style="padding:8px 12px;font-size:12px;color:#6b7280;width:25%;">Gross premium</td><td style="padding:8px 12px;font-size:13px;">₹${c.approved_premium.toLocaleString()}</td></tr>
    <tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:8px 12px;font-size:12px;color:#6b7280;">Retention</td><td style="padding:8px 12px;font-size:13px;font-weight:700;">₹${retention.toLocaleString()}</td><td style="padding:8px 12px;font-size:12px;color:#6b7280;">RI premium</td><td style="padding:8px 12px;font-size:13px;">₹${riPrem.toLocaleString()}</td></tr>
    <tr style="border-bottom:1px solid #e5e7eb;background:#f0fdf4;"><td style="padding:8px 12px;font-size:12px;color:#166534;font-weight:600;">Ceded to RI</td><td style="padding:8px 12px;font-size:14px;font-weight:700;color:#166534;">₹${ceded.toLocaleString()}</td><td style="padding:8px 12px;font-size:12px;color:#166534;font-weight:600;">Net retained premium</td><td style="padding:8px 12px;font-size:13px;font-weight:700;color:#166534;">₹${Math.max(0, c.approved_premium - riPrem).toLocaleString()}</td></tr>
  </table>
  ${slipNotes ? `<div style="background:#fef3c7;border:1px solid #d97706;border-radius:6px;padding:12px;margin-bottom:16px;font-size:12px;"><b>Special conditions:</b> ${slipNotes}</div>` : ''}
  <div style="border-top:1px solid #e5e7eb;padding-top:16px;font-size:11px;color:#9ca3af;">Generated by RiskUW UW Platform on ${slipDate} | This slip is subject to the terms of the applicable treaty/agreement.</div>
</div>` : ''

  const downloadSlip = async () => {
    if (!c) return
    setSaving(true)
    try {
      const blob = new Blob([slipHTML], { type:'text/html' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url; a.download = `ri_slip_${c.case_number}_${slipDate}.html`; a.click()
      URL.revokeObjectURL(url)
      // Mark slip as generated
      await api.post('/reinsurance/slips', {
        case_id: c.case_id, reinsurer_id: riSel, treaty,
        retention_amount: retention, ceded_amount: ceded,
        ri_premium: riPrem, cession_effective_date: effDate, cession_expiry_date: expDate||null,
      }).catch(() => {})
      message.success('Slip downloaded'); onRefresh()
    } catch(e:any) { message.error('Download failed') }
    finally { setSaving(false) }
  }

  return (
    <div>
      <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
        Generate a reinsurance slip for a case. Select a case from the RI Queue or search below.
      </div>

      <div style={card}>
        <div style={secTitle}>Select Case</div>
        <Select value={selCase||undefined} onChange={v => { setSelCase(v); const cs = cases.find(x => x.case_id===v); if (cs && ri) setCeded(Math.max(0, cs.face_amount - (ri.retention_limit||0))) }}
          style={{ width:'100%' }} placeholder="Select a case..." showSearch
          optionFilterProp="label"
          options={cases.map(c => ({ value:c.case_id, label:`${c.case_number} | ${fmt(c.face_amount)} | ${c.product_code} | ${c.outcome||'Pending'}` }))}/>
      </div>

      {c && (
        <>
          <div style={card}>
            <div style={secTitle}>RI Slip Details</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12, marginBottom:12 }}>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Reinsurer</div>
                <Select value={riSel} onChange={setRiSel} style={{ width:'100%' }}>
                  {reinsurers.map(r => <Option key={r.id} value={r.id}>{r.name}</Option>)}
                </Select>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Treaty / Reference</div>
                <Input value={treaty} onChange={e => setTreaty(e.target.value)} placeholder="e.g. FAC-2026-001"/>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Slip Date</div>
                <Input type="date" value={slipDate} onChange={e => setSlipDate(e.target.value)}/>
              </div>
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12, marginBottom:12 }}>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Retention (₹)</div>
                <InputNumber value={retention} onChange={v => { setRetention(v||0); setCeded(Math.max(0, c.face_amount-(v||0))) }} min={0} step={100000} style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Ceded Amount (₹)</div>
                <InputNumber value={ceded} onChange={v => setCeded(v||0)} min={0} step={100000} style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
              </div>
              <div>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>RI Premium (₹)</div>
                <InputNumber value={riPrem} onChange={v => setRiPrem(v||0)} min={0} step={1000} style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
              </div>
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
              <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Cession Effective Date <span style={{fontWeight:400,color:'#4b5563'}}>— date the risk transfer starts</span></div><Input type="date" value={effDate} onChange={e => setEff(e.target.value)}/></div>
              <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Cession Expiry Date <span style={{fontWeight:400,color:'#4b5563'}}>— blank = follows policy term</span></div><Input type="date" value={expDate} onChange={e => setExp(e.target.value)}/></div>
            </div>
            <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Additional notes / special conditions</div><TextArea value={slipNotes} onChange={e => setSlipNotes(e.target.value)} rows={2} placeholder="e.g. Special conditions or exclusions agreed with reinsurer"/></div>
          </div>

          {/* Slip Preview */}
          <div style={card}>
            <div style={secTitle}>Preview</div>
            <div dangerouslySetInnerHTML={{ __html: slipHTML }}/>
          </div>

          <Button type="primary" icon={<DownloadOutlined/>} loading={saving} onClick={downloadSlip} size="large">
            ⬇️ Download RI Slip (HTML)
          </Button>
        </>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3 — Reinsurer Registry
// ══════════════════════════════════════════════════════════════════════════════
function ReinsurerRegistryTab({ reinsurers, onRefresh }: { reinsurers: Reinsurer[]; onRefresh: () => void }) {
  const [addForm] = Form.useForm()
  const [adding, setAdding]   = useState(false)
  const [saving, setSaving]   = useState<string|null>(null)
  const [editForms, setEditForms] = useState<Record<string,any>>({})

  const TREATY_TYPES = ['FACULTATIVE','TREATY','QUOTA_SHARE','SURPLUS']
  const CURRENCIES   = ['INR','USD','GBP','EUR','SGD']

  const saveReinsurer = async (id: string, data: any) => {
    setSaving(id)
    try {
      const pcs = data.product_codes ? data.product_codes.split(',').map((x:string)=>x.trim().toUpperCase()).filter(Boolean) : []
      await api.put(`/reinsurance/reinsurers/${id}`, { ...data, product_codes: pcs })
      message.success('Reinsurer updated'); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSaving(null) }
  }

  const addReinsurer = async () => {
    const v = addForm.getFieldsValue()
    if (!v.name?.trim() || !v.code?.trim()) { message.error('Name and Code are required'); return }
    setAdding(true)
    try {
      await api.post('/reinsurance/reinsurers', {
        reinsurer_name: v.name.trim(), reinsurer_code: v.code.trim().toUpperCase(),
        treaty_code: v.treaty_code||null, treaty_type: v.treaty_type||'FACULTATIVE',
        contact_email: v.email||null, retention_limit: v.retention_limit||null,
        currency: v.currency||'INR', is_active: true,
        notes: v.notes||null,
        treaty_effective_date: v.eff_date||null, treaty_expiry_date: v.exp_date||null,
      })
      message.success(`${v.name} added`); addForm.resetFields(); onRefresh()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Add failed') }
    finally { setAdding(false) }
  }

  const subTabs = [
    {
      key: 'list',
      label: '📋 All Reinsurers',
      children: reinsurers.length === 0 ? (
        <div style={{ color:'#6b7280', fontSize:13 }}>No reinsurers configured yet. Add your first in the Add Reinsurer tab.</div>
      ) : (
        <div>
          {reinsurers.map(ri => {
            const today = new Date().toISOString().slice(0,10)
            const expired  = ri.treaty_expiry_date   && ri.treaty_expiry_date   < today
            const notYet   = ri.treaty_effective_date && ri.treaty_effective_date > today
            const icon = ri.is_active && !expired && !notYet ? '🟢' : expired || notYet ? '⚠️' : '⚫'
            const ef = editForms[ri.id] || {}
            return (
              <div key={ri.id} style={{ ...card, marginBottom:12 }}>
                <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12, cursor:'pointer' }}
                  onClick={() => setEditForms(f => ({ ...f, [ri.id]: f[ri.id] ? null : {
                    name: ri.name, code: ri.code, treaty_code: ri.treaty_code,
                    treaty_type: ri.treaty_type, email: ri.email,
                    retention_limit: ri.retention_limit, currency: ri.currency,
                    is_active: ri.is_active, notes: ri.notes,
                    product_codes: ri.product_codes?.join(', ') || '',
                    eff_date: ri.treaty_effective_date||'', exp_date: ri.treaty_expiry_date||'',
                  } }))}>
                  <span style={{ fontSize:16 }}>{icon}</span>
                  <strong style={{ color:'#e2e8f0', fontSize:14 }}>{ri.name}</strong>
                  <Tag style={{ fontFamily:'var(--font-mono,monospace)', fontSize:11 }}>{ri.code}</Tag>
                  <Tag style={{ fontSize:11 }}>{ri.treaty_type}</Tag>
                  {ri.retention_limit && <span style={{ fontSize:12, color:'#6b7280' }}>Retention: {fmt(ri.retention_limit)}</span>}
                  {expired && <Tag color="error">Expired</Tag>}
                </div>
                {ef && (
                  <div>
                    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Reinsurer Name *</div><Input value={ef.name||''} onChange={e => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], name:e.target.value } }))}/></div>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Code *</div><Input value={ef.code||''} onChange={e => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], code:e.target.value } }))} style={{ fontFamily:'var(--font-mono,monospace)' }}/></div>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Treaty Code</div><Input value={ef.treaty_code||''} onChange={e => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], treaty_code:e.target.value } }))}/></div>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Treaty Type</div><Select value={ef.treaty_type||'FACULTATIVE'} onChange={v => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], treaty_type:v } }))} style={{ width:'100%' }}>{TREATY_TYPES.map(t=><Option key={t} value={t}>{t}</Option>)}</Select></div>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Contact Email</div><Input value={ef.email||''} onChange={e => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], email:e.target.value } }))}/></div>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Retention Limit (₹)</div><InputNumber value={ef.retention_limit||0} onChange={v => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], retention_limit:v } }))} min={0} step={500000} style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/></div>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Currency</div><Select value={ef.currency||'INR'} onChange={v => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], currency:v } }))} style={{ width:'100%' }}>{CURRENCIES.map(c=><Option key={c} value={c}>{c}</Option>)}</Select></div>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Treaty Effective Date</div><Input type="date" value={ef.eff_date||''} onChange={e => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], eff_date:e.target.value } }))}/></div>
                      <div><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Treaty Expiry Date</div><Input type="date" value={ef.exp_date||''} onChange={e => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], exp_date:e.target.value } }))}/></div>
                    </div>
                    <div style={{ marginBottom:12 }}><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Product Codes (comma-separated)</div><Input value={ef.product_codes||''} onChange={e => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], product_codes:e.target.value } }))} placeholder="e.g. IND-TERM-20, IND-TERM-30"/></div>
                    <div style={{ marginBottom:12 }}><div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Notes</div><TextArea value={ef.notes||''} onChange={e => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], notes:e.target.value } }))} rows={2}/></div>
                    <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:12 }}>
                      <Switch checked={ef.is_active} onChange={v => setEditForms(f => ({ ...f, [ri.id]:{ ...f[ri.id], is_active:v } }))}/>
                      <span style={{ fontSize:13, color:'#9ca3af' }}>Active</span>
                    </div>
                    <Button type="primary" icon={<SaveOutlined/>} loading={saving===ri.id} onClick={() => saveReinsurer(ri.id, ef)}>Save Changes</Button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ),
    },
    {
      key: 'add',
      label: '➕ Add Reinsurer',
      children: (
        <div style={{ maxWidth:700 }}>
          <Form form={addForm} layout="vertical" requiredMark={false}>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
              <Form.Item name="name" label="Reinsurer Name *" rules={[{required:true}]}><Input placeholder="e.g. Munich Re India"/></Form.Item>
              <Form.Item name="code" label="Code *" rules={[{required:true}]}><Input placeholder="e.g. MUNICH-RE" style={{ fontFamily:'var(--font-mono,monospace)', textTransform:'uppercase' }}/></Form.Item>
              <Form.Item name="treaty_code" label="Treaty Code"><Input placeholder="e.g. FAC-2026-001"/></Form.Item>
              <Form.Item name="treaty_type" label="Treaty Type" initialValue="FACULTATIVE">
                <Select>{TREATY_TYPES.map(t=><Option key={t} value={t}>{t}</Option>)}</Select>
              </Form.Item>
              <Form.Item name="email" label="Contact Email"><Input placeholder="ri@munichre.com"/></Form.Item>
              <Form.Item name="retention_limit" label="Retention Limit (₹)" help="Maximum face amount the carrier retains before ceding the balance to this reinsurer">
                <InputNumber min={0} step={500000} style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/>
              </Form.Item>
              <Form.Item name="currency" label="Currency" initialValue="INR">
                <Select>{CURRENCIES.map(c=><Option key={c} value={c}>{c}</Option>)}</Select>
              </Form.Item>
              <Form.Item name="eff_date" label="Treaty Effective Date"><Input type="date"/></Form.Item>
              <Form.Item name="exp_date" label="Treaty Expiry Date"><Input type="date"/></Form.Item>
            </div>
            <Form.Item name="notes" label="Notes" help="Internal notes about this reinsurer — treaty scope, special conditions, contacts"><TextArea rows={2} placeholder="e.g. Covers all substandard lives up to Table 8; excludes HIV and aviation"/></Form.Item>
            <Button type="primary" icon={<PlusOutlined/>} loading={adding} onClick={addReinsurer} block>➕ Add Reinsurer</Button>
          </Form>
        </div>
      ),
    },
  ]

  return <Tabs items={subTabs} tabBarStyle={{ borderBottom:'1px solid rgba(255,255,255,0.07)', marginBottom:16 }}/>
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4 — Cession History
// ══════════════════════════════════════════════════════════════════════════════
function CessionHistoryTab() {
  const [history, setHistory] = useState<Cession[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch]   = useState('')

  useEffect(() => {
    api.get('/reinsurance/cessions')
      .then(r => setHistory(Array.isArray(r.data) ? r.data : []))
      .catch(() => setHistory([]))
      .finally(() => setLoading(false))
  }, [])

  const filtered = history.filter(h => {
    const q = search.toLowerCase()
    return !q || (h.cession_ref||'').toLowerCase().includes(q) || (h.case_number||'').toLowerCase().includes(q) || (h.reinsurer_name||'').toLowerCase().includes(q)
  })

  const exportCSV = () => {
    const cols = ['Cession ref','Case','Reinsurer','Type','Status','RI Decision','Gross face','Ceded','RI prem','Submitted at','Decision date']
    const rows = filtered.map(h => [h.cession_ref, h.case_number, h.reinsurer_name, h.cession_type, h.status, h.ri_decision, h.gross_face_amount, h.ceded_amount, h.ri_premium, h.submitted_at?.slice(0,16), h.ri_decision_date?.slice(0,10)])
    const csv  = [cols, ...rows].map(r => r.join(',')).join('\n')
    const url  = URL.createObjectURL(new Blob([csv], { type:'text/csv' }))
    const a    = document.createElement('a'); a.href=url; a.download=`ri_cessions_${new Date().toISOString().slice(0,10)}.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  const cols = [
    { title:'Cession ref', dataIndex:'cession_ref', width:160, render:(v:string) => <span style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa', fontSize:12 }}>{v||'—'}</span> },
    { title:'Case', dataIndex:'case_number', width:160 },
    { title:'Reinsurer', dataIndex:'reinsurer_name' },
    { title:'Type', dataIndex:'cession_type', width:110 },
    { title:'Status', dataIndex:'status', width:160, render:(v:string) => <Tag style={{ background:RI_STATUS_COLOR[v]||'#6b7280', color:'#fff', border:'none', fontSize:11 }}>{v}</Tag> },
    { title:'RI Decision', dataIndex:'ri_decision', width:120, render:(v:string) => v ? <Tag color={v==='ACCEPTED'?'success':v==='DECLINED'?'error':'warning'}>{v}</Tag> : <span style={{ color:'#6b7280' }}>—</span> },
    { title:'Gross face', dataIndex:'gross_face_amount', width:130, render:(v:number) => v ? fmt(v) : '—' },
    { title:'Ceded', dataIndex:'ceded_amount', width:120, render:(v:number) => v ? fmt(v) : '—' },
    { title:'RI prem', dataIndex:'ri_premium', width:110, render:(v:number) => v ? fmt(v) : '—' },
    { title:'Submitted', dataIndex:'submitted_at', width:130, render:(v:string) => v?.slice(0,16)||'—' },
    { title:'Decision date', dataIndex:'ri_decision_date', width:120, render:(v:string) => v?.slice(0,10)||'—' },
  ]

  return (
    <div>
      <div style={{ display:'flex', gap:10, marginBottom:16, alignItems:'center' }}>
        <Input placeholder="Search cession ref, case, reinsurer…" value={search} onChange={e => setSearch(e.target.value)} style={{ maxWidth:320 }} allowClear/>
        <Button icon={<DownloadOutlined/>} onClick={exportCSV} style={{ marginLeft:'auto' }}>Export CSV</Button>
        <Button icon={<ReloadOutlined/>} onClick={() => { setLoading(true); api.get('/reinsurance/cessions').then(r => setHistory(Array.isArray(r.data)?r.data:[])).finally(()=>setLoading(false)) }}/>
      </div>
      {loading ? <Spin/> : (
        <Table dataSource={filtered} columns={cols} rowKey="cession_ref" size="small"
          pagination={{ pageSize:20, showSizeChanger:false }} scroll={{ x:1400 }}
          locale={{ emptyText:'No cessions recorded yet.' }}/>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE SHELL
// ══════════════════════════════════════════════════════════════════════════════
export default function ReinsurancePage() {
  const [cases, setCases]         = useState<RICase[]>([])
  const [reinsurers, setReinsurers] = useState<Reinsurer[]>([])
  const [stats, setStats]         = useState<Stats|null>(null)
  const [loading, setLoading]     = useState(true)
  const [activeTab, setTab]       = useState('queue')

  const load = async () => {
    setLoading(true)
    try {
      const [cR, rR, sR] = await Promise.all([
        api.get('/reinsurance/cases').catch(() => ({ data: [] })),
        api.get('/reinsurance/reinsurers').catch(() => ({ data: [] })),
        api.get('/reinsurance/stats').catch(() => api.get('/reinsurance/summary').catch(() => ({ data: null }))),
      ])
      setCases(Array.isArray(cR.data) ? cR.data : [])
      setReinsurers(Array.isArray(rR.data) ? rR.data : [])
      if (sR.data) setStats(sR.data)
    } catch(e:any) { message.error('Failed to load reinsurance data') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const tabs = [
    { key:'queue',      label:'📋 RI Queue',          children: <RIQueueTab cases={cases} reinsurers={reinsurers} onRefresh={load}/> },
    { key:'slip',       label:'📄 Generate RI Slip',   children: <GenerateSlipTab cases={cases} reinsurers={reinsurers} onRefresh={load}/> },
    { key:'registry',   label:'🏢 Reinsurer Registry', children: <ReinsurerRegistryTab reinsurers={reinsurers} onRefresh={load}/> },
    { key:'history',    label:'📊 Cession History',    children: <CessionHistoryTab/> },
  ]

  return (
    <div style={{ padding:'32px 36px' }}>
      <div style={{ marginBottom:20, display:'flex', alignItems:'flex-start', justifyContent:'space-between' }}>
        <div>
          <h1 style={{ fontWeight:700, fontSize:20, color:'#e2e8f0', margin:0, letterSpacing:'-0.02em' }}>
            🏦 Reinsurance
          </h1>
          <p style={{ color:'#6b7280', fontSize:13, marginTop:4, marginBottom:0 }}>
            Manage reinsurance cessions — generate RI slips, track submissions, record RI decisions, and calculate premium splits.
          </p>
        </div>
        <Button icon={<ReloadOutlined/>} onClick={load} loading={loading}>Refresh</Button>
      </div>

      {/* Stats */}
      {stats && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(8,1fr)', gap:10, marginBottom:24 }}>
          {[
            { label:'Total RI cases',     value:stats.total_flagged,    color:'#00d4aa' },
            { label:'Pending submission', value:stats.pending_submission, color:'#ef4444' },
            { label:'Submitted',          value:stats.submitted,        color:'#3b82f6' },
            { label:'RI accepted',        value:stats.accepted,         color:'#22c55e' },
            { label:'RI declined',        value:stats.ri_declined,      color:'#f87171' },
            { label:'Total exposure',     value:fmt(stats.total_exposure), color:'#9ca3af' },
            { label:'Total ceded',        value:fmt(stats.total_ceded),  color:'#c084fc' },
            { label:'RI premium out',     value:fmt(stats.total_ri_prem), color:'#fbbf24' },
          ].map(s => (
            <div key={s.label} style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:8, padding:'10px 12px' }}>
              <div style={{ fontSize:15, fontWeight:700, color:s.color }}>{s.value}</div>
              <div style={{ fontSize:10, color:'#6b7280', marginTop:2, lineHeight:1.3 }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {loading && !stats ? (
        <div style={{ display:'flex', justifyContent:'center', padding:60 }}><Spin size="large"/></div>
      ) : (
        <Tabs activeKey={activeTab} onChange={setTab} items={tabs}
          tabBarStyle={{ borderBottom:'1px solid rgba(255,255,255,0.07)', marginBottom:24 }}/>
      )}
    </div>
  )
}
