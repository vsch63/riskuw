import { useState, useEffect, useCallback, useRef } from "react"
import {
  Table, Button, Modal, Form, Input, Select, Switch,
  DatePicker, Popconfirm, message, Tag, Space, Tabs,
  Tooltip, InputNumber, Upload, Radio, Alert,
  Descriptions, Timeline, Progress
} from "antd"
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  SearchOutlined, UserOutlined, HistoryOutlined,
  MailOutlined, PhoneOutlined, UploadOutlined,
  DownloadOutlined, InboxOutlined, FileTextOutlined,
  CheckCircleOutlined, ExclamationCircleOutlined
} from "@ant-design/icons"
import { api } from "../api/client"
import dayjs from "dayjs"

const { Option } = Select
const { Dragger } = Upload

// ── Types ─────────────────────────────────────────────────────────────────────
interface Member {
  id: number
  applicant_ref: string
  salutation: string | null
  full_name: string
  email: string | null
  phone: string | null
  mobile: string | null
  dob: string | null
  gender: string | null
  city: string | null
  state: string | null
  pincode: string | null
  address_line1: string | null
  address_line2: string | null
  country: string | null
  pan_number: string | null
  occupation: string | null
  annual_income: number | null
  nominee_name: string | null
  nominee_relation: string | null
  group_name: string | null
  employee_id: string | null
  department: string | null
  is_active: boolean
  outcome?: string
  approved_premium?: number
  product_code?: string
}

interface UploadLog {
  upload_ref: string
  filename: string
  total_rows: number
  inserted: number
  updated: number
  skipped: number
  errors: number
  uploaded_by: string
  uploaded_at: string
  notes: string | null
}

interface UWHistory {
  outcome: string
  risk_class: string
  net_debit_points: number
  approved_premium: number | null
  product_code: string
  face_amount: number
  created_at: string
}

const OUTCOME_COLOR: Record<string, string> = {
  APPROVED_STP: "green", APPROVED_RATED: "cyan",
  REFERRED: "orange", DECLINED: "red", POSTPONED: "volcano",
}

const fmt = (n: number | null | undefined) =>
  n != null ? `₹${n.toLocaleString("en-IN")}` : "—"

const card: React.CSSProperties = {
  background: "rgba(255,255,255,0.02)",
  border: "1px solid rgba(255,255,255,0.07)",
  borderRadius: 10, padding: "20px 24px", marginBottom: 16,
}

