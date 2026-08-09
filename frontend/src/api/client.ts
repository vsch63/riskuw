import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

// Attach Bearer token from localStorage on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('riskuw_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// On 401 → clear session and redirect to login
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('riskuw_token')
      localStorage.removeItem('riskuw_user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

// ─── Auth ────────────────────────────────────────────────────────
export const authAPI = {
  login: (username: string, password: string) =>
    api.post('/auth/login', { username, password }),

  verifyMFA: (totp_code: string, username: string, session_token?: string) =>
    api.post('/auth/verify-mfa', { totp_code, username, session_token }),

  setupMFA: (username: string, session_token: string) =>
    api.post('/auth/mfa/setup', { username, session_token }),

  verifySetupMFA: (username: string, session_token: string, totp_code: string) =>
    api.post('/auth/mfa/verify-setup', { username, session_token, totp_code }),

  disableMFA: (username: string, session_token: string) =>
    api.post('/auth/mfa/disable', { username, session_token }),

  forgotPassword: (identifier: string) =>
    api.post('/auth/forgot-password', { identifier }),

  verifyResetMFA: (token: string, totp_code: string) =>
    api.post('/auth/verify-reset-mfa', { token, totp_code }),

  resetPasswordConfirm: (token: string, new_password: string) =>
    api.post('/auth/reset-password-confirm', { token, new_password }),

  getUsers: () => api.get('/auth/users'),
}

// ─── SSO (OIDC + LDAP) ───────────────────────────────────────────
export const ssoAPI = {
  // Public — login page
  providers: () => api.get('/auth/sso/providers'),
  authorize: (providerCode: string) => api.get(`/auth/sso/${providerCode}/authorize`),

  // Admin — provider config
  listProviders: () => api.get('/auth/sso/admin/providers'),
  upsertProvider: (payload: object) => api.post('/auth/sso/admin/providers', payload),
  updateProvider: (code: string, payload: object) =>
    api.patch(`/auth/sso/admin/providers/${code}`, payload),
  deactivateProvider: (code: string) =>
    api.delete(`/auth/sso/admin/providers/${code}`),
  testProvider: (code: string) =>
    api.post(`/auth/sso/admin/providers/${code}/test`),
}

// ─── Products ────────────────────────────────────────────────────
export const productsAPI = {
  list: () => api.get('/products'),
  get: (code: string) => api.get(`/products/${code}`),
  getRules: (code: string) => api.get(`/products/${code}/rules`),
}

// ─── Underwriting ────────────────────────────────────────────────
export const uwAPI = {
  evaluate: (payload: object) =>
    api.post('/underwriting/evaluate', payload),
  aiScore: (payload: object) =>
    api.post('/underwriting/ai-score', payload),
  getCases: (pageSize = 50) =>
    api.get(`/queue/?page_size=${pageSize}`),
  getCase: (id: string) => api.get(`/queue/${id}`),
  // Multi-benefit proposal evaluation (SAR + FCL integrated)
  evaluateProposal: (payload: object) =>
    api.post('/underwriting/evaluate-proposal', payload),
}

// ─── Formula Engine (system-level, V025) ─────────────────────────
export const formulaAPI = {
  list: (params?: { formula_type?: string; product_code?: string }) =>
    api.get('/formulas', { params }),
  get: (id: string) => api.get(`/formulas/${id}`),
  create: (payload: object) => api.post('/formulas', payload),
  update: (id: string, payload: object) => api.put(`/formulas/${id}`, payload),
  remove: (id: string) => api.delete(`/formulas/${id}`),
  addStep: (id: string, payload: object) => api.post(`/formulas/${id}/steps`, payload),
  removeStep: (formulaId: string, stepId: string) =>
    api.delete(`/formulas/${formulaId}/steps/${stepId}`),
  // User labels (formula builder dropdown)
  listUserLabels: (productCode?: string) =>
    api.get('/formulas/user-labels', { params: productCode ? { product_code: productCode } : {} }),
  // Rate scales (RATE_SCALE parameter)
  listScales: () => api.get('/uw-scales'),
  // Reference tables
  listRefTables: () => api.get('/formulas/reference-tables'),
  getRefTable: (id: string) => api.get(`/formulas/reference-tables/${id}`),
  createRefTable: (payload: object) => api.post('/formulas/reference-tables', payload),
  addRefRow: (tableId: string, payload: object) =>
    api.post(`/formulas/reference-tables/${tableId}/rows`, payload),
  removeRefRow: (tableId: string, rowId: string) =>
    api.delete(`/formulas/reference-tables/${tableId}/rows/${rowId}`),
}

// ─── SAR Config (V026) ───────────────────────────────────────────
export const sarConfigAPI = {
  listBenefits: () => api.get('/sar-config/benefits'),
  benefitOptions: () => api.get('/sar-config/benefit-options'),
  upsertBenefit: (payload: object) => api.post('/sar-config/benefits', payload),
  benefitVersions: (benefitCode: string) => api.get('/sar-config/benefits/versions', { params: { benefit_code: benefitCode } }),
  listRiskGroups: () => api.get('/sar-config/risk-groups'),
  upsertRiskGroup: (payload: object) => api.post('/sar-config/risk-groups', payload),
  listExposureGroups: () => api.get('/sar-config/exposure-groups'),
  upsertExposureGroup: (payload: object) => api.post('/sar-config/exposure-groups', payload),
  listAggregationRules: () => api.get('/sar-config/aggregation-rules'),
  createAggregationRule: (payload: object) => api.post('/sar-config/aggregation-rules', payload),
  listFcl: () => api.get('/sar-config/fcl'),
  upsertFcl: (payload: object) => api.post('/sar-config/fcl', payload),
  listNml: () => api.get('/sar-config/nml'),
  upsertNml: (payload: object) => api.post('/sar-config/nml', payload),
}

// ─── In-app notifications (Phase 3d) ─────────────────────────────
export const notificationsAPI = {
  list: (unreadOnly = false, limit = 30) =>
    api.get('/notifications', { params: { unread_only: unreadOnly, limit } }),
  unreadCount: () => api.get('/notifications/unread-count'),
  markRead: (notificationId?: number) =>
    api.post('/notifications/read', notificationId ? { notification_id: notificationId } : { all: true }),
  sync: () => api.post('/notifications/sync'),
}

// ─── Medical Standards (data-driven UW catalogue, V034) ──────────
export const medicalStandardsAPI = {
  list: (productCode?: string) =>
    api.get('/medical-standards/list', { params: productCode ? { product_code: productCode } : {} }),
  get: (code: string, productCode?: string) =>
    api.get(`/medical-standards/${code}`, { params: productCode ? { product_code: productCode } : {} }),
  upsert: (code: string, payload: object) => api.put(`/medical-standards/${code}`, payload),
  remove: (code: string, productCode?: string) =>
    api.delete(`/medical-standards/${code}`, { params: productCode ? { product_code: productCode } : {} }),
}
