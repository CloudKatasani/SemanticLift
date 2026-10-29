import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { api, currentProject, setProject } from './api'
import { setPackageAffixes } from './components'
import Projects from './pages/Projects'
import Home from './pages/Home'
import Demo from './pages/Demo'
import ExportGuide from './pages/ExportGuide'
import Audit from './pages/Audit'
import Ingest from './pages/Ingest'
import Strategy from './pages/Strategy'
import ObjectLineage from './pages/ObjectLineage'
import Rationalization from './pages/Rationalization'
import KpiLineage from './pages/KpiLineage'
import CommonKpis from './pages/CommonKpis'
import DataSources from './pages/DataSources'
import LogicalModel from './pages/LogicalModel'
import DataProducts from './pages/DataProducts'
import Model from './pages/Model'
import Findings from './pages/Findings'
import Review from './pages/Review'
import Deploy from './pages/Deploy'

const PAGES = [
  { key: 'home', label: 'Product overview', icon: '✦', el: Home, section: 'Overview', global: true },
  { key: 'strategy', label: 'Strategy & approach', icon: '★', el: Strategy, section: 'Overview', global: true },
  { key: 'ingest', label: 'Upload & run', icon: '⇪', el: Ingest, section: 'Setup' },
  { key: 'rationalization', label: '1. Report rationalization', icon: '◧', el: Rationalization, section: 'Migration workflow' },
  { key: 'kpi-lineage', label: '2. KPI lineage', icon: '⇢', el: KpiLineage, section: 'Migration workflow' },
  { key: 'common-kpis', label: '3. Common KPIs', icon: '≡', el: CommonKpis, section: 'Migration workflow' },
  { key: 'sources', label: '4. Databases & tables', icon: '▤', el: DataSources, section: 'Migration workflow' },
  { key: 'ldm', label: '5. Logical data model', icon: '⊞', el: LogicalModel, section: 'Migration workflow' },
  { key: 'products', label: '6. Data products & semantic layer', icon: '◈', el: DataProducts, section: 'Migration workflow' },
  { key: 'objects', label: '7. Object lineage', icon: '⇄', el: ObjectLineage, section: 'Migration workflow' },
  { key: 'findings', label: 'Findings', icon: '⚑', el: Findings, section: 'Delivery' },
  { key: 'review', label: 'Design review', icon: '✓', el: Review, section: 'Delivery' },
  { key: 'deploy', label: 'Deploy & validate', icon: '⇧', el: Deploy, section: 'Delivery' },
  { key: 'audit', label: 'Audit trail', icon: '☰', el: Audit, section: 'Delivery' },
  { key: 'model', label: 'Model canvas', icon: '◎', el: Model, section: 'Explore' },
  { key: 'projects', label: 'Client projects', icon: '▦', el: Projects, section: 'Administration', global: true },
  { key: 'export-guide', label: 'Cognos export guide', icon: '⇩', el: ExportGuide, section: 'Administration', global: true },
  { key: 'demo', label: 'Demo walkthrough', icon: '▶', el: Demo, section: 'Learn', global: true },
]
// older deep links keep working
const ALIASES = { why: ['home', ''], estate: ['rationalization', ''], lineage: ['products', 'lineage'], aggregates: ['products', 'aggregates'] }

