import { create } from 'zustand'
import type { AuthUser } from '../types'

interface AuthState {
  user: AuthUser | null
  mfaPending: boolean
  mfaUsername: string
  mfaSessionToken: string
  setUser: (u: AuthUser) => void
  setMFAPending: (username: string, sessionToken?: string) => void
  clearMFA: () => void
  logout: () => void
}

const storedUser = (() => {
  try {
    const raw = localStorage.getItem('riskuw_user')
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
})()

export const useAuthStore = create<AuthState>((set) => ({
  user: storedUser,
  mfaPending: false,
  mfaUsername: '',
  mfaSessionToken: '',

  setUser: (u) => {
    localStorage.setItem('riskuw_token', u.token)
    localStorage.setItem('riskuw_user', JSON.stringify(u))
    set({ user: u, mfaPending: false, mfaUsername: '', mfaSessionToken: '' })
  },

  setMFAPending: (username, sessionToken = '') => {
    set({ mfaPending: true, mfaUsername: username, mfaSessionToken: sessionToken })
  },

  clearMFA: () => {
    set({ mfaPending: false, mfaUsername: '', mfaSessionToken: '' })
  },

  logout: () => {
    localStorage.removeItem('riskuw_token')
    localStorage.removeItem('riskuw_user')
    set({ user: null, mfaPending: false, mfaUsername: '', mfaSessionToken: '' })
  },
}))
