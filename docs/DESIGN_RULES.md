# SemLift design rules and requirement coverage

Every generated object records the rule IDs that produced it, in its DDL header and in the design workbook. All rules are deterministic and configurable (`semlift/config.py` plus the estate YAML). An LLM is only used to draft descriptions and synonyms, and those stay *suggested* until a steward accepts them.

## Rule catalogue

| Rule | Stage | What it does |
| --- | --- | --- |
| ING-01 | Ingest | Unpacks archives recursively, nested zips included, into an isolated work folder with zip-slip protection |
| ING-02 | Ingest | Detects the adapter from the XML root and namespace, or from an XLSX/CSV header found in the first 10 rows |
| ING-03 | Ingest | When both `model.xml` and `package.xml` exist, diffs them structurally; `package.xml` (published) wins |
| ING-04 | Ingest | Dedicated security files win over the `<security>` block embedded in the model (`security.precedence`). Rules found only in the other source are still carried; differing grants raise F9 |
| ING-05 | Ingest | Joins usage to reports on `report_name`, then on `report_path`; orphans are reported (F17) |
| RES-01 | Model | `[pkg].[QS].[item]` resolves to the FM Business Layer by query-subject name. Otherwise an **inferred** entity or item is created (F1) |
| RES-02 | Model | Items missing from an FM entity are matched by name to the FM physical columns (confidence 0.6), e.g. `Billing.DueDate → DUE_DATE` (F9) |
| RES-03 | Model | Landed catalog matching (FR-05) by exact name, fuzzy name (≥ 0.85) or column overlap (≥ 0.6). A match raises confidence to 1.0 for FM objects and 0.6 for inferred ones |
| ADD-01 | Model | An FM `regularAggregate` sets aggregation and additivity: total→SUM, maximum→MAX (semi), average→AVG (non), calculated→ratio metric |
| ADD-02..06 | Model | Name heuristics for inferred measures: Pct/Rate/Ratio/Per/Price/Score/Days… → AVG (non); Peak/Capacity/Limit… → MAX (semi); power units MW/KW → AVG (semi); Amount/Count/Cost/KWh… → SUM |
| CLS-01 | Model | FM entity on the *n* side with facts → fact. Inferred entity with measures or an event-like name → fact. Otherwise dimension |
| CLS-02 | Model | An entity used by more than one report package → conformed dimension, with core and per-package extension attributes (F10) |
| DIM-02 | Model | Inferred master entity (Substation, Plant, Asset, Line, Project) with dynamic measures → `DIM_<E>` (descriptive + static measures) + `FCT_<process>` |
| DIM-03 | Model | Reference attributes on facts (`*ID`, or configured ones such as StandardRef or CauseCode) → outrigger dimensions |
| REL-INF-01 | Model | An inferred fact co-used with a dimension in a report query gets an inferred n:1 relationship (confidence 0.3) |
| REL-INF-02 | Model | An FM fact co-used with Date but without a Date relationship gets a date key derived from its date attribute (`TO_NUMBER(TO_CHAR(x,'YYYYMMDD'))`) |
| JP-01 | Model | Join diagnostics per active report query: fan trap (path needs a 1:n step), chasm trap (two facts in one query), ambiguous path, missing relationship (F14) |
| RAT-01 | Rationalize | Group by `duplicateGroupID`, or by Jaccard on resolved items and filters when it is absent |
| RAT-02 | Rationalize | Canonical member = Active, unless a duplicate has more runs/day **and** a superset of columns |
| RAT-03 | Rationalize | Cluster contract = union of member items. Community extras are kept only if they ran inside the look-back window |
| RAT-04 | Rationalize | A cluster is retired when no member has runs/day > threshold within the look-back window (default 180 days) |
| SRC-01 | Design | A domain entity is routed to its package's landed source (`RAW_<SYSTEM>` from the mapping sheet) |
| SRC-02 | Design | A conformed FM dimension is sourced from the FM model's own enterprise data source |
| CORE-01/02 | Design | `CORE.DIM_<E>` (with a hash surrogate key) and `CORE.FCT_<process>` views; rename-only items become aliases |
| CORE-03 | Design | An inferred entity becomes a **stub**: TODO source mapping, confidence < 0.6, never auto-deployed |
| CORE-04 | Design | Row-level FM calculations (TotalBillWithTax, IsOverdue, ConsumptionMWh) become derived columns. Ratios are never stored |
| CORE-05 | Design | Hard-coded factors move to `REF.REF_EMISSION_FACTOR` and are joined with effective dating (F12) |
| CORE-06 | Design | A conformed dimension is published once in the Enterprise Reference product |
| CORE-07 | Design | Foreign keys come from FM relationships (documented RELY constraints) |
| CORE-08 | Design | An item demanded by reports but absent from both FM and catalog → typed `NULL` placeholder plus finding. The table stays compilable |
| CORE-09 | Design | Tags DOMAIN, DATA_OWNER, DATA_CLASSIFICATION, RETENTION and SENSITIVE, plus a COMMENT on every object and column |
| REF-01 | Design | Parameter maps → `REF.PARAM_DEFINITION` plus one `REF.PARAM_<NAME>` value table per pick list |
| SEC-01 | Design | A `select … from USER_*_ACCESS where USERNAME = session_user()` subselect → `SEC.MAP_USER_<SCOPE>` view |
| SEC-02 | Design | `securityFilter` → row access policy (exempt roles bypass; cross-entity predicates use an `EXISTS` lookup), attached inline to the CORE view |
| SEC-03 | Design | Column masks → dedicated masking policies. Column grants → `MP_RESTRICTED_AMOUNT`/`_TEXT`, driven by `SEC.MAP_ROLE_GRANT` through the ACCESS_GROUP tag |
| SEC-04 | Design | ABAC deny policies → conditions evaluated in every masking policy, keyed on the ABAC_POLICY tag; user attributes come from `SEC.MAP_USER_ATTRIBUTE` |
| SEC-05 | Design | Namespace visibility → schema grants. Cognos *denied* roles become documented non-grants |
| AGG-01 | Design | Grain signature per surviving cluster = fact + demanded dimension attributes reachable along n:1 paths |
| AGG-02 | Design | Greedy cover over signatures and their unions, rolled up through hierarchies: up to 3 per fact, target 80% of weighted demand (runs/day × avg duration), at least 10× smaller than the fact, each serving ≥ 5% of demand |
| AGG-03 | Design | MonthNumber is added beside MonthName as a sort companion |
| AGG-04 | Design | Only additive measures are pre-summed. Semi/non-additive measures are stored as SUM + COUNT (or MAX/MIN) components. Dynamic tables re-apply source masking and row policies |
| SEM-01 | Design | One semantic view per configured subject area (default: one per fact). Tables = members + n:1-reachable dimensions |
| SEM-02 | Design | Dimensions and facts = items demanded by the view's live clusters. Metrics use FM default aggregation, never the report override (F6). Ratios are `SUM(a)/NULLIF(SUM(b),0)` |
| SEM-03 | Design | Synonyms from business names and report labels. Sample values come from pick lists. Required prompts become default filters. Up to 10 verified queries per view |
| DP-01 | Design | One product per package plus Enterprise Reference. Secure `DP_<DOMAIN>.OUT_*` views over aggregates or atomic facts |
| DP-02 | Design | Share plus internal marketplace listing (unpublished), and an ODCS-style contract with quality rules |

