import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'

// Figures from the bundled energy sample run; replaced by live figures when the current project has a run.
const SAMPLE = { label: 'bundled sample estate (energy utility)', reports: 588, live: 91, reduction: 85, conflicts: 70, tables: 36, views: 11, products: 7, objects: 148 }

function useInView(ref) {
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    if (!ref.current || seen) return
    if (!('IntersectionObserver' in window)) { setSeen(true); return }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect() } }, { threshold: 0.3 })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [ref, seen])
  return seen
}

function Count({ to, suffix = '', run }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    if (!run) return
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) { setV(to); return }
    let raf, start
    const step = (t) => {
      start = start || t
      const k = Math.min(1, (t - start) / 1200)
      setV(Math.round(to * (1 - Math.pow(1 - k, 3))))
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [to, run])
  return <>{v.toLocaleString()}{suffix}</>
}

const PROBLEMS = [
  { icon: '▦', title: 'Report sprawl across many tools', text: 'Years of Cognos, BusinessObjects, Power BI, Tableau and MicroStrategy content: thousands of reports, many of them archive copies, personal variants or never opened. Nobody can say which ones the business still needs.' },
  { icon: '⚙', title: 'Business logic trapped in the BI layer', text: 'KPI formulas, aggregation rules, prompts and joins live in Framework Manager models, universes, DAX datasets and workbook calculations. They are tool-specific, undocumented and invisible to the data platform.' },
  { icon: '≠', title: 'The same KPI, different numbers', text: 'Revenue, volume or peak demand are calculated differently by package and by report. Every migration wave restarts the argument about which number is right.' },
  { icon: '⇄', title: 'Unknown lineage', text: 'Which tables, columns and filters feed which report is buried in report specs. Without it, teams cannot scope what to land, prove the new numbers match, or switch the old tool off.' },
  { icon: '🔒', title: 'Security hidden in the tool', text: 'Row-level filters, column masking and group grants are defined inside the BI tool. They are easy to lose in a lift-and-shift and hard to recreate on the platform.' },
  { icon: '⏱', title: 'Slow, manual, risky migrations', text: 'Analysts inventory reports in spreadsheets for months, rebuild logic by hand per report and find out at go-live that totals changed. Licences for the old tool keep running in parallel.' },
]

