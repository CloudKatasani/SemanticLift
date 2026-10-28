import React, { useMemo, useRef, useState } from 'react'
import { Conf, Loading, Section, fmt, useApi } from '../components'

const W = 1100, H = 720, PAD = 60

function color(c) {
  return c >= 0.8 ? 'var(--good)' : c >= 0.6 ? 'var(--warn)' : 'var(--bad)'
}

export default function Model({ arg }) {
  const { data, error, loading } = useApi('/api/model')
  const [sel, setSel] = useState(arg || null)
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const [filter, setFilter] = useState('')
  const drag = useRef(null)

  const layout = useMemo(() => {
    if (!data) return null
    const xs = data.entities.map((e) => e.x), ys = data.entities.map((e) => e.y)
    const [minx, maxx, miny, maxy] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const pos = {}
    data.entities.forEach((e) => {
      pos[e.name] = { x: PAD + ((e.x - minx) / (maxx - minx || 1)) * (W - 2 * PAD), y: PAD + ((e.y - miny) / (maxy - miny || 1)) * (H - 2 * PAD) }
    })
    return pos
  }, [data])

  const ent = data && sel ? data.entities.find((e) => e.name === sel) : null
  const issues = data && sel ? data.join_issues.filter((j) => j.key.includes(sel)) : []
  const hl = (n) => !filter || n.toLowerCase().includes(filter.toLowerCase())

  const onWheel = (e) => {
    const k = Math.max(0.4, Math.min(3, view.k * (e.deltaY < 0 ? 1.1 : 0.9)))
    setView({ ...view, k })
  }
  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>Model canvas</h1>
          <p className="lede">Logical entities coloured by confidence (green ≥ 0.8 FM-defined, amber 0.6 matched, red 0.3 inferred from reports only). Squares are facts, circles dimensions; dashed edges are relationships inferred from co-usage. Click an entity for attributes, measures, lineage and the reports that use it.</p>
          <div className="model">
            <div className="canvas card">
              <div className="row gap pad-s">
                <input className="search" placeholder="Highlight entity…" value={filter} onChange={(e) => setFilter(e.target.value)} />
                <button className="btn" onClick={() => setView({ x: 0, y: 0, k: 1 })}>Reset view</button>
                <span className="legend"><i style={{ background: 'var(--good)' }} />≥0.8 <i style={{ background: 'var(--warn)' }} />0.6 <i style={{ background: 'var(--bad)' }} />0.3 <b className="ring" /> conformed</span>
              </div>
              <svg viewBox={`0 0 ${W} ${H}`} onWheel={onWheel}
                   onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, v: view } }}
                   onMouseMove={(e) => { if (drag.current) setView({ ...drag.current.v, x: drag.current.v.x + (e.clientX - drag.current.x), y: drag.current.v.y + (e.clientY - drag.current.y) }) }}
                   onMouseUp={() => { drag.current = null }} onMouseLeave={() => { drag.current = null }}>
                <defs><marker id="arr" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="#8a94a6" /></marker></defs>
                <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
                  {data.relationships.map((r) => {
                    const a = layout[r.from], b = layout[r.to]
                    if (!a || !b) return null
                    const on = sel && (r.from === sel || r.to === sel)
                    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1
                    return <line key={r.name} x1={a.x} y1={a.y} x2={b.x - (dx / len) * 16} y2={b.y - (dy / len) * 16}
                                 stroke={on ? '#2f6fde' : '#b8c0cc'} strokeWidth={on ? 2.4 : 1.2}
                                 strokeDasharray={r.origin === 'FM' ? '' : '5 4'} markerEnd="url(#arr)"><title>{r.name} ({r.origin}, {r.cardinality})</title></line>
                  })}
                  {data.entities.map((e) => {
                    const p = layout[e.name]
                    const s = 13 + Math.min(10, Math.sqrt(e.report_count || 1))
                    const op = hl(e.name) ? 1 : 0.25
                    return (
                      <g key={e.name} transform={`translate(${p.x},${p.y})`} onClick={() => setSel(e.name)} style={{ cursor: 'pointer', opacity: op }}>
                        {e.conformed && <circle r={s + 6} fill="none" stroke="#2f6fde" strokeWidth="2" />}
                        {e.role === 'fact'
                          ? <rect x={-s} y={-s} width={2 * s} height={2 * s} rx="4" fill={color(e.confidence)} stroke={sel === e.name ? '#111' : '#fff'} strokeWidth="2" />
                          : <circle r={s} fill={color(e.confidence)} stroke={sel === e.name ? '#111' : '#fff'} strokeWidth="2" />}
                        <text y={s + 15} textAnchor="middle" className="node-label">{e.name}</text>
                      </g>)
                  })}
                </g>
              </svg>
            </div>
            <div className="side card">
              {!ent && <div className="muted pad">Select an entity.<br /><br />{data.entities.length} entities · {data.relationships.length} relationships · {data.join_issues.length} join-path issues</div>}
              {ent && (
                <div>
                  <h2>{ent.name}</h2>
                  <div className="row gap wrap">
                    <span className="tag">{ent.role}</span><span className="tag">{ent.origin}</span><Conf value={ent.confidence} />
                    {ent.conformed && <span className="tag blue">conformed</span>}
                  </div>
                  <div className="small muted">Domain {ent.domain} · used by {ent.report_count} reports · PK {ent.primary_key.join(', ') || 'TODO'}</div>
                  <h4>Target objects</h4>
                  <div>{ent.targets.map((t) => <a key={t} className="chip" href={`#/review/${t}`}>{t}</a>)}</div>
                  <h4>Attributes & measures ({ent.attributes.length})</h4>
                  <table className="tbl compact">
                    <thead><tr><th>Item</th><th>Kind</th><th>Agg</th><th>Conf</th><th>Target column</th></tr></thead>
                    <tbody>{ent.attributes.map((a) => (
                      <tr key={a.name} title={`${a.expression || ''}\nsemantic: ${a.semantic.join(', ')}`}>
                        <td>{a.name}{a.sensitive && <span className="pill bad tiny">PII</span>}</td><td className="small">{a.kind}</td>
                        <td className="small">{a.aggregation}{a.additivity && a.additivity !== 'additive' ? ` (${a.additivity})` : ''}</td>
                        <td><Conf value={a.confidence} /></td><td className="mono tiny">{a.target}</td></tr>))}</tbody>
                  </table>
                  {issues.length > 0 && (<><h4>Join-path issues</h4>{issues.map((j, i) => (
                    <div key={i} className="issue"><b>{j.kind.replace('_', ' ')}</b> {j.key.join(' / ')} — {j.count} queries<div className="small muted">{j.detail}</div></div>))}</>)}
                  <h4>Relationships</h4>
                  {data.relationships.filter((r) => r.from === ent.name || r.to === ent.name).map((r) => (
                    <div key={r.name} className="small"><span className="mono">{r.from} → {r.to}</span> <span className="muted">({r.origin}, {r.keys.map((k) => k.join('=')).join(', ')})</span> <Conf value={r.confidence} /></div>))}
                  <h4>Reports ({fmt(ent.report_count)})</h4>
                  <div className="small reports">{ent.reports.slice(0, 60).join(', ')}{ent.reports.length > 60 ? ' …' : ''}</div>
                </div>)}
            </div>
          </div>
          <Section title="Conformed dimensions">
            <table className="tbl"><thead><tr><th>Dimension</th><th>Packages</th><th>Core attributes</th><th>Package extensions</th></tr></thead>
              <tbody>{Object.entries(data.conformed).map(([k, v]) => (
                <tr key={k}><td><b>{k}</b></td><td className="small">{v.packages.filter((p) => v.per_package[p]).length}</td><td className="small">{v.core.join(', ')}</td>
                  <td className="small">{Object.entries(v.extensions).filter(([, x]) => x.length).map(([p, x]) => `${p.replace(/^Energy_|_Package$/g, '')}: ${x.join(', ')}`).join(' · ')}</td></tr>))}</tbody></table>
          </Section>
        </div>
      )}
    </Loading>
  )
}
