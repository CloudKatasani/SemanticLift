import React, { useMemo, useState } from 'react'
import { Conf, Kpi, Loading, SearchBox, Section, Tabs, fmt, useApi } from '../components'

const LANES = [
  { key: 'rpt', title: 'Cognos report', sub: 'report / data item' },
  { key: 'cog', title: 'Cognos item', sub: 'FM query item or inferred' },
  { key: 'phy', title: 'Cognos physical', sub: 'FM data source column' },
  { key: 'src', title: 'Landed source', sub: 'RAW schema column' },
  { key: 'core', title: 'CORE target', sub: 'conformed model column' },
  { key: 'cons', title: 'Consumers', sub: 'semantic view · aggregate · output' },
]
const LANE_W = 200, GAP = 46, NODE_H = 24, NODE_GAP = 6, TOP = 54, MAX_REPORTS = 18
const short = (s) => s.replace(/^(CORE|SEM|AGG)\./, '')

const MODES = [
  { key: 'table', label: 'Target table' },
  { key: 'report', label: 'Report' },
  { key: 'source', label: 'Source table' },
  { key: 'sv', label: 'Semantic view' },
]

function select(data, mode, focus) {
  if (!focus) return []
  if (mode === 'table') return data.columns.filter((c) => c.table === focus)
  if (mode === 'report') return data.columns.filter((c) => c.reports.some((r) => r.report === focus))
  if (mode === 'source') return data.columns.filter((c) => c.sources.some((s) => s.startsWith(focus + '.')))
  return data.columns.filter((c) => c.semantic.some((s) => s.object === focus))
}

function buildGraph(cols, mode, focus, showReports) {
  const nodes = {}, edges = []
  const add = (lane, id, label, extra = {}) => {
    const k = `${lane}:${id}`
    if (!nodes[k]) nodes[k] = { key: k, lane, id, label, ...extra }
    return k
  }
  const link = (a, b, dashed) => { if (a && b && !edges.some((e) => e.a === a && e.b === b)) edges.push({ a, b, dashed }) }
  // reports lane: in report mode only the focus; otherwise most-connected reports first
  const repCount = {}
  cols.forEach((c) => c.reports.forEach((r) => { repCount[r.report] = (repCount[r.report] || 0) + 1 }))
  const repList = Object.keys(repCount).sort((a, b) => repCount[b] - repCount[a] || a.localeCompare(b))
  const shownReports = new Set(mode === 'report' ? [focus] : showReports ? repList.slice(0, MAX_REPORTS) : [])
  const hidden = mode === 'report' || !showReports ? 0 : Math.max(0, repList.length - MAX_REPORTS)
  cols.forEach((c) => {
    const core = add('core', c.id, short(c.id), { todo: c.todo, stub: c.table_stub, conf: c.confidence, masked: !!c.masking_policy })
    let up = null
    if (c.cognos) {
      up = add('cog', c.cognos.item, c.cognos.item, { origin: c.cognos.origin, conf: c.cognos.confidence })
      c.reports.forEach((r) => {
        if (shownReports.has(r.report)) {
          const rk = add('rpt', r.report, r.report, { folder: r.folder, disposition: r.disposition })
          link(rk, up)
        }
      })
      if (hidden && c.reports.some((r) => !shownReports.has(r.report))) link(add('rpt', '__more', `+ ${hidden} more reports`, { more: true }), up)
    }
    const phys = c.cognos ? c.cognos.physical : []
    const physKeys = phys.map((p) => add('phy', p, p))
    physKeys.forEach((pk) => link(up, pk))
    if (c.sources.length) {
      c.sources.forEach((s) => {
        const sk = add('src', s, s, { todo: c.todo })
        if (physKeys.length) physKeys.forEach((pk) => link(pk, sk)); else link(up, sk, true)
        link(sk, core, c.todo)
      })
    } else if (up) link(up, core, true)
    const cons = {}
    c.semantic.forEach((s) => { cons[s.object] = { kind: 'sem', stub: s.stub } })
    c.aggregates.forEach((s) => { cons[s.object] = { kind: 'agg', stub: s.stub } })
    c.outputs.forEach((s) => { cons[s.object] = { kind: 'out', stub: s.stub } })
    Object.entries(cons).forEach(([o, info]) => link(core, add('cons', o, o, info)))
  })
  const lanes = {}
  Object.values(nodes).forEach((n) => { (lanes[n.lane] = lanes[n.lane] || []).push(n) })
  Object.values(lanes).forEach((l) => l.sort((a, b) => (a.more ? 1 : 0) - (b.more ? 1 : 0) || a.label.localeCompare(b.label)))
  let height = 0
  LANES.forEach((ln, i) => {
    (lanes[ln.key] || []).forEach((n, j) => { n.x = 20 + i * (LANE_W + GAP); n.y = TOP + j * (NODE_H + NODE_GAP) })
    height = Math.max(height, TOP + (lanes[ln.key] || []).length * (NODE_H + NODE_GAP))
  })
  return { nodes, edges, height: height + 20, width: 20 + LANES.length * (LANE_W + GAP) - GAP + 20 }
}

