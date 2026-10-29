# SemanticLift — Cognos-to-Data-Platform Semantic Layer Migrator

SemanticLift ingests a Cognos estate export and works out which business logic lives in the BI semantic layer. It then generates a governed semantic model on Snowflake: deployable DDL, semantic views, data product contracts and a traceability matrix that maps every surviving report column to its new home. Databricks metric views and a dbt project are generated from the same intermediate model.

SemanticLift serves many client engagements from one deployment: each client project is isolated, access is granted per project and role (with single sign-on through an authenticating proxy), every change is recorded in an audit trail, and pipeline runs execute in the background. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md) to run it and [`docs/PRODUCT_REVIEW.md`](docs/PRODUCT_REVIEW.md) for the enterprise-readiness review and roadmap.

The full specification is in [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md). The design rule catalogue and requirement coverage are in [`docs/DESIGN_RULES.md`](docs/DESIGN_RULES.md). The sample bundle is [`samples/Cognos Lineage Input.zip`](samples/) (energy utility). A second, synthetic telecommunications estate for testing is [`samples/Cognos Telco Input.zip`](samples/telco/README.md) with [`config/telco_estate.yaml`](config/telco_estate.yaml), and [`examples/energy_output/`](examples/energy_output/) holds the package generated from it.

## Quick start

```bash
pip install -e ".[dev]"                     # Python 3.11+
semlift run "samples/Cognos Lineage Input.zip" -c config/energy_estate.yaml
#   -> workspace/output/  (ddl/, semantic/, dbt/, contracts/, design_workbook.xlsx, findings.md, lineage.json, ...)

cd ui && npm ci && npm run build && cd ..   # build the web UI once
semlift serve                                # http://127.0.0.1:8000  (API docs at /docs)

# multi-client mode: one project per client under SEMLIFT_HOME
export SEMLIFT_HOME=$PWD/semlift_home
semlift projects create "Cognos wave 1" --client Acme -c config/energy_estate.yaml
semlift -p acme-cognos-wave-1 run "samples/Cognos Lineage Input.zip"
semlift serve
```

Or run the container:

```bash
docker build -t semlift . && docker run -p 8000:8000 -v $PWD/data:/data semlift
```

### CLI

| Command | Purpose |
| --- | --- |
| `semlift run <zip/folder> [-c config.yaml] [--catalog catalog.csv] [--live-compile]` | Stages 1–4: ingest, rationalize, design, generate the package |
| `semlift review <object-id> approve\|reject\|reset [--ack]` | Record a review decision (`--ack` lets a steward approve an inferred object below 0.6 confidence) |
| `semlift approve-all` | Approve every proposed object at or above the confidence threshold whose SQL compiles |
| `semlift deploy [--branch B] [--remote URL --push]` | Commit the approved objects to a Git branch with a CI pipeline (schemachange or Snowflake CLI) |
| `semlift parity` | Run the parity SQL against Snowflake (needs `SEMLIFT_SNOWFLAKE_*`) |
| `semlift serve` / `semlift summary` | Start the API and UI, or print the last run summary |
| `semlift projects list\|create NAME [--client C] [-c config.yaml]` | List or create client projects under `SEMLIFT_HOME`; any command takes `-p PROJECT` instead of `-w PATH` |
| `semlift config check config.yaml` | Report unknown settings and wrong value types in an estate configuration |
| `semlift token` | Generate a personal API token and the hash to put in the users file |

## Pipeline

```
 1 Ingest        unpack (nested zips) -> detect adapter per file -> parse into the canonical graph
 2 Model         resolve report items to FM or inferred entities, classify facts/dims & measure additivity,
                 infer relationships from co-usage, diagnose fan/chasm traps
 3 Rationalize   duplicate groups -> intent clusters -> Migrate / Merge / Retire / Defect fix needed
 4 Design        CORE, REF, SEC, AGG, SEM, DP objects + validation rules (spec 8.3) + findings register
 5 Review        human checkpoint: approve / edit / reject; decisions persist across re-runs
 6 Deploy        approved objects -> Git branch -> CI (schemachange / Snowflake CLI); never from the UI
 7 Validate      parity SQL: Cognos-equivalent query vs semantic view, within tolerance
```

| Package | Contents |
| --- | --- |
| `semlift/ingest` | Adapters FM-PROJ, FM-NS, FM-SEC, FM-PARAM, FM-DS, RPT, USAGE, MAP and SRC-CAT, each with provenance (file + XPath or sheet!row) |
| `semlift/expr.py` | Cognos expression grammar: tokenizer, recursive-descent parser, AST and Snowflake SQL translation |
| `semlift/model.py` | Canonical, platform-neutral metadata graph (spec section 5) |
| `semlift/analyze` | Resolution, catalog matching, classification, rationalization, join diagnostics, aggregate planning, findings |
| `semlift/design` | Design engine that turns the canonical graph into a physical design, and naming rules |
| `semlift/generate` | Snowflake DDL, Cortex semantic YAML, Databricks metric views, dbt, contracts, OpenLineage, traceability, parity SQL, workbook |
| `semlift/service` | Workspace (runs, review, diff, deploy, parity, audit), project registry, identity and roles, background jobs, compile checks, LLM assist, metadata repository, CI templates |
| `semlift/api` | FastAPI service used by the UI |
| `ui/` | React UI. Two overview pages. **Product overview** (opens first) is the pitch: the problem a large BI estate creates, the eight steps as one arrow strip, figures from the current project or the bundled sample, manual migration vs SemanticLift, enterprise capabilities, value per role and where it fits. **Strategy & approach** is the playbook: for each step why it matters, what SemanticLift does, a guideline for the team, the outcome, the decision needed and, once the project has a run, its live figures. Under Administration, **Client projects** lists every engagement the user can access with its progress (the current project and a Change link sit at the foot of the menu), and the **Cognos export guide** tells Cognos administrators how to export each input with column definitions, starting queries and CSV templates. **Audit trail** shows every change. Migration workflow: 1. Report rationalization (Keep / Review / Consolidate / Retire with evidence and overrides), 2. KPI lineage (KPI → FM → report → database → schema → table), 3. Common KPIs (competing definitions; approve the correct one), 4. Databases & tables in scope (Keep + Review reports, review-only objects flagged), 5. Logical data model, 6. Data products & semantic layer (business logic moved, semantic and aggregated views, outputs, lineage), 7. Object lineage (for every platform object: source tables, upstream objects, the aggregates, semantic views and data products it feeds, and the Cognos reports it serves with their outcome). Plus Upload & run, Findings, Design review, Deploy & validate and Model canvas |

