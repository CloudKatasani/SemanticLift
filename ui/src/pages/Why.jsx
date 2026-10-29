import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { fmt } from '../components'

const PROBLEMS = [
  { icon: '▦', title: 'Report sprawl across many tools', text: 'Years of Cognos, BusinessObjects, Power BI, Tableau and MicroStrategy content: thousands of reports, many of them archive copies, personal variants or never opened. Nobody can say which ones the business still needs.' },
  { icon: '⚙', title: 'Business logic trapped in the BI layer', text: 'KPI formulas, aggregation rules, prompts and joins live in Framework Manager models, universes, DAX datasets and workbook calculations. They are tool-specific, undocumented and invisible to the data platform.' },
  { icon: '≠', title: 'The same KPI, different numbers', text: 'Revenue, volume or peak demand are calculated differently by package and by report. Every migration wave restarts the argument about which number is right.' },
  { icon: '⇄', title: 'Unknown lineage', text: 'Which tables, columns and filters feed which report is buried in report specs. Without it, teams cannot scope what to land, prove the new numbers match, or switch the old tool off.' },
  { icon: '🔒', title: 'Security hidden in the tool', text: 'Row-level filters, column masking and group grants are defined inside the BI tool. They are easy to lose in a lift-and-shift and hard to recreate on the platform.' },
  { icon: '⏱', title: 'Slow, manual, risky migrations', text: 'Analysts inventory reports in spreadsheets for months, rebuild logic by hand per report and find out at go-live that totals changed. Licences for the old tool keep running in parallel.' },
]

const STEPS = [
  { key: 'estate', title: 'Review the BI estate', page: 'ingest',
    does: 'Reads the tool exports (models, report specs, usage, security, source mapping) into one metadata graph with provenance.',
    guide: 'Export everything once, including usage history and security. Agree the usage window (for example 180 days) with the business up front.',
    outcome: 'A complete inventory: reports, data items, filters, KPIs, security rules and usage, plus a findings register of gaps and defects.' },
  { key: 'rationalize', title: 'Rationalize the reports', page: 'rationalization',
    does: 'Groups duplicates, judges usage across all copies and recommends Keep, Review, Consolidate or Retire with the rule and evidence.',
    guide: 'Let report owners challenge recommendations rather than nominate reports. Decide Review items in short weekly sessions; every decision is recorded.',
    outcome: 'An agreed, evidence-backed list of reports to carry forward. Often a large share of the estate is retired or merged before any build starts.' },
  { key: 'kpis', title: 'Resolve KPI conflicts', page: 'common-kpis',
    does: 'Traces each KPI to its database column and finds the KPIs that reports compute differently (aggregation, filter or business definition).',
    guide: 'Name one business owner per KPI domain. Approve one definition per KPI before modelling, not after go-live.',
    outcome: 'One approved definition per KPI, with the reports whose numbers will change identified in advance.' },
  { key: 'scope', title: 'Scope the platform objects', page: 'sources',
    does: 'Works back from the surviving reports to the databases, schemas, tables and columns they really read.',
    guide: 'Land only what surviving reports need. Treat tables used only by Review reports as optional until those reports are decided.',
    outcome: 'A minimal, traceable landing scope for the data engineering team.' },
  { key: 'model', title: 'Design the logical data model', page: 'ldm',
    does: 'Builds conformed facts and dimensions, classifies measure additivity and detects fan and chasm traps.',
    guide: 'Conform shared dimensions (date, customer, location) once for every domain; resolve join-path warnings before building.',
    outcome: 'A conformed logical model that every data product shares, with double-counting risks removed.' },
  { key: 'products', title: 'Generate data products & semantic views', page: 'products',
    does: 'Moves calculations, aggregation rules, prompts and security into semantic views, aggregated views, policies and data-product contracts.',
    guide: 'Organise by business domain, not by old package. Keep logic in the semantic layer so BI tools, notebooks and AI agents share it.',
    outcome: 'Deployable DDL, semantic views, data-product contracts and right-sized aggregates, generated rather than hand-written.' },
  { key: 'lineage', title: 'Trace lineage for every object', page: 'objects',
    does: 'Links every platform object to its sources, the semantic objects that use it and the old reports it replaces.',
    guide: 'Use lineage to plan cut-over waves and to answer "what breaks if…?" before changing anything.',
    outcome: 'End-to-end traceability, from report column to platform column, for sign-off and decommissioning.' },
  { key: 'deliver', title: 'Review, deploy & prove parity', page: 'review',
    does: 'Puts every object through human review, commits approved objects to Git for CI deployment, and compares old and new numbers.',
    guide: 'Approve in waves per domain, deploy only through CI, and switch a report off only when parity passes.',
    outcome: 'A governed semantic layer in production, with numbers proven to match and the old tool ready to retire.' },
]

const COMPARE = [
  ['Inventory', 'Spreadsheets compiled by hand over weeks', 'Parsed from the exports in one run, with provenance'],
  ['What to migrate', 'Report owners nominate; nearly everything survives', 'Usage and duplicate evidence; owners challenge recommendations'],
  ['KPI definitions', 'Discovered at UAT when numbers differ', 'Conflicts found up front; one definition approved per KPI'],
  ['Business logic', 'Re-implemented per report in the new BI tool', 'Generated once into semantic views shared by every tool and AI agent'],
  ['Security', 'Re-keyed manually, easy to miss', 'Row and column rules generated as platform policies'],
  ['Lineage & sign-off', 'Partial, rebuilt for audits', 'Complete, from report column to platform column'],
  ['Change control', 'Ad hoc', 'Human review, audit trail, Git and CI deployment, parity checks'],
]

