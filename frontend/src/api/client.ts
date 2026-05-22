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

  getUsers: () => api.get('/auth/users'),
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
  getCases: (pageSize = 50) =>
    api.get(`/queue/?page_size=${pageSize}`),
  getCase: (id: string) => api.get(`/queue/${id}`),
}
