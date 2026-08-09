import { useEffect, useState } from 'react'
import {
  Table, Button, Tag, Modal, Form, Input, Select, Switch,
  message, Space, Popconfirm, Divider, Alert,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  ThunderboltOutlined, SafetyOutlined,
} from '@ant-design/icons'
import { api, ssoAPI } from '../api/client'

interface SsoProvider {
  provider_code: string
  provider_type: string
  display_name: string
  is_active: boolean
  client_secret_set: boolean
  ldap_bind_password_set: boolean
  issuer_url?: string
  client_id?: string
  authorize_url?: string
  token_url?: string
  jwks_url?: string
  scope?: string
  oidc_username_claim?: string
  ldap_server_uri?: string
  ldap_base_dn?: string
  ldap_bind_dn?: string
  ldap_user_filter?: string
  ldap_username_attr?: string
  default_role: string
  default_tenant_id?: string | null
  claim_role_attr?: string
  auto_provision: boolean
}

interface TenantRow { id: string; tenant_code: string; tenant_name: string }

const ROLE_OPTIONS = [
  'viewer', 'readonly', 'underwriter', 'senior_underwriter',
  'agent', 'broker', 'api_client', 'admin', 'super_admin',
].map((r) => ({ value: r, label: r }))

const SECRET_PLACEHOLDER = '•••••••• (stored — leave blank to keep)'

