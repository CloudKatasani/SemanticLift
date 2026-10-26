# Cognos-to-Data-Platform Semantic Layer Migrator — Application Specification

Oct 25, 2026 · @Durga Prasad Katasani

## 1. Purpose and scope

The application (working name **SemLift**) ingests a Cognos estate export, works out which business logic actually lives in the BI semantic layer, and generates a governed semantic model on the data platform. Its output is deployable DDL, semantic view definitions, data product contracts and a traceability matrix that maps every surviving Cognos report column to its new home.

Primary target is Snowflake (tables, dynamic tables, secure views, semantic views, row access and masking policies, internal marketplace listings). The generator layer is pluggable so Databricks (Unity Catalog metric views) or a dbt project can be emitted from the same intermediate model.

**Goals**

- Parse Framework Manager projects, report specifications, usage statistics and package-to-source mappings without manual pre-processing.
- Rationalize first: collapse archive and community duplicates so only demanded logic is migrated.
- Move joins, calculations, aggregation rules, prompts and security out of Cognos and into platform objects any BI or AI tool can consume.
- Produce a reviewable design (with confidence scores) before any DDL is deployed.
- Keep full lineage: report column → Cognos data item → FM query item → source column → new platform object.

**Non-goals**

- Re-building report layouts, visual formatting or bursting in a new BI tool.
- Physical data migration (ingest from Oracle, PI, SAP HANA and Salesforce is assumed to be handled by the ingestion program; the tool consumes its landed schemas).
- Translating Cognos dimensional (DMR/OLAP) cubes in release 1; flagged for manual design.

## 2. Review of the supplied Cognos export

The export holds 588 reports over 6 packages, but only one of those packages has a Framework Manager model, so the tool must design most of the semantic model from report usage alone. Two-thirds of the reports (392) are archive or community copies of 196 distinct reports, and they draw 68% of daily runs.

### 2.1 What is in the bundle

| File | Format | Contents | Role in the tool |
| --- | --- | --- | --- |
| `FM/cognos_fm_package_v12.zip` → `model.xml`, `package.xml` | FM BMT schema v13 (CA 12.1.2) | 3 namespaces: Physical (10 data-source query subjects on Oracle `ENERGY_DW`), Business (10 model query subjects, 65 query items, 7 calculations), Presentation (6 folders); 10 relationships, all n:1 inner | Authoritative source for tables, joins, business names, calculations, default aggregation |
| `.cpf`, `.ns`, `.ds` files | FM project, namespace summaries, data source | Project manifest, layer summaries, Oracle 19c JDBC, 11 tables incl. `USER_REGION_ACCESS` | Source-system and object inventory |
| `security/rowlevelsecurity.xml`, `objectlevelsecurity.xml` | FM security | 4 row filters (Region, ActiveMeter, ComplianceEntity, CurrentYearFinance); column grants on 5 measures (BillAmount, TotalBillWithTax, MarketSettlementAmount, FuelCostTotal, ViolationPenalty); CreditScore masking; ABAC deny policy | Generates row access and masking policies |
| `parametermaps/CommonPrompts.xml` | FM parameter map | `p_FiscalYear`, `p_Region`, `p_Month`, `p_Quarter`, `p_DateFrom`, `p_DateTo` with defaults, pick lists, validation | Generates filter dimensions and reference value sets |
| `Reports/.../all_reports.xml` | Content export, report spec v16 | 588 reports (378 list, 168 crosstab, 42 chart), 1 query each, 4,101 data items, 582 detail filters | Demand signal: which items, grains and filters are really used |
| `cognos_report_usage_600.xlsx` | Usage log | 588 rows: package, type, duplicate group, similarity, runs/day, last run, avg duration | Prioritization and retirement |
| `FM_Data_Module_Mapping_Energy.xlsx` | Mapping | 6 packages and 11 data modules → 5 source systems (Oracle ENERGY\_OPS\_DW, CC&B, OSIsoft PI, SAP HANA FICA, Salesforce Service Cloud) | Routes each package to its landed source schema |

### 2.2 Findings that shape the design

