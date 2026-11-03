import React, { useEffect, useRef, useState } from 'react'
import { api, isStatic } from '../api'
import { Kpi, Section, Status, fmt, useApi } from '../components'

const remember = (k, v) => { try { if (v != null) localStorage.setItem(k, v) } catch { /* private mode */ } }
const recall = (k, d) => { try { return localStorage.getItem(k) || d } catch { return d } }
const TASKS = [['rationalization', 'Report rationalization review', 'Its own Keep / Review / Consolidate / Retire per report group, next to the rules'],
  ['products', 'Data product recommendations', 'Names, owners, boundaries, semantic-view advice, risks and new product opportunities']]

function aiLine(ai) {
  if (!ai) return ''
  if (ai.status === 'failed' && ai.error) return ` AI review failed: ${ai.error}`
  const r = ai.tasks?.rationalization, p = ai.tasks?.products
  const parts = []
  if (r) parts.push(`${r.reviewed} report groups reviewed (${r.disagree} differ from the rules)${r.failed_batches ? `, ${r.failed_batches} batch(es) failed` : ''}`)
  if (p) parts.push(p.status === 'failed' ? `product review failed: ${(p.errors || [])[0]}` : `${p.reviewed} data products reviewed`)
  const u = ai.usage ? ` · ${fmt(ai.usage.requests)} requests, ${fmt(ai.usage.input_tokens)} input / ${fmt(ai.usage.output_tokens)} output tokens` : ''
  return ` AI review (${ai.provider_label || ai.provider}, ${ai.model}): ${parts.join('; ')}${u}.`
}

