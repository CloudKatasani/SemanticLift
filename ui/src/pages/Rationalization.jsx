import React, { useMemo, useState } from 'react'
import { api } from '../api'
import { Disp, Kpi, Loading, RerunBanner, SearchBox, Section, downloadCsv, fmt, pkgLabel, useApi } from '../components'

const DISPS = ['Keep', 'Review', 'Consolidate', 'Retire']
const short = (p) => pkgLabel(p)

export default function Rationalization({ arg }) {
  const { data, error, loading, reload, setData } = useApi('/api/portfolio')
  const [disp, setDisp] = useState('')
  const [pkg, setPkg] = useState('')
  const [folder, setFolder] = useState('Active')
  const [rule, setRule] = useState('')
  const [q, setQ] = useState(arg || '')
  const [open, setOpen] = useState(arg || null)

  const rows = useMemo(() => (data ? data.reports.filter((r) => (!disp || r.disposition === disp) && (!pkg || r.package === pkg)
    && (!folder || r.folder === folder) && (!rule || r.rule === rule)
    && (!q || `${r.report} ${r.kpis.join(' ')} ${r.reasons.join(' ')}`.toLowerCase().includes(q.toLowerCase()))) : []), [data, disp, pkg, folder, rule, q])
  const packages = data ? Object.keys(data.by_package) : []
  const byReport = useMemo(() => (data ? Object.fromEntries(data.reports.map((r) => [r.report, r])) : {}), [data])

  const decide = async (r, disposition, comment, target) => {
    const res = await api.post(`/api/portfolio/${encodeURIComponent(r.report)}`, { disposition, comment, target })
    const reports = data.reports.map((x) => (x.report === r.report ? { ...x, ...res } : x))
    const summary = {}
    reports.forEach((x) => { summary[x.disposition] = (summary[x.disposition] || 0) + 1 })
    setData({ ...data, reports, summary, pending_rerun: true })
  }
  const exportCsv = () => downloadCsv('report_rationalization.csv', rows.map((r) => ({
    report: r.report, package: r.package, folder: r.folder, cluster: r.cluster, runs_per_day: r.runs_per_day,
    group_runs_per_day: r.group_runs_per_day, last_run: r.last_run, recommendation: r.recommendation, rule: r.rule,
    decision: r.decision?.disposition || '', disposition: r.disposition, target: r.target || '', kpis: r.kpis,
    reasons: r.reasons, flags: r.flags, decision_comment: r.decision?.comment || '' })))

  const runsBy = (d) => data.reports.filter((r) => r.disposition === d).reduce((a, r) => a + (r.runs_per_day || 0), 0)
  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>1. Report rationalization</h1>
          <p className="lede">Every Cognos report gets a recommendation of <b>Keep</b>, <b>Review</b>, <b>Consolidate</b> or <b>Retire</b>. The recommendation comes from usage, duplicate groups and the KPIs each report shares with others. Each one carries the evidence behind it. You can override it; decisions are saved and applied on the next run.</p>
          <RerunBanner pending={data.pending_rerun} onDone={reload} />
          <div className="kpis">
            {DISPS.map((d) => (
              <div key={d} className={`kpi click ${d === 'Keep' ? 'good' : d === 'Review' ? 'warn' : d === 'Retire' ? 'bad' : 'info'} ${disp === d ? 'on' : ''}`}
                   onClick={() => setDisp(disp === d ? '' : d)}>
                <div className="kpi-value">{data.summary[d] || 0}</div>
                <div className="kpi-label">{d}</div>
                <div className="kpi-sub">{fmt(runsBy(d))} runs/day</div>
              </div>))}
            <Kpi label="Reports in export" value={fmt(data.reports.length)} sub={`as of ${data.thresholds.as_of}`} />
            <Kpi label="Report intents migrated" value={(data.summary.Keep || 0) + (data.reports.filter((r) => r.disposition === 'Review').length)} sub="Keep + Review" />
          </div>
          <div className="grid2">
            <Section title="How recommendations are made">
              <table className="tbl compact">
                <tbody>{data.rules.map((r) => (
                  <tr key={r.id} className={rule === r.id ? 'sel' : ''} onClick={() => setRule(rule === r.id ? '' : r.id)} style={{ cursor: 'pointer' }}>
                    <td className="mono">{r.id}</td><td><Disp value={r.disposition} /></td><td className="small">{r.rule}</td>
                    <td className="r small">{data.reports.filter((x) => x.rule === r.id).length}</td></tr>))}</tbody>
              </table>
              <div className="small muted">Thresholds: look-back {data.thresholds.lookback_days} days · review below {data.thresholds.review_min_runs_per_day} runs/day or no run in {data.thresholds.review_stale_days} days · consolidate when dimension overlap ≥ {Math.round(data.thresholds.consolidate_dim_jaccard * 100)}%. Change them in the estate configuration.</div>
            </Section>
            <Section title="By package">
              <table className="tbl compact">
                <thead><tr><th>Package</th><th>Disposition mix</th>{DISPS.map((d) => <th key={d} className="r">{d}</th>)}</tr></thead>
                <tbody>{packages.map((p) => {
                  const counts = Object.fromEntries(DISPS.map((d) => [d, data.reports.filter((r) => r.package === p && r.disposition === d).length]))
                  const tot = DISPS.reduce((a, d) => a + counts[d], 0) || 1
                  return (
                    <tr key={p} className={pkg === p ? 'sel' : ''} onClick={() => setPkg(pkg === p ? '' : p)} style={{ cursor: 'pointer' }}>
                      <td><b>{short(p)}</b></td>
                      <td><div className="stack">{['k', 'r', 'c', 'x'].map((c, i) => <div key={c} className={`s-${c}`} style={{ width: `${100 * counts[DISPS[i]] / tot}%` }} />)}</div></td>
                      {DISPS.map((d) => <td key={d} className="r">{counts[d]}</td>)}</tr>)
                })}</tbody>
              </table>
            </Section>
          </div>
          <Section title={`${rows.length} reports`} actions={<div className="row gap wrap">
            <SearchBox value={q} onChange={setQ} placeholder="Report, KPI or reason…" />
            <select value={folder} onChange={(e) => setFolder(e.target.value)}><option value="">All folders (incl. copies)</option><option>Active</option><option>Archive</option><option>Community</option></select>
            <select value={pkg} onChange={(e) => setPkg(e.target.value)}><option value="">All packages</option>{packages.map((p) => <option key={p} value={p}>{short(p)}</option>)}</select>
            <select value={disp} onChange={(e) => setDisp(e.target.value)}><option value="">All dispositions</option>{DISPS.map((d) => <option key={d}>{d}</option>)}</select>
            <button className="btn" onClick={exportCsv}>Export CSV</button>
          </div>}>
            <table className="tbl">
              <thead><tr><th>Report</th><th>Package</th><th>Folder</th><th className="r">Runs/day</th><th>Last run</th><th>KPIs</th><th>Recommended</th><th>Decision</th><th>Consolidate into</th></tr></thead>
              <tbody>{rows.map((r) => (
                <React.Fragment key={r.report}>
                  <tr className={open === r.report ? 'sel' : ''} onClick={() => setOpen(open === r.report ? null : r.report)} style={{ cursor: 'pointer' }}>
                    <td><b>{r.report}</b><div className="small muted">{r.reasons[0]?.slice(0, 110)}{r.reasons[0]?.length > 110 ? '…' : ''}</div></td>
                    <td className="small">{short(r.package)}</td><td className="small">{r.folder}</td>
                    <td className="r">{fmt(r.runs_per_day)}</td><td className="small nowrap">{r.last_run}</td>
                    <td className="small">{r.kpis.length}</td>
                    <td className="nowrap"><Disp value={r.recommendation} /> <span className="muted tiny">{r.rule}</span></td>
                    <td>{r.decision ? <Disp value={r.decision.disposition} /> : <span className="muted small">–</span>}</td>
                    <td className="small">{r.disposition === 'Consolidate' ? r.target : ''}</td>
                  </tr>
                  {open === r.report && <tr className="detail"><td colSpan="9"><Detail r={r} byReport={byReport} reports={data.reports} onDecide={decide} /></td></tr>}
                </React.Fragment>))}</tbody>
            </table>
          </Section>
        </div>
      )}
    </Loading>
  )
}