| # | Finding | Evidence | Design consequence |
| --- | --- | --- | --- |
| F1 | Model coverage gap | Reports reference 39 query subjects across 6 packages; the FM model defines 10 (Energy\_Utilities\_Package). 612 active data-item references (Compliance, Finance, Customer Service, Substation, LoadForecast, PowerPlant, …) have no FM definition | Tool must infer entities from report usage plus landed source schemas, with lower confidence scores |
| F2 | Heavy duplication | 196 duplicate groups, each exactly Active + Archive (97–99%) + Community (90–96%); archive column sets match active in 134 groups; 192 distinct active column signatures | Rationalize to \~192 report intents before design; migrate one semantic contract per group |
| F3 | Duplicates carry the load | Runs/day: Active 1,000, Archive 1,048, Community 1,087 (3,135 total) | Retirement needs a consumer redirect plan, not just deletion |
| F4 | Dormant content | 134 reports with 0 runs/day; 338 last run before 2026-01-01 | Exclude from design scope by default (configurable threshold) |
| F5 | No report-level logic | All 4,101 data items are direct references; aggregates only `none` / `total` | Business logic lives in FM; report specs supply grain and filter demand only |
| F6 | Aggregation overrides are wrong | Reports apply `total` to semi-/non-additive measures: CapacityFactorPct (11), CapacityMW (9), PeakDemandKW (7), RatePerKWh (5), CO2FactorKgKWh (3), DemandChargeRate (1) | Semantic layer enforces FM default aggregation (average, max, ratio) and flags reports whose numbers will change |
| F7 | Filter defects | 66 filters compare `[Date].[FiscalYear]` to `?p_Region?` | Flag as defects; do not replicate; route to report owners |
| F8 | Unused FM logic | 24 of 65 Business-layer items are unused by active reports, incl. calculated TotalBillWithTax, IsOverdue, CO2IntensityKgPerMWh, PeakOffPeakRatio | Keep calculations as semantic metrics (cheap), drop unused raw attributes from the presentation contract |
| F9 | Model drift | Reports use items absent from FM: Billing.DueDate, Customer.ServiceTier, Generation.FuelCostPerMWh, OutageEvent.SAIFICount / MAIFICount / CauseDescription; RLS targets DataSubmission and BudgetActual, which are not in the model; BillAmount grants in \`objectlevelsecurity.xml\` (4 roles) differ from those embedded in \`model.xml\` (2 roles) | Reconcile against source catalogs; raise as open items |
| F10 | Conformed dimensions | Date is used by all 6 packages, Location by 2, Customer by 2 with different attributes (Billing: AccountType, ServiceTier; CS: ChurnRisk, NPS\_Score, LifetimeValueUSD) | Build one conformed DIM\_DATE, DIM\_LOCATION and DIM\_CUSTOMER with mastered keys across CC&B and Salesforce |
| F11 | Inconsistent counts | Usage file title says 600 reports / 200 per category; actual rows and XML both hold 588 / 196 | Validator reconciles stated vs actual counts on ingest |
| F12 | Hard-coded factors | CO2EstimateKg uses a literal 0.233 kg/kWh | Externalize constants to a governed reference table |

## 3. Solution architecture

SemLift is a seven-stage pipeline: parse every input into one metadata graph, rationalize the report estate, design the target model, get it approved, then generate and deploy platform objects.

&#91;embedded content: solution architecture · 7 pipeline stages\]

Stages 1–3 are fully automated; stage 4 is rule-driven with LLM-drafted text; stage 5 is the human checkpoint that nothing skips. Stages 6–7 run in the client's CI pipeline so deployment follows the same controls as any other code change.

## 4. Input parsing specifications

Each input has its own adapter that emits records into the canonical model (Section 5); adapters never talk to each other. Every record carries `source_file`, `xpath` or `sheet!row`, and a parser confidence so reviewers can trace any generated object back to the line that produced it.

### 4.1 Accepted inputs

| Adapter | Input | Detection rule | Required? |
| --- | --- | --- | --- |
| FM-PROJ | `.cpf` + `model.xml` / `package.xml` (BMT 60/12 and 60/13) | root `project`, namespace `http://www.developer.cognos.com/schemas/bmt/60/*` | Optional per package; absence lowers confidence |
| FM-SEC | `rowlevelsecurity.xml`, `objectlevelsecurity.xml`, `<security>` block in model | root `rowLevelSecurity` / `objectLevelSecurity` | Optional |
| FM-PARAM | parameter map XML, `<parameterMap>` in model | root `parameterMap` | Optional |
| FM-DS | `.ds` data source files | root `dataSourceConnection` | Optional; mapping sheet can substitute |
| RPT | Content export XML (report spec v14–16), single or per-report files; Cognos SDK / REST dumps in phase 2 | root `contentExport` or `report` | **Required** |
| USAGE | Audit DB extract or usage XLSX/CSV | header row containing `report_name` + `runs_per_day` or audit `COGIPF_*` tables | Recommended |
| MAP | Package / data module → source system sheet | header `FM Package` + `Source Database/System` | Required when FM model is missing |
| SRC-CAT | Landed source catalog (Snowflake `INFORMATION_SCHEMA`, Horizon / Polaris catalog, or CSV) | live connection or file | Recommended; resolves F1 and F9 |

XLSX headers are located by scanning the first 10 rows (the usage file has a 3-row title block). Archives are unpacked recursively into an isolated work folder; nested zips (as in `FM/cognos_fm_package_v12.zip`) are expected.

### 4.2 Extraction rules

**FM model**

1. Namespaces are classified by `.ns` `type` or name heuristics: physical (dataSourceQuerySubject), business (modelQuerySubject), presentation (folders of `refObject`).
2. Physical query subjects: parse `dbQuery` for table name and optional SQL; each `queryItem` → column with `dataType`, `usage` (identifier / attribute / fact), `regularAggregate`.
3. Business query items: parse `expression` with a Cognos expression grammar (ANTLR). A single `[ns].[qs].[item]` reference is a rename; anything else is a calculation and is kept as an AST.
4. Relationships: `left`, `right`, `cardinality`, `joinType`, join expression → FK candidates and join paths.
5. `governanceMetadata`, `description`, `sensitiveData` → tags, owner, steward, classification, retention.
6. When both `model.xml` and `package.xml` exist, diff them and report drift; `package.xml` (published) wins by default.

