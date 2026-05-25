import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Modal, Form, Input, Select,
  Spin, message, Popconfirm, Tabs, InputNumber, Alert, Checkbox,
} from 'antd'
import {
  PlusOutlined, EditOutlined, StopOutlined, CheckOutlined,
  KeyOutlined, ReloadOutlined, UserOutlined, SafetyOutlined,
  TeamOutlined, LockOutlined, SearchOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAuthStore } from '../context/authStore'

const { Option } = Select

const ROLES = ['super_admin','admin','senior_underwriter','underwriter','api_client','readonly']

const roleColor: Record<string,string> = {
  super_admin:'purple', admin:'purple', senior_underwriter:'gold',
  underwriter:'cyan', api_client:'blue', readonly:'default',
}

// Tighter palette — only 2 accent hues per role, no rainbow
const roleBadgeStyle: Record<string, React.CSSProperties> = {
  super_admin:        { background:'rgba(168,85,247,0.12)', color:'#c084fc', border:'1px solid rgba(168,85,247,0.25)' },
  admin:              { background:'rgba(168,85,247,0.08)', color:'#a855f7', border:'1px solid rgba(168,85,247,0.2)'  },
  senior_underwriter: { background:'rgba(251,191,36,0.1)',  color:'#fbbf24', border:'1px solid rgba(251,191,36,0.25)' },
  underwriter:        { background:'rgba(0,212,170,0.1)',   color:'#00d4aa', border:'1px solid rgba(0,212,170,0.25)'  },
  api_client:         { background:'rgba(96,165,250,0.1)',  color:'#60a5fa', border:'1px solid rgba(96,165,250,0.2)'  },
  readonly:           { background:'rgba(255,255,255,0.05)',color:'#8b949e', border:'1px solid rgba(255,255,255,0.12)' },
}

const roleDesc: Record<string,string> = {
  super_admin:        'Full platform access including tenant management',
  admin:              'User management, product config, system settings',
  senior_underwriter: 'All UW functions + manual override + rule config',
  underwriter:        'Evaluate, queue work, record decisions, APS',
  api_client:         'API-only access for system integrations',
  readonly:           'Read-only view of decisions and reports',
}

const rolePerms: Record<string, string[]> = {
  super_admin:        ['All admin permissions','Tenant management','Suspend/activate tenants','Billing & plan management'],
  admin:              ['Create/edit/deactivate users','Product configuration','Rule configuration','System configuration','View all decisions'],
  senior_underwriter: ['All underwriter permissions','Manual decision override','Rule configuration','Authority limit setting','APS management'],
  underwriter:        ['Evaluate applications','Work UW queue','Record manual decisions','Request APS','View case history'],
  api_client:         ['POST /underwriting/evaluate','GET /products','GET /queue (read-only)','No UI access'],
  readonly:           ['View dashboard','View cases (read-only)','No evaluation or config access'],
}

interface User {
  username: string
  email: string
  full_name?: string
  role: string
  is_active: boolean
  last_login_at?: string
  tenant_id?: string
  tenant_name?: string
  tenant_code?: string
}

// Modal styles — consistent dark surface
const MS = {
  content: { background: '#0d1521', border: '1px solid rgba(255,255,255,0.09)' },
  header:  { background: '#0d1521' },
  footer:  { background: '#0d1521' },
}

// Avatar: initials circle from username
function Avatar({ username, role }: { username: string; role: string }) {
  const initials = username.slice(0, 2).toUpperCase()
  const colorMap: Record<string, { bg: string; color: string }> = {
    super_admin:        { bg: 'rgba(168,85,247,0.18)',  color: '#c084fc' },
    admin:              { bg: 'rgba(168,85,247,0.12)',  color: '#a855f7' },
    senior_underwriter: { bg: 'rgba(251,191,36,0.15)', color: '#fbbf24' },
    underwriter:        { bg: 'rgba(0,212,170,0.15)',  color: '#00d4aa' },
    api_client:         { bg: 'rgba(96,165,250,0.15)', color: '#60a5fa' },
    readonly:           { bg: 'rgba(255,255,255,0.08)',color: '#8b949e' },
  }
  const c = colorMap[role] || colorMap.readonly
  return (
    <div style={{
      width: 32, height: 32, borderRadius: '50%',
      background: c.bg, color: c.color,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 11, fontWeight: 700, letterSpacing: '0.03em', flexShrink: 0,
    }}>
      {initials}
    </div>
  )
}

// Relative time helper
function relTime(iso?: string): string {
  if (!iso) return '—'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60)   return 'Just now'
  if (diff < 3600) return `${Math.floor(diff/60)}m ago`
  if (diff < 86400) return `${Math.floor(diff/3600)}h ago`
  if (diff < 7*86400) return `${Math.floor(diff/86400)}d ago`
  return new Date(iso).toLocaleDateString()
}

