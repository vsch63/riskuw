import { useState, useRef, useEffect } from 'react'
import { Form, Input, Button, Alert, message } from 'antd'
import {
  UserOutlined, LockOutlined, SafetyOutlined, ArrowRightOutlined,
  ArrowLeftOutlined, MailOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { authAPI } from '../api/client'
import { useAuthStore } from '../context/authStore'
import type { AuthUser } from '../types'

/* ─── tiny shield SVG ─────────────────────────────────────────── */
const ShieldIcon = () => (
  <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
    <path
      d="M18 3 L32 8 L32 20 C32 27 18 33 18 33 C18 33 4 27 4 20 L4 8 Z"
      fill="none" stroke="#00d4aa" strokeWidth="1.8" strokeLinejoin="round"
    />
    <path
      d="M12 18 L16 22 L24 14"
      stroke="#00d4aa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    />
  </svg>
)

/* ─── 6-digit OTP input ────────────────────────────────────────── */
function OTPInput({ onComplete }: { onComplete: (code: string) => void }) {
  const [digits, setDigits] = useState<string[]>(Array(6).fill(''))
  const refs = useRef<(HTMLInputElement | null)[]>([])

  const handleKey = (i: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace') {
      if (digits[i]) {
        const next = [...digits]; next[i] = ''
        setDigits(next)
      } else if (i > 0) {
        refs.current[i - 1]?.focus()
      }
    }
  }

  const handleChange = (i: number, val: string) => {
    const ch = val.replace(/\D/g, '').slice(-1)
    const next = [...digits]; next[i] = ch
    setDigits(next)
    if (ch && i < 5) refs.current[i + 1]?.focus()
    if (next.every(Boolean)) onComplete(next.join(''))
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (pasted.length === 6) {
      setDigits(pasted.split(''))
      onComplete(pasted)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 10, justifyContent: 'center', margin: '28px 0' }}>
      {digits.map((d, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el }}
          value={d}
          maxLength={1}
          inputMode="numeric"
          onKeyDown={(e) => handleKey(i, e)}
          onChange={(e) => handleChange(i, e.target.value)}
          onPaste={handlePaste}
          style={{
            width: 48, height: 56,
            background: 'rgba(255,255,255,0.06)',
            border: `2px solid ${d ? '#00d4aa' : 'rgba(255,255,255,0.14)'}`,
            borderRadius: 10,
            color: '#fff',
            fontSize: 24,
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 600,
            textAlign: 'center',
            outline: 'none',
            transition: 'border-color 180ms',
            cursor: 'text',
          }}
          onFocus={(e) => (e.target.style.borderColor = '#00d4aa')}
          onBlur={(e) => (e.target.style.borderColor = d ? '#00d4aa' : 'rgba(255,255,255,0.14)')}
        />
      ))}
    </div>
  )
}

/* ─── Animated background grid ────────────────────────────────── */
const GridBg = () => (
  <svg
    style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.07 }}
    xmlns="http://www.w3.org/2000/svg"
  >
    <defs>
      <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
        <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#00d4aa" strokeWidth="0.6" />
      </pattern>
    </defs>
    <rect width="100%" height="100%" fill="url(#grid)" />
  </svg>
)

/* ─── Stats shown on left panel ────────────────────────────────── */
const STATS = [
  { label: 'Decisions / hour', value: '2,400+' },
  { label: 'Rules engine accuracy', value: '99.7%' },
  { label: 'STP rate', value: '68%' },
  { label: 'Products supported', value: '12+' },
]

type Step = 'credentials' | 'mfa' | 'forgot' | 'reset_mfa' | 'reset_password' | 'reset_done'

