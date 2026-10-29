import React, { useMemo, useState } from 'react'
import { Bar, Kpi, Loading, Section, fmt, useApi } from '../components'

// "Date.MonthName" -> "Month name"; "Customer.CustomerSegment" -> "Customer segment"
const words = (s) => s.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/_/g, ' ')
const attr = (ref) => {
  const [ent, item] = ref.split('.')
  const w = words(item || ent)
  const shortW = w.toLowerCase().startsWith(words(ent).toLowerCase() + ' ') ? w.slice(words(ent).length + 1) : w
  return shortW.charAt(0).toUpperCase() + shortW.slice(1).toLowerCase()
}
const pct = (x) => `${fmt(100 * x, 0)}%`
const ratio = (a, b) => (a && b ? Math.max(1, Math.round(b / a)) : null)

const GLOSSARY = [
  ['Aggregated view (aggregate)', 'A pre-summarised copy of a fact table at a coarser level, for example billing totals per month and region instead of one row per bill. Reports and AI agents read it instead of the detail rows.'],
  ['Fact', 'The business process whose numbers are summarised: billing, meter readings, outages, generation and so on.'],
  ['Report group', 'A surviving report together with its archive and community copies. The group is counted once, with the usage of all its copies.'],
  ['Grain', 'The dimensions a report slices by, such as Month, Region or Customer segment. An aggregate at a given grain can answer every report whose grain it contains (Month also answers Quarter and Year).'],
  ['Usage load', 'How heavily a report group is used: runs per day × average run time in minutes, across all copies. The planner tries to serve the heaviest load first.'],
  ['Coverage', 'The share of a fact\'s usage load that the chosen aggregates can answer. The rest is answered by the semantic view directly from the CORE tables, which is correct but scans more rows.'],
  ['Dynamic table / view', 'Dynamic table: Snowflake keeps the summary up to date automatically within the refresh lag. View: no stored copy, used when the fact table is small enough that pre-summarising does not pay off.'],
  ['Refresh lag (TARGET_LAG)', 'How stale the summary may get before Snowflake refreshes it, taken from the estate\'s refresh cadence (for example 24 hours for daily loads).'],
  ['Credits/day', 'An estimate of the Snowflake compute used to keep the aggregate refreshed, on the configured refresh warehouse. Compare it with the compute saved by reports no longer scanning the detail.'],
  ['Additive vs components', 'Amounts and counts are pre-summed. Averages, ratios and percentages cannot be summed again correctly, so the aggregate stores their sum and count, and the semantic view computes the average from those.'],
  ['Excluded dimension', 'A dimension that cannot be safely joined to the fact at summary level (a fan trap or no many-to-one path). It is left out so totals are never double-counted.'],
  ['Stub', 'The aggregate depends on a table whose source is not confirmed yet. It is designed but cannot be deployed until the source mapping is confirmed.'],
]

function HowItWorks({ s }) {
  return (
    <div className="how">
      {[
        ['Measure demand', 'For every report group that survives rationalization, record the dimensions it slices by (its grain) and its usage load (runs/day × average minutes, across all copies). Retired reports do not count.'],
        ['Find shared summaries', `Group reports whose grains fit inside one summary: one aggregate by Month × Region also answers reports by Quarter × Region or Year. Only candidates at least ${s.min_reduction_ratio}× smaller than the fact table are considered.`],
        ['Pick the fewest that matter', `Pick summaries one at a time, the one that serves the most remaining usage for its size first, until ${pct(s.coverage_target)} of the fact's usage is covered. Stop at ${s.max_per_fact} per fact, and skip any that would serve less than ${pct(s.min_aggregate_coverage)}.`],
        ['Keep numbers right', 'Only additive measures are pre-summed. Averages and ratios are stored as sum and count so they re-aggregate correctly. Dimensions behind a fan trap are excluded. Small facts and low-volume domains get plain views, with no stored copy.'],
      ].map(([t, d], i) => (
        <div key={t} className="how-step"><div className="how-n">{i + 1}</div><div><b>{t}</b><div className="small">{d}</div></div></div>))}
    </div>
  )
}

