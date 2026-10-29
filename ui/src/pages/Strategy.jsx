import React from 'react'
import { Loading, RerunBanner, fmt, useApi } from '../components'

const KIND = { aggregation: 'aggregation rule', filter: 'filter rule', concept: 'business definition' }

function steps(s) {
  const e = s.estate, r = s.rationalize, k = s.kpis, src = s.sources, m = s.model, p = s.products, l = s.lineage, d = s.deliver
  const logic = Object.entries(p.business_logic).sort((a, b) => b[1] - a[1])
  return [
    {
      key: 'review', title: 'Review the BI estate', page: 'ingest', cta: 'Upload & run',
      why: 'A migration that copies Cognos as-is carries 20 years of duplicates, dead reports and hidden logic onto the new platform. So the first step is an honest inventory: what exists, what is actually used, and where the business logic really lives.',
      did: [
        `Parsed ${e.files} export files (Framework Manager model, report specs, usage audit, security, parameters, source mapping) into one metadata graph with provenance for every element.`,
        `Catalogued ${fmt(e.reports)} reports across ${e.packages} packages, with ${fmt(e.report_items)} data items, ${fmt(e.filters)} filters and ${e.security_rules} security rules over ${e.source_systems} source systems.`,
        `Joined usage to every report: ${fmt(e.runs_per_day)} runs/day, of which ${e.duplicate_run_share}% go to Archive and Community copies; ${e.dormant} reports never run.`,
        `Raised ${e.findings} findings (${Object.entries(e.findings_by_severity).map(([k, v]) => `${v} ${k}`).join(', ')}) on gaps such as items missing from the FM model, type-mismatched prompts and non-additive measures summed in reports.`,
      ],
      out: [[fmt(e.reports), 'reports inventoried'], [e.duplicate_groups, 'duplicate groups'], [`${e.duplicate_run_share}%`, 'runs on copies']],
    },
    {
      key: 'rationalize', title: 'Rationalize the reports', page: 'rationalization', cta: '1. Report rationalization',
      why: 'Only reports people use, and that are not copies of another, deserve a place on the new platform. Every report gets one clear outcome with the evidence behind it, so owners can challenge it.',
      did: [
        `Retire (${r.Retire}): no copy of the report has run inside the usage window.`,
        `Consolidate (${r.Consolidate}): archive and community copies point to their main report, and reports whose KPIs are a subset of a busier report in the same package merge into it.`,
        `Review (${r.Review}): the report is needed, but it uses a KPI definition that is still in dispute, has filter defects, or has low or stale usage.`,
        `Keep (${r.Keep}): a distinct report that is still in demand, migrated as-is.`,
      ],
      out: [[r.live, 'reports carried forward'], [`${r.reduction_pct}%`, 'fewer reports'], [r.Consolidate, 'merged into survivors']],
      decide: 'Override any outcome or merge target; the design follows your decision on re-run.',
    },
    {
      key: 'kpis', title: 'Resolve KPI conflicts', page: 'common-kpis', cta: '3. Common KPIs', also: [['kpi-lineage', '2. KPI lineage']],
      why: 'The same KPI computed three ways in three reports is the main reason two dashboards disagree. Moving to a governed semantic layer means one approved definition per KPI, so the conflicts have to be surfaced and decided once.',
      did: [
        `Traced ${k.kpis} KPIs from report column through the FM item to the database column (KPI lineage).`,
        `Found ${k.groups} KPIs with competing definitions: ${Object.entries(k.by_kind).map(([x, v]) => `${v} by ${KIND[x] || x}`).join(', ')}.`,
        'Recommended a definition for each, based on FM metadata, measure additivity and report usage.',
        `${k.approved} of ${k.groups} definitions approved so far. The approved definition becomes the metric in the semantic view, and reports that used a different one move to Review.`,
      ],
      out: [[k.groups, 'KPIs with conflicts'], [k.approved, 'approved'], [k.groups - k.approved, 'open']],
      decide: 'Pick the correct definition for each KPI and record why.',
    },
    {
      key: 'sources', title: 'Scope the objects for the platform', page: 'sources', cta: '4. Databases & tables',
      why: 'Only data that surviving reports read needs to be landed and modelled. Scoping from the reports down keeps the data platform build small and traceable.',
      did: [
        `Resolved the reports carried forward to ${src.databases} databases, ${src.tables} tables / views and ${src.columns} columns.`,
        `${src.review_only} tables are read only by Review reports; they are flagged so you can decide whether they stay in scope.`,
        'Matched each table to its landed RAW copy and to the CORE objects built from it.',
      ],
      out: [[src.databases, 'databases'], [src.tables, 'tables / views'], [src.review_only, 'review-only']],
      decide: 'Include, Review or Exclude each flagged table.',
    },
    {
      key: 'ldm', title: 'Build the logical data model', page: 'ldm', cta: '5. Logical data model',
      why: 'Business logic belongs in a conformed model, not in each report. Facts, dimensions and their relationships are designed once and shared by every product.',
      did: [
        `Derived ${m.entities} logical entities and ${m.relationships} relationships from the FM model, completed with items inferred from report usage.`,
        `Conformed shared dimensions (${m.conformed.join(', ')}) so every product slices by the same definitions.`,
        `Classified facts and dimensions and the additivity of each measure, and diagnosed ${m.join_issues} join-path issues (fan and chasm traps) before they could double-count.`,
        `Laid out ${m.tables} model tables in ${m.subject_areas} subject areas.`,
      ],
      out: [[m.entities, 'entities'], [m.relationships, 'relationships'], [m.conformed.length, 'conformed dimensions']],
    },
    {
      key: 'products', title: 'Recommend data products & semantic views', page: 'products', cta: '6. Data products & semantic layer',
      why: 'This is where logic leaves the BI tool. Calculations, aggregation rules, prompts and security are re-implemented once on the data platform, so any BI tool, notebook or AI agent gets the same answer.',
      did: [
        `Proposed ${p.products} data products, each with an owner, a contract, quality rules and an internal listing.`,
        `Designed ${p.semantic_views} semantic views with ${p.metrics} governed metrics, ${p.aggregates} demand-driven aggregated views and ${p.outputs} output views.`,
        `Moved business logic out of Cognos: ${logic.map(([x, v]) => `${v} ${x.toLowerCase()}`).join(', ')}.`,
      ],
      out: [[p.products, 'data products'], [p.semantic_views, 'semantic views'], [p.aggregates, 'aggregated views']],
    },
    {
      key: 'lineage', title: 'Trace lineage for every object', page: 'objects', cta: '7. Object lineage',
      why: 'Every object on the new platform must answer two questions: which Cognos reports does it serve, and which semantic-layer objects will use it? That is the evidence for sign-off and for decommissioning Cognos.',
      did: [
        `Linked ${l.objects} platform objects to their source tables, Cognos items and upstream objects.`,
        `${l.with_reports} objects serve at least one Cognos report (${l.with_live_reports} serve a Keep or Review report); ${l.feeding_semantic} feed a semantic view, aggregate or data product.`,
        'Column-level lineage (report column → Cognos item → source column → platform column) is on page 6.',
      ],
      out: [[l.objects, 'objects traced'], [l.with_live_reports, 'serve live reports'], [l.feeding_semantic, 'feed the semantic layer']],
    },
    {
      key: 'deliver', title: 'Review, deploy and prove parity', page: 'review', cta: 'Design review', also: [['deploy', 'Deploy & validate'], ['findings', 'Findings']],
      why: 'Nothing deploys without a human decision, and nothing is decommissioned without proof that the numbers match.',
      did: [
        `${d.objects} generated objects with deterministic DDL: ${d.proposed || 0} proposed for approval and ${d.stub || 0} stubs that wait for a confirmed source.`,
        'Approved objects are committed to a Git branch and deployed through CI, never directly from this UI.',
        `Parity SQL compares each Cognos query with its semantic view within tolerance. ${d.validation_failed ? `${d.validation_failed} design validation rules are failing.` : 'All design validation rules pass.'}`,
      ],
      out: [[d.objects, 'objects'], [d.approved || 0, 'approved'], [d.deployed || 0, 'deployed']],
    },
  ]
}

