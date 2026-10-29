import React, { useState } from 'react'
import { Loading, Section, downloadCsv, useApi } from '../components'

const PAGE = 200

export default function Audit() {
  const [action, setAction] = useState('')
  const [user, setUser] = useState('')
  const [limit, setLimit] = useState(PAGE)
  const qs = new URLSearchParams({ limit, ...(action ? { action } : {}), ...(user ? { user } : {}) })
  const { data, error, loading } = useApi(`/api/audit?${qs}`)
  const fmtDetail = (d) => Object.entries(d || {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ')
  const exportCsv = () => downloadCsv('audit_trail.csv', data.entries.map((e) => ({ time: e.time, user: e.user, action: e.action, target: e.target, detail: fmtDetail(e.detail) })))

  return (
    <div>
      <h1>Audit trail</h1>
      <p className="lede">Every change in this project, newest first: uploads, pipeline runs, report, KPI and source decisions, object reviews, findings, suggestions, deployments and settings. Entries are append-only and record the signed-in user, so the trail can be handed to the client's governance or audit team.</p>
      <Loading error={error} loading={loading && !data}>
        {data && (
          <Section title={`${data.total} entries`} actions={<div className="row gap wrap">
            <select value={action} onChange={(e) => { setAction(e.target.value); setLimit(PAGE) }}><option value="">All actions</option>{data.actions.map((a) => <option key={a}>{a}</option>)}</select>
            <select value={user} onChange={(e) => { setUser(e.target.value); setLimit(PAGE) }}><option value="">All users</option>{data.users.map((u) => <option key={u}>{u}</option>)}</select>
            <button className="btn" onClick={exportCsv}>Export CSV</button>
          </div>}>
            <table className="tbl compact">
              <thead><tr><th>Time (UTC)</th><th>User</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
              <tbody>{data.entries.map((e, i) => (
                <tr key={i}><td className="nowrap small">{e.time.replace('T', ' ').replace('+00:00', '')}</td><td className="small"><b>{e.user}</b></td>
                  <td><span className="tag">{e.action}</span></td><td className="mono tiny">{e.target}</td><td className="small">{fmtDetail(e.detail)}</td></tr>))}</tbody>
            </table>
            {!data.entries.length && <div className="muted pad">No entries match.</div>}
            {data.entries.length < data.total && <button className="btn" style={{ marginTop: 10 }} onClick={() => setLimit(limit + PAGE)}>Show more</button>}
          </Section>)}
      </Loading>
    </div>
  )
}
