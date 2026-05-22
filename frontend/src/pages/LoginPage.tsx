import { useState, useRef, useEffect } from 'react'
import { Form, Input, Button, Alert, message } from 'antd'
import {
  UserOutlined, LockOutlined, SafetyOutlined, ArrowRightOutlined,
  ArrowLeftOutlined,
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

/* ═══════════════════════════════════════════════════════════════ */
export default function LoginPage() {
  const [step, setStep] = useState<'credentials' | 'mfa'>('credentials')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [otpLoading, setOtpLoading] = useState(false)
  const { setUser, setMFAPending, mfaUsername, mfaSessionToken, clearMFA } = useAuthStore()
  const [form] = Form.useForm()

  useEffect(() => { setError('') }, [step])

  /* ── Step 1: username + password ── */
  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true); setError('')
    try {
      const res = await authAPI.login(values.username, values.password)
      const data = res.data

      if (data.mfa_required) {
        setMFAPending(values.username, data.mfa_session_token)
        setStep('mfa')
        return
      }

      // No MFA — token comes back directly
      const user: AuthUser = {
        username: data.username ?? values.username,
        role: data.role ?? 'underwriter',
        token: data.access_token,
      }
      setUser(user)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail ?? 'Login failed. Check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  /* ── Step 2: TOTP verify ── */
  const handleOTP = async (code: string) => {
    setOtpLoading(true); setError('')
    try {
      const res = await authAPI.verifyMFA(code, mfaUsername, mfaSessionToken)
      const data = res.data
      const user: AuthUser = {
        username: data.username ?? mfaUsername,
        role: data.role ?? 'underwriter',
        token: data.access_token,
      }
      setUser(user)
      message.success('Authenticated successfully')
    } catch {
      setError('Invalid code. Please try again.')
    } finally {
      setOtpLoading(false)
    }
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

        {/* Teal glow blob */}
        <div style={{
          position: 'absolute', width: 480, height: 480,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(0,212,170,0.14) 0%, transparent 70%)',
          top: '15%', left: '-10%', pointerEvents: 'none',
        }} />
        <div style={{
          position: 'absolute', width: 320, height: 320,
          borderRadius: '50%',
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
            <span style={{
              display: 'block', color: 'var(--teal-500)',
              WebkitTextStroke: '0px',
            }}>speed of data.</span>
          </h1>

          <p style={{
            marginTop: 20, color: 'var(--slate-400)',
            fontSize: 15, lineHeight: 1.7, maxWidth: 400,
          }}>
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
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: 12, padding: '18px 20px',
              backdropFilter: 'blur(8px)',
            }}>
              <div style={{
                fontFamily: 'var(--font-mono)', fontWeight: 600,
                fontSize: 22, color: 'var(--teal-400)', lineHeight: 1,
              }}>{s.value}</div>
              <div style={{ fontSize: 12, color: 'var(--slate-400)', marginTop: 6 }}>
                {s.label}
              </div>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div style={{
          position: 'relative', zIndex: 1,
          fontSize: 11, color: 'var(--slate-600)',
          letterSpacing: '0.04em', marginTop: 32,
        }}>
          © 2025 RiskUW · riskuw.online · Secure · IRDAI-aligned
        </div>
      </div>

      {/* ── Right panel ── */}
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--navy-900)',
        padding: '48px 40px',
      }}>
        <div style={{ width: '100%', maxWidth: 400 }}>
          {step === 'credentials' ? (
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
                <Alert
                  message={error} type="error" showIcon
                  style={{ marginBottom: 20, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)' }}
                />
              )}

              <Form form={form} onFinish={handleLogin} layout="vertical" requiredMark={false}>
                <Form.Item
                  name="username"
                  label="Username"
                  rules={[{ required: true, message: 'Username is required' }]}
                >
                  <Input
                    prefix={<UserOutlined style={{ color: 'var(--slate-500)' }} />}
                    placeholder="your.username"
                    size="large"
                    autoComplete="username"
                  />
                </Form.Item>

                <Form.Item
                  name="password"
                  label="Password"
                  style={{ marginTop: 16 }}
                  rules={[{ required: true, message: 'Password is required' }]}
                >
                  <Input.Password
                    prefix={<LockOutlined style={{ color: 'var(--slate-500)' }} />}
                    placeholder="••••••••"
                    size="large"
                    autoComplete="current-password"
                  />
                </Form.Item>

                <Button
                  type="primary"
                  htmlType="submit"
                  loading={loading}
                  size="large"
                  block
                  style={{ marginTop: 28, height: 48, fontSize: 15, fontWeight: 600 }}
                  icon={<ArrowRightOutlined />}
                  iconPosition="end"
                >
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
          ) : (
            <>
              <button
                onClick={() => { clearMFA(); setStep('credentials') }}
                style={{
                  background: 'none', border: 'none', color: 'var(--teal-400)',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
                  fontSize: 13, marginBottom: 36, padding: 0,
                }}
              >
                <ArrowLeftOutlined /> Back to login
              </button>

              <div style={{ textAlign: 'center', marginBottom: 8 }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: 64, height: 64,
                  background: 'rgba(0,212,170,0.1)',
                  border: '1.5px solid rgba(0,212,170,0.3)',
                  borderRadius: '50%', marginBottom: 20,
                }}>
                  <SafetyOutlined style={{ fontSize: 26, color: 'var(--teal-400)' }} />
                </div>

                <h2 style={{
                  fontFamily: 'var(--font-display)', fontWeight: 700,
                  fontSize: 26, color: '#fff', letterSpacing: '-0.02em', marginBottom: 8,
                }}>Two-factor verification</h2>
                <p style={{ color: 'var(--slate-400)', fontSize: 14, lineHeight: 1.6 }}>
                  Enter the 6-digit code from your authenticator app
                </p>
                <p style={{
                  marginTop: 8, fontFamily: 'var(--font-mono)',
                  color: 'var(--teal-500)', fontSize: 13,
                }}>
                  {mfaUsername}
                </p>
              </div>

              {error && (
                <Alert
                  message={error} type="error" showIcon
                  style={{ marginBottom: 8, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)' }}
                />
              )}

              <OTPInput onComplete={handleOTP} />

              {otpLoading && (
                <div style={{ textAlign: 'center', color: 'var(--teal-400)', fontSize: 13 }}>
                  Verifying…
                </div>
              )}

              <p style={{
                textAlign: 'center', marginTop: 24,
                fontSize: 12, color: 'var(--slate-500)',
              }}>
                Open Google Authenticator or Authy · codes refresh every 30s
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