// ─── Role Badge ────────────────────────────────────────────────────────────────
function RoleBadge({ role }: { role: string }) {
  const s = roleBadgeStyle[role] || roleBadgeStyle.readonly
  return (
    <span style={{
      ...s, display:'inline-block',
      padding: '3px 9px', borderRadius: 5,
      fontSize: 11, fontWeight: 600,
      fontFamily: 'var(--font-mono, monospace)',
    }}>
      {role.replace(/_/g, ' ')}
    </span>
  )
}

// ─── Stat Card ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, color, sub }: { label: string; value: number; color: string; sub?: string }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.025)',
      border: '1px solid rgba(255,255,255,0.07)',
      borderRadius: 10, padding: '14px 16px',
    }}>
      <div style={{ fontSize: 22, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      <div style={{ fontSize: 11, color: '#6b7280', marginTop: 3 }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: '#4b5563', marginTop: 5 }}>{sub}</div>}
    </div>
  )
}

// ─── All Users Tab ─────────────────────────────────────────────────────────────
function AllUsersTab({ refresh }: { refresh: number }) {
  const [users, setUsers]         = useState<User[]>([])
  const [loading, setLoading]     = useState(true)
  const [search, setSearch]       = useState('')
  const [roleFilter, setRole]     = useState('ALL')
  const [statusFilter, setStat]   = useState('ALL')
  const [editUser, setEdit]       = useState<User|null>(null)
  const [pwUser, setPw]           = useState<User|null>(null)
  const [sub, setSub]             = useState(false)
  const [ef]                      = Form.useForm()
  const [pf]                      = Form.useForm()
  const { user: me }              = useAuthStore()

  const load = async () => {
    setLoading(true)
    try { const r = await api.get('/auth/users'); setUsers(Array.isArray(r.data) ? r.data : []) }
    catch { message.error('Failed to load users') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [refresh])

  const filtered = users.filter(u => {
    const q   = search.toLowerCase()
    const sOk = !q || u.username.includes(q) || u.email.includes(q) || (u.full_name||'').toLowerCase().includes(q)
    const rOk = roleFilter === 'ALL' || u.role === roleFilter
    const stOk = statusFilter === 'ALL' || (statusFilter === 'ACTIVE' && u.is_active) || (statusFilter === 'INACTIVE' && !u.is_active)
    return sOk && rOk && stOk
  })

  const openEdit = (u: User) => { setEdit(u); ef.setFieldsValue({ email: u.email, full_name: u.full_name, role: u.role }) }
  const doEdit = async () => {
    if (!editUser) return; setSub(true)
    try {
      const v = ef.getFieldsValue()
      if (v.role !== editUser.role) await api.post(`/auth/users/${editUser.username}/change-role`, { role: v.role })
      await api.patch(`/auth/users/${editUser.username}`, { email: v.email, full_name: v.full_name })
      message.success('User updated'); setEdit(null); load()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Update failed') }
    finally { setSub(false) }
  }
  const doPw = async () => {
    if (!pwUser) return
    await pf.validateFields().catch(() => { throw new Error() })
    setSub(true)
    try {
      const v = pf.getFieldsValue()
      await api.post(`/auth/users/${pwUser.username}/reset-password`, { new_password: v.np, actor_username: me?.username })
      message.success('Password reset'); setPw(null); pf.resetFields()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Reset failed') }
    finally { setSub(false) }
  }
  const toggle = async (u: User) => {
    try { await api.post(`/auth/users/${u.username}/${u.is_active ? 'deactivate' : 'activate'}`); message.success('Updated'); load() }
    catch { message.error('Failed') }
  }

  const cols = [
    {
      title: 'User', dataIndex: 'username', width: 220,
      render: (v: string, u: User) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Avatar username={v} role={u.role}/>
          <div>
            <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 13, color: '#e2e8f0', fontWeight: 600 }}>{v}</div>
            <div style={{ fontSize: 11, color: '#6b7280', marginTop: 1 }}>{u.full_name || u.email}</div>
          </div>
        </div>
      ),
    },
    {
      title: 'Email', dataIndex: 'email', width: 200,
      render: (v: string) => <span style={{ fontSize: 12, color: '#9ca3af' }}>{v}</span>,
    },
    {
      title: 'Role', dataIndex: 'role', width: 160,
      render: (v: string) => <RoleBadge role={v}/>,
    },
    {
      title: 'Status', dataIndex: 'is_active', width: 100,
      render: (v: boolean) => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: v ? '#22c55e' : '#ef4444', display: 'inline-block' }}/>
          <span style={{ color: v ? '#86efac' : '#fca5a5' }}>{v ? 'Active' : 'Inactive'}</span>
        </span>
      ),
    },
    {
      title: 'Last Login', dataIndex: 'last_login_at', width: 120,
      render: (v: string) => <span style={{ fontSize: 12, color: '#6b7280' }}>{relTime(v)}</span>,
    },
    ...(me?.role === 'super_admin' ? [{
      title: 'Tenant', dataIndex: 'tenant_name', width: 150,
      render: (v: string, u: User) => (
        <div>
          <div style={{ fontSize: 12, color: '#9ca3af' }}>{v || '—'}</div>
          {u.tenant_code && <div style={{ fontSize: 10, color: '#4b5563', fontFamily: 'var(--font-mono,monospace)' }}>{u.tenant_code}</div>}
        </div>
      ),
    }] : []),
    {
      title: 'Actions', width: 120,
      render: (_: any, u: User) => (
        <div style={{ display: 'flex', gap: 5 }}>
          <Button size="small" icon={<EditOutlined/>} onClick={() => openEdit(u)}
            style={{ borderColor: 'rgba(0,212,170,0.25)', color: '#00d4aa', background: 'transparent' }}
            title="Edit user"/>
          <Button size="small" icon={<KeyOutlined/>} onClick={() => setPw(u)}
            style={{ borderColor: 'rgba(251,191,36,0.25)', color: '#fbbf24', background: 'transparent' }}
            title="Reset password"/>
          <Popconfirm
            title={`${u.is_active ? 'Deactivate' : 'Activate'} ${u.username}?`}
            onConfirm={() => toggle(u)} okText="Yes" cancelText="No">
            <Button size="small"
              icon={u.is_active ? <StopOutlined/> : <CheckOutlined/>}
              style={{
                borderColor: u.is_active ? 'rgba(239,68,68,0.25)' : 'rgba(34,197,94,0.25)',
                color: u.is_active ? '#f87171' : '#4ade80', background: 'transparent',
              }}
              title={u.is_active ? 'Deactivate' : 'Activate'}
            />
          </Popconfirm>
        </div>
      ),
    },
  ]

  const active   = users.filter(u => u.is_active).length
  const inactive = users.filter(u => !u.is_active).length

  return (
    <>
      {/* Stat row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 12, marginBottom: 24 }}>
        <StatCard label="Total Users"  value={users.length} color="#00d4aa"/>
        <StatCard label="Active"       value={active}       color="#22c55e" sub={`${users.length ? Math.round(active/users.length*100) : 0}% of total`}/>
        <StatCard label="Inactive"     value={inactive}     color="#f87171"/>
        <StatCard label="Admins"       value={users.filter(u=>['admin','super_admin'].includes(u.role)).length} color="#c084fc"/>
        <StatCard label="Underwriters" value={users.filter(u=>['underwriter','senior_underwriter'].includes(u.role)).length} color="#60a5fa"/>
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}>
        <Input
          prefix={<SearchOutlined style={{ color: '#6b7280' }}/>}
          placeholder="Search by username, name or email…"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ maxWidth: 300 }} allowClear
        />
        <Select value={roleFilter} onChange={setRole} style={{ width: 170 }}>
          <Option value="ALL">All roles</Option>
          {ROLES.map(r => <Option key={r} value={r}>{r.replace(/_/g,' ')}</Option>)}
        </Select>
        <Select value={statusFilter} onChange={setStat} style={{ width: 130 }}>
          <Option value="ALL">All statuses</Option>
          <Option value="ACTIVE">Active</Option>
          <Option value="INACTIVE">Inactive</Option>
        </Select>
        <Button icon={<ReloadOutlined/>} onClick={load} loading={loading} style={{ marginLeft: 'auto' }}>
          Refresh
        </Button>
      </div>

      {/* Table */}
      {loading
        ? <div style={{ display:'flex', justifyContent:'center', padding:'60px 0' }}><Spin size="large"/></div>
        : (
          <Table
            dataSource={filtered} columns={cols} rowKey="username"
            size="middle" pagination={{ pageSize: 15, showSizeChanger: false }}
            locale={{ emptyText: 'No users match your filters' }}
          />
        )
      }

      {/* Edit Modal */}
      <Modal
        title={<span style={{ color: '#e2e8f0' }}>Edit user — {editUser?.username}</span>}
        open={!!editUser} onCancel={() => setEdit(null)} onOk={doEdit}
        confirmLoading={sub} okText="Save changes" styles={MS}>
        <Form form={ef} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="full_name" label="Full Name" help="Display name shown in audit logs and decisions"><Input placeholder="e.g. Jane Smith"/></Form.Item>
          <Form.Item name="email" label="Email" help="Used for notifications and password resets"><Input placeholder="jane@carrier.com"/></Form.Item>
          <Form.Item name="role" label="Role" help="Changing role takes effect on next login">
            <Select placeholder="Select role…">{ROLES.map(r => <Option key={r} value={r}>{r.replace(/_/g,' ')}</Option>)}</Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* Reset Password Modal */}
      <Modal
        title={<span style={{ color: '#e2e8f0' }}>Reset password — {pwUser?.username}</span>}
        open={!!pwUser} onCancel={() => setPw(null)} onOk={doPw}
        confirmLoading={sub} okText="Reset password" styles={MS}>
        <Form form={pf} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="np" label="New Password" rules={[{ required: true, min: 8 }]} help="Minimum 8 characters — user will be prompted to change on next login">
            <Input.Password placeholder="Min 8 characters"/>
          </Form.Item>
          <Form.Item name="c" label="Confirm Password" dependencies={['np']}
            rules={[{ required: true }, { validator: (_,v) => pf.getFieldValue('np')===v ? Promise.resolve() : Promise.reject('Passwords do not match') }]}>
            <Input.Password placeholder="Repeat new password"/>
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

