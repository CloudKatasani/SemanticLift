import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Conf, Loading, useApi } from '../components'

const BOX_W = 250, HEAD = 40, ROW = 18, MAX_ROWS = 14, COL_GAP = 120, ROW_GAP = 34, MARGIN = 30

const ROLE_ICON = { pk: 'PK', fk: 'FK', sk: 'SK', measure: 'Σ', derived: 'ƒ', attribute: '' }

function visibleColumns(t, opts) {
  return t.columns.filter((c) => {
    if (c.role === 'sk') return opts.showKeys
    if (c.role === 'measure' || c.role === 'derived') return opts.showMeasures
    if (c.role === 'attribute') return opts.showAttributes
    return true
  })
}

/** Layered layout: facts in the centre column, dimensions in columns left/right by n:1 distance. */
function layout(tables, opts, expanded) {
  const ids = new Set(tables.map((t) => t.id))
  const byId = Object.fromEntries(tables.map((t) => [t.id, t]))
  const out = {}
  tables.forEach((t) => { out[t.id] = t.foreign_keys.filter((f) => ids.has(f.ref_table)).map((f) => f.ref_table) })
  const facts = tables.filter((t) => t.kind === 'fact').map((t) => t.id)
  const roots = facts.length ? facts : tables.filter((t) => !tables.some((x) => out[x.id].includes(t.id))).map((t) => t.id)
  const depth = {}
  const queue = []
  roots.forEach((r) => { depth[r] = 0; queue.push(r) })
  while (queue.length) {
    const cur = queue.shift()
    for (const n of out[cur] || []) {
      if (depth[n] == null) { depth[n] = depth[cur] + 1; queue.push(n) }
    }
  }
  tables.forEach((t) => { if (depth[t.id] == null) depth[t.id] = 1 })
  // Depth-1 dimensions alternate left/right of the facts; deeper (snowflaked) ones follow their parent's side.
  const cols = {}
  const side = {}
  const maxDepth = Math.max(0, ...Object.values(depth))
  for (let dpt = 0; dpt <= maxDepth; dpt++) {
    const level = tables.filter((t) => depth[t.id] === dpt).map((t) => t.id)
    if (dpt === 0) { cols[0] = level; continue }
    const parentOf = (id) => tables.find((t) => depth[t.id] === dpt - 1 && out[t.id].includes(id))
    const order = level.slice().sort((a, b) => {
      const pa = parentOf(a), pb = parentOf(b)
      const ia = pa ? tables.indexOf(pa) : 999, ib = pb ? tables.indexOf(pb) : 999
      return ia - ib || a.localeCompare(b)
    })
    let flip = 0
    cols[-dpt] = []
    cols[dpt] = []
    order.forEach((id) => {
      const p = parentOf(id)
      const sd = dpt > 1 && p && side[p.id] ? side[p.id] : (flip++ % 2 === 0 ? 1 : -1)
      side[id] = sd
      cols[sd * dpt].push(id)
    })
  }
  const keys = Object.keys(cols).map(Number).sort((a, b) => a - b)
  const heights = {}
  tables.forEach((t) => {
    const n = visibleColumns(t, opts).length
    const shown = expanded.has(t.id) ? n : Math.min(n, MAX_ROWS)
    heights[t.id] = HEAD + shown * ROW + (n > shown ? ROW : 0) + 8
  })
  const pos = {}
  let x = MARGIN, H = 0
  keys.forEach((k) => {
    let y = MARGIN
    for (const id of cols[k]) {
      pos[id] = { x, y, w: BOX_W, h: heights[id] }
      y += heights[id] + ROW_GAP
    }
    H = Math.max(H, y)
    if (cols[k].length) x += BOX_W + COL_GAP
  })
  return { pos, width: Math.max(x - COL_GAP + MARGIN, 600), height: Math.max(H, 300), byId }
}

function rowY(p, t, colName, opts, expanded) {
  const cols = visibleColumns(t, opts)
  const shown = expanded.has(t.id) ? cols.length : Math.min(cols.length, MAX_ROWS)
  const i = cols.slice(0, shown).findIndex((c) => c.name === colName)
  return i < 0 ? p.y + HEAD / 2 : p.y + HEAD + i * ROW + ROW / 2 + 4
}