// ── UW History Modal ──────────────────────────────────────────────────────────
function UWHistoryModal({ applicantRef, open, onClose }: {
  applicantRef: string; open: boolean; onClose: () => void
}) {
  const [history, setHistory] = useState<UWHistory[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !applicantRef) return
    setLoading(true)
    api.get(`/members/${applicantRef}/uw-history`)
      .then(r => setHistory(r.data))
      .catch(() => message.error("Failed to load UW history"))
      .finally(() => setLoading(false))
  }, [open, applicantRef])

  return (
    <Modal title={<span>📋 UW History — {applicantRef}</span>}
      open={open} onCancel={onClose} footer={null} width={560}>
      {loading ? <div style={{ padding: 40, textAlign: "center" }}>Loading...</div>
        : history.length === 0
          ? <div style={{ padding: 40, textAlign: "center", color: "#6b7280" }}>
              No UW decisions found for this member
            </div>
          : <Timeline items={history.map(h => ({
              color: OUTCOME_COLOR[h.outcome] || "gray",
              children: (
                <div style={{ marginBottom: 4 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <Tag color={OUTCOME_COLOR[h.outcome] || "default"}>
                      {h.outcome.replace(/_/g, " ")}
                    </Tag>
                    <span style={{ fontSize: 11, color: "#6b7280" }}>
                      {h.created_at?.slice(0, 10)}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, marginTop: 4, color: "#9ca3af" }}>
                    {h.product_code} · SA: {fmt(h.face_amount)} ·
                    Debit: {h.net_debit_points} pts ·
                    Premium: {fmt(h.approved_premium)}
                  </div>
                </div>
              )
            }))} />
      }
    </Modal>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1 — Upload Members
// ══════════════════════════════════════════════════════════════════════════════
function UploadTab() {
  const [file, setFile]           = useState<File | null>(null)
  const [onConflict, setOnConflict] = useState("update")
  const [notes, setNotes]         = useState("")
  const [uploading, setUploading] = useState(false)
  const [result, setResult]       = useState<any>(null)

  const REQUIRED_COLS = [
    { col: "applicant_ref",  note: "Must match existing cases" },
    { col: "full_name",      note: "" },
    { col: "email",          note: "Used for decision letters" },
    { col: "phone",          note: "" },
    { col: "mobile",         note: "Optional" },
    { col: "dob",            note: "YYYY-MM-DD" },
    { col: "gender",         note: "M / F" },
    { col: "address_line1",  note: "" },
    { col: "address_line2",  note: "Optional" },
    { col: "city",           note: "" },
    { col: "state",          note: "State name" },
    { col: "pincode",        note: "" },
    { col: "country",        note: "Default: India" },
    { col: "group_name",     note: "Optional" },
    { col: "employee_id",    note: "Optional" },
    { col: "department",     note: "Optional" },
    { col: "nominee_name",   note: "Optional" },
    { col: "nominee_relation", note: "Optional" },
  ]

  const downloadTemplate = () => {
    const header = REQUIRED_COLS.map(c => c.col).join(",")
    const sample = "APP-001,John Doe,john@email.com,9876543210,9876543210,1990-01-15,M,123 MG Road,,Bengaluru,Karnataka,560001,India,ABC Corp,EMP001,IT,Jane Doe,Spouse"
    const blob = new Blob([header + "\n" + sample], { type: "text/csv" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a"); a.href = url
    a.download = "member_upload_template.csv"; a.click()
    URL.revokeObjectURL(url)
  }

  const handleUpload = async () => {
    if (!file) { message.warning("Please select a file"); return }
    setUploading(true)
    setResult(null)
    try {
      const fd = new FormData()
      fd.append("file", file)
      fd.append("on_conflict", onConflict)
      fd.append("notes", notes)
      const res = await api.post("/members/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" }
      })
      setResult(res.data)
      message.success(`Upload complete — ${res.data.inserted} inserted, ${res.data.updated} updated`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || "Upload failed")
    } finally { setUploading(false) }
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 400px", gap: 24 }}>
      {/* Left — upload form */}
      <div>
        <div style={card}>
          <div style={{ fontWeight: 600, marginBottom: 16, color: "#e2e8f0" }}>
            Upload file
          </div>
          <Dragger
            accept=".csv,.xlsx,.xls"
            beforeUpload={f => { setFile(f); return false }}
            onRemove={() => setFile(null)}
            maxCount={1}
            style={{ marginBottom: 16 }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined style={{ color: "#00d4aa" }} />
            </p>
            <p style={{ color: "#e2e8f0" }}>Drag and drop file here</p>
            <p style={{ color: "#6b7280", fontSize: 12 }}>
              Limit 200MB per file · CSV, XLSX, XLS
            </p>
          </Dragger>

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 13, color: "#9ca3af", marginBottom: 8 }}>
              If applicant_ref already exists:
            </div>
            <Radio.Group value={onConflict} onChange={e => setOnConflict(e.target.value)}>
              <Radio value="update">Update existing record</Radio>
              <Radio value="skip">Skip (keep existing)</Radio>
            </Radio.Group>
          </div>

          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, color: "#9ca3af", marginBottom: 6 }}>
              Upload notes
            </div>
            <Input
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="e.g. March 2026 new business batch"
            />
          </div>

          <Button
            type="primary" block size="large"
            icon={<UploadOutlined />}
            loading={uploading} onClick={handleUpload}
          >
            Upload Members
          </Button>
        </div>

        {/* Result */}
        {result && (
          <div style={{ ...card, borderColor: "rgba(0,212,170,0.3)" }}>
            <div style={{ fontWeight: 600, color: "#00d4aa", marginBottom: 12 }}>
              ✅ Upload Complete — {result.upload_ref}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8 }}>
              {[
                { label: "Total Rows", val: result.total_rows, color: "#e2e8f0" },
                { label: "Inserted",   val: result.inserted,   color: "#34d399" },
                { label: "Updated",    val: result.updated,    color: "#60a5fa" },
                { label: "Errors",     val: result.errors,     color: result.errors > 0 ? "#f87171" : "#6b7280" },
              ].map(r => (
                <div key={r.label} style={{ textAlign: "center",
                  background: "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 4px" }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color: r.color }}>{r.val}</div>
                  <div style={{ fontSize: 11, color: "#6b7280" }}>{r.label}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right — required columns */}
      <div style={card}>
        <div style={{ fontWeight: 600, marginBottom: 12, color: "#e2e8f0" }}>
          Required columns
        </div>
        <Table
          dataSource={REQUIRED_COLS}
          rowKey="col"
          size="small"
          pagination={false}
          columns={[
            { title: "Column", dataIndex: "col",
              render: v => <code style={{ color: "#34d399", fontSize: 11 }}>{v}</code> },
            { title: "Notes", dataIndex: "note",
              render: v => <span style={{ color: "#9ca3af", fontSize: 11 }}>{v}</span> },
          ]}
        />
        <Button
          block style={{ marginTop: 12 }}
          icon={<DownloadOutlined />}
          onClick={downloadTemplate}
        >
          Download template CSV
        </Button>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2 — Search & Edit
// ══════════════════════════════════════════════════════════════════════════════
function SearchTab() {
  const [data, setData]       = useState<Member[]>([])
  const [total, setTotal]     = useState(0)
  const [page, setPage]       = useState(1)
  const [loading, setLoading] = useState(false)
  const [search, setSearch]   = useState("")
  const [activeOnly, setActiveOnly] = useState(false)
  const [open, setOpen]       = useState(false)
  const [editing, setEditing] = useState<Member | null>(null)
  const [saving, setSaving]   = useState(false)
  const [histRef, setHistRef] = useState<string | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: String(page), page_size: "20",
        ...(search     ? { search }              : {}),
        ...(activeOnly ? { active_only: "true" } : {}),
      })
      const res = await api.get(`/members?${params}`)
      setData(res.data.items)
      setTotal(res.data.total)
    } catch { message.error("Failed to load members") }
    finally { setLoading(false) }
  }, [page, search, activeOnly])

  useEffect(() => { load() }, [load])

  const openAdd = () => {
    setEditing(null); form.resetFields()
    form.setFieldsValue({ is_active: true, country: "India" })
    setOpen(true)
  }

  const openEdit = (row: Member) => {
    setEditing(row)
    form.setFieldsValue({
      ...row,
      dob:         row.dob ? dayjs(row.dob) : null,
    })
    setOpen(true)
  }

  const handleSave = async () => {
    try {
      const vals = await form.validateFields()
      setSaving(true)
      const body = { ...vals, dob: vals.dob?.format("YYYY-MM-DD") || null }
      if (editing) {
        await api.put(`/members/${editing.applicant_ref}`, body)
        message.success("Member updated")
      } else {
        await api.post("/members", body)
        message.success("Member added")
      }
      setOpen(false); load()
    } catch (e: any) {
      if (e?.response?.status === 409) message.error(e.response.data.detail)
      else if (!e?.errorFields) message.error("Save failed")
    } finally { setSaving(false) }
  }

  const handleDelete = async (ref: string) => {
    try {
      await api.delete(`/members/${ref}`)
      message.success("Deleted"); load()
    } catch { message.error("Delete failed") }
  }

  const columns = [
    {
      title: "Member", width: 200,
      render: (_: any, row: Member) => (
        <div>
          <div style={{ fontWeight: 600, color: "#e2e8f0" }}>
            {row.salutation ? `${row.salutation} ` : ""}{row.full_name}
          </div>
          <div style={{ fontSize: 11, color: "#6b7280" }}>{row.applicant_ref}</div>
          {row.employee_id &&
            <div style={{ fontSize: 11, color: "#4b5563" }}>EMP: {row.employee_id}</div>}
        </div>
      )
    },
    {
      title: "Contact", width: 190,
      render: (_: any, row: Member) => (
        <div style={{ fontSize: 12 }}>
          {row.email && <div><MailOutlined style={{ marginRight: 4, color: "#6b7280" }} />{row.email}</div>}
          {(row.mobile || row.phone) &&
            <div><PhoneOutlined style={{ marginRight: 4, color: "#6b7280" }} />{row.mobile || row.phone}</div>}
        </div>
      )
    },
    {
      title: "Group", width: 140,
      render: (_: any, row: Member) => (
        <div style={{ fontSize: 12 }}>
          {row.group_name && <div style={{ color: "#e2e8f0" }}>{row.group_name}</div>}
          {row.department  && <div style={{ color: "#6b7280" }}>{row.department}</div>}
        </div>
      )
    },
    {
      title: "Location", width: 120,
      render: (_: any, row: Member) =>
        <div style={{ fontSize: 12 }}>
          {[row.city, row.state].filter(Boolean).join(", ") || "—"}
        </div>
    },
    {
      title: "Last Decision", width: 140,
      render: (_: any, row: Member) => row.outcome
        ? <div>
            <Tag color={OUTCOME_COLOR[row.outcome] || "default"} style={{ fontSize: 11 }}>
              {row.outcome.replace(/_/g, " ")}
            </Tag>
            {row.approved_premium &&
              <div style={{ fontSize: 11, color: "#34d399", marginTop: 2 }}>
                {fmt(row.approved_premium)}
              </div>}
          </div>
        : <span style={{ color: "#4b5563", fontSize: 12 }}>No decision</span>
    },
    {
      title: "Status", width: 80,
      render: (_: any, row: Member) =>
        <Tag color={row.is_active ? "green" : "default"}>
          {row.is_active ? "Active" : "Inactive"}
        </Tag>
    },
    {
      title: "Actions", width: 110,
      render: (_: any, row: Member) => (
        <Space>
          <Tooltip title="UW History">
            <Button size="small" icon={<HistoryOutlined />}
              onClick={() => setHistRef(row.applicant_ref)} />
          </Tooltip>
          <Tooltip title="Edit">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} />
          </Tooltip>
          <Popconfirm title="Delete member?" onConfirm={() => handleDelete(row.applicant_ref)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    }
  ]

  return (
    <>
      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        <Input
          placeholder="Search name, ref, email, PAN, employee ID..."
          prefix={<SearchOutlined style={{ color: "#6b7280" }} />}
          value={search} onChange={e => { setSearch(e.target.value); setPage(1) }}
          style={{ flex: 1, maxWidth: 420 }} allowClear
        />
        <Button size="small" type={activeOnly ? "primary" : "default"}
          onClick={() => { setActiveOnly(!activeOnly); setPage(1) }}>
          Active Only
        </Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
          Add Member
        </Button>
      </div>

      <Table rowKey="id" dataSource={data} columns={columns}
        loading={loading} size="small"
        pagination={{ total, current: page, pageSize: 20,
          showTotal: t => `${t} members`, onChange: p => setPage(p) }}
      />

      <UWHistoryModal applicantRef={histRef || ""} open={!!histRef}
        onClose={() => setHistRef(null)} />

      <Modal title={editing ? `Edit — ${editing.full_name}` : "Add Member"}
        open={open} onOk={handleSave} onCancel={() => setOpen(false)}
        okText="Save" confirmLoading={saving} width={680}>
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Tabs size="small" items={[
            {
              key: "personal", label: "👤 Personal",
              children: (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: "80px 1fr 1fr", gap: 12 }}>
                    <Form.Item name="salutation" label="Title">
                      <Select allowClear>
                        {["Mr","Ms","Mrs","Dr","Prof"].map(s =>
                          <Option key={s} value={s}>{s}</Option>)}
                      </Select>
                    </Form.Item>
                    <Form.Item name="full_name" label="Full Name"
                      rules={[{ required: true, message: "Required" }]}>
                      <Input />
                    </Form.Item>
                    <Form.Item name="applicant_ref" label="Applicant Ref"
                      rules={[{ required: true, message: "Required" }]}>
                      <Input disabled={!!editing} />
                    </Form.Item>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                    <Form.Item name="dob" label="Date of Birth">
                      <DatePicker style={{ width: "100%" }} format="DD-MM-YYYY" />
                    </Form.Item>
                    <Form.Item name="gender" label="Gender">
                      <Select allowClear>
                        <Option value="M">Male</Option>
                        <Option value="F">Female</Option>
                        <Option value="O">Other</Option>
                      </Select>
                    </Form.Item>
                    <Form.Item name="pan_number" label="PAN Number">
                      <Input placeholder="ABCDE1234F" />
                    </Form.Item>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <Form.Item name="occupation" label="Occupation">
                      <Input />
                    </Form.Item>
                    <Form.Item name="annual_income" label="Annual Income (₹)">
                      <InputNumber style={{ width: "100%" }} min={0} step={10000} />
                    </Form.Item>
                  </div>
                  <Form.Item name="is_active" label="Active" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </>
              )
            },
            {
              key: "contact", label: "📞 Contact",
              children: (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <Form.Item name="email" label="Email">
                      <Input prefix={<MailOutlined />} />
                    </Form.Item>
                    <Form.Item name="mobile" label="Mobile">
                      <Input prefix={<PhoneOutlined />} />
                    </Form.Item>
                    <Form.Item name="phone" label="Alternate Phone">
                      <Input />
                    </Form.Item>
                  </div>
                  <Form.Item name="address_line1" label="Address Line 1"><Input /></Form.Item>
                  <Form.Item name="address_line2" label="Address Line 2"><Input /></Form.Item>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 12 }}>
                    <Form.Item name="city"    label="City">   <Input /></Form.Item>
                    <Form.Item name="state"   label="State">  <Input /></Form.Item>
                    <Form.Item name="pincode" label="Pincode"><Input /></Form.Item>
                    <Form.Item name="country" label="Country"><Input /></Form.Item>
                  </div>
                </>
              )
            },
            {
              key: "group", label: "🏢 Group",
              children: (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <Form.Item name="group_name"  label="Group / Employer"><Input /></Form.Item>
                  <Form.Item name="employee_id" label="Employee ID">     <Input /></Form.Item>
                  <Form.Item name="department"  label="Department">      <Input /></Form.Item>
                </div>
              )
            },
            {
              key: "nominee", label: "👨‍👩‍👧 Nominee",
              children: (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <Form.Item name="nominee_name" label="Nominee Name"><Input /></Form.Item>
                  <Form.Item name="nominee_relation" label="Relationship">
                    <Select allowClear>
                      {["Spouse","Son","Daughter","Father","Mother","Brother","Sister","Other"]
                        .map(r => <Option key={r} value={r}>{r}</Option>)}
                    </Select>
                  </Form.Item>
                </div>
              )
            },
          ]} />
        </Form>
      </Modal>
    </>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3 — Upload History
