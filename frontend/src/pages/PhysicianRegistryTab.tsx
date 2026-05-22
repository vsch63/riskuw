import { useState, useEffect, useCallback } from "react"
import {
  Table, Button, Modal, Form, Input, Switch, Select,
  Popconfirm, message, Tag, Space, DatePicker, Tooltip
} from "antd"
import {
  PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined
} from "@ant-design/icons"
import { api } from "../api/client"
import dayjs from "dayjs"

const { Option } = Select

interface Physician {
  id: number
  physician_name: string
  registration_no: string
  specialisation: string | null
  clinic_name: string | null
  email: string | null
  phone: string | null
  city: string | null
  state: string | null
  pincode: string | null
  address_line1: string | null
  address_line2: string | null
  effective_date: string | null
  expire_date: string | null
  is_active: boolean
}

const SPECIALISATIONS = [
  "General Physician", "Cardiologist", "Pulmonologist",
  "Neurologist", "Endocrinologist", "Oncologist",
  "Nephrologist", "Gastroenterologist", "Psychiatrist",
  "Orthopedic", "Ophthalmologist", "General Surgeon", "Other"
]

export default function PhysicianRegistryTab() {
  const [data, setData]         = useState<Physician[]>([])
  const [loading, setLoading]   = useState(false)
  const [search, setSearch]     = useState("")
  const [activeOnly, setActiveOnly] = useState(false)
  const [open, setOpen]         = useState(false)
  const [editing, setEditing]   = useState<Physician | null>(null)
  const [saving, setSaving]     = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (search)     params.append("search", search)
      if (activeOnly) params.append("active_only", "true")
      const res = await api.get(`/physicians?${params}`)
      setData(res.data)
    } catch { message.error("Failed to load physicians") }
    finally { setLoading(false) }
  }, [search, activeOnly])

  useEffect(() => { load() }, [load])

  const openAdd = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ is_active: true })
    setOpen(true)
  }

  const openEdit = (row: Physician) => {
    setEditing(row)
    form.setFieldsValue({
      ...row,
      effective_date: row.effective_date ? dayjs(row.effective_date) : null,
      expire_date:    row.expire_date    ? dayjs(row.expire_date)    : null,
    })
    setOpen(true)
  }

  const handleSave = async () => {
    try {
      const vals = await form.validateFields()
      setSaving(true)
      const body = {
        ...vals,
        effective_date: vals.effective_date?.format("YYYY-MM-DD") || null,
        expire_date:    vals.expire_date?.format("YYYY-MM-DD")    || null,
      }
      if (editing) {
        await api.put(`/physicians/${editing.id}`, body)
        message.success("Physician updated")
      } else {
        await api.post("/physicians", body)
        message.success("Physician added")
      }
      setOpen(false)
      load()
    } catch (e: any) {
      if (!e?.errorFields) message.error("Save failed")
    } finally { setSaving(false) }
  }

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/physicians/${id}`)
      message.success("Physician deleted")
      load()
    } catch { message.error("Delete failed") }
  }

  const columns = [
    {
      title: "Name", dataIndex: "physician_name", width: 180,
      render: (v: string, row: Physician) => (
        <div>
          <div style={{ fontWeight: 600, color: "#e2e8f0" }}>{v}</div>
          <div style={{ fontSize: 11, color: "#6b7280" }}>{row.registration_no}</div>
        </div>
      )
    },
    {
      title: "Specialisation", dataIndex: "specialisation", width: 150,
      render: (v: string | null) => v
        ? <Tag color="blue">{v}</Tag>
        : <span style={{ color: "#4b5563" }}>—</span>
    },
    {
      title: "Clinic", dataIndex: "clinic_name", width: 160,
      render: (v: string | null) => v || "—"
    },
    {
      title: "Contact", width: 160,
      render: (_: any, row: Physician) => (
        <div>
          {row.phone && <div style={{ fontSize: 12 }}>{row.phone}</div>}
          {row.email && <div style={{ fontSize: 11, color: "#6b7280" }}>{row.email}</div>}
        </div>
      )
    },
    {
      title: "Location", width: 130,
      render: (_: any, row: Physician) => (
        <div style={{ fontSize: 12 }}>
          {[row.city, row.state].filter(Boolean).join(", ") || "—"}
        </div>
      )
    },
    {
      title: "Valid From", dataIndex: "effective_date", width: 100,
      render: (v: string | null) => v || <span style={{ color: "#4b5563" }}>—</span>
    },
    {
      title: "Status", dataIndex: "is_active", width: 80,
      render: (v: boolean) => v
        ? <Tag color="green">Active</Tag>
        : <Tag color="default">Inactive</Tag>
    },
    {
      title: "Actions", width: 80,
      render: (_: any, row: Physician) => (
        <Space>
          <Tooltip title="Edit">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} />
          </Tooltip>
          <Popconfirm title="Delete this physician?" onConfirm={() => handleDelete(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    }
  ]

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
        <Input
          placeholder="Search by name, reg no, specialisation, city..."
          prefix={<SearchOutlined style={{ color: "#6b7280" }} />}
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, maxWidth: 400 }}
          allowClear
        />
        <Button
          size="small"
          type={activeOnly ? "primary" : "default"}
          onClick={() => setActiveOnly(!activeOnly)}
        >
          Active Only
        </Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
          Add Physician
        </Button>
      </div>

      <Table
        rowKey="id"
        dataSource={data}
        columns={columns}
        loading={loading}
        size="small"
        pagination={{ pageSize: 20, showSizeChanger: false }}
      />

      <Modal
        title={editing ? "Edit Physician" : "Add Physician"}
        open={open}
        onOk={handleSave}
        onCancel={() => setOpen(false)}
        okText="Save"
        confirmLoading={saving}
        width={620}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Form.Item name="physician_name" label="Physician Name"
              rules={[{ required: true, message: "Required" }]}>
              <Input placeholder="Dr. Firstname Lastname" />
            </Form.Item>
            <Form.Item name="registration_no" label="Registration No"
              rules={[{ required: true, message: "Required" }]}>
              <Input placeholder="MCI/State reg number" />
            </Form.Item>
            <Form.Item name="specialisation" label="Specialisation">
              <Select allowClear placeholder="Select specialisation">
                {SPECIALISATIONS.map(s => <Option key={s} value={s}>{s}</Option>)}
              </Select>
            </Form.Item>
            <Form.Item name="clinic_name" label="Clinic / Hospital Name">
              <Input placeholder="Clinic or hospital name" />
            </Form.Item>
            <Form.Item name="phone" label="Phone">
              <Input placeholder="+91 XXXXX XXXXX" />
            </Form.Item>
            <Form.Item name="email" label="Email">
              <Input placeholder="doctor@clinic.com" />
            </Form.Item>
          </div>

          <Form.Item name="address_line1" label="Address Line 1">
            <Input placeholder="Street address" />
          </Form.Item>
          <Form.Item name="address_line2" label="Address Line 2">
            <Input placeholder="Area / Landmark" />
          </Form.Item>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            <Form.Item name="city" label="City">
              <Input placeholder="City" />
            </Form.Item>
            <Form.Item name="state" label="State">
              <Input placeholder="State" />
            </Form.Item>
            <Form.Item name="pincode" label="Pincode">
              <Input placeholder="560001" />
            </Form.Item>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            <Form.Item name="effective_date" label="Effective Date">
              <DatePicker style={{ width: "100%" }} format="DD-MM-YYYY" />
            </Form.Item>
            <Form.Item name="expire_date" label="Expiry Date">
              <DatePicker style={{ width: "100%" }} format="DD-MM-YYYY" />
            </Form.Item>
            <Form.Item name="is_active" label="Active" valuePropName="checked">
              <Switch />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  )
}