const STEPS = [
  ['Review the estate', 'A complete inventory with usage and findings'],
  ['Rationalize reports', 'Evidence-backed list of what to carry forward'],
  ['Resolve KPI conflicts', 'One approved definition per KPI'],
  ['Scope platform objects', 'Only the tables surviving reports read'],
  ['Design the model', 'Conformed facts and dimensions, no double counting'],
  ['Generate the semantic layer', 'Semantic views, aggregates, policies, data products'],
  ['Trace every object', 'Lineage from report column to platform column'],
  ['Review, deploy, prove', 'Approved, deployed through CI, parity checked'],
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

const ENTERPRISE = [
  ['Client projects', 'Every engagement isolated, side by side'],
  ['Single sign-on and roles', 'Viewer to deployer, per project'],
  ['Audit trail', 'Every decision attributed and exportable'],
  ['Four-eyes approval', 'No one approves their own edits'],
  ['Deterministic', 'Same inputs, byte-identical output'],
  ['Runs in your tenant', 'Metadata only; no business data leaves'],
]

const ROLES = [
  ['Executive sponsor', 'A dated, evidence-backed path to retire the legacy BI tool and its licence.'],
  ['BI lead', 'A defensible list of what to keep, merge and drop, decided once instead of argued forever.'],
  ['Data steward', 'One approved definition per KPI, with every report affected named in advance.'],
  ['Platform engineer', 'Generated, reviewed DDL and semantic views instead of hand-built rewrites.'],
  ['Cognos administrator', 'A clear export checklist; metadata only, no business data.'],
]

export default function Home({ current }) {
  const [live, setLive] = useState(null)
  useEffect(() => { if (current) api.get('/api/story').then(setLive).catch(() => setLive(null)) }, [current])
  const n = live ? {
    label: `current project (run ${live.run_id})`, reports: live.estate.reports, live: live.rationalize.live, reduction: live.rationalize.reduction_pct,
    conflicts: live.kpis.groups, tables: live.sources.tables, views: live.products.semantic_views, products: live.products.products, objects: live.deliver.objects,
  } : SAMPLE
  const statsRef = useRef(null)
  const statsSeen = useInView(statsRef)
  const start = current ? '#/ingest' : '#/projects'

  return (
    <div className="home">
      <section className="home-hero">
        <div className="home-glow" aria-hidden="true" />
        <div className="home-kicker">Introducing SemanticLift</div>
        <h1 className="home-title">Your BI estate has been hiding<br />a <span>semantic layer</span>.<br />We lift it out.</h1>
        <p className="home-sub">SemanticLift turns decades of Cognos reports into a governed semantic layer and data products on your cloud data platform. Less clutter carried over. One answer per KPI. Proof every number still matches.</p>
        <div className="row gap wrap">
          <a className="btn home-cta" href={start}>Start your lift →</a>
          <a className="btn home-ghost" href="#/strategy">See the approach</a>
        </div>
        <div className="home-flow" aria-hidden="true">
          <span>Thousands of reports</span><i>→</i><span>Evidence</span><i>→</i><span>Decisions</span><i>→</i><span className="hl">One semantic layer</span>
        </div>
      </section>

      <section className="home-band">
        <div className="home-quote">“The hard part of a BI migration was never the reports. It was the meaning inside them.”</div>
      </section>

      <section className="home-problem">
        <h2>The problem every large BI estate has</h2>
        <p className="home-lead">Monday, 9 a.m. Two dashboards, one question, two revenue numbers. Behind them sit years of reports across several tools, and the business logic that makes the numbers is locked inside them.</p>
        <div className="pain-grid">
          {PROBLEMS.map((p) => (
            <div key={p.title} className="pain"><div className="pain-icon">{p.icon}</div><b>{p.title}</b><p>{p.text}</p></div>))}
        </div>
        <div className="why-cost">The result: migrations that take years, copy the clutter onto the new platform, re-argue every KPI, keep two BI tools licensed in parallel, and leave AI and self-service without a trusted semantic layer.</div>
      </section>

      <section className="home-how">
        <h2>How SemanticLift lifts it</h2>
        <p className="home-lead">Eight steps from estate to production. The tool does the analysis and generation; people make the decisions, with the evidence next to each one.</p>
        <div className="home-steps">
          {STEPS.map(([t, o], i) => (
            <React.Fragment key={t}>
              <div className="home-step"><span className="flow-n">{i + 1}</span><b>{t}</b><span>{o}</span></div>
              {i < STEPS.length - 1 && <div className="home-step-arrow" aria-hidden="true">→</div>}
            </React.Fragment>))}
        </div>
        <a className="btn" href="#/strategy" style={{ marginTop: 14 }}>Read the full playbook: why, guidelines and decisions per step →</a>
      </section>

      <section className="home-stats" ref={statsRef}>
        <h2>The lift, in numbers</h2>
        <div className="home-stat-grid">
          <div><b><Count to={n.reports} run={statsSeen} /></b><span>reports analysed</span></div>
          <div className="big"><b><Count to={n.reduction} suffix="%" run={statsSeen} /></b><span>fewer reports to migrate</span></div>
          <div><b><Count to={n.conflicts} run={statsSeen} /></b><span>KPI conflicts surfaced before build</span></div>
          <div><b><Count to={n.views} run={statsSeen} /></b><span>governed semantic views</span></div>
          <div><b><Count to={n.products} run={statsSeen} /></b><span>data products</span></div>
          <div><b><Count to={n.objects} run={statsSeen} /></b><span>platform objects generated</span></div>
        </div>
        <div className="home-note">Figures from the {n.label}: {n.reports.toLocaleString()} reports narrowed to {n.live.toLocaleString()} carried forward, scoped to {n.tables} source tables.</div>
      </section>

      <section className="home-features">
        <h2>Manual migration vs SemanticLift</h2>
        <table className="tbl compare card">
          <thead><tr><th /><th>Typical manual migration</th><th>With SemanticLift</th></tr></thead>
          <tbody>{COMPARE.map(([k, a, b]) => <tr key={k}><td><b>{k}</b></td><td className="muted">{a}</td><td>{b}</td></tr>)}</tbody>
        </table>
      </section>

      <section className="home-split">
        <div>
          <h2>Built for the enterprise from day one</h2>
          <div className="home-ent">
            {ENTERPRISE.map(([t, d]) => <div key={t}><b>{t}</b><span>{d}</span></div>)}
          </div>
        </div>
        <div>
          <h2>Something for everyone at the table</h2>
          <div className="home-roles">
            {ROLES.map(([r, d]) => <div key={r}><b>{r}</b><span>{d}</span></div>)}
          </div>
        </div>
      </section>

      <section className="home-features">
        <h2>Where it fits</h2>
        <div className="fit">
          <div className="fit-col">
            <h4>BI sources</h4>
            <div><span className="pill good">available</span> IBM Cognos: report specifications, Framework Manager models, usage audit, security, prompts</div>
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
      </section>

      <section className="home-final">
        <h2>Stop migrating reports.<br />Start lifting meaning.</h2>
        <p>Bring one Cognos export. Leave with a scoped, evidence-backed plan and a generated semantic layer to review.</p>
        <div className="row gap wrap" style={{ justifyContent: 'center' }}>
          <a className="btn home-cta" href={start}>Start your lift →</a>
          <a className="btn home-ghost" href="#/export-guide">What to export from Cognos</a>
        </div>
      </section>
    </div>
  )
}