**Report specifications**

1. One record per report: name, type (L list, C crosstab, X chart), package, folder, path, `duplicateGroupID`, `similarityScore`.
2. One record per query and data item: name, expression, `usage`, `aggregate`, `rollupAggregate`.
3. Expressions are resolved against the package namespace; unresolved references are kept as **inferred** entities (F1).
4. Detail and summary filters are parsed into predicate, referenced item, operator, literal or `?param?`. Type checks catch mismatches such as FiscalYear vs `?p_Region?` (F7).
5. Data items with duplicate names inside one query are flagged (found in 1 active report).
6. Phase 2: layout pages, crosstab edges, chart series, drill-throughs, conditional styles and `sqlQuery` native SQL.

**Usage and mapping**

1. Join usage to reports on `report_name`, then `report_path`; report any orphans either way.
2. Dates are parsed from the `Mon D, YYYY h:mm:ss AM` format; `runs_per_day`, `avg_duration_min` are numeric.
3. Mapping rows map a package or data module to `vendor - database`; vendor drives the type mapping (Oracle, SAP HANA, OSIsoft PI, Salesforce).

## 5. Canonical metadata model (intermediate representation)

All adapters write to one platform-neutral graph, stored as relational tables in the tool's own repository (Postgres for the app, mirrored to a Snowflake `SEMLIFT_META` schema for analysis). Generators read only from this graph, which is what lets one parse feed Snowflake, Databricks or dbt outputs.

### 5.1 Core entities

| Entity | Key attributes | Populated from |
| --- | --- | --- |
| `source_system` | name, vendor, database, schema, refresh cadence | MAP, FM-DS, governance lineage |
| `source_object` | system, schema, table, columns, data types, row count (if catalog connected) | FM physical layer, SRC-CAT |
| `package` | name, FM project, data modules, source system | RPT, MAP, FM-PROJ |
| `logical_entity` | name, role (fact / dimension / bridge / reference), grain, primary key, origin (FM, inferred), confidence | FM business layer, report inference |
| `logical_attribute` | entity, business name, physical column, data type, usage, sensitivity, description | FM query items, report data items |
| `measure` | entity, expression AST, default aggregation, additivity (additive / semi / non), unit, format | FM facts and calculations, name heuristics (`Pct`, `Rate`, `Ratio`, `MW` capacity) |
| `relationship` | from, to, cardinality, join type, join keys, role name | FM relationships, co-usage inference |
| `hierarchy` | levels (e.g. FiscalYear → Quarter → MonthName → FullDate) | FM, DATE pattern library |
| `parameter` | name, type, default, pick list, validation | FM-PARAM, report filters |
| `security_rule` | type (row, column grant, mask, ABAC), target, predicate, roles in / exempt | FM-SEC |
| `report` | name, type, package, folder, path, dup group, similarity, runs/day, last run, avg duration, disposition | RPT, USAGE |
| `report_item` | report, query, data item, resolved attribute or measure, aggregate override | RPT |
| `report_filter` | report, predicate AST, parameter, defect flag | RPT |
| `intent_cluster` | canonical report, member reports, union of items, grain signature | Rationalization engine |
| `target_object` | layer, object type, name, DDL, source lineage, status (proposed / approved / deployed) | Design engine |
| `finding` | code (F1–F12 style), severity, object, evidence, owner, resolution | All stages |

### 5.2 Confidence scoring

Each logical entity, attribute and measure gets a score from 0 to 1 that drives the review queue:

- 1.0 — defined in FM and matched to a landed source column.
- 0.8 — defined in FM, source column not yet confirmed in the catalog.
- 0.6 — inferred from report usage and matched by name to a source column.
- 0.3 — inferred from report usage only (today: Compliance, Finance, Customer Service, and the Operations / Generation subjects missing from FM).

Objects below 0.6 cannot be auto-approved for deployment.

## 6. Semantic model design rules

The design engine turns the canonical graph into four platform layers — conformed core, aggregates, semantic views, data products — and every rule below is a deterministic, configurable rule, with an LLM used only to draft descriptions and synonyms.

### 6.1 Cognos construct → platform object