export default function LogicalModel() {
  const { data, error, loading } = useApi('/api/logical-model')
  const [scope, setScope] = useState('')
  const [names, setNames] = useState('logical')
  const [opts, setOpts] = useState({ showAttributes: true, showMeasures: true, showKeys: false })
  const [sel, setSel] = useState(null)
  const [expanded, setExpanded] = useState(new Set())
  const [zoom, setZoom] = useState(1)
  const svgRef = useRef()
  const boxRef = useRef()

  const scopes = useMemo(() => {
    if (!data) return []
    return [
      ...data.subject_areas.map((a) => ({ key: `sv:${a.id}`, label: `${a.name}${a.stub ? ' (stub)' : ''}`, group: 'Subject areas (semantic views)', tables: a.tables, description: a.description })),
      ...data.products.map((p) => ({ key: `dp:${p.key}`, label: p.name, group: 'Data products', tables: p.tables })),
      { key: 'all', label: `Entire model (${data.tables.length} tables)`, group: 'All', tables: data.tables.map((t) => t.id) },
    ]
  }, [data])
  const cur = scopes.find((s) => s.key === scope) || scopes[0]
  const tables = useMemo(() => (data && cur ? cur.tables.map((id) => data.tables.find((t) => t.id === id)).filter(Boolean) : []), [data, cur])
  const lay = useMemo(() => layout(tables, opts, expanded), [tables, opts, expanded])
  const fit = () => {
    const w = boxRef.current ? boxRef.current.clientWidth - 20 : 1000
    setZoom(Math.max(0.4, Math.min(1, w / lay.width)))
  }
  useEffect(fit, [cur?.key, lay.width])
  const selected = sel && data ? data.tables.find((t) => t.id === sel) : null
  const label = (t) => (names === 'logical' ? (t.entity && !/^[A-Z_]+$/.test(t.entity) ? `${t.entity}` : t.name.replace(/^(DIM|FCT)_/, '')) : t.id)
  const fkTarget = (t, c) => {
    const f = t.foreign_keys.find((x) => x.columns.includes(c.name))
    const tt = f && data.tables.find((x) => x.id === f.ref_table)
    return tt ? label(tt) : null
  }
  const colLabel = (c, t) => {
    if (names !== 'logical') return c.name
    if (c.role === 'fk' && !c.ref && t) { const tg = fkTarget(t, c); if (tg) return `${tg} (ref)` }
    return c.business_name
  }

  const edges = []
  tables.forEach((t) => t.foreign_keys.forEach((fk) => {
    if (!lay.pos[fk.ref_table]) return
    edges.push({ from: t, to: lay.byId[fk.ref_table], fk })
  }))

  const downloadSvg = () => {
    const s = new XMLSerializer().serializeToString(svgRef.current)
    const blob = new Blob([`<?xml version="1.0" encoding="UTF-8"?>\n${s}`], { type: 'image/svg+xml' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `logical_model_${(cur?.label || 'model').replace(/[^A-Za-z0-9]+/g, '_')}.svg`
    a.click()
  }
  const toggle = (k) => setOpts({ ...opts, [k]: !opts[k] })
  const expand = (id) => { const n = new Set(expanded); n.has(id) ? n.delete(id) : n.add(id); setExpanded(n) }

  return (
    <Loading error={error} loading={loading}>
      {data && cur && (
        <div>
          <h1>5. Logical data model</h1>
          <p className="lede">The target logical model the design engine proposes: conformed dimensions, facts at their grain, outriggers and the relationships the semantic views use. Facts sit in the centre with dimensions fanning out by many-to-one distance. Crow's feet mark the many side. Inferred (stub) entities have dashed borders.</p>
          <div className="card">
            <div className="row gap wrap">
              <label className="small">View&nbsp;
                <select value={cur.key} onChange={(e) => { setScope(e.target.value); setSel(null) }}>
                  {[...new Set(scopes.map((s) => s.group))].map((g) => (
                    <optgroup key={g} label={g}>{scopes.filter((s) => s.group === g).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</optgroup>))}
                </select>
              </label>
              <div className="seg">
                <button className={names === 'logical' ? 'on' : ''} onClick={() => setNames('logical')}>Business names</button>
                <button className={names === 'physical' ? 'on' : ''} onClick={() => setNames('physical')}>Physical names</button>
              </div>
              <label className="small"><input type="checkbox" checked={opts.showAttributes} onChange={() => toggle('showAttributes')} /> Attributes</label>
              <label className="small"><input type="checkbox" checked={opts.showMeasures} onChange={() => toggle('showMeasures')} /> Measures</label>
              <label className="small"><input type="checkbox" checked={opts.showKeys} onChange={() => toggle('showKeys')} /> Surrogate keys</label>
              <button className="btn" onClick={() => setZoom(Math.max(0.4, zoom - 0.1))}>−</button>
              <span className="small">{Math.round(zoom * 100)}%</span>
              <button className="btn" onClick={() => setZoom(Math.min(2, zoom + 0.1))}>+</button>
              <button className="btn" onClick={fit}>Fit</button>
              <button className="btn" onClick={downloadSvg}>Download SVG</button>
            </div>
            {cur.description && <div className="small muted" style={{ marginTop: 8 }}>{cur.description}</div>}
            <div className="row gap wrap small legend-row">
              <span className="lg-box fact" /> Fact <span className="lg-box dim" /> Dimension <span className="lg-box stub" /> Stub (inferred)
              <span className="mono">PK</span> primary key <span className="mono">FK</span> foreign key <span className="mono">Σ</span> measure <span className="mono">ƒ</span> derived
              <span className="pii">●</span> masked / restricted
            </div>
          </div>
          <div className="ldm">
            <div className="card ldm-canvas" ref={boxRef}>
              <svg ref={svgRef} xmlns="http://www.w3.org/2000/svg" width={lay.width * zoom} height={lay.height * zoom}
                   viewBox={`0 0 ${lay.width} ${lay.height}`} style={{ fontFamily: 'Inter, Segoe UI, sans-serif' }}>
                <rect width={lay.width} height={lay.height} fill="#fbfcfe" />
                {edges.map(({ from, to, fk }, i) => {
                  const a = lay.pos[from.id], b = lay.pos[to.id]
                  const right = b.x > a.x
                  const x1 = right ? a.x + a.w : a.x, x2 = right ? b.x : b.x + b.w
                  const y1 = rowY(a, from, fk.columns[0], opts, expanded), y2 = rowY(b, to, fk.ref_columns[0], opts, expanded)
                  const same = Math.abs(a.x - b.x) < 1
                  const dx = same ? 40 : Math.max(40, Math.abs(x2 - x1) / 2)
                  const sx = same ? a.x + a.w : x1, ex = same ? b.x + b.w : x2
                  const s1 = same || right ? 1 : -1, s2 = same || !right ? 1 : -1
                  const d = `M${sx},${y1} C${sx + s1 * dx},${y1} ${ex + s2 * dx},${y2} ${ex},${y2}`
                  const hot = sel && (sel === from.id || sel === to.id)
                  const stroke = hot ? '#2f6fde' : fk.confidence < 0.6 ? '#c9a24a' : '#8a94a6'
                  // crow's foot at the many side (source), bar at the one side (target)
                  const cf = s1 * 12
                  return (
                    <g key={i}>
                      <path d={d} fill="none" stroke={stroke} strokeWidth={hot ? 2.2 : 1.3} strokeDasharray={fk.confidence < 0.6 ? '5 4' : ''}>
                        <title>{`${from.name}(${fk.columns.join(', ')}) → ${to.name}(${fk.ref_columns.join(', ')})  ${fk.relationship} · confidence ${fk.confidence}`}</title>
                      </path>
                      <path d={`M${sx + cf},${y1} L${sx},${y1 - 6} M${sx + cf},${y1} L${sx},${y1 + 6} M${sx + cf},${y1} L${sx},${y1}`} stroke={stroke} strokeWidth="1.3" fill="none" />
                      <path d={`M${ex + s2 * 8},${y2 - 6} L${ex + s2 * 8},${y2 + 6}`} stroke={stroke} strokeWidth="1.5" />
                    </g>)
                })}
                {tables.map((t) => {
                  const p = lay.pos[t.id]
                  if (!p) return null
                  const cols = visibleColumns(t, opts)
                  const shown = expanded.has(t.id) ? cols : cols.slice(0, MAX_ROWS)
                  const head = t.kind === 'fact' ? '#1f3a5f' : '#2e7d5b'
                  const isSel = sel === t.id
                  return (
                    <g key={t.id} transform={`translate(${p.x},${p.y})`} onClick={() => setSel(t.id)} style={{ cursor: 'pointer' }}>
                      <rect width={p.w} height={p.h} rx="8" fill="#fff" stroke={isSel ? '#2f6fde' : t.stub ? '#d4543f' : '#c9d1dc'}
                            strokeWidth={isSel ? 2.5 : 1.3} strokeDasharray={t.stub ? '6 4' : ''} />
                      <path d={`M0,8 a8,8 0 0 1 8,-8 h${p.w - 16} a8,8 0 0 1 8,8 v${HEAD - 8} h${-p.w} z`} fill={t.stub ? '#9a5a4f' : head} />
                      <text x="10" y="17" fill="#fff" fontSize="13" fontWeight="700">{label(t)}</text>
                      <text x="10" y="32" fill="#d8e2f0" fontSize="10">{names === 'logical' ? t.id : `${t.kind} · ${t.entity}`} · {t.confidence.toFixed(1)}</text>
                      {shown.map((c, i) => {
                        const y = HEAD + i * ROW + 4
                        return (
                          <g key={c.name} transform={`translate(0,${y})`}>
                            {i % 2 === 1 && <rect x="1" width={p.w - 2} height={ROW} fill="#f7f9fc" />}
                            <text x="10" y="13" fontSize="9.5" fontWeight="700" fill={c.role === 'pk' ? '#b7791f' : c.role === 'fk' ? '#2f6fde' : '#6b7686'}>{ROLE_ICON[c.role]}</text>
                            <text x="34" y="13" fontSize="11.5" fill={c.todo ? '#a63a28' : '#1c2430'} fontStyle={c.todo ? 'italic' : 'normal'}
                                  fontWeight={c.role === 'pk' ? 700 : 400}>{colLabel(c, t).length > 24 ? colLabel(c, t).slice(0, 23) + '…' : colLabel(c, t)}{c.sensitive ? ' ●' : ''}</text>
                            <text x={p.w - 8} y="13" fontSize="10" fill="#8a94a6" textAnchor="end">{c.role === 'measure' && c.aggregation ? c.aggregation.toUpperCase() : c.data_type.replace(/\(.*\)/, '').toLowerCase()}</text>
                            <title>{`${c.name}${c.ref ? ` ← ${c.ref}` : ''}\n${c.comment}${c.todo ? '\nTODO: unconfirmed source' : ''}`}</title>
                          </g>)
                      })}
                      {cols.length > shown.length && (
                        <text x="34" y={HEAD + shown.length * ROW + 16} fontSize="11" fill="#2f6fde" onClick={(e) => { e.stopPropagation(); expand(t.id) }}>+ {cols.length - shown.length} more…</text>)}
                      {expanded.has(t.id) && cols.length > MAX_ROWS && (
                        <text x={p.w - 10} y={HEAD + shown.length * ROW + 16} fontSize="11" fill="#2f6fde" textAnchor="end" onClick={(e) => { e.stopPropagation(); expand(t.id) }}>collapse</text>)}
                    </g>)
                })}
              </svg>
            </div>
            <div className="card side ldm-side">
              {!selected && (
                <div className="small">
                  <h3>{cur.label}</h3>
                  <p className="muted">{tables.length} entities · {edges.length} relationships · {tables.filter((t) => t.stub).length} stubs</p>
                  <table className="tbl compact">
                    <thead><tr><th>Entity</th><th>Type</th><th>Conf.</th></tr></thead>
                    <tbody>{tables.map((t) => (
                      <tr key={t.id} onClick={() => setSel(t.id)} style={{ cursor: 'pointer' }}><td className="mono tiny">{t.id}</td><td className="small">{t.kind}</td><td><Conf value={t.confidence} /></td></tr>))}</tbody>
                  </table>
                </div>)}
              {selected && (
                <div>
                  <div className="row gap"><h3 className="mono">{selected.id}</h3><button className="btn tiny ghost" onClick={() => setSel(null)}>×</button></div>
                  <div className="row gap wrap" style={{ margin: '6px 0' }}>
                    <span className="tag">{selected.kind}</span><span className="tag">{selected.origin}</span><Conf value={selected.confidence} />
                    {selected.stub && <span className="pill bad">stub</span>}
                    {selected.row_access_policy && <span className="tag blue">{selected.row_access_policy}</span>}
                  </div>
                  <div className="small">{selected.comment}</div>
                  <div className="small muted">Source: <span className="mono">{selected.source}</span> · Grain: {selected.grain.join(', ') || selected.primary_key.join(', ')}</div>
                  <div className="row gap" style={{ marginTop: 6 }}><a className="btn tiny" href={`#/review/${selected.id}`}>Open in design review</a></div>
                  <h4>Relationships</h4>
                  {selected.foreign_keys.map((f, i) => <div key={i} className="small"><span className="mono">{f.columns.join(', ')} → {f.ref_table}</span> <Conf value={f.confidence} /></div>)}
                  {data.tables.filter((t) => t.foreign_keys.some((f) => f.ref_table === selected.id)).map((t) => (
                    <div key={t.id} className="small"><span className="mono">{t.id} → this</span></div>))}
                  <h4>Columns ({selected.columns.length})</h4>
                  <table className="tbl compact">
                    <thead><tr><th>Column</th><th>Business name</th><th>Type</th><th>Cognos item</th></tr></thead>
                    <tbody>{selected.columns.map((c) => (
                      <tr key={c.name} title={c.comment}><td className="mono tiny">{ROLE_ICON[c.role] && <b>{ROLE_ICON[c.role]} </b>}{c.name}{c.todo && <span className="pill bad tiny">TODO</span>}</td>
                        <td className="small">{c.business_name}{c.sensitive && <span className="pill bad tiny">masked</span>}</td>
                        <td className="tiny">{c.data_type}{c.aggregation && c.role === 'measure' ? ` · ${c.aggregation}` : ''}</td>
                        <td className="mono tiny">{c.ref}</td></tr>))}</tbody>
                  </table>
                </div>)}
            </div>
          </div>
        </div>
      )}
    </Loading>
  )
}
