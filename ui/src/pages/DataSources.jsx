import React, { useMemo, useState } from 'react'
import { api } from '../api'
import { Kpi, Loading, RerunBanner, SearchBox, Section, downloadCsv, useApi } from '../components'

const SCOPES = ['Include', 'Review', 'Exclude']
const short = (p) => (p || '').replace(/^Energy_|_Package$/g, '')

export default function DataSources() {
  const { data, error, loading, reload, setData } = useApi('/api/sources')
  const [db, setDb] = useState('')
  const [q, setQ] = useState('')
  const [onlyReview, setOnlyReview] = useState(false)
  const [open, setOpen] = useState(null)

  const tables = useMemo(() => (data ? data.tables.filter((t) => (!db || t.database === db) && (!onlyReview || t.review_only || t.scope === 'Review')
    && (!q || `${t.id} ${t.entities.join(' ')} ${t.kpis.join(' ')} ${t.columns.map((c) => c.column).join(' ')}`.toLowerCase().includes(q.toLowerCase()))) : []), [data, db, q, onlyReview])
  const grouped = useMemo(() => {
    const out = {}
    tables.forEach((t) => { ((out[t.database] = out[t.database] || {})[t.schema] = out[t.database][t.schema] || []).push(t) })
    return out
  }, [tables])
  const decide = async (t, scope) => {
    const r = await api.post(`/api/sources/${encodeURIComponent(t.id)}`, { scope })
    setData({ ...data, tables: data.tables.map((x) => (x.id === t.id ? { ...x, ...r } : x)), pending_rerun: true })
  }
  const exportCsv = () => downloadCsv('data_sources_in_scope.csv', data.tables.map((t) => ({
    database: t.database, vendor: t.vendor, schema: t.schema, table: t.table, object_type: t.object_type, basis: t.basis,
    columns: t.columns.map((c) => c.column), keep_reports: t.keep_reports.length, review_reports: t.review_reports.length,
    review_only: t.review_only, scope: t.scope, kpis: t.kpis, landed_as: t.landed, core_objects: t.core })))

  return (
    <Loading error={error} loading={loading}>
      {data && (
        <div>
          <h1>4. Databases, schemas &amp; tables in scope</h1>
          <p className="lede">Every database, schema and table/view read by reports that survive rationalization: <b>Keep</b> and <b>Review</b>. Objects used only by Review reports are flagged; decide whether they stay in the migration scope. Columns show which Cognos item reads them and how many Keep and Review reports depend on each.</p>
          <RerunBanner pending={data.pending_rerun} onDone={reload} />
          <div className="kpis">
            <Kpi label="Databases" value={data.databases.length} />
            <Kpi label="Schemas" value={new Set(data.tables.map((t) => `${t.database}.${t.schema}`)).size} />
            <Kpi label="Tables / views" value={data.tables.length} sub={`${data.tables.filter((t) => t.confirmed).length} confirmed in FM`} />
            <Kpi label="Used only by Review reports" value={data.tables.filter((t) => t.review_only).length} tone="warn" />
            <Kpi label="Excluded by decision" value={data.tables.filter((t) => t.scope === 'Exclude').length} tone="bad" />
            <Kpi label="Reports in scope" value={data.scope_reports.Keep + data.scope_reports.Review} sub={`${data.scope_reports.Keep} Keep · ${data.scope_reports.Review} Review`} />
          </div>
          <Section title="Databases">
            <table className="tbl compact">
              <thead><tr><th>Database</th><th>Vendor</th><th>Schemas</th><th className="r">Tables / views</th><th className="r">Review-only</th></tr></thead>
              <tbody>{data.databases.map((d) => (
                <tr key={d.database} className={db === d.database ? 'sel' : ''} style={{ cursor: 'pointer' }} onClick={() => setDb(db === d.database ? '' : d.database)}>
                  <td><b>{d.database}</b></td><td className="small">{d.vendor}</td><td className="small">{d.schemas.join(', ')}</td>
                  <td className="r">{d.tables}</td><td className="r">{d.review_only ? <span className="pill warn">{d.review_only}</span> : 0}</td></tr>))}</tbody>
            </table>
            <div className="small muted">ENERGY_DW is the Oracle warehouse the Framework Manager model queries (schema and tables confirmed from the FM physical layer). Other databases come from the package-to-source mapping; their schemas and tables are inferred from report usage and must be confirmed with a source catalog.</div>
          </Section>
          <Section title={`${tables.length} tables / views`} actions={<div className="row gap wrap">
            <SearchBox value={q} onChange={setQ} placeholder="Table, column, KPI…" />
            <label className="small"><input type="checkbox" checked={onlyReview} onChange={(e) => setOnlyReview(e.target.checked)} /> Review items only</label>
            <button className="btn" onClick={exportCsv}>Export CSV</button>
          </div>}>
            {Object.entries(grouped).map(([dbn, schemas]) => Object.entries(schemas).map(([sch, ts]) => (
              <div key={`${dbn}.${sch}`} style={{ marginBottom: 14 }}>
                <h4>{dbn} › {sch}</h4>
                <table className="tbl">
                  <thead><tr><th>Table / view</th><th>Type</th><th>Cognos entities</th><th className="r">Columns</th><th className="r">Keep rpts</th><th className="r">Review rpts</th><th>Landed as</th><th>Scope</th></tr></thead>
                  <tbody>{ts.map((t) => (
                    <React.Fragment key={t.id}>
                      <tr className={open === t.id ? 'sel' : ''} style={{ cursor: 'pointer' }} onClick={() => setOpen(open === t.id ? null : t.id)}>
                        <td><b className="mono">{t.table}</b>{t.review_only && <span className="pill warn tiny">review only</span>}{!t.confirmed && <span className="pill tiny">inferred</span>}</td>
                        <td className="small">{t.object_type}</td><td className="small">{t.entities.join(', ')}</td>
                        <td className="r">{t.columns.length}</td><td className="r">{t.keep_reports.length}</td>
                        <td className="r">{t.review_reports.length ? <span className="pill warn">{t.review_reports.length}</span> : 0}</td>
                        <td className="mono tiny">{t.landed.join(', ')}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <select value={t.scope} onChange={(e) => decide(t, e.target.value)}>{SCOPES.map((s) => <option key={s}>{s}</option>)}</select>
                          {t.decision && <div className="tiny muted">decided</div>}
                        </td>
                      </tr>
                      {open === t.id && (
                        <tr className="detail"><td colSpan="8">
                          <div className="detail-grid">
                            <div>
                              <h4>Columns used</h4>
                              <table className="tbl compact">
                                <thead><tr><th>Column</th><th>Cognos item</th><th>Kind</th><th className="r">Keep</th><th className="r">Review</th></tr></thead>
                                <tbody>{t.columns.map((c) => (
                                  <tr key={c.column}><td className="mono tiny">{c.column}{c.review_only && <span className="pill warn tiny">review only</span>}</td>
                                    <td className="small">{c.kind === 'measure' ? <a href={`#/kpi-lineage/${c.item}`}>{c.item}</a> : c.item}</td><td className="small">{c.kind}</td>
                                    <td className="r small">{c.keep}</td><td className="r small">{c.review}</td></tr>))}</tbody>
                              </table>
                              <div className="small muted">Basis: {t.basis}. Packages: {t.packages.map(short).join(', ')}. System of record: {t.systems_of_record.join(', ') || '–'}. CORE objects: {t.core.join(', ') || '–'}.</div>
                            </div>
                            <div>
                              <h4>Review reports ({t.review_reports.length})</h4>
                              <div className="chips">{t.review_reports.map((r) => <a key={r} className="chip" href={`#/rationalization/${r}`}>{r}</a>)}</div>
                              <h4>Keep reports ({t.keep_reports.length})</h4>
                              <div className="chips">{t.keep_reports.map((r) => <a key={r} className="chip" href={`#/rationalization/${r}`}>{r}</a>)}</div>
                              {t.kpis.length > 0 && (<><h4>KPIs</h4><div className="chips">{t.kpis.map((k) => <a key={k} className="chip" href={`#/kpi-lineage/${k}`}>{k}</a>)}</div></>)}
                            </div>
                          </div>
                        </td></tr>)}
                    </React.Fragment>))}</tbody>
                </table>
              </div>)))}
          </Section>
        </div>
      )}
    </Loading>
  )
}
