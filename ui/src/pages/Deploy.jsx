import React, { useState } from 'react'
import { api } from '../api'
import { Kpi, Loading, Section, Status, useApi } from '../components'

export default function Deploy() {
  const { data, error, loading, reload } = useApi('/api/deploy')
  const diff = useApi('/api/diff')
  const products = useApi('/api/products')
  const [branch, setBranch] = useState('')
  const [remote, setRemote] = useState('')
  const [push, setPush] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const deploy = async () => {
    setBusy(true); setMsg(null)
    try {
      if (remote) await api.put('/api/settings', { git_remote: remote })
      const r = await api.post('/api/deploy', { branch: branch || null, push })
      setMsg({ ok: `Committed ${r.deployed.length} objects to ${r.branch} @ ${r.commit.slice(0, 10)}${r.pushed ? ' and pushed' : ''}` })
      reload()
    } catch (e) { setMsg({ error: e.message }) }
    setBusy(false)
  }
  const parity = async () => {
    setBusy(true)
    try { await api.post('/api/parity'); reload() } catch (e) { setMsg({ error: e.message }) }
    setBusy(false)
  }
  const last = data?.deploy?.last
  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>9. Deploy & validate</h1>
          <p className="lede">Approved objects are committed to a Git branch with a CI pipeline (schemachange or Snowflake CLI). The UI never deploys directly to an account; deployment follows the same controls as any other code change.</p>
          <div className="kpis">
            {Object.entries(data.review_summary).map(([k, v]) => <Kpi key={k} label={k} value={v} tone={k === 'approved' ? 'good' : k === 'stub' ? 'bad' : ''} />)}
            <Kpi label="Environment" value={data.environment} />
          </div>
          <div className="grid2">
            <Section title="Git deployment">
              <div className="form">
                <label>Branch<input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="semlift/design-<run>" /></label>
                <label>Remote (optional)<input value={remote} onChange={(e) => setRemote(e.target.value)} placeholder={data.settings?.git_remote || 'git@github.com:org/semantic-layer.git'} /></label>
                <label className="small"><input type="checkbox" checked={push} onChange={(e) => setPush(e.target.checked)} /> Push branch to remote (CI then validates and deploys)</label>
                <button className="btn primary" disabled={busy} onClick={deploy}>Commit approved objects</button>
              </div>
              {msg && <div className={msg.error ? 'error' : 'ok'}>{msg.error || msg.ok}</div>}
              {last && (
                <div className="small">
                  <h4>Last deployment</h4>
                  <div>Branch <b>{last.branch}</b> · commit <span className="mono">{last.commit?.slice(0, 12)}</span> · {last.pushed ? 'pushed' : 'local only'} · {new Date(last.time).toLocaleString()}</div>
                  <div>{last.deployed.length} objects written; {last.skipped.length} skipped</div>
                  {last.skipped.length > 0 && <ul>{last.skipped.slice(0, 12).map((s) => <li key={s.id}><span className="mono">{s.id}</span>: {s.reason}</li>)}</ul>}
                  <h4>Deployment log</h4>
                  <pre className="code small">{last.log.map((l) => `$ ${l.cmd}  [rc=${l.rc}]\n${l.out}`).join('\n')}</pre>
                </div>)}
            </Section>
            <Section title="Parity tests" actions={<button className="btn" disabled={busy} onClick={parity}>Run parity</button>}>
              <p className="small muted">Cognos-equivalent SQL vs semantic view for the top reports by runs/day; totals must reconcile within ±0.5%, excluding the F6 aggregation corrections.</p>
              <table className="tbl compact"><thead><tr><th>Report</th><th>Semantic view</th><th>Expected change</th><th>Status</th></tr></thead>
                <tbody>{(data.parity?.results || []).map((r) => (
                  <tr key={r.file}><td>{r.report}</td><td className="mono small">{r.semantic_view}</td><td className="small">{r.expected_changes?.join(', ')}</td>
                    <td title={typeof r.detail === 'string' ? r.detail : JSON.stringify(r.detail)}><Status value={r.status} /></td></tr>))}
                  {!(data.parity?.results || []).length && <tr><td colSpan="4" className="muted">Not run yet</td></tr>}</tbody></table>
            </Section>
          </div>
          <div className="grid2">
            <Section title="Changes since previous run (incremental re-run)">
              {diff.data && (diff.data.baseline ? <div className="muted">Baseline run – {diff.data.added.length} objects.</div> : (
                <div className="small">
                  <div className="row gap"><span className="chip">+ {diff.data.added.length} added</span><span className="chip">~ {diff.data.changed.length} changed</span><span className="chip">− {diff.data.removed.length} removed</span><span className="chip">{diff.data.unchanged} unchanged</span></div>
                  {['added', 'changed', 'removed'].map((k) => diff.data[k].length > 0 && <div key={k}><b>{k}</b>: <span className="mono">{diff.data[k].join(', ')}</span></div>)}
                </div>))}
            </Section>
            <Section title="Downloads">
              <div className="row gap wrap">
                <a className="btn primary" href="/api/download/package">Design package (.zip)</a>
                <a className="btn" href="/api/download/workbook">Design workbook (.xlsx)</a>
                <a className="btn" href="/api/download/findings">Findings (.md)</a>
              </div>
              <h4>Data products</h4>
              <table className="tbl compact"><thead><tr><th>Product</th><th>Semantic views</th><th>Outputs</th><th>Clusters</th></tr></thead>
                <tbody>{(products.data || []).map((p) => (
                  <tr key={p.key}><td><b>{p.name}</b><div className="mono tiny">{p.schema} · contracts/{p.slug}.yaml</div></td><td className="small">{p.semantic_views.join(', ')}</td>
                    <td className="small">{p.outputs.length}</td><td className="small">{p.clusters}</td></tr>))}</tbody></table>
            </Section>
          </div>
          {data.deploy?.history?.length > 0 && (
            <Section title="Deployment history">
              <table className="tbl compact"><thead><tr><th>Time</th><th>Branch</th><th>Commit</th><th>Pushed</th></tr></thead>
                <tbody>{data.deploy.history.slice().reverse().map((h, i) => <tr key={i}><td>{new Date(h.time).toLocaleString()}</td><td>{h.branch}</td><td className="mono">{h.commit?.slice(0, 12)}</td><td>{h.pushed ? 'yes' : 'no'}</td></tr>)}</tbody></table>
            </Section>)}
        </div>
      )}
    </Loading>
  )
}
