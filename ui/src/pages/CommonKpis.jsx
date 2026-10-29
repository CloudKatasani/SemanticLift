import React, { useMemo, useState } from 'react'
import { api } from '../api'
import { Kpi, Loading, RerunBanner, SearchBox, Tabs, pkgLabel, useApi } from '../components'

const KINDS = {
  aggregation: { label: 'Aggregation rule', help: 'Reports aggregate the KPI differently from its FM / semantic-layer default.' },
  filter: { label: 'Filter rule', help: 'The same KPI is reported under different filters (subsets of rows).' },
  concept: { label: 'Business definition', help: 'One business KPI is implemented by different items in different packages.' },
}
const short = (p) => pkgLabel(p)

export default function CommonKpis({ arg }) {
  const { data, error, loading, reload, setData } = useApi('/api/kpis')
  const [kind, setKind] = useState('all')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')

  const groups = useMemo(() => (data ? data.groups.filter((g) => (kind === 'all' || g.kind === kind) && (!status || g.status === status)
    && (!q || `${g.title} ${g.kpis.join(' ')} ${g.reason}`.toLowerCase().includes(q.toLowerCase()))) : []), [data, kind, status, q])
  const ordered = useMemo(() => (arg ? [...groups].sort((a, b) => (b.id === arg) - (a.id === arg)) : groups), [groups, arg])
  const onSaved = (g) => setData({ ...data, groups: data.groups.map((x) => (x.id === g.id ? { ...x, ...g } : x)), pending_rerun: true })
  const count = (k, s) => data.groups.filter((g) => (k === 'all' || g.kind === k) && (!s || g.status === s)).length

  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>3. Common KPIs</h1>
          <p className="lede">KPIs that several reports compute differently. Each card lists the competing definitions: formula, aggregation, filter, and the reports that use each. Choose the one correct definition. The semantic layer then implements it, and reports using a different definition are flagged for review in the rationalization.</p>
          <RerunBanner pending={data.pending_rerun} onDone={reload} />
          <div className="kpis">
            <Kpi label="Common KPIs to resolve" value={count('all', 'open')} tone={count('all', 'open') ? 'warn' : 'good'} sub={`of ${data.groups.length}`} />
            <Kpi label="Approved" value={count('all', 'approved')} tone="good" />
            {Object.entries(KINDS).map(([k, v]) => <Kpi key={k} label={v.label} value={count(k)} sub={`${count(k, 'open')} open`} />)}
            <Kpi label="KPIs in catalog" value={data.kpis.length} />
          </div>
          <div className="row gap wrap" style={{ marginBottom: 10 }}>
            <Tabs value={kind} onChange={setKind} tabs={[{ key: 'all', label: 'All', count: data.groups.length },
              ...Object.entries(KINDS).map(([k, v]) => ({ key: k, label: v.label, count: count(k) }))]} />
            <SearchBox value={q} onChange={setQ} placeholder="KPI, item or reason…" />
            <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Open and approved</option><option value="open">Open</option><option value="approved">Approved</option></select>
          </div>
          {kind !== 'all' && <div className="small muted" style={{ marginBottom: 10 }}>{KINDS[kind].help}</div>}
          {ordered.map((g) => <GroupCard key={g.id} g={g} kpis={data.kpis} onSaved={onSaved} highlight={g.id === arg} />)}
          {!ordered.length && <div className="empty">No common KPIs match the filters.</div>}
        </div>
      )}
    </Loading>
  )
}

function GroupCard({ g, kpis, onSaved, highlight }) {
  const rec = g.variants.find((v) => v.recommended)
  const [choice, setChoice] = useState(g.approved_variant || rec?.id || '')
  const [comment, setComment] = useState(g.decision?.comment || '')
  const [showReports, setShowReports] = useState(null)
  const [err, setErr] = useState(null)
  const save = async (variant) => {
    setErr(null)
    try { onSaved(await api.post(`/api/kpis/${g.id}`, { variant, comment })) } catch (e) { setErr(e.message) }
  }
  const label = (id) => kpis.find((k) => k.id === id)?.label || id
  return (
    <div className={`group-card ${g.status === 'approved' ? 'approved' : ''}`} style={highlight ? { boxShadow: '0 0 0 2px #2f6fde' } : {}}>
      <div className="card-head">
        <div>
          <h3>{g.title}</h3>
          <div className="small muted">{g.reason}</div>
        </div>
        <div className="row gap">
          <span className="tag">{KINDS[g.kind].label}</span>
          <span className="tag">{g.domain === 'multiple' ? 'multiple domains' : short(g.domain)}</span>
          {g.status === 'approved' ? <span className="pill good">approved</span> : <span className="pill warn">needs decision</span>}
        </div>
      </div>
      <table className="tbl compact">
        <thead><tr><th style={{ width: 30 }} /><th>Definition</th><th>KPI item</th><th>Aggregation</th><th>Filter rule</th><th className="r">Reports (live)</th><th>Note</th></tr></thead>
        <tbody>{g.variants.map((v) => (
          <React.Fragment key={v.id}>
            <tr className={`var-row ${v.id === g.approved_variant ? 'chosen' : ''} ${v.recommended ? 'rec' : ''}`}>
              <td><input type="radio" name={g.id} checked={choice === v.id} onChange={() => setChoice(v.id)} /></td>
              <td className="mono tiny">{v.formula}</td>
              <td className="small"><a href={`#/kpi-lineage/${v.kpi}`}>{label(v.kpi)}</a><div className="muted tiny">{v.kpi}</div></td>
              <td><b>{v.aggregation}</b></td>
              <td className="mono tiny">{v.filter || '—'}</td>
              <td className="r small"><a href="#" onClick={(e) => { e.preventDefault(); setShowReports(showReports === v.id ? null : v.id) }}>{v.reports.length} ({v.live_reports})</a></td>
              <td className="small">{v.recommended && <span className="pill good tiny">recommended</span>} {v.id === g.approved_variant && <span className="pill good tiny">approved</span>} {v.note}</td>
            </tr>
            {showReports === v.id && <tr className="detail"><td /><td colSpan="6" className="small">{v.reports.map((r) => <a key={r} className="chip" href={`#/rationalization/${r}`}>{r}</a>)}{!v.reports.length && <span className="muted">No report uses this definition today; it is the semantic-layer default.</span>}</td></tr>}
          </React.Fragment>))}</tbody>
      </table>
      <div className="row gap wrap" style={{ marginTop: 8 }}>
        <input className="search" style={{ flex: 1 }} placeholder="Rationale (kept in the audit trail)" value={comment} onChange={(e) => setComment(e.target.value)} />
        <button className="btn primary" disabled={!choice} onClick={() => save(choice)}>Approve selected definition</button>
        {g.decision && <button className="btn ghost" onClick={() => save(null)}>Clear decision</button>}
      </div>
      {g.decision && <div className="small muted" style={{ marginTop: 4 }}>Approved by {g.decision.reviewer} · {new Date(g.decision.time).toLocaleString()}{g.decision.comment && ` — ${g.decision.comment}`}</div>}
      {err && <div className="error">{err}</div>}
    </div>
  )
}
