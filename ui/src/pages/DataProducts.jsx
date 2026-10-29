import React, { useMemo, useState } from 'react'
import { api } from '../api'
import { Conf, Kpi, LaneDiagram, Loading, RerunBanner, Section, Tabs, useApi } from '../components'
import Lineage from './Lineage'
import Aggregates from './Aggregates'

const LANES = [
  { key: 'source', title: 'Source table', sub: 'landed RAW schema' },
  { key: 'core', title: 'CORE', sub: 'conformed model' },
  { key: 'agg', title: 'Aggregated views', sub: 'dynamic tables / views' },
  { key: 'sem', title: 'Semantic views', sub: 'metrics & dimensions' },
  { key: 'dp', title: 'Data product outputs', sub: 'secure DP_* views' },
  { key: 'report', title: 'Reports served', sub: 'Keep / Review' },
]
const FILL = { source: '#eef4f9', core: '#e3f4ec', agg: '#efe8fb', sem: '#e5eeff', dp: '#e8f6f3', report: '#f5f6f8' }

export default function DataProducts({ arg }) {
  const [tab, setTab] = useState(arg === 'lineage' ? 'columns' : arg === 'aggregates' ? 'aggregates' : 'products')
  return (
    <div>
      <h1>6. Data products &amp; semantic layer</h1>
      <p className="lede">What moves from Cognos to the data platform, per data product. It covers the business logic (calculations, aggregation rules, prompts and security) as semantic views, aggregated views and secure data-product outputs, with lineage from source tables to the reports they replace.</p>
      <Tabs value={tab} onChange={setTab} tabs={[{ key: 'products', label: 'Data products' }, { key: 'columns', label: 'Column-level lineage' }, { key: 'aggregates', label: 'Aggregate planner' }]} />
      {tab === 'products' && <Products />}
      {tab === 'columns' && <div className="embedded"><Lineage /></div>}
      {tab === 'aggregates' && <div className="embedded"><Aggregates /></div>}
    </div>
  )
}

