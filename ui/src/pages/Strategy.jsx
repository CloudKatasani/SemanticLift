import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { RerunBanner, fmt } from '../components'

const KIND = { aggregation: 'aggregation rule', filter: 'filter rule', concept: 'business definition' }

// The eight-step playbook. Static parts (why, what SemanticLift does, guideline, outcome) always show;
// `did` and `out` add this project's live figures once it has a run.
function steps(s) {
  const e = s?.estate, r = s?.rationalize, k = s?.kpis, src = s?.sources, m = s?.model, p = s?.products, l = s?.lineage, d = s?.deliver
  const logic = p ? Object.entries(p.business_logic).sort((a, b) => b[1] - a[1]) : []
  return [
    {
      key: 'review', title: 'Review the BI estate', page: 'ingest', cta: 'Upload & run', also: [['export-guide', 'Cognos export guide']],
      why: 'A migration that copies the BI tool as-is carries years of duplicates, dead reports and hidden logic onto the new platform. The first step is an honest inventory: what exists, what is used, and where the business logic lives.',
      does: 'Reads the exports (models, report specs, usage, security, source mapping) into one metadata graph with provenance for every element.',
      guide: 'Export everything once, including usage history and security. Agree the usage window (for example 180 days) with the business up front.',
      outcome: 'A complete inventory of reports, data items, filters, KPIs, security rules and usage, plus a findings register of gaps and defects.',
      did: s && [
        `Parsed ${e.files} export files into one metadata graph.`,
        `Catalogued ${fmt(e.reports)} reports across ${e.packages} packages, with ${fmt(e.report_items)} data items, ${fmt(e.filters)} filters and ${e.security_rules} security rules over ${e.source_systems} source systems.`,
        `Joined usage to every report: ${fmt(e.runs_per_day)} runs/day, ${e.duplicate_run_share}% of them on archive and community copies; ${e.dormant} reports never run.`,
        `Raised ${e.findings} findings (${Object.entries(e.findings_by_severity).map(([x, v]) => `${v} ${x}`).join(', ')}).`,
      ],
      out: s && [[fmt(e.reports), 'reports inventoried'], [e.duplicate_groups, 'duplicate groups'], [`${e.duplicate_run_share}%`, 'runs on copies']],
    },
    {
      key: 'rationalize', title: 'Rationalize the reports', page: 'rationalization', cta: '1. Report rationalization',
      why: 'Only reports people use, and that are not copies of another, deserve a place on the new platform. Every report gets one clear outcome with the evidence behind it, so owners can challenge it.',
      does: 'Groups duplicates, judges usage across all copies and recommends Keep, Review, Consolidate or Retire with the rule and evidence.',
      guide: 'Let report owners challenge recommendations rather than nominate reports. Decide Review items in short weekly sessions; every decision is recorded.',
      outcome: 'An agreed, evidence-backed list of reports to carry forward.',
      decide: 'Override any outcome or merge target; the design follows your decision on re-run.',
      did: s && [
        `Retire (${r.Retire}): no copy of the report has run inside the usage window.`,
        `Consolidate (${r.Consolidate}): copies point to their main report, and reports whose KPIs are a subset of a busier report merge into it.`,
        `Review (${r.Review}): needed, but uses a disputed KPI definition, has filter defects, or low or stale usage.`,
        `Keep (${r.Keep}): distinct and in demand, migrated as-is.`,
      ],
      out: s && [[r.live, 'reports carried forward'], [`${r.reduction_pct}%`, 'fewer reports'], [r.Consolidate, 'merged into survivors']],
    },
    {
      key: 'kpis', title: 'Resolve KPI conflicts', page: 'common-kpis', cta: '3. Common KPIs', also: [['kpi-lineage', '2. KPI lineage']],
      why: 'The same KPI computed three ways is why two dashboards disagree. A governed semantic layer needs one approved definition per KPI, so conflicts are surfaced and decided once.',
      does: 'Traces each KPI to its database column and finds KPIs that reports compute differently: by aggregation, filter or business definition.',
      guide: 'Name one business owner per KPI domain. Approve one definition per KPI before modelling, not after go-live.',
      outcome: 'One approved definition per KPI, with the reports whose numbers will change identified in advance.',
      decide: 'Pick the correct definition for each KPI and record why.',
      did: s && [
        `Traced ${k.kpis} KPIs from report column through the FM item to the database column.`,
        `Found ${k.groups} KPIs with competing definitions: ${Object.entries(k.by_kind).map(([x, v]) => `${v} by ${KIND[x] || x}`).join(', ')}.`,
        `${k.approved} of ${k.groups} definitions approved so far; reports using a different one move to Review.`,
      ],
      out: s && [[k.groups, 'KPIs with conflicts'], [k.approved, 'approved'], [k.groups - k.approved, 'open']],
    },
    {
      key: 'sources', title: 'Scope the platform objects', page: 'sources', cta: '4. Databases & tables',
      why: 'Only data that surviving reports read needs to be landed and modelled. Scoping from the reports down keeps the build small and traceable.',
      does: 'Works back from the surviving reports to the databases, schemas, tables and columns they really read.',
      guide: 'Land only what surviving reports need. Treat tables used only by Review reports as optional until those reports are decided.',
      outcome: 'A minimal, traceable landing scope for the data engineering team.',
      decide: 'Include, Review or Exclude each flagged table.',
      did: s && [
        `Resolved the reports carried forward to ${src.databases} databases, ${src.tables} tables / views and ${src.columns} columns.`,
        `${src.review_only} tables are read only by Review reports and are flagged for a scope decision.`,
      ],
      out: s && [[src.databases, 'databases'], [src.tables, 'tables / views'], [src.review_only, 'review-only']],
    },
    {
      key: 'ldm', title: 'Design the logical data model', page: 'ldm', cta: '5. Logical data model',
      why: 'Business logic belongs in a conformed model, not in each report. Facts, dimensions and relationships are designed once and shared by every product.',
      does: 'Builds conformed facts and dimensions, classifies measure additivity and detects fan and chasm traps.',
      guide: 'Conform shared dimensions (date, customer, location) once for every domain; resolve join-path warnings before building.',
      outcome: 'A conformed logical model every data product shares, with double-counting risks removed.',
      did: s && [
        `Derived ${m.entities} logical entities and ${m.relationships} relationships; conformed dimensions: ${m.conformed.join(', ') || 'none'}.`,
        `Diagnosed ${m.join_issues} join-path issues; laid out ${m.tables} model tables in ${m.subject_areas} subject areas.`,
      ],
      out: s && [[m.entities, 'entities'], [m.relationships, 'relationships'], [m.conformed.length, 'conformed dimensions']],
    },
    {
      key: 'products', title: 'Generate data products & semantic views', page: 'products', cta: '6. Data products & semantic layer',
      why: 'This is where logic leaves the BI tool. Calculations, aggregation rules, prompts and security are re-implemented once on the platform, so every BI tool, notebook and AI agent gets the same answer.',
      does: 'Moves calculations, aggregation rules, prompts and security into semantic views, aggregated views, policies and data-product contracts.',
      guide: 'Organise by business domain, not by old package. Keep logic in the semantic layer, not in the next BI tool.',
      outcome: 'Deployable DDL, semantic views, data-product contracts and right-sized aggregates, generated rather than hand-written.',
      did: s && [
        `Proposed ${p.products} data products and ${p.semantic_views} semantic views with ${p.metrics} governed metrics, ${p.aggregates} aggregated views and ${p.outputs} output views.`,
        `Moved business logic out of the BI tool: ${logic.map(([x, v]) => `${v} ${x.toLowerCase()}`).join(', ')}.`,
      ],
      out: s && [[p.products, 'data products'], [p.semantic_views, 'semantic views'], [p.aggregates, 'aggregated views']],
    },
    {
      key: 'lineage', title: 'Trace lineage for every object', page: 'objects', cta: '7. Object lineage',
      why: 'Every new object must answer two questions: which old reports does it serve, and which semantic-layer objects use it? That is the evidence for sign-off and for switching the old tool off.',
      does: 'Links every platform object to its sources, the semantic objects that use it and the reports it replaces.',
      guide: 'Use lineage to plan cut-over waves and to answer "what breaks if…?" before changing anything.',
      outcome: 'End-to-end traceability, from report column to platform column.',
      did: s && [
        `Linked ${l.objects} platform objects; ${l.with_live_reports} serve a Keep or Review report and ${l.feeding_semantic} feed the semantic layer.`,
      ],
      out: s && [[l.objects, 'objects traced'], [l.with_live_reports, 'serve live reports'], [l.feeding_semantic, 'feed the semantic layer']],
    },
    {
      key: 'deliver', title: 'Review, deploy & prove parity', page: 'review', cta: 'Design review', also: [['deploy', 'Deploy & validate'], ['findings', 'Findings']],
      why: 'Nothing deploys without a human decision, and nothing is switched off without proof that the numbers match.',
      does: 'Puts every object through human review, commits approved objects to Git for CI deployment, and compares old and new numbers.',
      guide: 'Approve in waves per domain, deploy only through CI, and switch a report off only when parity passes.',
      outcome: 'A governed semantic layer in production, with numbers proven to match and the old tool ready to retire.',
      did: s && [
        `${d.objects} generated objects with deterministic DDL: ${d.proposed || 0} proposed and ${d.stub || 0} stubs waiting for a confirmed source; ${d.approved || 0} approved.`,
        d.validation_failed ? `${d.validation_failed} design validation rules are failing.` : 'All design validation rules pass.',
      ],
      out: s && [[d.objects, 'objects'], [d.approved || 0, 'approved'], [d.deployed || 0, 'deployed']],
    },
  ]
}

