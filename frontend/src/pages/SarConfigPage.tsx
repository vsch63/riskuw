// ══════════════════════════════════════════════════════════════════════════
// SarConfigPage.tsx — Sum-at-Risk configuration (SAR framework, V026)
//
// Manages the SAR pipeline configuration:
//   * Benefit Master   — per-benefit SAR formula + risk-group memberships
//   * Risk Groups      — actuarial aggregation buckets (LIFE/HEALTH/ACCIDENT)
//   * Exposure Groups  — underwriting-treatment buckets (EMPLOYER_BASE/…)
//   * Aggregation      — SUM/MAXIMUM per (risk_group, exposure_group, product)
//   * FCL Config       — Free Cover Limits (FLAT or FORMULA)
//   * NML Config       — Non-Medical Limit bands → medical requirements
//
// All endpoints are tenant-scoped; config changes take effect immediately.
// ══════════════════════════════════════════════════════════════════════════
import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, InputNumber, Switch, Popconfirm, Divider, DatePicker,
  message, Tag, Space, Tabs, Card, Typography, Alert,
} from 'antd'
import dayjs from 'dayjs'
import { PlusOutlined, ReloadOutlined, MinusCircleOutlined } from '@ant-design/icons'
import MedicalStandardsPage from './MedicalStandardsPage'
import { Titled } from '../components/ColHint'
import { sarConfigAPI, productsAPI } from '../api/client'

const { Option } = Select

const SAR_FORMULAS = ['FACE_AMOUNT', 'MORTALITY_PORTION', 'NET_AMOUNT_AT_RISK', 'PERCENTAGE', 'SUM_OF_SELECTED', 'MAXIMUM_BENEFIT']
const PAYERS = ['ANY', 'EMPLOYER', 'EMPLOYEE', 'JOINT', 'EXCLUDE_EMPLOYER']
const AGG_METHODS = ['SUM', 'MAXIMUM', 'WEIGHTED_SUM']
const FCL_BASIS = ['FLAT', 'FORMULA']

const card = {
  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 10, padding: '14px 16px', marginBottom: 16,
}
const mono: React.CSSProperties = { fontFamily: 'var(--font-mono)', fontSize: 11 }