export default function Ingest({ onRun }) {
  const uploads = useApi('/api/uploads')
  const configs = useApi('/api/configs')
  const ingest = useApi('/api/ingest')
  const [providers, setProviders] = useState(null)
  const [config, setConfig] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [drag, setDrag] = useState(false)
  const [mode, setMode] = useState(recall('semlift_ai_mode', 'rules'))
  const [provider, setProvider] = useState(recall('semlift_ai_provider', 'anthropic'))
  const [model, setModel] = useState(recall('semlift_ai_model', ''))
  const [customModel, setCustomModel] = useState('')
  const [baseUrl, setBaseUrl] = useState(recall('semlift_ai_base_url', ''))
  const [apiKey, setApiKey] = useState('')
  const [useServerKey, setUseServerKey] = useState(false)
  const [tasks, setTasks] = useState(['rationalization', 'products'])
  const [consent, setConsent] = useState(false)
  const input = useRef()

  useEffect(() => { if (configs.data && configs.data.length && !config) setConfig(configs.data[0]) }, [configs.data])
  useEffect(() => { if (!isStatic) api.get('/api/ai/providers').then(setProviders).catch(() => setProviders(null)) }, [])
  const prov = providers?.[provider]
  useEffect(() => {
    if (!prov) return
    if (prov.models.length && !prov.models.find((m) => m.id === model) && model !== '__other') setModel(prov.default_model)
    if (!prov.models.length) setModel('__other')
    setUseServerKey(prov.server_key)
  }, [provider, providers])

  const send = async (files) => {
    if (!files.length) return
    setBusy(true); setMsg(null)
    try { await api.upload(files, false); uploads.reload() } catch (e) { setMsg({ error: e.message }) }
    setBusy(false)
  }
  const modelId = model === '__other' ? customModel.trim() : model
  const aiSettings = () => ({ provider, model: modelId || null, api_key: useServerKey ? null : apiKey.trim() || null,
    base_url: prov?.base_url ? baseUrl.trim() : null, tasks })
  const aiProblem = mode === 'ai' && (!consent ? 'Confirm what is sent to the AI provider.'
    : !tasks.length ? 'Choose at least one AI task.'
      : !modelId ? 'Choose or enter a model.'
        : !useServerKey && !apiKey.trim() ? 'Enter an API key.'
          : prov?.base_url && !baseUrl.trim() ? 'Enter the endpoint base URL.' : null)
  const keepChoices = () => {
    remember('semlift_ai_mode', mode); remember('semlift_ai_provider', provider)
    remember('semlift_ai_model', model); if (prov?.base_url) remember('semlift_ai_base_url', baseUrl)
  }
  const run = async () => {
    setBusy(true); setMsg(null); keepChoices()
    try {
      const body = { config: config || null, ai: mode === 'ai' ? aiSettings() : null }
      const s = await api.runJob('run', body, (j) => setMsg({ info: `Run ${j.status}…${mode === 'ai' ? ' The AI review runs after the pipeline and can take a few minutes.' : ''} You can keep working; this page updates when it finishes.` }))
      const warn = (s.config_warnings || []).length ? ` Configuration warnings: ${s.config_warnings.join('; ')}.` : ''
      setMsg({ [s.ai?.status === 'failed' ? 'warn' : 'ok']: `Run ${s.run_id} complete: ${s.objects} objects, ${s.findings} findings in ${Object.values(s.timings).reduce((a, b) => a + b, 0).toFixed(1)}s.${aiLine(s.ai)} Continue with 1. Report rationalization.${warn}` })
      setApiKey(''); ingest.reload(); onRun()
    } catch (e) { setMsg({ error: e.message }) }
    setBusy(false)
  }
  const runAiOnly = async () => {
    setBusy(true); setMsg(null); keepChoices()
    try {
      const s = await api.runJob('ai', aiSettings(), () => setMsg({ info: 'AI review running… this can take a few minutes.' }))
      setMsg({ [s.ai?.status === 'failed' ? 'warn' : 'ok']: aiLine(s.ai).trim() })
      setApiKey(''); onRun()
    } catch (e) { setMsg({ error: e.message }) }
    setBusy(false)
  }
  const clear = async () => { await api.del('/api/uploads'); uploads.reload() }

  const ing = ingest.data
  const gov = ing?.governance
  const hasRun = !!ing
  return (
    <div>
      <h1>Upload &amp; run</h1>
      <p className="lede">Upload a zip or the loose files of a Cognos estate export (FM projects, report specs, usage, package mapping, optional source catalog), plus optional business and technical metadata from your data governance tool. Each file is auto-detected and routed to its adapter. See the <a href="#/export-guide">Cognos export guide</a> for what to export.</p>
      <div className="grid2">
        <Section title="1. Upload">
          <div className={drag ? 'drop active' : 'drop'}
               onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
               onDrop={(e) => { e.preventDefault(); setDrag(false); send([...e.dataTransfer.files]) }}
               onClick={() => input.current.click()}>
            <div className="drop-icon">⇪</div>
            <div>Drop files here or click to browse</div>
            <div className="muted small">.zip (nested zips supported), .xml, .cpf, .ns, .ds, .xlsx, .csv, .json</div>
            <input ref={input} type="file" multiple hidden onChange={(e) => send([...e.target.files])} />
          </div>
          <div className="gov-hint">
            <b>Governance metadata (optional).</b> Add asset exports from <b>Collibra</b>, <b>Atlan</b> or <b>Alation</b> (CSV, XLSX or JSON): tables, columns, business terms, domains, owners, stewards, classifications and certification. SemanticLift matches them to the estate and uses them for descriptions, glossary synonyms, sensitivity tags, data-product owners and product recommendations, with or without AI.
          </div>
          <table className="tbl compact">
            <thead><tr><th>Uploaded file</th><th className="r">Size</th></tr></thead>
            <tbody>
              {(uploads.data || []).map((u) => <tr key={u.name}><td>{u.name}</td><td className="r">{fmt(u.size / 1024, 1)} KB</td></tr>)}
              {uploads.data && !uploads.data.length && <tr><td colSpan="2" className="muted">Nothing uploaded yet</td></tr>}
            </tbody>
          </table>
          <div className="row gap wrap">
            <label>Estate configuration&nbsp;
              <select value={config} onChange={(e) => setConfig(e.target.value)}>
                <option value="">(defaults)</option>
                {(configs.data || []).map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
            <button className="btn" disabled={busy} onClick={clear}>Clear uploads</button>
          </div>
        </Section>

        <Section title="2. Choose how to run">
          <div className="run-modes">
            <label className={`run-mode ${mode === 'rules' ? 'on' : ''}`}>
              <input type="radio" name="mode" checked={mode === 'rules'} onChange={() => setMode('rules')} />
              <div><b>Run without AI</b><span>Rule-based analysis only. Deterministic, offline, nothing leaves the server.</span></div>
            </label>
            <label className={`run-mode ${mode === 'ai' ? 'on' : ''} ${!providers ? 'disabled' : ''}`}>
              <input type="radio" name="mode" checked={mode === 'ai'} disabled={!providers} onChange={() => setMode('ai')} />
              <div><b>Run with AI</b><span>The rules run first; then an AI model reviews the rationalization and the data products, using governance metadata when uploaded. AI suggests, people decide.</span></div>
            </label>
          </div>
          {mode === 'ai' && providers && (
            <div className="form ai-form">
              <label>Provider
                <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                  {Object.entries(providers).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
                </select>
                <span className="tiny muted">{prov?.hint}</span>
              </label>
              <label>Model
                {prov?.models.length > 0 && (
                  <select value={model} onChange={(e) => setModel(e.target.value)}>
                    {prov.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                    <option value="__other">Other model id…</option>
                  </select>)}
                {model === '__other' && <input value={customModel} onChange={(e) => setCustomModel(e.target.value)} placeholder="Model id, exactly as your provider names it" />}
              </label>
              {prov?.base_url && (
                <label>Endpoint base URL<input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://your-gateway.example.com/v1" /></label>)}
              <label>API key
                {prov?.server_key && <span className="small"><input type="checkbox" checked={useServerKey} onChange={(e) => setUseServerKey(e.target.checked)} /> Use the key configured on the server</span>}
                {!useServerKey && <input type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="Used for this run only; never stored" />}
              </label>
              <fieldset className="ai-tasks"><legend>AI tasks</legend>
                {TASKS.map(([k, l, d]) => (
                  <label key={k} className="small"><input type="checkbox" checked={tasks.includes(k)} onChange={(e) => setTasks(e.target.checked ? [...tasks, k] : tasks.filter((t) => t !== k))} /> <b>{l}</b><span className="tiny muted"> {d}</span></label>))}
              </fieldset>
              <div className="note small">
                <b>What is sent to {prov?.label}:</b> report names and descriptions, KPI, dimension and filter expressions, usage figures, the rule-based outcome and its reasons, data-product structure and governance descriptions, owners and classifications. No business data. The key is used for this run only and is not stored, logged or written to the audit trail; the audit trail records the provider and model.
                <label className="small" style={{ display: 'block', marginTop: 6 }}><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> I am allowed to send this client's metadata to this provider.</label>
              </div>
            </div>)}
          <div className="row gap wrap" style={{ marginTop: 12 }}>
            <button className="btn primary" disabled={busy || !(uploads.data || []).length || !!aiProblem} onClick={run}>
              {busy ? 'Working…' : mode === 'ai' ? 'Run pipeline with AI' : 'Run pipeline'}</button>
            {mode === 'ai' && hasRun && <button className="btn" disabled={busy || !!aiProblem} onClick={runAiOnly} title="Keep the current run and only (re)run the AI review">Run AI review only</button>}
            {aiProblem && <span className="small muted">{aiProblem}</span>}
          </div>
          {msg && <div className={msg.error ? 'error' : msg.info ? 'banner' : msg.warn ? 'banner' : 'ok'}>{msg.error || msg.info || msg.warn || msg.ok}</div>}
        </Section>
      </div>

      {ing && (
        <div className="grid2">
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
          <Section title="Governance metadata">
            {!gov?.loaded ? <div className="muted small">No governance export in this run. Upload Collibra, Atlan or Alation asset exports to enrich descriptions, owners, classifications and data-product recommendations.</div> : (
              <>
                <div className="kpis">
                  <Kpi label="Assets read" value={fmt(gov.assets)} sub={Object.entries(gov.tools).map(([t, n]) => `${t} ${n}`).join(' · ')} />
                  <Kpi label="Tables matched" value={gov.matched.tables} sub={gov.unmatched.tables ? `${gov.unmatched.tables} unmatched` : 'all matched'} />
                  <Kpi label="Columns matched" value={gov.matched.columns} sub={gov.unmatched.columns ? `${gov.unmatched.columns} unmatched` : 'all matched'} />
                  <Kpi label="Business terms matched" value={gov.matched.terms} sub={gov.unmatched.terms ? `${gov.unmatched.terms} unmatched` : 'all matched'} />
                </div>
                <div className="small">Domains: {gov.domains.join(', ') || '–'}. Enriched {gov.entities_matched} entities and {gov.items_matched} columns or KPIs.</div>
                {gov.unmatched.examples.length > 0 && (
                  <details className="small" style={{ marginTop: 6 }}><summary>Unmatched assets ({gov.unmatched.examples.length})</summary>
                    <ul className="guide-list">{gov.unmatched.examples.map((u, i) => <li key={i}><span className="tag">{u.type}</span> <span className="mono tiny">{u.name}</span> <span className="muted tiny">{u.tool}</span></li>)}</ul>
                  </details>)}
              </>)}
          </Section>
        </div>
      )}
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