function Detail({ r, byReport, reports, onDecide }) {
  const [comment, setComment] = useState(r.decision?.comment || '')
  const [target, setTarget] = useState(r.target || '')
  const members = reports.filter((x) => x.cluster === r.cluster)
  const targets = reports.filter((x) => x.package === r.package && x.folder === 'Active' && x.report !== r.report && ['Keep', 'Review'].includes(x.disposition))
  return (
    <div className="detail-grid">
      <div>
        <h4>Why {r.recommendation}</h4>
        <ul className="reasons">{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>
        {r.flags.length > 0 && (<><h4>Also note</h4><ul className="reasons flags">{r.flags.map((x, i) => <li key={i}>{x}</li>)}</ul></>)}
        {r.overlap && (
          <div className="small"><h4>Common-KPI overlap with {r.overlap.target}</h4>
            {r.overlap.kpis_shared} of {r.overlap.kpis_total} KPIs shared (target has {r.overlap.target_kpis}); dimension overlap {Math.round(r.overlap.dimension_jaccard * 100)}%
            {r.overlap.extra_dimensions.length > 0 && <> · extra dimensions to carry: {r.overlap.extra_dimensions.join(', ')}</>}</div>)}
        <h4>KPIs ({r.kpis.length})</h4>
        <div className="chips">{r.kpis.map((k) => <a key={k} className="chip" href={`#/kpi-lineage/${k}`}>{k}</a>)}{!r.kpis.length && <span className="muted small">List report (attributes only)</span>}</div>
        <h4>Dimensions ({r.dimensions.length})</h4>
        <div className="chips">{r.dimensions.map((k) => <span key={k} className="chip">{k}</span>)}</div>
        {r.filters.length > 0 && (<><h4>Filters</h4>{r.filters.map((f, i) => (
          <div key={i} className={`small mono ${f.defect ? 'bad-t' : ''}`}>{f.expression}{f.defect && ` — ${f.reason}`}</div>))}</>)}
      </div>
      <div>
        <h4>Duplicate group {r.cluster}</h4>
        <table className="tbl compact">
          <thead><tr><th>Report</th><th>Folder</th><th className="r">Sim.</th><th className="r">Runs/day</th><th>Last run</th><th>Disposition</th></tr></thead>
          <tbody>{members.map((m) => (
            <tr key={m.report}><td className="small">{m.report}{m.report === r.canonical && <span className="pill good tiny">canonical</span>}</td><td className="small">{m.folder}</td>
              <td className="r small">{m.similarity}</td><td className="r small">{fmt(m.runs_per_day)}</td><td className="small">{m.last_run}</td><td><Disp value={m.disposition} /></td></tr>))}</tbody>
        </table>
        <h4>Decision</h4>
        <div className="btn-group">
          {DISPS.map((d) => <button key={d} className={`btn ${r.decision?.disposition === d ? `sel-${d.toLowerCase()}` : ''}`} onClick={() => onDecide(r, d, comment, d === 'Consolidate' ? (target || r.target) : null)}>{d}</button>)}
          {r.decision && <button className="btn ghost" onClick={() => onDecide(r, null, '')}>Use recommendation</button>}
        </div>
        <div className="form" style={{ marginTop: 8 }}>
          <label>Consolidate into
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">{r.target ? `${r.target} (recommended)` : '(choose a report)'}</option>
              {targets.map((t) => <option key={t.report} value={t.report}>{t.report}</option>)}
            </select></label>
          <label>Comment<input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why this decision (kept in the audit trail)" /></label>
        </div>
        {r.decision && <div className="small muted">Decided {r.decision.disposition} by {r.decision.reviewer} · {new Date(r.decision.time).toLocaleString()}{r.decision.comment && ` — ${r.decision.comment}`}</div>}
        {r.disposition === 'Consolidate' && r.target && byReport[r.target] && <div className="small" style={{ marginTop: 6 }}>Redirect users, bookmarks and schedules to <b>{r.target}</b> ({byReport[r.target].disposition}).</div>}
      </div>
    </div>
  )
}