| Cognos construct | Snowflake target | Databricks target |
| --- | --- | --- |
| Physical query subject | Source table in landing / `RAW_<SYSTEM>` (referenced, not created) | Bronze table |
| Business query subject (dimension) | `CORE.DIM_<ENTITY>` view or table with surrogate key | Silver / gold dimension |
| Business query subject (fact) | `CORE.FCT_<PROCESS>` at atomic grain | Gold fact |
| Rename-only query item | Column alias in CORE view | Column alias |
| Row-level calculation (IsOverdue, TotalBillWithTax, ConsumptionMWh) | Derived column in CORE | Derived column |
| Ratio or `regularAggregate=calculated` (CO2IntensityKgPerMWh, PeakOffPeakRatio) | Semantic view **metric** (`SUM(a)/NULLIF(SUM(b),0)`), never a stored column | Metric view measure |
| Relationship | Semantic view `RELATIONSHIPS` + FK constraint (RELY) in CORE | Metric view joins + FK |
| Presentation folder | Semantic view per subject area | Metric view per subject area |
| Parameter map | `REF.PARAM_<NAME>` value tables + documented filter dimension | Reference tables |
| Row security filter | Row access policy on the dimension; mapping table in `SEC` | Row filter function |
| Object security / masking | Masking policy + tag-based masking on sensitive columns | Column mask |
| ABAC policy | Tag-based policy keyed on `DATA_CLASSIFICATION` tag | ABAC on governed tags |
| Package | Data product (one or more semantic views + contract + listing) | Unity Catalog share / data product |
| Data module | Optional child semantic view; same CORE objects | Metric view |

### 6.2 Rationalization before design

1. Group by `duplicateGroupID` (or compute similarity on item sets when absent: Jaccard on resolved items + filters).
2. Pick the canonical member: Active unless a duplicate has more runs/day and a superset of columns.
3. The cluster contract is the union of resolved items across members; extra community items are kept only if their reports ran in the look-back window (default 180 days).
4. Clusters whose members all have 0 runs/day or no run in the window are marked **Retire** and excluded from aggregate design.
5. Outcome per report: Migrate, Merge into canonical, Retire, Defect fix needed.

### 6.3 Conformed core layer

- **Dimensions** are entities whose items are mostly `attribute` / `identifier` and sit on the “1” side of relationships. Identically named entities across packages (Date, Location, Customer) are merged into one conformed dimension when key and core attributes match; package-specific attributes become extension columns.
- **Facts** are entities with `fact` items on the “n” side. Grain = the set of FK identifiers plus the degenerate key (ReadingID, BillID, GenerationID, OutageID).
- Inferred entities (confidence < 0.6) are generated as **stubs**: DDL with `TODO` source mapping and a finding, never auto-deployed.
- Every column carries a `COMMENT` from the FM description or generated text, plus object tags: `DOMAIN`, `DATA_OWNER`, `DATA_CLASSIFICATION`, `SENSITIVE`, `RETENTION` (7 years per FERC from governance metadata).
- Hard-coded constants (0.233 kg/kWh) move to `REF.EMISSION_FACTOR` with effective dates.

### 6.4 Aggregated views

Aggregates are designed from demand, not guessed:

1. For each surviving cluster compute its **grain signature** = fact entity + set of dimension attributes used (for example `Billing × {Region, MonthName, FiscalYear, CustomerSegment, PaymentStatus}`).
2. Roll signatures up the dimension hierarchies (FullDate → MonthName → Quarter → FiscalYear; City → StateProvince → Region).
3. Greedily choose the smallest set of aggregates that covers ≥ 80% of weighted demand (weight = runs/day × avg duration), capped at 3 per fact by default.
4. Only additive measures are pre-summed. Semi- and non-additive measures are stored as their components (sum, count, max) so ratios and averages re-aggregate correctly.
5. Default implementation is a Snowflake **dynamic table** (`AGG.AGG_<FACT>_<GRAIN>`), `TARGET_LAG` from the source refresh cadence (daily → `'24 hours'`). Option: materialized view for single-table cases, or a plain view when the base fact is under 10M rows.
6. The semantic view keeps pointing at the atomic fact; aggregates are registered for query rewrite or exposed as separate semantic tables, per platform capability.

### 6.5 Semantic views

- One semantic view per presentation folder or package subject area, named `SEM.SV_<DOMAIN>_<SUBJECT>` (for example `SV_BILLING_REVENUE`, `SV_GRID_RELIABILITY`).
- Sections generated: `TABLES` (with primary keys), `RELATIONSHIPS`, `FACTS` (row-level), `DIMENSIONS` (with synonyms and sample values from pick lists), `METRICS` (with the correct aggregation from FM, not the report override, see F6).
- Synonyms come from the FM business name, the report data-item labels (e.g. ReadingDate → FullDate) and an LLM pass reviewed by stewards, so Cortex Analyst and BI tools share one vocabulary.
- Verified queries: the top 10 report intents per view are rendered as natural-language question + SQL pairs.
- Prompts become filterable dimensions; required prompts (`p_FiscalYear`) are documented as default filters in the consumer contract.

### 6.6 Data products

- Default boundary = one data product per Cognos package, adjusted by data module mapping: today six candidates — Grid Operations, Customer Billing and Metering, Generation and Energy Mix, NERC Compliance, Financial Performance, Customer Experience.
- Each product bundles: its semantic views, secure output views in `DP_<DOMAIN>.OUT_*`, a data contract (YAML: schema, grain, SLAs from refresh cadence, owner, steward, classification, quality rules), and an internal marketplace listing.
- Conformed dimensions are published once as a shared **Enterprise Reference** product and consumed by the others.
- Quality rules generated from the model: not-null on keys, FK integrity per relationship, pick-list domain checks from parameter maps, freshness against target lag.

