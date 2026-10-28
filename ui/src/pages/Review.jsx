import React, { useEffect, useMemo, useState } from 'react'
import { api, enc } from '../api'
import { Conf, Loading, SearchBox, Section, Status, Tabs, useApi } from '../components'

const LAYERS = [['all', 'All'], ['setup', 'Setup'], ['ref', 'REF'], ['sec', 'SEC'], ['core', 'CORE'], ['agg', 'AGG'], ['sem', 'SEM'], ['dp', 'DP']]

export default function Review({ arg }) {
  const { data, error, loading, reload, setData } = useApi('/api/objects')
  const [layer, setLayer] = useState('all')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [sel, setSel] = useState(arg || null)
  const [msg, setMsg] = useState(null)

  const rows = useMemo(() => data ? data.objects.filter((o) => (layer === 'all' || o.layer === layer) && (!status || o.status === status)
    && (!q || `${o.id} ${o.domain} ${o.comment}`.toLowerCase().includes(q.toLowerCase()))) : [], [data, layer, q, status])

  const approveAll = async () => {
    try { const r = await api.post('/api/approve-all'); setMsg({ ok: `${r.approved} objects approved (confidence ≥ threshold and SQL compiles)` }); reload() }
    catch (e) { setMsg({ error: e.message }) }
  }
  const onChange = (o) => setData({ ...data, objects: data.objects.map((x) => (x.id === o.id ? { ...x, ...o, edited: !!o.edited_ddl } : x)) })

  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>Design review</h1>
          <p className="lede">The human checkpoint nothing skips. Each proposed object shows the generated SQL beside the Cognos source it came from. Approve, edit or reject; decisions and edits persist across re-runs. Objects below 0.6 confidence cannot be auto-approved.</p>
          <div className="row gap wrap">
            {Object.entries(data.summary).map(([k, v]) => <span key={k} className="chip"><Status value={k} /> {v}</span>)}
            <button className="btn primary" onClick={approveAll}>Approve all eligible</button>
            {msg && <span className={msg.error ? 'error inline' : 'ok inline'}>{msg.error || msg.ok}</span>}
          </div>
          <Tabs value={layer} onChange={setLayer} tabs={LAYERS.map(([k, l]) => ({ key: k, label: l, count: k === 'all' ? data.objects.length : data.objects.filter((o) => o.layer === k).length }))} />
          <div className="review">
            <div className="card list">
              <div className="row gap pad-s">
                <SearchBox value={q} onChange={setQ} />
                <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option>{['proposed', 'stub', 'approved', 'edited', 'rejected'].map((s) => <option key={s}>{s}</option>)}</select>
              </div>
              <div className="scroll">
                {rows.map((o) => (
                  <div key={o.id} className={sel === o.id ? 'obj sel' : 'obj'} onClick={() => setSel(o.id)}>
                    <div className="obj-id mono">{o.id}</div>
                    <div className="row gap small"><span className="muted">{o.object_type}</span><Conf value={o.confidence} /><Status value={o.status} />
                      {o.compile?.status === 'failed' && <span className="pill bad tiny">compile</span>}
                      {o.edited && <span className="pill tiny">edited</span>}
                      {o.review?.changed_since_review && <span className="pill warn tiny">changed</span>}</div>
                  </div>))}
                {!rows.length && <div className="muted pad">No objects</div>}
              </div>
            </div>
            <div className="detail-pane">{sel ? <Detail id={sel} onChange={onChange} key={sel} /> : <div className="card muted pad">Select an object to review.</div>}</div>
          </div>
          <Suggestions />
        </div>
      )}
    </Loading>
  )
}

