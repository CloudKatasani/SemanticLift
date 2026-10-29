import React, { useState } from 'react'
import { downloadCsv } from '../components'

const INPUTS = [
  { n: 1, name: 'Report specifications', need: 'Required', from: 'Content Store', format: 'XML: one file per report named after the report, or one combined export', why: 'Report rationalization, KPIs, filters, lineage' },
  { n: 2, name: 'Report usage', need: 'Required', from: 'Audit database', format: 'XLSX or CSV, one row per report', why: 'Keep / Review / Consolidate / Retire decisions' },
  { n: 3, name: 'Package-to-source mapping', need: 'Required', from: 'Data source connections, package definitions', format: 'XLSX or CSV, one row per package or data module', why: 'Source scoping and landing (RAW) schemas' },
  { n: 4, name: 'Framework Manager project', need: 'Recommended', from: 'FM project folder', format: 'Zip of the project folder', why: 'Confirms tables, measure aggregation rules, relationships, security' },
  { n: 5, name: 'Security and prompt definitions', need: 'Recommended', from: 'FM security, parameter maps', format: 'XML', why: 'Row and column policies, prompt defaults' },
  { n: 6, name: 'Source catalog', need: 'Optional', from: 'Landed data platform', format: 'CSV of tables and columns', why: 'Raises confidence for items not in the FM model' },
]

const USAGE_COLS = [
  ['report_name', 'Required', 'Exact report name. Must match the report specification file name.'],
  ['runs_per_day', 'Required', 'Average runs per day over the look-back window (for example runs in the last 180 days ÷ 180). 0 for reports that never ran.'],
  ['last_run_date', 'Strongly recommended', 'Date of the most recent run. Accepted: 2026-10-01, 10/01/2026 or "Oct 1, 2026 12:00:00 AM".'],
  ['report_path', 'Strongly recommended', 'Full Content Store path, e.g. Team Content/Sales/Revenue by Region. Used as the second join key.'],
  ['package', 'Strongly recommended', 'Package the report is built on.'],
  ['folder_category', 'Strongly recommended', 'Active, Archive or Community (see below). Decides which copy of a duplicate is the main report.'],
  ['avg_duration_min', 'Recommended', 'Average run time in minutes. Weights demand for the aggregate planner.'],
  ['duplicate_group_id', 'Optional', 'Your own duplicate grouping, if you have one. If omitted, SemanticLift groups reports by similarity.'],
  ['report_type, query_name, column_count, similarity_score', 'Optional', 'Extra context shown on the rationalization page.'],
]

const AUDIT_SQL = `-- Report usage from the Cognos Audit database (report executions).
-- Table and column names below are those of COGIPF_RUNREPORT in common Cognos versions;
-- check them against your audit schema before running. Times are in milliseconds.
SELECT
    COGIPF_REPORTNAME                                   AS report_name,
    COGIPF_REPORTPATH                                   AS report_path,
    COGIPF_PACKAGE                                      AS package,
    CASE WHEN COGIPF_REPORTPATH LIKE '%My Folders%' THEN 'Community'
         WHEN UPPER(COGIPF_REPORTPATH) LIKE '%ARCHIVE%' THEN 'Archive'
         ELSE 'Active' END                              AS folder_category,
    COUNT(*) / 180.0                                    AS runs_per_day,
    MAX(CAST(COGIPF_LOCALTIMESTAMP AS DATE))            AS last_run_date,
    AVG(COGIPF_RUNTIME) / 60000.0                       AS avg_duration_min
FROM COGIPF_RUNREPORT
WHERE COGIPF_STATUS = 'Success'
  AND COGIPF_LOCALTIMESTAMP >= CURRENT_DATE - 180      -- date arithmetic differs by database
GROUP BY COGIPF_REPORTNAME, COGIPF_REPORTPATH, COGIPF_PACKAGE;

-- Then add every report from step 1 that is missing here with runs_per_day = 0
-- and its last known run (or blank): reports that never ran are the ones to retire.`

const CATALOG_SQL = `-- Example for Snowflake; most platforms expose the same INFORMATION_SCHEMA views.
SELECT c.table_catalog, c.table_schema, c.table_name, c.column_name, c.data_type, t.row_count
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_catalog = c.table_catalog AND t.table_schema = c.table_schema AND t.table_name = c.table_name
WHERE c.table_schema IN ('RAW_CRM', 'RAW_BILLING')     -- the landed schemas for your sources
ORDER BY 1, 2, 3, c.ordinal_position;`

