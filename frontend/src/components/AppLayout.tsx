import { useState, useEffect } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Avatar, Tooltip, Badge, Popover, Spin, Empty } from 'antd'
import {
  ThunderboltOutlined, UnorderedListOutlined, DashboardOutlined,
  LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
  UserOutlined, InboxOutlined, UploadOutlined, SwapOutlined,
  TeamOutlined, AppstoreOutlined, FunctionOutlined, SettingOutlined, BankOutlined,
  ExportOutlined, // <--- ADDED THIS HERE
  SolutionOutlined,
  ApiOutlined,
  FundOutlined,
  CalculatorOutlined,
  MedicineBoxOutlined,
  BellOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../context/authStore'
import { AuditOutlined } from '@ant-design/icons'
import { notificationsAPI } from '../api/client'

const NAV_MAIN = [
  { key: '/',            icon: <DashboardOutlined />,     label: 'Dashboard' },
  { key: '/evaluate',    icon: <ThunderboltOutlined />,   label: 'Evaluate',    badge: 'DEMO' },
  { key: '/queue',       icon: <InboxOutlined />,         label: 'UW Queue' },
  { key: '/cases',       icon: <UnorderedListOutlined />, label: 'Cases' },
  { key: '/workbench',   icon: <SolutionOutlined />,      label: 'Workbench' },
  { key: '/integrations', icon: <ApiOutlined />,           label: 'Integrations' },
  { key: '/members',     icon: <UserOutlined />,          label: 'Members' },
  { key: '/batch',       icon: <UploadOutlined />,        label: 'Batch' },
  { key: '/reinsurance', icon: <SwapOutlined />,          label: 'Reinsurance' },
]
const NAV_CONFIG = [
  { key: '/users',          icon: <TeamOutlined />,        label: 'Users' },
  { key: '/tenants',        icon: <BankOutlined />,        label: 'Tenants' },
  { key: '/product-config', icon: <AppstoreOutlined />,    label: 'Products' },
  { key: '/sar-config',     icon: <FundOutlined />,        label: 'SAR Config' },
  { key: '/medical-standards', icon: <MedicineBoxOutlined />, label: 'Med Standards' },
  { key: '/formula-engine', icon: <CalculatorOutlined />,  label: 'Formula Engine' },
  { key: '/rule-config',    icon: <FunctionOutlined />,    label: 'Rules' },
  { key: '/system-config',  icon: <SettingOutlined />,     label: 'System' },
  { key: '/output-interface', icon: <ExportOutlined/>, label: 'Output Interface' },
  { key: '/audit'           , icon: <AuditOutlined/>,      label: 'Audit Log' },
  { key: '/developer-portal', icon: <ApiOutlined/>,        label: 'Developer Portal' },
]

const ROLE_COLOR: Record<string,string> = {
  admin:'#c084fc', super_admin:'#c084fc', senior_underwriter:'#fbbf24',
  underwriter:'#00d4aa', api_client:'#60a5fa', readonly:'#94a3b8',
}

// ── In-app notification bell (Phase 3d) ───────────────────────────────────────
const EVENT_COLOR: Record<string,string> = {
  SLA_BREACH: '#ef4444', ASSIGNMENT: '#00d4aa', REQUIREMENT: '#fbbf24',
  NOTE: '#60a5fa', DECISION: '#c084fc',
}

function timeAgo(iso: string): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  const m = Math.floor(ms / 60000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function NotificationBell({ navigate }: { navigate: (p: string) => void }) {
  const [count, setCount] = useState(0)
  const [items, setItems] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  const refreshAll = () => {
    setLoading(true)
    Promise.all([
      notificationsAPI.unreadCount(),
      notificationsAPI.list(false, 20),
    ]).then(([c, l]) => {
      setCount(c?.data?.unread ?? 0)
      setItems(l?.data?.notifications ?? [])
    }).catch(() => {}).finally(() => setLoading(false))
  }

  useEffect(() => {
    refreshAll()
    // Poll: detect SLA breaches server-side, then refresh the badge
    const t = setInterval(() => {
      notificationsAPI.sync()
        .then(d => setCount(d?.data?.unread ?? 0))
        .catch(() => refreshAll())
    }, 60_000)
    return () => clearInterval(t)
  }, [])

  const openPop = (v: boolean) => {
    setOpen(v)
    if (v) refreshAll()
  }

  const clickItem = (n: any) => {
    if (n.id) notificationsAPI.markRead(n.id).then(() => refreshAll()).catch(() => {})
    navigate('/workbench')
  }

  return (
    <Popover
      open={open}
      onOpenChange={openPop}
      trigger="click"
      placement="bottomRight"
      overlayInnerStyle={{ padding: 0, background: '#0f172a', border: '1px solid rgba(255,255,255,0.08)' }}
      content={
        <div style={{ width: 340, background: '#0f172a', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 14px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <span style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>Notifications</span>
            <a style={{ fontSize: 12, color: 'var(--teal-400)', cursor: 'pointer' }}
              onClick={() => notificationsAPI.markRead().then(() => refreshAll()).catch(() => {})}>
              Mark all read
            </a>
          </div>
          <div style={{ maxHeight: 360, overflow: 'auto' }}>
            {loading ? <div style={{ textAlign: 'center', padding: 28 }}><Spin size="small" /></div>
              : items.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 28 }}><Empty description={<span style={{ color: '#64748b', fontSize: 12 }}>No notifications</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} /></div>
              ) : items.map((n: any) => (
                <div key={n.id} onClick={() => clickItem(n)} style={{
                  display: 'flex', gap: 10, padding: '10px 14px', cursor: 'pointer',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                  background: n.is_read ? 'transparent' : 'rgba(0,212,170,0.05)',
                }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', marginTop: 5, flexShrink: 0,
                    background: EVENT_COLOR[n.event_type] ?? '#64748b' }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ color: '#e2e8f0', fontSize: 12.5, fontWeight: n.is_read ? 400 : 600 }}>{n.title}</span>
                      <span style={{ color: '#64748b', fontSize: 11, flexShrink: 0 }}>{timeAgo(n.created_at)}</span>
                    </div>
                    {n.body && <div style={{ color: '#94a3b8', fontSize: 11.5, marginTop: 2,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.body}</div>}
                    {n.case_ref_id && <div style={{ color: '#475569', fontSize: 10.5, fontFamily: 'var(--font-mono)', marginTop: 2 }}>
                      case #{n.case_ref_id}
                    </div>}
                  </div>
                </div>
              ))}
          </div>
        </div>
      }
    >
      <Tooltip title="Notifications">
        <Badge count={count} size="small" offset={[-2, 2]} style={{ boxShadow: 'none' }}>
          <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--slate-400)',
            padding: '4px 6px', borderRadius: 6, display: 'flex', transition: 'color 150ms' }}
            onMouseEnter={e => ((e.currentTarget as HTMLElement).style.color = 'var(--teal-400)')}
            onMouseLeave={e => ((e.currentTarget as HTMLElement).style.color = 'var(--slate-400)')}
          >
            <BellOutlined style={{ fontSize: 16 }} />
          </button>
        </Badge>
      </Tooltip>
    </Popover>
  )
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
            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)',
            cursor: 'pointer' }}
            onClick={() => navigate('/my-account')}
            onMouseEnter={e => ((e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.08)')}
            onMouseLeave={e => ((e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)')}
          >
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: 12, color: 'var(--slate-500)' }}>
            <NotificationBell navigate={navigate} />
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
