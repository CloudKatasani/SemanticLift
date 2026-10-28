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

/** Banner shown when steward decisions are saved but not yet applied to the design. */
export function RerunBanner({ pending, onDone }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  if (!pending) return null
  const go = async () => {
    setBusy(true); setErr(null)
    try { await api.post('/api/rerun'); onDone && onDone() } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <div className="banner">
      <span>Decisions saved. Re-run the pipeline to apply them to the design, semantic views and data products.</span>
      <button className="btn primary" disabled={busy} onClick={go}>{busy ? 'Re-running…' : 'Apply decisions (re-run)'}</button>
      {err && <span className="error inline">{err}</span>}
    </div>
  )
}

export const DISP_TONE = { Keep: 'good', Review: 'warn', Consolidate: 'info', Retire: 'bad' }
export function Disp({ value }) {
  return <span className={`disp disp-${(value || '').toLowerCase()}`}>{value}</span>
}

/**
 * Generic left-to-right lane diagram.
 * lanes: [{key, title, sub}]; nodes: [{key, lane, label, fill, title}]; edges: [{a, b, dashed}]
 */
export function LaneDiagram({ lanes, nodes, edges, laneWidth = 200, gap = 46, nodeH = 24, onSelect, selected, minWidth = 900 }) {
  const TOP = 54, NG = 6
  const byLane = {}
  nodes.forEach((n) => { (byLane[n.lane] = byLane[n.lane] || []).push(n) })
  const pos = {}
  let height = 0
  lanes.forEach((ln, i) => {
    (byLane[ln.key] || []).forEach((n, j) => { pos[n.key] = { x: 20 + i * (laneWidth + gap), y: TOP + j * (nodeH + NG) } })
    height = Math.max(height, TOP + (byLane[ln.key] || []).length * (nodeH + NG))
  })
  const width = 20 + lanes.length * (laneWidth + gap) - gap + 20
  const hot = (() => {
    if (!selected) return null
    const seen = new Set([selected])
    for (const dir of ['down', 'up']) {
      const q = [selected]
      while (q.length) {
        const cur = q.shift()
        edges.forEach((e) => {
          const [f, t] = dir === 'down' ? [e.a, e.b] : [e.b, e.a]
          if (f === cur && !seen.has(t)) { seen.add(t); q.push(t) }
        })
      }
    }
    return seen
  })()
  const maxChars = Math.floor(laneWidth / 6.6)
  return (
    <svg viewBox={`0 0 ${width} ${height + 20}`} width="100%" style={{ minWidth, fontFamily: 'Inter, Segoe UI, sans-serif' }}>
      {lanes.map((ln, i) => (
        <g key={ln.key} transform={`translate(${20 + i * (laneWidth + gap)},10)`}>
          <text fontSize="12" fontWeight="700" fill="#1c2430">{ln.title}</text>
          <text y="16" fontSize="10.5" fill="#8a94a6">{ln.sub}</text>
        </g>))}
      {edges.map((e, i) => {
        const a = pos[e.a], b = pos[e.b]
        if (!a || !b) return null
        const x1 = a.x + laneWidth, y1 = a.y + nodeH / 2, x2 = b.x, y2 = b.y + nodeH / 2
        const on = hot && hot.has(e.a) && hot.has(e.b)
        return <path key={i} d={`M${x1},${y1} C${x1 + gap / 2},${y1} ${x2 - gap / 2},${y2} ${x2},${y2}`} fill="none"
                     stroke={on ? '#2f6fde' : '#c3cad6'} strokeWidth={on ? 2 : 1} opacity={hot && !on ? 0.25 : 1}
                     strokeDasharray={e.dashed ? '4 3' : ''} />
      })}
      {nodes.map((n) => {
        const p = pos[n.key]
        const dim = hot && !hot.has(n.key)
        return (
          <g key={n.key} transform={`translate(${p.x},${p.y})`} style={{ cursor: onSelect ? 'pointer' : 'default', opacity: dim ? 0.3 : 1 }}
             onClick={() => onSelect && onSelect(n.key === selected ? null : n.key)}>
            <rect width={laneWidth} height={nodeH} rx="6" fill={n.fill || '#eef1f6'} stroke={n.key === selected ? '#2f6fde' : '#d5dbe4'}
                  strokeWidth={n.key === selected ? 2 : 1} strokeDasharray={n.dashedBox ? '4 3' : ''} />
            <text x="8" y="16" fontSize="11" fill="#1c2430">{n.label.length > maxChars ? n.label.slice(0, maxChars - 1) + '…' : n.label}</text>
            <title>{n.title || n.label}</title>
          </g>)
      })}
    </svg>
  )
}

export function downloadCsv(filename, rows) {
  if (!rows.length) return
  const keys = Object.keys(rows[0])
  const esc = (v) => { const s = v == null ? '' : Array.isArray(v) ? v.join('; ') : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s }
  const text = [keys.join(','), ...rows.map((r) => keys.map((k) => esc(r[k])).join(','))].join('\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  a.download = filename
  a.click()
}
