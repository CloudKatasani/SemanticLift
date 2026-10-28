import React, { useMemo, useState } from 'react'
import { api } from '../api'
import { Loading, SearchBox, Section, Sev, Tabs, useApi } from '../components'

const STATUSES = ['open', 'accepted', 'resolved', 'wont_fix']

export default function Findings() {
  const { data, error, loading, setData } = useApi('/api/findings')
  const [tab, setTab] = useState('register')
  const [q, setQ] = useState('')
  const [code, setCode] = useState('')
  const [sev, setSev] = useState('')
  const [status, setStatus] = useState('')
  const [open, setOpen] = useState(null)

  const codes = useMemo(() => data ? [...new Set(data.findings.map((f) => f.code))].sort((a, b) => +a.slice(1) - +b.slice(1)) : [], [data])
  const rows = data ? data.findings.filter((f) => (!code || f.code === code) && (!sev || f.severity === sev) && (!status || f.status === status)
    && (!q || `${f.title} ${f.object} ${f.evidence} ${f.owner}`.toLowerCase().includes(q.toLowerCase()))) : []

  const update = async (f, patch) => {
    const r = await api.patch(`/api/findings/${f.id}`, patch)
    setData({ ...data, findings: data.findings.map((x) => (x.id === f.id ? { ...x, ...r } : x)) })
  }
  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>Findings</h1>
          <p className="lede">Every finding carries evidence, an owner and a resolution. Owner and status changes persist across re-runs. Blocking findings stop deployment.</p>
          <div className="code-strip">
            {codes.map((c) => {
              const fs = data.findings.filter((f) => f.code === c)
              const worst = ['high', 'medium', 'low', 'info'].find((s) => fs.some((f) => f.severity === s))
              return <button key={c} className={`code-chip sev-b-${worst} ${code === c ? 'on' : ''}`} onClick={() => setCode(code === c ? '' : c)}>{c}<b>{fs.length}</b></button>
            })}
          </div>
          <Tabs value={tab} onChange={setTab} tabs={[{ key: 'register', label: 'Register', count: data.findings.length },
            { key: 'numbers', label: 'Numbers that will change', count: data.numbers_that_change.length },
            { key: 'validation', label: 'Validation rules', count: data.validation.length }]} />
          {tab === 'register' && (
            <Section title={`${rows.length} findings`} actions={<div className="row gap">
              <SearchBox value={q} onChange={setQ} />
              <select value={sev} onChange={(e) => setSev(e.target.value)}><option value="">All severities</option>{['high', 'medium', 'low', 'info'].map((s) => <option key={s}>{s}</option>)}</select>
              <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
              <a className="btn" href="/api/download/findings">Export findings.md</a>
            </div>}>
              <table className="tbl">
                <thead><tr><th>ID</th><th>Sev</th><th>Finding</th><th>Object</th><th>Owner</th><th>Status</th></tr></thead>
                <tbody>{rows.map((f) => (
                  <React.Fragment key={f.id}>
                    <tr className={open === f.id ? 'sel' : ''} onClick={() => setOpen(open === f.id ? null : f.id)}>
                      <td className="mono small">{f.id}{f.blocking && <span className="pill bad tiny">blocking</span>}</td><td><Sev value={f.severity} /></td>
                      <td>{f.title}</td><td className="small mono">{f.object}</td>
                      <td onClick={(e) => e.stopPropagation()}><input className="inline" defaultValue={f.owner} onBlur={(e) => e.target.value !== f.owner && update(f, { owner: e.target.value })} /></td>
                      <td onClick={(e) => e.stopPropagation()}><select value={f.status} onChange={(e) => update(f, { status: e.target.value })}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></td>
                    </tr>
                    {open === f.id && <tr className="detail"><td colSpan="6"><div><b>Evidence:</b> {f.evidence}</div><div><b>Resolution:</b> {f.resolution}</div></td></tr>}
                  </React.Fragment>))}</tbody>
              </table>
            </Section>)}
          {tab === 'numbers' && (
            <Section title="Reports whose numbers change after migration (F6)">
              <p className="muted small">Cognos reports apply <code>total</code> to semi- or non-additive measures. The semantic layer enforces the FM default aggregation, so these report totals will differ. Publish this list to report owners before cut-over.</p>
              <table className="tbl"><thead><tr><th>Report</th><th>Measure</th><th>Cognos</th><th>Semantic layer</th><th>Origin</th></tr></thead>
                <tbody>{data.numbers_that_change.map((r, i) => <tr key={i}><td>{r.report}</td><td className="mono">{r.measure}</td><td>{r.cognos}</td><td><b>{r.semantic}</b></td><td>{r.origin}</td></tr>)}</tbody></table>
            </Section>)}
          {tab === 'validation' && (
            <Section title="Validation rules (spec 8.3)">
              <table className="tbl"><thead><tr><th>Rule</th><th>Check</th><th>Result</th><th>Detail</th></tr></thead>
                <tbody>{data.validation.map((v) => (
                  <tr key={v.rule}><td>{v.rule}</td><td>{v.title}</td>
                    <td>{v.passed == null ? <span className="pill">per object</span> : v.passed ? <span className="pill good">pass</span> : <span className="pill bad">fail</span>}</td>
                    <td className="small">{v.detail}{v.failures.length ? `: ${v.failures.slice(0, 10).join(', ')}` : ''}</td></tr>))}</tbody></table>
            </Section>)}
        </div>
      )}
    </Loading>
  )
}