function PageHeader({ onReload }: { onReload: () => void }) {
  return (
    <Card bordered={false} style={{ background: 'transparent', marginBottom: 14, padding: '0 4px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0, color: 'var(--teal-300)' }}>Sum-at-Risk Configuration</Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            SAR pipeline · risk groups · Free Cover Limits · Non-Medical Limits
          </Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={onReload}>Refresh</Button>
      </div>
    </Card>
  )
}

// ─────────────────────────── Benefits ───────────────────────────
function BenefitsTab({ notify }: { notify: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [options, setOptions] = useState<any[]>([])
  const [optionsLoading, setOptionsLoading] = useState(true)
  const [riskGroups, setRiskGroups] = useState<any[]>([])
  const [hist, setHist] = useState<{ code: string; versions: any[] } | null>(null)
  const [histLoading, setHistLoading] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await sarConfigAPI.listBenefits()
      setRows(data || [])
    } catch (e: any) { message.error(e.message) }
    finally { setLoading(false) }
  }

  // Dropdown source = union of products (BASE) + product_benefit_config riders,
  // so a typed code can't create a phantom SAR benefit with no backing product.
  const loadOptions = async () => {
    setOptionsLoading(true)
    try {
      const { data } = await sarConfigAPI.benefitOptions()
      setOptions(data || [])
    } catch (e: any) { message.error(e.message) }
    finally { setOptionsLoading(false) }
  }

  // Risk groups from the Risk Groups tab — the membership picker source.
  const loadRiskGroups = async () => {
    try {
      const { data } = await sarConfigAPI.listRiskGroups()
      setRiskGroups((data || []).filter((g: any) => g.is_active))
    } catch (e: any) { message.error(e.message) }
  }
  useEffect(() => { load(); loadOptions(); loadRiskGroups() }, [])

  const openModal = (r?: any) => {
    setEditing(r || null)
    form.resetFields()
    if (r) form.setFieldsValue(r)
    setOpen(true)
  }

  const save = async () => {
    const v = await form.validateFields()
    try {
      await sarConfigAPI.upsertBenefit(v)
      message.success('Benefit config saved — new version created')
      setOpen(false); setEditing(null); form.resetFields(); load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  // Soft delete via append-versioning: new inactive version supersedes the current one.
  const deactivate = async (r: any) => {
    try {
      await sarConfigAPI.upsertBenefit({ ...r, is_active: false })
      message.success(`Benefit ${r.benefit_code} deactivated — new inactive version created`)
      load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  const showHistory = async (code: string) => {
    setHist({ code, versions: [] })
    setHistLoading(true)
    try {
      const { data } = await sarConfigAPI.benefitVersions(code)
      setHist({ code, versions: data?.versions || [] })
    } catch (e: any) { message.error(e.message) }
    finally { setHistLoading(false) }
  }

  const cols = [
    { title: Titled('Benefit Code', 'benefit_code'), dataIndex: 'benefit_code', render: (v: string) => <span style={mono}>{v}</span> },
    { title: Titled('Ver', 'version'), dataIndex: 'version', width: 60, render: (v: number) => <Tag color="cyan">v{v}</Tag> },
    { title: Titled('Type', 'benefit_type'), dataIndex: 'benefit_type', width: 100, render: (v: string) => <Tag color={v === 'BASE' ? 'geekblue' : 'purple'}>{v}</Tag> },
    { title: Titled('SAR Formula', 'sar_formula'), dataIndex: 'sar_formula', width: 150, render: (v: string) => <span style={mono}>{v || 'FACE_AMOUNT'}</span> },
    { title: Titled('Exposure Group', 'uw_exposure_group'), dataIndex: 'uw_exposure_group', width: 140 },
    { title: Titled('Risk Group', 'risk_group'), dataIndex: 'risk_group', width: 110 },
    { title: Titled('Groups (w%)', 'group_maps'), dataIndex: 'group_maps', width: 180, render: (v: any[]) =>
        <span>{v?.length ? v.map((m: any) =>
          <Tag key={m.risk_group_code} color="geekblue" style={{ marginBottom: 2 }}>{m.risk_group_code} {Number(m.weight_pct)}%</Tag>
        ) : <Tag>—</Tag>}</span> },
    { title: Titled('Payer', 'premium_payer'), dataIndex: 'premium_payer', width: 100 },
    { title: Titled('In SAR', 'include_in_sar'), dataIndex: 'include_in_sar', width: 70, render: (v: boolean) => (v ? <Tag color="green">Yes</Tag> : <Tag>No</Tag>) },
    { title: Titled('Seq', 'processing_sequence'), dataIndex: 'processing_sequence', width: 60 },
    { title: Titled('Active', 'is_active'), dataIndex: 'is_active', width: 70, render: (v: boolean) => (v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>) },
    { title: Titled('Effective', 'effective_date'), dataIndex: 'effective_date', width: 105, render: (v: string) => <span style={mono}>{v || 'today'}</span> },
    { title: 'History', key: 'hist', width: 90, render: (_: any, r: any) =>
        <Button size="small" type="link" onClick={() => showHistory(r.benefit_code)}>History</Button> },
    { title: 'Actions', key: 'act', width: 150, render: (_: any, r: any) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => openModal(r)}>Edit</Button>
          <Popconfirm
            title={`Deactivate benefit ${r.benefit_code}?`}
            description="Creates a new inactive version — the current one stops applying."
            okText="Deactivate" okButtonProps={{ danger: true }}
            onConfirm={() => deactivate(r)}
            disabled={!r.is_active}
          >
            <Button size="small" type="link" danger disabled={!r.is_active}>Deactivate</Button>
          </Popconfirm>
        </Space>
    ) },
  ]

  return (
    <div style={card}>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>New Benefit</Button>
      </Space>
      <Table size="small" rowKey="benefit_code" dataSource={rows} columns={cols} loading={loading} pagination={{ pageSize: 12 }} />
      <Modal title={editing ? `Edit Benefit · ${editing.benefit_code}` : 'New Benefit'} open={open} onOk={save} onCancel={() => { setEditing(null); setOpen(false) }} width={720}>
        <Form form={form} layout="vertical" initialValues={{ benefit_type: 'BASE', risk_type: 'MORTALITY', premium_payer: 'ANY', include_in_sar: true, sar_formula: 'FACE_AMOUNT', processing_sequence: 0, is_active: true }}>
          <Space style={{ width: '100%' }} wrap>
            <Form.Item name="benefit_code" label="Benefit / Product Code" rules={[{ required: true }]}
              tooltip="Pick an existing benefit from Product Config. Free text could create a phantom SAR benefit with no backing product — on edit the code is locked.">
              <Select
                style={{ width: 260 }} showSearch disabled={!!editing} loading={optionsLoading}
                placeholder="Search benefit / product code…" optionFilterProp="children"
                options={options.map(o => ({ value: o.benefit_code, label: `${o.benefit_code} — ${o.product_name ?? o.benefit_code} (${o.benefit_type})` }))}
              />
            </Form.Item>
            <Form.Item name="benefit_type" label="Type"><Select style={{ width: 140 }}>
              {['BASE', 'RIDER_CI', 'RIDER_ADB', 'RIDER_ATPD', 'RIDER_WOP'].map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select></Form.Item>
            <Form.Item name="risk_type" label="Risk Type"><Select style={{ width: 140 }}>
              {['MORTALITY', 'MORBIDITY', 'ACCIDENT', 'HEALTH'].map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select></Form.Item>
            <Form.Item name="uw_exposure_group" label="Exposure Group"><Select allowClear style={{ width: 160 }}>
              {['EMPLOYER_BASE', 'VOLUNTARY_TOPUP', 'INDIVIDUAL', 'FREE_COVER', 'EXCESS_COVER', 'OPTIONAL_RIDER'].map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select></Form.Item>
            <Form.Item name="risk_group" label="Risk Group"><Select allowClear style={{ width: 120 }}>
              {['LIFE', 'HEALTH', 'ACCIDENT'].map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select></Form.Item>
            <Form.Item name="premium_payer" label="Premium Payer"><Select style={{ width: 150 }}>
              {PAYERS.map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select></Form.Item>
            <Form.Item name="sar_formula" label="SAR Formula"><Select style={{ width: 200 }}>
              {SAR_FORMULAS.map(t => <Option key={t} value={t}>{t}</Option>)}
            </Select></Form.Item>
            <Form.Item name="sar_percentage" label="SAR % (PERCENTAGE)"><InputNumber style={{ width: 120 }} /></Form.Item>
            <Form.Item name="processing_sequence" label="Seq"><InputNumber style={{ width: 70 }} /></Form.Item>
            <Form.Item name="include_in_sar" label="Include in SAR" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item name="is_active" label="Active" valuePropName="checked"><Switch /></Form.Item>
          </Space>

          <Divider style={{ margin: '12px 0' }} />
          <Form.Item
            label="Risk Group Memberships"
            style={{ marginBottom: 4 }}
            tooltip="Which Risk Groups this benefit's SAR aggregates into, and the weight per group (0–100). Empty = falls back to the single Risk Group category above. A benefit can belong to several groups (e.g. 60% LIFE / 40% HEALTH)."
          >
            <Form.List name="group_maps">
              {(fields, { add, remove }) => (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {fields.map(({ key, name, ...rest }) => (
                    <Space key={key} align="baseline" wrap>
                      <Form.Item {...rest} name={[name, 'risk_group_code']} rules={[{ required: true, message: 'Pick a risk group' }]} style={{ marginBottom: 0 }}>
                        <Select style={{ width: 220 }} showSearch optionFilterProp="children" placeholder="Risk group"
                          options={(riskGroups || []).map(g => ({ value: g.group_code, label: `${g.group_code} · ${g.aggregation_method}` }))} />
                      </Form.Item>
                      <Form.Item {...rest} name={[name, 'weight_pct']} style={{ marginBottom: 0 }}>
                        <InputNumber style={{ width: 100 }} min={0} max={100} step={5} addonAfter="%" placeholder="Weight" />
                      </Form.Item>
                      <Form.Item {...rest} name={[name, 'priority']} style={{ marginBottom: 0 }}>
                        <InputNumber style={{ width: 70 }} min={1} placeholder="Seq" />
                      </Form.Item>
                      <MinusCircleOutlined onClick={() => remove(name)} style={{ color: 'var(--red-300)' }} />
                    </Space>
                  ))}
                  <Button type="dashed" size="small" icon={<PlusOutlined />} block
                    onClick={() => add({ risk_group_code: riskGroups?.[0]?.group_code, weight_pct: 100, priority: 100 })}>
                    Add risk group
                  </Button>
                </Space>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>
      <Modal title={`Version history — ${hist?.code ?? ''}`} open={!!hist} onCancel={() => setHist(null)} footer={null} width={640}>
        <Table
          size="small" rowKey="version" loading={histLoading}
          dataSource={hist?.versions || []} pagination={false}
          columns={[
            { title: Titled('Version', 'version'), dataIndex: 'version', width: 70, render: (v: number) => <Tag color="cyan">v{v}</Tag> },
            { title: Titled('Current', 'is_current'), dataIndex: 'is_current', width: 85, render: (v: boolean) => (v ? <Tag color="green">current</Tag> : <Tag>superseded</Tag>) },
            { title: Titled('Effective', 'effective_date'), dataIndex: 'effective_date', width: 110, render: (v: string) => <span style={mono}>{v || 'today'}</span> },
            { title: Titled('Expiry', 'expiry_date'), dataIndex: 'expiry_date', width: 110, render: (v: string) => <span style={mono}>{v || '—'}</span> },
            { title: Titled('SAR Formula', 'sar_formula'), dataIndex: 'sar_formula', render: (v: string) => <span style={mono}>{v || 'FACE_AMOUNT'}</span> },
            { title: Titled('Seq', 'processing_sequence'), dataIndex: 'processing_sequence', width: 60 },
            { title: Titled('By', 'updated_by'), dataIndex: 'updated_by', width: 110 },
            { title: Titled('Changed', 'updated_at'), dataIndex: 'updated_at', width: 150, render: (v: string) => <span style={mono}>{v ? v.slice(0, 16) : '—'}</span> },
          ]}
        />
      </Modal>
    </div>
  )
}

// ─────────────────────────── Risk Groups ─────────────────────────
function RiskGroupsTab({ notify }: { notify: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const load = async () => {
    setLoading(true)
    try { const { data } = await sarConfigAPI.listRiskGroups(); setRows(data || []) }
    catch (e: any) { message.error(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  const openModal = (r?: any) => {
    setEditing(r || null)
    form.resetFields()
    if (r) form.setFieldsValue(r)
    setOpen(true)
  }
  const save = async () => {
    try {
      await sarConfigAPI.upsertRiskGroup(await form.validateFields())
      message.success('Risk group saved'); setOpen(false); form.resetFields(); load(); notify()
    } catch (e: any) { message.error(e.message) }
  }
  const inr = (v?: number) => v != null ? '₹' + Number(v).toLocaleString('en-IN') : '—'
  const cols = [
    { title: Titled('Group', 'group_code'), dataIndex: 'group_code', render: (v: string) => <Tag color="cyan" style={mono}>{v}</Tag> },
    { title: Titled('Ver', 'version'), dataIndex: 'version', width: 60, render: (v: number) => <Tag color="cyan">v{v}</Tag> },
    { title: Titled('Name', 'group_name'), dataIndex: 'group_name', render: (v: string, r: any) =>
      <a onClick={() => openModal(r)} style={{ color: 'var(--teal-300)' }}>{v}</a> },
    { title: Titled('Aggregation', 'aggregation_method'), dataIndex: 'aggregation_method', width: 110, render: (v: string) => <span style={mono}>{v}</span> },
    { title: Titled('Auto Refer ≥', 'auto_refer_threshold'), dataIndex: 'auto_refer_threshold', width: 120, render: inr },
    { title: Titled('Senior UW ≥', 'senior_uw_threshold'), dataIndex: 'senior_uw_threshold', width: 120, render: inr },
    { title: Titled('RI Approve ≥', 'ri_approval_threshold'), dataIndex: 'ri_approval_threshold', width: 120, render: inr },
    { title: Titled('Decline ≥', 'decline_threshold'), dataIndex: 'decline_threshold', width: 120, render: inr },
    { title: Titled('Active', 'is_active'), dataIndex: 'is_active', width: 70, render: (v: boolean) => (v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>) },
  ]
  return (
    <div style={card}>
      <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => openModal()}>New Risk Group</Button>
      <Table size="small" rowKey="group_code" dataSource={rows} columns={cols} loading={loading} pagination={false} />
      <Modal title={editing ? `Edit Risk Group · ${editing.group_code}` : 'New Risk Group'} open={open} onOk={save} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ aggregation_method: 'SUM', uw_threshold_basis: 'INDIVIDUAL', include_existing_policies: true, include_pending_proposals: true, is_active: true }}>
          <Form.Item name="group_code" label="Group Code" rules={[{ required: true }]}><Input disabled={!!editing} /></Form.Item>
          <Form.Item name="group_name" label="Group Name" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="aggregation_method" label="Aggregation Method"><Select>{AGG_METHODS.map(t => <Option key={t} value={t}>{t}</Option>)}</Select></Form.Item>
          <Form.Item name="uw_threshold_basis" label="Threshold Basis"><Select>{['INDIVIDUAL', 'SCHEME'].map(t => <Option key={t} value={t}>{t}</Option>)}</Select></Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 12 }}>
            <Form.Item name="auto_refer_threshold" label="Auto Refer ≥"><InputNumber style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="senior_uw_threshold" label="Senior UW ≥"><InputNumber style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="ri_approval_threshold" label="RI Approval ≥"><InputNumber style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="decline_threshold" label="Decline ≥"><InputNumber style={{ width: '100%' }} /></Form.Item>
          </div>
          <Form.Item name="description" label="Description"><Input /></Form.Item>
          <Form.Item name="include_existing_policies" valuePropName="checked" label="Include existing policies"><Switch /></Form.Item>
          <Form.Item name="include_pending_proposals" valuePropName="checked" label="Include pending proposals"><Switch /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ─────────────────────────── Exposure Groups ─────────────────────
function ExposureGroupsTab({ notify }: { notify: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const load = async () => {
    setLoading(true)
    try { const { data } = await sarConfigAPI.listExposureGroups(); setRows(data || []) }
    catch (e: any) { message.error(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  const save = async () => {
    try {
      await sarConfigAPI.upsertExposureGroup(await form.validateFields())
      message.success('Exposure group saved'); setOpen(false); form.resetFields(); load(); notify()
    } catch (e: any) { message.error(e.message) }
  }
  const cols = [
    { title: Titled('Exposure', 'exposure_code'), dataIndex: 'exposure_code', render: (v: string) => <Tag color="geekblue" style={mono}>{v}</Tag> },
    { title: Titled('Name', 'exposure_name'), dataIndex: 'exposure_name' },
    { title: Titled('Description', 'description'), dataIndex: 'description' },
    { title: Titled('Active', 'is_active'), dataIndex: 'is_active', width: 70, render: (v: boolean) => (v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>) },
  ]
  return (
    <div style={card}>
      <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => setOpen(true)}>New Exposure Group</Button>
      <Table size="small" rowKey="exposure_code" dataSource={rows} columns={cols} loading={loading} pagination={false} />
      <Modal title="Exposure Group" open={open} onOk={save} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ is_active: true }}>
          <Form.Item name="exposure_code" label="Exposure Code" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="exposure_name" label="Exposure Name" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="Description"><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ─────────────────────────── Aggregation Rules ────────────────────
// Sentinel value for "blank" (NULL) in the product/exposure dropdowns.
// NULL means the rule applies to ALL products / ALL exposure groups.
const ANY = '__ANY__'

function AggregationTab({ notify }: { notify: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [riskGroups, setRiskGroups] = useState<any[]>([])
  const [exposureOptions, setExposureOptions] = useState<any[]>([])
  const [productOptions, setProductOptions] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { const { data } = await sarConfigAPI.listAggregationRules(); setRows(data || []) }
    catch (e: any) { message.error(e.message) } finally { setLoading(false) }
  }

  // Dropdown sources: risk groups + exposure groups (Risk Groups/Exposure
  // Groups tabs) and active products (Product Config) — no free-text typos.
  const loadDropdowns = async () => {
    try {
      const [rg, eg, pr] = await Promise.all([
        sarConfigAPI.listRiskGroups(),
        sarConfigAPI.listExposureGroups(),
        productsAPI.list(),
      ])
      setRiskGroups((rg.data || []).filter((g: any) => g.is_active))
      setExposureOptions((eg.data || []).filter((e: any) => e.is_active))
      setProductOptions((pr.data || []).filter((p: any) => p.is_active))
    } catch (e: any) { message.error(e.message) }
  }
  useEffect(() => { load(); loadDropdowns() }, [])

  const openModal = (r?: any) => {
    setEditing(r || null)
    form.resetFields()
    if (r) form.setFieldsValue({
      risk_group_code: r.risk_group_code,
      exposure_group: r.exposure_group || ANY,
      product_code: r.product_code || ANY,
      aggregation_method: r.aggregation_method,
      is_active: r.is_active,
    })
    setOpen(true)
  }

  const save = async () => {
    const v = await form.validateFields()
    // Blank → omit so the backend stores NULL (= any product / any exposure).
    if (v.exposure_group === ANY) delete v.exposure_group
    if (v.product_code === ANY) delete v.product_code
    try {
      await sarConfigAPI.createAggregationRule(v)
      message.success(editing ? 'Aggregation rule updated — new version created' : 'Aggregation rule created')
      setOpen(false); setEditing(null); form.resetFields(); load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  // Soft delete: new is_active=false version supersedes the active one.
  const deactivate = async (r: any) => {
    try {
      await sarConfigAPI.createAggregationRule({
        risk_group_code: r.risk_group_code,
        product_code: r.product_code || undefined,
        exposure_group: r.exposure_group || undefined,
        aggregation_method: r.aggregation_method,
        is_active: false,
      })
      message.success('Aggregation rule deactivated — new inactive version created')
      load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  const cols = [
    { title: Titled('Risk Group', 'risk_group_code'), dataIndex: 'risk_group_code', width: 130, render: (v: string) => <Tag color="cyan">{v}</Tag> },
    { title: Titled('Exposure', 'exposure_group'), dataIndex: 'exposure_group', width: 150, render: (v?: string) => v || <Tag>Any</Tag> },
    { title: Titled('Product', 'product_code'), dataIndex: 'product_code', width: 150, render: (v?: string) => v || <Tag>Any</Tag> },
    { title: Titled('Method', 'aggregation_method'), dataIndex: 'aggregation_method', width: 130, render: (v: string) => <span style={mono}>{v}</span> },
    { title: Titled('Active', 'is_active'), dataIndex: 'is_active', width: 70, render: (v: boolean) => (v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>) },
    { title: 'Actions', key: 'act', width: 150, render: (_: any, r: any) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => openModal(r)}>Edit</Button>
          <Popconfirm
            title={`Deactivate this aggregation rule?`}
            description="New inactive version — this (risk group, exposure, product) combination stops applying."
            okText="Deactivate" okButtonProps={{ danger: true }}
            onConfirm={() => deactivate(r)} disabled={!r.is_active}
          >
            <Button size="small" type="link" danger disabled={!r.is_active}>Deactivate</Button>
          </Popconfirm>
        </Space>
    ) },
  ]

  return (
    <div style={card}>
      <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => openModal()}>New Aggregation Rule</Button>
      <Table size="small" rowKey={(r) => r.id} dataSource={rows} columns={cols} loading={loading} pagination={false} />
      <Modal title={editing ? `Edit Aggregation Rule · ${editing.risk_group_code}` : 'New Aggregation Rule'}
        open={open} onOk={save} onCancel={() => { setEditing(null); setOpen(false) }} width={540}>
        <Form form={form} layout="vertical" initialValues={{ aggregation_method: 'SUM', is_active: true }}>
          <Form.Item name="risk_group_code" label="Risk Group" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="children" disabled={!!editing} placeholder="Risk group"
              options={riskGroups.map(g => ({ value: g.group_code, label: `${g.group_code} · ${g.aggregation_method}` }))} />
          </Form.Item>
          <Form.Item name="exposure_group" label="Exposure Group" tooltip="— Any (blank) — applies the rule to every exposure group.">
            <Select showSearch optionFilterProp="children" disabled={!!editing}
              options={[
                { value: ANY, label: '— Any (blank) —' },
                ...exposureOptions.map(e => ({ value: e.exposure_code, label: `${e.exposure_code} · ${e.exposure_name ?? ''}` })),
              ]} />
          </Form.Item>
          <Form.Item name="product_code" label="Product Code" tooltip="— Any (blank) — applies the rule to every product.">
            <Select showSearch optionFilterProp="children" disabled={!!editing}
              options={[
                { value: ANY, label: '— Any (blank) —' },
                ...productOptions.map(p => ({ value: p.product_code, label: `${p.product_code} · ${p.product_name ?? ''}` })),
              ]} />
          </Form.Item>
          <Form.Item name="aggregation_method" label="Aggregation Method"><Select>{AGG_METHODS.map(t => <Option key={t} value={t}>{t}</Option>)}</Select></Form.Item>
          <Form.Item name="is_active" label="Active" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ─────────────────────────── FCL Config ──────────────────────────
function FclTab({ notify }: { notify: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [exposureOptions, setExposureOptions] = useState<any[]>([])
  const [productOptions, setProductOptions] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { const { data } = await sarConfigAPI.listFcl(); setRows(data || []) }
    catch (e: any) { message.error(e.message) } finally { setLoading(false) }
  }

  // Dropdown sources: active products (Product Config) + exposure groups.
  const loadDropdowns = async () => {
    try {
      const [eg, pr] = await Promise.all([sarConfigAPI.listExposureGroups(), productsAPI.list()])
      setExposureOptions((eg.data || []).filter((e: any) => e.is_active))
      setProductOptions((pr.data || []).filter((p: any) => p.is_active))
    } catch (e: any) { message.error(e.message) }
  }
  useEffect(() => { load(); loadDropdowns() }, [])

  const openModal = (r?: any) => {
    setEditing(r || null)
    form.resetFields()
    if (r) form.setFieldsValue({
      product_code: r.product_code,
      scheme_id: r.scheme_id || undefined,
      exposure_group: r.exposure_group || ANY,
      fcl_basis: r.fcl_basis,
      flat_fcl_amount: r.flat_fcl_amount,
      formula_id: r.formula_id,
      apply_fcl_per_benefit: r.apply_fcl_per_benefit,
      premium_payer_filter: r.premium_payer_filter,
      is_active: r.is_active,
      effective_date: r.effective_date ? dayjs(r.effective_date) : null,
      expiry_date: r.expiry_date ? dayjs(r.expiry_date) : null,
    })
    setOpen(true)
  }

  const save = async () => {
    const v = await form.validateFields()
    // Blank exposure → omit so the backend stores NULL (= product-level).
    if (v.exposure_group === ANY) delete v.exposure_group
    const body = {
      ...v,
      effective_date: v.effective_date ? v.effective_date.format('YYYY-MM-DD') : null,
      expiry_date: v.expiry_date ? v.expiry_date.format('YYYY-MM-DD') : null,
    }
    try {
      await sarConfigAPI.upsertFcl(body)
      message.success(editing ? 'FCL rule updated — new version created' : 'FCL rule created')
      setOpen(false); setEditing(null); form.resetFields(); load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  // Soft delete: new is_active=false version supersedes the active one.
  const deactivate = async (r: any) => {
    try {
      await sarConfigAPI.upsertFcl({
        product_code: r.product_code,
        scheme_id: r.scheme_id || undefined,
        exposure_group: r.exposure_group || undefined,
        fcl_basis: r.fcl_basis,
        flat_fcl_amount: r.flat_fcl_amount,
        formula_id: r.formula_id,
        apply_fcl_per_benefit: r.apply_fcl_per_benefit,
        premium_payer_filter: r.premium_payer_filter,
        is_active: false,
      })
      message.success('FCL rule deactivated — new inactive version created')
      load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  const cols = [
    { title: Titled('Product', 'product_code'), dataIndex: 'product_code', width: 130, render: (v: string) => <span style={mono}>{v}</span> },
    { title: Titled('Ver', 'version'), dataIndex: 'version', width: 60, render: (v: number) => <Tag color="cyan">v{v}</Tag> },
    { title: Titled('Scheme', 'scheme_id'), dataIndex: 'scheme_id', width: 90, render: (v?: string) => v || <Tag>Any</Tag> },
    { title: Titled('Exposure', 'exposure_group'), dataIndex: 'exposure_group', width: 130, render: (v?: string) => v || <Tag>Product</Tag> },
    { title: Titled('Basis', 'fcl_basis'), dataIndex: 'fcl_basis', width: 90, render: (v: string) => <Tag color={v === 'FORMULA' ? 'purple' : 'blue'}>{v}</Tag> },
    { title: Titled('Flat FCL', 'flat_fcl_amount'), dataIndex: 'flat_fcl_amount', width: 100, render: (v?: number) => (v != null ? Number(v).toLocaleString('en-IN') : '—') },
    { title: Titled('Effective', 'effective_date'), dataIndex: 'effective_date', width: 105, render: (v?: string) => <span style={mono}>{v || 'today'}</span> },
    { title: Titled('Expires', 'expiry_date'), dataIndex: 'expiry_date', width: 105, render: (v?: string) => <span style={mono}>{v || '—'}</span> },
    { title: Titled('Active', 'is_active'), dataIndex: 'is_active', width: 70, render: (v: boolean) => (v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>) },
    { title: 'Actions', key: 'act', width: 150, render: (_: any, r: any) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => openModal(r)}>Edit</Button>
          <Popconfirm
            title={`Deactivate this FCL rule?`}
            description="New inactive version — the rule stops applying."
            okText="Deactivate" okButtonProps={{ danger: true }}
            onConfirm={() => deactivate(r)} disabled={!r.is_active}
          >
            <Button size="small" type="link" danger disabled={!r.is_active}>Deactivate</Button>
          </Popconfirm>
        </Space>
    ) },
  ]

  return (
    <div style={card}>
      <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => openModal()}>New FCL Rule</Button>
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
        message="FORMULA-based FCLs are built in the Formula Engine tab (formula_type = FCL). Pick the formula from the list, or use FLAT for a fixed Free Cover Limit." />
      <Table size="small" rowKey={(r) => r.id} dataSource={rows} columns={cols} loading={loading} pagination={false} />
      <Modal title={editing ? `Edit FCL Rule · ${editing.product_code}` : 'New FCL Rule'}
        open={open} onOk={save} onCancel={() => { setEditing(null); setOpen(false) }} width={560}>
        <Form form={form} layout="vertical" initialValues={{ fcl_basis: 'FLAT', apply_fcl_per_benefit: false, premium_payer_filter: 'ANY', is_active: true }}>
          <Form.Item name="product_code" label="Product Code" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="children" disabled={!!editing} placeholder="Select product"
              options={productOptions.map(p => ({ value: p.product_code, label: `${p.product_code} · ${p.product_name ?? ''}` }))} />
          </Form.Item>
          <Form.Item name="scheme_id" label="Scheme ID" tooltip="Blank = applies to all schemes."><Input placeholder="Blank = all schemes" /></Form.Item>
          <Form.Item name="exposure_group" label="Exposure Group" tooltip="— Product level (blank) — applies the rule at product level across all exposure groups.">
            <Select showSearch optionFilterProp="children" disabled={!!editing}
              options={[
                { value: ANY, label: '— Product level (blank) —' },
                ...exposureOptions.map(e => ({ value: e.exposure_code, label: `${e.exposure_code} · ${e.exposure_name ?? ''}` })),
              ]} />
          </Form.Item>
          <Form.Item name="fcl_basis" label="Basis"><Select>{FCL_BASIS.map(t => <Option key={t} value={t}>{t}</Option>)}</Select></Form.Item>
          <Form.Item noStyle shouldUpdate={(p, n) => p.fcl_basis !== n.fcl_basis}>
            {({ getFieldValue }) => getFieldValue('fcl_basis') === 'FLAT' ? (
              <Form.Item name="flat_fcl_amount" label="Flat FCL Amount" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item>
            ) : (
              <Form.Item name="formula_id" label="FCL Formula ID (from Formula Engine)" rules={[{ required: true }]}><Input placeholder="Paste formula ID" /></Form.Item>
            )}
          </Form.Item>
          <Space style={{ width: '100%' }} wrap>
            <Form.Item name="premium_payer_filter" label="Premium Payer Filter"><Select style={{ width: 180 }}>{PAYERS.map(t => <Option key={t} value={t}>{t}</Option>)}</Select></Form.Item>
            <Form.Item name="apply_fcl_per_benefit" label="Apply FCL per benefit" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item name="is_active" label="Active" valuePropName="checked"><Switch /></Form.Item>
          </Space>
          <Space style={{ width: '100%' }} wrap>
            <Form.Item name="effective_date" label="Effective From" tooltip="Blank = applies immediately. Future date = scheduled — the previous rule stays active until this takes effect.">
              <DatePicker style={{ width: 200 }} format="DD-MM-YYYY" />
            </Form.Item>
            <Form.Item name="expiry_date" label="Expires On" tooltip="Blank = no end date.">
              <DatePicker style={{ width: 200 }} format="DD-MM-YYYY" />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}

// ─────────────────────────── NML Config ──────────────────────────
function NmlTab({ notify }: { notify: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [productOptions, setProductOptions] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { const { data } = await sarConfigAPI.listNml(); setRows(data || []) }
    catch (e: any) { message.error(e.message) } finally { setLoading(false) }
  }

  // Dropdown source: active products (Product Config) — no free-text typos.
  const loadProducts = async () => {
    try {
      const pr = await productsAPI.list()
      setProductOptions((pr.data || []).filter((p: any) => p.is_active))
    } catch (e: any) { message.error(e.message) }
  }
  useEffect(() => { load(); loadProducts() }, [])

  const openModal = (r?: any) => {
    setEditing(r || null)
    form.resetFields()
    if (r) form.setFieldsValue({
      product_code: r.product_code,
      age_min: r.age_min,
      age_max: r.age_max,
      sar_min: r.sar_min,
      sar_max: r.sar_max,
      nml_category: r.nml_category,
      medical_tests_required: r.medical_tests_required || [],
      reinsurer_approval_required: r.reinsurer_approval_required,
      is_active: r.is_active,
      effective_date: r.effective_date ? dayjs(r.effective_date) : null,
      expiry_date: r.expiry_date ? dayjs(r.expiry_date) : null,
    })
    setOpen(true)
  }

  const save = async () => {
    const v = await form.validateFields()
    const body = {
      ...v,
      effective_date: v.effective_date ? v.effective_date.format('YYYY-MM-DD') : null,
      expiry_date: v.expiry_date ? v.expiry_date.format('YYYY-MM-DD') : null,
    }
    try {
      await sarConfigAPI.upsertNml(body)
      message.success(editing ? 'NML band updated — new version created' : 'NML band created')
      setOpen(false); setEditing(null); form.resetFields(); load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  // Soft delete: new is_active=false version supersedes the active one.
  const deactivate = async (r: any) => {
    try {
      await sarConfigAPI.upsertNml({
        product_code: r.product_code,
        age_min: r.age_min,
        age_max: r.age_max,
        sar_min: r.sar_min,
        sar_max: r.sar_max,
        nml_category: r.nml_category,
        medical_tests_required: r.medical_tests_required || [],
        reinsurer_approval_required: r.reinsurer_approval_required,
        is_active: false,
      })
      message.success('NML band deactivated — new inactive version created')
      load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  const cols = [
    { title: Titled('Product', 'product_code'), dataIndex: 'product_code', width: 130, render: (v: string) => <span style={mono}>{v}</span> },
    { title: Titled('Ver', 'version'), dataIndex: 'version', width: 60, render: (v: number) => <Tag color="cyan">v{v}</Tag> },
    { title: 'Age', width: 100, render: (_: any, r: any) => `${r.age_min ?? '≤'}–${r.age_max ?? '∞'}` },
    { title: 'SAR Band', width: 140, render: (_: any, r: any) => `${(r.sar_min ?? 0).toLocaleString('en-IN')} → ${r.sar_max ? r.sar_max.toLocaleString('en-IN') : '∞'}` },
    { title: Titled('Category', 'nml_category'), dataIndex: 'nml_category', width: 130, render: (v: string) => <Tag color={v === 'NON_MEDICAL' ? 'green' : 'orange'}>{v}</Tag> },
    { title: Titled('Tests', 'medical_tests_required'), dataIndex: 'medical_tests_required', render: (v: string[]) => (v || []).join(', ') || '—' },
    { title: Titled('Effective', 'effective_date'), dataIndex: 'effective_date', width: 105, render: (v?: string) => <span style={mono}>{v || 'today'}</span> },
    { title: Titled('Expires', 'expiry_date'), dataIndex: 'expiry_date', width: 105, render: (v?: string) => <span style={mono}>{v || '—'}</span> },
    { title: Titled('Active', 'is_active'), dataIndex: 'is_active', width: 70, render: (v: boolean) => (v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>) },
    { title: 'Actions', key: 'act', width: 150, render: (_: any, r: any) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => openModal(r)}>Edit</Button>
          <Popconfirm
            title={`Deactivate this NML band?`}
            description="New inactive version — the band stops applying."
            okText="Deactivate" okButtonProps={{ danger: true }}
            onConfirm={() => deactivate(r)} disabled={!r.is_active}
          >
            <Button size="small" type="link" danger disabled={!r.is_active}>Deactivate</Button>
          </Popconfirm>
        </Space>
    ) },
  ]

  return (
    <div style={card}>
      <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => openModal()}>New NML Band</Button>
      <Table size="small" rowKey={(r) => r.id} dataSource={rows} columns={cols} loading={loading} pagination={false} />
      <Modal title={editing ? `Edit NML Band · ${editing.product_code}` : 'New NML Band'}
        open={open} onOk={save} onCancel={() => { setEditing(null); setOpen(false) }} width={560}>
        <Form form={form} layout="vertical" initialValues={{ nml_category: 'NON_MEDICAL', sar_min: 0, medical_tests_required: [], reinsurer_approval_required: false, is_active: true }}>
          <Form.Item name="product_code" label="Product Code" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="children" disabled={!!editing} placeholder="Select product"
              options={productOptions.map(p => ({ value: p.product_code, label: `${p.product_code} · ${p.product_name ?? ''}` }))} />
          </Form.Item>
          <Space wrap>
            <Form.Item name="age_min" label="Age From" tooltip="Locked on edit — changing a band creates a new band."><InputNumber disabled={!!editing} /></Form.Item>
            <Form.Item name="age_max" label="Age To"><InputNumber disabled={!!editing} /></Form.Item>
            <Form.Item name="sar_min" label="SAR Min"><InputNumber disabled={!!editing} style={{ width: 130 }} /></Form.Item>
            <Form.Item name="sar_max" label="SAR Max"><InputNumber disabled={!!editing} style={{ width: 130 }} /></Form.Item>
          </Space>
          <Form.Item name="nml_category" label="Category"><Select>
            {['NON_MEDICAL', 'MEDICAL', 'PARAMEDICAL', 'SPECIAL'].map(t => <Option key={t} value={t}>{t}</Option>)}
          </Select></Form.Item>
          <Form.Item name="medical_tests_required" label="Medical Tests (comma-separated)">
            <Select mode="tags" placeholder="e.g. FULL_MEDICAL, HBA1C, ECG" tokenSeparators={[',']} />
          </Form.Item>
          <Space style={{ width: '100%' }} wrap>
            <Form.Item name="reinsurer_approval_required" label="Reinsurer approval" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item name="is_active" label="Active" valuePropName="checked"><Switch /></Form.Item>
          </Space>
          <Space style={{ width: '100%' }} wrap>
            <Form.Item name="effective_date" label="Effective From" tooltip="Blank = applies immediately. Future date = scheduled — the previous band stays active until this takes effect.">
              <DatePicker style={{ width: 200 }} format="DD-MM-YYYY" />
            </Form.Item>
            <Form.Item name="expiry_date" label="Expires On" tooltip="Blank = no end date.">
              <DatePicker style={{ width: 200 }} format="DD-MM-YYYY" />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}

// ─────────────────────────── RI Retention (Phase 4) ─────────────
function RITab({ notify }: { notify: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [productOptions, setProductOptions] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { const { data } = await sarConfigAPI.listRI(); setRows(data || []) }
    catch (e: any) { message.error(e.message) } finally { setLoading(false) }
  }

  // Dropdown source: active products (Product Config) — no free-text typos.
  const loadProducts = async () => {
    try {
      const pr = await productsAPI.list()
      setProductOptions((pr.data || []).filter((p: any) => p.is_active))
    } catch (e: any) { message.error(e.message) }
  }
  useEffect(() => { load(); loadProducts() }, [])

  const openModal = (r?: any) => {
    setEditing(r || null)
    form.resetFields()
    if (r) form.setFieldsValue({
      reinsurer_code: r.reinsurer_code,
      reinsurer_name: r.reinsurer_name,
      retention_limit: r.retention_limit,
      currency: r.currency,
      product_codes: r.product_codes || [],
      treaty_code: r.treaty_code,
      treaty_type: r.treaty_type,
      contact_name: r.contact_name,
      contact_email: r.contact_email,
      notes: r.notes,
      is_active: r.is_active,
      treaty_effective_date: r.treaty_effective_date ? dayjs(r.treaty_effective_date) : null,
      treaty_expiry_date: r.treaty_expiry_date ? dayjs(r.treaty_expiry_date) : null,
    })
    setOpen(true)
  }

  const save = async () => {
    const v = await form.validateFields()
    const body = {
      ...v,
      treaty_effective_date: v.treaty_effective_date ? v.treaty_effective_date.format('YYYY-MM-DD') : null,
      treaty_expiry_date: v.treaty_expiry_date ? v.treaty_expiry_date.format('YYYY-MM-DD') : null,
    }
    try {
      await sarConfigAPI.upsertRI(body)
      message.success(editing ? 'Reinsurer updated' : 'Reinsurer created')
      setOpen(false); setEditing(null); form.resetFields(); load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  // Deactivate: upsert the full row with is_active=false. RI has no versioning,
  // so a partial upsert would wipe name/retention/etc. — send everything.
  const deactivate = async (r: any) => {
    try {
      await sarConfigAPI.upsertRI({
        reinsurer_code: r.reinsurer_code,
        reinsurer_name: r.reinsurer_name,
        retention_limit: r.retention_limit,
        product_codes: r.product_codes || [],
        treaty_code: r.treaty_code,
        treaty_type: r.treaty_type || 'FACULTATIVE',
        contact_name: r.contact_name,
        contact_email: r.contact_email,
        currency: r.currency || 'INR',
        is_active: false,
        notes: r.notes,
        treaty_effective_date: r.treaty_effective_date || null,
        treaty_expiry_date: r.treaty_expiry_date || null,
      })
      message.success('Reinsurer deactivated')
      load(); notify()
    } catch (e: any) { message.error(e.message) }
  }

  const inr = (v?: number) => v != null ? '₹' + Number(v).toLocaleString('en-IN') : '—'
  const cols = [
    { title: Titled('Code', 'reinsurer_code'), dataIndex: 'reinsurer_code', render: (v: string) => <Tag color="volcano" style={mono}>{v}</Tag> },
    { title: Titled('Name', 'reinsurer_name'), dataIndex: 'reinsurer_name' },
    { title: Titled('Retention Limit', 'retention_limit'), dataIndex: 'retention_limit', width: 130, render: inr },
    { title: Titled('Products', 'product_codes'), dataIndex: 'product_codes', render: (v: string[]) =>
      (v || []).length ? (v || []).map(p => <Tag key={p} style={{ marginRight: 4 }}>{p}</Tag>) : <Tag>All</Tag> },
    { title: Titled('Treaty', 'treaty_code'), dataIndex: 'treaty_code', render: (v?: string) => v ? <span style={mono}>{v}</span> : '—' },
    { title: Titled('Effective', 'treaty_effective_date'), dataIndex: 'treaty_effective_date', width: 105, render: (v?: string) => <span style={mono}>{v || '—'}</span> },
    { title: Titled('Expires', 'treaty_expiry_date'), dataIndex: 'treaty_expiry_date', width: 105, render: (v?: string) => <span style={mono}>{v || '—'}</span> },
    { title: Titled('Active', 'is_active'), dataIndex: 'is_active', width: 70, render: (v: boolean) => (v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>) },
    { title: 'Actions', key: 'act', width: 150, render: (_: any, r: any) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => openModal(r)}>Edit</Button>
          <Popconfirm
            title={`Deactivate ${r.reinsurer_code}?`}
            description="Inactive reinsurers stop appearing as retention options."
            okText="Deactivate" okButtonProps={{ danger: true }}
            onConfirm={() => deactivate(r)} disabled={!r.is_active}
          >
            <Button size="small" type="link" danger disabled={!r.is_active}>Deactivate</Button>
          </Popconfirm>
        </Space>
    ) },
  ]
  return (
    <div style={card}>
      <div style={{ marginBottom: 8 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>New Reinsurer</Button>
        <span style={{ fontSize: 11, color: 'var(--slate-500)', marginLeft: 12 }}>
          Retention limit = net amount at risk (excess SAR after FCL) above which reinsurer approval is required (SAR engine step 10).
        </span>
      </div>
      <Table size="small" rowKey="id" dataSource={rows} columns={cols} loading={loading} pagination={false} />
      <Modal title={editing ? `Edit Reinsurer · ${editing.reinsurer_code}` : 'New Reinsurer'} open={open} onOk={save} onCancel={() => setOpen(false)} width={600} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ treaty_type: 'FACULTATIVE', currency: 'INR', is_active: true }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 12 }}>
            <Form.Item name="reinsurer_code" label="Reinsurer Code" rules={[{ required: true }]}><Input disabled={!!editing} /></Form.Item>
            <Form.Item name="reinsurer_name" label="Reinsurer Name" rules={[{ required: true }]}><Input /></Form.Item>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 12 }}>
            <Form.Item name="retention_limit" label="Retention Limit (INR)"><InputNumber style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="currency" label="Currency"><Input /></Form.Item>
          </div>
          <Form.Item name="product_codes" label="Products — leave empty for all" tooltip="Products this treaty covers. Empty = all products.">
            <Select mode="multiple" showSearch optionFilterProp="children" placeholder="Select products"
              options={productOptions.map(p => ({ value: p.product_code, label: `${p.product_code} · ${p.product_name ?? ''}` }))} />
          </Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 12 }}>
            <Form.Item name="treaty_code" label="Treaty Code"><Input /></Form.Item>
            <Form.Item name="treaty_type" label="Treaty Type"><Input /></Form.Item>
          </div>
          <Space style={{ width: '100%' }} wrap>
            <Form.Item name="treaty_effective_date" label="Effective From" tooltip="Blank = applies immediately.">
              <DatePicker style={{ width: 200 }} format="DD-MM-YYYY" />
            </Form.Item>
            <Form.Item name="treaty_expiry_date" label="Expires On" tooltip="Blank = no end date.">
              <DatePicker style={{ width: 200 }} format="DD-MM-YYYY" />
            </Form.Item>
          </Space>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 12 }}>
            <Form.Item name="contact_name" label="Contact"><Input /></Form.Item>
            <Form.Item name="contact_email" label="Contact Email"><Input /></Form.Item>
          </div>
          <Form.Item name="notes" label="Notes"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="is_active" label="Active" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ─────────────────────────── Page ────────────────────────────────
export default function SarConfigPage() {
  const [tick, setTick] = useState(0)
  // After a save each tab reloads itself; notify is a cross-tab hook for
  // future needs and intentionally does not reset the active tab.
  const notify = () => {}
  const items = [
    { key: 'benefits', label: 'Benefit Master', children: <BenefitsTab notify={notify} /> },
    { key: 'risk-groups', label: 'Risk Groups', children: <RiskGroupsTab notify={notify} /> },
    { key: 'exposure-groups', label: 'Exposure Groups', children: <ExposureGroupsTab notify={notify} /> },
    { key: 'aggregation', label: 'Aggregation', children: <AggregationTab notify={notify} /> },
    { key: 'fcl', label: 'FCL Config', children: <FclTab notify={notify} /> },
    { key: 'nml', label: 'NML Config', children: <NmlTab notify={notify} /> },
    { key: 'ri', label: 'RI Retention', children: <RITab notify={notify} /> },
    { key: 'medical-standards', label: 'Medical Standards', children: <MedicalStandardsPage embedded /> },
  ]
  return (
    <div style={{ padding: 20 }}>
      <PageHeader onReload={() => setTick(t => t + 1)} />
      <Tabs items={items} key={`tabs-${tick}`} destroyInactiveTabPane />
    </div>
  )
}