### 6.7 Naming and placement

| Layer | Schema | Object pattern |
| --- | --- | --- |
| Core | `CORE` | `DIM_<ENTITY>`, `FCT_<PROCESS>` |
| Reference | `REF` | `REF_<NAME>`, `PARAM_<NAME>` |
| Aggregates | `AGG` | `AGG_<FACT>_<GRAIN>` |
| Semantic | `SEM` | `SV_<DOMAIN>_<SUBJECT>` |
| Security | `SEC` | `RAP_<NAME>`, `MP_<NAME>`, `MAP_USER_<SCOPE>` |
| Data product | `DP_<DOMAIN>` | `OUT_<NAME>` secure views |

## 7. Outputs and sample design from this export

One run produces a versioned design package: a Git-ready DDL project, a design workbook for review and a findings register. For this export the engine should propose roughly 32 distinct logical entities (39 package-level subjects after merging Date, Location, Customer and OutageEvent) grouped into six domain data products plus a shared reference product.

### 7.1 Output package

| Artifact | Format | Content |
| --- | --- | --- |
| `ddl/core/*.sql`, `ddl/agg/*.sql`, `ddl/sem/*.sql`, `ddl/sec/*.sql`, `ddl/dp/*.sql` | SQL, one object per file, ordered by dependency | CREATE OR ALTER for every proposed object |
| `semantic/*.yaml` | Snowflake semantic model YAML / Databricks metric view YAML | Same content as the semantic views, for tools that read YAML |
| `dbt/` (optional) | dbt project | Models, sources, tests, exposures per report cluster |
| `contracts/<product>.yaml` | Open Data Contract Standard style | Schema, grain, SLAs, owner, quality rules, classification |
| `design_workbook.xlsx` | Excel | Object inventory, column mapping, measure catalog, aggregate plan, security matrix, report disposition, findings |
| `lineage.json` + traceability matrix | OpenLineage JSON, CSV | Report column → data item → FM item → source column → target object |
| `findings.md` | Markdown | All findings with evidence and owner |
| `validation/*.sql` | SQL | Parity queries comparing Cognos-generated SQL results with semantic view results |

### 7.2 Proposed object inventory for this export

| Data product | Facts (CORE) | Domain dimensions | Aggregate candidates | Semantic views | Confidence |
| --- | --- | --- | --- | --- | --- |
| Enterprise Reference (shared) | — | DIM\_DATE, DIM\_LOCATION, DIM\_CUSTOMER (CC&B + Salesforce mastered), REF\_PARAM\_\* , REF\_EMISSION\_FACTOR | — | Used by all | High for Date / Location; medium for Customer |
| Customer Billing and Metering | FCT\_BILLING, FCT\_METER\_READING | DIM\_METER, DIM\_TARIFF | AGG\_BILLING\_MONTH\_REGION\_SEGMENT (+ PaymentStatus); AGG\_METER\_READING\_MONTH\_METER | SV\_BILLING\_REVENUE, SV\_METER\_CONSUMPTION | High (FM-defined) |
| Generation and Energy Mix | FCT\_GENERATION, FCT\_REC\_CERTIFICATE, FCT\_STORAGE\_STATUS | DIM\_ENERGY\_SOURCE, DIM\_POWER\_PLANT, DIM\_STORAGE\_ASSET | AGG\_GENERATION\_MONTH\_PLANT\_SOURCE | SV\_GENERATION\_MIX, SV\_RENEWABLES\_STORAGE | Mixed: Generation / EnergySource high; plant, REC, storage inferred |
| Grid Operations | FCT\_OUTAGE\_EVENT, FCT\_LOAD\_FORECAST, FCT\_SUBSTATION\_LOAD, FCT\_LINE\_LOADING | DIM\_SUBSTATION, DIM\_TRANSMISSION\_LINE, DIM\_OUTAGE\_CAUSE | AGG\_LOAD\_FORECAST\_DAY\_REGION; AGG\_SUBSTATION\_MONTH\_REGION | SV\_GRID\_RELIABILITY, SV\_LOAD\_AND\_CAPACITY | Outage high; others inferred |
| NERC Compliance | FCT\_COMPLIANCE\_EVENT, FCT\_VIOLATION, FCT\_AUDIT\_RECORD, FCT\_DATA\_SUBMISSION, FCT\_MISOPERATION, FCT\_PRC004\_TEST | DIM\_NERC\_STANDARD, DIM\_REPORTING\_ENTITY | none (low volume; plain views) | SV\_NERC\_COMPLIANCE | Inferred (0.3–0.6) |
| Financial Performance | FCT\_BUDGET\_ACTUAL, FCT\_REVENUE, FCT\_MARKET\_SETTLEMENT, FCT\_FUEL\_COST, FCT\_CAPEX\_SPEND | DIM\_GL\_ACCOUNT, DIM\_COST\_CENTER, DIM\_CAPEX\_PROJECT, DIM\_COUNTERPARTY | AGG\_BUDGET\_ACTUAL\_MONTH\_ACCOUNT | SV\_FINANCE\_PERFORMANCE, SV\_MARKET\_AND\_FUEL | Inferred (SAP HANA FICA) |
| Customer Experience | FCT\_SERVICE\_REQUEST, FCT\_COMPLAINT, FCT\_FIELD\_SERVICE, FCT\_EV\_CHARGING | DIM\_AGENT, DIM\_TECHNICIAN, DIM\_CHARGER | AGG\_SERVICE\_REQUEST\_MONTH\_SEGMENT\_TYPE | SV\_CUSTOMER\_SERVICE, SV\_EV\_CHARGING | Inferred (Salesforce) |

