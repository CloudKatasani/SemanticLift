import React, { useEffect, useState } from 'react'
import { api } from './api'

export function useApi(url, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const load = () => {
    if (!url) return
    setLoading(true)
    api.get(url).then((d) => { setData(d); setError(null) }).catch(setError).finally(() => setLoading(false))
  }
  useEffect(load, [url, ...deps])
  return { data, error, loading, reload: load, setData }
}

export function Loading({ error, loading, children }) {
  if (error) {
    if (error.status === 404) return <Empty>No run yet. Go to <a href="#/ingest">Ingest</a>, upload the Cognos bundle and run the pipeline.</Empty>
    return <div className="error">{String(error.message || error)}</div>
  }
  if (loading) return <div className="muted pad">Loading…</div>
  return children
}

export const Empty = ({ children }) => <div className="empty">{children}</div>

export function Kpi({ label, value, sub, tone }) {
  return (
    <div className={`kpi ${tone || ''}`}>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  )
}

export function Conf({ value }) {
  const v = Number(value || 0)
  const tone = v >= 0.8 ? 'good' : v >= 0.6 ? 'warn' : 'bad'
  return <span className={`pill ${tone}`}>{v.toFixed(2)}</span>
}

export function Status({ value }) {
  return <span className={`status s-${(value || '').replace(/\s+/g, '-').toLowerCase()}`}>{value}</span>
}

export function Sev({ value }) {
  return <span className={`sev sev-${value}`}>{value}</span>
}

export function Bar({ value, max, label, tone }) {
  const pct = max ? Math.max(0, Math.min(100, (100 * value) / max)) : 0
  return (
    <div className="bar" title={label || String(value)}>
      <div className={`bar-fill ${tone || ''}`} style={{ width: `${pct}%` }} />
      <span className="bar-label">{label ?? value}</span>
    </div>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs">
      {tabs.map((t) => (
        <button key={t.key} className={t.key === value ? 'tab active' : 'tab'} onClick={() => onChange(t.key)}>
          {t.label}{t.count != null && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function SearchBox({ value, onChange, placeholder }) {
  return <input className="search" value={value} placeholder={placeholder || 'Search…'} onChange={(e) => onChange(e.target.value)} />
}

export function Section({ title, children, actions }) {
  return (
    <section className="card">
      <div className="card-head"><h3>{title}</h3><div>{actions}</div></div>
      {children}
    </section>
  )
}

export const fmt = (n, d = 0) => (n == null || n === '' ? '–' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }))