function Detail({ id, onChange }) {
  const { data, error, loading, setData } = useApi(`/api/objects/${enc(id)}`)
  const [ddl, setDdl] = useState('')
  const [editing, setEditing] = useState(false)
  const [ack, setAck] = useState(false)
  const [comment, setComment] = useState('')
  const [msg, setMsg] = useState(null)
  useEffect(() => { if (data) setDdl(data.edited_ddl || data.ddl) }, [data])

  const act = async (action) => {
    setMsg(null)
    try {
      const body = { action, comment, acknowledge_low_confidence: ack }
      if (action === 'edit') body.ddl = ddl
      const o = await api.post(`/api/objects/${enc(id)}/review`, body)
      setData({ ...data, ...o })
      onChange(o)
      setEditing(false)
      setMsg({ ok: `${action} recorded` })
    } catch (e) { setMsg({ error: e.message }) }
  }
  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div className="card">
          <div className="card-head"><h3 className="mono">{data.id}</h3><div className="row gap"><Conf value={data.confidence} /><Status value={data.status} /></div></div>
          <div className="meta-grid small">
            <div><b>Type</b> {data.object_type}</div><div><b>Domain</b> {data.domain || '–'}</div>
            <div><b>Owner</b> {data.owner}</div><div><b>Classification</b> {data.classification}</div>
            <div><b>Rules</b> {data.rule_ids.join(', ')}</div><div><b>Compile</b> <span className={data.compile?.status === 'failed' ? 'bad-t' : ''}>{data.compile?.status}</span> <span className="muted">{data.compile?.message}</span></div>
            <div className="span2"><b>Depends on</b> {data.depends_on.join(', ') || '–'}</div>
            {data.meta?.attached_to && <div className="span2"><b>Attached to</b> {data.meta.attached_to}</div>}
            {data.review && <div className="span2"><b>Review</b> {data.review.status} by {data.review.reviewer} {data.review.comment && `– ${data.review.comment}`} {data.review.changed_since_review && <span className="pill warn">generated SQL changed since review</span>}</div>}
          </div>
          <div className="sbs">
            <div>
              <h4>Cognos source</h4>
              <pre className="code cognos">{data.cognos_source || '(no direct Cognos construct – generated by design rule)'}{data.lineage.length ? `\n\n-- evidence\n${data.lineage.join('\n')}` : ''}</pre>
            </div>
            <div>
              <h4>Generated SQL {data.edited_ddl && <span className="pill tiny">edited</span>}</h4>
              {editing ? <textarea className="code edit" value={ddl} onChange={(e) => setDdl(e.target.value)} spellCheck="false" />
                : <pre className="code">{ddl}</pre>}
              {data.edit_compile && <div className="small muted">Edit compile check: {data.edit_compile.status} – {data.edit_compile.message}</div>}
            </div>
          </div>
          <div className="row gap wrap">
            <input className="search" placeholder="Review comment" value={comment} onChange={(e) => setComment(e.target.value)} />
            {data.confidence < 0.6 && <label className="small"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I acknowledge this inferred object's TODO source mappings</label>}
            <button className="btn primary" onClick={() => act('approve')}>Approve</button>
            {editing ? <button className="btn" onClick={() => act('edit')}>Save edit</button> : <button className="btn" onClick={() => setEditing(true)}>Edit</button>}
            <button className="btn danger" onClick={() => act('reject')}>Reject</button>
            <button className="btn ghost" onClick={() => act('reset')}>Reset</button>
          </div>
          {msg && <div className={msg.error ? 'error' : 'ok'}>{msg.error || msg.ok}</div>}
        </div>
      )}
    </Loading>
  )
}

function Suggestions() {
  const { data, setData } = useApi('/api/suggestions')
  const [show, setShow] = useState(false)
  const [q, setQ] = useState('')
  if (!data) return null
  const decide = async (s, status) => {
    const r = await api.post(`/api/suggestions/${s.id}`, { status })
    setData(data.map((x) => (x.id === s.id ? r : x)))
  }
  const rows = data.filter((s) => !q || s.target.toLowerCase().includes(q.toLowerCase()))
  return (
    <Section title={`LLM-assist suggestions (${data.filter((s) => s.status === 'suggested').length} pending)`} actions={<div className="row gap"><SearchBox value={q} onChange={setQ} /><button className="btn" onClick={() => setShow(!show)}>{show ? 'Hide' : 'Show'}</button></div>}>
      <p className="muted small">Descriptions and synonyms drafted by the configured provider are marked <i>suggested</i> until a steward accepts them; accepted text is applied to semantic views on the next run.</p>
      {show && <table className="tbl compact"><thead><tr><th>Target</th><th>Current</th><th>Suggested description</th><th>Synonyms</th><th>Status</th><th /></tr></thead>
        <tbody>{rows.slice(0, 300).map((s) => (
          <tr key={s.id}><td className="mono tiny">{s.target}</td><td className="small muted">{s.current_description}</td><td className="small">{s.description}</td>
            <td className="small">{s.synonyms.join(', ')}</td><td><Status value={s.status} /></td>
            <td className="nowrap"><button className="btn tiny" onClick={() => decide(s, 'accepted')}>Accept</button> <button className="btn tiny ghost" onClick={() => decide(s, 'rejected')}>Reject</button></td></tr>))}</tbody></table>}
    </Section>
  )
}
