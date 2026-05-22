import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Avatar, Tooltip, Badge } from 'antd'
import {
  ThunderboltOutlined, UnorderedListOutlined, DashboardOutlined,
  LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
  UserOutlined, InboxOutlined, UploadOutlined, SwapOutlined,
  TeamOutlined, AppstoreOutlined, FunctionOutlined, SettingOutlined, BankOutlined,
  ExportOutlined // <--- ADDED THIS HERE
} from '@ant-design/icons'
import { useAuthStore } from '../context/authStore'
import { AuditOutlined } from '@ant-design/icons'

const NAV_MAIN = [
  { key: '/',            icon: <DashboardOutlined />,     label: 'Dashboard' },
  { key: '/evaluate',    icon: <ThunderboltOutlined />,   label: 'Evaluate',    badge: 'DEMO' },
  { key: '/queue',       icon: <InboxOutlined />,         label: 'UW Queue' },
  { key: '/cases',       icon: <UnorderedListOutlined />, label: 'Cases' },
  { key: '/members',     icon: <UserOutlined />,          label: 'Members' },
  { key: '/batch',       icon: <UploadOutlined />,        label: 'Batch' },
  { key: '/reinsurance', icon: <SwapOutlined />,          label: 'Reinsurance' },
]
const NAV_CONFIG = [
  { key: '/users',          icon: <TeamOutlined />,        label: 'Users' },
  { key: '/tenants',        icon: <BankOutlined />,        label: 'Tenants' },
  { key: '/product-config', icon: <AppstoreOutlined />,    label: 'Products' },
  { key: '/rule-config',    icon: <FunctionOutlined />,    label: 'Rules' },
  { key: '/system-config',  icon: <SettingOutlined />,     label: 'System' },
  { key: '/output-interface', icon: <ExportOutlined/>, label: 'Output Interface' },
  { key: '/audit'           , icon: <AuditOutlined/>,      label: 'Audit Log' }
]