const SPEC_EXAMPLE = `<report xmlns="http://developer.cognos.com/schemas/report/16.0/">
  <modelPath>/content/package[@name='Sales_Package']/model[@name='model']</modelPath>
  <queries>
    <query name="Query1">
      <selection>
        <dataItem name="Region"><expression>[Sales_Package].[Location].[Region]</expression></dataItem>
        <dataItem name="Revenue" aggregate="total"><expression>[Sales_Package].[Orders].[Revenue]</expression></dataItem>
      </selection>
      <detailFilters><detailFilter><filterExpression>[Sales_Package].[Date].[FiscalYear] = ?p_FiscalYear?</filterExpression></detailFilter></detailFilters>
    </query>
  </queries>
  ...layouts are ignored...
</report>`

const LAYOUT = `client_cognos_export.zip
├── Reports/                          one XML per report (file name = report name)
│   ├── Revenue_by_Region.xml
│   └── ...
├── FM/sales_fm_project.zip           the Framework Manager project folder, zipped (zips may be nested)
├── report_usage.xlsx                 step 2
├── package_source_mapping.xlsx       step 3
└── source_catalog.csv                step 6 (optional)`

function Code({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = () => { navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }) }
  return (
    <div className="code-wrap">
      <button className="btn tiny-btn" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
      <pre className="code">{text}</pre>
    </div>
  )
}

function Step({ n, title, need, children }) {
  return (
    <section className="card guide-step" id={`export-${n}`}>
      <div className="row gap" style={{ marginBottom: 6 }}>
        <span className="flow-n">{n}</span><h2 style={{ margin: 0 }}>{title}</h2>
        <span className={`pill ${need === 'Required' ? 'bad' : need === 'Recommended' ? 'warn' : ''}`}>{need}</span>
      </div>
      {children}
    </section>
  )
}

