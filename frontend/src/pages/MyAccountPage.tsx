import { useEffect, useState } from 'react'
import {
  Button, Input, Form, message, Spin, QRCode, Divider, Tag,
} from 'antd'
import {
  UserOutlined, LockOutlined, SafetyCertificateOutlined,
  CheckCircleFilled, CloseCircleFilled, CopyOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../context/authStore'

// Direct fetch helper — auth routes go via /auth/* proxied correctly
const _tok = () => localStorage.getItem('riskuw_token') || ''
const authFetch = {
  get: (path: string) =>
    fetch(path, { headers: { Authorization: `Bearer ${_tok()}` } }).then(r => r.json()),
  post: (path: string, body?: any) =>
    fetch(path, { method: 'POST', headers: { Authorization: `Bearer ${_tok()}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json()),
  patch: (path: string, body?: any) =>
    fetch(path, { method: 'PATCH', headers: { Authorization: `Bearer ${_tok()}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json()),
}

const ROLE_COLOR: Record<string, string> = {
  super_admin: '#c084fc', admin: '#c084fc',
  senior_underwriter: '#fbbf24', underwriter: '#00d4aa',
  api_client: '#60a5fa', readonly: '#94a3b8',
}

const card: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid rgba(255,255,255,0.07)',
  borderRadius: 12, padding: '24px 28px', marginBottom: 20,
}
const sectionTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: '#6b7280',
  textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 16,
}

// ── Profile Section ────────────────────────────────────────────────────────────
function ProfileSection({ username }: { username: string }) {
  const [profile, setProfile]   = useState<any>(null)
  const [editing, setEditing]   = useState(false)
  const [saving, setSaving]     = useState(false)
  const [form]                  = Form.useForm()

  useEffect(() => {
    authFetch.get(`/auth/users/${username}`).then(r => {
      setProfile(r)
      form.setFieldsValue({ full_name: r.full_name, email: r.email })
    }).catch(() => {})
  }, [username])

  const save = async () => {
    const vals = await form.validateFields()
    setSaving(true)
    try {
      const r = await authFetch.patch(`/auth/users/${username}`, vals)
      if (r.detail) throw new Error(r.detail)
      setProfile((p: any) => ({ ...p, ...vals }))
      message.success('Profile updated')
      setEditing(false)
    } catch(e: any) { message.error(e.message || 'Update failed') }
    finally { setSaving(false) }
  }

  if (!profile) return <div style={card}><Spin/></div>

  return (
    <div style={card}>
      <div style={sectionTitle}>Profile</div>

      {/* Avatar + identity */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
        <div style={{
          width: 56, height: 56, borderRadius: '50%',
          background: 'rgba(0,212,170,0.15)', border: '2px solid rgba(0,212,170,0.3)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 22, fontWeight: 700, color: '#00d4aa', flexShrink: 0,
        }}>
          {username[0].toUpperCase()}
        </div>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>
            {profile.full_name || username}
          </div>
          <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>@{username}</div>
          <Tag style={{
            marginTop: 6, fontSize: 10, fontFamily: 'var(--font-mono,monospace)',
            color: ROLE_COLOR[profile.role] || '#94a3b8',
            borderColor: (ROLE_COLOR[profile.role] || '#94a3b8') + '40',
            background: (ROLE_COLOR[profile.role] || '#94a3b8') + '15',
          }}>
            {profile.role?.replace('_', ' ').toUpperCase()}
          </Tag>
        </div>
      </div>

      {!editing ? (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            {[
              { label: 'Full Name',  value: profile.full_name || '—' },
              { label: 'Email',      value: profile.email || '—' },
              { label: 'Username',   value: profile.username },
              { label: 'Tenant ID', value: profile.tenant_id?.slice(0, 8) + '...' || '—' },
            ].map(f => (
              <div key={f.label}>
                <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>{f.label}</div>
                <div style={{ fontSize: 13, color: '#e2e8f0', fontFamily: f.label === 'Tenant ID' ? 'var(--font-mono,monospace)' : undefined }}>{f.value}</div>
              </div>
            ))}
          </div>
          <Button onClick={() => setEditing(true)}
            style={{ borderColor: 'rgba(0,212,170,0.3)', color: '#00d4aa' }}>
            ✏️ Edit Profile
          </Button>
        </>
      ) : (
        <Form form={form} layout="vertical">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Form.Item name="full_name" label="Full Name">
              <Input prefix={<UserOutlined/>} placeholder="Your full name"/>
            </Form.Item>
            <Form.Item name="email" label="Email" rules={[{ type: 'email', message: 'Invalid email' }]}>
              <Input placeholder="your@email.com"/>
            </Form.Item>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <Button type="primary" loading={saving} onClick={save}>Save Changes</Button>
            <Button onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </Form>
      )}
    </div>
  )
}

// ── Change Password Section ───────────────────────────────────────────────────
function ChangePasswordSection({ username }: { username: string }) {
  const [form]            = Form.useForm()
  const [saving, setSaving] = useState(false)

  const save = async () => {
    const vals = await form.validateFields()
    if (vals.new_password !== vals.confirm_password) {
      message.error('New passwords do not match'); return
    }
    setSaving(true)
    try {
      const r = await authFetch.post(`/auth/users/${username}/reset-password`, {
        new_password: vals.new_password,
        actor_username: username,
      })
      if (r.detail) throw new Error(r.detail)
      message.success('Password changed successfully')
      form.resetFields()
    } catch(e: any) { message.error(e.message || 'Password change failed') }
    finally { setSaving(false) }
  }

  return (
    <div style={card}>
      <div style={sectionTitle}>Change Password</div>
      <Form form={form} layout="vertical" style={{ maxWidth: 420 }}>
        <Form.Item name="new_password" label="New Password"
          rules={[{ required: true }, { min: 8, message: 'At least 8 characters' }]}>
          <Input.Password prefix={<LockOutlined/>} placeholder="New password"/>
        </Form.Item>
        <Form.Item name="confirm_password" label="Confirm New Password"
          rules={[{ required: true }]}>
          <Input.Password prefix={<LockOutlined/>} placeholder="Confirm new password"/>
        </Form.Item>
        <Button type="primary" loading={saving} onClick={save}
          style={{ background: '#1a2744', borderColor: 'rgba(0,212,170,0.3)', color: '#00d4aa' }}>
          🔒 Update Password
        </Button>
      </Form>
    </div>
  )
}

// ── MFA Section ───────────────────────────────────────────────────────────────
function MFASection({ username }: { username: string }) {
  const [mfaStatus, setMfaStatus]   = useState<any>(null)
  const [setup, setSetup]           = useState<any>(null)
  const [totp, setTotp]             = useState('')
  const [verifying, setVerifying]   = useState(false)
  const [disabling, setDisabling]   = useState(false)
  const [loading, setLoading]       = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const r = await authFetch.get(`/auth/mfa/setup/${username}`)
      setMfaStatus(r)
      setSetup(r)  // always store — contains secret, uri, qr_base64
    } catch {}
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [username])

  const verify = async () => {
    if (!totp || totp.length !== 6) { message.error('Enter 6-digit code'); return }
    setVerifying(true)
    try {
      const r = await authFetch.post(`/auth/mfa/enable/${username}`, { totp_code: totp })
      if (r.detail) throw new Error(r.detail)
      message.success('✅ MFA activated successfully!')
      setTotp('')
      load()
    } catch(e: any) { message.error(e.message || 'Verification failed — check the code') }
    finally { setVerifying(false) }
  }

  const disable = async () => {
    setDisabling(true)
    try {
      const r = await authFetch.post(`/auth/mfa/disable/${username}`, {})
      if (r.detail) throw new Error(r.detail)
      message.success('MFA disabled')
      setSetup(null)
      load()
    } catch(e: any) { message.error(e.message || 'Failed to disable MFA') }
    finally { setDisabling(false) }
  }

  const copyKey = () => {
    if (setup?.secret) {
      navigator.clipboard.writeText(setup.secret)
      message.success('Setup key copied')
    }
  }

  if (loading) return <div style={card}><Spin/></div>

  const isEnabled  = mfaStatus?.is_enabled && mfaStatus?.is_verified
  const isPending  = mfaStatus?.is_enabled && !mfaStatus?.is_verified
  const isDisabled = !mfaStatus?.is_enabled

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={sectionTitle}>Two-Factor Authentication (MFA)</div>
        {isEnabled  && <Tag color="success" icon={<CheckCircleFilled/>}>Active</Tag>}
        {isPending  && <Tag color="warning">Setup in progress</Tag>}
        {isDisabled && <Tag color="default" icon={<CloseCircleFilled/>}>Disabled</Tag>}
      </div>

      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 20, lineHeight: 1.6 }}>
        Add a second layer of security using a TOTP authenticator app.
        Works with Google Authenticator, Authy, Microsoft Authenticator, and any RFC 6238-compatible app.
      </div>

      {/* MFA Active */}
      {isEnabled && (
        <div>
          <div style={{
            background: 'rgba(34,197,94,0.07)', border: '1px solid rgba(34,197,94,0.2)',
            borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 13, color: '#22c55e',
          }}>
            ✅ MFA is active on your account. Your login requires a 6-digit TOTP code.
          </div>
          {mfaStatus?.last_used_at && (
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 16 }}>
              Last used: {mfaStatus.last_used_at?.slice(0, 19).replace('T', ' ')}
            </div>
          )}
          <Button danger loading={disabling} onClick={disable}>
            🔓 Disable MFA
          </Button>
        </div>
      )}

      {/* MFA Setup / Pending */}
      {(isDisabled || isPending) && setup && (
        <div>
          {isPending && (
            <div style={{
              background: 'rgba(251,191,36,0.07)', border: '1px solid rgba(251,191,36,0.2)',
              borderRadius: 8, padding: '12px 16px', marginBottom: 20, fontSize: 13, color: '#fbbf24',
            }}>
              ⏳ MFA setup is in progress — complete the steps below to activate it.
            </div>
          )}

          {/* Step 1 */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginBottom: 12 }}>
              Step 1 — Add to your authenticator app
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 24, alignItems: 'start' }}>
              <div>
                <div style={{ fontSize: 13, color: '#9ca3af', marginBottom: 12 }}>
                  <strong style={{ color: '#e2e8f0' }}>Option A</strong> — Open authenticator app and scan the QR code
                </div>
                <div style={{ fontSize: 13, color: '#9ca3af', marginBottom: 12 }}>
                  <strong style={{ color: '#e2e8f0' }}>Option B</strong> — Enter key manually
                </div>
                {/* Setup key card */}
                <div style={{
                  background: 'rgba(0,212,170,0.05)', border: '1px solid rgba(0,212,170,0.15)',
                  borderRadius: 10, padding: '14px 16px',
                }}>
                  <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4, letterSpacing: '0.08em' }}>ACCOUNT NAME</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', marginBottom: 10 }}>UW Platform</div>
                  <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4, letterSpacing: '0.08em' }}>SETUP KEY</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                    <code style={{
                      fontSize: 13, fontFamily: 'var(--font-mono,monospace)',
                      color: '#00d4aa', letterSpacing: '0.04em', wordBreak: 'break-all',
                    }}>
                      {setup.secret}
                    </code>
                    <Button size="small" icon={<CopyOutlined/>} onClick={copyKey}
                      style={{ borderColor: 'rgba(0,212,170,0.3)', color: '#00d4aa', flexShrink: 0 }}/>
                  </div>
                  <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 2, letterSpacing: '0.08em' }}>TYPE</div>
                  <div style={{ fontSize: 13, color: '#9ca3af' }}>Time-based (TOTP)</div>
                </div>
              </div>

              {/* QR Code */}
              {setup.qr_base64 ? (
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>📷 Scan QR code</div>
                  <div style={{
                    background: '#fff', padding: 12, borderRadius: 8,
                    display: 'inline-block',
                  }}>
                    <img src={`data:image/png;base64,${setup.qr_base64}`}
                      width={140} height={140} alt="MFA QR Code"
                      style={{ display: 'block' }}/>
                  </div>
                </div>
              ) : setup.uri ? (
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>📷 Scan QR code</div>
                  <div style={{
                    background: '#fff', padding: 12, borderRadius: 8,
                    display: 'inline-block',
                  }}>
                    <QRCode value={setup.uri} size={140} bordered={false}/>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <Divider style={{ borderColor: 'rgba(255,255,255,0.07)' }}/>

          {/* Step 2 */}
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>
              Step 2 — Verify it's working
            </div>
            <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 16 }}>
              Once you've added the account to your app, enter the 6-digit code it shows to confirm setup.
            </div>
            <div style={{
              background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)',
              borderRadius: 10, padding: '20px 24px', maxWidth: 420,
            }}>
              <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 8 }}>6-digit code from your app</div>
              <Input
                value={totp} onChange={e => setTotp(e.target.value.replace(/\D/g,'').slice(0,6))}
                placeholder="000000" maxLength={6}
                style={{ fontSize: 24, letterSpacing: '0.4em', textAlign: 'center',
                  fontFamily: 'var(--font-mono,monospace)', marginBottom: 16, height: 52 }}
                onPressEnter={verify}
              />
              <Button type="primary" block size="large" loading={verifying} onClick={verify}
                style={{ height: 48, fontSize: 15, fontWeight: 600,
                  background: '#ef4444', borderColor: '#ef4444' }}>
                ✅ Verify & Activate MFA
              </Button>
            </div>

            {isPending && (
              <Button size="small" onClick={load} style={{ marginTop: 12, color: '#6b7280' }}>
                🔄 Start over (generate new secret)
              </Button>
            )}
          </div>
        </div>
      )}

      {/* No setup data yet — trigger setup */}
      {isDisabled && !setup && (
        <Button type="primary" icon={<SafetyCertificateOutlined/>} onClick={load}>
          Set up MFA
        </Button>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function MyAccountPage() {
  const { user } = useAuthStore()
  const username = user?.username || ''

  return (
    <div style={{ padding: '32px 36px', maxWidth: 860 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontWeight: 700, fontSize: 22, color: '#e2e8f0', margin: 0, letterSpacing: '-0.02em' }}>
          👤 My Account
        </h1>
        <p style={{ color: '#6b7280', fontSize: 13, marginTop: 4, marginBottom: 0 }}>
          Manage your profile, password and two-factor authentication settings.
        </p>
      </div>

      <ProfileSection      username={username} />
      <ChangePasswordSection username={username} />
      <MFASection          username={username} />
    </div>
  )
}

