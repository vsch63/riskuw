import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Modal, Form, Input, Select,
  Switch, Spin, message, Popconfirm, Tabs, InputNumber,
  Alert, Checkbox,
} from 'antd'
import {
  PlusOutlined, EditOutlined, StopOutlined, CheckOutlined,
  KeyOutlined, ReloadOutlined, UserOutlined, SafetyOutlined,
  TeamOutlined, LockOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAuthStore } from '../context/authStore'

const { Option } = Select

const ROLES = ['super_admin','admin','senior_underwriter','underwriter','api_client','readonly']
const roleColor: Record<string,string> = {
  super_admin:'purple', admin:'purple', senior_underwriter:'gold',
  underwriter:'cyan', api_client:'blue', readonly:'default',
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

interface User { username: string; email: string; full_name?: string; role: string; is_active: boolean; last_login_at?: string }
interface AuthLim { username: string; min_face_amount: number; max_face_amount?: number; notes?: string; is_medical_officer?: boolean; can_assess_medical?: boolean }

const MS = {
  content: { background: '#0f2044', border: '1px solid rgba(255,255,255,0.1)' },
  header:  { background: '#0f2044' },
  footer:  { background: '#0f2044' },
}

function AllUsersTab({ refresh }: { refresh: number }) {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [roleFilter, setRole] = useState('ALL')
  const [statusFilter, setStat] = useState('ALL')
  const [editUser, setEdit] = useState<User|null>(null)
  const [pwUser, setPw] = useState<User|null>(null)
  const [sub, setSub] = useState(false)
  const [ef] = Form.useForm()
  const [pf] = Form.useForm()
  const { user: me } = useAuthStore()

  const load = async () => { setLoading(true); try { const r = await api.get('/auth/users'); setUsers(Array.isArray(r.data)?r.data:[]) } catch { message.error('Failed') } finally { setLoading(false) } }
  useEffect(() => { load() }, [refresh])

  const filtered = users.filter(u => {
    const rOk = roleFilter==='ALL'||u.role===roleFilter
    const sOk = statusFilter==='ALL'||(statusFilter==='ACTIVE'&&u.is_active)||(statusFilter==='INACTIVE'&&!u.is_active)
    return rOk&&sOk
  })

  const openEdit = (u: User) => { setEdit(u); ef.setFieldsValue({ email: u.email, full_name: u.full_name, role: u.role }) }
  const doEdit = async () => { if(!editUser) return; setSub(true); try { const v=ef.getFieldsValue(); if(v.role!==editUser.role) await api.post(`/auth/users/${editUser.username}/change-role`,{role:v.role}); await api.patch(`/auth/users/${editUser.username}`,{email:v.email,full_name:v.full_name}); message.success('Updated'); setEdit(null); load() } catch(e:any){message.error(e?.response?.data?.detail||'Failed')} finally{setSub(false)} }
  const doPw = async () => { if(!pwUser) return; await pf.validateFields().catch(()=>{throw new Error}); setSub(true); try { const v=pf.getFieldsValue(); await api.post(`/auth/users/${pwUser.username}/reset-password`,{new_password:v.np,actor_username:me?.username}); message.success('Password reset'); setPw(null); pf.resetFields() } catch(e:any){message.error(e?.response?.data?.detail||'Failed')} finally{setSub(false)} }
  const toggle = async (u: User) => { try { await api.post(`/auth/users/${u.username}/${u.is_active?'deactivate':'activate'}`); message.success('Done'); load() } catch { message.error('Failed') } }

  const cols = [
    { title:'Username', dataIndex:'username', render:(v:string,u:User)=><div><div style={{fontFamily:'var(--font-mono)',fontSize:13,color:'var(--teal-400)'}}><UserOutlined style={{marginRight:6}}/>{v}</div>{u.last_login_at&&<div style={{fontSize:10,color:'var(--slate-500)'}}>Last: {u.last_login_at.slice(0,10)}</div>}</div> },
    { title:'Full Name', dataIndex:'full_name', render:(v:string)=>v||<span style={{color:'var(--slate-500)'}}>—</span> },
    { title:'Email', dataIndex:'email', render:(v:string)=><span style={{fontSize:12}}>{v}</span> },
    { title:'Role', dataIndex:'role', render:(v:string)=><Tag color={roleColor[v]||'default'} style={{fontFamily:'var(--font-mono)',fontSize:10,fontWeight:700}}>{v?.replace(/_/g,' ').toUpperCase()}</Tag> },
    { title:'Status', dataIndex:'is_active', render:(v:boolean)=><Tag color={v?'success':'error'}>{v?'Active':'Inactive'}</Tag> },
    { title:'Actions', render:(_:any,u:User)=><div style={{display:'flex',gap:6}}>
        <Button size="small" icon={<EditOutlined/>} onClick={()=>openEdit(u)} style={{borderColor:'rgba(0,212,170,0.3)',color:'var(--teal-400)'}}/>
        <Button size="small" icon={<KeyOutlined/>} onClick={()=>setPw(u)} style={{borderColor:'rgba(251,191,36,0.3)',color:'#fbbf24'}}/>
        <Popconfirm title={`${u.is_active?'Deactivate':'Activate'} ${u.username}?`} onConfirm={()=>toggle(u)} okText="Yes" cancelText="No">
          <Button size="small" icon={u.is_active?<StopOutlined/>:<CheckOutlined/>} style={{borderColor:u.is_active?'rgba(239,68,68,0.3)':'rgba(34,197,94,0.3)',color:u.is_active?'#f87171':'#4ade80'}}/>
        </Popconfirm>
      </div> },
  ]

  return <>
    <div style={{display:'grid',gridTemplateColumns:'repeat(5,1fr)',gap:12,marginBottom:20}}>
      {[{l:'Total Users',v:users.length,c:'#00d4aa'},{l:'Active',v:users.filter(u=>u.is_active).length,c:'#22c55e'},{l:'Inactive',v:users.filter(u=>!u.is_active).length,c:'#ef4444'},{l:'With Cases',v:0,c:'#94a3b8'},{l:'Locked 🔒',v:0,c:'#94a3b8'}].map(m=>(
        <div key={m.l} style={{background:'rgba(255,255,255,0.03)',border:'1px solid rgba(255,255,255,0.08)',borderRadius:10,padding:'12px 16px'}}>
          <div style={{fontFamily:'var(--font-mono)',fontSize:20,fontWeight:700,color:m.c}}>{m.v}</div>
          <div style={{fontSize:11,color:'var(--slate-500)',marginTop:4}}>{m.l}</div>
        </div>
      ))}
    </div>
    <div style={{display:'flex',gap:12,marginBottom:16}}>
      <div style={{flex:1}}><div style={{fontSize:11,color:'var(--slate-500)',marginBottom:4}}>Filter by role</div>
        <Select value={roleFilter} onChange={setRole} style={{width:'100%'}}><Option value="ALL">All</Option>{ROLES.map(r=><Option key={r} value={r}>{r.replace(/_/g,' ')}</Option>)}</Select></div>
      <div style={{flex:1}}><div style={{fontSize:11,color:'var(--slate-500)',marginBottom:4}}>Filter by status</div>
        <Select value={statusFilter} onChange={setStat} style={{width:'100%'}}><Option value="ALL">All</Option><Option value="ACTIVE">Active</Option><Option value="INACTIVE">Inactive</Option></Select></div>
      <div style={{display:'flex',alignItems:'flex-end'}}><Button icon={<ReloadOutlined/>} onClick={load} loading={loading}/></div>
    </div>
    {loading?<Spin size="large"/>:<Table dataSource={filtered} columns={cols} rowKey="username" size="middle" pagination={{pageSize:15}}/>}
    <Modal title={<span style={{color:'#fff'}}>Edit — {editUser?.username}</span>} open={!!editUser} onCancel={()=>setEdit(null)} onOk={doEdit} confirmLoading={sub} okText="Save" styles={MS}>
      <Form form={ef} layout="vertical" style={{marginTop:16}}>
        <Form.Item name="full_name" label="Full Name"><Input/></Form.Item>
        <Form.Item name="email" label="Email" rules={[{type:'email'}]}><Input/></Form.Item>
        <Form.Item name="role" label="Role"><Select>{ROLES.map(r=><Option key={r} value={r}>{r.replace(/_/g,' ')}</Option>)}</Select></Form.Item>
      </Form>
    </Modal>
    <Modal title={<span style={{color:'#fff'}}>Reset Password — {pwUser?.username}</span>} open={!!pwUser} onCancel={()=>setPw(null)} onOk={doPw} confirmLoading={sub} okText="Reset" styles={MS}>
      <Form form={pf} layout="vertical" style={{marginTop:16}}>
        <Form.Item name="np" label="New Password" rules={[{required:true,min:8}]}><Input.Password/></Form.Item>
        <Form.Item name="c" label="Confirm" dependencies={['np']} rules={[{required:true},{validator:(_,v)=>pf.getFieldValue('np')===v?Promise.resolve():Promise.reject('Mismatch')}]}><Input.Password/></Form.Item>
      </Form>
    </Modal>
  </>
}

function CreateUserTab({ onCreated }: { onCreated: () => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [selectedRole, setSelectedRole] = useState('underwriter')
  const { user: me } = useAuthStore()

  const UW_ROLES = ['underwriter', 'senior_underwriter', 'admin']
  const showAuthority = UW_ROLES.includes(selectedRole)

  const go = async () => {
    try {
      await form.validateFields()
    } catch {
      return
    }
    setLoading(true)
    try {
      const v = form.getFieldsValue()

      // Validate confirm password
      if (v.password !== v.confirm_password) {
        message.error('Passwords do not match')
        setLoading(false)
        return
      }

      // 1. Create the user
      await api.post('/auth/register', {
        username:       v.username,
        full_name:      v.full_name,
        email:          v.email,
        password:       v.password,
        role:           v.role,
        effective_date: v.effective_date || null,
        expiry_date:    v.expiry_date || null,
        tenant_id:      (me as any)?.tenant_id,
      })

      // 2. Optionally save authority limits if role supports it
      if (showAuthority && (v.min_face_amount || v.max_face_amount || v.notes)) {
        try {
          const products = v.product_codes
            ? v.product_codes.split(',').map((s: string) => s.trim()).filter(Boolean)
            : []
          await api.post('/users/authority-limits', {
            username:        v.username,
            min_face_amount: v.min_face_amount || 0,
            max_face_amount: v.max_face_amount || null,
            product_codes:   products,
            notes:           v.notes || null,
            is_medical_officer: false,
          })
        } catch {
          // Non-fatal — user was created, limits can be set later
          message.warning(`User created but authority limits failed — set them in Authority Limits tab`)
        }
      }

      message.success(`✅ User ${v.username} created successfully`)
      form.resetFields()
      setSelectedRole('underwriter')
      onCreated()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Failed to create user')
    } finally {
      setLoading(false)
    }
  }

  const labelStyle: React.CSSProperties = {
    color: 'var(--slate-300)', fontSize: 13, fontWeight: 500,
  }
  const sectionStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.02)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 10, padding: '20px 24px', marginBottom: 16,
  }

  return (
    <div style={{ maxWidth: 900 }}>
      <Alert
        message="New users can log in immediately. MFA-required roles will be prompted to enrol on first login."
        type="info" showIcon
        style={{ marginBottom: 20, background: 'rgba(0,212,170,0.05)', border: '1px solid rgba(0,212,170,0.2)' }}
      />

      <Form form={form} layout="vertical" requiredMark={false}>

        {/* ── Account Details ── */}
        <div style={sectionStyle}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

            {/* Left column */}
            <div>
              <Form.Item name="username" label={<span style={labelStyle}>Username *</span>}
                rules={[{ required: true, message: 'Username is required' },
                        { pattern: /^[a-z0-9._-]+$/, message: 'Lowercase, numbers, dots, dashes only' }]}>
                <Input placeholder="e.g. jsmith" prefix={<UserOutlined style={{ color: 'var(--slate-500)' }}/>}/>
              </Form.Item>

              <Form.Item name="full_name" label={<span style={labelStyle}>Full Name *</span>}
                rules={[{ required: true, message: 'Full name is required' }]}>
                <Input placeholder="e.g. John Smith"/>
              </Form.Item>

              <Form.Item name="email" label={<span style={labelStyle}>Email *</span>}
                rules={[{ required: true, type: 'email', message: 'Valid email required' }]}>
                <Input placeholder="jsmith@carrier.com"/>
              </Form.Item>

              <Form.Item name="role" label={<span style={labelStyle}>Role *</span>}
                initialValue="underwriter" rules={[{ required: true }]}>
                <Select onChange={(v) => setSelectedRole(v)}>
                  {ROLES.map(r => (
                    <Option key={r} value={r}>
                      <Tag color={roleColor[r]} style={{ fontSize: 10, marginRight: 6 }}>
                        {r.replace(/_/g, ' ')}
                      </Tag>
                      — {roleDesc[r]}
                    </Option>
                  ))}
                </Select>
              </Form.Item>

              {/* Role permissions hint */}
              {selectedRole && (
                <div style={{ background: 'rgba(0,212,170,0.05)', border: '1px solid rgba(0,212,170,0.15)',
                  borderRadius: 8, padding: '8px 12px', marginBottom: 8 }}>
                  <div style={{ fontSize: 11, color: 'var(--slate-500)', marginBottom: 4 }}>Permissions</div>
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {rolePerms[selectedRole]?.map((p, i) => (
                      <li key={i} style={{ fontSize: 11, color: 'var(--slate-400)' }}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Right column */}
            <div>
              <Form.Item name="password" label={<span style={labelStyle}>Password *</span>}
                rules={[{ required: true, min: 8, message: 'Min 8 characters' }]}>
                <Input.Password placeholder="Min 8 characters" prefix={<LockOutlined style={{ color: 'var(--slate-500)' }}/>}/>
              </Form.Item>

              <Form.Item name="confirm_password" label={<span style={labelStyle}>Confirm Password *</span>}
                dependencies={['password']}
                rules={[
                  { required: true, message: 'Please confirm password' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue('password') === value) return Promise.resolve()
                      return Promise.reject(new Error('Passwords do not match'))
                    },
                  }),
                ]}>
                <Input.Password placeholder="Repeat password" prefix={<LockOutlined style={{ color: 'var(--slate-500)' }}/>}/>
              </Form.Item>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Form.Item name="effective_date" label={<span style={labelStyle}>Account Effective Date</span>}>
                  <Input type="date"/>
                </Form.Item>
                <Form.Item name="expiry_date" label={<span style={labelStyle}>Account Expiry Date</span>}>
                  <Input type="date"/>
                </Form.Item>
              </div>
            </div>
          </div>
        </div>

        {/* ── Authority Limits (only for UW roles) ── */}
        {showAuthority && (
          <div style={sectionStyle}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--slate-300)', marginBottom: 16 }}>
              🎯 Authority Limits <span style={{ fontSize: 11, color: 'var(--slate-500)', fontWeight: 400 }}>
                (optional — can also set later via All Users → Set Authority)
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <Form.Item name="min_face_amount" label={<span style={labelStyle}>Min face amount ($)</span>} initialValue={0}>
                <InputNumber min={0} style={{ width: '100%' }}
                  formatter={v => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                  parser={(v: any) => Number(v!.replace(/,*/g, ''))}/>
              </Form.Item>
              <Form.Item name="max_face_amount" label={<span style={labelStyle}>Max face amount ($)</span>} initialValue={0}>
                <InputNumber min={0} style={{ width: '100%' }}
                  formatter={v => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                  parser={(v: any) => Number(v!.replace(/,*/g, ''))}/>
              </Form.Item>
            </div>
            <Form.Item name="product_codes"
              label={<span style={labelStyle}>Restrict to products <span style={{ color: 'var(--slate-500)' }}>(comma-separated, blank = all)</span></span>}>
              <Input placeholder="e.g. IND-TERM-10, IND-TERM-20"/>
            </Form.Item>
            <Form.Item name="notes" label={<span style={labelStyle}>Authority Notes</span>}>
              <Input.TextArea rows={3}
                placeholder="e.g. Junior UW — cases above ₹50L must be co-signed by Senior UW. Non-medical products only."/>
            </Form.Item>
          </div>
        )}

        <Button type="primary" icon={<PlusOutlined/>} loading={loading}
          onClick={go} size="large" block
          style={{ height: 44, fontSize: 15, fontWeight: 600 }}>
          Create User
        </Button>
      </Form>
    </div>
  )
}
function MFATab({ users, loading }: { users: User[], loading: boolean }) {
  const [setupUser, setSetupUser] = useState<User|null>(null)
  const [setupData, setSetupData] = useState<any>(null)
  const [setupLoading, setSetupLoading] = useState(false)
  const [verifyCode, setVerifyCode] = useState('')
  const [verifying, setVerifying] = useState(false)

  const openSetup = async (u: User) => {
    setSetupUser(u); setSetupData(null); setVerifyCode(''); setSetupLoading(true)
    try {
      const r = await api.get(`/auth/mfa/setup/${u.username}`)
      setSetupData(r.data)
    } catch (e: any) { message.error(e?.response?.data?.detail || 'Failed to generate QR') }
    finally { setSetupLoading(false) }
  }

  const verifyAndEnable = async () => {
    if (!setupUser || !verifyCode) return
    setVerifying(true)
    try {
      await api.post(`/auth/mfa/enable/${setupUser.username}`, { totp_code: verifyCode })
      message.success(`✅ MFA enabled for ${setupUser.username}`)
      setSetupUser(null); setSetupData(null); setVerifyCode('')
    } catch (e: any) { message.error(e?.response?.data?.detail || 'Invalid code') }
    finally { setVerifying(false) }
  }

  const disableMFA = async (username: string) => {
    try {
      await api.post(`/auth/mfa/disable/${username}`)
      message.success(`MFA disabled for ${username}`)
    } catch (e: any) { message.error(e?.response?.data?.detail || 'Failed') }
  }

  return <div>
    <Alert message="TOTP MFA (Google Authenticator / Authy) is enforced per role. Click 'Setup MFA' to generate a QR code for any user." type="info" showIcon style={{marginBottom:20,background:'rgba(0,212,170,0.05)',border:'1px solid rgba(0,212,170,0.2)'}}/>

    <div style={{background:'rgba(255,255,255,0.03)',border:'1px solid rgba(255,255,255,0.08)',borderRadius:10,padding:'16px 20px',marginBottom:20}}>
      <div style={{fontSize:13,fontWeight:700,color:'#fff',marginBottom:12}}>MFA Required Roles</div>
      <div style={{display:'flex',gap:10,flexWrap:'wrap'}}>
        {['admin','super_admin','senior_underwriter'].map(r=><Tag key={r} color="purple" style={{fontFamily:'var(--font-mono)',fontSize:11,padding:'4px 10px'}}><SafetyOutlined style={{marginRight:6}}/>{r.replace(/_/g,' ')}</Tag>)}
      </div>
      <div style={{fontSize:12,color:'var(--slate-500)',marginTop:10}}>Configure in System Config → Auth / MFA to change which roles require MFA.</div>
    </div>

    {loading ? <Spin/> : (
      <Table dataSource={users} rowKey="username" size="middle" pagination={false}
        columns={[
          {title:'Username',dataIndex:'username',render:(v:string)=><span style={{fontFamily:'var(--font-mono)',color:'var(--teal-400)'}}>{v}</span>},
          {title:'Role',dataIndex:'role',render:(v:string)=><Tag color={roleColor[v]} style={{fontSize:10}}>{v.replace(/_/g,' ')}</Tag>},
          {title:'MFA Required',dataIndex:'role',render:(v:string)=>['admin','super_admin','senior_underwriter'].includes(v)?<Tag color="purple"><SafetyOutlined/> Required</Tag>:<Tag color="default">Optional</Tag>},
          {title:'Status',dataIndex:'is_active',render:(v:boolean)=><Tag color={v?'success':'error'}>{v?'Active':'Inactive'}</Tag>},
          {title:'Actions',render:(_:any,u:User)=>(
            <div style={{display:'flex',gap:6}}>
              <Button size="small" icon={<SafetyOutlined/>} onClick={()=>openSetup(u)}
                style={{borderColor:'rgba(192,132,252,0.3)',color:'#c084fc'}}>
                Setup MFA
              </Button>
              <Popconfirm title={`Disable MFA for ${u.username}?`} onConfirm={()=>disableMFA(u.username)} okText="Yes" cancelText="No">
                <Button size="small" danger>Disable</Button>
              </Popconfirm>
            </div>
          )},
        ]}
      />
    )}

    {/* QR Code Modal */}
    <Modal
      title={<span style={{color:'#fff',fontFamily:'var(--font-display)',fontWeight:700}}>
        Setup MFA — {setupUser?.username}
      </span>}
      open={!!setupUser}
      onCancel={()=>{setSetupUser(null);setSetupData(null);setVerifyCode('')}}
      footer={null}
      width={480}
      styles={{content:{background:'#0f2044',border:'1px solid rgba(255,255,255,0.1)'},header:{background:'#0f2044'}}}
    >
      {setupLoading ? (
        <div style={{display:'flex',justifyContent:'center',padding:'40px 0'}}><Spin size="large"/></div>
      ) : setupData ? (
        <div style={{textAlign:'center',padding:'8px 0'}}>
          <div style={{fontSize:13,color:'var(--slate-400)',marginBottom:20,lineHeight:1.7}}>
            Scan this QR code with <strong style={{color:'#fff'}}>Google Authenticator</strong> or <strong style={{color:'#fff'}}>Authy</strong>.<br/>
            Then enter the 6-digit code below to verify and activate MFA.
          </div>

          {/* QR Code image */}
          {setupData.qr_base64 ? (
            <div style={{display:'inline-block',padding:12,background:'#fff',borderRadius:12,marginBottom:20}}>
              <img src={`data:image/png;base64,${setupData.qr_base64}`}
                alt="MFA QR Code" style={{width:200,height:200,display:'block'}}/>
            </div>
          ) : (
            <div style={{background:'rgba(255,255,255,0.05)',border:'1px dashed rgba(255,255,255,0.2)',
              borderRadius:12,padding:'20px',marginBottom:20}}>
              <div style={{fontSize:11,color:'var(--slate-500)',marginBottom:8}}>
                QR image unavailable — enter this URI manually in your authenticator:
              </div>
              <div style={{fontFamily:'var(--font-mono)',fontSize:10,color:'var(--teal-400)',
                wordBreak:'break-all',lineHeight:1.6}}>
                {setupData.uri}
              </div>
            </div>
          )}

          {/* Manual secret */}
          <div style={{background:'rgba(255,255,255,0.04)',border:'1px solid rgba(255,255,255,0.1)',
            borderRadius:8,padding:'10px 14px',marginBottom:20,textAlign:'left'}}>
            <div style={{fontSize:11,color:'var(--slate-500)',marginBottom:4}}>
              Or enter this secret key manually:
            </div>
            <div style={{fontFamily:'var(--font-mono)',fontSize:14,color:'var(--teal-400)',
              letterSpacing:'0.15em',fontWeight:700}}>
              {setupData.secret}
            </div>
          </div>

          {/* Verify input */}
          <div style={{display:'flex',gap:10,justifyContent:'center'}}>
            <Input
              value={verifyCode}
              onChange={e=>setVerifyCode(e.target.value.replace(/\D/g,'').slice(0,6))}
              placeholder="Enter 6-digit code"
              maxLength={6}
              style={{width:180,fontFamily:'var(--font-mono)',fontSize:20,
                textAlign:'center',letterSpacing:'0.2em'}}
              onPressEnter={verifyAndEnable}
            />
            <Button type="primary" loading={verifying}
              onClick={verifyAndEnable}
              disabled={verifyCode.length !== 6}>
              Verify &amp; Enable
            </Button>
          </div>

          {setupData.is_enabled && setupData.is_verified && (
            <div style={{marginTop:16}}>
              <Tag color="success" style={{fontSize:12,padding:'4px 12px'}}>
                ✅ MFA is currently ENABLED for this user
              </Tag>
            </div>
          )}
        </div>
      ) : null}
    </Modal>
  </div>
}

function AuthorityLimitsTab() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState('')
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('/auth/users')
      .then(r => {
        const u = Array.isArray(r.data) ? r.data : []
        setUsers(u.filter((u: User) => ['underwriter', 'senior_underwriter', 'admin'].includes(u.role)))
      })
      .catch(() => message.error('Failed to load users'))
      .finally(() => setLoading(false))
  }, [])

  const pick = async (u: string) => {
    setSelected(u)
    try {
      const r = await api.get(`/users/authority-limits/${u}`)
      form.setFieldsValue(r.data || {})
    } catch {
      form.resetFields()
    }
  }

  const save = async () => {
    setSaving(true)
    try {
      await api.post('/users/authority-limits', { username: selected, ...form.getFieldsValue() })
      message.success('Saved')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 24 }}>
      <div>
        <div style={{ fontSize: 11, color: 'var(--slate-500)', fontWeight: 700,
          textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>
          Select Underwriter
        </div>
        {loading ? <Spin/> : users.map(u => (
          <div key={u.username} onClick={() => pick(u.username)}
            style={{ padding: '10px 14px', borderRadius: 8, cursor: 'pointer', marginBottom: 4,
              background: selected === u.username ? 'rgba(0,212,170,0.12)' : 'rgba(255,255,255,0.03)',
              border: `1px solid ${selected === u.username ? 'rgba(0,212,170,0.3)' : 'rgba(255,255,255,0.08)'}` }}>
            <div style={{ fontSize: 13, color: selected === u.username ? 'var(--teal-400)' : '#fff', fontWeight: 600 }}>
              {u.username}
            </div>
            <div style={{ fontSize: 11, color: 'var(--slate-500)' }}>{u.full_name || u.email}</div>
            <Tag color={roleColor[u.role]} style={{ fontSize: 9, marginTop: 4 }}>
              {u.role.replace(/_/g, ' ')}
            </Tag>
          </div>
        ))}
      </div>
      <div>
        {!selected ? (
          <div style={{ color: 'var(--slate-500)', paddingTop: 40, textAlign: 'center' }}>
            Select an underwriter to set their authority limits
          </div>
        ) : (
          <>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#fff', marginBottom: 20 }}>
              Authority limits — {selected}
            </div>
            <Form form={form} layout="vertical" requiredMark={false}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Form.Item name="min_face_amount" label="Min Face Amount (₹)">
                  <InputNumber min={0} style={{ width: '100%' }}
                    formatter={v => `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                    parser={(v: any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
                </Form.Item>
                <Form.Item name="max_face_amount" label="Max Face Amount (₹)" extra="Leave blank = unlimited">
                  <InputNumber min={0} style={{ width: '100%' }}
                    formatter={v => v ? `₹ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : ''}
                    parser={(v: any) => Number(v!.replace(/₹\s?|(,*)/g, ''))}/>
                </Form.Item>
              </div>
              <Form.Item name="notes" label="Notes">
                <Input.TextArea rows={2}/>
              </Form.Item>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Form.Item name="is_medical_officer" valuePropName="checked" label=" ">
                  <Checkbox style={{ color: 'var(--slate-300)' }}>Is Medical Officer</Checkbox>
                </Form.Item>
                <Form.Item name="can_assess_medical" valuePropName="checked" label=" ">
                  <Checkbox style={{ color: 'var(--slate-300)' }}>Can Assess Medical (no referral)</Checkbox>
                </Form.Item>
              </div>
              <Button type="primary" loading={saving} onClick={save}>Save Authority Limits</Button>
            </Form>
          </>
        )}
      </div>
    </div>
  )
}

