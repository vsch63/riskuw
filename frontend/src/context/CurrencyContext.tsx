import { createContext, useContext, useEffect, useState, ReactNode } from 'react'

interface CurrencyInfo {
  currency_code: string
  currency_symbol: string
  currency_name: string
  country_name: string
  flag: string
}

interface CurrencyContextValue {
  currency: CurrencyInfo
  loading: boolean
  fmt: (value: number | null | undefined, opts?: { decimals?: number }) => string
  fmtCompact: (value: number | null | undefined) => string  // e.g. ₹12.5L, $1.2M
}

const DEFAULT_CURRENCY: CurrencyInfo = {
  currency_code: 'INR',
  currency_symbol: '₹',
  currency_name: 'Indian Rupee',
  country_name: 'India',
  flag: '🇮🇳',
}

const CurrencyContext = createContext<CurrencyContextValue>({
  currency: DEFAULT_CURRENCY,
  loading: true,
  fmt: (v) => `₹${new Intl.NumberFormat('en-IN').format(v || 0)}`,
  fmtCompact: (v) => `₹${new Intl.NumberFormat('en-IN').format(v || 0)}`,
})

// Locale map for number formatting per currency
const LOCALE_MAP: Record<string, string> = {
  INR: 'en-IN', AED: 'en-AE', SGD: 'en-SG', GBP: 'en-GB', USD: 'en-US',
}

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [currency, setCurrency] = useState<CurrencyInfo>(DEFAULT_CURRENCY)
  const [loading, setLoading]   = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('riskuw_token')
    if (!token) { setLoading(false); return }

    fetch('/integrations/tenant-context', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(d => {
        if (d?.currency) {
          setCurrency(d.currency)
          try {
            localStorage.setItem('riskuw_currency_symbol', d.currency.currency_symbol)
            localStorage.setItem('riskuw_currency_code', d.currency.currency_code)
          } catch {}
        }
      })
      .catch(() => {
        // Silent fallback to default (INR) — never block the app on this
      })
      .finally(() => setLoading(false))
  }, [])

  const fmt = (value: number | null | undefined, opts?: { decimals?: number }) => {
    const v = value ?? 0
    const locale = LOCALE_MAP[currency.currency_code] || 'en-IN'
    const formatted = opts?.decimals !== undefined
      ? v.toFixed(opts.decimals)
      : new Intl.NumberFormat(locale).format(v)
    return `${currency.currency_symbol}${formatted}`
  }

  // Compact format for large numbers: ₹12.5L / ₹1.2Cr (India) or $1.2M (others)
  const fmtCompact = (value: number | null | undefined) => {
    const v = value ?? 0
    if (currency.currency_code === 'INR') {
      // Indian numbering: Lakh / Crore
      if (Math.abs(v) >= 10000000) return `${currency.currency_symbol}${(v / 10000000).toFixed(2)}Cr`
      if (Math.abs(v) >= 100000)   return `${currency.currency_symbol}${(v / 100000).toFixed(2)}L`
      return fmt(v)
    }
    // International: K / M / B
    if (Math.abs(v) >= 1000000000) return `${currency.currency_symbol}${(v / 1000000000).toFixed(2)}B`
    if (Math.abs(v) >= 1000000)    return `${currency.currency_symbol}${(v / 1000000).toFixed(2)}M`
    if (Math.abs(v) >= 1000)       return `${currency.currency_symbol}${(v / 1000).toFixed(1)}K`
    return fmt(v)
  }

  return (
    <CurrencyContext.Provider value={{ currency, loading, fmt, fmtCompact }}>
      {children}
    </CurrencyContext.Provider>
  )
}

export function useCurrency() {
  return useContext(CurrencyContext)
}

// Standalone fmt for non-component contexts (e.g. inside a plain function before hooks)
// Falls back to reading currency_symbol from localStorage cache if available, else ₹.
export function fmtCurrencyStandalone(value: number | null | undefined): string {
  const cached = localStorage.getItem('riskuw_currency_symbol') || '₹'
  return `${cached}${new Intl.NumberFormat('en-IN').format(value || 0)}`
}