// ══════════════════════════════════════════════════════════════════════════════
function HistoryTab() {
  const [data, setData]       = useState<UploadLog[]>([])
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.get("/members/upload-history")
      setData(res.data)
    } catch { message.error("Failed to load history") }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const columns = [
    { title: "Ref",      dataIndex: "upload_ref", width: 100,
      render: (v: string) => <code style={{ color: "#00d4aa" }}>{v}</code> },
    { title: "Filename", dataIndex: "filename",   width: 200 },
    { title: "Total",    dataIndex: "total_rows", width: 70,  align: "center" as const },
    { title: "Inserted", dataIndex: "inserted",   width: 80,  align: "center" as const,
      render: (v: number) => <span style={{ color: "#34d399", fontWeight: 600 }}>{v}</span> },
    { title: "Updated",  dataIndex: "updated",    width: 80,  align: "center" as const,
      render: (v: number) => <span style={{ color: "#60a5fa", fontWeight: 600 }}>{v}</span> },
    { title: "Skipped",  dataIndex: "skipped",    width: 80,  align: "center" as const },
    { title: "Errors",   dataIndex: "errors",     width: 70,  align: "center" as const,
      render: (v: number) => <span style={{ color: v > 0 ? "#f87171" : "#6b7280" }}>{v}</span> },
    { title: "Uploaded By", dataIndex: "uploaded_by", width: 120 },
    { title: "Date", dataIndex: "uploaded_at", width: 160,
      render: (v: string) => v?.slice(0, 16).replace("T", " ") },
    { title: "Notes", dataIndex: "notes",
      render: (v: string | null) => v || "—" },
  ]

  return (
    <Table rowKey="upload_ref" dataSource={data} columns={columns}
      loading={loading} size="small"
      pagination={{ pageSize: 20, showSizeChanger: false }}
    />
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ══════════════════════════════════════════════════════════════════════════════
export default function MembersPage() {
  return (
    <div style={{ padding: "32px 36px" }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontWeight: 700, fontSize: 20, color: "#e2e8f0",
                     margin: 0, display: "flex", alignItems: "center", gap: 10 }}>
          <UserOutlined style={{ color: "#00d4aa" }} /> Member Data
        </h1>
        <p style={{ color: "#6b7280", fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          Upload applicant contact details by applicant_ref. Enriches cases so decision
          letters, APS emails, and output files auto-populate name, email, address and
          phone without manual entry.
        </p>
      </div>

      <Tabs defaultActiveKey="upload" size="middle" items={[
        {
          key: "upload",
          label: <span>📥 Upload Members</span>,
          children: <UploadTab />,
        },
        {
          key: "search",
          label: <span>🔍 Search & Edit</span>,
          children: <SearchTab />,
        },
        {
          key: "history",
          label: <span>📋 Upload History</span>,
          children: <HistoryTab />,
        },
      ]} />
    </div>
  )
}