export default function ExportGuide() {
  const usageTemplate = () => downloadCsv('report_usage_template.csv', [{
    report_name: 'Revenue_by_Region', report_path: 'Team Content/Sales/Revenue_by_Region', package: 'Sales_Package', folder_category: 'Active',
    runs_per_day: 4.2, last_run_date: '2026-10-01', avg_duration_min: 2.5, duplicate_group_id: '', report_type: 'List' }])
  const mappingTemplate = () => downloadCsv('package_source_mapping_template.csv', [
    { 'FM Package/Data Module': 'Sales_Package', 'FM Package': 'Sales_Package', 'Source Database/System': 'Oracle - SALES_DW' },
    { 'FM Package/Data Module': 'Sales_Orders_DM', 'FM Package': 'Sales_Package', 'Source Database/System': 'Oracle - SALES_DW' }])
  const catalogTemplate = () => downloadCsv('source_catalog_template.csv', [
    { table_catalog: 'SALES_DW', table_schema: 'RAW_SALES', table_name: 'ORDERS', column_name: 'ORDER_ID', data_type: 'NUMBER', row_count: 2500000 }])

  return (
    <div className="guide">
      <h1>Cognos export guide</h1>
      <p className="lede">For Cognos administrators. SemanticLift needs the <b>metadata</b> of the BI estate: report definitions, usage statistics, the Framework Manager model and where each package's data comes from. It needs <b>no business data</b>. Most estates can be exported in a few hours. Put everything in one zip and upload it on <a href="#/ingest">Upload &amp; run</a>; each file is detected automatically.</p>

      <div className="card">
        <table className="tbl">
          <thead><tr><th>#</th><th>Input</th><th>Need</th><th>Comes from</th><th>Format</th><th>Used for</th></tr></thead>
          <tbody>{INPUTS.map((i) => (
            <tr key={i.n}><td>{i.n}</td><td><a href={`#export-${i.n}`} onClick={(e) => { e.preventDefault(); document.getElementById(`export-${i.n}`)?.scrollIntoView({ behavior: 'smooth' }) }}><b>{i.name}</b></a></td>
              <td><span className={`pill ${i.need === 'Required' ? 'bad' : i.need === 'Recommended' ? 'warn' : ''}`}>{i.need}</span></td>
              <td className="small">{i.from}</td><td className="small">{i.format}</td><td className="small">{i.why}</td></tr>))}</tbody>
        </table>
        <div className="row gap wrap" style={{ marginTop: 10 }}>
          <span className="small muted">Templates:</span>
          <button className="btn" onClick={usageTemplate}>Usage (CSV)</button>
          <button className="btn" onClick={mappingTemplate}>Package mapping (CSV)</button>
          <button className="btn" onClick={catalogTemplate}>Source catalog (CSV)</button>
        </div>
      </div>

      <Step n={1} title="Report specifications" need="Required">
        <p>Export the specification (the report XML) of <b>every</b> report: Team Content, archive folders and users' My Folders. Copies and old versions are exactly what rationalization needs to see, so do not pre-filter. Include reports, saved interactive reports and report views' base reports.</p>
        <h4>How to export</h4>
        <ol className="guide-list">
          <li><b>Cognos SDK (recommended for whole estates).</b> Query the Content Manager service for objects of class <span className="mono">report</span> and <span className="mono">interactiveReport</span> under <span className="mono">/content</span>, requesting the properties <span className="mono">defaultName</span>, <span className="mono">searchPath</span> and <span className="mono">specification</span>. Write each specification to a file named after <span className="mono">defaultName</span>.</li>
          <li><b>Content Store database (with your DBA, read-only).</b> Specifications are stored in the Content Store tables. In many versions they are in <span className="mono">CMOBJPROPS7</span> (column <span className="mono">SPEC</span>), joined to <span className="mono">CMOBJNAMES</span> for the report name. Check the table names for your version, then save each specification to its own file.</li>
          <li><b>A few reports by hand.</b> Open the report in Reporting and use <i>Copy report to clipboard</i>, then paste it into a file named after the report.</li>
        </ol>
        <h4>What SemanticLift reads</h4>
        <ul className="guide-list">
          <li><b>Name:</b> the report name comes from the file name, so name each file exactly as the report appears in the usage sheet, e.g. <span className="mono">Revenue_by_Region.xml</span>.</li>
          <li><b>Package:</b> read from <span className="mono">&lt;modelPath&gt;</span>.</li>
          <li><b>Queries:</b> data items (expression, aggregate) and detail and summary filters, including prompts like <span className="mono">?p_FiscalYear?</span>. Layouts are ignored.</li>
          <li><b>Folder and duplicate group:</b> taken from the usage sheet (step 2).</li>
          <li><b>Combined export:</b> one <span className="mono">&lt;contentExport&gt;</span> file holding many <span className="mono">&lt;report name="…" package="…" folder="…" reportPath="…"&gt;</span> elements also works. This is the format of the samples.</li>
        </ul>
        <Code text={SPEC_EXAMPLE} />
        <p className="small muted">Deployment archives created under Administration › Content administration › Export are not read directly; extract the specifications as above.</p>
      </Step>

      <Step n={2} title="Report usage" need="Required">
        <p>Usage decides what is kept and what is retired, so it matters as much as the specifications. It comes from the <b>Audit database</b>. Audit logging of report executions must be enabled; use at least 6 months of history, and ideally 12 months so quarterly and year-end reports show up.</p>
        <h4>Columns</h4>
        <table className="tbl compact">
          <thead><tr><th>Column</th><th>Need</th><th>Meaning</th></tr></thead>
          <tbody>{USAGE_COLS.map(([c, n, d]) => <tr key={c}><td className="mono small">{c}</td><td className="small">{n}</td><td className="small">{d}</td></tr>)}</tbody>
        </table>
        <p className="small"><b>folder_category:</b> <b>Active</b> is the governed report (Team Content). <b>Archive</b> is an old or backup copy. <b>Community</b> is a copy or variant in a user's My Folders or a shared team folder. The column header may sit in any of the first 10 rows, so a title row above it is fine. Leave user names out; they are not needed.</p>
        <h4>Starting query</h4>
        <Code text={AUDIT_SQL} />
      </Step>

      <Step n={3} title="Package-to-source mapping" need="Required">
        <p>One row per package, and one per data module, naming the database each one reads. Find it under <i>Administration › Configuration › Data source connections</i> and in each package's data source. SemanticLift uses it to scope the sources and to name the landing (RAW) schemas.</p>
        <table className="tbl compact">
          <thead><tr><th>FM Package/Data Module</th><th>FM Package</th><th>Source Database/System</th></tr></thead>
          <tbody><tr><td>Sales_Package</td><td>Sales_Package</td><td>Oracle - SALES_DW</td></tr><tr><td>Sales_Orders_DM</td><td>Sales_Package</td><td>Oracle - SALES_DW</td></tr></tbody>
        </table>
        <p className="small muted">Write the source as <span className="mono">Vendor - DATABASE</span>. Oracle, SQL Server, Db2, Teradata, SAP HANA, Salesforce and OSIsoft PI are recognised; other vendor names are kept as written. The header row must contain <span className="mono">FM Package</span> and <span className="mono">Source Database/System</span>.</p>
      </Step>

      <Step n={4} title="Framework Manager project" need="Recommended">
        <p>Zip the whole Framework Manager project folder: the <span className="mono">.cpf</span>, <span className="mono">model.xml</span> and any data source, namespace, parameter map, security and publish files. The model confirms physical tables and columns, each measure's aggregation rule, relationships and calculated items. That raises confidence, so more generated objects are ready to approve.</p>
        <div className="note">
          <b>Supported layout today.</b> SemanticLift reads the Framework Manager XML layout used in the bundled samples, where names are attributes (<span className="mono">&lt;querySubject name="Billing"&gt;</span>, <span className="mono">&lt;queryItem name="BillAmount" usage="fact" regularAggregate="total"&gt;</span>). The native <span className="mono">model.xml</span> that Framework Manager saves keeps names in child elements; it is <b>not parsed yet</b>. If you upload one, <i>Upload &amp; run</i> marks it "rejected: not supported yet" and the run continues. Entities are then inferred from the report specifications, at lower confidence and with more objects left as stubs until their source is confirmed. Adding the source catalog (step 6) closes most of that gap.
        </div>
      </Step>

      <Step n={5} title="Security and prompt definitions" need="Recommended">
        <ul className="guide-list">
          <li><b>Row-level security:</b> security filters per query subject, with the roles they apply to and the roles exempt from them. Root element <span className="mono">&lt;rowLevelSecurity&gt;</span>, one <span className="mono">&lt;securityFilter name targetQuerySubject&gt;</span> each, with <span className="mono">&lt;expression&gt;</span>, <span className="mono">&lt;appliesTo&gt;</span> and <span className="mono">&lt;exemptRoles&gt;</span>.</li>
          <li><b>Object-level security and masking:</b> root <span className="mono">&lt;objectLevelSecurity&gt;</span> with <span className="mono">&lt;securedObject querySubject queryItem&gt;</span> (allowed and denied roles) and <span className="mono">&lt;columnMasking&gt;</span> (masked value and masking roles).</li>
          <li><b>Prompts:</b> parameter maps, root <span className="mono">&lt;parameterMap&gt;</span> with one <span className="mono">&lt;parameter name&gt;</span> each: data type, default value, multi-select and pick list.</li>
        </ul>
        <p className="small muted">These become row access and masking policies on the platform. The samples show complete examples. Never include passwords; SemanticLift masks credentials in connection URLs, but they should not be in the export at all.</p>
      </Step>

      <Step n={6} title="Source catalog" need="Optional">
        <p>If the sources are already landed on the data platform, export the tables and columns from its information schema. SemanticLift matches report items that are missing from the FM model to these tables by name and column overlap, and uses row counts to size aggregates.</p>
        <Code text={CATALOG_SQL} />
      </Step>

      <section className="card">
        <h2 style={{ marginTop: 0 }}>Package and check</h2>
        <Code text={LAYOUT} />
        <ul className="guide-list">
          <li><b>Accepted files:</b> .zip (nested zips are unpacked), .xml, .cpf, .ns, .ds, .xlsx, .csv. File and folder names do not matter, except report specification file names (the report name).</li>
          <li><b>After uploading:</b> on <a href="#/ingest">Upload &amp; run</a>, check that every file shows an adapter and the status <i>parsed</i>, that the stated and actual report counts match, and that the usage join matched almost every report. A rejected file shows the reason next to it.</li>
          <li><b>Do not include:</b> data extracts, passwords or user lists. Only metadata is needed.</li>
          <li><b>Examples:</b> <span className="mono">samples/Cognos Lineage Input.zip</span> (energy utility) and <span className="mono">samples/Cognos Telco Input.zip</span> (telecommunications) in the repository show complete bundles.</li>
        </ul>
      </section>
    </div>
  )
}