/* ═══════════════════════════════════════════════════════════════ */
export default function LoginPage() {
  const [step, setStep] = useState<Step>('credentials')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [otpLoading, setOtpLoading] = useState(false)
  const [resetToken, setResetToken] = useState('')
  const [resetMfaRequired, setResetMfaRequired] = useState(false)
  const [forgotSent, setForgotSent] = useState(false)
  const { setUser, setMFAPending, mfaUsername, mfaSessionToken, clearMFA } = useAuthStore()
  const [form] = Form.useForm()
  const [forgotForm] = Form.useForm()
  const [resetForm] = Form.useForm()

  // MFA enrollment state
  const [enrollRequired, setEnrollRequired] = useState(false)
  const [mfaSecret, setMfaSecret] = useState('')
  const [mfaOtpUri, setMfaOtpUri] = useState('')
  const [enrollPhase, setEnrollPhase] = useState<'setup' | 'verify'>('setup')

  useEffect(() => { setError('') }, [step])

  /* ── MFA enrollment: fetch secret on mount when enrollment required ── */
  useEffect(() => {
    if (step !== 'mfa' || !enrollRequired || mfaSecret) return
    ;(async () => {
      try {
        const res  = await authAPI.setupMFA(mfaUsername, mfaSessionToken)
        const data = res.data
        setMfaSecret(data.secret || '')
        setMfaOtpUri(data.otpauth_uri || '')
      } catch {
        setError('Failed to initialize MFA enrollment. Please try again.')
      }
    })()
  }, [step, enrollRequired])

  // Read token from URL on mount (for email link clicks)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const token  = params.get('token')
    const mfa    = params.get('mfa')
    if (token) {
      setResetToken(token)
      setResetMfaRequired(mfa === 'required')
      setStep(mfa === 'required' ? 'reset_mfa' : 'reset_password')
      // Clean URL
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  /* ── Step 1: username + password ── */
  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true); setError('')
    try {
      const res  = await authAPI.login(values.username, values.password)
      const data = res.data
      if (data.mfa_required) {
        setMFAPending(values.username, data.mfa_session_token)
        setEnrollRequired(!!data.mfa_enrollment_required)
        setEnrollPhase('setup')
        setMfaSecret('')
        setMfaOtpUri('')
        setStep('mfa')
        return
      }
      const user: AuthUser = {
        username:    data.username ?? values.username,
        role:        data.role ?? 'underwriter',
        full_name:   data.full_name ?? '',
        token:       data.access_token,
        tenant_id:   data.tenant_id ?? '',
        tenant_name: data.tenant_name ?? '',
      }
      setUser(user)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail ?? 'Login failed. Check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  /* ── Step 2: TOTP verify (login) ── */
  const handleOTP = async (code: string) => {
    setOtpLoading(true); setError('')
    try {
      const res  = await authAPI.verifyMFA(code, mfaUsername, mfaSessionToken)
      const data = res.data
      const user: AuthUser = {
        username:    data.username ?? mfaUsername,
        role:        data.role ?? 'underwriter',
        full_name:   data.full_name ?? '',
        token:       data.access_token,
        tenant_id:   data.tenant_id ?? '',
        tenant_name: data.tenant_name ?? '',
      }
      setUser(user)
      message.success('Authenticated successfully')
    } catch {
      setError('Invalid code. Please try again.')
    } finally {
      setOtpLoading(false)
    }
  }

  /* ── Step 2b: TOTP enroll (login enforcement) ── */
  const handleEnrollOTP = async (code: string) => {
    setOtpLoading(true); setError('')
    try {
      const res  = await authAPI.verifySetupMFA(mfaUsername, mfaSessionToken, code)
      const data = res.data
      const user: AuthUser = {
        username:    data.username ?? mfaUsername,
        role:        data.role ?? 'underwriter',
        full_name:   data.full_name ?? '',
        token:       data.access_token,
        tenant_id:   data.tenant_id ?? '',
        tenant_name: data.tenant_name ?? '',
      }
      setUser(user)
      message.success('MFA enabled — you are signed in')
    } catch {
      setError('Invalid code. Please try again.')
    } finally {
      setOtpLoading(false)
    }
  }

  /* ── Forgot password: send email ── */
  const handleForgot = async (values: { identifier: string }) => {
    setLoading(true); setError('')
    try {
      await authAPI.forgotPassword(values.identifier)
      setForgotSent(true)
    } catch {
      // Always show success to avoid user enumeration
      setForgotSent(true)
    } finally {
      setLoading(false)
    }
  }

  /* ── Reset MFA verify (before new password) ── */
  const handleResetMFA = async (code: string) => {
    setOtpLoading(true); setError('')
    try {
      await authAPI.verifyResetMFA(resetToken, code)
      setStep('reset_password')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail ?? 'Invalid code. Please try again.')
    } finally {
      setOtpLoading(false)
    }
  }

  /* ── Set new password ── */
  const handleResetPassword = async (values: { new_password: string; confirm_password: string }) => {
    if (values.new_password !== values.confirm_password) {
      setError('Passwords do not match'); return
    }
    setLoading(true); setError('')
    try {
      await authAPI.resetPasswordConfirm(resetToken, values.new_password)
      setStep('reset_done')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail ?? 'Reset failed. The link may have expired.')
    } finally {
      setLoading(false)
    }
  }

  /* ── shared back button ── */
  const BackBtn = ({ to, label = 'Back to login' }: { to: Step; label?: string }) => (
    <button
      onClick={() => { clearMFA(); setStep(to); setError(''); setForgotSent(false) }}
      style={{
        background: 'none', border: 'none', color: 'var(--teal-400)',
        cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
        fontSize: 13, marginBottom: 36, padding: 0,
      }}
    >
      <ArrowLeftOutlined /> {label}
    </button>
  )

  /* ── panel content by step ── */
  const renderStep = () => {

    /* ── credentials ── */
    if (step === 'credentials') return (
      <>
        <div style={{ marginBottom: 40 }}>
          <h2 style={{
            fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: 28, color: '#fff', letterSpacing: '-0.02em', marginBottom: 8,
          }}>Sign in</h2>
          <p style={{ color: 'var(--slate-400)', fontSize: 14 }}>
            Access your underwriting workspace
          </p>
        </div>

        {error && (
          <Alert message={error} type="error" showIcon
            style={{ marginBottom: 20, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)' }} />
        )}

        <Form form={form} onFinish={handleLogin} layout="vertical" requiredMark={false}>
          <Form.Item name="username" label="Username"
            rules={[{ required: true, message: 'Username is required' }]}>
            <Input prefix={<UserOutlined style={{ color: 'var(--slate-500)' }} />}
              placeholder="your.username" size="large" autoComplete="username" />
          </Form.Item>

          <Form.Item name="password" label="Password" style={{ marginTop: 16 }}
            rules={[{ required: true, message: 'Password is required' }]}>
            <Input.Password prefix={<LockOutlined style={{ color: 'var(--slate-500)' }} />}
              placeholder="••••••••" size="large" autoComplete="current-password" />
          </Form.Item>

          {/* Forgot password link */}
          <div style={{ textAlign: 'right', marginTop: -8, marginBottom: 4 }}>
            <button type="button"
              onClick={() => { setStep('forgot'); setError('') }}
              style={{
                background: 'none', border: 'none', color: 'var(--teal-400)',
                cursor: 'pointer', fontSize: 13, padding: 0,
              }}>
              Forgot password?
            </button>
          </div>

          <Button type="primary" htmlType="submit" loading={loading} size="large" block
            style={{ marginTop: 20, height: 48, fontSize: 15, fontWeight: 600 }}
            icon={<ArrowRightOutlined />} iconPosition="end">
            Continue
          </Button>
        </Form>

        <div style={{
          marginTop: 32, padding: '14px 16px',
          background: 'rgba(0,212,170,0.05)',
          border: '1px solid rgba(0,212,170,0.15)',
          borderRadius: 8, fontSize: 12, color: 'var(--slate-400)',
        }}>
          <SafetyOutlined style={{ color: 'var(--teal-500)', marginRight: 8 }} />
          All sessions are encrypted · TOTP MFA enforced for privileged roles
        </div>
      </>
    )

    /* ── login MFA ── */
    if (step === 'mfa') return (
      <>
        <BackBtn to="credentials" />
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 64, height: 64,
            background: 'rgba(0,212,170,0.1)', border: '1.5px solid rgba(0,212,170,0.3)',
            borderRadius: '50%', marginBottom: 20,
          }}>
            <SafetyOutlined style={{ fontSize: 26, color: 'var(--teal-400)' }} />
          </div>
          <h2 style={{
            fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: 26, color: '#fff', letterSpacing: '-0.02em', marginBottom: 8,
          }}>
            {enrollRequired ? 'Set up authenticator' : 'Two-factor verification'}
          </h2>
          <p style={{ color: 'var(--slate-400)', fontSize: 14, lineHeight: 1.6 }}>
            {enrollRequired
              ? 'Open your authenticator app and add the account using the secret below'
              : 'Enter the 6-digit code from your authenticator app'}
          </p>
          <p style={{ marginTop: 8, fontFamily: 'var(--font-mono)', color: 'var(--teal-500)', fontSize: 13 }}>
            {mfaUsername}
          </p>
        </div>

        {enrollRequired && mfaSecret && (
          <div style={{ marginBottom: 12, padding: '14px 16px', background: 'rgba(0,212,170,0.05)',
            border: '1px solid rgba(0,212,170,0.15)', borderRadius: 8, fontSize: 13 }}>
            <div style={{ fontWeight: 600, color: 'var(--teal-400)', marginBottom: 4 }}>
              Your TOTP secret
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', color: '#fff', marginBottom: 8,
              fontSize: 14, letterSpacing: '0.05em' }}>
              {mfaSecret}
            </div>
            {mfaOtpUri && (
              <div>
                <a href={mfaOtpUri} target="_blank" rel="noreferrer"
                  style={{ color: 'var(--teal-400)', fontSize: 12 }}>
                  Open in authenticator app
                </a>
              </div>
            )}
          </div>
        )}

        {error && <Alert message={error} type="error" showIcon
          style={{ marginBottom: 8, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)' }} />}
        <OTPInput onComplete={(code) => enrollRequired ? handleEnrollOTP(code) : handleOTP(code)} />
        {otpLoading && <div style={{ textAlign: 'center', color: 'var(--teal-400)', fontSize: 13 }}>
          {enrollRequired ? 'Verifying & activating…' : 'Verifying…'}
        </div>}
        <p style={{ textAlign: 'center', marginTop: 24, fontSize: 12, color: 'var(--slate-500)' }}>
          Open Google Authenticator or Authy · codes refresh every 30s
        </p>
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <button type="button"
            onClick={() => { clearMFA(); setStep('credentials'); setEnrollRequired(false); setError('') }}
            style={{ background: 'none', border: 'none', color: 'var(--slate-400)', cursor: 'pointer', fontSize: 13 }}>
            Use a different account
          </button>
        </div>
      </>
    )

    /* ── forgot password ── */
    if (step === 'forgot') return (
      <>
        <BackBtn to="credentials" />
        <div style={{ marginBottom: 32 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 56, height: 56, background: 'rgba(0,212,170,0.1)',
            border: '1.5px solid rgba(0,212,170,0.3)', borderRadius: '50%', marginBottom: 20,
          }}>
            <MailOutlined style={{ fontSize: 22, color: 'var(--teal-400)' }} />
          </div>
          <h2 style={{
            fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: 26, color: '#fff', letterSpacing: '-0.02em', marginBottom: 8,
          }}>Reset your password</h2>
          <p style={{ color: 'var(--slate-400)', fontSize: 14, lineHeight: 1.6 }}>
            Enter your username or email address and we'll send you a reset link.
          </p>
        </div>

        {forgotSent ? (
          <div style={{
            background: 'rgba(0,212,170,0.06)', border: '1px solid rgba(0,212,170,0.2)',
            borderRadius: 10, padding: '20px 24px', textAlign: 'center',
          }}>
            <CheckCircleOutlined style={{ fontSize: 32, color: 'var(--teal-400)', marginBottom: 12 }} />
            <p style={{ color: '#e2e8f0', fontSize: 14, lineHeight: 1.7, margin: 0 }}>
              If an account exists for that username or email, a reset link has been sent.<br />
              <span style={{ color: 'var(--slate-400)', fontSize: 12 }}>Check your inbox — link expires in 30 minutes.</span>
            </p>
            <button type="button" onClick={() => { setStep('credentials'); setForgotSent(false) }}
              style={{
                marginTop: 20, background: 'none', border: 'none',
                color: 'var(--teal-400)', cursor: 'pointer', fontSize: 13,
              }}>
              ← Back to login
            </button>
          </div>
        ) : (
          <>
            {error && <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} />}
            <Form form={forgotForm} onFinish={handleForgot} layout="vertical" requiredMark={false}>
              <Form.Item name="identifier" label="Username or Email"
                rules={[{ required: true, message: 'Please enter your username or email' }]}>
                <Input prefix={<UserOutlined style={{ color: 'var(--slate-500)' }} />}
                  placeholder="your.username or email@company.com" size="large" autoComplete="username" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={loading} size="large" block
                style={{ marginTop: 24, height: 48, fontSize: 15, fontWeight: 600 }}
                icon={<MailOutlined />}>
                Send Reset Link
              </Button>
            </Form>
          </>
        )}
      </>
    )

    /* ── reset MFA verify ── */
    if (step === 'reset_mfa') return (
      <>
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 64, height: 64, background: 'rgba(0,212,170,0.1)',
            border: '1.5px solid rgba(0,212,170,0.3)', borderRadius: '50%', marginBottom: 20,
          }}>
            <SafetyOutlined style={{ fontSize: 26, color: 'var(--teal-400)' }} />
          </div>
          <h2 style={{
            fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: 24, color: '#fff', letterSpacing: '-0.02em', marginBottom: 8,
          }}>Verify your identity</h2>
          <p style={{ color: 'var(--slate-400)', fontSize: 14, lineHeight: 1.6 }}>
            Your account has MFA enabled.<br />
            Enter your authenticator code to continue with the password reset.
          </p>
        </div>
        {error && <Alert message={error} type="error" showIcon
          style={{ marginBottom: 8, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)' }} />}
        <OTPInput onComplete={handleResetMFA} />
        {otpLoading && <div style={{ textAlign: 'center', color: 'var(--teal-400)', fontSize: 13 }}>Verifying…</div>}
        <p style={{ textAlign: 'center', marginTop: 16, fontSize: 12, color: 'var(--slate-500)' }}>
          Open Google Authenticator or Authy · codes refresh every 30s
        </p>
      </>
    )

    /* ── set new password ── */
    if (step === 'reset_password') return (
      <>
        <div style={{ marginBottom: 32 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 56, height: 56, background: 'rgba(0,212,170,0.1)',
            border: '1.5px solid rgba(0,212,170,0.3)', borderRadius: '50%', marginBottom: 20,
          }}>
            <LockOutlined style={{ fontSize: 22, color: 'var(--teal-400)' }} />
          </div>
          <h2 style={{
            fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: 26, color: '#fff', letterSpacing: '-0.02em', marginBottom: 8,
          }}>Set new password</h2>
          <p style={{ color: 'var(--slate-400)', fontSize: 14 }}>
            Choose a strong password of at least 8 characters.
          </p>
        </div>
        {error && <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} />}
        <Form form={resetForm} onFinish={handleResetPassword} layout="vertical" requiredMark={false}>
          <Form.Item name="new_password" label="New Password"
            rules={[
              { required: true, message: 'Password is required' },
              { min: 8, message: 'At least 8 characters' },
            ]}>
            <Input.Password prefix={<LockOutlined style={{ color: 'var(--slate-500)' }} />}
              placeholder="New password" size="large" autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="confirm_password" label="Confirm Password" style={{ marginTop: 16 }}
            rules={[{ required: true, message: 'Please confirm your password' }]}>
            <Input.Password prefix={<LockOutlined style={{ color: 'var(--slate-500)' }} />}
              placeholder="Repeat new password" size="large" autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} size="large" block
            style={{ marginTop: 24, height: 48, fontSize: 15, fontWeight: 600 }}
            icon={<ArrowRightOutlined />} iconPosition="end">
            Reset Password
          </Button>
        </Form>
      </>
    )

    /* ── success ── */
    if (step === 'reset_done') return (
      <div style={{ textAlign: 'center' }}>
        <div style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 72, height: 72, background: 'rgba(0,212,170,0.1)',
          border: '1.5px solid rgba(0,212,170,0.3)', borderRadius: '50%', marginBottom: 24,
        }}>
          <CheckCircleOutlined style={{ fontSize: 34, color: 'var(--teal-400)' }} />
        </div>
        <h2 style={{
          fontFamily: 'var(--font-display)', fontWeight: 700,
          fontSize: 26, color: '#fff', letterSpacing: '-0.02em', marginBottom: 12,
        }}>Password updated!</h2>
        <p style={{ color: 'var(--slate-400)', fontSize: 14, lineHeight: 1.7, marginBottom: 32 }}>
          Your password has been reset successfully.<br />
          You can now sign in with your new password.
        </p>
        <Button type="primary" size="large" block
          style={{ height: 48, fontSize: 15, fontWeight: 600 }}
          icon={<ArrowRightOutlined />} iconPosition="end"
          onClick={() => { setStep('credentials'); setResetToken('') }}>
          Go to Sign In
        </Button>
      </div>
    )

    return null
  }

  return (
    <div style={{
      display: 'flex', height: '100vh', width: '100vw',
      background: 'var(--navy-950)', overflow: 'hidden',
    }}>
      {/* ── Left panel ── */}
      <div style={{
        width: '52%', position: 'relative', overflow: 'hidden',
        background: 'linear-gradient(145deg, #060d1f 0%, #0a1e44 60%, #061828 100%)',
        display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
        padding: '52px 60px',
      }}>
        <GridBg />
        <div style={{
          position: 'absolute', width: 480, height: 480, borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(0,212,170,0.14) 0%, transparent 70%)',
          top: '15%', left: '-10%', pointerEvents: 'none',
        }} />
        <div style={{
          position: 'absolute', width: 320, height: 320, borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(0,212,170,0.08) 0%, transparent 70%)',
          bottom: '10%', right: '5%', pointerEvents: 'none',
        }} />

        {/* Logo */}
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 64 }}>
            <ShieldIcon />
            <div>
              <div style={{
                fontFamily: 'var(--font-display)', fontWeight: 700,
                fontSize: 22, color: '#fff', letterSpacing: '-0.02em',
              }}>RiskUW</div>
              <div style={{ fontSize: 11, color: 'var(--teal-500)', letterSpacing: '0.12em', marginTop: 1 }}>
                AUTOMATED UNDERWRITING
              </div>
            </div>
          </div>
          <h1 style={{
            fontFamily: 'var(--font-display)', fontWeight: 700,
            fontSize: 40, lineHeight: 1.15, color: '#fff',
            letterSpacing: '-0.03em', maxWidth: 420,
          }}>
            Decisions at the
            <span style={{ display: 'block', color: 'var(--teal-500)', WebkitTextStroke: '0px' }}>
              speed of data.
            </span>
          </h1>
          <p style={{ marginTop: 20, color: 'var(--slate-400)', fontSize: 15, lineHeight: 1.7, maxWidth: 400 }}>
            Enterprise underwriting automation for Indian insurance carriers —
            life, health, motor, and reinsurance in a single platform.
          </p>
        </div>

        {/* Stats */}
        <div style={{
          position: 'relative', zIndex: 1,
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16,
        }}>
          {STATS.map((s) => (
            <div key={s.label} style={{
              background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: 12, padding: '18px 20px', backdropFilter: 'blur(8px)',
            }}>
              <div style={{
                fontFamily: 'var(--font-mono)', fontWeight: 600,
                fontSize: 22, color: 'var(--teal-400)', lineHeight: 1,
              }}>{s.value}</div>
              <div style={{ fontSize: 12, color: 'var(--slate-400)', marginTop: 6 }}>{s.label}</div>
            </div>
          ))}
        </div>

        <div style={{
          position: 'relative', zIndex: 1,
          fontSize: 11, color: 'var(--slate-600)', letterSpacing: '0.04em', marginTop: 32,
        }}>
          © 2025 RiskUW · riskuw.online · Secure · IRDAI-aligned
        </div>
      </div>

      {/* ── Right panel ── */}
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--navy-900)', padding: '48px 40px',
      }}>
        <div style={{ width: '100%', maxWidth: 400 }}>
          {renderStep()}
        </div>
      </div>
    </div>
  )
}