Security objects for all products: `SEC.MAP_USER_REGION` (from `USER_REGION_ACCESS`), `SEC.MAP_USER_COMPLIANCE_ENTITY`, row access policies `RAP_REGION`, `RAP_ACTIVE_METER`, `RAP_COMPLIANCE_ENTITY`, `RAP_FINANCE_CURRENT_YEAR`; masking policies `MP_CREDIT_SCORE`, `MP_RESTRICTED_AMOUNT` (BillAmount, TotalBillWithTax, MarketSettlementAmount, FuelCostTotal, ViolationPenalty).

### 7.3 Sample generated objects (Customer Billing and Metering)

Core fact with FM calculations pushed down as row-level columns:

```sql
CREATE OR REPLACE VIEW CORE.FCT_BILLING
  COMMENT = 'Bill line grain. Source: CC_AND_B_PROD.BILLING. Origin: FM Business Layer.Billing'
AS
SELECT
    b.BILL_ID                         AS BILL_ID,
    b.METER_ID                        AS METER_ID,
    b.BILL_DATE_KEY                   AS DATE_KEY,
    b.BILL_AMOUNT                     AS BILL_AMOUNT,
    b.TAX_AMOUNT                      AS TAX_AMOUNT,
    b.ENERGY_CHARGE                   AS ENERGY_CHARGE,
    b.DEMAND_CHARGE                   AS DEMAND_CHARGE,
    b.BILL_AMOUNT + b.TAX_AMOUNT      AS TOTAL_BILL_WITH_TAX,
    b.PAYMENT_STATUS                  AS PAYMENT_STATUS,
    IFF(b.PAYMENT_STATUS = 'Overdue', 'Yes', 'No') AS IS_OVERDUE,
    b.IS_EBILL                        AS IS_EBILL
FROM RAW_CCB.BILLING b;
```

Demand-driven aggregate (covers the 17 active billing reports grouped by Region and month):

```sql
CREATE OR REPLACE DYNAMIC TABLE AGG.AGG_BILLING_MONTH_REGION_SEGMENT
  TARGET_LAG = '24 hours'
  WAREHOUSE  = WH_SEMANTIC_REFRESH
AS
SELECT d.FISCAL_YEAR, d.QUARTER, d.MONTH_NUMBER, d.MONTH_NAME,
       l.REGION, c.CUSTOMER_SEGMENT, f.PAYMENT_STATUS,
       SUM(f.BILL_AMOUNT)    AS BILL_AMOUNT,
       SUM(f.TAX_AMOUNT)     AS TAX_AMOUNT,
       SUM(f.ENERGY_CHARGE)  AS ENERGY_CHARGE,
       SUM(f.DEMAND_CHARGE)  AS DEMAND_CHARGE,
       COUNT(*)              AS BILL_COUNT
FROM CORE.FCT_BILLING f
JOIN CORE.DIM_DATE     d ON f.DATE_KEY    = d.DATE_KEY
JOIN CORE.DIM_METER    m ON f.METER_ID    = m.METER_ID
JOIN CORE.DIM_CUSTOMER c ON m.CUSTOMER_ID = c.CUSTOMER_ID
JOIN CORE.DIM_LOCATION l ON m.LOCATION_ID = l.LOCATION_ID
GROUP BY ALL;
```

TariffType is deliberately left out. Eleven active billing reports group Billing by TariffType, but the FM model joins Tariff only to MeterReading, so Cognos reaches it through Billing → Meter ← MeterReading → Tariff — a fan trap that can multiply bill amounts. The engine flags this path as an ambiguous join and asks the modeller to add a bill-level tariff key before the aggregate includes it.

Semantic view, with FM default aggregations enforced:

