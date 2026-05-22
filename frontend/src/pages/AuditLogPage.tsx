import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Input, Select, Spin, message,
} from 'antd'
import {
  ReloadOutlined, DownloadOutlined, SearchOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

const { Option } = Select

// ── Types ──────────────────────────────────────────────────────────────────────
interface AuditEvent {
  event_id: string; occurred_at: string
  event_category: string; event_type: string
  actor_username: string; actor_role: string
  entity_type: string; entity_id: string; entity_ref: string
  outcome: string; failure_reason: string
  before_state: string; after_state: string
  event_metadata: string; actor_ip: string
}
interface Stats {
  total: number; decisions: number; overrides: number; auth: number
  config: number; assignments: number; user_mgmt: number; failures: number
}

// ── Constants ──────────────────────────────────────────────────────────────────
const CATEGORIES = ['All','DECISION','OVERRIDE','AUTH','ASSIGNMENT','APS','USER_MGMT','CONFIG','RULE','BATCH','MEMBER','DATA_ACCESS']
const CAT_COLOR: Record<string,string> = {
  DECISION:'#22c55e', OVERRIDE:'#ef4444', AUTH:'#3b82f6',
  ASSIGNMENT:'#a16207', APS:'#a855f7', USER_MGMT:'#f97316',
  CONFIG:'#eab308', RULE:'#6b7280', BATCH:'#fb923c',
  MEMBER:'#60a5fa', DATA_ACCESS:'#9ca3af',
}
const CAT_ICON: Record<string,string> = {
  DECISION:'🟢', OVERRIDE:'🔴', AUTH:'🔵', ASSIGNMENT:'🟤',
  APS:'🟣', USER_MGMT:'🟠', CONFIG:'🟡', RULE:'⚫',
  BATCH:'🔶', MEMBER:'🔷', DATA_ACCESS:'⚪',
}

// ── Styles ─────────────────────────────────────────────────────────────────────
const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 10, padding: '18px 22px', marginBottom: 16,
}
const statBlock: React.CSSProperties = {
  background: 'rgba(255,255,255,0.025)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 8, padding: '12px 14px',
}

function tryParseJson(s: string) {
  if (!s) return null
  try { return JSON.parse(s) } catch { return s }
}

