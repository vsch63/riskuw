import { useEffect, useState } from 'react'
import {
  Button, Input, Select, Switch, InputNumber,
  message, Spin, Table, Popconfirm, Divider,
} from 'antd'
import {
  SaveOutlined, ReloadOutlined, SendOutlined,
  DownloadOutlined, EyeOutlined, ApiOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

const { Option } = Select
const { TextArea } = Input

// ── Constants ──────────────────────────────────────────────────────────────────
const AVAILABLE_COLS: Record<string, string> = {
  applicant_ref:    'Applicant reference',
  applicant_name:   'Applicant name',
  applicant_email:  'Applicant email',
  case_id:          'Case ID',
  job_id:           'Batch job ID',
  product_code:     'Product code',
  face_amount:      'Face amount',
  age:              'Age',
  gender:           'Gender',
  state:            'State',
  outcome:          'Outcome',
  risk_class:       'Risk class',
  net_debit_points: 'Net debit points',
  approved_premium: 'Approved premium',
  effective_date:   'Policy effective date',
  expire_date:      'Policy expiry date',
  decision_date:    'Decision date',
  reason:           'Decision reason',
  source:           'Source (ONLINE/BATCH)',
  created_at:       'Record created at',
}

// ── Styles ─────────────────────────────────────────────────────────────────────
const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 10, padding: '20px 24px', marginBottom: 20,
}
const secTitle: React.CSSProperties = {
  fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginBottom: 4,
}
const secCaption: React.CSSProperties = {
  fontSize: 12, color: '#6b7280', marginBottom: 16,
}

// ── Types ──────────────────────────────────────────────────────────────────────
interface QueueStats {
  total: number; pushed: number; pending: number; failed: number; unprocessed: number
}
interface FailedRecord {
  id: number; applicant_ref: string; applicant_name: string
  outcome: string; push_attempts: number; push_last_error: string
  push_last_at: string; created_at: string
}
interface WebhookConfig {
  webhook_url: string; webhook_method: string
  webhook_auth_type: string; webhook_auth_value: string
  webhook_api_key_header: string; webhook_timeout: number
  webhook_max_retries: number; webhook_envelope_key: string
  webhook_custom_headers: string; webhook_auto_push: boolean
  columns: string[]; webhook_field_map: Record<string, string>
  file_format: string; delimiter: string; filename_prefix: string
}