## Results on the supplied export

One run takes about 0.6 s of pipeline time (about 2.5 s including the package and workbook). It reproduces the findings in spec section 2.2:

| # | Reproduced |
| --- | --- |
| F1 | 39 package-level query subjects; 17 resolve to the FM model; **612** active data-item references have no FM definition |
| F2 | **196** duplicate groups; archive column set equals active in **134** groups |
| F3 | Runs/day Active 1,000 · Archive 1,048 · Community 1,087; duplicates draw **68%** of runs |
| F4 | **134** reports with 0 runs/day; **338** last run before 2026-01-01; 100 clusters retired (180-day window) |
| F5 | 4,101 of 4,101 data items are direct references; aggregates only `none` / `total` |
| F6 | CapacityFactorPct 11, CapacityMW 9, PeakDemandKW 7, RatePerKWh 5, CO2FactorKgKWh 3, DemandChargeRate 1 (FM-defined), plus 24 inferred measures |
| F7 | **66** filters compare `[Date].[FiscalYear]` to `?p_Region?` (type mismatch); 24 further filters with type or prompt-semantics mismatches |
| F8 | **24 of 65** Business-layer items unused, including TotalBillWithTax, IsOverdue, CO2IntensityKgPerMWh and PeakOffPeakRatio |
| F9 | DueDate, ServiceTier, FuelCostPerMWh, SAIFI/MAIFI, CauseDescription absent from FM; RLS on DataSubmission and BudgetActual; BillAmount 4-role vs 2-role grant |
| F10 | Conformed Date, Location and Customer, with core attributes and package extensions |
| F11 | Usage title states 600 / 200, actual 588 / 196 |
| F12 | `CO2EstimateKg` literal 0.233 moved to `REF.REF_EMISSION_FACTOR` (effective-dated) |

Design output: 32 logical entities, 148 target objects (52 proposed, 96 stubs that depend on inferred entities), 23 demand-driven aggregates, 11 semantic views, 7 data products, 4 row access policies, 5 masking policies. The fan trap Billing → Meter ← MeterReading → Tariff is detected, and TariffType is left out of the billing aggregates.

## Steward decisions

Pages 1, 3 and 4 record decisions in the project's `review/portfolio_decisions.json`, attributed to the signed-in user and written to the audit trail: report dispositions, approved KPI definitions and source scope. A banner offers **Apply decisions (re-run)**. On re-run:

- A report forced to Keep or Review brings its duplicate group back into the design. One set to Retire drops it.
- An approved aggregation rule becomes the semantic-layer aggregation. Choosing SUM for a non-additive KPI is allowed but recorded as finding F21.
- Reports that use a definition other than the approved one move to Review.

## Configuration

`semlift/config.py` holds the generic defaults: thresholds, confidence levels, additivity patterns, cardinality estimates and the aggregate planner budget. An estate YAML such as [`config/energy_estate.yaml`](config/energy_estate.yaml) is merged on top and supplies names, boundaries and vocabulary: product names, domain codes, package-name affixes, fact names for split entities, reference attributes, policy names, subject areas, RAW schema routing, the industry glossary and governance options such as `four_eyes`. Start a new client from [`config/template_estate.yaml`](config/template_estate.yaml); unknown settings and wrong types are reported after every run. The same inputs and configuration always produce byte-identical DDL.

Environment variables:

| Variable | Use |
| --- | --- |
| `SEMLIFT_HOME` | Root of the multi-client project registry (one isolated workspace per project) |
| `SEMLIFT_WORKSPACE` | Legacy single workspace; appears as project `default` |
| `SEMLIFT_USERS_FILE` | Users, personal token hashes and IdP group → per-project roles |
| `SEMLIFT_TRUST_PROXY_HEADERS` | `1` to take identity from an SSO proxy (`X-Forwarded-Email`, `X-Forwarded-Groups`) |
| `SEMLIFT_API_TOKEN` | Legacy shared administrator token (`Authorization: Bearer <token>`) |
| `SEMLIFT_MAX_CONCURRENT_RUNS` | Background pipeline runs at once across projects (default 2) |
| `SEMLIFT_ENV` | Shown in the UI; deployment is always Git + CI regardless |
| `SEMLIFT_SNOWFLAKE_ACCOUNT`, `_USER`, `_ROLE`, `_WAREHOUSE`, `_DATABASE`, `_AUTHENTICATOR` | Optional live connection for EXPLAIN compile checks, parity runs and the Cortex LLM provider |
| `SEMLIFT_DB_URL` | `postgresql://…` to store the canonical graph in Postgres (default: SQLite `workspace/semlift.db`) |
| `ANTHROPIC_API_KEY` | Used only when `llm.provider: anthropic` is configured |

## Tests

```bash
python -m pytest -q        # 71 tests: units, the F1–F12 reproduction, design invariants, determinism, workspace and API
```
