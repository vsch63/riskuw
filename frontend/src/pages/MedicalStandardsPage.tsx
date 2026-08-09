// ══════════════════════════════════════════════════════════════════════════
// MedicalStandardsPage.tsx — data-driven underwriting standards (V034)
//
// Manages the R001–R080 catalogue that the engine now reads from
// uw_medical_standard(_rule/_range). Editing a RANGE rule's bands changes the
// evaluated debit points for the next proposal; editing FLAT rules changes
// fixed-point conditions. Optionally scoped to a product code to create a
// per-product override (system defaults otherwise apply).
// ══════════════════════════════════════════════════════════════════════════
import { useCallback, useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, InputNumber, Select, Switch,
  message, Space, Card, Typography, Tag, Alert,
} from 'antd'
import { ReloadOutlined, SaveOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { medicalStandardsAPI } from '../api/client'
import { Titled } from '../components/ColHint'

const { Text } = Typography

const card = {
  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 10, padding: '14px 16px', marginBottom: 16,
}
const mono: React.CSSProperties = { fontFamily: 'var(--font-mono)', fontSize: 11 }

type RangeRow = {
  key: string
  min_value: number | null
  max_value: number | null
  min_exclusive: boolean
  max_exclusive: boolean
  name?: string
  debit_points: number
  requires_aps: boolean
  aps_reason?: string | null
}

type RuleRow = {
  key: string
  rule_type: 'FLAT' | 'RANGE'
  param?: string
  name?: string
  debit_points: number
  requires_aps: boolean
  condition?: object | null
  ranges: RangeRow[]
}

type Standard = {
  code: string
  family: string
  name: string
  category: string
  rules: RuleRow[]
}

// Header fields held while the editor modal is open — either an existing
// standard (isNew=false, code locked) or a brand-new one (isNew=true).
type StandardDraft = {
  code: string
  family: string
  name: string
  category: string
  isNew: boolean
}

const uid = () => Math.random().toString(36).slice(2, 9)

export default function MedicalStandardsPage({ embedded = false }: { embedded?: boolean }) {
  const [standards, setStandards] = useState<Standard[]>([])
  const [loading, setLoading] = useState(false)
  const [productScope, setProductScope] = useState<string>('')
  const [draft, setDraft] = useState<StandardDraft | null>(null)
  const [rules, setRules] = useState<RuleRow[]>([])
  const [saveScope, setSaveScope] = useState<string>('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await medicalStandardsAPI.list(productScope || undefined)
      setStandards((r.data || []).map((s: Standard) => s))
    } catch (e: any) {
      message.error(e?.message || 'Failed to load standards')
    } finally {
      setLoading(false)
    }
  }, [productScope])

  useEffect(() => { load() }, [load])

  const openAdd = () => {
    setDraft({ code: '', family: '', name: '', category: 'BUILD', isNew: true })
    setSaveScope(productScope || '')
    setRules([])
  }

  const openEdit = (s: Standard) => {
    setDraft({ code: s.code, family: s.family, name: s.name, category: s.category, isNew: false })
    setSaveScope(productScope || '')
    setRules((s.rules || []).map((r) => ({
      key: uid(), rule_type: r.rule_type, param: r.param, name: r.name,
      debit_points: r.debit_points, requires_aps: r.requires_aps,
      condition: r.condition || null,
      ranges: (r.ranges || []).map((b) => ({
        key: uid(), min_value: b.min_value, max_value: b.max_value,
        min_exclusive: b.min_exclusive, max_exclusive: b.max_exclusive,
        name: b.name, debit_points: b.debit_points, requires_aps: b.requires_aps,
        aps_reason: b.aps_reason,
      })),
    })))
  }

  const updateRule = (key: string, patch: Partial<RuleRow>) =>
    setRules((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const updateRange = (ruleKey: string, rangeKey: string, patch: Partial<RangeRow>) =>
    setRules((rs) => rs.map((r) => r.key === ruleKey
      ? { ...r, ranges: r.ranges.map((b) => (b.key === rangeKey ? { ...b, ...patch } : b)) }
      : r))

  const addRange = (ruleKey: string) =>
    setRules((rs) => rs.map((r) => r.key === ruleKey
      ? { ...r, ranges: [...r.ranges, { key: uid(), min_value: null, max_value: null, min_exclusive: false, max_exclusive: false, name: '', debit_points: 0, requires_aps: false }] }
      : r))

  const removeRange = (ruleKey: string, rangeKey: string) =>
    setRules((rs) => rs.map((r) => r.key === ruleKey
      ? { ...r, ranges: r.ranges.filter((b) => b.key !== rangeKey) } : r))

  const save = async () => {
    if (!draft) return
    setSaving(true)
    try {
      if (!draft.code.trim()) {
        message.error('A standard code is required (e.g. R085)')
        setSaving(false)
        return
      }
      const payload = {
        family: draft.family, name: draft.name, category: draft.category,
        product_code: saveScope || null,
        rules: rules.map((r) => ({
          rule_type: r.rule_type,
          condition: r.condition || null,
          param: r.param || null,
          name: r.name || null,
          debit_points: r.debit_points,
          requires_aps: r.requires_aps,
          ranges: r.rule_type === 'RANGE'
            ? r.ranges.map((b) => ({
                min_value: b.min_value, max_value: b.max_value,
                min_exclusive: b.min_exclusive, max_exclusive: b.max_exclusive,
                name: b.name || null, debit_points: b.debit_points,
                requires_aps: b.requires_aps, aps_reason: b.aps_reason || null,
              }))
            : [],
        })),
      }
      const code = draft.code.trim().toUpperCase()
      const r = await medicalStandardsAPI.upsert(code, payload)
      message.success(`Standard ${code} ${draft.isNew ? 'created' : 'saved'}`)
      setDraft(null)
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const cols = [
    { title: Titled('Code', 'code'), dataIndex: 'code', width: 70, render: (v: string) => <Tag style={mono}>{v}</Tag> },
    { title: Titled('Family', 'family'), dataIndex: 'family', width: 130 },
    { title: Titled('Name', 'name'), dataIndex: 'name' },
    { title: Titled('Category', 'category'), dataIndex: 'category', width: 130 },
    { title: 'Rules', width: 70, render: (_: any, s: Standard) => s.rules?.length || 0 },
    { title: 'Bands', width: 70, render: (_: any, s: Standard) => (s.rules || []).reduce((n, r) => n + (r.ranges?.length || 0), 0) },
    {
      title: '', width: 80, render: (_: any, s: Standard) =>
        <Button size="small" onClick={() => openEdit(s)}>Edit</Button>,
    },
  ]

  return (
    <div style={{ padding: embedded ? 0 : 20 }}>
      <Card bordered={false} style={{ background: 'transparent', marginBottom: 14 }}>
        <Space wrap style={{ justifyContent: 'space-between', width: '100%' }}>
          <div>
            <Typography.Title level={4} style={{ margin: 0 }}>Underwriting Standards</Typography.Title>
            <Text type="secondary">R001–R080 catalogue · edits take effect on the next evaluation · audited</Text>
          </div>
          <Space>
            <Select
              placeholder="Scope: system defaults"
              allowClear
              style={{ width: 260 }}
              value={productScope || undefined}
              onChange={(v) => setProductScope(v || '')}
              options={[]}
              showSearch
              onSearch={(q) => setProductScope(q)}
            />
            <Button icon={<ReloadOutlined />} onClick={load}>Reload</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>New Standard</Button>
          </Space>
        </Space>
      </Card>

      {productScope && (
        <Alert
          style={{ marginBottom: 12 }}
          type="info" showIcon
          message={`Editing scope: product "${productScope}". Saving a standard here creates a product-specific override; system defaults still apply to other products.`}
        />
      )}

      <Card bordered={false} style={card}>
        <Table size="small" rowKey="code" dataSource={standards} columns={cols}
               loading={loading} pagination={false} />
      </Card>

      <Modal
        title={draft ? (draft.isNew ? 'New Standard' : `Edit ${draft.code} — ${draft.name}`) : ''}
        open={!!draft} onOk={save} onCancel={() => setDraft(null)}
        okText={draft?.isNew ? 'Create' : 'Save'} confirmLoading={saving} width={860} destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space wrap>
            <div style={{ width: 110 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>Code</Text>
              <Input style={mono} value={draft?.code} disabled={!draft?.isNew}
                     placeholder="R085" onChange={(e) => setDraft((d) => d && ({ ...d, code: e.target.value }))} />
            </div>
            <div style={{ width: 160 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>Family</Text>
              <Input value={draft?.family} placeholder="e.g. Build"
                     onChange={(e) => setDraft((d) => d && ({ ...d, family: e.target.value }))} />
            </div>
            <div style={{ width: 240 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>Name</Text>
              <Input value={draft?.name} placeholder="e.g. Body mass index"
                     onChange={(e) => setDraft((d) => d && ({ ...d, name: e.target.value }))} />
            </div>
            <div style={{ width: 120 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>Category</Text>
              <Input value={draft?.category} placeholder="BUILD"
                     onChange={(e) => setDraft((d) => d && ({ ...d, category: e.target.value }))} />
            </div>
          </Space>
          <Space wrap>
            <Text type="secondary">Product override (optional):</Text>
            <Input value={saveScope} onChange={(e) => setSaveScope(e.target.value)}
                   placeholder="leave blank = system level" style={{ width: 260 }} />
          </Space>

          {rules.map((rule) => (
            <div key={rule.key} style={{ ...card, padding: '10px 12px' }}>
              <Space wrap style={{ marginBottom: 8 }}>
                <Tag color={rule.rule_type === 'RANGE' ? 'blue' : 'purple'}>{rule.rule_type}</Tag>
                {rule.param && <Tag style={mono}>param: {rule.param}</Tag>}
                <Input size="small" style={{ width: 300 }} value={rule.name || ''} placeholder="Rule name"
                       onChange={(e) => updateRule(rule.key, { name: e.target.value })} />
                <span>Pts</span>
                <InputNumber size="small" value={rule.debit_points} min={-999} max={999}
                             onChange={(v) => updateRule(rule.key, { debit_points: v ?? 0 })} />
                <Switch size="small" checked={rule.requires_aps} onChange={(v) => updateRule(rule.key, { requires_aps: v })}
                        checkedChildren="APS" unCheckedChildren="No APS" />
              </Space>

              {rule.rule_type === 'RANGE' ? (
                <div>
                  <Table size="small" rowKey="key" pagination={false} dataSource={rule.ranges}
                         columns={[
                           { title: 'Min', width: 90, render: (_: any, b: RangeRow) => (
                             <InputNumber size="small" style={{ width: 80 }} value={b.min_value}
                               onChange={(v) => updateRange(rule.key, b.key, { min_value: v ?? null })} />) },
                           { title: 'Max', width: 90, render: (_: any, b: RangeRow) => (
                             <InputNumber size="small" style={{ width: 80 }} value={b.max_value}
                               onChange={(v) => updateRange(rule.key, b.key, { max_value: v ?? null })} />) },
                           { title: 'Excl', width: 130, render: (_: any, b: RangeRow) => (
                             <Space size={2}>
                               <span style={{ fontSize: 11 }}>min</span>
                               <Switch size="small" checked={b.min_exclusive}
                                 onChange={(v) => updateRange(rule.key, b.key, { min_exclusive: v })} />
                               <span style={{ fontSize: 11 }}>max</span>
                               <Switch size="small" checked={b.max_exclusive}
                                 onChange={(v) => updateRange(rule.key, b.key, { max_exclusive: v })} />
                             </Space>) },
                           { title: 'Band name', render: (_: any, b: RangeRow) => (
                             <Input size="small" value={b.name || ''}
                               onChange={(e) => updateRange(rule.key, b.key, { name: e.target.value })} />) },
                           { title: 'Pts', width: 90, render: (_: any, b: RangeRow) => (
                             <InputNumber size="small" style={{ width: 70 }} value={b.debit_points} min={-999} max={999}
                               onChange={(v) => updateRange(rule.key, b.key, { debit_points: v ?? 0 })} />) },
                           { title: 'APS', width: 60, render: (_: any, b: RangeRow) => (
                             <Switch size="small" checked={b.requires_aps}
                               onChange={(v) => updateRange(rule.key, b.key, { requires_aps: v })} />) },
                           { title: '', width: 40, render: (_: any, b: RangeRow) => (
                             <Button size="small" type="text" danger icon={<DeleteOutlined />}
                               onClick={() => removeRange(rule.key, b.key)} />) },
                         ]}
                         footer={() => (
                           <Button size="small" type="dashed" icon={<PlusOutlined />}
                             onClick={() => addRange(rule.key)} style={{ width: '100%' }}>
                             Add band
                           </Button>
                         )} />
                </div>
              ) : (
                <div>
                  <Text type="secondary" style={{ fontSize: 11 }}>Trigger condition (read-only JSON):</Text>
                  <pre style={{ ...mono, background: 'rgba(0,0,0,0.25)', padding: 8, borderRadius: 6, whiteSpace: 'pre-wrap', marginTop: 4 }}>
                    {JSON.stringify(rule.condition, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </Space>
      </Modal>
    </div>
  )
}