function connected(graph, start) {
  if (!start) return null
  const seen = new Set([start])
  const walk = (dir) => {
    const q = [start]
    while (q.length) {
      const cur = q.shift()
      graph.edges.forEach((e) => {
        const [from, to] = dir === 'down' ? [e.a, e.b] : [e.b, e.a]
        if (from === cur && !seen.has(to)) { seen.add(to); q.push(to) }
      })
    }
  }
  walk('down'); walk('up')
  return seen
}

function fill(n) {
  if (n.more) return '#eef1f6'
  if (n.lane === 'rpt') return n.disposition === 'Retire' ? '#f6e3df' : '#e8eefb'
  if (n.lane === 'cog') return n.origin === 'FM' ? '#e3f4ec' : '#fbe7e3'
  if (n.lane === 'phy') return '#f3efe3'
  if (n.lane === 'src') return n.todo ? '#fdf2dc' : '#eef4f9'
  if (n.lane === 'core') return n.stub ? '#fbe7e3' : n.todo ? '#fdf2dc' : '#e3f4ec'
  return n.kind === 'sem' ? '#e5eeff' : n.kind === 'agg' ? '#efe8fb' : '#e8f6f3'
}

export default function Lineage({ arg }) {
  const { data, error, loading } = useApi('/api/lineage')
  const [mode, setMode] = useState('table')
  const [focus, setFocus] = useState(arg || 'CORE.FCT_BILLING')
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(null)
  const [showReports, setShowReports] = useState(true)

  const options = useMemo(() => {
    if (!data) return []
    return { table: data.tables, report: data.reports, source: data.source_tables, sv: data.semantic_views }[mode]
  }, [data, mode])
  const cols = useMemo(() => (data ? select(data, mode, focus) : []), [data, mode, focus])
  const graph = useMemo(() => buildGraph(cols, mode, focus, showReports), [cols, mode, focus, showReports])
  const hot = useMemo(() => connected(graph, sel), [graph, sel])
  const pickMode = (m) => {
    setMode(m); setSel(null)
    const first = { table: data.tables, report: data.reports, source: data.source_tables, sv: data.semantic_views }[m]
    setFocus(m === 'table' ? 'CORE.FCT_BILLING' : m === 'sv' ? 'SEM.SV_BILLING_REVENUE' : first[0])
  }

  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>5. Source-to-target lineage</h1>
          <p className="lede">Column-level lineage for every CORE column: the Cognos reports and data items that demand it, the FM query item and its Cognos physical column, the landed source column, and the semantic views, aggregates and data-product outputs that consume it. Click a node to trace it upstream and downstream.</p>
          <div className="kpis">
            <Kpi label="Active report items → CORE" value={`${fmt(data.summary.active_items_to_core)} / ${fmt(data.summary.active_report_items)}`} tone="good" />
            <Kpi label="Active report items → semantic" value={`${fmt(data.summary.active_items_to_semantic)} / ${fmt(data.summary.active_report_items)}`} tone="good" />
            <Kpi label="CORE columns" value={fmt(data.summary.core_columns)} sub={`${data.summary.fm_origin} from FM · ${data.summary.with_cognos_origin - data.summary.fm_origin} inferred`} />
            <Kpi label="Confirmed source" value={fmt(data.summary.confirmed_source)} tone="good" sub={`${data.summary.todo_source} TODO mappings`} />
            <Kpi label="Consumed downstream" value={fmt(data.summary.consumed)} />
            <Kpi label="Gaps" value={data.summary.gaps + data.summary.unresolved_items} tone={data.summary.gaps ? 'bad' : ''} sub="report items without a target" />
          </div>
          <div className="lin">
            <div className="card list">
              <Tabs value={mode} onChange={pickMode} tabs={MODES.map((m) => ({ key: m.key, label: m.label }))} />
              <SearchBox value={q} onChange={setQ} placeholder="Filter…" />
              <div className="scroll" style={{ marginTop: 8 }}>
                {options.filter((o) => !q || o.toLowerCase().includes(q.toLowerCase())).map((o) => (
                  <div key={o} className={o === focus ? 'obj sel' : 'obj'} onClick={() => { setFocus(o); setSel(null) }}>
                    <div className="obj-id mono">{o}</div>
                  </div>))}
              </div>
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="card lin-canvas">
                <div className="row gap wrap pad-s">
                  <b className="mono">{focus}</b><span className="muted small">{cols.length} target columns</span>
                  {mode !== 'report' && <label className="small"><input type="checkbox" checked={showReports} onChange={(e) => setShowReports(e.target.checked)} /> Show reports</label>}
                  {sel && <button className="btn tiny" onClick={() => setSel(null)}>Clear trace</button>}
                  <span className="legend small"><i style={{ background: '#e3f4ec' }} />FM / confirmed <i style={{ background: '#fbe7e3' }} />inferred / stub <i style={{ background: '#fdf2dc' }} />TODO source · dashed = unconfirmed link</span>
                </div>
                {!cols.length ? <div className="muted pad">No lineage for this selection.</div> : (
                  <svg viewBox={`0 0 ${graph.width} ${graph.height}`} width="100%" style={{ minWidth: 960, fontFamily: 'Inter, Segoe UI, sans-serif' }}>
                    {LANES.map((ln, i) => (
                      <g key={ln.key} transform={`translate(${20 + i * (LANE_W + GAP)},10)`}>
                        <text fontSize="12" fontWeight="700" fill="#1c2430">{ln.title}</text>
                        <text y="16" fontSize="10.5" fill="#8a94a6">{ln.sub}</text>
                      </g>))}
                    {graph.edges.map((e, i) => {
                      const a = graph.nodes[e.a], b = graph.nodes[e.b]
                      const x1 = a.x + LANE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2
                      const on = hot && hot.has(e.a) && hot.has(e.b)
                      return <path key={i} d={`M${x1},${y1} C${x1 + GAP / 2},${y1} ${x2 - GAP / 2},${y2} ${x2},${y2}`} fill="none"
                                   stroke={on ? '#2f6fde' : '#c3cad6'} strokeWidth={on ? 2 : 1} opacity={hot && !on ? 0.25 : 1}
                                   strokeDasharray={e.dashed ? '4 3' : ''} />
                    })}
                    {Object.values(graph.nodes).map((n) => {
                      const dim = hot && !hot.has(n.key)
                      return (
                        <g key={n.key} transform={`translate(${n.x},${n.y})`} onClick={() => setSel(n.key === sel ? null : n.key)} style={{ cursor: 'pointer', opacity: dim ? 0.3 : 1 }}>
                          <rect width={LANE_W} height={NODE_H} rx="6" fill={fill(n)} stroke={n.key === sel ? '#2f6fde' : '#d5dbe4'} strokeWidth={n.key === sel ? 2 : 1} />
                          <text x="8" y="16" fontSize="11" fill="#1c2430">{n.label.length > 30 ? n.label.slice(0, 29) + '…' : n.label}{n.masked ? ' ●' : ''}</text>
                          <title>{n.label}</title>
                        </g>)
                    })}
                  </svg>)}
              </div>
              <Section title="Column lineage detail" actions={<div className="row gap"><a className="btn" href="/api/files/traceability.csv" download>traceability.csv</a><a className="btn" href="/api/files/lineage.json" download>lineage.json (OpenLineage)</a></div>}>
                <table className="tbl compact">
                  <thead><tr><th>CORE column</th><th>Transform</th><th>Landed source</th><th>Cognos item</th><th>Cognos expression / physical</th><th className="r">Reports</th><th>Consumers</th></tr></thead>
                  <tbody>{cols.map((c) => (
                    <tr key={c.id} className={sel === `core:${c.id}` ? 'sel' : ''} onClick={() => setSel(`core:${c.id}`)} style={{ cursor: 'pointer' }}>
                      <td className="mono tiny">{short(c.id)}{c.todo && <span className="pill warn tiny">TODO</span>}{c.masking_policy && <span className="pill bad tiny">masked</span>}</td>
                      <td className="mono tiny">{c.transform}</td>
                      <td className="mono tiny">{c.sources.join(', ') || '–'}</td>
                      <td className="small">{c.cognos ? <>{c.cognos.item} <Conf value={c.cognos.confidence} /></> : <span className="muted">key / design rule</span>}</td>
                      <td className="mono tiny">{c.cognos ? `${c.cognos.expression || '(inferred from reports)'}${c.cognos.physical.length ? ` → ${c.cognos.physical.join(', ')}` : ''}` : ''}</td>
                      <td className="r small">{c.reports.length}</td>
                      <td className="tiny">{[...new Set([...c.semantic, ...c.aggregates, ...c.outputs].map((x) => x.object))].join(', ')}</td>
                    </tr>))}</tbody>
                </table>
              </Section>
              {(data.gaps.length > 0 || data.unresolved.length > 0) && (
                <Section title="Lineage gaps">
                  {data.gaps.map((g) => <div key={g.ref} className="small">{g.ref}: used by {g.reports} reports, no CORE column</div>)}
                  {data.unresolved.map((u, i) => <div key={i} className="small">{u.report}.{u.column}: {u.expression}</div>)}
                </Section>)}
            </div>
          </div>
        </div>
      )}
    </Loading>
  )
}
