import React, { useState } from 'react'
import { api } from '../api'
import { Disp, Kpi, Loading, Section, useApi } from '../components'

const ago = (t) => {
  if (!t) return '–'
  const d = (Date.now() - new Date(t).getTime()) / 86400000
  return d < 1 ? 'today' : d < 2 ? 'yesterday' : `${Math.floor(d)} days ago`
}

function Progress({ value, total, label }) {
  const pct = total ? Math.round((100 * value) / total) : 0
  return (
    <div className="prog" title={`${value} of ${total}`}>
      <div className="prog-head"><span>{label}</span><b>{total ? `${value}/${total}` : '–'}</b></div>
      <div className="prog-bar"><div style={{ width: `${pct}%` }} /></div>
    </div>
  )
}

export default function Projects({ me, current, onOpen, onChanged }) {
  const [archived, setArchived] = useState(false)
  const { data, error, loading, reload } = useApi(`/api/projects${archived ? '?include_archived=true' : ''}`)
  const configs = useApi('/api/configs')
  const [form, setForm] = useState({ name: '', client: '', description: '', config: '' })
  const [msg, setMsg] = useState(null)

  const create = async (e) => {
    e.preventDefault(); setMsg(null)
    try {
      const p = await api.post('/api/projects', { ...form, config: form.config || null })
      setForm({ name: '', client: '', description: '', config: '' }); reload(); onChanged && onChanged()
      onOpen(p.id, 'ingest')
    } catch (err) { setMsg(err.message) }
  }
  const setStatus = async (p, status) => { await api.patch(`/api/projects/${p.id}`, { status }); reload(); onChanged && onChanged() }

  const list = data || []
  const withRun = list.filter((p) => p.summary)
  const totals = withRun.reduce((a, p) => ({ reports: a.reports + p.summary.reports, keep: a.keep + (p.summary.dispositions.Keep || 0) + (p.summary.dispositions.Review || 0) }), { reports: 0, keep: 0 })

  return (
    <Loading error={error} loading={loading}>
      <div>
        <h1>Client projects</h1>
        <p className="lede">Each client engagement is an isolated project with its own uploads, configuration, decisions, audit trail and output package. Access is granted per project and role. Pick a project to work in it; the left menu then applies to that project.</p>
        <div className="kpis">
          <Kpi label="Projects" value={list.length} sub={`${list.filter((p) => p.status === 'active').length} active`} />
          <Kpi label="Clients" value={new Set(list.map((p) => p.client || p.name)).size} />
          <Kpi label="Reports analysed" value={totals.reports.toLocaleString()} />
          <Kpi label="Reports carried forward" value={totals.keep.toLocaleString()} sub={totals.reports ? `${Math.round(100 - (100 * totals.keep) / totals.reports)}% fewer` : ''} tone="good" />
        </div>
        <Section title="Portfolio" actions={<label className="small"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> show archived</label>}>
          {!list.length && <div className="muted pad">No projects yet{me?.admin ? ' — create the first one below.' : '. Ask an administrator to give you access to a project.'}</div>}
          <div className="proj-grid">
            {list.map((p) => {
              const s = p.summary
              const d = s?.dispositions || {}
              const approved = s ? (s.object_reviews?.approved || 0) : 0
              return (
                <div key={p.id} className={`proj-card ${p.id === current ? 'sel' : ''} ${p.status === 'archived' ? 'archived' : ''}`}>
                  <div className="row gap" style={{ justifyContent: 'space-between' }}>
                    <div>
                      <div className="tiny muted">{p.client || 'No client set'}</div>
                      <h3 style={{ margin: '2px 0' }}>{p.name}</h3>
                      <div className="tiny muted mono">{p.id}</div>
                    </div>
                    {p.status === 'archived' ? <span className="pill">archived</span> : p.id === current ? <span className="pill good">current</span> : null}
                  </div>
                  {p.description && <div className="small muted" style={{ marginTop: 6 }}>{p.description}</div>}
                  {s ? (
                    <>
                      <div className="small" style={{ margin: '10px 0 6px' }}>Last run <b>{s.run_id}</b> · {ago(s.time)} · {s.reports} reports in {s.packages} packages</div>
                      <div className="row gap wrap small">{['Keep', 'Review', 'Consolidate', 'Retire'].map((k) => <span key={k}><Disp value={k} /> {d[k] || 0}</span>)}</div>
                      <div className="prog-list">
                        <Progress label="KPI definitions approved" value={s.kpi_approved} total={s.kpi_groups} />
                        <Progress label="Objects approved" value={approved} total={s.objects} />
                        <Progress label="Findings closed" value={s.findings - s.findings_open} total={s.findings} />
                      </div>
                      <div className="tiny muted">
                        {s.report_decisions} report and {s.source_decisions} source decisions
                        {s.pending_rerun && <span className="pill warn tiny">re-run needed</span>}
                        {s.last_deploy ? ` · last Git deploy ${ago(s.last_deploy.time)}` : ' · not deployed yet'}
                      </div>
                    </>
                  ) : <div className="small muted" style={{ margin: '12px 0' }}>No run yet. Upload the client's Cognos export to start.</div>}
                  <div className="row gap wrap" style={{ marginTop: 10 }}>
                    {p.status !== 'archived' && <button className="btn primary" onClick={() => onOpen(p.id, s ? 'strategy' : 'ingest')}>{p.id === current ? 'Continue' : 'Open'}</button>}
                    {(p.my_roles || []).includes('admin') && (p.status === 'archived'
                      ? <button className="btn" onClick={() => setStatus(p, 'active')}>Restore</button>
                      : <button className="btn" onClick={() => setStatus(p, 'archived')}>Archive</button>)}
                    <span className="tiny muted">Your roles: {(p.my_roles || []).join(', ') || '–'}</span>
                  </div>
                </div>)
            })}
          </div>
        </Section>
        {me?.admin && (
          <Section title="New client project">
            <form className="form" onSubmit={create}>
              <label>Client<input value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} placeholder="e.g. Acme Energy" /></label>
              <label>Project name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Cognos wave 1" /></label>
              <label>Description<input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Scope, packages, sponsor…" /></label>
              <label>Starting configuration
                <select value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })}>
                  <option value="">Generic defaults</option>
                  {(configs.data || []).map((c) => <option key={c}>{c}</option>)}
                </select>
              </label>
              <div><button className="btn primary" type="submit">Create project</button></div>
              {msg && <div className="error">{msg}</div>}
              <div className="tiny muted">The project id is derived from client and name. Start new clients from <span className="mono">template_estate</span> and check it with <span className="mono">semlift config check</span>.</div>
            </form>
          </Section>
        )}
      </div>
    </Loading>
  )
}
