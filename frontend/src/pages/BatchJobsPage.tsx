import { useEffect, useRef, useState } from 'react'
import {
  Button, Input, Select, Switch, InputNumber, Spin,
  message, Tag, Table, Tabs, Upload, Checkbox, Progress,
  Collapse,
} from 'antd'
import {
  UploadOutlined, ReloadOutlined, DownloadOutlined,
  ClockCircleOutlined, BarChartOutlined, CalendarOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

const { Option } = Select
const { Dragger } = Upload
const { Panel } = Collapse

// ── Styles ─────────────────────────────────────────────────────────────────────
const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 10, padding: '20px 24px', marginBottom: 16,
}
const secTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#6b7280',
  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 12,
}

// ── Types ──────────────────────────────────────────────────────────────────────
interface BatchJob {
  id: string; job_number: string; job_name: string; status: string
  total_records: number; approved: number; declined: number
  referred: number; errored: number; processed: number
  dry_run: boolean; submitted_at: string; completed_at: string
  submitted_by: string; input_filename: string; error_message: string
}

const STATUS_COLOR: Record<string,string> = {
  COMPLETED:'#22c55e', PROCESSING:'#f59e0b', QUEUED:'#3b82f6',
  PENDING:'#3b82f6', FAILED:'#ef4444', CANCELLED:'#6b7280',
}
const STATUS_ICON: Record<string,string> = {
  COMPLETED:'🟢', PROCESSING:'🟡', QUEUED:'⏳',
  PENDING:'⏳', FAILED:'🔴', CANCELLED:'⚫',
}

