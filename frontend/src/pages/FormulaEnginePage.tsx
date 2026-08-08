// ══════════════════════════════════════════════════════════════════════════
// FormulaEnginePage.tsx — System-level Business Formula Engine (V025)
//
// The generalized formula engine: formulas live at tenant level
// (product_code NULL = shared system formula, non-NULL = product override)
// and are keyed by formula_type — PREMIUM / BASE_PREMIUM / SUBSTANDARD_LOADING /
// FLAT_EXTRA / GST / FCL / SAR / MEDICAL / FINANCIAL / DECISION.
//
// FCL formulas (Free Cover Limits) use reference tables for BAND/EXACT
// lookups (age scales, salary multiples, member-count scales, employer tables).
// ══════════════════════════════════════════════════════════════════════════
import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, InputNumber,
  message, Tag, Space, Tabs, Card, Typography, Popconfirm,
} from 'antd'
import { PlusOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons'
import { formulaAPI } from '../api/client'
import { Titled } from '../components/ColHint'

const { Option } = Select

const FORMULA_TYPES = [
  'BASE_PREMIUM', 'SUBSTANDARD_LOADING', 'FLAT_EXTRA', 'GST', 'PREMIUM',
  'FCL', 'SAR', 'MEDICAL', 'FINANCIAL', 'DECISION',
]
const OPERATORS = [
  { value: '+', label: '+ Add' }, { value: '-', label: '− Subtract' },
  { value: '*', label: '× Times' }, { value: '/', label: '÷ Divide' },
  { value: '%', label: '% Percent' },   // running result *= operand/100
  { value: 'IF', label: 'IF (branch)' }, { value: 'ELSE', label: 'ELSE' },
  { value: 'ENDIF', label: 'ENDIF' },
]
const OP_META: Record<string, { label: string; color: string }> = {
  '+': { label: '+ Add',      color: 'blue' },
  '-': { label: '− Subtract', color: 'blue' },
  '*': { label: '× Times',    color: 'green' },
  '/': { label: '÷ Divide',   color: 'green' },
  '%': { label: '% Percent',  color: 'orange' },
  IF:   { label: 'IF',    color: 'volcano' },
  ELSE: { label: 'ELSE',  color: 'purple' },
  ENDIF:{ label: 'ENDIF', color: 'cyan' },
}
const COMPARE_OPS = [
  { value: 'EQ', label: '= equals' }, { value: 'NEQ', label: '≠ not equal' },
  { value: 'GT', label: '> greater' }, { value: 'GTE', label: '≥ greater/equal' },
  { value: 'LT', label: '< less' }, { value: 'LTE', label: '≤ less/equal' },
  { value: 'BETWEEN', label: 'between' },
]
// Condition clause builder constants
const STRUCTURAL_OPS = new Set(['IF', 'ELSE', 'ENDIF'])
const PARAMETER_TYPES = [
  'USER_VALUE', 'USER_LABEL', 'SUM_ASSURED', 'FACE_AMOUNT', 'RATE_SCALE',
  'REFERENCE_TABLE', 'DEBIT_POINTS', 'POLICY_TERM', 'ANNUAL_INCOME',
  'ANNUAL_SALARY', 'SCHEME_MEMBER_COUNT', 'EMPLOYER_CODE',
  'POLICY_RESERVE', 'FUND_VALUE', 'AGE', 'PREVIOUS_RESULT',
]
// Built-in parameters resolved automatically from the applicant/benefit — no
// configuration needed, so the builder shows no extra field for these.
const AUTO_PARAMS = new Set([
  'SUM_ASSURED', 'FACE_AMOUNT', 'DEBIT_POINTS', 'POLICY_TERM', 'ANNUAL_INCOME',
  'ANNUAL_SALARY', 'SCHEME_MEMBER_COUNT', 'POLICY_RESERVE', 'FUND_VALUE',
  'AGE', 'PREVIOUS_RESULT',
])
// Applicant fields a reference table can be keyed on (lookup key options).
const LOOKUP_FIELDS = ['age', 'annual_salary', 'scheme_member_count', 'employer_code',
  'policy_term', 'sum_assured', 'fund_value']

const card = {
  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 10, padding: '14px 16px', marginBottom: 16,
}
const mono: React.CSSProperties = { fontFamily: 'var(--font-mono)', fontSize: 11 }
const TYPE_COLOR: Record<string, string> = {
  BASE_PREMIUM: 'cyan', SUBSTANDARD_LOADING: 'gold', FLAT_EXTRA: 'orange',
  GST: 'purple', PREMIUM: 'blue', FCL: 'green', SAR: 'geekblue',
  MEDICAL: 'red', FINANCIAL: 'magenta', DECISION: 'volcano',
}

// ─────────────────────────── Condition helpers (Phase B) ───────────
const OP_TEXT: Record<string, string> = {
  EQ: '=', NEQ: '≠', GT: '>', GTE: '≥', LT: '<', LTE: '≤',
}
// Render a condition tree as a short human string (for the step table).
function conditionText(c: any): string {
  if (!c || !Array.isArray(c.clauses) || !c.clauses.length) return '—'
  const join = c.logic === 'OR' ? ' OR ' : ' AND '
  const body = c.clauses.map((cl: any) => {
    if (cl.clauses) return `(${conditionText(cl)})`
    if (cl.op === 'BETWEEN') return `${cl.field} ${cl.min}–${cl.max}`
    return `${cl.field} ${OP_TEXT[cl.op] || cl.op} ${cl.value}`
  }).join(join)
  return (c.negate ? 'NOT ' : '') + body
}

function ConditionBuilder({ value, onChange, depth = 0 }: any) {
  const cond: any = value && value.clauses ? value : { logic: 'AND', negate: false, clauses: [] }
  const set = (patch: any) => onChange({ ...cond, ...patch })
  const updateClause = (i: number, patch: any) => {
    const clauses = cond.clauses.map((c: any, j: number) => j === i ? { ...c, ...patch } : c)
    set({ clauses })
  }
  const addClause = () => set({ clauses: [...cond.clauses, { field: 'age', op: 'GTE', value: 40 }] })
  const addNested = () => set({ clauses: [...cond.clauses, { logic: 'OR', negate: false, clauses: [] }] })
  const removeClause = (i: number) => set({ clauses: cond.clauses.filter((_: any, j: number) => j !== i) })

  return (
    <div style={{ border: '1px solid rgba(255,255,255,0.12)', borderRadius: 8, padding: 10, background: 'rgba(255,255,255,0.02)', marginBottom: 8 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <Select size="small" value={cond.logic} style={{ width: 80 }}
          onChange={(v) => set({ logic: v })}>
          <Option value="AND">AND</Option><Option value="OR">OR</Option>
        </Select>
        <Select size="small" value={cond.negate ? 'NOT' : 'NORM'} style={{ width: 70 }}
          onChange={(v) => set({ negate: v === 'NOT' })}>
          <Option value="NORM">normal</Option><Option value="NOT">NOT</Option>
        </Select>
        <span style={{ fontSize: 11, color: 'var(--slate-500)' }}>when <b>all</b> (or any, if OR) clauses hold</span>
      </div>
      {cond.clauses.map((cl: any, i: number) => (
        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
          {cl.clauses ? (
            <>
              <div style={{ flex: 1 }}>
                <ConditionBuilder value={cl} depth={depth + 1}
                  onChange={(v: any) => updateClause(i, { ...v })} />
              </div>
            </>
          ) : (
            <>
              <Select size="small" value={cl.field} style={{ width: 150 }} onChange={(v) => updateClause(i, { field: v })}>
                {LOOKUP_FIELDS.map(k => <Option key={k} value={k}>{k}</Option>)}
              </Select>
              <Select size="small" value={cl.op} style={{ width: 130 }} onChange={(v) => updateClause(i, { op: v })}>
                {COMPARE_OPS.map(o => <Option key={o.value} value={o.value}>{o.label}</Option>)}
              </Select>
              {cl.op === 'BETWEEN' ? (
                <>
                  <InputNumber size="small" style={{ width: 90 }} value={cl.min} placeholder="min"
                    onChange={(v) => updateClause(i, { min: v })} />
                  <InputNumber size="small" style={{ width: 90 }} value={cl.max} placeholder="max"
                    onChange={(v) => updateClause(i, { max: v })} />
                </>
              ) : (
                <Input size="small" style={{ width: 110 }} value={cl.value}
                  onChange={(e) => updateClause(i, { value: e.target.value })} />
              )}
              <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeClause(i)} />
            </>
          )}
        </div>
      ))}
      {depth < 3 && (
        <div style={{ display: 'flex', gap: 8 }}>
          <Button size="small" icon={<PlusOutlined />} onClick={addClause}>Add condition</Button>
          <Button size="small" icon={<PlusOutlined />} onClick={addNested}>Add group (AND/OR)</Button>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────── Step editor modal ─────────────────────
function FormulaModal({ formula, refTables, onClose, onSaved }: any) {
  const [steps, setSteps] = useState<any[]>(formula.steps || [])
  const [userLabels, setUserLabels] = useState<any[]>([])
  const [scales, setScales] = useState<any[]>([])
  const [cond, setCond] = useState<any>(null)
  const [stepForm] = Form.useForm()
  const structuralOp = Form.useWatch('operator', stepForm) || '+'

  // Load user labels for the USER_LABEL dropdown. For a product-scoped formula
  // prefer the labels its formulas already use, but fall back to the full list
  // so a fresh formula can still reference a brand-new label.
  useEffect(() => {
    formulaAPI.listUserLabels(formula.product_code || undefined).then(({ data }: any) => {
      const all = data || []
      if (formula.product_code) {
        const used = all.filter((l: any) => l.used_by_product)
        setUserLabels(used.length ? used : all)
      } else {
        setUserLabels(all)
      }
    }).catch(() => {})
    formulaAPI.listScales().then(({ data }: any) => setScales(data || [])).catch(() => {})
  }, [formula.id])

  const addStep = async () => {
    const v = await stepForm.validateFields()
    if (v.operator === 'IF') {
      // A condition tree is required on IF steps (else the branch never runs).
      if (!cond || !Array.isArray(cond.clauses) || cond.clauses.length === 0) {
        message.warning('Add at least one condition to the IF step')
        return
      }
      v.condition = cond
    }
    try {
      await formulaAPI.addStep(formula.id, v)
      message.success('Step added')
      const { data } = await formulaAPI.get(formula.id)
      setSteps(data.steps || [])
      stepForm.resetFields()
      setCond(null)
    } catch (e: any) { message.error(e.message) }
  }
  const removeStep = async (stepId: string) => {
    try {
      await formulaAPI.removeStep(formula.id, stepId)
      const { data } = await formulaAPI.get(formula.id)
      setSteps(data.steps || [])
    } catch (e: any) { message.error(e.message) }
  }

  const structural = (r: any) => STRUCTURAL_OPS.has(r.operator)
  const stepCols = [
    { title: Titled('Seq', 'seq_no'), dataIndex: 'seq_no', width: 60, render: (v: number) => <span style={mono}>{v}</span> },
    { title: Titled('Op', 'operator'), dataIndex: 'operator', width: 90, render: (v: string) =>
      <Tag color={OP_META[v]?.color}>{OP_META[v]?.label || v}</Tag> },
    { title: Titled('Factor', 'factor'), dataIndex: 'factor', width: 70, render: (v: number, r: any) =>
      structural(r) ? <span style={{ color: 'var(--slate-500)' }}>—</span> : <span style={mono}>{v}</span> },
    { title: Titled('Parameter', 'parameter_type'), dataIndex: 'parameter_type', render: (v: string, r: any) =>
      structural(r) ? <span style={{ color: 'var(--slate-500)', fontSize: 11 }}>—</span> :
      <span style={{ fontSize: 11 }}>
        <Tag color="blue">{v}</Tag>
        {v === 'REFERENCE_TABLE' && r.reference_table_id
          ? <span style={mono}>→ {refTables.find((t: any) => t.id === r.reference_table_id)?.table_code || r.reference_table_id.slice(0, 8)}</span>
          : v === 'USER_VALUE' ? <span style={mono}>= {r.user_value}</span>
            : r.user_label ? <span style={mono}>· {r.user_label}</span> : null}
      </span> },
    { title: Titled('Condition', 'condition'), dataIndex: 'condition', render: (c: any, r: any) =>
      r.operator === 'IF' ? <span style={{ fontSize: 11, color: 'var(--teal-300)', fontFamily: 'var(--font-mono)' }}>{conditionText(c)}</span>
        : <span style={{ color: 'var(--slate-500)' }}>—</span> },
    { title: '', width: 60, render: (_: any, r: any) => (
      <Popconfirm title="Delete step?" onConfirm={() => removeStep(r.id)}>
        <Button size="small" type="text" danger icon={<DeleteOutlined />} />
      </Popconfirm>
    ) },
  ]

  return (
    <Modal open onCancel={onClose} width={720} title={`Formula · ${formula.formula_name}`} destroyOnClose
      footer={[<Button key="done" type="primary" onClick={onClose}>Done</Button>]}>
      <div style={{ marginBottom: 12 }}>
        <Space wrap>
          <Tag color={TYPE_COLOR[formula.formula_type] || 'default'}>{formula.formula_type}</Tag>
          {formula.product_code ? <Tag>Product: {formula.product_code}</Tag> : <Tag color="green">System-wide</Tag>}
          <span style={mono}>{steps.length} steps</span>
        </Space>
      </div>

      <Table size="small" rowKey="id" dataSource={steps} columns={stepCols} pagination={false} style={{ marginBottom: 14 }} />

      {steps.length === 0 && (
        <div style={{ ...card, padding: '8px 12px', marginBottom: 12 }}>
          <span style={{ fontSize: 12, color: 'var(--slate-500)' }}>
            No steps yet — add your first step below. Steps run in <b>Seq</b> order on the running total:
            <span style={mono}> result = result op (factor × value)</span>
          </span>
        </div>
      )}

      <Form form={stepForm} layout="inline" initialValues={{ operator: '+', factor: 1, seq_no: (steps.length + 1) * 10, parameter_type: 'USER_VALUE' }}
        style={{ rowGap: 8, flexWrap: 'wrap' }}>
        <Form.Item name="seq_no" label="Seq"><InputNumber style={{ width: 70 }} /></Form.Item>
        <Form.Item name="operator" label="Op" rules={[{ required: true, message: 'Required' }]}>
          <Select style={{ width: 130 }} onChange={() => setCond(null)}>{OPERATORS.map(o => <Option key={o.value} value={o.value}>{o.label}</Option>)}</Select>
        </Form.Item>
        {structuralOp === 'IF' && (
          <div style={{ width: '100%' }}>
            <div style={{ fontSize: 11, color: 'var(--slate-500)', marginBottom: 6 }}>
              <b>IF</b> the condition below holds, the following steps run — otherwise the <b>ELSE</b> branch (or <b>ENDIF</b>) runs:
            </div>
            <ConditionBuilder value={cond} onChange={setCond} />
          </div>
        )}
        {structuralOp === 'ELSE' && (
          <div style={{ fontSize: 11, color: 'var(--slate-500)', alignSelf: 'center' }}>
            Marks the <b>false branch</b> of the nearest IF. No operand needed.
          </div>
        )}
        {structuralOp === 'ENDIF' && (
          <div style={{ fontSize: 11, color: 'var(--slate-500)', alignSelf: 'center' }}>
            Ends the nearest IF block. The running total continues from here. No operand needed.
          </div>
        )}
        {!STRUCTURAL_OPS.has(structuralOp) && (
          <>
        <Form.Item name="factor" label="Factor"><InputNumber style={{ width: 90 }} /></Form.Item>
        <Form.Item name="parameter_type" label="Parameter" rules={[{ required: true, message: 'Select a parameter' }]}>
          <Select style={{ width: 200 }}>{PARAMETER_TYPES.map(t => <Option key={t} value={t}>{t}</Option>)}</Select>
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(p, n) => p.parameter_type !== n.parameter_type}>
          {({ getFieldValue }) => {
            const pt = getFieldValue('parameter_type')
            if (pt === 'USER_VALUE') return (
              <Form.Item name="user_value" label="Value" rules={[{ required: true, message: 'Value required' }]}>
                <InputNumber />
              </Form.Item>
            )
            if (pt === 'REFERENCE_TABLE') return (
              <>
                <Form.Item name="reference_table_id" label="Ref Table">
                  {refTables.length ? (
                    <Select showSearch style={{ width: 230 }} allowClear placeholder="Select a table" optionFilterProp="label"
                      onChange={(v) => {
                        const t = refTables.find((x: any) => x.id === v)
                        if (t?.key_field) stepForm.setFieldsValue({ user_label: t.key_field })
                      }}>
                      {refTables.map(t => (
                        <Option key={t.id} value={t.id} label={`${t.table_code} · ${t.table_name}`}>
                          <span>{t.table_code}</span> <span style={{ color: '#8b949e', fontSize: 11 }}>· {t.table_name}</span>
                        </Option>
                      ))}
                    </Select>
                  ) : (
                    <span style={{ fontSize: 11, color: 'var(--slate-500)', lineHeight: 2 }}>
                      No reference tables yet — create one in the <b>Reference Tables</b> tab first.
                    </span>
                  )}
                </Form.Item>
                <Form.Item name="user_label" label="Lookup key">
                  <Select showSearch style={{ width: 190 }} allowClear placeholder="Keyed on…" optionFilterProp="label">
                    {LOOKUP_FIELDS.map(k => <Option key={k} value={k} label={k}>{k}</Option>)}
                  </Select>
                </Form.Item>
              </>
            )
            if (pt === 'USER_LABEL') return (
              <Form.Item name="user_label" label="User label">
                {userLabels.length
                  ? <Select showSearch style={{ width: 220 }} placeholder="Select a label" optionFilterProp="label">
                      {userLabels.map(l => (
                        <Option key={l.label_key} value={l.label_key} label={`${l.label_name} (${l.label_key})`}>
                          <span>{l.label_name}</span> <span style={{ color: '#8b949e', fontSize: 11 }}>· {l.label_key}</span>
                        </Option>
                      ))}
                    </Select>
                  : <Input style={{ width: 160 }} placeholder="label_key" />}
              </Form.Item>
            )
            if (pt === 'RATE_SCALE') return (
              <Form.Item name="scale_id" label="Scale" rules={[{ required: true, message: 'Select a scale' }]}>
                <Select showSearch style={{ width: 240 }} placeholder="Select a rate scale" optionFilterProp="label">
                  {scales.map((s: any) => (
                    <Option key={s.id} value={s.id} label={s.name}>
                      {s.name} <span style={{ color: '#8b949e', fontSize: 11 }}>· {s.scale_type}</span>
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            )
            if (pt === 'EMPLOYER_CODE') return (
              <div style={{ fontSize: 11, color: 'var(--slate-500)', alignSelf: 'center', maxWidth: 230 }}>
                ⚠ Employer code isn't a numeric operand — reference it via a <b>REFERENCE_TABLE</b> step (EXACT match) instead.
              </div>
            )
            if (AUTO_PARAMS.has(pt)) return (
              <div style={{ fontSize: 11, color: 'var(--slate-500)', alignSelf: 'center' }}>
                ✓ auto — resolved from the applicant/benefit, no value needed
              </div>
            )
            return <Form.Item name="user_label" label="Label / key"><Input style={{ width: 160 }} /></Form.Item>
          }}
        </Form.Item>
          </>
        )}
        <Form.Item><Button type="primary" icon={<PlusOutlined />} onClick={addStep}>Add Step</Button></Form.Item>
      </Form>
    </Modal>
  )
}

// ─────────────────────────── Formulas tab ──────────────────────────
function FormulasTab({ tick }: { tick: number }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [open, setOpen] = useState(false)
  const [viewing, setViewing] = useState<any>(null)
  const [refTables, setRefTables] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await formulaAPI.list(typeFilter ? { formula_type: typeFilter } : {})
      setRows(data || [])
      const rt = await formulaAPI.listRefTables()
      setRefTables(rt.data || [])
    } catch (e: any) { message.error(e.message) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [tick, typeFilter])

  const create = async () => {
    const v = await form.validateFields()
    try {
      const { data } = await formulaAPI.create(v)
      message.success('Formula created — now add steps')
      setOpen(false); form.resetFields()
      const full = await formulaAPI.get(data.id)   // open step editor immediately
      setViewing(full.data)
    } catch (e: any) { message.error(e.message) }
  }

  const openFormula = async (r: any) => {
    try {
      const { data } = await formulaAPI.get(r.id)
      setViewing(data) // full header + steps
    } catch (e: any) { message.error(e.message) }
  }

  const cols = [
    { title: Titled('Name', 'formula_name'), dataIndex: 'formula_name', render: (v: string, r: any) =>
      <a onClick={() => openFormula(r)} style={{ color: 'var(--teal-300)' }}>{v}</a> },
    { title: Titled('Type', 'formula_type'), dataIndex: 'formula_type', width: 170, render: (v: string) => <Tag color={TYPE_COLOR[v] || 'default'}>{v}</Tag> },
    { title: Titled('Scope', 'product_code'), dataIndex: 'product_code', width: 120, render: (v?: string) => v ? <Tag>{v}</Tag> : <Tag color="green">System</Tag> },
    { title: Titled('Steps', 'step_count'), dataIndex: 'step_count', width: 70, render: (v: number) => <span style={mono}>{v ?? 0}</span> },
    { title: Titled('Active', 'is_active'), dataIndex: 'is_active', width: 80, render: (v: boolean) => (v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>) },
  ]

  return (
    <div style={card}>
      <Space style={{ marginBottom: 12 }} wrap>
        <Select value={typeFilter} placeholder="Filter by formula type" allowClear style={{ width: 220 }}
          onChange={setTypeFilter}>
          {FORMULA_TYPES.map(t => <Option key={t} value={t}>{t}</Option>)}
        </Select>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>New Formula</Button>
      </Space>
      <Table size="small" rowKey="id" dataSource={rows} columns={cols} loading={loading} pagination={{ pageSize: 12 }} />

      <Modal title="New Formula" open={open} onOk={create} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ formula_type: 'FCL', is_active: true }}>
          <Form.Item name="formula_name" label="Formula Name" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="formula_type" label="Formula Type" rules={[{ required: true }]}>
            <Select>{FORMULA_TYPES.map(t => <Option key={t} value={t}>{t}</Option>)}</Select>
          </Form.Item>
          <Form.Item name="product_code" label="Product Code (blank = system-wide)">
            <Input placeholder="Leave blank for a shared system formula" />
          </Form.Item>
          <Form.Item name="description" label="Description"><Input /></Form.Item>
        </Form>
      </Modal>

      {viewing && (
        <FormulaModal formula={viewing} refTables={refTables}
          onClose={() => { setViewing(null); load() }}
          onSaved={() => load()} />
      )}
    </div>
  )
}

// ─────────────────────────── Reference tables tab ──────────────────
function RefTablesTab({ tick }: { tick: number }) {
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [viewing, setViewing] = useState<any>(null)
  const [form] = Form.useForm()
  const [rowForm] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { const { data } = await formulaAPI.listRefTables(); setRows(data || []) }
    catch (e: any) { message.error(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [tick])

  const create = async () => {
    try {
      await formulaAPI.createRefTable(await form.validateFields())
      message.success('Reference table created'); setOpen(false); form.resetFields(); load()
    } catch (e: any) { message.error(e.message) }
  }
  const openViewer = async (id: string) => {
    try { const { data } = await formulaAPI.getRefTable(id); setViewing(data) }
    catch (e: any) { message.error(e.message) }
  }
  const addRow = async () => {
    const v = await rowForm.validateFields()
    try {
      await formulaAPI.addRefRow(viewing.id, v)
      message.success('Row added')
      const { data } = await formulaAPI.getRefTable(viewing.id); setViewing(data)
      rowForm.resetFields()
    } catch (e: any) { message.error(e.message) }
  }
  const removeRow = async (rowId: string) => {
    try {
      await formulaAPI.removeRefRow(viewing.id, rowId)
      const { data } = await formulaAPI.getRefTable(viewing.id); setViewing(data)
    } catch (e: any) { message.error(e.message) }
  }

  const cols = [
    { title: Titled('Code', 'table_code'), dataIndex: 'table_code', render: (v: string) => <span style={mono}>{v}</span> },
    { title: Titled('Name', 'table_name'), dataIndex: 'table_name', render: (v: string, r: any) =>
      <a onClick={() => openViewer(r.id)} style={{ color: 'var(--teal-300)' }}>{v}</a> },
    { title: Titled('Key', 'key_field'), dataIndex: 'key_field', width: 130, render: (v?: string) =>
      v ? <Tag color="purple" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{v}</Tag> : <span style={{ color: '#8b949e' }}>—</span> },
    { title: Titled('Rows', 'row_count'), dataIndex: 'row_count', width: 70, render: (v: number) => <span style={mono}>{v ?? 0}</span> },
  ]

  return (
    <div style={card}>
      <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => setOpen(true)}>New Reference Table</Button>
      <Table size="small" rowKey="id" dataSource={rows} columns={cols} loading={loading} pagination={false} />

      <Modal title="New Reference Table" open={open} onOk={create} onCancel={() => setOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ is_active: true }}>
          <Form.Item name="table_code" label="Table Code (e.g. FCL_MEMBER_COUNT_SCALE)" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="table_name" label="Table Name" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="key_field" label="Key field — applicant input this table is looked up by">
            <Select showSearch allowClear placeholder="e.g. age, annual_salary, employer_code" optionFilterProp="label">
              {LOOKUP_FIELDS.map(k => <Option key={k} value={k} label={k}>{k}</Option>)}
            </Select>
          </Form.Item>
          <Form.Item name="description" label="Description"><Input /></Form.Item>
        </Form>
      </Modal>

      {viewing && (
        <Modal open onCancel={() => setViewing(null)} footer={null} width={700}
          title={`Reference Table · ${viewing.table_code}`} destroyOnClose>
          <Table size="small" rowKey="id" dataSource={viewing.rows || []} pagination={{ pageSize: 8 }}
            columns={[
              { title: Titled('Match', 'match_type'), dataIndex: 'match_type', width: 80, render: (v: string) => <Tag color={v === 'BAND' ? 'blue' : 'purple'}>{v}</Tag> },
              { title: Titled('From', 'band_min'), dataIndex: 'band_min', width: 90, render: (v?: number) => v ?? '—' },
              { title: Titled('To', 'band_max'), dataIndex: 'band_max', width: 90, render: (v?: number) => v ?? '∞' },
              { title: Titled('Match Value', 'match_value'), dataIndex: 'match_value', width: 120, render: (v?: string) => v || '—' },
              { title: Titled('Output', 'output_value'), dataIndex: 'output_value', render: (v: number) => <span style={mono}>{v.toLocaleString('en-IN')}</span> },
              { title: '', width: 50, render: (_: any, r: any) => (
                <Popconfirm title="Delete row?" onConfirm={() => removeRow(r.id)}>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ) },
            ]} />
          <Form form={rowForm} layout="inline" initialValues={{ match_type: 'BAND', output_value: 0 }}
            style={{ marginTop: 14, rowGap: 8, flexWrap: 'wrap' }}>
            <Form.Item name="match_type" label="Match"><Select style={{ width: 110 }}>
              <Option value="BAND">BAND</Option><Option value="EXACT">EXACT</Option>
            </Select></Form.Item>
            <Form.Item noStyle shouldUpdate={(p, n) => p.match_type !== n.match_type}>
              {({ getFieldValue }) => getFieldValue('match_type') === 'BAND' ? (
                <>
                  <Form.Item name="band_min" label="From"><InputNumber /></Form.Item>
                  <Form.Item name="band_max" label="To"><InputNumber placeholder="∞" /></Form.Item>
                </>
              ) : (
                <Form.Item name="match_value" label="Exact value"><Input style={{ width: 150 }} /></Form.Item>
              )}
            </Form.Item>
            <Form.Item name="output_value" label="Output"><InputNumber /></Form.Item>
            <Form.Item name="sort_order" label="Order" initialValue={0}><InputNumber /></Form.Item>
            <Form.Item><Button type="primary" icon={<PlusOutlined />} onClick={addRow}>Add Row</Button></Form.Item>
          </Form>
        </Modal>
      )}
    </div>
  )
}

// ─────────────────────────── Page ──────────────────────────────────
export default function FormulaEnginePage() {
  const [tick, setTick] = useState(0)
  const items = [
    { key: 'formulas', label: 'Formulas', children: <FormulasTab tick={tick} /> },
    { key: 'ref-tables', label: 'Reference Tables', children: <RefTablesTab tick={tick} /> },
  ]
  return (
    <div style={{ padding: 20 }}>
      <Card bordered={false} style={{ background: 'transparent', marginBottom: 14, padding: '0 4px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Typography.Title level={4} style={{ margin: 0, color: 'var(--teal-300)' }}>Formula Engine</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              System-level Business Formula Engine · premium / FCL / SAR · reference tables
            </Typography.Text>
          </div>
          <Button icon={<ReloadOutlined />} onClick={() => setTick(t => t + 1)}>Refresh</Button>
        </div>
      </Card>
      <Tabs items={items} />
    </div>
  )
}