```sql
CREATE OR REPLACE SEMANTIC VIEW SEM.SV_BILLING_REVENUE
  TABLES (
    billing  AS CORE.FCT_BILLING  PRIMARY KEY (BILL_ID)     WITH SYNONYMS ('bills', 'invoices'),
    meter    AS CORE.DIM_METER    PRIMARY KEY (METER_ID),
    customer AS CORE.DIM_CUSTOMER PRIMARY KEY (CUSTOMER_ID),
    location AS CORE.DIM_LOCATION PRIMARY KEY (LOCATION_ID),
    dt       AS CORE.DIM_DATE     PRIMARY KEY (DATE_KEY)
  )
  RELATIONSHIPS (
    billing_to_meter    AS billing (METER_ID)    REFERENCES meter,
    billing_to_date     AS billing (DATE_KEY)    REFERENCES dt,
    meter_to_customer   AS meter (CUSTOMER_ID)   REFERENCES customer,
    meter_to_location   AS meter (LOCATION_ID)   REFERENCES location
  )
  FACTS (
    billing.bill_amount   AS BILL_AMOUNT,
    billing.tax_amount    AS TAX_AMOUNT
  )
  DIMENSIONS (
    dt.fiscal_year         AS FISCAL_YEAR      WITH SYNONYMS ('FY'),
    dt.month_name          AS MONTH_NAME,
    location.region        AS REGION           WITH SYNONYMS ('service territory'),
    customer.segment       AS CUSTOMER_SEGMENT,
    billing.payment_status AS PAYMENT_STATUS,
    billing.is_overdue     AS IS_OVERDUE
  )
  METRICS (
    billing.total_billed          AS SUM(billing.bill_amount),
    billing.total_billed_with_tax AS SUM(billing.bill_amount + billing.tax_amount),
    billing.overdue_bill_count    AS COUNT_IF(billing.is_overdue = 'Yes')
  )
  COMMENT = 'Generated by SemLift from Energy_Billing_Package and FM Business Layer.Billing';
```

Security translated from `RegionFilter` and `CreditScore` masking:

```sql
CREATE OR REPLACE ROW ACCESS POLICY SEC.RAP_REGION AS (region STRING) RETURNS BOOLEAN ->
    IS_ROLE_IN_SESSION('REPORT_ADMINS') OR IS_ROLE_IN_SESSION('DATA_ENGINEERS')
    OR IS_ROLE_IN_SESSION('EXECUTIVE_VIEWERS')
    OR EXISTS (SELECT 1 FROM SEC.MAP_USER_REGION m
               WHERE m.USERNAME = CURRENT_USER() AND m.REGION = region);
ALTER VIEW CORE.DIM_LOCATION ADD ROW ACCESS POLICY SEC.RAP_REGION ON (REGION);

CREATE OR REPLACE MASKING POLICY SEC.MP_CREDIT_SCORE AS (v NUMBER) RETURNS NUMBER ->
    CASE WHEN IS_ROLE_IN_SESSION('FINANCE_ANALYSTS') OR IS_ROLE_IN_SESSION('CREDIT_RISK_TEAM')
         THEN v ELSE NULL END;
```

Data product contract (excerpt):

```yaml
product: customer-billing-and-metering
owner: Energy Data Engineering Team
steward: analytics-team@energy-utility.com
classification: Internal - Restricted
retention: 7 years (FERC)
source_systems: [CC_AND_B_PROD]
outputs:
  - SEM.SV_BILLING_REVENUE
  - SEM.SV_METER_CONSUMPTION
  - DP_BILLING.OUT_BILLING_MONTHLY
freshness_sla: 24h
quality:
  - not_null: [FCT_BILLING.BILL_ID, FCT_BILLING.METER_ID]
  - referential: FCT_BILLING.METER_ID -> DIM_METER.METER_ID
  - accepted_values: {DIM_LOCATION.REGION: [North, South, East, West, Central]}
replaces_cognos_reports: 33 clusters (99 reports)
```

## 8. Requirements

Release 1 must take this exact bundle (one zip, nested zip, two spreadsheets) from upload to a reviewed, deployable Snowflake design without hand-editing any input.

### 8.1 Functional requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-01 | Upload a zip or folder of mixed Cognos artifacts; auto-detect each file's adapter; show an ingest summary with counts and rejected files | Must |
| FR-02 | Parse FM BMT 60/12 and 60/13 projects, including security and parameter maps, and diff `model.xml` vs `package.xml` | Must |
| FR-03 | Parse report specs (list, crosstab, chart) and resolve every data-item and filter expression to a model object or an inferred entity | Must |
| FR-04 | Load usage and package-to-source mapping; reconcile stated vs actual counts | Must |
| FR-05 | Connect read-only to the target platform catalog to match inferred entities to landed tables (name, fuzzy, column-overlap matching) | Should |
| FR-06 | Rationalize reports into intent clusters with disposition (Migrate, Merge, Retire, Defect) and configurable thresholds | Must |
| FR-07 | Classify entities as fact / dimension / bridge; detect conformed dimensions across packages | Must |
| FR-08 | Classify measure additivity and enforce correct aggregation; list reports whose numbers change (F6) | Must |
| FR-09 | Detect join-path issues: fan and chasm traps, missing relationships, ambiguous paths | Must |
| FR-10 | Propose aggregates from weighted grain demand with a coverage percentage and estimated credit cost | Must |
| FR-11 | Generate CORE, AGG, SEM, SEC, DP objects, semantic YAML, contracts and lineage per Section 7 | Must |
| FR-12 | Review workspace: approve, edit or reject any proposed object; edits persist across re-runs | Must |
| FR-13 | Deploy approved objects to a target account through a CI pipeline (Git branch + Snowflake CLI / schemachange), never directly from the UI in production | Must |
| FR-14 | Parity testing: run Cognos-equivalent SQL and semantic view queries for sampled reports and compare row counts and totals within tolerance | Should |
| FR-15 | LLM assist: draft descriptions, synonyms and verified queries; all LLM output is marked as suggested until a steward accepts it | Should |
| FR-16 | Incremental re-run: a new export produces a diff (added, changed, removed objects) rather than a full rebuild | Should |
| FR-17 | Generate Databricks metric views and dbt projects from the same design | Could |
| FR-18 | Export the design workbook and findings for client sign-off | Must |

