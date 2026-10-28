import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { api } from './api'
import Ingest from './pages/Ingest'
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
  { key: 'ingest', label: 'Upload & run', icon: '⇪', el: Ingest, section: 'Setup' },
  { key: 'rationalization', label: '1. Report rationalization', icon: '◧', el: Rationalization, section: 'Migration workflow' },
  { key: 'kpi-lineage', label: '2. KPI lineage', icon: '⇢', el: KpiLineage, section: 'Migration workflow' },
  { key: 'common-kpis', label: '3. Common KPIs', icon: '≡', el: CommonKpis, section: 'Migration workflow' },
  { key: 'sources', label: '4. Databases & tables', icon: '▤', el: DataSources, section: 'Migration workflow' },
  { key: 'ldm', label: '5. Logical data model', icon: '⊞', el: LogicalModel, section: 'Migration workflow' },
  { key: 'products', label: '6. Data products & semantic layer', icon: '◈', el: DataProducts, section: 'Migration workflow' },
  { key: 'findings', label: 'Findings', icon: '⚑', el: Findings, section: 'Delivery' },
  { key: 'review', label: 'Design review', icon: '✓', el: Review, section: 'Delivery' },
  { key: 'deploy', label: 'Deploy & validate', icon: '⇧', el: Deploy, section: 'Delivery' },
  { key: 'model', label: 'Model canvas', icon: '◎', el: Model, section: 'Explore' },
]
// older deep links keep working
const ALIASES = { estate: ['rationalization', ''], lineage: ['products', 'lineage'], aggregates: ['products', 'aggregates'] }

function route() {
  const h = window.location.hash.replace(/^#\/?/, '')
  let [page, ...rest] = h.split('/')
  let arg = decodeURIComponent(rest.join('/'))
  if (ALIASES[page]) [page, arg] = ALIASES[page]
  return { page: PAGES.find((p) => p.key === page) ? page : 'rationalization', arg }
}

function App() {
  const [r, setR] = useState(route())
  const [summary, setSummary] = useState(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const on = () => setR(route())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  useEffect(() => { api.get('/api/summary').then(setSummary).catch(() => setSummary(null)) }, [tick])
  const Page = PAGES.find((p) => p.key === r.page).el
  return (
    <div className="shell">
      <aside className="nav">
        <div className="brand">Sem<span>Lift</span></div>
        <div className="brand-sub">Cognos → Data Platform semantic layer</div>
        {PAGES.map((p, i) => (
          <React.Fragment key={p.key}>
            {(i === 0 || PAGES[i - 1].section !== p.section) && <div className="nav-sec">{p.section}</div>}
            <a href={`#/${p.key}`} className={r.page === p.key ? 'nav-item active' : 'nav-item'}>
              <span className="nav-icon">{p.icon}</span><span>{p.label}</span>
            </a>
          </React.Fragment>
        ))}
        <div className="nav-foot">
          {summary ? (
            <>
              <div>Run <b>{summary.run_id}</b></div>
              <div className="muted">{new Date(summary.time).toLocaleString()}</div>
              <div className="muted">{summary.objects} objects · {summary.findings} findings</div>
            </>
          ) : <div className="muted">No run yet</div>}
        </div>
      </aside>
      <main className="main">
        <Page arg={r.arg} summary={summary} onRun={() => setTick((t) => t + 1)} key={`${r.page}/${r.arg}`} />
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
