import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Kpi, Section, Status, fmt, useApi } from '../components'

export default function Ingest({ onRun }) {
  const uploads = useApi('/api/uploads')
  const configs = useApi('/api/configs')
  const ingest = useApi('/api/ingest')
  const [config, setConfig] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [drag, setDrag] = useState(false)
  const input = useRef()

  useEffect(() => { if (configs.data && configs.data.length && !config) setConfig(configs.data[0]) }, [configs.data])

  const send = async (files) => {
    if (!files.length) return
    setBusy(true); setMsg(null)
    try { await api.upload(files, false); uploads.reload() } catch (e) { setMsg({ error: e.message }) }
    setBusy(false)
  }
  const run = async () => {
    setBusy(true); setMsg(null)
    try {
      const s = await api.post('/api/run', { config: config || null })
      setMsg({ ok: `Run ${s.run_id} complete: ${s.objects} objects, ${s.findings} findings in ${Object.values(s.timings).reduce((a, b) => a + b, 0).toFixed(1)}s` })
      ingest.reload(); onRun()
    } catch (e) { setMsg({ error: e.message }) }
    setBusy(false)
  }
  const clear = async () => { await api.del('/api/uploads'); uploads.reload() }

  const ing = ingest.data
  return (
    <div>
      <h1>1. Ingest</h1>
      <p className="lede">Upload a zip or the loose files of a Cognos estate export (FM projects, report specs, usage, package mapping, optional source catalog). Each file is auto-detected and routed to its adapter.</p>
      <div className="grid2">
        <Section title="Upload">
          <div className={drag ? 'drop active' : 'drop'}
               onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
               onDrop={(e) => { e.preventDefault(); setDrag(false); send([...e.dataTransfer.files]) }}
               onClick={() => input.current.click()}>
            <div className="drop-icon">⇪</div>
            <div>Drop files here or click to browse</div>
            <div className="muted small">.zip (nested zips supported), .xml, .cpf, .ns, .ds, .xlsx, .csv</div>
            <input ref={input} type="file" multiple hidden onChange={(e) => send([...e.target.files])} />
          </div>
          <table className="tbl compact">
            <thead><tr><th>Uploaded file</th><th className="r">Size</th></tr></thead>
            <tbody>
              {(uploads.data || []).map((u) => <tr key={u.name}><td>{u.name}</td><td className="r">{fmt(u.size / 1024, 1)} KB</td></tr>)}
              {uploads.data && !uploads.data.length && <tr><td colSpan="2" className="muted">Nothing uploaded yet</td></tr>}
            </tbody>
          </table>
          <div className="row gap">
            <label>Estate configuration&nbsp;
              <select value={config} onChange={(e) => setConfig(e.target.value)}>
                <option value="">(defaults)</option>
                {(configs.data || []).map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
            <button className="btn primary" disabled={busy || !(uploads.data || []).length} onClick={run}>{busy ? 'Working…' : 'Run pipeline'}</button>
            <button className="btn" disabled={busy} onClick={clear}>Clear uploads</button>
          </div>
          {msg && <div className={msg.error ? 'error' : 'ok'}>{msg.error || msg.ok}</div>}
        </Section>
        {ing && (
          <Section title="Ingest summary">
            <div className="kpis">
              <Kpi label="Reports" value={fmt(ing.counts.reports)} />
              <Kpi label="Data items" value={fmt(ing.counts.report_items)} />
              <Kpi label="Filters" value={fmt(ing.counts.filters)} />
              <Kpi label="FM entities" value={ing.counts.fm_entities} />
              <Kpi label="Security rules" value={ing.counts.security_rules} />
              <Kpi label="Source systems" value={ing.counts.source_systems} />
            </div>
            <h4>Stated vs actual counts</h4>
            <table className="tbl compact">
              <thead><tr><th>Check</th><th className="r">Stated</th><th className="r">Actual</th><th /></tr></thead>
              <tbody>{ing.reconciliation.map((c) => (
                <tr key={c.check}><td>{c.check}</td><td className="r">{c.stated}</td><td className="r">{c.actual}</td>
                  <td>{c.ok ? <span className="pill good">ok</span> : <span className="pill bad">mismatch</span>}</td></tr>))}</tbody>
            </table>
            <div className="muted small">Usage join: {ing.usage_join.matched} of {ing.usage_join.usage_rows} usage rows matched to reports; {ing.usage_join.reports_without_usage?.length || 0} reports without usage.</div>
          </Section>
        )}
      </div>
      {ing && (
        <Section title={`Detected files (${ing.files.length})`}>
          <table className="tbl">
            <thead><tr><th>File</th><th>Adapter</th><th>Status</th><th className="r">Records</th><th className="r">Size</th><th>Warnings</th></tr></thead>
            <tbody>{ing.files.map((f) => (
              <tr key={f.path}><td className="mono small">{f.path}</td><td><span className="tag">{f.adapter}</span></td>
                <td><Status value={f.status} /></td><td className="r">{fmt(f.records)}</td><td className="r">{fmt(f.size / 1024, 1)} KB</td>
                <td className="small">{f.warnings.join('; ')}</td></tr>))}</tbody>
          </table>
        </Section>
      )}
    </div>
  )
}
