import React, { useMemo, useState } from 'react'
import { Bar, Kpi, Loading, Section, fmt, useApi } from '../components'

export default function Aggregates() {
  const { data, error, loading } = useApi('/api/aggregates')
  const [fact, setFact] = useState(null)
  const facts = data ? Object.keys(data.facts).sort((a, b) => data.facts[b].total_weight - data.facts[a].total_weight) : []
  const cur = fact || facts[0]
  const f = data && cur ? data.facts[cur] : null
  const plans = data ? data.plans.filter((p) => p.fact === cur) : []

  const heat = useMemo(() => {
    if (!f) return null
    const attrs = Object.keys(f.heat).slice(0, 18)
    const max = Math.max(1, ...f.demand.map((d) => d.weight))
    return { attrs, max }
  }, [f])

  const totals = data ? {
    aggs: data.plans.length, credits: data.plans.reduce((a, p) => a + p.credits_per_day, 0),
    covered: Object.values(data.facts).reduce((a, x) => a + x.covered_weight, 0),
    total: Object.values(data.facts).reduce((a, x) => a + x.total_weight, 0),
  } : null

  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>8. Aggregate planner</h1>
          <p className="lede">Aggregates are designed from demand: each surviving cluster contributes a grain signature weighted by runs/day × average duration. The planner greedily picks the smallest set (max 3 per fact) covering ≥ 80% of weighted demand. Only additive measures are pre-summed; others are stored as re-aggregable components.</p>
          <div className="kpis">
            <Kpi label="Aggregates proposed" value={totals.aggs} />
            <Kpi label="Weighted demand covered" value={`${fmt(100 * totals.covered / (totals.total || 1), 1)}%`} />
            <Kpi label="Est. refresh credits/day" value={fmt(totals.credits, 3)} />
            <Kpi label="Facts with demand" value={facts.length} />
          </div>
          <div className="agg">
            <div className="card list">
              {facts.map((k) => (
                <div key={k} className={k === cur ? 'obj sel' : 'obj'} onClick={() => setFact(k)}>
                  <div className="obj-id">{k}</div>
                  <Bar value={data.facts[k].coverage_pct} max={100} label={`${data.facts[k].coverage_pct}% · ${data.facts[k].aggregates.length} agg`} tone={data.facts[k].coverage_pct >= 80 ? 'good' : data.facts[k].low_volume ? '' : 'warn'} />
                </div>))}
            </div>
            <div>
              {f && (
                <>
                  <Section title={`${cur}: grain demand heatmap`}>
                    <div className="small muted">{f.clusters} clusters · weighted demand {fmt(f.total_weight, 1)} · {f.low_volume ? 'low-volume domain: plain views only' : `coverage ${f.coverage_pct}%`}</div>
                    <div className="heat-wrap">
                      <table className="heat">
                        <thead><tr><th>Cluster</th><th className="r">Weight</th>{heat.attrs.map((a) => <th key={a} className="rot"><span>{a}</span></th>)}</tr></thead>
                        <tbody>{f.demand.slice().sort((a, b) => b.weight - a.weight).map((d) => {
                          const covered = plans.some((p) => p.clusters.includes(d.cluster))
                          return (
                            <tr key={d.cluster}><td className={covered ? 'mono small cov' : 'mono small'}>{d.cluster}{covered ? ' ✓' : ''}</td><td className="r small">{fmt(d.weight, 1)}</td>
                              {heat.attrs.map((a) => <td key={a} style={{ background: d.signature.includes(a) ? `rgba(47,111,222,${0.15 + 0.85 * d.weight / heat.max})` : 'transparent' }} />)}</tr>)
                        })}</tbody>
                      </table>
                    </div>
                    {f.excluded_attributes.length > 0 && <div className="small warn-t">Excluded from aggregate grain (fan trap or no many-to-one path): {f.excluded_attributes.join(', ')}</div>}
                  </Section>
                  <Section title="Chosen aggregates">
                    {!plans.length && <div className="muted">No aggregate proposed (low volume, or no grain under the size limit with ≥ 5% demand).</div>}
                    {plans.map((p) => (
                      <div key={p.id} className="agg-card">
                        <div className="row gap"><a className="mono" href={`#/review/${p.id}`}>{p.id}</a><span className="tag">{p.implementation.replace('_', ' ')}</span>{p.stub && <span className="pill bad">stub</span>}</div>
                        <div className="small">Grain: {p.grain.join(', ')}</div>
                        <div className="row gap small"><span>Coverage <b>{p.coverage_pct}%</b></span><span>Clusters {p.clusters.length}</span><span>Est. rows {fmt(p.est_rows)}</span>
                          <span>~{p.credits_per_day} credits/day</span><span>TARGET_LAG {p.target_lag}</span></div>
                        {p.excluded.length > 0 && <div className="small warn-t">Excluded: {p.excluded.join(', ')}</div>}
                      </div>))}
                  </Section>
                </>)}
            </div>
          </div>
        </div>
      )}
    </Loading>
  )
}
