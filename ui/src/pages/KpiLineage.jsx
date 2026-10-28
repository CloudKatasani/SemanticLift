import React, { useMemo, useState } from 'react'
import { Conf, Disp, LaneDiagram, Loading, SearchBox, Section, useApi } from '../components'

const LANES = [
  { key: 'kpi', title: 'KPI', sub: 'business measure' },
  { key: 'fm', title: 'FM', sub: 'Framework Manager query item' },
  { key: 'rpt', title: 'Report', sub: 'Cognos reports using it' },
  { key: 'db', title: 'Database', sub: 'source system' },
  { key: 'sch', title: 'Schema', sub: '' },
  { key: 'tbl', title: 'Table / view', sub: 'table.column' },
]
const DISP_FILL = { Keep: '#e3f4ec', Review: '#fdf2dc', Consolidate: '#e5eeff', Retire: '#fbe7e3' }
const MAX_REPORTS = 25
const short = (p) => (p || '').replace(/^Energy_|_Package$/g, '')

export default function KpiLineage({ arg }) {
  const { data, error, loading } = useApi('/api/kpis')
  const [sel, setSel] = useState(arg || null)
  const [q, setQ] = useState('')
  const [domain, setDomain] = useState('')
  const [scopeOnly, setScopeOnly] = useState(true)
  const [node, setNode] = useState(null)

  const conflicts = useMemo(() => {
    const m = {}
    if (data) data.groups.forEach((g) => g.kpis.forEach((k) => { (m[k] = m[k] || []).push(g) }))
    return m
  }, [data])
  const kpi = data ? data.kpis.find((k) => k.id === (sel || data.kpis[0]?.id)) : null
  const domains = data ? [...new Set(data.kpis.map((k) => k.domain))].sort() : []
  const list = data ? data.kpis.filter((k) => (!domain || k.domain === domain) && (!q || `${k.id} ${k.label}`.toLowerCase().includes(q.toLowerCase()))) : []

  const graph = useMemo(() => {
    if (!kpi) return null
    const nodes = [], edges = []
    const add = (n) => { if (!nodes.find((x) => x.key === n.key)) nodes.push(n); return n.key }
    const k = add({ key: `kpi:${kpi.id}`, lane: 'kpi', label: kpi.label, fill: '#e5eeff', title: `${kpi.id} · default ${kpi.default_aggregation} (${kpi.additivity})` })
    const fm = add({ key: `fm:${kpi.id}`, lane: 'fm', label: kpi.fm_item ? kpi.fm_item.replace('Business Layer.', 'BL.') : `${kpi.id} (inferred)`,
                     fill: kpi.origin === 'FM' ? '#e3f4ec' : '#fbe7e3', dashedBox: kpi.origin !== 'FM', title: kpi.formula })
    edges.push({ a: k, b: fm })
    const seen = new Map()
    kpi.reports.forEach((r) => { if (!seen.has(r.report)) seen.set(r.report, r) })
    let reps = [...seen.values()].filter((r) => !scopeOnly || ['Keep', 'Review'].includes(r.disposition))
    reps.sort((a, b) => ['Keep', 'Review', 'Consolidate', 'Retire'].indexOf(a.disposition) - ['Keep', 'Review', 'Consolidate', 'Retire'].indexOf(b.disposition) || a.report.localeCompare(b.report))
    const more = Math.max(0, reps.length - MAX_REPORTS)
    reps = reps.slice(0, MAX_REPORTS)
    const srcFor = (r) => kpi.sources.filter((s) => s.basis !== 'inferred from report usage' || s.system_of_record === data.package_systems[r.package] || s.database === data.package_systems[r.package])
    reps.forEach((r) => {
      const rk = add({ key: `rpt:${r.report}`, lane: 'rpt', label: r.report, fill: DISP_FILL[r.disposition],
                       title: `${r.report} — ${r.disposition} · ${short(r.package)} · ${r.aggregation}${r.filter ? ` WHERE ${r.filter}` : ''}` })
      edges.push({ a: fm, b: rk })
      srcFor(r).forEach((s) => {
        const db = add({ key: `db:${s.database}`, lane: 'db', label: `${s.database}`, fill: '#eef4f9', title: `${s.vendor} ${s.database}` })
        edges.push({ a: rk, b: db })
      })
    })
    if (more) { const m = add({ key: 'rpt:__more', lane: 'rpt', label: `+ ${more} more reports`, fill: '#f5f6f8' }); edges.push({ a: fm, b: m }) }
    kpi.sources.forEach((s) => {
      const db = add({ key: `db:${s.database}`, lane: 'db', label: s.database, fill: '#eef4f9', title: `${s.vendor} ${s.database}` })
      const sch = add({ key: `sch:${s.database}.${s.schema}`, lane: 'sch', label: s.schema, fill: s.confirmed ? '#eef4f9' : '#fdf2dc', dashedBox: !s.confirmed })
      const tb = add({ key: `tbl:${s.database}.${s.schema}.${s.table}.${s.column}`, lane: 'tbl', label: `${s.table}.${s.column}`,
                       fill: s.confirmed ? '#e3f4ec' : '#fdf2dc', dashedBox: !s.confirmed,
                       title: `${s.object_type} · ${s.basis}${s.landed ? `\nlanded on the platform as ${s.landed}` : ''}` })
      edges.push({ a: db, b: sch }); edges.push({ a: sch, b: tb })
    })
    const dedup = []
    edges.forEach((e) => { if (!dedup.find((x) => x.a === e.a && x.b === e.b)) dedup.push(e) })
    return { nodes, edges: dedup }
  }, [kpi, scopeOnly, data])

  return (
    <Loading error={error} loading={loading}>
      {data && kpi && (
        <div>
          <h1>2. KPI lineage</h1>
          <p className="lede">Each KPI traced from its Framework Manager definition, through the Cognos reports that use it, to the database, schema and table/column it reads. Reports are coloured by rationalization outcome. Dashed boxes are inferred from report usage and need a source confirmation. Click any box to highlight its path.</p>
          <div className="two">
            <div className="card list">
              <SearchBox value={q} onChange={setQ} placeholder={`Search ${data.kpis.length} KPIs…`} />
              <select value={domain} onChange={(e) => setDomain(e.target.value)} style={{ width: '100%', marginTop: 6 }}>
                <option value="">All domains</option>{domains.map((d) => <option key={d} value={d}>{short(d)}</option>)}</select>
              <div className="scroll" style={{ marginTop: 8 }}>
                {list.map((k) => (
                  <div key={k.id} className={k.id === kpi.id ? 'obj sel' : 'obj'} onClick={() => { setSel(k.id); setNode(null) }}>
                    <div className="obj-id">{k.label}</div>
                    <div className="row gap small"><span className="muted mono tiny">{k.id}</span><Conf value={k.confidence} />
                      {(conflicts[k.id] || []).length > 0 && <span className="pill warn tiny">{conflicts[k.id].length} conflict</span>}</div>
                  </div>))}
              </div>
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="card">
                <div className="card-head">
                  <div><h2 style={{ margin: 0 }}>{kpi.label}</h2><div className="mono small muted">{kpi.id}</div></div>
                  <div className="row gap wrap">
                    <span className="tag">{kpi.origin}</span><Conf value={kpi.confidence} />
                    <span className="tag">default {kpi.default_aggregation}</span><span className="tag">{kpi.additivity === 'additive' ? 'additive' : `${kpi.additivity}-additive`}</span>
                    {kpi.unit && <span className="tag">{kpi.unit}</span>}
                    <label className="small"><input type="checkbox" checked={scopeOnly} onChange={(e) => setScopeOnly(e.target.checked)} /> In-scope reports only (Keep / Review)</label>
                  </div>
                </div>
                <div className="meta-grid small">
                  <div><b>FM item</b> {kpi.fm_item || '— not in the FM model (inferred)'}</div>
                  <div><b>Formula</b> <span className="mono">{kpi.formula}</span></div>
                  <div><b>Used by</b> {new Set(kpi.reports.map((r) => r.report)).size} reports ({kpi.live_reports} live) in {kpi.packages.map(short).join(', ')}</div>
                  <div><b>Semantic layer</b> {kpi.semantic.filter((s) => !s.endsWith(kpi.name.toLowerCase())).slice(0, 3).join(', ') || kpi.semantic.slice(0, 3).join(', ') || '–'}</div>
                </div>
                <div className="lin-canvas" style={{ marginTop: 8 }}>
                  <LaneDiagram lanes={LANES} nodes={graph.nodes} edges={graph.edges} laneWidth={170} gap={32} selected={node} onSelect={setNode} />
                </div>
                <div className="legend small"><i style={{ background: '#e3f4ec' }} />Keep / FM-defined <i style={{ background: '#fdf2dc' }} />Review / to confirm <i style={{ background: '#e5eeff' }} />Consolidate <i style={{ background: '#fbe7e3' }} />Retire / inferred</div>
              </div>
              <div className="grid2">
                <Section title="Definitions in use">
                  <table className="tbl compact">
                    <thead><tr><th>Aggregation</th><th>Filter rule</th><th className="r">Reports</th><th>Source</th></tr></thead>
                    <tbody>{kpi.variants.map((v) => (
                      <tr key={v.id}><td>{v.aggregation}{v.aggregation === kpi.default_aggregation && !v.filter && <span className="pill good tiny">default</span>}</td>
                        <td className="mono tiny">{v.filter || '(all rows)'}</td><td className="r">{v.reports.length}</td><td className="small">{v.source}</td></tr>))}</tbody>
                  </table>
                  {(conflicts[kpi.id] || []).map((g) => (
                    <div key={g.id} className="small" style={{ marginTop: 6 }}>⚑ <a href={`#/common-kpis/${g.id}`}>{g.title}</a> — {g.status === 'approved' ? 'approved' : 'needs a decision'}</div>))}
                </Section>
                <Section title="Physical sources">
                  <table className="tbl compact">
                    <thead><tr><th>Database</th><th>Schema</th><th>Table.column</th><th>Basis</th><th>Landed as</th></tr></thead>
                    <tbody>{kpi.sources.map((s, i) => (
                      <tr key={i}><td className="small">{s.database}<div className="muted tiny">{s.vendor}</div></td><td className="small">{s.schema}</td>
                        <td className="mono tiny">{s.table}.{s.column}</td><td className="small">{s.basis}</td><td className="mono tiny">{s.landed}</td></tr>))}</tbody>
                  </table>
                </Section>
              </div>
              <Section title="Reports using this KPI">
                <table className="tbl compact">
                  <thead><tr><th>Report</th><th>Package</th><th>Folder</th><th>Disposition</th><th>Aggregation</th><th>Filter rule</th><th>Prompts</th></tr></thead>
                  <tbody>{kpi.reports.filter((r) => !scopeOnly || ['Keep', 'Review'].includes(r.disposition)).map((r, i) => (
                    <tr key={i}><td><a href={`#/rationalization/${r.report}`}>{r.report}</a></td><td className="small">{short(r.package)}</td><td className="small">{r.folder}</td>
                      <td><Disp value={r.disposition} /></td><td className="small">{r.aggregation}</td><td className="mono tiny">{r.filter}</td>
                      <td className="mono tiny">{r.prompts.join('; ')}{r.defects.length > 0 && <span className="bad-t"> {r.defects.join('; ')}</span>}</td></tr>))}</tbody>
                </table>
              </Section>
            </div>
          </div>
        </div>
      )}
    </Loading>
  )
}