export default function Why({ current }) {
  const [story, setStory] = useState(null)
  useEffect(() => { if (current) api.get('/api/story').then(setStory).catch(() => setStory(null)) }, [current])

  return (
    <div className="why">
      <div className="why-hero">
        <div className="why-kicker">Cloud BI modernisation</div>
        <h1>Move the business logic, not the clutter</h1>
        <p>Large enterprises run BI estates built up over many years across several tools. The real migration is not the reports; it is the business logic inside them. SemanticLift reads the estate, decides with evidence what is worth moving, resolves conflicting KPIs, and generates a governed semantic layer and data products on the cloud data platform, with lineage and proof that the numbers match.</p>
        <div className="row gap wrap">
          <a className="btn primary" href={current ? '#/strategy' : '#/projects'}>{current ? 'See the approach for this project →' : 'Start a client project →'}</a>
          <a className="btn" href="#step-flow" onClick={(e) => { e.preventDefault(); document.getElementById('step-flow')?.scrollIntoView({ behavior: 'smooth' }) }}>How it works</a>
        </div>
      </div>

      <h2 className="why-h">The problem clients face today</h2>
      <div className="pain-grid">
        {PROBLEMS.map((p) => (
          <div key={p.title} className="pain"><div className="pain-icon">{p.icon}</div><b>{p.title}</b><p>{p.text}</p></div>))}
      </div>
      <div className="why-cost">The result: cloud migrations that take years, copy the clutter onto the new platform, re-argue every KPI, keep two BI tools licensed in parallel, and leave AI and self-service without a trusted semantic layer.</div>

      <h2 className="why-h" id="step-flow">How SemanticLift accelerates the journey</h2>
      <p className="lede">Eight steps from estate to production. Each step narrows the scope and produces evidence; the tool does the analysis and generation, and people make the decisions. Follow the arrows: each step's outcome is the next step's input.</p>
      <div className="flow-head"><span /><span>What SemanticLift does</span><span>Guideline for the team</span><span>Outcome</span></div>
      <div className="flow">
        {STEPS.map((s, i) => (
          <React.Fragment key={s.key}>
            <div className="flow-row">
              <a className="flow-step" href={current ? `#/${s.page}` : '#/projects'} title={current ? 'Open this step for the current project' : 'Create or open a project first'}>
                <span className="flow-n">{i + 1}</span><span>{s.title}</span>
              </a>
              <div className="flow-cell"><span className="flow-label">What SemanticLift does</span>{s.does}</div>
              <div className="flow-cell guide"><span className="flow-label">Guideline</span>{s.guide}</div>
              <div className="flow-cell outcome"><span className="flow-label">Outcome</span>{s.outcome}</div>
            </div>
            {i < STEPS.length - 1 && <div className="flow-arrow" aria-hidden="true">▼</div>}
          </React.Fragment>))}
        <div className="flow-arrow" aria-hidden="true">▼</div>
        <div className="flow-final"><b>Result:</b> a smaller, trusted estate on the cloud platform. One definition per KPI, business logic in reusable semantic views and data products, complete lineage, and a dated plan to switch the legacy BI tools off.</div>
      </div>

      {story && (
        <>
          <h2 className="why-h">Evidence from the current project</h2>
          <div className="funnel">
            {[[story.estate.reports, 'reports in the estate'], [story.rationalize.live, 'carried forward'], [`${story.rationalize.reduction_pct}%`, 'fewer reports'],
              [story.kpis.groups, 'KPI conflicts surfaced'], [story.sources.tables, 'source tables in scope'], [story.products.semantic_views, 'semantic views'], [story.products.products, 'data products']].map(([v, l]) => (
              <div key={l} className="funnel-step"><b>{typeof v === 'number' ? fmt(v) : v}</b><span>{l}</span></div>))}
          </div>
        </>)}

      <h2 className="why-h">Manual migration vs SemanticLift</h2>
      <table className="tbl compare">
        <thead><tr><th /><th>Typical manual migration</th><th>With SemanticLift</th></tr></thead>
        <tbody>{COMPARE.map(([k, a, b]) => <tr key={k}><td><b>{k}</b></td><td className="muted">{a}</td><td>{b}</td></tr>)}</tbody>
      </table>

      <h2 className="why-h">Where it fits</h2>
      <div className="fit">
        <div className="fit-col">
          <h4>BI sources</h4>
          <div><span className="pill good">available</span> IBM Cognos: Framework Manager models, report specifications, usage audit, security, parameters</div>
          <div><span className="pill">roadmap</span> Power BI, Tableau, SAP BusinessObjects, MicroStrategy, read into the same platform-neutral model</div>
        </div>
        <div className="fit-arrow">➜</div>
        <div className="fit-col center"><h4>SemanticLift</h4><div>Platform-neutral metadata graph, design rules, steward decisions, audit trail</div></div>
        <div className="fit-arrow">➜</div>
        <div className="fit-col">
          <h4>Cloud data platform</h4>
          <div><span className="pill good">available</span> Snowflake: DDL, semantic views, row and column policies, data-product listings, CI deployment</div>
          <div><span className="pill good">available</span> Databricks metric views and a dbt project, generated from the same model</div>
        </div>
      </div>
      <p className="small muted" style={{ marginTop: 18 }}>Nothing is deployed without a person's approval, every decision is attributed and audited, and the same inputs always generate the same output.</p>
    </div>
  )
}