function route() {
  const h = window.location.hash.replace(/^#\/?/, '')
  let [page, ...rest] = h.split('/')
  let arg = decodeURIComponent(rest.join('/'))
  if (ALIASES[page]) [page, arg] = ALIASES[page]
  return { page: PAGES.find((p) => p.key === page) ? page : 'home', arg }
}

function SignIn({ message }) {
  const [tok, setTok] = useState('')
  const save = (e) => { e.preventDefault(); try { localStorage.setItem('semlift_token', tok.trim()) } catch { /* ignore */ } window.location.reload() }
  return (
    <div className="signin">
      <div className="card" style={{ maxWidth: 460 }}>
        <div className="brand dark">Semantic<span>Lift</span></div>
        <p className="muted">{message || 'Sign in to continue.'}</p>
        <p className="small">If your organisation signs in through single sign-on, open SemanticLift through its SSO address. Otherwise paste the personal API token your administrator gave you.</p>
        <form className="form" onSubmit={save}><label>Personal API token<input type="password" value={tok} onChange={(e) => setTok(e.target.value)} autoFocus /></label>
          <div><button className="btn primary" type="submit" disabled={!tok.trim()}>Sign in</button></div></form>
      </div>
    </div>
  )
}

function App() {
  const [r, setR] = useState(route())
  const [summary, setSummary] = useState(null)
  const [tick, setTick] = useState(0)
  const [me, setMe] = useState(null)
  const [authErr, setAuthErr] = useState(null)
  const [projects, setProjects] = useState(null)
  const [project, setProj] = useState(currentProject())
  const [toast, setToast] = useState(null)
  useEffect(() => {
    const on = () => setR(route())
    window.addEventListener('hashchange', on)
    const err = (e) => { setToast(e.detail); setTimeout(() => setToast(null), 7000) }
    window.addEventListener('semlift:error', err)
    // API errors are already shown in the toast; do not also surface them as uncaught promise errors
    const rej = (e) => { if (e.reason && e.reason.status) e.preventDefault() }
    window.addEventListener('unhandledrejection', rej)
    return () => { window.removeEventListener('hashchange', on); window.removeEventListener('semlift:error', err); window.removeEventListener('unhandledrejection', rej) }
  }, [])
  const loadProjects = () => api.get('/api/projects').then((list) => {
    setProjects(list)
    const cur = currentProject()
    if (!list.find((p) => p.id === cur)) {
      const next = list.length === 1 ? list[0].id : list.find((p) => p.id === 'default')?.id || null
      setProject(next); setProj(next)
    }
  }).catch((e) => { if (e.status === 401) setAuthErr(e.message) })
  useEffect(() => { loadProjects() }, [])
  useEffect(() => {
    if (!projects) return
    api.get('/api/me').then(setMe).catch(() => setMe(null))
    if (!project) { setSummary(null); return }
    api.get('/api/summary').then((s) => { setSummary(s); setPackageAffixes(s.display?.package_affixes) }).catch(() => setSummary(null))
  }, [tick, project, projects])
  const open = (id, page) => { setProject(id); setProj(id); setTick((t) => t + 1); window.location.hash = `#/${page || 'strategy'}`; loadProjects() }

  if (authErr) return <SignIn message={authErr} />
  if (!projects) return <div className="muted pad">Loading…</div>
  const pageDef = PAGES.find((p) => p.key === r.page)
  const needsProject = !pageDef.global && !project
  const Page = needsProject ? Projects : pageDef.el
  const proj = projects.find((p) => p.id === project)
  return (
    <div className="shell">
      <aside className="nav">
        <div className="brand">Semantic<span>Lift</span></div>
        <div className="brand-sub">Cognos → Data Platform semantic layer</div>
        {PAGES.map((p, i) => (
          <React.Fragment key={p.key}>
            {(i === 0 || PAGES[i - 1].section !== p.section) && <div className="nav-sec">{p.section}</div>}
            <a href={`#/${p.key}`} className={`${r.page === p.key ? 'nav-item active' : 'nav-item'}${!p.global && !project ? ' disabled' : ''}`}>
              <span className="nav-icon">{p.icon}</span><span>{p.label}</span>
            </a>
          </React.Fragment>
        ))}
        <div className="nav-foot">
          {proj && <div className="nav-proj"><b>{proj.client ? `${proj.client} · ` : ''}{proj.name}</b> <a href="#/projects">Change</a></div>}
          {summary ? (
            <>
              <div>Run <b>{summary.run_id}</b></div>
              <div className="muted">{new Date(summary.time).toLocaleString()}</div>
              <div className="muted">{summary.objects} objects · {summary.findings} findings</div>
            </>
          ) : <div className="muted">{project ? 'No run yet' : 'No project selected'}</div>}
          {me && (
            <div className="nav-user">
              <b>{me.name}</b>{me.auth_mode === 'open' && <span className="pill warn tiny">open mode</span>}
              <div className="muted tiny">{(me.roles || []).join(' · ') || 'no access to this project'}</div>
              {me.auth_mode === 'users' && <a className="tiny" href="#" onClick={(e) => { e.preventDefault(); try { localStorage.removeItem('semlift_token') } catch { /* ignore */ } window.location.reload() }}>Sign out</a>}
            </div>)}
        </div>
      </aside>
      <main className="main">
        {proj && proj.status === 'archived' && <div className="banner">This project is archived and read-only.</div>}
        <Page arg={r.arg} summary={summary} me={me} current={project} onOpen={open} onChanged={loadProjects}
              onRun={() => { setTick((t) => t + 1); loadProjects() }} key={`${project}/${needsProject ? 'projects' : r.page}/${r.arg}`} />
      </main>
      {toast && <div className="toast" onClick={() => setToast(null)}>{toast}</div>}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