// ── CSV Template ───────────────────────────────────────────────────────────────
const CSV_TEMPLATE = `applicant_ref,product_code,age,gender,state,face_amount,coverage_term_yrs,tobacco_status,tobacco_quit_years,height_inches,weight_lbs,systolic_bp,diastolic_bp,heart_condition,heart_event_years_ago,diabetes_type,diabetes_dx_age,a1c,cancer_status,cancer_free_years,depression_history,depression_hospitalized,kidney_disease,copd,stroke_history,alcohol_drinks_week,hazardous_activity,occupation_class,occupation_title,annual_income,existing_coverage
SAMPLE-001,IND-TERM-20,40,MALE,CA,500000,20,NON_TOBACCO,,70,175,120,78,NONE,,NONE,,,NONE,,false,false,false,false,false,4,false,1,Software Engineer,100000,0
SAMPLE-002,IND-TERM-20,52,FEMALE,TX,250000,10,NON_TOBACCO,,65,155,138,88,HYPERTENSION,,TYPE2,45,7.8,NONE,,false,false,false,false,false,6,false,2,Manager,80000,200000
`

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1 — Upload Batch
// ══════════════════════════════════════════════════════════════════════════════
function UploadTab({ onSubmitted }: { onSubmitted: (jobId: string) => void }) {
  const [file, setFile]             = useState<File|null>(null)
  const [jobName, setJobName]       = useState('')
  const [effDate, setEff]           = useState(new Date().toISOString().slice(0,10))
  const [expDate, setExp]           = useState('')
  const [dryRun, setDryRun]         = useState(false)
  const [skipProdErr, setSkipProd]  = useState(false)
  const [autoAssign, setAutoAssign] = useState(true)
  const [slaHours, setSla]          = useState(48)
  const [routeMed, setRouteMed]     = useState(true)
  const [aiScore, setAiScore]       = useState(false)
  const [aiEngine, setAiEngine]     = useState('xgboost')
  const [sendEmail, setSendEmail]   = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [valErrors, setValErrors]   = useState<string[]>([])
  const [valWarnings, setValWarn]   = useState<string[]>([])

  // Diagnose form
  const [diagProd, setDiagProd]   = useState('IND-TERM-20')
  const [diagAge, setDiagAge]     = useState(30)
  const [diagGender, setDiagGen]  = useState('MALE')
  const [diagState, setDiagSt]    = useState('MH')
  const [diagFace, setDiagFace]   = useState(500000)
  const [diagTob, setDiagTob]     = useState('NON_TOBACCO')
  const [diagResult, setDiagRes]  = useState<any>(null)
  const [diagging, setDiagRun]    = useState(false)

  const [products, setProducts] = useState<any[]>([])
  useEffect(() => {
    api.get('/products').then(r => setProducts(Array.isArray(r.data) ? r.data : [])).catch(() => {})
  }, [])

  const downloadTemplate = () => {
    const blob = new Blob([CSV_TEMPLATE], { type:'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a'); a.href=url; a.download='batch_template.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  const validateAndSubmit = async () => {
    const errors: string[] = []
    const warnings: string[] = []
    setValErrors([]); setValWarn([])

    if (!file) { setValErrors(['Please select a file to upload.']); return }

    // Basic client-side validation
    const text = await file.text()
    const lines = text.split('\n').filter(l => l.trim())
    if (lines.length < 2) { setValErrors(['File appears empty — no data rows found.']); return }
    const headers = lines[0].toLowerCase().split(',').map(h => h.trim())
    if (!headers.includes('product_code')) {
      if (headers.includes('product_type')) {
        errors.push('[PROD_TYPE_INVALID] Your file has `product_type` but not `product_code`. Replace `product_type` with `product_code` (e.g. IND-TERM-20). Download the template.')
      } else {
        errors.push(`[PROD_NOT_FOUND] Missing \`product_code\` column. Columns found: ${headers.join(', ')}. Download the template.`)
      }
    }

    if (errors.length && !skipProdErr) {
      setValErrors(errors); return
    }
    if (errors.length && skipProdErr) {
      warnings.push(...errors)
      setValWarn(warnings)
    }

    // Submit
    setSubmitting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const params = new URLSearchParams({
        job_name: jobName || 'Batch Job',
        dry_run: String(dryRun),
        skip_product_errors: String(skipProdErr),
        ...(effDate && { policy_effective_date: effDate }),
        ...(expDate && { policy_expire_date: expDate }),
      })
      const r = await api.post(`/batch/upload?${params}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const d = r.data
      message.success(`✅ Job queued: ${d.job_number}`)
      onSubmitted(d.job_id || d.id || '')
      setFile(null); setJobName('')
    } catch(e:any) {
      message.error(e?.response?.data?.detail || 'Upload failed')
    }
    finally { setSubmitting(false) }
  }

  const runDiagnose = async () => {
    setDiagRun(true); setDiagRes(null)
    try {
      const r = await api.post('/underwriting/evaluate', {
        applicant_ref: 'DIAG-001', product_code: diagProd.trim().toUpperCase(),
        age: diagAge, gender: diagGender, state: diagState.trim().toUpperCase(),
        face_amount: diagFace, tobacco_status: diagTob,
        coverage_term_yrs: 20, height_inches: 68, weight_lbs: 170,
        systolic_bp: 120, diastolic_bp: 80, diabetes_type: 'NONE',
        hazardous_activity: false, annual_income: 100000, existing_coverage: 0,
      })
      setDiagRes(r.data)
    } catch(e:any) {
      setDiagRes({ error: e?.response?.data?.detail || e.message })
    }
    finally { setDiagRun(false) }
  }

  return (
    <div style={{ display:'grid', gridTemplateColumns:'2fr 1fr', gap:24 }}>
      {/* Left — Upload Form */}
      <div>
        <div style={card}>
          <div style={secTitle}>Upload Batch File</div>

          <div style={{ marginBottom:16 }}>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Job Name</div>
            <Input value={jobName} onChange={e => setJobName(e.target.value)}
              placeholder="e.g. March 2026 New Business"/>
            <div style={{ fontSize:11, color:'#6b7280', marginTop:4 }}>
              Optional label to identify this batch run in the Job Monitor.
            </div>
          </div>

          <div style={{ marginBottom:16 }}>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>
              Select CSV or Excel file
              <span style={{ color:'#4b5563', marginLeft:8 }}>Limit 200MB • CSV, XLSX, XLS</span>
            </div>
            <Dragger accept=".csv,.xlsx,.xls" maxCount={1} beforeUpload={f => { setFile(f); return false }}
              onRemove={() => setFile(null)}
              style={{ background:'rgba(255,255,255,0.02)', border:'1px dashed rgba(255,255,255,0.15)' }}>
              <p style={{ color:'#6b7280', margin:0 }}>
                <UploadOutlined style={{ fontSize:20, marginRight:8 }}/>
                Drag and drop file here or click to browse
              </p>
              {file && <p style={{ color:'#00d4aa', marginTop:8, marginBottom:0 }}>✅ {file.name}</p>}
            </Dragger>
          </div>

          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:16 }}>
            <div>
              <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Policy Effective Date</div>
              <Input type="date" value={effDate} onChange={e => setEff(e.target.value)}/>
              <div style={{ fontSize:11, color:'#6b7280', marginTop:4 }}>
                Start date applied to all policies in this batch.
              </div>
            </div>
            <div>
              <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Policy Expire Date</div>
              <Input type="date" value={expDate} onChange={e => setExp(e.target.value)}/>
              <div style={{ fontSize:11, color:'#6b7280', marginTop:4 }}>
                End date for all policies. Leave blank if not applicable.
              </div>
            </div>
          </div>

          <div style={{ display:'flex', flexDirection:'column', gap:10, marginBottom:16 }}>
            <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer' }}>
              <Checkbox checked={dryRun} onChange={e => setDryRun(e.target.checked)}/>
              Dry Run (validate only, no UW decisions)
            </label>
            <div style={{ fontSize:11, color:'#6b7280', paddingLeft:24, marginTop:-6 }}>
              Validates all rows and reports errors without creating any cases or decisions.
            </div>
            <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#fbbf24', cursor:'pointer' }}>
              <Checkbox checked={skipProdErr} onChange={e => setSkipProd(e.target.checked)}/>
              ⚠️ Skip product errors — process valid rows anyway
            </label>
            <div style={{ fontSize:11, color:'#6b7280', paddingLeft:24, marginTop:-6 }}>
              Rows with invalid product codes are skipped; all other valid rows are processed.
            </div>
          </div>

          <div style={{ borderTop:'1px solid rgba(255,255,255,0.07)', paddingTop:16, marginBottom:16 }}>
            <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer', marginBottom:4 }}>
              <Checkbox checked={autoAssign} onChange={e => setAutoAssign(e.target.checked)}/>
              🎯 Auto-assign referred cases to eligible underwriters
            </label>
            <div style={{ fontSize:11, color:'#6b7280', paddingLeft:24, marginBottom:10 }}>
              REFERRED decisions are automatically assigned to available underwriters based on their authority limits.
            </div>
            {autoAssign && (
              <div style={{ paddingLeft:24 }}>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>SLA hours for auto-assigned cases</div>
                <InputNumber value={slaHours} onChange={v => setSla(v||48)} min={1} max={240} step={8} style={{ width:150 }}/>
                <div style={{ fontSize:11, color:'#6b7280', marginTop:4 }}>
                  Cases not actioned within this time will be escalated. Default: 48 hours.
                </div>
                <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer', marginTop:10 }}>
                  <Checkbox checked={routeMed} onChange={e => setRouteMed(e.target.checked)}/>
                  🩺 Route medical cases to medical officers
                </label>
                <div style={{ fontSize:11, color:'#6b7280', paddingLeft:24, marginTop:4 }}>
                  Cases with medical debits are routed to medical officers instead of general underwriters.
                </div>
              </div>
            )}
          </div>

          <div style={{ borderTop:'1px solid rgba(255,255,255,0.07)', paddingTop:16, marginBottom:16 }}>
            <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer', marginBottom:4 }}>
              <Checkbox checked={aiScore} onChange={e => setAiScore(e.target.checked)}/>
              🤖 Enable AI Risk Scoring for each row
            </label>
            <div style={{ fontSize:11, color:'#6b7280', paddingLeft:24, marginBottom:10 }}>
              Runs an AI model in addition to the standard rules engine for enhanced risk assessment.
            </div>
            {aiScore && (
              <div style={{ paddingLeft:24 }}>
                <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>AI Engine for Batch Scoring</div>
                <Select value={aiEngine} onChange={setAiEngine} style={{ width:'100%', maxWidth:300 }}>
                  <Option value="xgboost">XGBoost ML Model</Option>
                  <Option value="rules_only">Rules Only</Option>
                  <Option value="ollama">Ollama LLM (AI Server)</Option>
                  <Option value="claude">Claude AI (Anthropic)</Option>
                </Select>
                <div style={{ fontSize:11, color:'#4b5563', marginTop:6 }}>
                  AI scoring adds ~20–50ms per row. For 1,000 rows expect ~30–60 seconds extra.
                </div>
              </div>
            )}
          </div>

          <div style={{ borderTop:'1px solid rgba(255,255,255,0.07)', paddingTop:16, marginBottom:20 }}>
            <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:13, color:'#9ca3af', cursor:'pointer' }}>
              <Checkbox checked={sendEmail} onChange={e => setSendEmail(e.target.checked)}/>
              📧 Send decision emails to APPROVED applicants after batch completes
            </label>
            <div style={{ fontSize:11, color:'#4b5563', marginTop:6, paddingLeft:24 }}>
              {sendEmail
                ? '✅ Emails will be sent automatically to APPROVED cases after processing.'
                : '📧 Email sending is OFF. You can still send emails manually in Results & Downloads.'}
            </div>
          </div>

          {/* Validation errors */}
          {valWarnings.map((w,i) => (
            <div key={i} style={{ background:'rgba(251,191,36,0.08)', border:'1px solid rgba(251,191,36,0.2)', borderRadius:8, padding:'8px 12px', fontSize:12, color:'#fbbf24', marginBottom:8 }}>
              ⚠️ {w}
            </div>
          ))}
          {valErrors.map((e,i) => (
            <div key={i} style={{ background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.2)', borderRadius:8, padding:'8px 12px', fontSize:12, color:'#f87171', marginBottom:8 }}>
              🚫 {e}
            </div>
          ))}

          <Button type="primary" icon={<UploadOutlined/>} loading={submitting}
            onClick={validateAndSubmit} block size="large" style={{ height:44, fontWeight:600 }}>
            📤 Submit Batch
          </Button>
        </div>

        {/* Diagnose tool */}
        <Collapse ghost style={{ background:'rgba(255,255,255,0.01)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:10 }}>
          <Panel header={<span style={{ fontSize:13, color:'#9ca3af' }}>🔬 Diagnose SY001 errors — test a single record</span>} key="1">
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:12 }}>
              Use this to find out exactly what the engine returns for a specific record.
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10, marginBottom:10 }}>
              <div><div style={{ fontSize:11, color:'#6b7280', marginBottom:3 }}>Product Code</div><Input value={diagProd} onChange={e => setDiagProd(e.target.value)} size="small" style={{ fontFamily:'var(--font-mono,monospace)' }}/></div>
              <div><div style={{ fontSize:11, color:'#6b7280', marginBottom:3 }}>Age</div><InputNumber value={diagAge} onChange={v => setDiagAge(v||30)} min={18} max={80} size="small" style={{ width:'100%' }}/></div>
              <div><div style={{ fontSize:11, color:'#6b7280', marginBottom:3 }}>Gender</div><Select value={diagGender} onChange={setDiagGen} size="small" style={{ width:'100%' }}><Option value="MALE">MALE</Option><Option value="FEMALE">FEMALE</Option></Select></div>
              <div><div style={{ fontSize:11, color:'#6b7280', marginBottom:3 }}>State</div><Input value={diagState} onChange={e => setDiagSt(e.target.value)} size="small"/></div>
              <div><div style={{ fontSize:11, color:'#6b7280', marginBottom:3 }}>Face Amount</div><InputNumber value={diagFace} onChange={v => setDiagFace(v||100000)} min={100000} step={50000} size="small" style={{ width:'100%' }} formatter={v=>`₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g,',')} parser={(v:any)=>Number(v!.replace(/₹\s?|(,*)/g,''))}/></div>
              <div><div style={{ fontSize:11, color:'#6b7280', marginBottom:3 }}>Tobacco</div><Select value={diagTob} onChange={setDiagTob} size="small" style={{ width:'100%' }}><Option value="NON_TOBACCO">NON_TOBACCO</Option><Option value="SMOKER">SMOKER</Option><Option value="NEVER">NEVER</Option></Select></div>
            </div>
            <Button size="small" loading={diagging} onClick={runDiagnose} style={{ borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa' }}>
              🔬 Test Record
            </Button>
            {diagResult && (
              <div style={{ marginTop:12, background:'rgba(255,255,255,0.02)', borderRadius:8, padding:12 }}>
                {diagResult.error ? (
                  <div style={{ color:'#f87171', fontSize:12 }}>❌ {diagResult.error}</div>
                ) : (
                  <>
                    <div style={{ fontSize:13, color:'#22c55e', marginBottom:8 }}>
                      ✅ <strong>{diagResult.outcome}</strong> | Score: {diagResult.net_debit_points ?? diagResult.total_debits ?? '—'}
                    </div>
                    {diagResult.error_codes?.length > 0 && (
                      <div style={{ fontSize:12, color:'#f87171', marginBottom:8 }}>Error codes: {diagResult.error_codes.join(', ')}</div>
                    )}
                    <pre style={{ fontSize:11, color:'#6b7280', overflow:'auto', maxHeight:200, margin:0 }}>
                      {JSON.stringify(diagResult, null, 2)}
                    </pre>
                  </>
                )}
              </div>
            )}
          </Panel>
        </Collapse>
      </div>

      {/* Right — Resources */}
      <div>
        <div style={card}>
          <div style={secTitle}>Resources</div>
          <Button block icon={<DownloadOutlined/>} onClick={downloadTemplate} style={{ marginBottom:10 }}>
            📥 Download CSV Template
          </Button>
          <Button block icon={<DownloadOutlined/>}
            onClick={() => api.get('/batch/template', { responseType:'blob' }).then(r => {
              const url = URL.createObjectURL(r.data); const a = document.createElement('a')
              a.href=url; a.download='batch_template_api.csv'; a.click(); URL.revokeObjectURL(url)
            }).catch(() => message.warning('API template unavailable — use CSV template above'))}
            style={{ marginBottom:16 }}>
            📥 API Template (legacy)
          </Button>

          <div style={{ background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.25)', borderRadius:8, padding:'10px 14px', marginBottom:16 }}>
            <div style={{ fontSize:13, fontWeight:700, color:'#f87171', marginBottom:6 }}>⚠️ product_code required</div>
            <div style={{ fontSize:12, color:'#9ca3af', lineHeight:1.6 }}>
              The batch file must include <strong style={{ color:'#e2e8f0' }}>product_code</strong> (e.g.{' '}
              <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa' }}>IND-TERM-20</code>,{' '}
              <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa' }}>BSLI-END-10</code>)
              — NOT <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#f87171' }}>product_type</code>.
              Rules, thresholds and build tables are all looked up by product_code.
            </div>
          </div>

          <Collapse ghost>
            <Panel header={<span style={{ fontSize:12, color:'#9ca3af' }}>📋 Available Product Codes</span>} key="1">
              {products.length === 0
                ? <div style={{ fontSize:12, color:'#6b7280' }}>Could not load products</div>
                : products.map(p => (
                  <div key={p.product_code} style={{ fontSize:12, marginBottom:4 }}>
                    <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa' }}>{p.product_code}</code>
                    <span style={{ color:'#6b7280', marginLeft:8 }}>— {p.product_name || p.name}</span>
                  </div>
                ))
              }
            </Panel>
          </Collapse>

          <div style={{ marginTop:16 }}>
            <div style={secTitle}>Processing Modes</div>
            <div style={{ fontSize:12, color:'#9ca3af', marginBottom:6 }}>
              🟢 <strong style={{ color:'#22c55e' }}>Live</strong> — full UW evaluation, creates cases
            </div>
            <div style={{ fontSize:12, color:'#9ca3af' }}>
              🟡 <strong style={{ color:'#f59e0b' }}>Dry Run</strong> — validate only, no cases created
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2 — Job Monitor
// ══════════════════════════════════════════════════════════════════════════════
function JobMonitorTab({ onViewResults }: { onViewResults: (jobId: string) => void }) {
  const [jobs, setJobs]         = useState<BatchJob[]>([])
  const [loading, setLoading]   = useState(true)
  const [autoRefresh, setAuto]  = useState(false)
  const timerRef                = useRef<ReturnType<typeof setInterval>|null>(null)

  const load = async () => {
    try {
      const r = await api.get('/batch/jobs')
      const list = r.data?.jobs || r.data || []
      setJobs(Array.isArray(list) ? list : [])
    } catch { setJobs([]) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (autoRefresh) timerRef.current = setInterval(load, 5000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [autoRefresh])

  const cancelJob = async (id: string) => {
    try { await api.post(`/batch/jobs/${id}/cancel`); message.success('Job cancelled'); load() }
    catch { message.error('Cancel failed') }
  }

  const statusOrder: Record<string,number> = { PROCESSING:0, QUEUED:1, PENDING:1, FAILED:2, COMPLETED:3, CANCELLED:4 }
  const sorted = [...jobs].sort((a,b) => (statusOrder[a.status]??5) - (statusOrder[b.status]??5))

  const total    = jobs.length
  const processing = jobs.filter(j => j.status === 'PROCESSING').length
  const completed  = jobs.filter(j => j.status === 'COMPLETED').length
  const failed     = jobs.filter(j => ['FAILED','CANCELLED'].includes(j.status)).length
  const recTotal   = jobs.reduce((s,j) => s + (j.total_records||0), 0)
  const recProc    = jobs.reduce((s,j) => s + (j.processed||0), 0)

  return (
    <div>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:16 }}>
        <div style={{ fontSize:13, color:'#6b7280' }}>Live job status — refresh to see latest progress.</div>
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:10 }}>
          <Switch checked={autoRefresh} onChange={setAuto}
            checkedChildren="⚡ Auto" unCheckedChildren="Auto"/>
          <Button icon={<ReloadOutlined/>} onClick={load} loading={loading} size="small"/>
        </div>
      </div>
      {autoRefresh && <div style={{ fontSize:11, color:'#00d4aa', marginBottom:12 }}>🔄 Auto-refresh ON — refreshing every 5 seconds</div>}

      {/* Stats */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(6,1fr)', gap:10, marginBottom:20 }}>
        {[
          { label:'Total Jobs',    value:total,      color:'#00d4aa' },
          { label:'🟡 Processing', value:processing, color:'#f59e0b' },
          { label:'🟢 Completed',  value:completed,  color:'#22c55e' },
          { label:'🔴 Failed',     value:failed,     color:'#ef4444' },
          { label:'Records Total', value:recTotal.toLocaleString(), color:'#9ca3af' },
          { label:'Processed',     value:recProc.toLocaleString(),  color:'#9ca3af' },
        ].map(s => (
          <div key={s.label} style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:8, padding:'10px 12px' }}>
            <div style={{ fontSize:16, fontWeight:700, color:s.color }}>{s.value}</div>
            <div style={{ fontSize:10, color:'#6b7280', marginTop:2 }}>{s.label}</div>
          </div>
        ))}
      </div>

      {loading && jobs.length === 0 ? <Spin/> : sorted.length === 0 ? (
        <div style={{ color:'#6b7280', fontSize:13, padding:'24px 0' }}>
          No batch jobs yet. Upload a file in the Upload Batch tab to get started.
        </div>
      ) : sorted.map(job => {
        const isActive = ['PROCESSING','QUEUED','PENDING'].includes(job.status)
        const total    = job.total_records || 1
        const proc     = job.processed || 0
        const pct      = Math.round((proc / total) * 100)
        const appr     = job.approved || 0
        const decl     = job.declined || 0
        const ref      = job.referred || 0
        const err      = job.errored  || 0

        return (
          <div key={job.id} style={{ ...card, marginBottom:12 }}>
            <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:isActive||job.status==='COMPLETED'?12:0 }}>
              <span style={{ fontSize:16 }}>{STATUS_ICON[job.status]||'⚪'}</span>
              <strong style={{ color:'#e2e8f0', fontFamily:'var(--font-mono,monospace)', fontSize:13 }}>{job.job_number}</strong>
              <span style={{ color:'#9ca3af', fontSize:13 }}>{job.job_name || 'Batch Job'}</span>
              <Tag style={{ background:STATUS_COLOR[job.status]||'#6b7280', color:'#fff', border:'none', fontSize:11 }}>
                {job.status}
              </Tag>
              {job.dry_run && <Tag color="gold" style={{ fontSize:11 }}>DRY RUN</Tag>}
              <span style={{ fontSize:11, color:'#6b7280', marginLeft:'auto' }}>
                {(job.total_records||0).toLocaleString()} records
              </span>
            </div>

            {isActive && (
              <div style={{ marginBottom:12 }}>
                <Progress percent={pct} size="small" strokeColor="#00d4aa"
                  format={() => `${proc.toLocaleString()} / ${total.toLocaleString()} (${pct}%)`}/>
                <div style={{ fontSize:11, color:'#6b7280', marginTop:4 }}>
                  🔄 Turn on ⚡ Auto above to auto-refresh every 5 seconds
                </div>
              </div>
            )}

            {job.status === 'COMPLETED' && (
              <>
                <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:10, marginBottom:12 }}>
                  {[
                    { label:'✅ Approved', value:appr, color:'#22c55e' },
                    { label:'🔴 Declined', value:decl, color:'#ef4444' },
                    { label:'🟡 Referred', value:ref,  color:'#f59e0b' },
                    { label:'⚫ Errors',   value:err,  color:'#6b7280' },
                    { label:'📊 Processed',value:proc, color:'#9ca3af' },
                  ].map(s => (
                    <div key={s.label} style={{ background:'rgba(255,255,255,0.02)', borderRadius:6, padding:'8px 10px' }}>
                      <div style={{ fontSize:14, fontWeight:700, color:s.color }}>{s.value.toLocaleString()}</div>
                      <div style={{ fontSize:10, color:'#6b7280' }}>{s.label}</div>
                    </div>
                  ))}
                </div>
                {/* Decision bar */}
                <div style={{ display:'flex', height:8, borderRadius:4, overflow:'hidden', marginBottom:6 }}>
                  <div style={{ width:`${Math.round(appr/total*100)}%`, background:'#22c55e' }}/>
                  <div style={{ width:`${Math.round(ref/total*100)}%`,  background:'#f59e0b' }}/>
                  <div style={{ width:`${Math.round(decl/total*100)}%`, background:'#ef4444' }}/>
                  <div style={{ width:`${Math.round(err/total*100)}%`,  background:'#6b7280' }}/>
                </div>
                <div style={{ fontSize:11, color:'#6b7280', marginBottom:10 }}>
                  🟢 {Math.round(appr/total*100)}% approved &nbsp;
                  🟡 {Math.round(ref/total*100)}% referred &nbsp;
                  🔴 {Math.round(decl/total*100)}% declined &nbsp;
                  ⚫ {Math.round(err/total*100)}% errors
                </div>
              </>
            )}

            {job.error_message && (
              <div style={{ fontSize:12, color:'#f87171', marginBottom:10 }}>❌ {job.error_message}</div>
            )}

            <div style={{ fontSize:11, color:'#6b7280', marginBottom:10 }}>
              📅 {job.submitted_at?.slice(0,19).replace('T',' ')} &nbsp;|&nbsp;
              👤 {job.submitted_by?.split('@')[0] || '—'} &nbsp;|&nbsp;
              📄 {job.input_filename || ''} &nbsp;|&nbsp;
              {job.completed_at ? `✅ ${job.completed_at?.slice(0,19).replace('T',' ')}` : 'In progress...'}
            </div>

            <div style={{ display:'flex', gap:10 }}>
              {job.status === 'COMPLETED' && (
                <>
                  <Button size="small" type="primary" onClick={() => onViewResults(job.id)}>
                    📊 View Results
                  </Button>
                  <Button size="small" type="primary" onClick={() => onViewResults(job.id)}>
                    📥 Downloads
                  </Button>
                </>
              )}
              {['PENDING','QUEUED'].includes(job.status) && (
                <Button size="small" danger onClick={() => cancelJob(job.id)}>⏹️ Cancel Job</Button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3 — Results & Downloads
// ══════════════════════════════════════════════════════════════════════════════
function ResultsTab({ initialJobId }: { initialJobId?: string }) {
  const [jobs, setJobs]         = useState<BatchJob[]>([])
  const [selJob, setSelJob]     = useState(initialJobId || '')
  const [detail, setDetail]     = useState<BatchJob|null>(null)
  const [loading, setLoading]   = useState(true)
  const [dlLoading, setDlLoad]  = useState<string|null>(null)

  useEffect(() => {
    api.get('/batch/jobs').then(r => {
      const list = (r.data?.jobs || r.data || []) as BatchJob[]
      const done = list.filter(j => j.status === 'COMPLETED')
      setJobs(done)
      if (!selJob && done.length > 0) setSelJob(done[0].id)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!selJob) return
    api.get(`/batch/jobs/${selJob}`).then(r => setDetail(r.data)).catch(() => {
      const found = jobs.find(j => j.id === selJob)
      if (found) setDetail(found)
    })
  }, [selJob])

  const download = async (type: 'results'|'errors'|'summary', fmt: 'csv'|'xlsx') => {
    const key = `${type}_${fmt}`
    setDlLoad(key)
    try {
      const r = await api.get(`/batch/jobs/${selJob}/download/${type}`, {
        params: { fmt }, responseType: 'blob',
      })
      const ext  = fmt === 'xlsx' ? 'xlsx' : 'csv'
      const mime = fmt === 'xlsx'
        ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' : 'text/csv'
      const url  = URL.createObjectURL(new Blob([r.data], { type: mime }))
      const a    = document.createElement('a')
      a.href = url; a.download = `batch_${type}_${selJob.slice(0,8)}.${ext}`; a.click()
      URL.revokeObjectURL(url)
    } catch { message.error(`Download failed — ${type} not available`) }
    finally { setDlLoad(null) }
  }

  if (loading) return <Spin/>
  if (jobs.length === 0) return <div style={{ color:'#6b7280', fontSize:13 }}>No completed jobs yet.</div>

  const total  = detail?.total_records || 1
  const appr   = detail?.approved || 0
  const decl   = detail?.declined || 0
  const ref    = detail?.referred || 0
  const err    = detail?.errored  || 0

  return (
    <div>
      <div style={{ marginBottom:16 }}>
        <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Select job</div>
        <Select value={selJob} onChange={setSelJob} style={{ width:'100%' }} showSearch
          options={jobs.map(j => ({
            value: j.id,
            label: `${j.job_number} — ${j.job_name || 'Batch Job'} (${(j.total_records||0).toLocaleString()} records)`,
          }))}/>
      </div>

      {detail && (
        <>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12, marginBottom:16 }}>
            {[
              { label:'✅ Approved', value:appr, color:'#22c55e' },
              { label:'🔴 Declined', value:decl, color:'#ef4444' },
              { label:'🟡 Referred', value:ref,  color:'#f59e0b' },
              { label:'⚫ Errors',   value:err,  color:'#6b7280' },
            ].map(s => (
              <div key={s.label} style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:10, padding:'14px 16px' }}>
                <div style={{ fontSize:20, fontWeight:700, color:s.color }}>{s.value.toLocaleString()}</div>
                <div style={{ fontSize:11, color:'#6b7280', marginTop:2 }}>{s.label}</div>
              </div>
            ))}
          </div>

          <div style={{ fontSize:13, color:'#9ca3af', marginBottom:16 }}>
            <strong style={{ color:'#e2e8f0' }}>Decision Distribution:</strong>{' '}
            🟢 {Math.round(appr/total*100)}% approved &nbsp;
            🔴 {Math.round(decl/total*100)}% declined &nbsp;
            🟡 {Math.round(ref/total*100)}% referred &nbsp;
            ⚫ {Math.round(err/total*100)}% errors
          </div>

          <div style={card}>
            <div style={secTitle}>Download Reports</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16 }}>
              {(['results','errors','summary'] as const).map(type => (
                <div key={type}>
                  <div style={{ fontSize:13, fontWeight:600, color:'#e2e8f0', marginBottom:8, textTransform:'capitalize' }}>
                    {type === 'results' ? '📊 Full Results' : type === 'errors' ? '❌ Errors Only' : '📋 Summary'}
                  </div>
                  <div style={{ display:'flex', gap:8 }}>
                    <Button size="small" icon={<DownloadOutlined/>}
                      loading={dlLoading === `${type}_csv`}
                      onClick={() => download(type, 'csv')}
                      style={{ flex:1, borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa' }}>
                      CSV
                    </Button>
                    <Button size="small" icon={<DownloadOutlined/>}
                      loading={dlLoading === `${type}_xlsx`}
                      onClick={() => download(type, 'xlsx')}
                      style={{ flex:1, borderColor:'rgba(96,165,250,0.25)', color:'#60a5fa' }}>
                      Excel
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4 — Schedule
// ══════════════════════════════════════════════════════════════════════════════
function ScheduleTab() {
  const [schedules, setSchedules] = useState<any[]>([])
  const [loading, setLoading]     = useState(true)
  const [name, setName]           = useState('')
  const [cron, setCron]           = useState('0 2 * * 1')
  const [saving, setSaving]       = useState(false)

  useEffect(() => {
    api.get('/batch/schedules').then(r => setSchedules(Array.isArray(r.data) ? r.data : []))
      .catch(() => setSchedules([])).finally(() => setLoading(false))
  }, [])

  const save = async () => {
    if (!name.trim() || !cron.trim()) { message.warning('Name and cron expression required'); return }
    setSaving(true)
    try {
      await api.post('/batch/schedules', { schedule_name: name.trim(), cron_expression: cron.trim(), is_active: true })
      message.success('Schedule saved')
      const r = await api.get('/batch/schedules')
      setSchedules(Array.isArray(r.data) ? r.data : [])
      setName(''); setCron('0 2 * * 1')
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSaving(false) }
  }

  const toggle = async (id: string, active: boolean) => {
    try {
      await api.patch(`/batch/schedules/${id}`, { is_active: !active })
      setSchedules(prev => prev.map(s => s.id === id ? { ...s, is_active: !active } : s))
    } catch { message.error('Toggle failed') }
  }

  const PRESETS = [
    { label:'Daily at 2am',     value:'0 2 * * *'   },
    { label:'Weekly Monday 2am',value:'0 2 * * 1'   },
    { label:'Monthly 1st 2am',  value:'0 2 1 * *'   },
    { label:'Every 6 hours',    value:'0 */6 * * *' },
  ]

  return (
    <div>
      <div style={card}>
        <div style={secTitle}>Scheduled Batch Jobs</div>
        <div style={{ fontSize:13, color:'#6b7280', marginBottom:16 }}>
          Configure recurring batch jobs that run automatically on a cron schedule.
        </div>

        {loading ? <Spin/> : schedules.length === 0 ? (
          <div style={{ color:'#6b7280', fontSize:13, marginBottom:16 }}>No schedules configured yet.</div>
        ) : (
          <Table dataSource={schedules} rowKey="id" size="small" pagination={false}
            style={{ marginBottom:16 }}
            columns={[
              { title:'Name',       dataIndex:'schedule_name' },
              { title:'Cron',       dataIndex:'cron_expression', render:(v:string) => <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa' }}>{v}</code> },
              { title:'Status',     dataIndex:'is_active', width:100, render:(v:boolean) => <Tag color={v?'success':'default'}>{v?'Active':'Paused'}</Tag> },
              { title:'Last run',   dataIndex:'last_run_at', width:160, render:(v:string) => v?.slice(0,16)||'—' },
              { title:'Next run',   dataIndex:'next_run_at', width:160, render:(v:string) => v?.slice(0,16)||'—' },
              { title:'', width:100, render:(_:any, r:any) => (
                <Switch checked={r.is_active} size="small" onChange={() => toggle(r.id, r.is_active)}/>
              )},
            ]}/>
        )}
      </div>

      <div style={card}>
        <div style={secTitle}>Add New Schedule</div>
        <div style={{ marginBottom:12 }}>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Schedule Name</div>
          <Input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Weekly Monday Batch"/>
        </div>
        <div style={{ marginBottom:12 }}>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Cron Expression</div>
          <Input value={cron} onChange={e => setCron(e.target.value)}
            placeholder="0 2 * * 1" style={{ fontFamily:'var(--font-mono,monospace)', maxWidth:220 }}/>
          <div style={{ display:'flex', gap:8, flexWrap:'wrap', marginTop:8 }}>
            {PRESETS.map(p => (
              <Button key={p.value} size="small" onClick={() => setCron(p.value)}
                style={{ fontSize:11 }}>{p.label}</Button>
            ))}
          </div>
          <div style={{ fontSize:11, color:'#4b5563', marginTop:8 }}>
            Format: <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#9ca3af' }}>minute hour day month weekday</code>
          </div>
        </div>
        <Button type="primary" icon={<CalendarOutlined/>} loading={saving} onClick={save}>
          Save Schedule
        </Button>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE SHELL
// ══════════════════════════════════════════════════════════════════════════════
export default function BatchJobsPage() {
  const [activeTab, setTab]   = useState('upload')
  const [viewJobId, setView]  = useState<string|undefined>()

  const handleSubmitted = (jobId: string) => {
    setView(jobId); setTab('monitor')
  }

  const handleViewResults = (jobId: string) => {
    setView(jobId); setTab('results')
  }

  const tabs = [
    {
      key: 'upload',
      label: <span><UploadOutlined/> Upload Batch</span>,
      children: <UploadTab onSubmitted={handleSubmitted}/>,
    },
    {
      key: 'monitor',
      label: <span><BarChartOutlined/> Job Monitor</span>,
      children: <JobMonitorTab onViewResults={handleViewResults}/>,
    },
    {
      key: 'results',
      label: <span><DownloadOutlined/> Results & Downloads</span>,
      children: <ResultsTab initialJobId={viewJobId}/>,
    },
    {
      key: 'schedule',
      label: <span><CalendarOutlined/> Schedule</span>,
      children: <ScheduleTab/>,
    },
  ]

  return (
    <div style={{ padding:'32px 36px' }}>
      <div style={{ marginBottom:24 }}>
        <h1 style={{ fontWeight:700, fontSize:20, color:'#e2e8f0', margin:0, letterSpacing:'-0.02em' }}>
          📦 Batch Underwriting Jobs
        </h1>
        <p style={{ color:'#6b7280', fontSize:13, marginTop:4, marginBottom:0 }}>
          Upload CSV or Excel files for bulk underwriting. Results downloadable as CSV/Excel.
        </p>
      </div>
      <Tabs activeKey={activeTab} onChange={setTab} items={tabs}
        tabBarStyle={{ borderBottom:'1px solid rgba(255,255,255,0.07)', marginBottom:24 }}/>
    </div>
  )
}