export default function SsoConfigTab() {
  const [providers, setProviders] = useState<SsoProvider[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<SsoProvider | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [tenants, setTenants] = useState<TenantRow[]>([])
  const [form] = Form.useForm()
  const providerType = Form.useWatch('provider_type', form)

  const load = async () => {
    setLoading(true)
    try {
      const r = await ssoAPI.listProviders()
      setProviders(Array.isArray(r.data) ? r.data : [])
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Failed to load SSO providers')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => {
    api.get('/tenants/').then((r) => {
      if (Array.isArray(r.data)) setTenants(r.data)
    }).catch(() => { /* tenant selector stays empty */ })
  }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({
      provider_type: 'OIDC', is_active: true, auto_provision: false,
      scope: 'openid email profile', oidc_username_claim: 'preferred_username',
      ldap_username_attr: 'sAMAccountName', default_role: 'viewer',
    })
    setOpen(true)
  }

  const openEdit = (p: SsoProvider) => {
    setEditing(p)
    form.resetFields()
    // Secrets are masked in the API — don't populate them; blank keeps stored value.
    const { client_secret_set, ldap_bind_password_set, ...rest } = p as any
    form.setFieldsValue(rest)
    setOpen(true)
  }

  const close = () => { setOpen(false); setEditing(null) }

  const onFinish = async (values: any) => {
    setSaving(true)
    try {
      const payload: any = { ...values }
      // Empty tenant select → null (backend casts to uuid; '' would crash)
      if (payload.default_tenant_id === '' || payload.default_tenant_id == null) {
        payload.default_tenant_id = null
      }
      if (payload.provider_type === 'OIDC') {
        ;['ldap_server_uri','ldap_base_dn','ldap_bind_dn','ldap_bind_password','ldap_user_filter','ldap_username_attr']
          .forEach((k) => { delete payload[k] })
        if (editing && !payload.client_secret) delete payload.client_secret
      } else {
        ;['issuer_url','client_id','client_secret','authorize_url','token_url','jwks_url','scope','oidc_username_claim']
          .forEach((k) => { delete payload[k] })
        if (editing && !payload.ldap_bind_password) delete payload.ldap_bind_password
      }
      if (editing) {
        await ssoAPI.updateProvider(editing.provider_code, payload)
        message.success(`Provider ${editing.provider_code} updated`)
      } else {
        await ssoAPI.upsertProvider(payload)
        message.success(`Provider ${payload.provider_code} created`)
      }
      close(); load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (p: SsoProvider) => {
    try {
      await ssoAPI.updateProvider(p.provider_code, { is_active: !p.is_active })
      message.success(`${p.provider_code} ${p.is_active ? 'deactivated' : 'activated'}`)
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Update failed')
    }
  }

  const runTest = async (p: SsoProvider) => {
    setTesting(p.provider_code)
    try {
      const r = await ssoAPI.testProvider(p.provider_code)
      message.success(r.data?.message || 'Connection OK')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Connection test failed')
    } finally {
      setTesting(null)
    }
  }

  const tenantLabel = (id?: string | null) => {
    const t = tenants.find((x) => x.id === id)
    return t ? `${t.tenant_code} — ${t.tenant_name}` : (id || '—')
  }

  const columns = [
    {
      title: 'Provider',
      dataIndex: 'provider_code',
      render: (_: unknown, p: SsoProvider) => (
        <div>
          <div style={{ fontWeight: 600 }}>{p.display_name}</div>
          <div style={{ color: 'var(--slate-500)', fontSize: 12 }}>{p.provider_code}</div>
        </div>
      ),
    },
    {
      title: 'Type', dataIndex: 'provider_type', width: 90,
      render: (t: string) => <Tag color={t === 'OIDC' ? 'geekblue' : 'purple'}>{t}</Tag>,
    },
    {
      title: 'Mapping', key: 'mapping',
      render: (_: unknown, p: SsoProvider) => (
        <div style={{ fontSize: 12 }}>
          <div>role: <b>{p.default_role}</b> · tenant: {tenantLabel(p.default_tenant_id)}</div>
          <div style={{ color: 'var(--slate-500)' }}>
            {p.auto_provision ? 'JIT auto-provision on' : 'pre-provisioned only'}
            {p.claim_role_attr ? ` · role claim: ${p.claim_role_attr}` : ''}
          </div>
        </div>
      ),
    },
    {
      title: 'Status', dataIndex: 'is_active', width: 110,
      render: (a: boolean) => a
        ? <Tag color="green">Active</Tag>
        : <Tag color="default">Inactive</Tag>,
    },
    {
      title: '', key: 'actions', width: 220,
      render: (_: unknown, p: SsoProvider) => (
        <Space size={6}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(p)}>Edit</Button>
          <Button size="small" icon={<ThunderboltOutlined />} loading={testing === p.provider_code}
            onClick={() => runTest(p)}>Test</Button>
          <Popconfirm
            title={p.is_active ? `Deactivate ${p.provider_code}?` : `Activate ${p.provider_code}?`}
            onConfirm={() => toggleActive(p)}
          >
            <Button size="small" danger={p.is_active} icon={<DeleteOutlined />}>
              {p.is_active ? 'Deactivate' : 'Activate'}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const tenantOptions = tenants.map((t) => ({ value: t.id, label: `${t.tenant_code} — ${t.tenant_name}` }))

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>Single Sign-On</div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Add Provider
        </Button>
      </div>

      <Alert
        type="info" showIcon icon={<SafetyOutlined />}
        message="Corporate-directory login (OIDC + LDAP). Users authenticate with their IdP/AD credentials and are mapped to a RiskUW role + tenant."
        style={{ marginBottom: 12 }}
      />

      <Table
        rowKey="provider_code" loading={loading} dataSource={providers}
        columns={columns} size="small" pagination={false}
        locale={{ emptyText: 'No SSO providers configured — add one to enable corporate login.' }}
      />

      <Modal
        title={editing ? `Edit ${editing.provider_code}` : 'Add SSO Provider'}
        open={open} onCancel={close} onOk={() => form.submit()}
        confirmLoading={saving} width={620} destroyOnClose
        okText={editing ? 'Save Changes' : 'Create Provider'}
      >
        <Form form={form} layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Space size={12} style={{ width: '100%' }} align="start">
            <Form.Item name="provider_type" label="Type" rules={[{ required: true }]} style={{ width: 140 }}>
              <Select options={[{ value: 'OIDC', label: 'OIDC' }, { value: 'LDAP', label: 'LDAP' }]} />
            </Form.Item>
            <Form.Item name="provider_code" label="Provider Code" style={{ width: 200 }}
              rules={[{ required: true, pattern: /^[A-Za-z0-9_-]+$/, message: 'Code (letters, digits, - _)' }]}>
              <Input placeholder="e.g. azure-ad" disabled={!!editing} />
            </Form.Item>
            <Form.Item name="display_name" label="Display Name" style={{ width: 240 }}
              rules={[{ required: true }]}>
              <Input placeholder="e.g. Azure AD" />
            </Form.Item>
          </Space>

          {providerType === 'OIDC' ? (
            <>
              <Space size={12} style={{ width: '100%' }} align="start">
                <Form.Item name="issuer_url" label="Issuer URL" style={{ flex: 1 }}
                  rules={[{ required: true, type: 'url', message: 'Issuer URL is required' }]}>
                  <Input placeholder="https://login.microsoftonline.com/{tenant}/v2.0" />
                </Form.Item>
                <Form.Item name="client_id" label="Client ID" style={{ flex: 1 }}
                  rules={[{ required: true }]}>
                  <Input placeholder="application (client) ID" />
                </Form.Item>
              </Space>
              <Space size={12} style={{ width: '100%' }} align="start">
                <Form.Item name="client_secret" label="Client Secret" style={{ flex: 1 }}
                  extra={editing?.client_secret_set ? 'A secret is already stored — leave blank to keep it.' : undefined}>
                  <Input.Password placeholder={editing ? SECRET_PLACEHOLDER : 'client secret'} autoComplete="new-password" />
                </Form.Item>
                <Form.Item name="scope" label="Scope" style={{ width: 220 }}>
                  <Input placeholder="openid email profile" />
                </Form.Item>
              </Space>
              <Divider style={{ margin: '4px 0 12px' }} />
              <div style={{ fontSize: 12, color: 'var(--slate-500)', marginBottom: 8 }}>
                Optional — leave blank to auto-discover from the issuer.
              </div>
              <Space size={12} style={{ width: '100%' }} align="start">
                <Form.Item name="authorize_url" label="Authorize URL" style={{ flex: 1 }}>
                  <Input placeholder="https://…/authorize" />
                </Form.Item>
                <Form.Item name="token_url" label="Token URL" style={{ flex: 1 }}>
                  <Input placeholder="https://…/token" />
                </Form.Item>
                <Form.Item name="jwks_url" label="JWKS URL" style={{ flex: 1 }}>
                  <Input placeholder="https://…/jwks" />
                </Form.Item>
              </Space>
            </>
          ) : (
            <>
              <Space size={12} style={{ width: '100%' }} align="start">
                <Form.Item name="ldap_server_uri" label="Server URI" style={{ flex: 1 }}
                  rules={[{ required: true, message: 'ldap:// or ldaps:// URL' }]}>
                  <Input placeholder="ldaps://ad.corp.local:636" />
                </Form.Item>
                <Form.Item name="ldap_bind_dn" label="Bind DN (search)" style={{ flex: 1 }}>
                  <Input placeholder="cn=svc-uw,ou=svc,dc=corp,dc=local" />
                </Form.Item>
              </Space>
              <Space size={12} style={{ width: '100%' }} align="start">
                <Form.Item name="ldap_bind_password" label="Bind Password" style={{ width: 240 }}
                  extra={editing?.ldap_bind_password_set ? 'Stored — leave blank to keep.' : undefined}>
                  <Input.Password placeholder={editing ? SECRET_PLACEHOLDER : 'service account password'} autoComplete="new-password" />
                </Form.Item>
                <Form.Item name="ldap_base_dn" label="Base DN" style={{ flex: 1 }}
                  rules={[{ required: true }]}>
                  <Input placeholder="dc=corp,dc=local" />
                </Form.Item>
              </Space>
              <Space size={12} style={{ width: '100%' }} align="start">
                <Form.Item name="ldap_user_filter" label="User Filter" style={{ flex: 1 }}
                  rules={[{ required: true }]}
                  extra="{username} is replaced with the typed username.">
                  <Input placeholder="(&(objectClass=user)(sAMAccountName={username}))" />
                </Form.Item>
                <Form.Item name="ldap_username_attr" label="Username Attr" style={{ width: 160 }}>
                  <Input placeholder="sAMAccountName" />
                </Form.Item>
              </Space>
            </>
          )}

          <Divider style={{ margin: '4px 0 12px' }} orientation="left" orientationMargin={0}>
            Account mapping
          </Divider>
          <Space size={12} style={{ width: '100%' }} align="start">
            <Form.Item name="default_role" label="Default Role" rules={[{ required: true }]}>
              <Select options={ROLE_OPTIONS} style={{ width: 180 }} />
            </Form.Item>
            <Form.Item name="default_tenant_id" label="Default Tenant"
              extra="Provisioned users land here." style={{ flex: 1 }}>
              <Select allowClear showSearch optionFilterProp="label"
                options={tenantOptions} placeholder="Select tenant" />
            </Form.Item>
            <Form.Item name="claim_role_attr" label="Role Claim / Attr" style={{ width: 200 }}
              extra="Optional claim/attribute holding the role (must be an allowed role).">
              <Input placeholder="e.g. role / memberOf" />
            </Form.Item>
          </Space>
          <Form.Item name="auto_provision" label="JIT auto-provision"
            valuePropName="checked" extra="Auto-create RiskUW accounts on first SSO login. Off = admins must pre-create users.">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