## Report rationalization (page 1)

| Rule | Outcome | Condition |
| --- | --- | --- |
| R1 | Retire | Every copy in the duplicate group lacks demand (0 runs/day or no run in the look-back window, default 180 days) |
| R2 | Consolidate | Archive / community copy of a live report; redirect to the canonical report, or to the report it in turn consolidates into |
| R3 | Review | Live report needing a decision: filter defect, totals that change while the KPI rule is not yet approved, use of a non-approved KPI definition, group usage below `review_min_runs_per_day` or no run in `review_stale_days`, duplicate data items |
| R4 | Consolidate | All of its KPIs exist in another live report of the same package and dimension overlap ≥ `consolidate_dim_jaccard` (default 0.6); with equal KPI sets the busier report survives |
| R5 | Keep | Distinct report intent in demand |

Usage is judged on the whole duplicate group, so a canonical report whose archive copy is busy stays in scope. Steward decisions override the recommendation.

## Common KPIs (page 3)

| Kind | Detected when | Recommended definition |
| --- | --- | --- |
| Aggregation rule | Reports aggregate a measure differently from its FM / semantic default (e.g. SUM of CapacityFactorPct, FM says AVG) | FM / semantic default |
| Filter rule | The same measure is reported under different literal filters (e.g. BillAmount for all bills vs `PaymentStatus = 'Overdue'`) | Unfiltered base definition; filtered variants become slices |
| Business definition | One business KPI is implemented by different items across packages (`kpi_concepts` in the estate YAML, or the same normalized name on different entities) | FM-defined item with the most live reports |