### 8.2 User interface

1. **Ingest** — drop zone, detected file list, parser warnings.
2. **Estate overview** — packages, reports by disposition, runs/day by package, duplicate clusters, dormant content.
3. **Model canvas** — entity-relationship graph with confidence colouring; click an entity for attributes, measures, lineage and the reports that use it.
4. **Findings** — filterable register, owner assignment, status.
5. **Design review** — per layer, the proposed objects with generated SQL side by side with Cognos source expressions; approve / edit / reject.
6. **Aggregate planner** — grain demand heatmap per fact, chosen aggregates, coverage and cost.
7. **Deploy and validate** — Git push status, deployment log, parity results.

### 8.3 Validation rules

- Every active, non-retired report item must resolve to exactly one semantic dimension, fact or metric, or carry an open finding.
- No generated metric may sum a measure classified as semi- or non-additive.
- Every Cognos security rule must map to a platform policy; unmapped rules block deployment.
- Every target object must have an owner, a classification tag and a comment.
- Generated SQL must compile (`EXPLAIN` against the target) before it can be approved.

### 8.4 Non-functional requirements

| Area | Requirement |
| --- | --- |
| Scale | Parse 70,000 reports and 200 FM packages in under 60 minutes on a 4-vCPU worker; this export (1.5 MB report XML) in under 1 minute |
| Security | Runs inside the client tenant (Snowpark Container Services or client VPC); inputs never leave it; LLM calls go to Cortex or an approved endpoint; no credentials stored in exports (the `.ds` file's JDBC URL is masked in outputs) |
| Auditability | Every generated object records the tool version, rule IDs and source evidence that produced it |
| Extensibility | New adapters (Power BI PBIX / TMDL, BusinessObjects universes, MicroStrategy) and generators plug in through defined interfaces |
| Determinism | Same inputs and configuration produce byte-identical DDL |
| Tech stack | Python 3.12 (lxml, pandas, sqlglot for SQL dialects, ANTLR Cognos expression grammar, networkx), FastAPI, React UI, Postgres repository; packaged as a container |

## 9. Delivery roadmap, risks and open questions

The proposed plan delivers a working billing data product in 8 weeks, because billing is the only domain fully backed by the FM model, and reaches all six products by week 14.

&#91;embedded content: delivery roadmap · 4 phases, 3 gates\]

Gate 2 parity means the top 20 billing reports by runs/day reconcile to the semantic views within ±0.5% on totals, after excluding the aggregation corrections listed under F6.

### 9.1 Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Five of six packages have no FM model (F1) | Inferred entities may mis-state grain or keys | Require source catalog access in Phase 0; steward review for confidence < 0.6 |
| Business users rely on the wrong totals (F6) | Numbers change after migration and trust drops | Publish a “numbers that will change” list per report owner before cut-over |
| Duplicates carry 68% of runs (F3) | Retiring copies breaks bookmarks and schedules | Redirect map from each retired report to its canonical replacement and semantic view |
| Customer mastering across CC&B and Salesforce | Conformed DIM\_CUSTOMER cannot be built from Cognos metadata alone | Dependency on MDM or a match-key agreement; ship domain-local customer dims first |
| OSIsoft PI time-series grain | Generation facts may be far finer than Cognos shows | Model PI tags as interval facts with standard rollups (15 min, hour, day) |
| Semantic view feature gaps by platform | Some Cognos constructs (dimensional models, macros) have no direct equivalent | Flag as manual-design items; keep a construct coverage matrix per release |

### 9.2 Open questions

- [ ] Which data platform and accounts are in scope — Snowflake only, or Databricks as well?
- [ ] Are FM models available for the Operations, Generation, Compliance, Finance and Customer Service packages and their 11 data modules?
- [ ] Is a catalog of the landed source schemas (ENERGY\_OPS\_DW, CC&B, PI, SAP FICA, Salesforce) available, and in what form?
- [ ] What look-back window and runs/day threshold define “Retire” (default proposed: no run in 180 days or 0 runs/day)?
- [ ] Who owns fixes for the 66 FiscalYear-vs-Region filter defects (F7)?
- [ ] Should the semantic layer correct the six mis-aggregated measures (F6) or replicate Cognos totals for a transition period?
- [ ] Is BillAmount access governed by the 4-role grant in `objectlevelsecurity.xml` or the 2-role grant in `model.xml`?
- [ ] Which BI tools consume the semantic views after cut-over (Power BI, Sigma, Cortex Analyst / Snowflake Intelligence)?
