import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { api } from './api'
import Ingest from './pages/Ingest'
import Estate from './pages/Estate'
import Model from './pages/Model'
import LogicalModel from './pages/LogicalModel'
import Findings from './pages/Findings'
import Review from './pages/Review'
import Aggregates from './pages/Aggregates'
import Deploy from './pages/Deploy'

const PAGES = [
  { key: 'ingest', label: 'Ingest', icon: '⇪', el: Ingest },
  { key: 'estate', label: 'Estate overview', icon: '▦', el: Estate },
  { key: 'model', label: 'Model canvas', icon: '◎', el: Model },
  { key: 'ldm', label: 'Logical data model', icon: '⊞', el: LogicalModel },
  { key: 'findings', label: 'Findings', icon: '⚑', el: Findings },
  { key: 'review', label: 'Design review', icon: '✓', el: Review },
  { key: 'aggregates', label: 'Aggregate planner', icon: '▤', el: Aggregates },
  { key: 'deploy', label: 'Deploy & validate', icon: '⇧', el: Deploy },
]

function route() {
  const h = window.location.hash.replace(/^#\/?/, '')
  const [page, ...rest] = h.split('/')
  return { page: PAGES.find((p) => p.key === page) ? page : 'ingest', arg: decodeURIComponent(rest.join('/')) }
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
          <a key={p.key} href={`#/${p.key}`} className={r.page === p.key ? 'nav-item active' : 'nav-item'}>
            <span className="nav-icon">{p.icon}</span><span>{i + 1}. {p.label}</span>
          </a>
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
        <Page arg={r.arg} summary={summary} onRun={() => setTick((t) => t + 1)} key={r.page} />
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