// ─── Create User Tab ───────────────────────────────────────────────────────────
function CreateUserTab({ onCreated }: { onCreated: () => void }) {
  const [form]                      = Form.useForm()
  const [loading, setLoading]       = useState(false)
  const [selectedRole, setSelectedRole] = useState('underwriter')
  const { user: me }                = useAuthStore()
  const isSuperAdmin                = me?.role === 'super_admin'
  const [tenants, setTenants]       = useState<{id:string, tenant_name:string, tenant_code:string}[]>([])

  const UW_ROLES = ['underwriter', 'senior_underwriter', 'admin']
  const showAuthority = UW_ROLES.includes(selectedRole)

  useEffect(() => {
    if (isSuperAdmin) {
      api.get('/tenants/').then(r => {
        setTenants(Array.isArray(r.data) ? r.data : [])
        // Pre-select first tenant if only one exists
        if (Array.isArray(r.data) && r.data.length === 1) {
          form.setFieldValue('tenant_id', r.data[0].id)
        }
      }).catch(() => {})
    }
  }, [isSuperAdmin])

  const sectionStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.02)',
    border: '1px solid rgba(255,255,255,0.07)',
    borderRadius: 10, padding: '20px 24px', marginBottom: 16,
  }
  const sectionTitle: React.CSSProperties = {
    fontSize: 12, fontWeight: 600, color: '#6b7280',
    textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16,
  }

  const go = async () => {
    try { await form.validateFields() } catch { return }
    setLoading(true)
    try {
      const v = form.getFieldsValue()
      if (v.password !== v.confirm_password) {
        message.error('Passwords do not match'); setLoading(false); return
      }
      await api.post('/auth/register', {
        username: v.username, full_name: v.full_name, email: v.email,
        password: v.password, role: v.role,
        effective_date: v.effective_date || null,
        expiry_date:    v.expiry_date    || null,
        tenant_id: isSuperAdmin ? v.tenant_id : me?.tenant_id,
      })
      if (showAuthority && (v.min_face_amount || v.max_face_amount || v.notes)) {
        try {
          const products = v.product_codes
            ? v.product_codes.split(',').map((s: string) => s.trim()).filter(Boolean)
            : []
          await api.post('/users/authority-limits', {
            username: v.username,
            min_face_amount: v.min_face_amount || 0,
            max_face_amount: v.max_face_amount || null,
            product_codes: products,
            notes: v.notes || null,
            is_medical_officer: false,
          })
        } catch {
          message.warning('User created — authority limits could not be saved. Set them in the Authority Limits tab.')
        }
      }
      message.success(`User ${v.username} created successfully`)
      form.resetFields(); setSelectedRole('underwriter'); onCreated()
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Failed to create user') }
    finally { setLoading(false) }
  }

  return (
    <div style={{ maxWidth: 860 }}>
      <Alert
        message="New users can log in immediately. MFA-required roles will be prompted to enrol on first login."
        type="info" showIcon
        style={{ marginBottom: 20, background: 'rgba(0,212,170,0.05)', border: '1px solid rgba(0,212,170,0.18)' }}
      />
      <Form form={form} layout="vertical" requiredMark={false}>

        {/* Account details */}
        <div style={sectionStyle}>
          <div style={sectionTitle}>Account Details</div>

          {/* Tenant selector — super_admin only */}
          {isSuperAdmin && (
            <Form.Item name="tenant_id" label="Tenant" rules={[{ required: true, message: 'Please select a tenant' }]}
              help="Select which insurance carrier this user belongs to">
              <Select placeholder="Select tenant…" showSearch
                optionFilterProp="label"
                options={tenants.map(t => ({
                  value: t.id,
                  label: `${t.tenant_name} (${t.tenant_code})`,
                }))}
              />
            </Form.Item>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            {/* Left */}
            <div>
              <Form.Item name="username" label="Username"
                rules={[{ required: true, message: 'Required' }, { pattern: /^[a-z0-9._-]+$/, message: 'Lowercase, numbers, dots, dashes only' }]}>
                <Input placeholder="e.g. jsmith" prefix={<UserOutlined style={{ color: '#6b7280' }}/>}/>
              </Form.Item>
              <Form.Item name="full_name" label="Full Name" rules={[{ required: true, message: 'Required' }]}>
                <Input placeholder="e.g. John Smith"/>
              </Form.Item>
              <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email', message: 'Valid email required' }]}>
                <Input placeholder="jsmith@carrier.com"/>
              </Form.Item>
              <Form.Item name="role" label="Role" initialValue="underwriter" rules={[{ required: true }]}>
                <Select onChange={(v) => setSelectedRole(v)}>
                  {ROLES.map(r => (
                    <Option key={r} value={r}>
                      <span style={{ ...roleBadgeStyle[r], padding:'2px 7px', borderRadius:4, fontSize:10, fontFamily:'monospace', marginRight:8 }}>
                        {r.replace(/_/g,' ')}
                      </span>
                      {roleDesc[r]}
                    </Option>
                  ))}
                </Select>
              </Form.Item>
              {/* Role permissions hint */}
              {selectedRole && (
                <div style={{ background:'rgba(0,212,170,0.04)', border:'1px solid rgba(0,212,170,0.12)', borderRadius:8, padding:'10px 14px' }}>
                  <div style={{ fontSize:11, color:'#6b7280', marginBottom:6, fontWeight:600, textTransform:'uppercase', letterSpacing:'0.06em' }}>Permissions</div>
                  <ul style={{ margin:0, paddingLeft:16 }}>
                    {rolePerms[selectedRole]?.map((p,i) => (
                      <li key={i} style={{ fontSize:12, color:'#9ca3af', marginBottom:3 }}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            {/* Right */}
            <div>
              <Form.Item name="password" label="Password" rules={[{ required: true, min: 8, message: 'Min 8 characters' }]}>
                <Input.Password placeholder="Min 8 characters" prefix={<LockOutlined style={{ color: '#6b7280' }}/>}/>
              </Form.Item>
              <Form.Item name="confirm_password" label="Confirm Password" dependencies={['password']}
                rules={[
                  { required: true, message: 'Please confirm password' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue('password') === value) return Promise.resolve()
                      return Promise.reject(new Error('Passwords do not match'))
                    },
                  }),
                ]}>
                <Input.Password placeholder="Repeat password" prefix={<LockOutlined style={{ color: '#6b7280' }}/>}/>
              </Form.Item>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Form.Item name="effective_date" label="Account Effective Date" help="User cannot log in before this date — leave blank to activate immediately">
                  <Input type="date"/>
                </Form.Item>
                <Form.Item name="expiry_date" label="Account Expiry Date" help="Account is automatically disabled after this date — leave blank for no expiry">
                  <Input type="date"/>
                </Form.Item>
              </div>
            </div>
          </div>
        </div>

        {/* Authority Limits — only for UW roles */}
        {showAuthority && (
          <div style={sectionStyle}>
            <div style={sectionTitle}>
              Authority Limits
              <span style={{ fontSize:11, color:'#4b5563', fontWeight:400, textTransform:'none', letterSpacing:0, marginLeft:8 }}>
                optional — can also be set later via Authority Limits tab
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <Form.Item name="min_face_amount" label="Min face amount (₹)" initialValue={0} help="Minimum case size this user can approve — set 0 for no lower limit">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="e.g. 0"
                  formatter={v => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                  parser={(v:any) => Number(v!.replace(/,*/g, ''))}/>
              </Form.Item>
              <Form.Item name="max_face_amount" label="Max face amount (₹)" initialValue={0} help="Maximum case size this user can approve independently — 0 means unlimited">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="e.g. 5000000"
                  formatter={v => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                  parser={(v:any) => Number(v!.replace(/,*/g, ''))}/>
              </Form.Item>
            </div>
            <Form.Item name="product_codes" label="Restrict to products (comma-separated, blank = all)">
              <Input placeholder="e.g. IND-TERM-10, IND-TERM-20"/>
            </Form.Item>
            <Form.Item name="notes" label="Authority Notes">
              <Input.TextArea rows={3}
                placeholder="e.g. Junior UW — cases above ₹50L must be co-signed by Senior UW. Non-medical products only."/>
            </Form.Item>
          </div>
        )}

        <Button type="primary" icon={<PlusOutlined/>} loading={loading} onClick={go} size="large" block
          style={{ height: 44, fontWeight: 600 }}>
          Create User
        </Button>
      </Form>
    </div>
  )
}

// ─── Authority Limits Tab ──────────────────────────────────────────────────────
function AuthorityLimitsTab() {
  const [users, setUsers]     = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState('')
  const [form]                = Form.useForm()
  const [saving, setSaving]   = useState(false)

  useEffect(() => {
    api.get('/auth/users')
      .then(r => {
        const u = Array.isArray(r.data) ? r.data : []
        setUsers(u.filter((u: User) => ['underwriter','senior_underwriter','admin'].includes(u.role)))
      })
      .catch(() => message.error('Failed to load users'))
      .finally(() => setLoading(false))
  }, [])

  const pick = async (u: string) => {
    setSelected(u)
    try { const r = await api.get(`/users/authority-limits/${u}`); form.setFieldsValue(r.data || {}) }
    catch { form.resetFields() }
  }

  const save = async () => {
    setSaving(true)
    try { await api.post('/users/authority-limits', { username: selected, ...form.getFieldsValue() }); message.success('Authority limits saved') }
    catch(e:any) { message.error(e?.response?.data?.detail || 'Failed') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 24 }}>
      {/* User list */}
      <div>
        <div style={{ fontSize:11, color:'#6b7280', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:10 }}>
          Select User
        </div>
        {loading ? <Spin/> : users.length === 0
          ? <div style={{ color:'#6b7280', fontSize:13 }}>No underwriters found</div>
          : users.map(u => (
            <div key={u.username} onClick={() => pick(u.username)} style={{
              padding: '10px 14px', borderRadius: 8, cursor: 'pointer', marginBottom: 4,
              background: selected === u.username ? 'rgba(0,212,170,0.08)' : 'rgba(255,255,255,0.02)',
              border: `1px solid ${selected === u.username ? 'rgba(0,212,170,0.28)' : 'rgba(255,255,255,0.07)'}`,
              transition: 'all 0.15s',
            }}>
              <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                <Avatar username={u.username} role={u.role}/>
                <div>
                  <div style={{ fontSize:13, color: selected===u.username ? '#00d4aa' : '#e2e8f0', fontWeight:600 }}>{u.username}</div>
                  <div style={{ fontSize:11, color:'#6b7280' }}>{u.full_name || u.email}</div>
                </div>
              </div>
              <div style={{ marginTop:6 }}><RoleBadge role={u.role}/></div>
            </div>
          ))
        }
      </div>

      {/* Form */}
      <div>
        {!selected
          ? (
            <div style={{ color:'#6b7280', paddingTop:60, textAlign:'center', fontSize:13 }}>
              Select a user on the left to configure their authority limits
            </div>
          ) : (
            <>
              <div style={{ fontSize:15, fontWeight:600, color:'#e2e8f0', marginBottom:20 }}>
                Authority limits — <span style={{ color:'#00d4aa' }}>{selected}</span>
              </div>
              <Form form={form} layout="vertical" requiredMark={false}>
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
                  <Form.Item name="min_face_amount" label="Min Face Amount (₹)" help="Minimum case size this user can approve">
                    <InputNumber min={0} style={{ width:'100%' }} placeholder="e.g. 0"
                      formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                      parser={(v:any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
                  </Form.Item>
                  <Form.Item name="max_face_amount" label="Max Face Amount (₹)" extra="Leave blank = unlimited">
                    <InputNumber min={0} style={{ width:'100%' }}
                      formatter={v => v ? `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : ''}
                      parser={(v:any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
                  </Form.Item>
                </div>
                <Form.Item name="notes" label="Notes" help="Internal notes about this user's authority — visible to admins only">
                  <Input.TextArea rows={2} placeholder="e.g. Junior UW — cases above ₹50L require co-sign by Senior UW"/>
                </Form.Item>
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
                  <Form.Item name="is_medical_officer" valuePropName="checked" label=" ">
                    <Checkbox style={{ color:'#9ca3af' }}>Is Medical Officer</Checkbox>
                  </Form.Item>
                  <Form.Item name="can_assess_medical" valuePropName="checked" label=" ">
                    <Checkbox style={{ color:'#9ca3af' }}>Can Assess Medical (no referral)</Checkbox>
                  </Form.Item>
                </div>
                <Button type="primary" loading={saving} onClick={save} icon={<CheckOutlined/>}>
                  Save Authority Limits
                </Button>
              </Form>
            </>
          )
        }
      </div>
    </div>
  )
}

// ─── MFA Tab ───────────────────────────────────────────────────────────────────
const MFA_REQUIRED_ROLES = ['admin','super_admin','senior_underwriter']

function MFATab({ users, loading }: { users: User[], loading: boolean }) {
  const [setupUser, setSetupUser]   = useState<User|null>(null)
  const [setupData, setSetupData]   = useState<any>(null)
  const [setupLoading, setSetupLoading] = useState(false)
  const [verifyCode, setVerifyCode] = useState('')
  const [verifying, setVerifying]   = useState(false)

  const openSetup = async (u: User) => {
    setSetupUser(u); setSetupData(null); setVerifyCode(''); setSetupLoading(true)
    try { const r = await api.get(`/auth/mfa/setup/${u.username}`); setSetupData(r.data) }
    catch(e:any) { message.error(e?.response?.data?.detail || 'Failed to generate QR') }
    finally { setSetupLoading(false) }
  }

  const verifyAndEnable = async () => {
    if (!setupUser || !verifyCode) return
    setVerifying(true)
    try {
      await api.post(`/auth/mfa/enable/${setupUser.username}`, { totp_code: verifyCode })
      message.success(`MFA enabled for ${setupUser.username}`)
      setSetupUser(null); setSetupData(null); setVerifyCode('')
    } catch(e:any) { message.error(e?.response?.data?.detail || 'Invalid code') }
    finally { setVerifying(false) }
  }

  const disableMFA = async (username: string) => {
    try { await api.post(`/auth/mfa/disable/${username}`); message.success(`MFA disabled for ${username}`) }
    catch(e:any) { message.error(e?.response?.data?.detail || 'Failed') }
  }

  const cols = [
    {
      title: 'User', dataIndex: 'username', width: 220,
      render: (v: string, u: User) => (
        <div style={{ display:'flex', alignItems:'center', gap:10 }}>
          <Avatar username={v} role={u.role}/>
          <div>
            <div style={{ fontFamily:'var(--font-mono, monospace)', fontSize:13, color:'#e2e8f0', fontWeight:600 }}>{v}</div>
            <div style={{ fontSize:11, color:'#6b7280' }}>{u.email}</div>
          </div>
        </div>
      ),
    },
    { title:'Role', dataIndex:'role', width:160, render:(v:string)=><RoleBadge role={v}/> },
    {
      title: 'MFA Required', dataIndex: 'role', width: 140,
      render: (v: string) => MFA_REQUIRED_ROLES.includes(v)
        ? <span style={{ display:'inline-flex', alignItems:'center', gap:5, fontSize:12, color:'#c084fc' }}><SafetyOutlined/> Required</span>
        : <span style={{ fontSize:12, color:'#6b7280' }}>Optional</span>,
    },
    {
      title: 'Status', dataIndex: 'is_active', width: 100,
      render: (v: boolean) => (
        <span style={{ display:'inline-flex', alignItems:'center', gap:6, fontSize:12 }}>
          <span style={{ width:7, height:7, borderRadius:'50%', background: v?'#22c55e':'#ef4444', display:'inline-block' }}/>
          <span style={{ color: v?'#86efac':'#fca5a5' }}>{v ? 'Active' : 'Inactive'}</span>
        </span>
      ),
    },
    {
      title: 'Actions', width: 180,
      render: (_: any, u: User) => (
        <div style={{ display:'flex', gap:6 }}>
          <Button size="small" icon={<SafetyOutlined/>} onClick={() => openSetup(u)}
            style={{ borderColor:'rgba(192,132,252,0.25)', color:'#c084fc', background:'transparent' }}>
            Setup MFA
          </Button>
          <Popconfirm title={`Disable MFA for ${u.username}?`} onConfirm={() => disableMFA(u.username)} okText="Yes" cancelText="No">
            <Button size="small" danger>Disable</Button>
          </Popconfirm>
        </div>
      ),
    },
  ]

  return (
    <div>
      {/* Info banner */}
      <Alert
        message="TOTP MFA (Google Authenticator / Authy) is enforced per role. Click 'Setup MFA' to generate a QR code for any user."
        type="info" showIcon
        style={{ marginBottom:20, background:'rgba(0,212,170,0.05)', border:'1px solid rgba(0,212,170,0.18)' }}
      />

      {/* Required roles card */}
      <div style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:10, padding:'16px 20px', marginBottom:20 }}>
        <div style={{ fontSize:12, fontWeight:600, color:'#6b7280', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:12 }}>
          MFA Required Roles
        </div>
        <div style={{ display:'flex', gap:10, flexWrap:'wrap' }}>
          {MFA_REQUIRED_ROLES.map(r => (
            <span key={r} style={{ ...roleBadgeStyle[r], display:'inline-flex', alignItems:'center', gap:6, padding:'4px 12px', borderRadius:6, fontSize:12 }}>
              <SafetyOutlined style={{ fontSize:11 }}/>{r.replace(/_/g,' ')}
            </span>
          ))}
        </div>
        <div style={{ fontSize:12, color:'#4b5563', marginTop:10 }}>
          Configure in System Config → Auth / MFA to change which roles require MFA.
        </div>
      </div>

      {loading
        ? <div style={{ display:'flex', justifyContent:'center', padding:'40px 0' }}><Spin/></div>
        : <Table dataSource={users} columns={cols} rowKey="username" size="middle" pagination={false}/>
      }

      {/* QR Code Modal */}
      <Modal
        title={<span style={{ color:'#e2e8f0', fontWeight:600 }}>Setup MFA — {setupUser?.username}</span>}
        open={!!setupUser}
        onCancel={() => { setSetupUser(null); setSetupData(null); setVerifyCode('') }}
        footer={null} width={480} styles={MS}
      >
        {setupLoading
          ? <div style={{ display:'flex', justifyContent:'center', padding:'40px 0' }}><Spin size="large"/></div>
          : setupData
            ? (
              <div style={{ textAlign:'center', padding:'8px 0' }}>
                <div style={{ fontSize:13, color:'#9ca3af', marginBottom:20, lineHeight:1.7 }}>
                  Scan this QR code with <strong style={{ color:'#e2e8f0' }}>Google Authenticator</strong> or <strong style={{ color:'#e2e8f0' }}>Authy</strong>.<br/>
                  Then enter the 6-digit code to verify and activate MFA.
                </div>

                {setupData.qr_base64
                  ? (
                    <div style={{ display:'inline-block', padding:12, background:'#fff', borderRadius:12, marginBottom:20 }}>
                      <img src={`data:image/png;base64,${setupData.qr_base64}`} alt="MFA QR Code" style={{ width:200, height:200, display:'block' }}/>
                    </div>
                  ) : (
                    <div style={{ background:'rgba(255,255,255,0.04)', border:'1px dashed rgba(255,255,255,0.15)', borderRadius:12, padding:20, marginBottom:20 }}>
                      <div style={{ fontSize:11, color:'#6b7280', marginBottom:8 }}>QR image unavailable — enter this URI manually:</div>
                      <div style={{ fontFamily:'var(--font-mono, monospace)', fontSize:10, color:'#00d4aa', wordBreak:'break-all', lineHeight:1.6 }}>{setupData.uri}</div>
                    </div>
                  )
                }

                <div style={{ background:'rgba(255,255,255,0.03)', border:'1px solid rgba(255,255,255,0.08)', borderRadius:8, padding:'10px 14px', marginBottom:20, textAlign:'left' }}>
                  <div style={{ fontSize:11, color:'#6b7280', marginBottom:4 }}>Or enter this secret key manually:</div>
                  <div style={{ fontFamily:'var(--font-mono, monospace)', fontSize:14, color:'#00d4aa', letterSpacing:'0.15em', fontWeight:700 }}>{setupData.secret}</div>
                </div>

                <div style={{ display:'flex', gap:10, justifyContent:'center' }}>
                  <Input
                    value={verifyCode}
                    onChange={e => setVerifyCode(e.target.value.replace(/\D/g,'').slice(0,6))}
                    placeholder="6-digit code" maxLength={6}
                    style={{ width:160, fontFamily:'var(--font-mono, monospace)', fontSize:20, textAlign:'center', letterSpacing:'0.2em' }}
                    onPressEnter={verifyAndEnable}
                  />
                  <Button type="primary" loading={verifying} onClick={verifyAndEnable} disabled={verifyCode.length !== 6}>
                    Verify &amp; Enable
                  </Button>
                </div>

                {setupData.is_enabled && setupData.is_verified && (
                  <div style={{ marginTop:16 }}>
                    <Tag color="success" style={{ fontSize:12, padding:'4px 12px' }}>MFA is currently enabled for this user</Tag>
                  </div>
                )}
              </div>
            )
            : null
        }
      </Modal>
    </div>
  )
}

// ─── Role Reference Tab ────────────────────────────────────────────────────────
function RoleReferenceTab() {
  return (
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
      {ROLES.map(role => (
        <div key={role} style={{ background:'rgba(255,255,255,0.02)', border:'1px solid rgba(255,255,255,0.07)', borderRadius:12, padding:'16px 20px' }}>
          <div style={{ marginBottom:10 }}><RoleBadge role={role}/></div>
          <div style={{ fontSize:12, color:'#9ca3af', marginBottom:10 }}>{roleDesc[role]}</div>
          <ul style={{ margin:0, paddingLeft:16 }}>
            {rolePerms[role].map((p,i) => (
              <li key={i} style={{ fontSize:12, color:'#6b7280', marginBottom:3 }}>{p}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

// ─── Page Shell ────────────────────────────────────────────────────────────────
export default function UserManagementPage() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [allUsers, setAllUsers]     = useState<User[]>([])
  const [allLoading, setAllLoading] = useState(true)

  useEffect(() => {
    setAllLoading(true)
    api.get('/auth/users')
      .then(r => setAllUsers(Array.isArray(r.data) ? r.data : []))
      .catch(e => message.error('Failed to load users: ' + (e?.response?.data?.detail || e.message)))
      .finally(() => setAllLoading(false))
  }, [refreshKey])

  const tabs = [
    {
      key: 'users',
      label: <span style={{ display:'inline-flex', alignItems:'center', gap:7 }}><SafetyCertificateOutlined/>Role Reference</span>,
      children: <AllUsersTab refresh={refreshKey}/>,
    },
    {
      key: 'create',
      label: <span style={{ display:'inline-flex', alignItems:'center', gap:7 }}><PlusOutlined/>Create User</span>,
      children: <CreateUserTab onCreated={() => setRefreshKey(k => k+1)}/>,
    },
    {
      key: 'authority',
      label: <span style={{ display:'inline-flex', alignItems:'center', gap:7 }}><KeyOutlined/>Authority Limits</span>,
      children: <AuthorityLimitsTab/>,
    },
    {
      key: 'mfa',
      label: <span style={{ display:'inline-flex', alignItems:'center', gap:7 }}><LockOutlined/>MFA Settings</span>,
      children: <MFATab users={allUsers} loading={allLoading}/>,
    },
    {
      key: 'roles',
      label: <span style={{ display:'inline-flex', alignItems:'center', gap:7 }}><SafetyCertificateOutlined/>Role Reference</span>,
      children: <RoleReferenceTab/>,
    },
  ]

  return (
    <div style={{ padding:'32px 36px' }}>
      <div style={{ marginBottom:24, display:'flex', alignItems:'flex-start', justifyContent:'space-between' }}>
        <div>
          <h1 style={{ fontWeight:700, fontSize:20, color:'#e2e8f0', margin:0, letterSpacing:'-0.02em', display:'flex', alignItems:'center', gap:10 }}>
            <TeamOutlined style={{ color:'#00d4aa' }}/>User Management
          </h1>
          <p style={{ color:'#6b7280', fontSize:13, marginTop:4, marginBottom:0 }}>
            Manage platform users, roles, access control, and underwriting authority limits.
          </p>
        </div>
      </div>
      <Tabs
        defaultActiveKey="users"
        items={tabs}
        tabBarStyle={{ borderBottom:'1px solid rgba(255,255,255,0.07)', marginBottom:24 }}
      />
    </div>
  )
}
