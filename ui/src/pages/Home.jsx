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

const ACTS = [
  { act: 'Act I', title: 'The sprawl', tone: 'act-1',
    text: 'Monday, 9 a.m. Two dashboards, one question, two revenue numbers. Behind them sit thousands of reports built up over twenty years: copies of copies, personal variants, reports nobody has opened since the last reorganisation. The business logic that makes the numbers is locked inside the BI tool, in models only a handful of people can still read.' },
  { act: 'Act II', title: 'The lift', tone: 'act-2',
    text: 'SemanticLift reads the whole estate: every report specification, every query and filter, every audit log line, every security rule. It shows which reports are really used and which are copies, finds every KPI calculated three different ways, and traces each one back to the column it comes from. People decide; the evidence sits next to every decision.' },
  { act: 'Act III', title: 'The landing', tone: 'act-3',
    text: 'What lands on the cloud platform is smaller and better: one approved definition per KPI, a conformed model, governed semantic views and data products that every BI tool, notebook and AI agent shares. Lineage proves where every number comes from, parity checks prove it still matches, and the old tool can finally be switched off.' },
]

const FEATURES = [
  { icon: '◉', title: 'Read everything', text: 'Report specs, Framework Manager models, audit usage, prompts and security in one metadata graph, with provenance for every element.' },
  { icon: '✂', title: 'Cut with evidence', text: 'Keep, Review, Consolidate or Retire for every report, with the rule, the usage and the KPI overlap behind it.' },
  { icon: '≡', title: 'One truth per KPI', text: 'Conflicting aggregations, filters and definitions are surfaced up front, and a steward approves the right one.' },
  { icon: '◈', title: 'Generate the platform', text: 'Snowflake DDL, semantic views, aggregates, row and column policies, data-product contracts, Databricks metric views and dbt.' },
  { icon: '⇄', title: 'Trace every number', text: 'Lineage from report column to platform column, and from every object to the reports it replaces.' },
  { icon: '✓', title: 'Prove it, then ship', text: 'Human review, Git and CI deployment, and parity SQL that compares old and new numbers before cut-over.' },
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
          <a className="btn home-ghost" href="#/why">See how it works</a>
        </div>
        <div className="home-flow" aria-hidden="true">
          <span>Thousands of reports</span><i>→</i><span>Evidence</span><i>→</i><span>Decisions</span><i>→</i><span className="hl">One semantic layer</span>
        </div>
      </section>

      <section className="home-band">
        <div className="home-quote">“The hard part of a BI migration was never the reports. It was the meaning inside them.”</div>
      </section>

      <section className="home-acts">
        {ACTS.map((a) => (
          <div key={a.act} className={`home-act ${a.tone}`}>
            <div className="home-act-n">{a.act}</div>
            <h3>{a.title}</h3>
            <p>{a.text}</p>
          </div>))}
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
        <h2>Everything a migration needs. Nothing it doesn't.</h2>
        <div className="home-feature-grid">
          {FEATURES.map((f) => (
            <div key={f.title} className="home-feature"><div className="home-feature-icon">{f.icon}</div><b>{f.title}</b><p>{f.text}</p></div>))}
        </div>
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

      <section className="home-final">
        <h2>Stop migrating reports.<br />Start lifting meaning.</h2>
        <p>Bring one Cognos export. Leave with a scoped, evidence-backed plan and a generated semantic layer to review.</p>
        <div className="row gap wrap" style={{ justifyContent: 'center' }}>
          <a className="btn home-cta" href={start}>Start your lift →</a>
          <a className="btn home-ghost" href="#/export-guide">What to export from Cognos</a>
        </div>
        <div className="home-fine">IBM Cognos available today · Snowflake, Databricks metric views and dbt generated · More BI sources on the roadmap</div>
      </section>
    </div>
  )
}
