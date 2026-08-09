import { useEffect, useState } from 'react'
import { Alert, Button } from 'antd'
import { useAuthStore } from '../context/authStore'
import type { AuthUser } from '../types'

/**
 * /sso/callback — terminal of the OIDC browser flow.
 *
 * The backend redirects here with a URL fragment carrying the RiskUW JWT
 * (#access_token=…&username=…&role=…&tenant_id=…). A fragment (never a query
 * string) keeps the token out of server logs. On error the same fragment
 * carries #error=<detail>. This route sits OUTSIDE RequireAuth in App.tsx.
 */
export default function SsoCallback() {
  const { setUser } = useAuthStore()
  const [error, setError] = useState('')

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    if (params.get('error')) {
      setError(params.get('error') ?? 'SSO sign-in failed')
      return
    }
    const token = params.get('access_token')
    if (!token) {
      setError('No access token returned from the identity provider.')
      return
    }
    const user: AuthUser = {
      username: params.get('username') ?? '',
      role: params.get('role') ?? 'viewer',
      full_name: params.get('full_name') ?? '',
      token,
      tenant_id: params.get('tenant_id') ?? '',
      tenant_name: params.get('tenant_name') ?? '',
    }
    setUser(user)
    window.location.replace('/')
  }, [setUser])

  if (error) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100vh', background: 'var(--navy-950)',
      }}>
        <div style={{ width: 380 }}>
          <Alert
            type="error" showIcon
            message="SSO sign-in failed"
            description={error}
            style={{ marginBottom: 20 }}
          />
          <Button type="primary" block href="/login">Back to Sign In</Button>
        </div>
      </div>
    )
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100vh', background: 'var(--navy-950)', color: 'var(--slate-400)',
    }}>
      Completing sign-in…
    </div>
  )
}
