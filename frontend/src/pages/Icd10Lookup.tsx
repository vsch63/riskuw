// Icd10Lookup.tsx
// Searchable ICD-10 code widget for the Evaluate page
// Allows underwriters to search, select codes, and auto-apply debit points

import { useState, useEffect, useRef } from 'react'
import { Input, Tag, Button, Spin, Tooltip, Modal } from 'antd'
import {
  SearchOutlined, PlusOutlined, DeleteOutlined,
  WarningOutlined, MedicineBoxOutlined,
} from '@ant-design/icons'
import { api } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────
interface ICD10Code {
  id:              number
  code:            string
  description:     string
  category:        string
  debit_points:    number
  is_hard_decline: boolean
  severity:        string
  uw_notes:        string
}

interface Props {
  onChange?: (codes: ICD10Code[], totalDebits: number) => void
}

const SEVERITY_COLOR: Record<string, string> = {
  LOW:      '#22c55e',
  MODERATE: '#f59e0b',
  HIGH:     '#ef4444',
  CRITICAL: '#7c3aed',
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function Icd10Lookup({ onChange }: Props) {
  const [query, setQuery]           = useState('')
  const [results, setResults]       = useState<ICD10Code[]>([])
  const [searching, setSearching]   = useState(false)
  const [selected, setSelected]     = useState<ICD10Code[]>([])
  const [showResults, setShowResults] = useState(false)
  const [detailCode, setDetailCode] = useState<ICD10Code | null>(null)
  const searchRef                   = useRef<ReturnType<typeof setTimeout>>()
  const wrapperRef                  = useRef<HTMLDivElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowResults(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Debounced search
  useEffect(() => {
    if (!query.trim() || query.length < 2) {
      setResults([])
      setShowResults(false)
      return
    }
    if (searchRef.current) clearTimeout(searchRef.current)
    searchRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const r = await api.get('/icd10/search', { params: { q: query, limit: 10 } })
        setResults(r.data || [])
        setShowResults(true)
      } catch { setResults([]) }
      finally { setSearching(false) }
    }, 300)
  }, [query])

  const addCode = (code: ICD10Code) => {
    if (selected.find(s => s.code === code.code)) return
    const newSelected = [...selected, code]
    setSelected(newSelected)
    setQuery('')
    setShowResults(false)
    const totalDebits = newSelected.reduce((s, c) => s + c.debit_points, 0)
    onChange?.(newSelected, totalDebits)
  }

  const removeCode = (code: string) => {
    const newSelected = selected.filter(s => s.code !== code)
    setSelected(newSelected)
    const totalDebits = newSelected.reduce((s, c) => s + c.debit_points, 0)
    onChange?.(newSelected, totalDebits)
  }

  const totalDebits    = selected.reduce((s, c) => s + c.debit_points, 0)
  const hasHardDecline = selected.some(c => c.is_hard_decline)

  return (
    <div style={{ marginBottom: 16 }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10,
      }}>
        <MedicineBoxOutlined style={{ color: '#00d4aa', fontSize: 14 }}/>
        <span style={{ fontSize: 12, fontWeight: 600, color: '#9ca3af',
          textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          ICD-10 Medical Codes
        </span>
        {selected.length > 0 && (
          <Tag style={{ marginLeft: 'auto', fontSize: 11,
            background: totalDebits > 0 ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
            border: `1px solid ${totalDebits > 0 ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)'}`,
            color: totalDebits > 0 ? '#f87171' : '#22c55e',
          }}>
            {selected.length} code{selected.length > 1 ? 's' : ''} · +{totalDebits} debits
          </Tag>
        )}
      </div>

      {/* Hard decline warning */}
      {hasHardDecline && (
        <div style={{
          background: 'rgba(239,68,68,0.1)',
          border: '1px solid rgba(239,68,68,0.3)',
          borderRadius: 8, padding: '8px 12px', marginBottom: 10,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <WarningOutlined style={{ color: '#ef4444' }}/>
          <span style={{ fontSize: 12, color: '#f87171', fontWeight: 600 }}>
            Hard Decline — one or more codes trigger automatic decline
          </span>
        </div>
      )}

      {/* Selected codes */}
      {selected.length > 0 && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10,
        }}>
          {selected.map(code => (
            <div key={code.code} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: 'rgba(255,255,255,0.04)',
              border: `1px solid ${code.is_hard_decline ? 'rgba(239,68,68,0.4)' : 'rgba(255,255,255,0.1)'}`,
              borderRadius: 6, padding: '4px 8px',
            }}>
              <span style={{
                fontSize: 11, fontWeight: 700,
                color: SEVERITY_COLOR[code.severity] || '#9ca3af',
                fontFamily: 'var(--font-mono, monospace)',
              }}>
                {code.code}
              </span>
              <Tooltip title={code.uw_notes || code.description}>
                <span style={{ fontSize: 11, color: '#9ca3af', maxWidth: 150,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  cursor: 'help' }}>
                  {code.description}
                </span>
              </Tooltip>
              <span style={{ fontSize: 11, color: '#f87171', fontWeight: 600 }}>
                +{code.debit_points}
              </span>
              <Button
                type="text" size="small" danger
                icon={<DeleteOutlined style={{ fontSize: 10 }}/>}
                onClick={() => removeCode(code.code)}
                style={{ padding: '0 2px', height: 16, minWidth: 16 }}
              />
            </div>
          ))}
        </div>
      )}

      {/* Search input */}
      <div ref={wrapperRef} style={{ position: 'relative' }}>
        <Input
          prefix={searching ? <Spin size="small"/> : <SearchOutlined style={{ color: '#6b7280' }}/>}
          placeholder="Search ICD-10 code or diagnosis (e.g. E11, diabetes, hypertension)"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setShowResults(true)}
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 8,
          }}
        />

        {/* Dropdown results */}
        {showResults && results.length > 0 && (
          <div style={{
            position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 1000,
            background: '#1a1f2e',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 8, marginTop: 4,
            maxHeight: 320, overflowY: 'auto',
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
          }}>
            {results.map(code => {
              const isAdded = selected.some(s => s.code === code.code)
              return (
                <div
                  key={code.code}
                  onClick={() => !isAdded && addCode(code)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px',
                    cursor: isAdded ? 'default' : 'pointer',
                    opacity: isAdded ? 0.5 : 1,
                    borderBottom: '1px solid rgba(255,255,255,0.05)',
                    transition: 'background 150ms',
                  }}
                  onMouseEnter={e => {
                    if (!isAdded) (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.04)'
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLDivElement).style.background = 'transparent'
                  }}
                >
                  {/* Code */}
                  <span style={{
                    fontSize: 12, fontWeight: 700, minWidth: 52,
                    color: SEVERITY_COLOR[code.severity] || '#9ca3af',
                    fontFamily: 'var(--font-mono, monospace)',
                  }}>
                    {code.code}
                  </span>

                  {/* Description */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: '#e2e8f0',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {code.description}
                    </div>
                    <div style={{ fontSize: 10, color: '#6b7280', marginTop: 1 }}>
                      {code.category}
                      {code.uw_notes && ` · ${code.uw_notes.slice(0, 50)}...`}
                    </div>
                  </div>

                  {/* Debit points */}
                  <div style={{ textAlign: 'right', minWidth: 60 }}>
                    {code.is_hard_decline ? (
                      <Tag color="error" style={{ fontSize: 10 }}>DECLINE</Tag>
                    ) : (
                      <span style={{ fontSize: 12, fontWeight: 700,
                        color: code.debit_points > 100 ? '#ef4444' :
                               code.debit_points > 50  ? '#f59e0b' : '#22c55e' }}>
                        +{code.debit_points} pts
                      </span>
                    )}
                  </div>

                  {/* Add button */}
                  {!isAdded ? (
                    <PlusOutlined style={{ color: '#00d4aa', fontSize: 12 }}/>
                  ) : (
                    <span style={{ fontSize: 10, color: '#6b7280' }}>added</span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div style={{ fontSize: 11, color: '#4b5563', marginTop: 6 }}>
        Type at least 2 characters to search. Debit points are automatically added to the evaluation.
      </div>
    </div>
  )
}
