import { useState, useEffect, useCallback } from "react";
import {
  Table, Button, Modal, Form, InputNumber, DatePicker,
  Switch, Tag, Select, Popconfirm, message, Tooltip, Space, Alert
} from "antd";
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  InfoCircleOutlined, GlobalOutlined, ApartmentOutlined
} from "@ant-design/icons";
import { api } from '../api/client';
import dayjs from "dayjs";

// ── Types ─────────────────────────────────────────────────────────────────────
interface GSTRow {
  id: string;
  product_code: string | null;
  category: string;
  first_year_rate: number;
  renewal_rate: number;
  effective_date: string;
  expiry_date: string | null;
  is_active: boolean;
  source: "system" | "product";
}

interface ModalRow {
  id: string;
  product_code: string | null;
  mode: string;
  factor: number;
  effective_date: string;
  expiry_date: string | null;
  is_active: boolean;
  source: "system" | "product";
}

const MODE_LABELS: Record<string, string> = {
  ANNUAL:      "Annual",
  HALF_YEARLY: "Half-Yearly",
  QUARTERLY:   "Quarterly",
  MONTHLY:     "Monthly",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const SourceTag = ({ source }: { source: string }) =>
  source === "system"
    ? <Tag icon={<GlobalOutlined />} color="blue">System</Tag>
    : <Tag icon={<ApartmentOutlined />} color="green">Product</Tag>;

const StatusTag = ({ row }: { row: GSTRow | ModalRow }) => {
  const today = dayjs();
  const eff   = dayjs(row.effective_date);
  const exp   = row.expiry_date ? dayjs(row.expiry_date) : null;
  if (!row.is_active)            return <Tag color="default">Inactive</Tag>;
  if (eff.isAfter(today))        return <Tag color="orange">Scheduled</Tag>;
  if (exp && exp.isBefore(today)) return <Tag color="red">Expired</Tag>;
  return <Tag color="green">Active</Tag>;
};

// ══════════════════════════════════════════════════════════════════════════════
// GST PANEL
// ══════════════════════════════════════════════════════════════════════════════
function GSTPanel({ productCode }: { productCode?: string }) {
  const [rows, setRows]         = useState<GSTRow[]>([]);
  const [loading, setLoading]   = useState(false);
  const [open, setOpen]         = useState(false);
  const [editing, setEditing]   = useState<GSTRow | null>(null);
  const [saving, setSaving]     = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = productCode
        ? `/gst-config?product_code=${productCode}`
        : "/gst-config";
      const res = await api.get(url);
      setRows(res.data);
    } catch { message.error("Failed to load GST config"); }
    finally { setLoading(false); }
  }, [productCode]);

  useEffect(() => { load(); }, [load]);

  const openAdd = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ category: "LIFE", is_active: true });
    setOpen(true);
  };

  const openEdit = (row: GSTRow) => {
    setEditing(row);
    form.setFieldsValue({
      ...row,
      effective_date: dayjs(row.effective_date),
      expiry_date: row.expiry_date ? dayjs(row.expiry_date) : null,
    });
    setOpen(true);
  };

  const handleSave = async () => {
    try {
      const vals = await form.validateFields();
      setSaving(true);
      const body = {
        ...vals,
        product_code:   productCode || null,
        effective_date: vals.effective_date.format("YYYY-MM-DD"),
        expiry_date:    vals.expiry_date
                          ? vals.expiry_date.format("YYYY-MM-DD")
                          : null,
      };
      if (editing) {
        await api.put(`/gst-config/${editing.id}`, body);
        message.success("GST config updated");
      } else {
        await api.post("/gst-config", body);
        message.success("GST config created");
      }
      setOpen(false);
      load();
    } catch (err: any) {
      if (err?.response?.status === 409)
        message.error(err.response.data.detail);
      else if (!err?.errorFields)
        message.error("Save failed");
    } finally { setSaving(false); }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/gst-config/${id}`);
      message.success("Deleted");
      load();
    } catch { message.error("Delete failed"); }
  };

  const columns = [
    { title: "Source",   dataIndex: "source",
      render: (v: string) => <SourceTag source={v} />, width: 100 },
    { title: "Category", dataIndex: "category", width: 100 },
    { title: "1st Year", dataIndex: "first_year_rate",
      render: (v: number) => <strong>{v}%</strong>, width: 90 },
    { title: "Renewal",  dataIndex: "renewal_rate",
      render: (v: number) => `${v}%`, width: 90 },
    { title: "Effective Date", dataIndex: "effective_date", width: 120 },
    { title: "Expiry Date",    dataIndex: "expiry_date",
      render: (v: string | null) => v ?? <span style={{ color: "#888" }}>Open-ended</span>,
      width: 120 },
    { title: "Status", render: (_: any, row: GSTRow) => <StatusTag row={row} />, width: 100 },
    {
      title: "Actions", width: 90,
      render: (_: any, row: GSTRow) => (
        <Space>
          <Tooltip title="Edit">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} />
          </Tooltip>
          <Popconfirm title="Delete this GST config?" onConfirm={() => handleDelete(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 12 }}>
        <Alert
          type="info" showIcon
          message="Product-level rates override system defaults. Dates within the same scope cannot overlap."
          style={{ flex: 1, marginRight: 12, padding: "4px 12px" }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
          Add GST Rate
        </Button>
      </div>

      <Table rowKey="id" dataSource={rows} columns={columns}
             loading={loading} size="small" pagination={false} />

      <Modal
        title={editing ? "Edit GST Config" : "Add GST Rate"}
        open={open} onOk={handleSave} onCancel={() => setOpen(false)}
        okText="Save" confirmLoading={saving} width={540}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="category" label="Category"
                     rules={[{ required: true }]}>
            <Select options={[
              { value: "LIFE",    label: "Life Insurance" },
              { value: "HEALTH",  label: "Health Insurance" },
              { value: "ANNUITY", label: "Annuity" },
            ]} />
          </Form.Item>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Form.Item name="first_year_rate"
                       label="First Year Rate (%)"
                       rules={[{ required: true, message: "Required" }]}>
              <InputNumber min={0} max={100} step={0.5}
                           precision={2} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="renewal_rate"
                       label="Renewal Rate (%)"
                       rules={[{ required: true, message: "Required" }]}>
              <InputNumber min={0} max={100} step={0.5}
                           precision={2} style={{ width: "100%" }} />
            </Form.Item>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Form.Item name="effective_date" label="Effective Date"
                       rules={[{ required: true, message: "Required" }]}>
              <DatePicker style={{ width: "100%" }} format="DD-MM-YYYY" />
            </Form.Item>
            <Form.Item name="expiry_date"
                       label={
                         <span>Expiry Date
                           <span style={{ color: "#888", fontWeight: 400 }}> (blank = open-ended)</span>
                         </span>
                       }>
              <DatePicker style={{ width: "100%" }} format="DD-MM-YYYY" />
            </Form.Item>
          </div>

          <Form.Item name="is_active" label="Active" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// MODAL FACTOR PANEL
// ══════════════════════════════════════════════════════════════════════════════
function ModalPanel({ productCode }: { productCode?: string }) {
  const [rows, setRows]       = useState<ModalRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen]       = useState(false);
  const [editing, setEditing] = useState<ModalRow | null>(null);
  const [saving, setSaving]   = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = productCode
        ? `/modal-factor-config?product_code=${productCode}`
        : "/modal-factor-config";
      const res = await api.get(url);
      setRows(res.data);
    } catch { message.error("Failed to load modal factors"); }
    finally { setLoading(false); }
  }, [productCode]);

  useEffect(() => { load(); }, [load]);

  const openAdd = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true });
    setOpen(true);
  };

  const openEdit = (row: ModalRow) => {
    setEditing(row);
    form.setFieldsValue({
      ...row,
      effective_date: dayjs(row.effective_date),
      expiry_date: row.expiry_date ? dayjs(row.expiry_date) : null,
    });
    setOpen(true);
  };

  const handleSave = async () => {
    try {
      const vals = await form.validateFields();
      setSaving(true);
      const body = {
        ...vals,
        product_code:   productCode || null,
        effective_date: vals.effective_date.format("YYYY-MM-DD"),
        expiry_date:    vals.expiry_date
                          ? vals.expiry_date.format("YYYY-MM-DD")
                          : null,
      };
      if (editing) {
        await api.put(`/modal-factor-config/${editing.id}`, body);
        message.success("Modal factor updated");
      } else {
        await api.post("/modal-factor-config", body);
        message.success("Modal factor created");
      }
      setOpen(false);
      load();
    } catch (err: any) {
      if (err?.response?.status === 409)
        message.error(err.response.data.detail);
      else if (!err?.errorFields)
        message.error("Save failed");
    } finally { setSaving(false); }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/modal-factor-config/${id}`);
      message.success("Deleted");
      load();
    } catch { message.error("Delete failed"); }
  };

  const columns = [
    { title: "Source", dataIndex: "source",
      render: (v: string) => <SourceTag source={v} />, width: 100 },
    { title: "Mode", dataIndex: "mode",
      render: (v: string) => MODE_LABELS[v] || v, width: 120 },
    { title: "Factor", dataIndex: "factor",
      render: (v: number) => <strong>{v.toFixed(4)}</strong>, width: 90 },
    { title: "Effective Date", dataIndex: "effective_date", width: 120 },
    { title: "Expiry Date", dataIndex: "expiry_date",
      render: (v: string | null) => v ?? <span style={{ color: "#888" }}>Open-ended</span>,
      width: 120 },
    { title: "Status",
      render: (_: any, row: ModalRow) => <StatusTag row={row} />, width: 100 },
    {
      title: "Actions", width: 90,
      render: (_: any, row: ModalRow) => (
        <Space>
          <Tooltip title="Edit">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} />
          </Tooltip>
          <Popconfirm title="Delete this modal factor?" onConfirm={() => handleDelete(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 12 }}>
        <Alert
          type="info" showIcon
          message="Same mode cannot have overlapping date ranges within the same scope. Product overrides take priority."
          style={{ flex: 1, marginRight: 12, padding: "4px 12px" }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
          Add Modal Factor
        </Button>
      </div>

      <Table rowKey="id" dataSource={rows} columns={columns}
             loading={loading} size="small" pagination={false} />

      <Modal
        title={editing ? "Edit Modal Factor" : "Add Modal Factor"}
        open={open} onOk={handleSave} onCancel={() => setOpen(false)}
        okText="Save" confirmLoading={saving} width={540}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="mode" label="Payment Mode"
                     rules={[{ required: true, message: "Required" }]}>
            <Select
              disabled={!!editing}
              options={Object.entries(MODE_LABELS).map(([v, l]) => ({ value: v, label: l }))}
            />
          </Form.Item>

          <Form.Item
            name="factor"
            label={
              <span>
                Factor&nbsp;
                <Tooltip title="Fraction of annual premium. Annual=1.0, Half-yearly≈0.51, Quarterly≈0.26, Monthly≈0.09">
                  <InfoCircleOutlined style={{ color: "#888" }} />
                </Tooltip>
              </span>
            }
            rules={[{ required: true, message: "Required" }]}
          >
            <InputNumber min={0} max={2} step={0.001}
                         precision={4} style={{ width: "100%" }} />
          </Form.Item>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Form.Item name="effective_date" label="Effective Date"
                       rules={[{ required: true, message: "Required" }]}>
              <DatePicker style={{ width: "100%" }} format="DD-MM-YYYY" />
            </Form.Item>
            <Form.Item name="expiry_date"
                       label={
                         <span>Expiry Date
                           <span style={{ color: "#888", fontWeight: 400 }}> (blank = open-ended)</span>
                         </span>
                       }>
              <DatePicker style={{ width: "100%" }} format="DD-MM-YYYY" />
            </Form.Item>
          </div>

          <Form.Item name="is_active" label="Active" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN EXPORT
// ══════════════════════════════════════════════════════════════════════════════
export function GSTModalConfigTab({ productCode }: { productCode?: string }) {
  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ marginBottom: 4 }}>
          🧾 GST Configuration
          {productCode && (
            <span style={{ fontSize: 13, fontWeight: 400, color: "#888", marginLeft: 8 }}>
              — showing system defaults + {productCode} overrides
            </span>
          )}
        </h3>
        <GSTPanel productCode={productCode} />
      </div>

      <div>
        <h3 style={{ marginBottom: 4 }}>
          📊 Modal Factors
          {productCode && (
            <span style={{ fontSize: 13, fontWeight: 400, color: "#888", marginLeft: 8 }}>
              — showing system defaults + {productCode} overrides
            </span>
          )}
        </h3>
        <ModalPanel productCode={productCode} />
      </div>
    </div>
  );
}

export default GSTModalConfigTab;