export default function OutputInterfacePage() {
  const [cfg, setCfg]             = useState<Partial<WebhookConfig>>({})
  const [stats, setStats]         = useState<QueueStats|null>(null)
  const [failed, setFailed]       = useState<FailedRecord[]>([])
  const [loading, setLoading]     = useState(true)
  const [savingWh, setSavingWh]   = useState(false)
  const [savingFm, setSavingFm]   = useState(false)
  const [savingFs, setSavingFs]   = useState(false)
  const [pushing, setPushing]     = useState(false)
  const [testing, setTesting]     = useState(false)
  const [extracting, setExtract]  = useState(false)
  const [preview, setPreview]     = useState<any[]>([])
  const [showPreview, setShowPv]  = useState(false)

  // field map state
  const [selectedCols, setSelCols]   = useState<Record<string,boolean>>({})
  const [renames, setRenames]        = useState<Record<string,string>>({})

  // file settings
  const [fileFormat, setFileFormat] = useState('csv')
  const [delimiter, setDelimiter]   = useState(',')
  const [fnPrefix, setFnPrefix]     = useState('policy_admin')

  // webhook form
  const [whUrl, setWhUrl]           = useState('')
  const [whMethod, setWhMethod]     = useState('POST')
  const [whAuth, setWhAuth]         = useState('NONE')
  const [whToken, setWhToken]       = useState('')
  const [whKeyHdr, setWhKeyHdr]     = useState('X-API-Key')
  const [whTimeout, setWhTimeout]   = useState(15)
  const [whRetries, setWhRetries]   = useState(3)
  const [whEnvelope, setWhEnvelope] = useState('')
  const [whCustomHdr, setWhCustomHdr] = useState('')
  const [whAutoPush, setWhAutoPush] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [cfgR, statsR, failR] = await Promise.all([
        api.get('/system/output-interface').catch(() => ({ data: {} })),
        api.get('/system/output-interface/stats').catch(() => ({ data: null })),
        api.get('/system/output-interface/failed').catch(() => ({ data: [] })),
      ])
      const c: Partial<WebhookConfig> = cfgR.data || {}
      setCfg(c)

      // Populate webhook form
      setWhUrl(c.webhook_url || '')
      setWhMethod(c.webhook_method || 'POST')
      setWhAuth(c.webhook_auth_type || 'NONE')
      setWhToken(c.webhook_auth_value || '')
      setWhKeyHdr(c.webhook_api_key_header || 'X-API-Key')
      setWhTimeout(Number(c.webhook_timeout) || 15)
      setWhRetries(Number(c.webhook_max_retries) || 3)
      setWhEnvelope(c.webhook_envelope_key || '')
      setWhCustomHdr(c.webhook_custom_headers || '')
      setWhAutoPush(c.webhook_auto_push !== false)

      // Populate field map
      const savedCols = c.columns || Object.keys(AVAILABLE_COLS)
      const colSel: Record<string,boolean> = {}
      Object.keys(AVAILABLE_COLS).forEach(k => { colSel[k] = savedCols.includes(k) })
      setSelCols(colSel)
      setRenames(c.webhook_field_map || {})

      // File settings
      setFileFormat(c.file_format || 'csv')
      setDelimiter(c.delimiter || ',')
      setFnPrefix(c.filename_prefix || 'policy_admin')

      if (statsR.data) setStats(statsR.data)
      setFailed(Array.isArray(failR.data) ? failR.data : [])
    } catch { message.error('Failed to load output interface config') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const saveWebhook = async () => {
    setSavingWh(true)
    try {
      await api.post('/system/output-interface', {
        ...cfg,
        webhook_url:          whUrl.trim(),
        webhook_method:       whMethod,
        webhook_auth_type:    whAuth,
        webhook_auth_value:   whToken.trim(),
        webhook_api_key_header: whKeyHdr.trim() || 'X-API-Key',
        webhook_timeout:      whTimeout,
        webhook_max_retries:  whRetries,
        webhook_envelope_key: whEnvelope.trim(),
        webhook_custom_headers: whCustomHdr.trim(),
        webhook_auto_push:    whAutoPush,
      })
      message.success('Webhook configuration saved')
      load()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSavingWh(false) }
  }

  const saveFieldMap = async () => {
    const cols = Object.entries(selectedCols).filter(([,v]) => v).map(([k]) => k)
    if (!cols.length) { message.error('Select at least one field'); return }
    const fmap: Record<string,string> = {}
    Object.entries(renames).forEach(([k,v]) => { if (v.trim() && v.trim() !== k) fmap[k] = v.trim() })
    setSavingFm(true)
    try {
      await api.post('/system/output-interface', { ...cfg, columns: cols, webhook_field_map: fmap })
      message.success(`Field mapping saved — ${cols.length} fields, ${Object.keys(fmap).length} renamed`)
      load()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSavingFm(false) }
  }

  const saveFileSettings = async () => {
    setSavingFs(true)
    try {
      await api.post('/system/output-interface', {
        ...cfg, file_format: fileFormat, delimiter, filename_prefix: fnPrefix.trim() || 'policy_admin',
      })
      message.success('File settings saved')
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Save failed') }
    finally { setSavingFs(false) }
  }

  const testWebhook = async () => {
    if (!whUrl.trim()) { message.warning('Enter webhook URL first'); return }
    setTesting(true)
    try {
      await api.post('/system/output-interface/test', {
        applicant_ref:'TEST-001', applicant_name:'Test Applicant',
        product_code:'IND-TERM-20', face_amount:1000000,
        outcome:'APPROVED', risk_class:'STANDARD',
        approved_premium:12000, decision_date:new Date().toISOString().slice(0,10),
        source:'TEST', _test:true,
      })
      message.success('✅ Test succeeded — webhook is working!')
    } catch(e:any) { message.error('Test failed: ' + (e?.response?.data?.detail || e.message)) }
    finally { setTesting(false) }
  }

  const pushAll = async () => {
    if (!whUrl.trim()) { message.error('Configure webhook URL in Block 1 first'); return }
    setPushing(true)
    try {
      const r = await api.post('/system/output-interface/push')
      const d = r.data
      if (d.pushed) message.success(`✅ Pushed ${d.pushed} record(s) to PAS`)
      if (d.failed) message.error(`❌ ${d.failed} record(s) failed`)
      if (!d.pushed && !d.failed) message.info('No pending records to push')
      load()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Push failed') }
    finally { setPushing(false) }
  }

  const repushSingle = async (id: number) => {
    try {
      await api.post(`/system/output-interface/push/${id}`)
      message.success('Record pushed'); load()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Push failed') }
  }

  const runExtract = async () => {
    setExtract(true)
    try {
      const r = await api.post('/system/output-interface/extract', {
        file_format: fileFormat, delimiter, filename_prefix: fnPrefix,
      }, { responseType: 'blob' })
      const ext  = fileFormat === 'excel' ? 'xlsx' : 'csv'
      const date = new Date().toISOString().slice(0,19).replace(/[-:T]/g,s=>s==='-'?s:s===':'?s:'_')
      const url  = URL.createObjectURL(r.data)
      const a    = document.createElement('a')
      a.href = url; a.download = `${fnPrefix}_${date}.${ext}`; a.click()
      URL.revokeObjectURL(url)
      message.success('Extract downloaded')
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Extract failed') }
    finally { setExtract(false) }
  }

  const loadPreview = async () => {
    try {
      const r = await api.get('/system/output-interface/preview')
      setPreview(Array.isArray(r.data) ? r.data : [])
      setShowPv(true)
    } catch { message.error('Preview unavailable') }
  }

  if (loading) return <div style={{ display:'flex', justifyContent:'center', padding:80 }}><Spin size="large"/></div>

  return (
    <div style={{ padding:'32px 36px' }}>
      {/* Header */}
      <div style={{ marginBottom:24, display:'flex', alignItems:'flex-start', justifyContent:'space-between' }}>
        <div>
          <h1 style={{ fontWeight:700, fontSize:20, color:'#e2e8f0', margin:0, letterSpacing:'-0.02em', display:'flex', alignItems:'center', gap:10 }}>
            <ApiOutlined style={{ color:'#00d4aa' }}/>Output Interface
          </h1>
          <p style={{ color:'#6b7280', fontSize:13, marginTop:4, marginBottom:0 }}>
            Configure how underwriting decisions are pushed to your policy administration system — via webhook API push or file extract.
          </p>
        </div>
        <Button icon={<ReloadOutlined/>} onClick={load}>Refresh</Button>
      </div>

      {/* Stats */}
      {stats && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:12, marginBottom:24 }}>
          {[
            { label:'Total Records',    value:stats.total,       color:'#00d4aa' },
            { label:'Pushed to PAS',    value:stats.pushed,      color:'#22c55e' },
            { label:'Pending Push',     value:stats.pending,     color:'#fbbf24' },
            { label:'Push Failed',      value:stats.failed,      color:'#ef4444' },
            { label:'Unextracted (CSV)',value:stats.unprocessed, color:'#9ca3af' },
          ].map(s => (
            <div key={s.label} style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:10, padding:'14px 16px' }}>
              <div style={{ fontSize:22, fontWeight:700, color:s.color, fontVariantNumeric:'tabular-nums' }}>{(s.value||0).toLocaleString()}</div>
              <div style={{ fontSize:11, color:'#6b7280', marginTop:3 }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* ── Block 1 — Webhook Config ─────────────────────────────────────── */}
      <div style={card}>
        <div style={secTitle}>🌐 Block 1 — Webhook Push Configuration</div>
        <div style={secCaption}>
          Configure the PAS API endpoint. Once set, every new approved decision is pushed automatically. Use Block 3 to push existing backlog records.
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'3fr 1fr', gap:12, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>PAS Webhook URL *</div>
            <Input value={whUrl} onChange={e => setWhUrl(e.target.value)}
              placeholder="https://your-pas.example.com/api/v1/decisions"/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Method</div>
            <Select value={whMethod} onChange={setWhMethod} style={{ width:'100%' }} placeholder="Select HTTP method…">
              <Option value="POST">POST</Option>
              <Option value="PUT">PUT</Option>
            </Select>
          </div>
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Authentication</div>
            <Select value={whAuth} onChange={setWhAuth} style={{ width:'100%' }} placeholder="Select auth type…">
              {['NONE','BEARER','API_KEY','BASIC'].map(a => <Option key={a} value={a}>{a}</Option>)}
            </Select>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Token / Key / user:password</div>
            <Input.Password value={whToken} onChange={e => setWhToken(e.target.value)}
              placeholder="Bearer token, API key, or user:password"/>
          </div>
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>API Key header name</div>
            <Input value={whKeyHdr} onChange={e => setWhKeyHdr(e.target.value)} placeholder="X-API-Key"/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Timeout (seconds)</div>
            <InputNumber value={whTimeout} onChange={v => setWhTimeout(v||15)} min={5} max={120} style={{ width:'100%' }} placeholder="15"/>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Max retries</div>
            <InputNumber value={whRetries} onChange={v => setWhRetries(v||3)} min={1} max={10} style={{ width:'100%' }} placeholder="3"/>
          </div>
        </div>

        <div style={{ marginBottom:12 }}>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>
            Envelope key (optional)
            <span style={{ color:'#4b5563', marginLeft:8 }}>wraps payload as {`{"key": {...}}`}</span>
          </div>
          <Input value={whEnvelope} onChange={e => setWhEnvelope(e.target.value)}
            placeholder='e.g. "decision" wraps payload as {"decision": {...}}'/>
        </div>

        <div style={{ marginBottom:12 }}>
          <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>
            Custom headers (JSON object, optional)
          </div>
          <TextArea value={whCustomHdr} onChange={e => setWhCustomHdr(e.target.value)}
            rows={2} placeholder='{"X-Client-ID": "UW-PLATFORM", "X-Version": "2"}'
            style={{ fontFamily:'var(--font-mono,monospace)', fontSize:12 }}/>
        </div>

        <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:16 }}>
          <Switch checked={whAutoPush} onChange={setWhAutoPush}/>
          <span style={{ fontSize:13, color:'#9ca3af' }}>
            Auto-push on every new decision
          </span>
        </div>

        <div style={{ display:'flex', gap:10 }}>
          <Button type="primary" icon={<SaveOutlined/>} loading={savingWh} onClick={saveWebhook}>
            Save Webhook Config
          </Button>
          {whUrl && (
            <Button icon={<SendOutlined/>} loading={testing} onClick={testWebhook}
              style={{ borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa' }}>
              Test Webhook
            </Button>
          )}
        </div>

        {whUrl ? (
          <div style={{ marginTop:12, background:'rgba(34,197,94,0.08)', border:'1px solid rgba(34,197,94,0.2)', borderRadius:8, padding:'8px 14px', fontSize:12, color:'#4ade80' }}>
            🌐 {whUrl.length > 60 ? whUrl.slice(0,60)+'…' : whUrl} &nbsp;|&nbsp; {whMethod} &nbsp;|&nbsp; Auth: {whAuth} &nbsp;|&nbsp; {whAutoPush ? 'Auto-push ON' : 'Manual push only'}
          </div>
        ) : (
          <div style={{ marginTop:12, background:'rgba(251,191,36,0.08)', border:'1px solid rgba(251,191,36,0.2)', borderRadius:8, padding:'8px 14px', fontSize:12, color:'#fbbf24' }}>
            ⚠ No webhook URL configured yet.
          </div>
        )}
      </div>

      {/* ── Block 2 — Field Mapping ──────────────────────────────────────── */}
      <div style={card}>
        <div style={secTitle}>🗂️ Block 2 — Field Mapping</div>
        <div style={secCaption}>
          Map internal field names to the field names your PAS expects. Leave blank to use the internal name. Also controls which fields are included in CSV exports.
        </div>

        <div style={{ fontSize:13, color:'#9ca3af', fontWeight:600, marginBottom:12 }}>
          Select fields and optionally rename them for your PAS:
        </div>

        {Object.entries(AVAILABLE_COLS).map(([key, label]) => (
          <div key={key} style={{ display:'grid', gridTemplateColumns:'36px 1fr 1fr', gap:12, alignItems:'center', padding:'6px 0', borderBottom:'1px solid rgba(255,255,255,0.04)' }}>
            <input type="checkbox"
              checked={selectedCols[key] !== false}
              onChange={e => setSelCols(c => ({ ...c, [key]: e.target.checked }))}
              style={{ accentColor:'#00d4aa', width:16, height:16 }}/>
            <div style={{ fontSize:12 }}>
              <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#00d4aa', fontSize:11 }}>{key}</code>
              <span style={{ color:'#6b7280', marginLeft:8 }}>— {label}</span>
            </div>
            <Input
              value={renames[key] || ''}
              onChange={e => setRenames(r => ({ ...r, [key]: e.target.value }))}
              placeholder={key} size="small"
              style={{ fontFamily:'var(--font-mono,monospace)', fontSize:12 }}/>
          </div>
        ))}

        <Button type="primary" icon={<SaveOutlined/>} loading={savingFm} onClick={saveFieldMap} style={{ marginTop:16 }}>
          Save Field Mapping
        </Button>
      </div>

      {/* ── Block 3 — Push Queue ─────────────────────────────────────────── */}
      <div style={card}>
        <div style={secTitle}>🚀 Block 3 — Webhook Push Queue</div>
        <div style={secCaption}>
          Push pending records to the PAS webhook. Retry failed records. Every push is logged to the audit trail.
        </div>

        {stats && (
          <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:16 }}>
            {[
              { label:'Pending push', value:stats.pending, color:'#fbbf24' },
              { label:'Push failed',  value:stats.failed,  color:'#ef4444' },
              { label:'Pushed OK',    value:stats.pushed,  color:'#22c55e' },
            ].map(s => (
              <div key={s.label} style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:8, padding:'12px 16px' }}>
                <div style={{ fontSize:18, fontWeight:700, color:s.color }}>{(s.value||0).toLocaleString()}</div>
                <div style={{ fontSize:11, color:'#6b7280', marginTop:2 }}>{s.label}</div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display:'flex', gap:10 }}>
          <Button type="primary" icon={<SendOutlined/>} loading={pushing} onClick={pushAll}>
            🚀 Push all pending to PAS
          </Button>
          <Button icon={<ReloadOutlined/>} onClick={load}>Refresh</Button>
        </div>

        {/* Failed records */}
        {failed.length > 0 && (
          <div style={{ marginTop:20 }}>
            <div style={{ fontSize:13, fontWeight:600, color:'#f87171', marginBottom:12 }}>
              Failed Records ({failed.length})
            </div>
            <Table
              dataSource={failed}
              rowKey="id"
              size="small"
              pagination={{ pageSize:10, showSizeChanger:false }}
              columns={[
                { title:'Applicant',   dataIndex:'applicant_ref',    width:130 },
                { title:'Name',        dataIndex:'applicant_name',   width:150 },
                { title:'Outcome',     dataIndex:'outcome',          width:100 },
                { title:'Attempts',    dataIndex:'push_attempts',    width:80  },
                { title:'Last Error',  dataIndex:'push_last_error',  render:(v:string) => <span style={{ fontSize:11, color:'#f87171' }}>{v?.slice(0,60)||'—'}</span> },
                { title:'Last Tried',  dataIndex:'push_last_at',     width:140, render:(v:string) => v?.slice(0,16)||'—' },
                { title:'', width:80, render:(_:any, r:FailedRecord) => (
                  <Button size="small" icon={<ReloadOutlined/>}
                    onClick={() => repushSingle(r.id)}
                    style={{ borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa' }}>
                    Retry
                  </Button>
                )},
              ]}
            />
          </div>
        )}
      </div>

      {/* ── Block 4 — CSV Extract ────────────────────────────────────────── */}
      <div style={card}>
        <div style={secTitle}>📁 Block 4 — CSV / Excel File Extract</div>
        <div style={secCaption}>
          Manual fallback extract — downloads a file for systems that cannot accept a webhook push. Records already pushed via webhook are excluded.
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:12, marginBottom:16 }}>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>File format</div>
            <Select value={fileFormat} onChange={setFileFormat} style={{ width:'100%' }} placeholder="Select format…">
              <Option value="csv">CSV</Option>
              <Option value="excel">Excel (.xlsx)</Option>
            </Select>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>CSV delimiter</div>
            <Select value={delimiter} onChange={setDelimiter} style={{ width:'100%' }} disabled={fileFormat==='excel'} placeholder="Select delimiter…">
              <Option value=",">, (comma)</Option>
              <Option value="|">| (pipe)</Option>
              <Option value=";">; (semicolon)</Option>
              <Option value={'\t'}>tab</Option>
            </Select>
          </div>
          <div>
            <div style={{ fontSize:12, color:'#6b7280', marginBottom:4 }}>Filename prefix</div>
            <Input value={fnPrefix} onChange={e => setFnPrefix(e.target.value)} placeholder="policy_admin"/>
          </div>
        </div>

        <div style={{ fontSize:11, color:'#4b5563', marginBottom:12 }}>
          Files named: <code style={{ fontFamily:'var(--font-mono,monospace)', color:'#9ca3af' }}>{fnPrefix || 'policy_admin'}_YYYYMMDD_HHMMSS.{fileFormat === 'excel' ? 'xlsx' : 'csv'}</code>
        </div>

        <div style={{ display:'flex', gap:10, marginBottom:16 }}>
          <Button type="primary" icon={<SaveOutlined/>} loading={savingFs} onClick={saveFileSettings}>
            Save File Settings
          </Button>
          <Button type="primary" icon={<DownloadOutlined/>} loading={extracting} onClick={runExtract}>
            🚀 Run Extract Now
          </Button>
          <Button icon={<EyeOutlined/>} onClick={loadPreview}>
            Preview unprocessed
          </Button>
        </div>

        {showPreview && preview.length > 0 && (
          <div>
            <div style={{ fontSize:13, color:'#9ca3af', marginBottom:8 }}>
              Preview — {preview.length} unprocessed records (max 50)
            </div>
            <Table
              dataSource={preview}
              rowKey="case_id"
              size="small"
              pagination={false}
              scroll={{ x:true }}
              columns={[
                { title:'Applicant ref', dataIndex:'applicant_ref',  width:130 },
                { title:'Name',          dataIndex:'applicant_name', width:150 },
                { title:'Product',       dataIndex:'product_code',   width:130 },
                { title:'Outcome',       dataIndex:'outcome',        width:100 },
                { title:'Decision date', dataIndex:'decision_date',  width:120 },
                { title:'Push status',   dataIndex:'push_status',    width:110 },
                { title:'Source',        dataIndex:'source',         width:90  },
                { title:'Queued at',     dataIndex:'created_at',     width:130, render:(v:string) => v?.slice(0,16)||'—' },
              ]}
            />
          </div>
        )}
        {showPreview && preview.length === 0 && (
          <div style={{ color:'#6b7280', fontSize:13 }}>No unprocessed records.</div>
        )}
      </div>
    </div>
  )
}