function Products() {
  const { data, error, loading, reload } = useApi('/api/products-view')
  const [sel, setSel] = useState(null)
  const [node, setNode] = useState(null)
  const p = data ? data.products.find((x) => x.key === sel) || data.products[0] : null

  const graph = useMemo(() => {
    if (!p) return null
    const lanesUsed = new Set(p.lineage.nodes.map((n) => n.layer))
    const short = (s) => s.replace(/^(CORE|AGG|SEM)\./, '')
    const nodes = p.lineage.nodes.slice().sort((a, b) => a.label.localeCompare(b.label)).map((n) => ({
      key: n.id, lane: n.layer, label: n.layer === 'report' ? n.label : short(n.label),
      fill: n.stub ? '#fbe7e3' : n.layer === 'report' && n.disposition === 'Review' ? '#fdf2dc' : FILL[n.layer], dashedBox: n.stub,
      title: `${n.label}${n.stub ? ' (stub: inferred, needs source confirmation)' : ''}${n.coverage != null ? ` · covers ${n.coverage}% of demand` : ''}`,
    }))
    return { lanes: LANES.filter((l) => lanesUsed.has(l.key)), nodes, edges: p.lineage.edges.map((e) => ({ a: e.from, b: e.to })) }
  }, [p])

  return (
    <Loading error={error} loading={loading}>
      {data && p && (
        <div>
          <RerunBanner pending={data.pending_rerun} onDone={reload} />
          <div className="prod-cards">
            {data.products.map((x) => (
              <div key={x.key} className={`prod-card ${x.key === p.key ? 'sel' : ''}`} onClick={() => { setSel(x.key); setNode(null) }}>
                <div className="row gap"><b>{x.name}</b><Conf value={x.confidence} /></div>
                <div className="mono tiny muted">{x.schema}</div>
                <div className="small" style={{ marginTop: 6 }}>{x.semantic_views.length} semantic views · {x.aggregates.length} aggregates · {x.outputs.length} outputs</div>
                <div className="small muted">{x.core_tables.length} CORE tables · replaces {x.reports.Keep + x.reports.Review} report intents</div>
              </div>))}
          </div>
          <div className="card">
            <div className="card-head">
              <div><h2 style={{ margin: 0 }}>{p.name}</h2><div className="small muted">Owner {p.owner} · steward {p.steward} · {p.classification} · retention {p.retention} · freshness SLA {p.freshness_sla}</div></div>
              <div className="row gap wrap">
                <button className="btn" onClick={() => api.download(`/api/files/${p.contract}`)}>Data contract (YAML)</button>
                <a className="btn" href={`#/review/${p.listing}`}>Marketplace listing</a>
              </div>
            </div>
            <div className="kpis">
              <Kpi label="Semantic views" value={p.semantic_views.length} />
              <Kpi label="Aggregated views" value={p.aggregates.length} />
              <Kpi label="Output views" value={p.outputs.length} />
              <Kpi label="CORE tables" value={p.core_tables.length} sub={`${p.core_tables.filter((t) => t.stub).length} stubs`} />
              <Kpi label="Business rules moved" value={p.business_logic.length} />
              <Kpi label="Reports" value={p.reports.Keep + p.reports.Review} sub={`${p.reports.Keep} Keep · ${p.reports.Review} Review · ${p.reports.Consolidate} consolidated · ${p.reports.Retire} retired`} />
            </div>
            <div className="small muted">Sources: {p.source_systems.join(', ') || '–'}{p.data_modules.length > 0 && ` · Cognos data modules: ${p.data_modules.join(', ')}`}{p.default_filters.length > 0 && ` · default filters: ${p.default_filters.map((f) => `${f.dimension} = ${f.default}`).join(', ')}`}</div>
          </div>
          <Section title="Lineage: source → CORE → aggregated / semantic views → outputs → reports">
            <div className="lin-canvas"><LaneDiagram lanes={graph.lanes} nodes={graph.nodes} edges={graph.edges} laneWidth={200} selected={node} onSelect={setNode} /></div>
            <div className="legend small"><i style={{ background: '#fbe7e3' }} />stub (inferred source) <i style={{ background: '#fdf2dc' }} />report under review · click a box to trace it</div>
          </Section>
          <Section title={`Business logic moved from Cognos (${p.business_logic.length})`}>
            <table className="tbl compact">
              <thead><tr><th>Type</th><th>In Cognos</th><th>On the data platform</th><th>Rule</th></tr></thead>
              <tbody>{p.business_logic.map((b, i) => (
                <tr key={i}><td className="small nowrap"><b>{b.kind}</b></td><td className="mono tiny">{b.cognos}</td><td className="mono tiny">{b.platform}</td><td className="tiny">{b.rule}</td></tr>))}
                {!p.business_logic.length && <tr><td colSpan="4" className="muted small">No calculations or security rules for this product; its logic is the aggregation and join rules in the semantic views.</td></tr>}</tbody>
            </table>
          </Section>
          <Section title="Semantic views">
            {p.semantic_views.map((s) => (
              <details key={s.id} className="acc">
                <summary>{s.name} <span className="muted small">— {s.description}</span> {s.stub ? <span className="pill bad tiny">stub</span> : <span className="pill good tiny">deployable</span>}
                  <span className="small muted"> · {s.tables.length} tables · {s.dimensions.length} dimensions · {s.metrics.length} metrics · serves {s.reports_served.length} reports</span></summary>
                <div className="detail-grid" style={{ marginTop: 8 }}>
                  <div>
                    <h4>Metrics</h4>
                    <table className="tbl compact"><thead><tr><th>Metric</th><th>Expression</th><th>Cognos item</th></tr></thead>
                      <tbody>{s.metrics.map((m) => <tr key={`${m.table}.${m.name}`}><td className="small">{m.table}.{m.name}</td><td className="mono tiny">{m.expr}</td><td className="tiny">{m.ref}</td></tr>)}</tbody></table>
                    <h4>Dimensions</h4>
                    <div className="chips">{s.dimensions.map((d) => <span key={`${d.table}.${d.name}`} className="chip" title={`${d.synonyms.join(', ')}${d.sample_values.length ? ` · e.g. ${d.sample_values.join(', ')}` : ''}`}>{d.table}.{d.name}</span>)}</div>
                  </div>
                  <div>
                    <h4>Tables & relationships</h4>
                    <div className="small">{s.tables.map((t) => `${t.alias} = ${t.table}`).join(' · ')}</div>
                    <div className="small mono tiny" style={{ marginTop: 4 }}>{s.relationships.join(' · ')}</div>
                    {s.default_filters.length > 0 && (<><h4>Default filters (required prompts)</h4><div className="small">{s.default_filters.map((f) => `${f.dimension} = ${f.default} (?${f.parameter}?)`).join(', ')}</div></>)}
                    <h4>Verified questions ({s.verified_queries.length})</h4>
                    {s.verified_queries.slice(0, 5).map((v, i) => <div key={i} className="small" title={v.sql}>• {v.question}</div>)}
                    <h4>Reports served</h4>
                    <div className="chips">{s.reports_served.slice(0, 30).map((r) => <a key={r} className="chip" href={`#/rationalization/${r}`}>{r}</a>)}</div>
                    <a className="btn tiny" href={`#/review/${s.id}`} style={{ marginTop: 8 }}>Open DDL in design review</a>
                  </div>
                </div>
              </details>))}
            {!p.semantic_views.length && <div className="muted small">Conformed dimensions are published as outputs and consumed by every other product's semantic views.</div>}
          </Section>
          <div className="grid2">
            <Section title="Aggregated views">
              <table className="tbl compact"><thead><tr><th>Aggregate</th><th>Grain</th><th className="r">Coverage</th><th className="r">Credits/day</th></tr></thead>
                <tbody>{p.aggregates.map((a) => (
                  <tr key={a.id}><td className="mono tiny"><a href={`#/review/${a.id}`}>{a.id}</a>{a.stub && <span className="pill bad tiny">stub</span>}<div className="muted">{a.implementation.replace('_', ' ')} · lag {a.target_lag}</div></td>
                    <td className="tiny">{a.grain.join(', ')}</td><td className="r small">{a.coverage_pct}%</td><td className="r small">{a.credits_per_day}</td></tr>))}
                  {!p.aggregates.length && <tr><td colSpan="4" className="muted small">No aggregate needed (low volume or no common grain).</td></tr>}</tbody></table>
            </Section>
            <Section title="Data product outputs & CORE tables">
              <table className="tbl compact"><thead><tr><th>Output view</th><th className="r">Columns</th><th>Built on</th></tr></thead>
                <tbody>{p.outputs.map((o) => <tr key={o.id}><td className="mono tiny"><a href={`#/review/${o.id}`}>{o.id}</a>{o.stub && <span className="pill bad tiny">stub</span>}</td><td className="r small">{o.columns.length}</td><td className="mono tiny">{o.depends_on.slice(0, 3).join(', ')}</td></tr>)}</tbody></table>
              <h4>CORE tables</h4>
              <div className="chips">{p.core_tables.map((t) => <a key={t.id} className="chip" href={`#/ldm`} title={t.source}>{t.id}{t.stub ? ' (stub)' : ''}</a>)}</div>
            </Section>
          </div>
        </div>
      )}
    </Loading>
  )
}
