import React, { useMemo, useState } from 'react'
import { Conf, Disp, Kpi, LaneDiagram, Loading, SearchBox, Section, Status, downloadCsv, useApi } from '../components'

const LAYERS = [['', 'All'], ['core', 'Core'], ['ref', 'Reference'], ['sec', 'Security'], ['agg', 'Aggregate'], ['sem', 'Semantic view'], ['dp', 'Data product']]
const FILL = { source: '#f4efe6', core: '#e5eeff', ref: '#eef1f6', sec: '#fbeef0', agg: '#fdf2dc', sem: '#e3f4ec', dp: '#efe7fb' }
const DFILL = { Keep: '#e3f4ec', Review: '#fdf2dc', Consolidate: '#e5eeff', Retire: '#fbe7e3' }
const MAX_REPORTS = 40
const ORDER = ['core', 'agg', 'sem', 'dp', 'ref', 'sec']

export default function ObjectLineage({ arg }) {
  const { data, error, loading } = useApi('/api/objects-lineage')
  const [layer, setLayer] = useState('')
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(arg || null)
  const [hot, setHot] = useState(null)
  const [showAll, setShowAll] = useState(false)

  const byId = useMemo(() => Object.fromEntries((data?.objects || []).map((o) => [o.id, o])), [data])
  const list = useMemo(() => (data ? data.objects.filter((o) => (!layer || o.layer === layer)
    && (!q || `${o.id} ${o.domain} ${o.reports.join(' ')}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => ORDER.indexOf(a.layer) - ORDER.indexOf(b.layer) || b.live_reports - a.live_reports || a.id.localeCompare(b.id)) : []), [data, layer, q])
  const cur = byId[sel] || list[0]

  const diagram = useMemo(() => {
    if (!cur) return null
    const nodes = [], edges = [], seen = new Set()
    const add = (key, lane, label, fill, title, dashedBox) => { if (!seen.has(key)) { seen.add(key); nodes.push({ key, lane, label, fill, title, dashedBox }) } }
    const upObjs = cur.upstream_all.map((x) => byId[x]).filter(Boolean)
    const srcOf = (o) => o.sources.map((s) => s.table)
    ;[cur, ...upObjs].forEach((o) => srcOf(o).forEach((s) => add(`src:${s}`, 'source', s, FILL.source)))
    upObjs.forEach((o) => add(o.id, 'up', o.id, FILL[o.layer], `${o.layer_title}: ${o.id}`, o.status === 'stub'))
    add(cur.id, 'obj', cur.id, FILL[cur.layer], `${cur.layer_title}: ${cur.id}`, cur.status === 'stub')
    const feeds = cur.feeds.map((x) => byId[x]).filter(Boolean)
    feeds.forEach((o) => add(o.id, 'down', o.id, FILL[o.layer], `${o.layer_title}: ${o.id}`, o.status === 'stub'))
    ;[cur, ...upObjs].forEach((o) => {
      srcOf(o).forEach((s) => edges.push({ a: `src:${s}`, b: o.id }))
      o.upstream.forEach((u) => { if (seen.has(u)) edges.push({ a: u, b: o.id }) })
    })
    feeds.forEach((o) => o.upstream.forEach((u) => { if (seen.has(u) && (u === cur.id || cur.feeds.includes(u))) edges.push({ a: u, b: o.id }) }))
    const live = cur.reports.filter((r) => ['Keep', 'Review'].includes(data.reports[r]?.disposition))
    live.slice(0, MAX_REPORTS).forEach((r) => {
      const info = data.reports[r]
      add(`rep:${r}`, 'rep', r, DFILL[info.disposition], `${r} · ${info.disposition}`)
      const via = feeds.filter((o) => ['sem', 'agg'].includes(o.layer) && o.reports.includes(r))
      if (via.length) via.forEach((o) => edges.push({ a: o.id, b: `rep:${r}` }))
      else edges.push({ a: cur.id, b: `rep:${r}`, dashed: !['sem', 'agg'].includes(cur.layer) })
    })
    return { nodes, edges, live }
  }, [cur, byId, data])

  const reps = cur ? cur.reports.map((r) => ({ report: r, ...data.reports[r] })).sort((a, b) => ['Keep', 'Review', 'Consolidate', 'Retire'].indexOf(a.disposition) - ['Keep', 'Review', 'Consolidate', 'Retire'].indexOf(b.disposition) || a.report.localeCompare(b.report)) : []
  const shownReps = showAll ? reps : reps.filter((r) => r.disposition === 'Keep' || r.disposition === 'Review')

  const exportCsv = () => downloadCsv('object_lineage.csv', data.objects.map((o) => ({
    object: o.id, layer: o.layer_title, type: o.type, domain: o.domain, status: o.status, confidence: o.confidence,
    sources: o.sources.map((s) => s.table), upstream: o.upstream, feeds_semantic_layer: o.feeds,
    keep_reports: o.reports.filter((r) => data.reports[r].disposition === 'Keep'),
    review_reports: o.reports.filter((r) => data.reports[r].disposition === 'Review'),
    consolidated_reports: o.report_counts.Consolidate, retired_reports: o.report_counts.Retire })))

  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>7. Object lineage</h1>
          <p className="lede">Every object the platform will build, traced both ways. <b>Upstream</b>: the source tables and objects it is built from. <b>Downstream</b>: the aggregates, semantic views and data products that will use it, and the Cognos reports it serves, with each report's rationalization outcome. Consolidated reports are served through the report they merge into; retired reports are not migrated.</p>
          <div className="kpis">
            <Kpi label="Platform objects" value={data.summary.objects} />
            <Kpi label="Serve Keep / Review reports" value={data.summary.with_live_reports} tone="good" />
            <Kpi label="Feed the semantic layer" value={data.summary.feeding_semantic} />
            <Kpi label="No direct report use" value={data.summary.without_reports.length} sub="lookup, mapping and dimension objects reached through joins" tone="warn" />
          </div>
          <div className="two">
            <Section title={`${list.length} objects`}>
              <div className="seg" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
                {LAYERS.map(([k, l]) => <button key={k} className={layer === k ? 'on' : ''} onClick={() => setLayer(k)}>{l}{k && ` ${data.summary.by_layer[k] || 0}`}</button>)}
              </div>
              <SearchBox value={q} onChange={setQ} placeholder="Object or report…" />
              <div className="scroll" style={{ maxHeight: '64vh', overflow: 'auto', marginTop: 8 }}>
                {list.map((o) => (
                  <div key={o.id} className={`obj ${cur && cur.id === o.id ? 'sel' : ''}`} onClick={() => { setSel(o.id); setHot(null); window.history.replaceState(null, '', `#/objects/${o.id}`) }}>
                    <div className="mono small"><b>{o.id}</b></div>
                    <div className="tiny muted">{o.layer_title} · {o.live_reports} live report{o.live_reports === 1 ? '' : 's'} · feeds {o.feeds.length}</div>
                  </div>))}
              </div>
              <button className="btn" style={{ marginTop: 8 }} onClick={exportCsv}>Export CSV</button>
            </Section>
            {cur && (
              <div>
                <Section title={cur.id} actions={<span className="row gap"><span className="tag">{cur.layer_title}</span><span className="tag">{cur.type}</span><Status value={cur.status} /><Conf value={cur.confidence} /></span>}>
                  {cur.comment && <p className="small muted" style={{ marginTop: 0 }}>{cur.comment}</p>}
                  <div className="lin-canvas">
                    <LaneDiagram
                      lanes={[{ key: 'source', title: 'Source tables', sub: 'landed RAW' }, { key: 'up', title: 'Built from', sub: 'upstream objects' },
                        { key: 'obj', title: 'This object', sub: cur.layer_title }, { key: 'down', title: 'Used by', sub: 'aggregates · semantic views · data products' },
                        { key: 'rep', title: 'Cognos reports served', sub: `${diagram.live.length} Keep / Review${diagram.live.length > MAX_REPORTS ? ` (first ${MAX_REPORTS})` : ''}` }]}
                      nodes={diagram.nodes} edges={diagram.edges} laneWidth={196} gap={34} selected={hot} onSelect={setHot} minWidth={0} />
                  </div>
                  <div className="row gap wrap legend-row small">
                    {[['source', 'Source'], ['core', 'Core'], ['ref', 'Reference'], ['sec', 'Security'], ['agg', 'Aggregate'], ['sem', 'Semantic view'], ['dp', 'Data product']].map(([k, l]) => <span key={k} className="legend"><span className="lg-box" style={{ background: FILL[k] }} />{l}</span>)}
                    <span className="legend">dashed box = stub (waits for a confirmed source) · dashed line = report reads this object's columns directly</span>
                  </div>
                </Section>
                <div className="detail-grid">
                  <Section title={`Cognos reports (${reps.length})`} actions={<label className="small"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> include Consolidate / Retire</label>}>
                    <div className="row gap wrap small" style={{ marginBottom: 8 }}>
                      {Object.entries(cur.report_counts).map(([k, v]) => <span key={k}><Disp value={k} /> {v}</span>)}
                    </div>
                    {shownReps.length ? (
                      <table className="tbl compact">
                        <thead><tr><th>Report</th><th>Package</th><th>Outcome</th><th>Served by</th></tr></thead>
                        <tbody>{shownReps.map((r) => (
                          <tr key={r.report}><td><a href={`#/rationalization/${r.report}`}>{r.report}</a></td><td className="small">{(r.package || '').replace(/^Energy_|_Package$/g, '')}</td>
                            <td><Disp value={r.disposition} /></td>
                            <td className="tiny mono" style={{ wordBreak: 'break-all' }}>{r.disposition === 'Consolidate' ? `→ ${r.redirect_to || ''}` : r.disposition === 'Retire' ? 'not migrated'
                              : (cur.feeds.filter((x) => ['sem', 'agg'].includes(byId[x]?.layer) && byId[x].reports.includes(r.report)).join(' · ') || cur.id)}</td></tr>))}</tbody>
                      </table>) : <div className="small muted">No Keep or Review report reads this object directly. {cur.feeds.length > 0 && 'It reaches reports through the objects it feeds.'}</div>}
                  </Section>
                  <div>
                    <Section title="Semantic-layer objects that will use it">
                      {cur.feeds.length ? <div className="chips">{cur.feeds.map((x) => <a key={x} className="chip mono" href={`#/objects/${x}`} onClick={() => setSel(x)} style={{ background: FILL[byId[x]?.layer] }}>{x}</a>)}</div>
                        : <div className="small muted">None. This is a semantic-layer endpoint or a standalone object.</div>}
                    </Section>
                    <Section title="Built from">
                      {cur.sources.length > 0 && <><h4>Source tables</h4><div className="chips">{cur.sources.map((s) => <span key={s.table} className="chip mono" title={s.role}>{s.table}<span className="tiny muted">{s.system}</span></span>)}</div></>}
                      {cur.upstream.length > 0 && <><h4>Objects</h4><div className="chips">{cur.upstream.map((x) => <a key={x} className="chip mono" href={`#/objects/${x}`} onClick={() => setSel(x)} style={{ background: FILL[byId[x]?.layer] }}>{x}</a>)}</div></>}
                      {cur.cognos.length > 0 && <><h4>Cognos items</h4>
                        <table className="tbl compact"><tbody>{cur.cognos.map((c) => <tr key={c.item}><td className="mono tiny">{c.item}</td><td className="r small">{c.reports != null ? `${c.reports} reports` : ''}</td></tr>)}</tbody></table></>}
                      {!cur.sources.length && !cur.upstream.length && !cur.cognos.length && <div className="small muted">Generated from configuration and Cognos metadata (no upstream objects).</div>}
                      {cur.rules.length > 0 && <div className="tiny muted" style={{ marginTop: 6 }}>Design rules: {cur.rules.join(', ')}</div>}
                    </Section>
                  </div>
                </div>
              </div>)}
          </div>
        </div>
      )}
    </Loading>
  )
}
