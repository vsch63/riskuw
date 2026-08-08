import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Input, Select, Spin, Modal, Form,
  message, Tabs, Popconfirm, Alert,
} from 'antd'
import {
  KeyOutlined, PlusOutlined, DeleteOutlined, CopyOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ApiOutlined,
  BookOutlined, BarChartOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useCurrency } from '../context/CurrencyContext'
import { Titled } from '../components/ColHint'

const { Option } = Select

const _tok = () => localStorage.getItem('riskuw_token') || ''
const devApi = {
  get: (path: string, params?: any) => {
    const url = params ? `${path}?${new URLSearchParams(params)}` : path
    return fetch(url, { headers: { Authorization: `Bearer ${_tok()}` } }).then(r => r.json())
  },
  post: (path: string, body?: any) =>
    fetch(path, { method: 'POST', headers: { Authorization: `Bearer ${_tok()}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json()),
  delete: (path: string) =>
    fetch(path, { method: 'DELETE', headers: { Authorization: `Bearer ${_tok()}` } }).then(r => r.json()),
}

const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 10, padding: 20, marginBottom: 16,
}

// ══════════════════════════════════════════════════════════════════════════════
// API Keys Tab
// ══════════════════════════════════════════════════════════════════════════════
function APIKeysTab() {
  const [keys, setKeys]         = useState<any[]>([])
  const [loading, setLoading]   = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [newKeyResult, setNewKeyResult] = useState<any>(null)
  const [creating, setCreating] = useState(false)
  const [copied, setCopied]     = useState(false)
  const [form] = Form.useForm()

  const load = () => {
    setLoading(true)
    devApi.get('/api-keys')
      .then(d => setKeys(Array.isArray(d) ? d : []))
      .catch(() => setKeys([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const createKey = async () => {
    const v = await form.validateFields()
    setCreating(true)
    try {
      const r = await devApi.post('/api-keys', {
        name: v.name,
        environment: v.environment || 'sandbox',
        expires_in_days: v.expires_in_days || undefined,
      })
      if (r?.detail) throw new Error(r.detail)
      setNewKeyResult(r)
      form.resetFields()
      load()
    } catch (e: any) { message.error(e.message || 'Failed to create key') }
    finally { setCreating(false) }
  }

  const revokeKey = async (id: number) => {
    try {
      await devApi.delete(`/api-keys/${id}`)
      message.success('Key revoked')
      load()
    } catch { message.error('Failed to revoke key') }
  }

  const copyKey = () => {
    if (newKeyResult?.api_key) {
      navigator.clipboard.writeText(newKeyResult.api_key)
      setCopied(true)
      message.success('Copied to clipboard')
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const closeNewKeyModal = () => {
    setNewKeyResult(null)
    setCreateOpen(false)
    setCopied(false)
  }

  const columns = [
    {
      title: Titled('Name', 'name'), dataIndex: 'name',
      render: (v: string, r: any) => (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{v}</div>
          <div style={{ fontSize: 11, color: '#6b7280', fontFamily: 'var(--font-mono,monospace)' }}>{r.masked}</div>
        </div>
      ),
    },
    {
      title: Titled('Environment', 'environment'), dataIndex: 'environment', width: 110,
      render: (v: string) => (
        <Tag color={v === 'live' ? 'success' : 'default'} style={{ fontSize: 10 }}>
          {v === 'live' ? '🟢 LIVE' : '🧪 SANDBOX'}
        </Tag>
      ),
    },
    {
      title: Titled('Status', 'is_active'), dataIndex: 'is_active', width: 100,
      render: (v: boolean) => v
        ? <Tag color="success" icon={<CheckCircleOutlined />}>Active</Tag>
        : <Tag color="error" icon={<CloseCircleOutlined />}>Revoked</Tag>,
    },
    {
      title: Titled('Requests', 'request_count'), dataIndex: 'request_count', width: 90,
      render: (v: number) => <span style={{ fontFamily: 'var(--font-mono,monospace)', fontSize: 12 }}>{v ?? 0}</span>,
    },
    {
      title: Titled('Last Used', 'last_used_at'), dataIndex: 'last_used_at', width: 140,
      render: (v: string) => v ? <span style={{ fontSize: 11, color: '#6b7280' }}>{v.slice(0, 16).replace('T', ' ')}</span> : <span style={{ color: '#4b5563' }}>Never</span>,
    },
    {
      title: Titled('Created', 'created_at'), dataIndex: 'created_at', width: 140,
      render: (v: string) => <span style={{ fontSize: 11, color: '#6b7280' }}>{v?.slice(0, 16).replace('T', ' ')} by {''}</span>,
    },
    {
      title: '', width: 80,
      render: (_: any, r: any) => r.is_active ? (
        <Popconfirm title="Revoke this key? Any integration using it will stop working immediately." onConfirm={() => revokeKey(r.id)} okText="Revoke" okButtonProps={{ danger: true }}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ) : null,
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 13, color: '#6b7280' }}>
          API keys let external systems (banks, brokers, your own integrations) call RiskUW programmatically.
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          Generate New Key
        </Button>
      </div>

      {loading ? <Spin /> : (
        <Table dataSource={keys} columns={columns} rowKey="id" size="middle"
          locale={{ emptyText: 'No API keys yet. Generate one to start integrating.' }} />
      )}

      {/* Create key modal */}
      <Modal
        title={<span style={{ color: '#e2e8f0' }}><KeyOutlined /> Generate API Key</span>}
        open={createOpen && !newKeyResult}
        onCancel={() => setCreateOpen(false)}
        onOk={createKey}
        confirmLoading={creating}
        okText="Generate"
        styles={{ content: { background: 'var(--navy-800,#0a1628)' }, header: { background: 'var(--navy-800,#0a1628)' } }}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="Key Name" rules={[{ required: true, message: 'Required' }]}>
            <Input placeholder="e.g. Production - HDFC Bank integration" />
          </Form.Item>
          <Form.Item name="environment" label="Environment" initialValue="sandbox">
            <Select>
              <Option value="sandbox">🧪 Sandbox (testing — no production impact)</Option>
              <Option value="live">🟢 Live (production)</Option>
            </Select>
          </Form.Item>
          <Form.Item name="expires_in_days" label="Expires After (days, optional)">
            <Input type="number" placeholder="Leave blank for no expiry" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Show new key once modal */}
      <Modal
        title={<span style={{ color: '#e2e8f0' }}>✅ API Key Generated</span>}
        open={!!newKeyResult}
        onCancel={closeNewKeyModal}
        footer={[<Button key="done" type="primary" onClick={closeNewKeyModal}>I've saved my key — Done</Button>]}
        closable={false}
        maskClosable={false}
        styles={{ content: { background: 'var(--navy-800,#0a1628)' }, header: { background: 'var(--navy-800,#0a1628)' } }}
      >
        <Alert
          type="warning" showIcon icon={<WarningOutlined />}
          message="This key will not be shown again"
          description="Copy it now and store it securely. If you lose it, you'll need to generate a new one."
          style={{ marginBottom: 16 }}
        />
        <div style={{ background: 'rgba(0,212,170,0.05)', border: '1px solid rgba(0,212,170,0.2)',
          borderRadius: 8, padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <code style={{ flex: 1, fontSize: 13, color: '#00d4aa', wordBreak: 'break-all', fontFamily: 'var(--font-mono,monospace)' }}>
            {newKeyResult?.api_key}
          </code>
          <Button size="small" icon={<CopyOutlined />} onClick={copyKey}>
            {copied ? 'Copied!' : 'Copy'}
          </Button>
        </div>
        <div style={{ fontSize: 12, color: '#6b7280', marginTop: 12 }}>
          Use this key in the <code>X-API-Key</code> header for all requests. See the Documentation tab for examples.
        </div>
      </Modal>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Documentation Tab
// ══════════════════════════════════════════════════════════════════════════════
function DocumentationTab() {
  const [keys, setKeys] = useState<any[]>([])
  const [lang, setLang] = useState<'curl' | 'python' | 'javascript'>('curl')

  useEffect(() => {
    devApi.get('/api-keys').then(d => setKeys(Array.isArray(d) ? d.filter((k: any) => k.is_active) : [])).catch(() => {})
  }, [])

  const exampleKey = keys[0]?.masked?.replace(/•+$/, 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx') || 'ruw_sandbox_YOUR_KEY_HERE'
  const baseUrl = window.location.origin

  const examples: Record<string, string> = {
    curl: `curl -X POST ${baseUrl}/underwriting/evaluate \\
  -H "X-API-Key: ${exampleKey}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "applicant_ref": "EXT-12345",
    "product_code": "IND-TERM-20",
    "age": 35,
    "gender": "MALE",
    "state": "MH",
    "face_amount": 5000000,
    "tobacco_status": "NON_TOBACCO"
  }'`,
    python: `import requests

response = requests.post(
    "${baseUrl}/underwriting/evaluate",
    headers={"X-API-Key": "${exampleKey}"},
    json={
        "applicant_ref": "EXT-12345",
        "product_code": "IND-TERM-20",
        "age": 35,
        "gender": "MALE",
        "state": "MH",
        "face_amount": 5000000,
        "tobacco_status": "NON_TOBACCO",
    },
)
result = response.json()
print(result["outcome"])  # APPROVED_STP, REFERRED, DECLINED...`,
    javascript: `const response = await fetch("${baseUrl}/underwriting/evaluate", {
  method: "POST",
  headers: {
    "X-API-Key": "${exampleKey}",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    applicant_ref: "EXT-12345",
    product_code: "IND-TERM-20",
    age: 35,
    gender: "MALE",
    state: "MH",
    face_amount: 5000000,
    tobacco_status: "NON_TOBACCO",
  }),
})
const result = await response.json()
console.log(result.outcome)  // APPROVED_STP, REFERRED, DECLINED...`,
  }

  return (
    <div style={{ maxWidth: 820 }}>
      <div style={card}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>🔐 Authentication</div>
        <div style={{ fontSize: 13, color: '#9ca3af', lineHeight: 1.6, marginBottom: 12 }}>
          Every request must include your API key in the <code style={{ color: '#00d4aa' }}>X-API-Key</code> header.
          Generate a key in the API Keys tab. Sandbox keys are safe for testing — they don't count against your
          production decision limits.
        </div>
        {keys.length === 0 && (
          <Alert type="info" showIcon message="You don't have any API keys yet"
            description="Go to the API Keys tab to generate one before testing these examples." />
        )}
      </div>

      <div style={card}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', marginBottom: 12 }}>🚀 Quick Start — Evaluate an Application</div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          {(['curl', 'python', 'javascript'] as const).map(l => (
            <Button key={l} size="small"
              type={lang === l ? 'primary' : 'default'}
              onClick={() => setLang(l)}>
              {l === 'curl' ? 'cURL' : l === 'python' ? 'Python' : 'JavaScript'}
            </Button>
          ))}
        </div>
        <pre style={{
          background: '#0a0e1a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8,
          padding: 16, fontSize: 12, color: '#9ca3af', overflowX: 'auto', fontFamily: 'var(--font-mono,monospace)',
          lineHeight: 1.6,
        }}>
          {examples[lang]}
        </pre>
      </div>

      <div style={card}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>📋 Response Fields</div>
        <div style={{ fontSize: 12, color: '#9ca3af', lineHeight: 1.8 }}>
          <div><code style={{ color: '#00d4aa' }}>outcome</code> — APPROVED_STP, APPROVED, REFERRED, DECLINED</div>
          <div><code style={{ color: '#00d4aa' }}>risk_class</code> — PREFERRED, STANDARD, SUBSTANDARD, RATED</div>
          <div><code style={{ color: '#00d4aa' }}>net_debit_points</code> — underwriting score driving the decision</div>
          <div><code style={{ color: '#00d4aa' }}>approved_premium</code> — calculated annual premium (if approved)</div>
          <div><code style={{ color: '#00d4aa' }}>premium_detail</code> — full breakdown across payment modes (monthly/quarterly/annual)</div>
          <div><code style={{ color: '#00d4aa' }}>case_number</code> — reference for this decision in RiskUW</div>
        </div>
      </div>

      <div style={card}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>📚 Full API Reference</div>
        <div style={{ fontSize: 13, color: '#9ca3af', marginBottom: 12 }}>
          Interactive documentation for every endpoint — request/response schemas, try-it-now console.
        </div>
        <Button icon={<BookOutlined />} onClick={() => window.open(`${baseUrl}/docs`, '_blank')}>
          Open Full API Docs (Swagger)
        </Button>
      </div>

      <div style={card}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>🔑 Other Key Endpoints</div>
        <div style={{ fontSize: 12, color: '#9ca3af', lineHeight: 2 }}>
          <div><Tag style={{ fontSize: 10 }}>POST</Tag> <code style={{ color: '#00d4aa' }}>/underwriting/evaluate</code> — Single application decision</div>
          <div><Tag style={{ fontSize: 10 }}>POST</Tag> <code style={{ color: '#00d4aa' }}>/batch/upload</code> — Bulk processing (CSV/Excel)</div>
          <div><Tag style={{ fontSize: 10 }}>GET</Tag> <code style={{ color: '#00d4aa' }}>/underwriting/cases</code> — List past decisions</div>
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Usage Tab
// ══════════════════════════════════════════════════════════════════════════════
function UsageTab() {
  const [usage, setUsage]     = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    devApi.get('/api-keys/usage', { days: 30 })
      .then(d => setUsage(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin />

  const monthTotal = usage?.month_total_requests ?? 0
  const limit       = usage?.max_decisions_per_month ?? 0
  const pct          = limit > 0 ? Math.min(100, Math.round((monthTotal / limit) * 100)) : 0

  const columns = [
    { title: Titled('Date', 'usage_date'), dataIndex: 'usage_date', width: 120,
      render: (v: string) => <span style={{ fontSize: 12, color: '#9ca3af' }}>{v}</span> },
    { title: Titled('Endpoint', 'endpoint'), dataIndex: 'endpoint',
      render: (v: string) => <code style={{ fontSize: 11, color: '#00d4aa' }}>{v}</code> },
    { title: Titled('Requests', 'requests'), dataIndex: 'requests', width: 100,
      render: (v: number) => <span style={{ fontFamily: 'var(--font-mono,monospace)', fontSize: 12 }}>{v}</span> },
    { title: Titled('Errors', 'errors'), dataIndex: 'errors', width: 100,
      render: (v: number) => <span style={{ fontFamily: 'var(--font-mono,monospace)', fontSize: 12, color: v > 0 ? '#ef4444' : '#6b7280' }}>{v}</span> },
  ]

  return (
    <div>
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <span style={{ fontSize: 13, color: '#9ca3af' }}>This Month's API Usage</span>
          <span style={{ fontFamily: 'var(--font-mono,monospace)', fontSize: 18, fontWeight: 700, color: '#00d4aa' }}>
            {monthTotal.toLocaleString()} {limit > 0 && <span style={{ fontSize: 13, color: '#6b7280' }}>/ {limit.toLocaleString()}</span>}
          </span>
        </div>
        {limit > 0 && (
          <div style={{ height: 8, background: 'rgba(255,255,255,0.07)', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${pct}%`,
              background: pct > 90 ? '#ef4444' : pct > 70 ? '#fbbf24' : 'linear-gradient(90deg, #00d4aa, #22c55e)',
              borderRadius: 4 }} />
          </div>
        )}
      </div>

      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginBottom: 12 }}>Daily Breakdown (Last 30 Days)</div>
        <Table dataSource={usage?.daily || []} columns={columns} rowKey={(r: any) => `${r.usage_date}-${r.endpoint}`}
          size="small" pagination={{ pageSize: 15 }}
          locale={{ emptyText: 'No API usage recorded yet' }} />
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Page
// ══════════════════════════════════════════════════════════════════════════════
export default function DeveloperPortalPage() {
  const tabs = [
    { key: 'keys', label: <span><KeyOutlined /> API Keys</span>, children: <APIKeysTab /> },
    { key: 'docs', label: <span><BookOutlined /> Documentation</span>, children: <DocumentationTab /> },
    { key: 'usage', label: <span><BarChartOutlined /> Usage</span>, children: <UsageTab /> },
  ]

  return (
    <div style={{ padding: '32px 36px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontWeight: 700, fontSize: 22, color: '#e2e8f0', margin: 0, letterSpacing: '-0.02em' }}>
          <ApiOutlined /> Developer Portal
        </h1>
        <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          Integrate RiskUW's underwriting engine into your own systems — banks, brokers, and partner platforms.
        </p>
      </div>
      <Tabs defaultActiveKey="keys" items={tabs}
        tabBarStyle={{ borderBottom: '1px solid rgba(255,255,255,0.07)', marginBottom: 20 }} />
    </div>
  )
}
