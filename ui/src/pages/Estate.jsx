import React, { useMemo, useState } from 'react'
import { Bar, Kpi, Loading, SearchBox, Section, Status, Tabs, fmt, useApi } from '../components'

const DISP = ['Migrate', 'Merge', 'Defect fix needed', 'Retire']

export default function Estate() {
  const { data, error, loading } = useApi('/api/estate')
  const [tab, setTab] = useState('clusters')
  const [q, setQ] = useState('')
  const [pkg, setPkg] = useState('')
  const [disp, setDisp] = useState('')

  const view = useMemo(() => {
    if (!data) return {}
    const reps = data.reports
    const totalRuns = reps.reduce((a, r) => a + (r.runs_per_day || 0), 0)
    const byFolderRuns = {}
    reps.forEach((r) => { byFolderRuns[r.folder] = (byFolderRuns[r.folder] || 0) + (r.runs_per_day || 0) })
    const dormant = reps.filter((r) => !r.runs_per_day)
    return { totalRuns, byFolderRuns, dormant }
  }, [data])

  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>2. Estate overview</h1>
          <p className="lede">Rationalize first: duplicate archive and community copies collapse into intent clusters, dormant content is retired, and only demanded logic is migrated.</p>
          <div className="kpis">
            <Kpi label="Reports" value={fmt(data.reports.length)} />
            <Kpi label="Intent clusters" value={data.rationalization.clusters} sub={`${data.rationalization.distinct_active_signatures} distinct active signatures`} />
            <Kpi label="Retired clusters" value={data.rationalization.retired_clusters} tone="warn" sub={`no run since ${data.rationalization.window_start}`} />
            <Kpi label="Runs / day" value={fmt(view.totalRuns)} sub={`duplicates ${fmt(100 * (1 - (view.byFolderRuns.Active || 0) / (view.totalRuns || 1)))}% of runs`} />
            <Kpi label="Dormant (0 runs/day)" value={view.dormant.length} tone="bad" />
          </div>
          <Section title="Packages">
              <table className="tbl">
                <thead><tr><th>Package</th><th>Source system</th><th>FM model</th><th>FM coverage</th><th className="r">Reports</th><th>Runs/day</th><th>Dispositions</th></tr></thead>
                <tbody>{data.packages.map((p) => {
                  const maxRuns = Math.max(...data.packages.map((x) => x.runs_per_day))
                  return (
                    <tr key={p.package}>
                      <td><b>{p.package.replace(/^Energy_|_Package$/g, '')}</b><div className="muted small">{(p.data_modules || []).join(', ')}</div></td>
                      <td className="small">{p.source_system}</td>
                      <td>{p.fm_model ? <span className="pill good">own FM</span> : <span className="pill bad">none</span>}</td>
                      <td style={{ minWidth: 110 }}><Bar value={p.fm_coverage_pct} max={100} label={`${p.fm_coverage_pct}% items`} tone={p.fm_coverage_pct >= 80 ? 'good' : p.fm_coverage_pct >= 30 ? 'warn' : 'bad'} /></td>
                      <td className="r">{p.reports}</td>
                      <td style={{ minWidth: 120 }}><Bar value={p.runs_per_day} max={maxRuns} label={fmt(p.runs_per_day)} /></td>
                      <td className="small">{DISP.filter((d) => p.by_disposition[d]).map((d) => <span key={d} className={`chip d-${d.split(' ')[0].toLowerCase()}`}>{d.split(' ')[0]} {p.by_disposition[d]}</span>)}</td>
                    </tr>)
                })}</tbody>
              </table>
          </Section>
          <div className="grid2">
            <Section title="Reports by disposition">
              {DISP.map((d) => (
                <div key={d} className="hrow"><span className="hlabel">{d}</span>
                  <Bar value={data.dispositions[d] || 0} max={data.reports.length} label={data.dispositions[d] || 0} tone={d === 'Retire' ? 'bad' : d === 'Merge' ? 'warn' : 'good'} /></div>))}
            </Section>
            <Section title="Runs/day by folder">
              {Object.entries(view.byFolderRuns).map(([k, v]) => (
                <div key={k} className="hrow"><span className="hlabel">{k}</span><Bar value={v} max={view.totalRuns} label={fmt(v)} /></div>))}
              <div className="small muted">Archive and community copies carry most of the load: retirement needs a redirect plan, not just deletion.</div>
            </Section>
          </div>
          <Section title="Detail" actions={<div className="row gap">
            <SearchBox value={q} onChange={setQ} />
            <select value={pkg} onChange={(e) => setPkg(e.target.value)}><option value="">All packages</option>{data.packages.map((p) => <option key={p.package}>{p.package}</option>)}</select>
            <select value={disp} onChange={(e) => setDisp(e.target.value)}><option value="">All dispositions</option>{['Migrate', 'Retire'].map((d) => <option key={d}>{d}</option>)}</select>
          </div>}>
            <Tabs value={tab} onChange={setTab} tabs={[{ key: 'clusters', label: 'Duplicate clusters', count: data.clusters.length },
              { key: 'reports', label: 'Reports', count: data.reports.length }, { key: 'dormant', label: 'Dormant content', count: view.dormant.length }]} />
            {tab === 'clusters' && (
              <table className="tbl">
                <thead><tr><th>Cluster</th><th>Canonical report</th><th>Members</th><th>Facts</th><th className="r">Runs/day</th><th className="r">Weighted demand</th><th>Disposition</th><th>Reason</th></tr></thead>
                <tbody>{data.clusters.filter((c) => (!pkg || c.package === pkg) && (!disp || c.disposition === disp) && (!q || JSON.stringify(c).toLowerCase().includes(q.toLowerCase()))).map((c) => (
                  <tr key={c.id}><td className="mono">{c.id}</td><td>{c.canonical}</td><td className="small">{c.members.length}</td><td className="small">{c.facts.join(', ')}</td>
                    <td className="r">{fmt(c.runs_per_day)}</td><td className="r">{fmt(c.weighted_demand, 1)}</td><td><Status value={c.disposition} /></td><td className="small muted">{c.reason}</td></tr>))}</tbody>
              </table>)}
            {(tab === 'reports' || tab === 'dormant') && (
              <table className="tbl">
                <thead><tr><th>Report</th><th>Type</th><th>Folder</th><th>Cluster</th><th className="r">Runs/day</th><th>Last run</th><th className="r">Sim.</th><th>Disposition</th><th>Defects</th></tr></thead>
                <tbody>{(tab === 'dormant' ? view.dormant : data.reports).filter((r) => (!pkg || r.package === pkg) && (!disp || r.disposition === disp) && (!q || r.name.toLowerCase().includes(q.toLowerCase()))).slice(0, 600).map((r) => (
                  <tr key={r.name}><td>{r.name}</td><td>{r.type}</td><td>{r.folder}</td><td className="mono small">{r.cluster}</td><td className="r">{fmt(r.runs_per_day)}</td>
                    <td className="small">{r.last_run}</td><td className="r">{r.similarity}</td><td><Status value={r.disposition} /></td><td className="small">{r.defects.join(', ')}</td></tr>))}</tbody>
              </table>)}
          </Section>
        </div>
      )}
    </Loading>
  )
}