export default function Strategy({ current, onRun }) {
  const [data, setData] = useState(null)
  const [state, setState] = useState('loading')       // loading | live | norun | noproject
  const load = () => {
    if (!current) { setState('noproject'); return }
    api.get('/api/story').then((d) => { setData(d); setState('live') }).catch(() => { setData(null); setState('norun') })
  }
  useEffect(load, [current])
  const st = steps(data)
  const go = (key) => document.getElementById(`step-${key}`)?.scrollIntoView({ behavior: 'smooth' })

  return (
    <div className="story">
      <h1>Strategy &amp; approach</h1>
      <p className="lede">The playbook for moving business logic out of the BI tool onto the data platform. Each step narrows the estate, records the evidence and ends in an outcome the next step builds on. For every step: why it matters, what SemanticLift does, a guideline for the team, and the decision it needs.{state === 'live' && <> Figures are from run <b>{data.run_id}</b> of this project.</>}</p>
      {state === 'noproject' && <div className="banner">Open a client project to see its live figures next to each step. <a href="#/projects">Client projects →</a></div>}
      {state === 'norun' && <div className="banner">This project has no run yet. Upload the Cognos export to fill each step with this estate's figures. <a href="#/ingest">Upload &amp; run →</a></div>}
      {state === 'live' && <RerunBanner pending={data.pending_rerun} onDone={() => { load(); onRun && onRun() }} />}
      <div className="journey">
        {st.map((s, i) => (
          <React.Fragment key={s.key}>
            {i > 0 && <span className="journey-arrow">›</span>}
            <a className="journey-step" href={`#step-${s.key}`} onClick={(e) => { e.preventDefault(); go(s.key) }}><span className="journey-n">{i + 1}</span>{s.title}</a>
          </React.Fragment>))}
      </div>
      {state === 'live' && (
        <div className="funnel">
          {[[data.estate.reports, 'reports in the estate'], [data.rationalize.live, 'reports carried forward'], [data.kpis.groups, 'KPI conflicts to resolve'],
            [data.sources.tables, 'source tables in scope'], [data.model.entities, 'logical entities'],
            [data.products.semantic_views, 'semantic views'], [data.products.products, 'data products']].map(([v, l]) => (
            <div key={l} className="funnel-step"><b>{fmt(v)}</b><span>{l}</span></div>))}
        </div>)}
      {st.map((s, i) => (
        <React.Fragment key={s.key}>
          <section id={`step-${s.key}`} className="chapter card">
            <div className="chapter-n">{i + 1}</div>
            <div className="chapter-body">
              <h2>{s.title}</h2>
              <p className="chapter-why">{s.why}</p>
              <div className="play-grid">
                <div className="play-cell"><span>What SemanticLift does</span>{s.does}</div>
                <div className="play-cell guide"><span>Guideline for the team</span>{s.guide}</div>
                <div className="play-cell outcome"><span>Outcome</span>{s.outcome}</div>
              </div>
              {s.decide && <div className="chapter-decide"><b>Your decision:</b> {s.decide}</div>}
              {s.did && (
                <div className="chapter-grid" style={{ marginTop: 12 }}>
                  <div>
                    <h4>In this project</h4>
                    <ul className="reasons">{s.did.map((t, j) => <li key={j}>{t}</li>)}</ul>
                  </div>
                  <div className="chapter-out">{s.out.map(([v, l]) => <div key={l}><b>{typeof v === 'number' ? fmt(v) : v}</b><span>{l}</span></div>)}</div>
                </div>)}
              <div className="row gap wrap" style={{ marginTop: 10 }}>
                <a className="btn primary" href={`#/${s.page}`}>{s.cta} →</a>
                {(s.also || []).map(([pg, lbl]) => <a key={pg} className="btn" href={`#/${pg}`}>{lbl}</a>)}
              </div>
            </div>
          </section>
          {i < st.length - 1 && <div className="play-arrow" aria-hidden="true">▼</div>}
        </React.Fragment>))}
      <div className="flow-final"><b>Result:</b> a smaller, trusted estate on the cloud platform. One definition per KPI, business logic in reusable semantic views and data products, complete lineage, and a dated plan to switch the legacy BI tool off.</div>
    </div>
  )
}