export default function Aggregates() {
  const { data, error, loading } = useApi('/api/aggregates')
  const [fact, setFact] = useState(null)
  const [showGloss, setShowGloss] = useState(false)
  const facts = data ? Object.keys(data.facts).sort((a, b) => data.facts[b].total_weight - data.facts[a].total_weight) : []
  const cur = fact || facts[0]
  const f = data && cur ? data.facts[cur] : null
  const plans = data ? data.plans.filter((p) => p.fact === cur) : []
  const group = (id) => data.groups[id] || { canonical: id, members: 1 }

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
    withAgg: Object.values(data.facts).filter((x) => x.aggregates.length).length,
  } : null
  const example = data && [...data.plans].filter((p) => !p.stub).sort((a, b) => b.coverage_pct - a.coverage_pct)[0]
  const exFact = example && data.facts[example.fact]

  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>Aggregated views (aggregate planner)</h1>
          <p className="lede">Cognos dashboards ask the same summary questions many times a day ("revenue by month and region"). On the data platform, each of those questions would scan the full fact table every time. This page shows the small set of <b>pre-summarised tables</b> SemanticLift proposes so the most-used reports answer from a few hundred rows instead of millions. It is faster for users and cheaper to run, and the semantic views pick the summary automatically, so report authors and AI agents do not need to know it exists.</p>

          {example && (
            <div className="example">
              <b>Example from this estate.</b> Reports such as <i>{group(example.clusters[0]).canonical}</i> ask for {words(example.fact).toLowerCase()} by {[...example.grain.filter((g) => !g.startsWith('Date.')), ...example.grain.filter((g) => g.startsWith('Date.')).slice(0, 1)].map(attr).filter((v, i, a) => a.indexOf(v) === i).join(', ')}.
              Without a summary they read every {words(example.fact).toLowerCase()} row (~{fmt(exFact.fact_rows)}).
              <span className="mono"> {example.id}</span> holds ~{fmt(example.est_rows)} rows ({fmt(ratio(example.est_rows, exFact.fact_rows))}× smaller), refreshes every {example.target_lag} and serves {example.clusters.length} report groups, {example.coverage_pct}% of all {words(example.fact).toLowerCase()} usage.
            </div>)}

          <Section title="How the planner decides" actions={<button className="btn" onClick={() => setShowGloss(!showGloss)}>{showGloss ? 'Hide' : 'Show'} glossary</button>}>
            <HowItWorks s={data.settings} />
            {showGloss && (
              <dl className="gloss">{GLOSSARY.map(([t, d]) => <React.Fragment key={t}><dt>{t}</dt><dd>{d}</dd></React.Fragment>)}</dl>)}
            <div className="tiny muted" style={{ marginTop: 8 }}>Thresholds come from the project configuration (<span className="mono">aggregates.*</span>). Every aggregate still goes through Design review before deployment.</div>
          </Section>

          <div className="kpis">
            <Kpi label="Aggregated views proposed" value={totals.aggs} sub={`for ${totals.withAgg} of ${facts.length} facts`} />
            <Kpi label="Usage answered from summaries" value={`${fmt(100 * totals.covered / (totals.total || 1), 0)}%`} sub="of all report usage load" tone="good" />
            <Kpi label="Refresh cost" value={`${fmt(totals.credits, 2)} credits/day`} sub={`estimate on ${data.settings.warehouse}`} />
            <Kpi label="Facts used by reports" value={facts.length} sub={`${facts.length - totals.withAgg} answered from detail only`} />
          </div>

          <div className="agg">
            <div className="card list">
              <div className="small muted" style={{ marginBottom: 6 }}>Facts, busiest first. The bar shows the share of usage answered from summaries.</div>
              {facts.map((k) => (
                <div key={k} className={k === cur ? 'obj sel' : 'obj'} onClick={() => setFact(k)}>
                  <div className="obj-id">{words(k)}</div>
                  <Bar value={data.facts[k].coverage_pct} max={100}
                       label={data.facts[k].low_volume ? 'low volume: views only' : !data.facts[k].aggregates.length ? 'none met thresholds: read from detail' : `${fmt(data.facts[k].coverage_pct, 0)}% · ${data.facts[k].aggregates.length} aggregate${data.facts[k].aggregates.length === 1 ? '' : 's'}`}
                       tone={data.facts[k].coverage_pct >= 100 * data.settings.coverage_target ? 'good' : data.facts[k].low_volume ? '' : 'warn'} />
                </div>))}
            </div>
            <div>
              {f && (
                <>
                  <Section title={words(cur)}>
                    <p className="small" style={{ marginTop: 0 }}>
                      <b>{f.clusters}</b> surviving report groups use {words(cur).toLowerCase()} data (fact table ~{fmt(f.fact_rows)} rows).{' '}
                      {f.low_volume
                        ? 'This domain is configured as low volume, so no summaries are stored; reports read the semantic view directly.'
                        : plans.length
                          ? <>The planner proposes <b>{plans.length}</b> aggregated view{plans.length === 1 ? '' : 's'} that answer <b>{fmt(f.coverage_pct, 0)}%</b> of their usage. The remaining {fmt(100 - f.coverage_pct, 0)}% is answered from the detail tables through the semantic view.</>
                          : 'No summary met the size and usage thresholds, so these reports read the semantic view directly from the detail tables.'}
                    </p>
                    {plans.map((p) => {
                      const sums = p.measures.filter((m) => ['sum', 'count'].includes(m.kind)).map((m) => m.name)
                      const comps = [...new Set(p.measures.filter((m) => m.kind.startsWith('component')).map((m) => m.name.replace(/_(SUM|COUNT)$/, '')))]
                      const other = p.measures.filter((m) => ['avg', 'max', 'min'].includes(m.kind)).map((m) => `${m.kind.toUpperCase()} ${m.name}`)
                      return (
                        <div key={p.id} className="agg-card">
                          <div className="row gap wrap"><a className="mono" href={`#/review/${p.id}`}><b>{p.id}</b></a>
                            <span className="tag">{p.implementation === 'dynamic_table' ? 'dynamic table' : 'view'}</span>{p.stub && <span className="pill bad">stub: source not confirmed</span>}</div>
                          <div style={{ margin: '6px 0' }}>Pre-summarises <b>{words(p.fact).toLowerCase()}</b> by <b>{p.grain.map(attr).filter((v, i, a) => a.indexOf(v) === i).join(', ')}</b>.</div>
                          <div className="agg-impact">
                            <div><b>{fmt(p.est_rows)}</b><span>rows instead of {fmt(f.fact_rows)} ({fmt(ratio(p.est_rows, f.fact_rows))}× smaller)</span></div>
                            <div><b>{p.clusters.length}</b><span>report groups served · {p.coverage_pct}% of usage</span></div>
                            <div><b>{p.target_lag}</b><span>refresh lag · ~{p.credits_per_day} credits/day</span></div>
                          </div>
                          <div className="small"><b>Measures.</b> {sums.length > 0 && <>Summed: {sums.join(', ')}. </>}{comps.length > 0 && <>Stored as sum + count (averages and ratios recomputed correctly): {comps.join(', ')}. </>}{other.length > 0 && <>{other.join(', ')}. </>}</div>
                          {p.excluded.length > 0 && <div className="small warn-t">Left out to avoid double counting: {p.excluded.map(attr).join(', ')}.</div>}
                          <div className="small" style={{ marginTop: 6 }}><b>Reports it speeds up</b></div>
                          <div className="chips">{p.clusters.map((c) => <a key={c} className="chip" href={`#/rationalization/${group(c).canonical}`} title={`${c} · ${group(c).members} copies · ${fmt(group(c).runs_per_day, 1)} runs/day`}>{group(c).canonical}{group(c).members > 1 && <span className="tiny muted"> +{group(c).members - 1}</span>}</a>)}</div>
                        </div>)
                    })}
                    {f.excluded_attributes.length > 0 && <div className="small warn-t">Dimensions never used in {words(cur).toLowerCase()} summaries (fan trap or no safe join path): {f.excluded_attributes.map(attr).slice(0, 12).join(', ')}{f.excluded_attributes.length > 12 ? '…' : ''}.</div>}
                  </Section>
                  <Section title="Demand map: which report groups slice by which dimensions">
                    <div className="small muted">Each row is a report group, busiest first. Each column is a dimension, and a shaded cell means the group slices by it; darker means heavier usage. <b>✓</b> marks groups answered by one of the aggregates above; the others read the detail through the semantic view.</div>
                    <div className="heat-wrap">
                      <table className="heat">
                        <thead><tr><th>Report group</th><th className="r">Usage load</th>{heat.attrs.map((a) => <th key={a} className="rot"><span title={a}>{attr(a)}</span></th>)}</tr></thead>
                        <tbody>{f.demand.slice().sort((a, b) => b.weight - a.weight).map((d) => {
                          const covered = plans.some((p) => p.clusters.includes(d.cluster))
                          return (
                            <tr key={d.cluster}><td className={covered ? 'small cov' : 'small'} title={d.cluster}>{group(d.cluster).canonical}{covered ? ' ✓' : ''}</td><td className="r small">{fmt(d.weight, 0)}</td>
                              {heat.attrs.map((a) => <td key={a} style={{ background: d.signature.includes(a) ? `rgba(47,111,222,${0.15 + 0.85 * d.weight / heat.max})` : 'transparent' }} />)}</tr>)
                        })}</tbody>
                      </table>
                    </div>
                    <div className="tiny muted">Usage load = runs per day × average run time (minutes), summed over the group's copies.</div>
                  </Section>
                </>)}
            </div>
          </div>
        </div>
      )}
    </Loading>
  )
}