// ── Event Detail Panel ─────────────────────────────────────────────────────────
function EventDetail({ event, onClose }: { event: AuditEvent; onClose: () => void }) {
  const [timeline, setTimeline] = useState<any[]>([])

  useEffect(() => {
    if (event.entity_id) {
      api.get(`/audit/entity/${event.entity_id}`)
        .then(r => setTimeline(Array.isArray(r.data) ? r.data : []))
        .catch(() => {})
    }
  }, [event.entity_id])

  const before = tryParseJson(event.before_state)
  const after  = tryParseJson(event.after_state)
  const meta   = tryParseJson(event.event_metadata)
  const isSuccess = event.outcome === 'SUCCESS'

  return (
    <div style={{ ...card, borderColor: isSuccess ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)' }}>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:16 }}>
        <div style={{ display:'flex', alignItems:'center', gap:10 }}>
          <Tag style={{ background: isSuccess ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
            color: isSuccess ? '#4ade80' : '#f87171', border:'none', fontSize:12, padding:'2px 10px' }}>
            {isSuccess ? '✅ SUCCESS' : '❌ FAILURE'}
          </Tag>
          <strong style={{ color:'#e2e8f0', fontSize:14 }}>{event.event_type}</strong>
          <span style={{ color:'#6b7280', fontSize:12 }}>· {event.occurred_at}</span>
          {event.actor_username && (
            <span style={{ color:'#9ca3af', fontSize:12 }}>· {event.actor_username} ({event.actor_role || '—'})</span>
          )}
          {event.failure_reason && (
            <span style={{ color:'#f87171', fontSize:12 }}>· ❌ {event.failure_reason}</span>
          )}
        </div>
        <Button size="small" onClick={onClose} style={{ color:'#6b7280' }}>✕ Close</Button>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16, marginBottom:16 }}>
        {/* Event info */}
        <div>
          <div style={{ fontSize:11, fontWeight:600, color:'#6b7280', marginBottom:8, textTransform:'uppercase' }}>Event</div>
          {[
            { label:'ID',       value:event.event_id?.slice(0,16)+'…' },
            { label:'Category', value:event.event_category },
            { label:'Entity',   value:`${event.entity_type || '—'} / ${event.entity_id || '—'}` },
            { label:'Ref',      value:event.entity_ref || '—' },
            { label:'IP',       value:event.actor_ip || '—' },
          ].map(f => (
            <div key={f.label} style={{ marginBottom:6 }}>
              <span style={{ fontSize:11, color:'#6b7280', marginRight:8 }}>{f.label}:</span>
              <span style={{ fontSize:12, color:'#9ca3af', fontFamily:'var(--font-mono,monospace)' }}>{f.value}</span>
            </div>
          ))}
        </div>

        {/* Before state */}
        <div>
          <div style={{ fontSize:11, fontWeight:600, color:'#6b7280', marginBottom:8, textTransform:'uppercase' }}>Before State</div>
          {before
            ? <pre style={{ fontSize:11, color:'#9ca3af', background:'rgba(0,0,0,0.2)', borderRadius:6, padding:10, overflow:'auto', maxHeight:180, margin:0 }}>
                {typeof before === 'object' ? JSON.stringify(before, null, 2) : String(before)}
              </pre>
            : <span style={{ fontSize:12, color:'#4b5563' }}>—</span>
          }
        </div>

        {/* After state */}
        <div>
          <div style={{ fontSize:11, fontWeight:600, color:'#6b7280', marginBottom:8, textTransform:'uppercase' }}>After State</div>
          {after
            ? <pre style={{ fontSize:11, color:'#9ca3af', background:'rgba(0,0,0,0.2)', borderRadius:6, padding:10, overflow:'auto', maxHeight:180, margin:0 }}>
                {typeof after === 'object' ? JSON.stringify(after, null, 2) : String(after)}
              </pre>
            : <span style={{ fontSize:12, color:'#4b5563' }}>—</span>
          }
        </div>
      </div>

      {/* Metadata */}
      {meta && (
        <div style={{ marginBottom:16 }}>
          <div style={{ fontSize:11, fontWeight:600, color:'#6b7280', marginBottom:6, textTransform:'uppercase' }}>Metadata</div>
          <pre style={{ fontSize:11, color:'#9ca3af', background:'rgba(0,0,0,0.2)', borderRadius:6, padding:10, overflow:'auto', maxHeight:120, margin:0 }}>
            {typeof meta === 'object' ? JSON.stringify(meta, null, 2) : String(meta)}
          </pre>
        </div>
      )}

      {/* Entity Timeline */}
      {timeline.length > 0 && (
        <div>
          <div style={{ fontSize:11, fontWeight:600, color:'#6b7280', marginBottom:8, textTransform:'uppercase' }}>
            All events for {event.entity_type} `{event.entity_id}` ({timeline.length})
          </div>
          <Table dataSource={timeline} rowKey={(r:any) => r.occurred_at + r.event_type}
            size="small" pagination={false}
            columns={[
              { title:'Time',     dataIndex:'occurred_at', width:160 },
              { title:'Event',    dataIndex:'event_type' },
              { title:'Actor',    dataIndex:'actor', width:130 },
              { title:'Category', dataIndex:'category', width:120 },
              { title:'Outcome',  dataIndex:'outcome', width:100,
                render:(v:string) => <Tag color={v==='SUCCESS'?'success':'error'} style={{ fontSize:11 }}>{v}</Tag> },
            ]}
          />
        </div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Page
// ══════════════════════════════════════════════════════════════════════════════
export default function AuditLogPage() {
  const today    = new Date().toISOString().slice(0,10)
  const month30  = new Date(Date.now() - 30*24*60*60*1000).toISOString().slice(0,10)

  const [stats, setStats]       = useState<Stats|null>(null)
  const [events, setEvents]     = useState<AuditEvent[]>([])
  const [total, setTotal]       = useState(0)
  const [totalPages, setTP]     = useState(1)
  const [loading, setLoading]   = useState(false)
  const [seeding, setSeeding]   = useState(false)
  const [selected, setSelected] = useState<AuditEvent|null>(null)
  const [exporting, setExport]  = useState(false)

  // Filters
  const [search, setSearch]     = useState('')
  const [dateFrom, setFrom]     = useState(month30)
  const [dateTo, setTo]         = useState(today)
  const [category, setCat]      = useState('All')
  const [outcome, setOutcome]   = useState('All')
  const [page, setPage]         = useState(1)

  const loadStats = async () => {
    try { const r = await api.get('/audit/stats'); setStats(r.data) } catch {}
  }

  const load = async (p = page) => {
    setLoading(true)
    try {
      const r = await api.get('/audit', {
        params: { search, date_from: dateFrom, date_to: dateTo, category, outcome, page: p, page_size: 50 }
      })
      setEvents(r.data.events || [])
      setTotal(r.data.total || 0)
      setTP(r.data.total_pages || 1)
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Failed to load audit log') }
    finally { setLoading(false) }
  }

  useEffect(() => { loadStats(); load(1) }, [])

  const handleSearch = () => { setPage(1); load(1) }
  const handlePageChange = (p: number) => { setPage(p); load(p) }

  const exportCsv = async () => {
    setExport(true)
    try {
      const r = await api.get('/audit/export', {
        params: { search, date_from: dateFrom, date_to: dateTo, category, outcome },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(new Blob([r.data], { type:'text/csv' }))
      const a   = document.createElement('a')
      a.href = url; a.download = `audit_${dateFrom}_${dateTo}.csv`; a.click()
      URL.revokeObjectURL(url)
      message.success('Export downloaded')
    } catch { message.error('Export failed') }
    finally { setExport(false) }
  }

  const seedLogin = async () => {
    setSeeding(true)
    try {
      await api.post('/audit/seed', { note: 'Manual seed from Audit Log page' })
      message.success('✅ Login event written to audit trail')
      loadStats(); load(1)
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Seed failed') }
    finally { setSeeding(false) }
  }

  const cols = [
    {
      title: 'Time', dataIndex: 'occurred_at', width: 155,
      render: (v:string) => <span style={{ fontSize:12, color:'#6b7280', fontFamily:'var(--font-mono,monospace)' }}>{v}</span>,
    },
    {
      title: 'Category', dataIndex: 'event_category', width: 130,
      render: (v:string) => (
        <Tag style={{ background: `${CAT_COLOR[v] || '#6b7280'}22`,
          color: CAT_COLOR[v] || '#9ca3af', border:`1px solid ${CAT_COLOR[v] || '#6b7280'}44`,
          fontSize:11 }}>
          {CAT_ICON[v]||'⚪'} {v}
        </Tag>
      ),
    },
    {
      title: 'Event', dataIndex: 'event_type',
      render: (v:string) => <span style={{ fontSize:12, fontWeight:600, color:'#e2e8f0' }}>{v}</span>,
    },
    {
      title: 'Actor', dataIndex: 'actor_username', width: 130,
      render: (v:string, r:AuditEvent) => (
        <div>
          <div style={{ fontSize:12, color:'#9ca3af' }}>{v || '—'}</div>
          {r.actor_role && <div style={{ fontSize:10, color:'#4b5563' }}>{r.actor_role}</div>}
        </div>
      ),
    },
    {
      title: 'Entity', dataIndex: 'entity_type', width: 120,
      render: (v:string, r:AuditEvent) => (
        <div>
          <div style={{ fontSize:11, color:'#6b7280' }}>{v || '—'}</div>
          {r.entity_ref && <div style={{ fontSize:11, color:'#9ca3af', fontFamily:'var(--font-mono,monospace)' }}>{r.entity_ref.slice(0,30)}</div>}
        </div>
      ),
    },
    {
      title: 'Outcome', dataIndex: 'outcome', width: 90,
      render: (v:string) => v === 'SUCCESS'
        ? <span style={{ color:'#4ade80', fontSize:14  }}>✅</span>
        : <span style={{ color:'#f87171', fontSize:14 }}>❌</span>,
    },
    {
      title: '', width: 70,
      render: (_:any, r:AuditEvent) => (
        <Button size="small" onClick={() => setSelected(r)}
          style={{ fontSize:11, borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa' }}>
          Detail
        </Button>
      ),
    },
  ]

  return (
    <div style={{ padding:'32px 36px' }}>
      {/* Header */}
      <div style={{ marginBottom:20 }}>
        <h1 style={{ fontWeight:700, fontSize:20, color:'#e2e8f0', margin:0, letterSpacing:'-0.02em' }}>
          🔍 Audit Log
        </h1>
        <p style={{ color:'#6b7280', fontSize:13, marginTop:4, marginBottom:0 }}>
          Immutable record of every decision, override, assignment, login, config change and user management action. Cannot be edited or deleted.
        </p>
      </div>

      {/* Seed button */}
      <div style={{ marginBottom:16 }}>
        <Button loading={seeding} onClick={seedLogin} size="small"
          style={{ borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa', fontSize:12 }}>
          📝 Record current session login to audit trail
        </Button>
        <span style={{ fontSize:11, color:'#4b5563', marginLeft:10 }}>
          Use this once to confirm the audit table is working.
        </span>
      </div>

      {/* Stats */}
      {stats && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(8,1fr)', gap:10, marginBottom:24 }}>
          {[
            { label:'Total (30d)',  value:stats.total,       color:'#00d4aa' },
            { label:'Decisions',   value:stats.decisions,   color:'#22c55e' },
            { label:'Overrides',   value:stats.overrides,   color:'#ef4444' },
            { label:'Auth',        value:stats.auth,        color:'#3b82f6' },
            { label:'Config',      value:stats.config,      color:'#eab308' },
            { label:'Assignments', value:stats.assignments, color:'#a16207' },
            { label:'User Mgmt',   value:stats.user_mgmt,  color:'#f97316' },
            { label:'Failures',    value:stats.failures,    color:stats.failures > 0 ? '#ef4444' : '#6b7280' },
          ].map(s => (
            <div key={s.label} style={statBlock}>
              <div style={{ fontSize:18, fontWeight:700, color:s.color, fontVariantNumeric:'tabular-nums' }}>
                {(s.value||0).toLocaleString()}
              </div>
              <div style={{ fontSize:10, color:'#6b7280', marginTop:2 }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div style={{ ...card, marginBottom:16 }}>
        <div style={{ display:'grid', gridTemplateColumns:'2fr 1fr 1fr 1fr 1fr', gap:12, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:11, color:'#6b7280', marginBottom:4 }}>Search</div>
            <Input prefix={<SearchOutlined style={{ color:'#6b7280' }}/>}
              value={search} onChange={e => setSearch(e.target.value)}
              onPressEnter={handleSearch}
              placeholder="username, case ref, event type…" allowClear/>
          </div>
          <div>
            <div style={{ fontSize:11, color:'#6b7280', marginBottom:4 }}>From</div>
            <input type="date" value={dateFrom} onChange={e => setFrom(e.target.value)}
              style={{ width:'100%', background:'rgba(255,255,255,0.04)', border:'1px solid rgba(255,255,255,0.1)', borderRadius:6, padding:'5px 10px', color:'#e2e8f0', fontSize:13 }}/>
          </div>
          <div>
            <div style={{ fontSize:11, color:'#6b7280', marginBottom:4 }}>To</div>
            <input type="date" value={dateTo} onChange={e => setTo(e.target.value)}
              style={{ width:'100%', background:'rgba(255,255,255,0.04)', border:'1px solid rgba(255,255,255,0.1)', borderRadius:6, padding:'5px 10px', color:'#e2e8f0', fontSize:13 }}/>
          </div>
          <div>
            <div style={{ fontSize:11, color:'#6b7280', marginBottom:4 }}>Category</div>
            <Select value={category} onChange={setCat} style={{ width:'100%' }}>
              {CATEGORIES.map(c => <Option key={c} value={c}>{c === 'All' ? 'All' : `${CAT_ICON[c]||'⚪'} ${c}`}</Option>)}
            </Select>
          </div>
          <div>
            <div style={{ fontSize:11, color:'#6b7280', marginBottom:4 }}>Outcome</div>
            <Select value={outcome} onChange={setOutcome} style={{ width:'100%' }}>
              <Option value="All">All</Option>
              <Option value="SUCCESS">✅ SUCCESS</Option>
              <Option value="FAILURE">❌ FAILURE</Option>
            </Select>
          </div>
        </div>
        <div style={{ display:'flex', gap:10, alignItems:'center' }}>
          <Button type="primary" onClick={handleSearch} loading={loading}>
            Search
          </Button>
          <Button icon={<ReloadOutlined/>} onClick={() => { setPage(1); load(1); loadStats() }} loading={loading}>
            Refresh
          </Button>
          <Button icon={<DownloadOutlined/>} loading={exporting} onClick={exportCsv}
            style={{ borderColor:'rgba(0,212,170,0.25)', color:'#00d4aa' }}>
            Export CSV
          </Button>
          <span style={{ fontSize:12, color:'#6b7280', marginLeft:'auto' }}>
            {total.toLocaleString()} events · Page {page} of {totalPages}
          </span>
        </div>
      </div>

      {/* Selected event detail */}
      {selected && (
        <EventDetail event={selected} onClose={() => setSelected(null)}/>
      )}

      {/* Table */}
      {loading && events.length === 0 ? <Spin/> : (
        <Table
          dataSource={events}
          columns={cols}
          rowKey="event_id"
          size="small"
          pagination={{
            current: page,
            total,
            pageSize: 50,
            showSizeChanger: false,
            onChange: handlePageChange,
            showTotal: (t) => `${t.toLocaleString()} events`,
          }}
          onRow={(r) => ({
            style: { cursor:'pointer' },
            onClick: () => setSelected(r),
          })}
          locale={{ emptyText: 'No audit events found for the selected filters.' }}
          style={{ background:'transparent' }}
        />
      )}
    </div>
  )
}