function RoleReferenceTab() {
  return <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16}}>
    {ROLES.map(role=><div key={role} style={{background:'rgba(255,255,255,0.03)',border:'1px solid rgba(255,255,255,0.08)',borderRadius:12,padding:'16px 20px'}}>
      <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:12}}>
        <Tag color={roleColor[role]} style={{fontFamily:'var(--font-mono)',fontSize:11,fontWeight:700,padding:'3px 10px'}}>{role.replace(/_/g,' ').toUpperCase()}</Tag>
      </div>
      <div style={{fontSize:12,color:'var(--slate-400)',marginBottom:8}}>{roleDesc[role]}</div>
      <ul style={{margin:0,paddingLeft:16}}>{rolePerms[role].map((p,i)=><li key={i} style={{fontSize:12,color:'var(--slate-300)',marginBottom:4}}>{p}</li>)}</ul>
    </div>)}
  </div>
}

export default function UserManagementPage() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [allUsers, setAllUsers] = useState<User[]>([])
  const [allLoading, setAllLoading] = useState(true)

  useEffect(() => {
    setAllLoading(true)
    api.get('/auth/users')
      .then(r => setAllUsers(Array.isArray(r.data) ? r.data : []))
      .catch(() => {})
      .finally(() => setAllLoading(false))
  }, [refreshKey])
  const tabs = [
    { key:'users',     label:'👥 All Users',        children:<AllUsersTab refresh={refreshKey}/> },
    { key:'create',    label:'➕ Create User',       children:<CreateUserTab onCreated={()=>setRefreshKey(k=>k+1)}/> },
    { key:'authority', label:'🎯 Authority Limits',  children:<AuthorityLimitsTab/> },
    { key:'mfa',       label:'🔐 MFA Settings',     children:<MFATab users={allUsers} loading={allLoading}/> },
    { key:'roles',     label:'🛡️ Role Reference',   children:<RoleReferenceTab/> },
  ]
  return <div style={{padding:'32px 36px'}}>
    <div style={{marginBottom:24}}>
      <h1 style={{fontFamily:'var(--font-display)',fontWeight:700,fontSize:22,color:'#fff',margin:0,letterSpacing:'-0.02em'}}>
        <TeamOutlined style={{color:'var(--teal-400)',marginRight:10}}/>User Management
      </h1>
      <p style={{color:'var(--slate-500)',fontSize:13,marginTop:4,marginBottom:0}}>
        Manage platform users, roles, access control, and underwriting authority limits.
      </p>
    </div>
    <Tabs defaultActiveKey="users" items={tabs} tabBarStyle={{borderBottom:'1px solid rgba(255,255,255,0.08)',marginBottom:24}}/>
  </div>
}
