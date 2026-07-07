import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './context/authStore'
import { CurrencyProvider } from './context/CurrencyContext'
import LoginPage from './pages/LoginPage'
import AppLayout from './components/AppLayout'
import EvaluatePage from './pages/EvaluatePage'
import DashboardPage from './pages/DashboardPage'
import CasesPage from './pages/CasesPage'
import QueuePage from './pages/QueuePage'
import BatchJobsPage from "./pages/BatchJobsPage"
import ReinsurancePage from './pages/ReinsurancePage'
import UserManagementPage from './pages/UserManagementPage'
import ProductConfigPage from './pages/ProductConfigPage'
import RuleConfigPage from './pages/RuleConfigPage'
import SystemConfigPage from './pages/SystemConfigPage'
import TenantManagementPage from './pages/TenantManagementPage'
import OutputInterfacePage from './pages/OutputInterfacePage'
import AuditLogPage from './pages/AuditLogPage'
import MembersPage from './pages/MembersPage'
import DebitScalePage from './pages/DebitScalePage'
import MyAccountPage from './pages/MyAccountPage'
import WorkbenchPage from './pages/WorkbenchPage'
import AgentPortalPage from './pages/AgentPortalPage'
import PolicyAdminPage from './pages/PolicyAdminPage'
import IntegrationsPage from './pages/IntegrationsPage'
import DeveloperPortalPage from './pages/DeveloperPortalPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  return user ? <>{children}</> : <Navigate to="/login" replace />
}

function RequireUW({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (!user) return <Navigate to="/login" replace />
  if (user.role === 'agent' || user.role === 'broker') return <Navigate to="/agent-portal" replace />
  return <>{children}</>
}

export default function App() {
  const user = useAuthStore((s) => s.user)
  return (
    <CurrencyProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route path="/" element={<RequireUW><AppLayout /></RequireUW>}>
          <Route index element={<DashboardPage />} />
          <Route path="evaluate"       element={<EvaluatePage />} />
          <Route path="/workbench" element={<WorkbenchPage />} />
          <Route path="queue"          element={<QueuePage />} />
          <Route path="cases"          element={<CasesPage />} />
          <Route path="batch"          element={<BatchJobsPage />} />
          <Route path="reinsurance"    element={<ReinsurancePage />} />
          <Route path="users"          element={<UserManagementPage />} />
          <Route path="product-config" element={<ProductConfigPage />} />
          <Route path="rule-config"    element={<RuleConfigPage />} />
          <Route path="system-config"  element={<SystemConfigPage />} />
          <Route path="/scale-builder" element={<DebitScalePage/>}/>
          <Route path="tenants" element={<TenantManagementPage />} />
          <Route path="output-interface" element={<OutputInterfacePage />} />
          <Route path="audit"   element={<AuditLogPage />} />
          <Route path="members" element={<MembersPage />} />
          <Route path="policy-admin" element={<PolicyAdminPage />} />
          <Route path="/integrations" element={<IntegrationsPage />} />
          <Route path="/developer-portal" element={<DeveloperPortalPage />} />
          <Route path="/my-account" element={<MyAccountPage />} />
        </Route>
        <Route path="/agent-portal" element={
          <RequireAuth>
            <AgentPortalPage/>
          </RequireAuth>
        }/>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
    </CurrencyProvider>
  )
}