export default function Strategy({ onRun }) {
  const { data, error, loading, reload } = useApi('/api/story')
  return (
    <Loading error={error} loading={loading}>
      {data && (() => {
        const st = steps(data)
        return (
          <div className="story">
            <h1>Strategy &amp; approach</h1>
            <p className="lede">The goal is to move business logic out of the Cognos semantic layer onto the data platform, as governed data products and semantic views, and to bring only what the business still needs. Each step below narrows the estate and records the evidence, and each one links to the page where you review it and decide. All figures come from run <b>{data.run_id}</b>.</p>
            <RerunBanner pending={data.pending_rerun} onDone={() => { reload(); onRun && onRun() }} />
            <div className="journey">
              {st.map((s, i) => (
                <React.Fragment key={s.key}>
                  {i > 0 && <span className="journey-arrow">›</span>}
                  <a className="journey-step" href={`#step-${s.key}`} onClick={(e) => { e.preventDefault(); document.getElementById(`step-${s.key}`)?.scrollIntoView({ behavior: 'smooth' }) }}>
                    <span className="journey-n">{i + 1}</span>{s.title}
                  </a>
                </React.Fragment>))}
            </div>
            <div className="funnel">
              {[[data.estate.reports, 'reports in Cognos'], [data.rationalize.live, 'reports carried forward'], [data.kpis.groups, 'KPI conflicts to resolve'],
                [data.sources.tables, 'source tables in scope'], [data.model.entities, 'logical entities'],
                [data.products.semantic_views, 'semantic views'], [data.products.products, 'data products']].map(([v, l], i) => (
                <div key={l} className="funnel-step" style={{ opacity: 1 - i * 0.04 }}><b>{fmt(v)}</b><span>{l}</span></div>))}
            </div>
            {st.map((s, i) => (
              <section key={s.key} id={`step-${s.key}`} className="chapter card">
                <div className="chapter-n">{i + 1}</div>
                <div className="chapter-body">
                  <h2>{s.title}</h2>
                  <p className="chapter-why">{s.why}</p>
                  <div className="chapter-grid">
                    <div>
                      <h4>What SemanticLift did</h4>
                      <ul className="reasons">{s.did.map((t, j) => <li key={j}>{t}</li>)}</ul>
                      {s.decide && <div className="chapter-decide"><b>Your decision:</b> {s.decide}</div>}
                    </div>
                    <div>
                      <div className="chapter-out">{s.out.map(([v, l]) => <div key={l}><b>{typeof v === 'number' ? fmt(v) : v}</b><span>{l}</span></div>)}</div>
                      <div className="row gap wrap" style={{ marginTop: 10 }}>
                        <a className="btn primary" href={`#/${s.page}`}>{s.cta} →</a>
                        {(s.also || []).map(([pg, lbl]) => <a key={pg} className="btn" href={`#/${pg}`}>{lbl}</a>)}
                      </div>
                    </div>
                  </div>
                </div>
              </section>))}
            <p className="small muted">Design principles: evidence over assumption (every recommendation names its rule and source), a person decides before anything changes, deterministic output (the same inputs always produce the same DDL), and logic lives once on the data platform rather than in each report.</p>
          </div>
        )
      })()}
    </Loading>
  )
}