const ROLE_COLOR: Record<string,string> = {
  admin:'#c084fc', super_admin:'#c084fc', senior_underwriter:'#fbbf24',
  underwriter:'#00d4aa', api_client:'#60a5fa', readonly:'#94a3b8',
}

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const sideW = collapsed ? 64 : 228

  const NavBtn = ({ item }: { item: typeof NAV_MAIN[0] }) => {
    const active = location.pathname === item.key
    return (
      <Tooltip title={collapsed ? item.label : ''} placement="right" mouseEnterDelay={0.2}>
        <button onClick={() => navigate(item.key)} style={{
          width: '100%', display: 'flex', alignItems: 'center',
          gap: 10, padding: collapsed ? '10px 14px' : '9px 12px',
          borderRadius: 8, border: 'none', cursor: 'pointer', marginBottom: 2,
          position: 'relative',
          background: active ? 'rgba(0,212,170,0.12)' : 'transparent',
          color: active ? 'var(--teal-400)' : 'var(--slate-400)',
          fontSize: 14, fontFamily: 'var(--font-body)', transition: 'all 160ms', outline: 'none',
        }}
          onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.05)' }}
          onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
        >
          {active && <div style={{ position: 'absolute', left: 0, top: '20%', bottom: '20%',
            width: 3, background: 'var(--teal-500)', borderRadius: '0 2px 2px 0' }} />}
          <span style={{ fontSize: 15, flexShrink: 0 }}>{item.icon}</span>
          {!collapsed && (
            <>
              <span style={{ flex: 1, textAlign: 'left', fontWeight: active ? 600 : 400 }}>{item.label}</span>
              {(item as any).badge && (
                <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 600,
                  background: 'rgba(0,212,170,0.15)', color: 'var(--teal-400)',
                  padding: '2px 6px', borderRadius: 4, letterSpacing: '0.06em' }}>
                  {(item as any).badge}
                </span>
              )}
            </>
          )}
        </button>
      </Tooltip>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--navy-950)' }}>
      <aside style={{
        width: sideW, flexShrink: 0, transition: 'width 220ms cubic-bezier(0.4,0,0.2,1)',
        background: 'var(--navy-900)', borderRight: '1px solid rgba(255,255,255,0.06)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative', zIndex: 10,
      }}>
        {/* Logo */}
        <div style={{ height: 56, display: 'flex', alignItems: 'center',
          padding: collapsed ? '0 18px' : '0 20px',
          borderBottom: '1px solid rgba(255,255,255,0.06)', gap: 10, overflow: 'hidden', flexShrink: 0 }}>
          <svg width="26" height="26" viewBox="0 0 36 36" fill="none" style={{ flexShrink: 0 }}>
            <path d="M18 3 L32 8 L32 20 C32 27 18 33 18 33 C18 33 4 27 4 20 L4 8 Z"
              fill="none" stroke="#00d4aa" strokeWidth="1.8" strokeLinejoin="round" />
            <path d="M12 18 L16 22 L24 14" stroke="#00d4aa" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {!collapsed && (
            <div>
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700,
                fontSize: 16, color: '#fff', letterSpacing: '-0.01em', lineHeight: 1 }}>RiskUW</div>
              <div style={{ fontSize: 9, color: 'var(--teal-500)', letterSpacing: '0.1em', marginTop: 2 }}>
                UNDERWRITING
              </div>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: '12px 8px', overflow: 'hidden auto' }}>
          {/* Main nav */}
          {NAV_MAIN.map(item => <NavBtn key={item.key} item={item} />)}

          {/* Config group divider */}
          {!collapsed && (
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--slate-600)',
              letterSpacing: '0.12em', textTransform: 'uppercase',
              padding: '14px 12px 6px', marginTop: 4 }}>
              Configuration
            </div>
          )}
          {collapsed && <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', margin: '8px 0' }} />}
          {NAV_CONFIG.map(item => <NavBtn key={item.key} item={item} />)}
        </nav>

        {/* Bottom */}
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '10px 8px', flexShrink: 0 }}>
          <button onClick={() => setCollapsed(!collapsed)} style={{
            width: '100%', display: 'flex', alignItems: 'center', gap: 10,
            padding: collapsed ? '9px 14px' : '9px 12px',
            borderRadius: 8, border: 'none', cursor: 'pointer',
            background: 'transparent', color: 'var(--slate-500)',
            fontSize: 14, marginBottom: 8, transition: 'all 160ms',
          }}
            onMouseEnter={e => ((e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.05)')}
            onMouseLeave={e => ((e.currentTarget as HTMLElement).style.background = 'transparent')}
          >
            {collapsed ? <MenuUnfoldOutlined style={{ fontSize: 15 }} /> : <MenuFoldOutlined style={{ fontSize: 15 }} />}
            {!collapsed && <span>Collapse</span>}
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 10px', borderRadius: 8,
            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
            <Badge dot status="success" offset={[-2, 28]} style={{ backgroundColor: '#22c55e' }}>
              <Avatar size={32} style={{ background: 'rgba(0,212,170,0.15)',
                color: 'var(--teal-400)', fontSize: 13, fontWeight: 600, flexShrink: 0 }}
                icon={<UserOutlined />} />
            </Badge>
            {!collapsed && (
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#fff',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {user?.username ?? '—'}
                </div>
                <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)',
                  color: ROLE_COLOR[user?.role ?? ''] ?? 'var(--slate-400)',
                  textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  {user?.role ?? '—'}
                </div>
              </div>
            )}
            {!collapsed && (
              <Tooltip title="Sign out">
                <button onClick={logout} style={{ background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--slate-500)', padding: '4px', borderRadius: 4, display: 'flex', transition: 'color 150ms' }}
                  onMouseEnter={e => ((e.currentTarget as HTMLElement).style.color = 'var(--red-400)')}
                  onMouseLeave={e => ((e.currentTarget as HTMLElement).style.color = 'var(--slate-500)')}
                >
                  <LogoutOutlined />
                </button>
              </Tooltip>
            )}
          </div>
        </div>
      </aside>

      {/* Main */}
      <main style={{ flex: 1, overflow: 'hidden auto', background: 'var(--navy-950)',
        display: 'flex', flexDirection: 'column' }}>
        <header style={{ height: 56, flexShrink: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', padding: '0 28px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          background: 'var(--navy-900)', position: 'sticky', top: 0, zIndex: 5 }}>
          <div style={{ fontSize: 13, color: 'var(--slate-500)', fontFamily: 'var(--font-mono)' }}>
            riskuw.online
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--slate-500)' }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#22c55e',
              boxShadow: '0 0 8px rgba(34,197,94,0.6)', display: 'inline-block' }} />
            Engine online
          </div>
        </header>
        <div style={{ flex: 1, overflow: 'hidden auto' }}><Outlet /></div>
      </main>
    </div>
  )
}