**KPI-01:** an approved aggregation rule overrides the measure's default aggregation in the semantic views and aggregates, and is recorded as finding F21.

## Databases & tables (page 4)

Physical objects are resolved from the FM physical layer when the item is FM-defined (database = FM data source, e.g. ENERGY_DW). Otherwise they are inferred from the package-to-source mapping, with the schema marked "to confirm". Objects used only by Review reports are flagged and default to scope **Review**.

## Validation rules (spec 8.3)

| Rule | Implementation |
| --- | --- |
| V1 | Every active, non-retired report item maps to a semantic dimension, fact or metric, or carries an open finding |
| V2 | No semantic metric or aggregate sums a semi- or non-additive measure |
| V3 | Every Cognos security rule maps to a policy, a grant table row or a schema grant. Unmapped rules raise blocking finding F16 and `deploy` refuses to run |
| V4 | Every object has an owner, a classification tag and a comment |
| V5 | Every object's SQL is parsed offline (sqlglot, Snowflake dialect); with a connection, `EXPLAIN` runs as well. Approval is refused for objects that fail |

## Requirement coverage

| ID | Status | Where |
| --- | --- | --- |
| FR-01 | Done | `ingest/unpack.py`, Ingest screen (drop zone, detected files, warnings, rejected files) |
| FR-02 | Done | `ingest/fm.py` (BMT 60/12 and 60/13, security, parameter maps, model vs package diff) |
| FR-03 | Done | `ingest/reports.py`, `analyze/resolve.py` |
| FR-04 | Done | `ingest/sheets.py`, count reconciliation (F11) |
| FR-05 | Done (CSV catalog; live `INFORMATION_SCHEMA` export can be supplied as CSV) | `analyze/resolve.py::_match_catalog`, `semlift run --catalog` |
| FR-06 | Done | `analyze/rationalize.py`, configurable thresholds |
| FR-07 | Done | `analyze/classify.py` |
| FR-08 | Done | `analyze/classify.py`, F6 "numbers that will change" list |
| FR-09 | Done | `analyze/joins.py` |
| FR-10 | Done | `analyze/aggregates.py` (coverage %, estimated credits/day) |
| FR-11 | Done | `design/*`, `generate/*` |
| FR-12 | Done | `service/workspace.py` review (approve/edit/reject; persisted, flagged when the generated SQL changes) |
| FR-13 | Done | `Workspace.deploy` writes approved objects to a Git branch with a GitHub Actions, schemachange and Snowflake CLI pipeline; the UI never deploys directly |
| FR-14 | Done (execution needs a Snowflake connection) | `generate/artifacts.py::parity_sql`, `Workspace.run_parity` |
| FR-15 | Done | `service/llm.py` (template / Cortex / Anthropic providers; suggestions need steward acceptance) |
| FR-16 | Done | Per-run object hashes and an added/changed/removed diff |
| FR-17 | Done | `semantic/databricks/*.yaml`, `dbt/` |
| FR-18 | Done | `design_workbook.xlsx`, `findings.md`, downloads in the UI |

## Implementation notes and deviations

- **Cognos expression grammar.** The spec names ANTLR. SemLift uses a hand-written recursive-descent parser with the same grammar (documented in `semlift/expr.py`), which avoids a generated-code build step. Malformed expressions such as `= < 0.3` are rejected and raised as F13.
- **Repository.** SQLite by default and Postgres through `SEMLIFT_DB_URL`. Every output package also carries a `meta/` mirror and a load script for a Snowflake `SEMLIFT_META` schema.
- **Live platform features.** EXPLAIN compile checks, parity execution and the Cortex LLM provider need a Snowflake connection, which is not available offline. Without one, compile checks run offline with sqlglot and parity results report `not_run`.
- **Python version.** The spec targets Python 3.12. The code runs on 3.11+ and the container uses 3.12.
- **Row security semantics.** Cognos applies a filter only to its `appliesTo` roles. Generated policies are deny-by-default for every non-exempt role, matching the spec sample; `security.rls_default_deny: false` mirrors Cognos exactly (F20).
- **Masked values.** For numeric columns the Cognos masked text (e.g. `*** Restricted ***`) cannot be returned, so NULL is returned instead and the policy comment records this.
