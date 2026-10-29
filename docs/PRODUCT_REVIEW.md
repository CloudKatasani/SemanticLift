# SemanticLift product review: readiness for enterprise, multi-client scale

This review looks at SemanticLift as a product company would: who uses it, what they must trust, and what breaks when one deployment serves many client engagements at once. It records what was changed in this round and what remains on the roadmap, in priority order.

## Verdict

The analytical core was strong and differentiated. It produces evidence-based rationalization, KPI conflict resolution, a conformed model, semantic views and data products, and every recommendation names its rule and source. Output is deterministic, and nothing deploys without a person's approval.

What held it back was the shell around that core. It was built for one consultant working on one estate:

- one shared workspace
- one shared password
- a free-text reviewer name
- no audit trail
- pipeline runs that block the request
- energy-industry names built into the code

Those six gaps blocked a multi-client rollout. All six are fixed in this round. The remaining gaps limit scale (more replicas, more BI sources), not correctness or governance.

## What already worked (keep)

| Strength | Why it matters commercially |
| --- | --- |
| Evidence on every recommendation (rule ID, usage, KPI overlap, source) | Client owners can challenge a decision instead of rejecting the tool |
| Deterministic DDL (same inputs and configuration give byte-identical output) | Re-runs are safe; diffs show only real change |
| A person decides before anything changes; deploys go through Git and CI, never the UI | Passes client change-management and security reviews |
| Story-led UX (Strategy & approach → steps 1–7) | Sponsors understand the approach without a walkthrough |
| A platform-neutral canonical graph | New BI sources and targets are adapters, not rewrites |

## Gaps found and fixed in this round

| # | Gap (product lens) | Severity for multi-client | Change |
| --- | --- | --- | --- |
| 1 | One global workspace, so every client's data shares one folder | Blocker | **Client projects.** A registry under `SEMLIFT_HOME`. Each project has its own uploads, configuration, decisions, runs, output package and audit trail. Every API call is scoped by the `X-SemLift-Project` header. A project switcher sits in the UI and there is a portfolio page across clients. Projects can be archived (read-only). |
| 2 | One shared token, so every user is an anonymous administrator | Blocker | **Identity and roles.** Four sources: SSO through an authenticating proxy (OIDC/SAML via oauth2-proxy or a gateway, mapping IdP groups to roles), personal tokens stored as SHA-256 hashes, the legacy shared token, or open mode for evaluation only. Six roles (viewer, analyst, steward, approver, deployer, admin) are granted per project pattern, e.g. `acme-*`. Users only see the projects they have access to. |
| 3 | The reviewer name came from the request body, so anyone could approve as anyone | Blocker | The reviewer is now taken from the signed-in identity. A name in the request body is trusted only in open mode. |
| 4 | No audit trail | Blocker for regulated clients | **Append-only audit log per project.** It records uploads, runs, report/KPI/source decisions, object reviews, findings, suggestions, deployments, settings and project changes. Available as the Audit trail page with CSV export, through `GET /api/audit`, and in the CLI. Git commits carry the deployer's name. |
| 5 | Runs held the HTTP request open; parallel runs could corrupt a workspace | High | **Background jobs.** Polling, one run per project, and `SEMLIFT_MAX_CONCURRENT_RUNS` across projects. State files are written atomically, so readers never see half-written JSON. |
| 6 | Energy-client specifics hard-coded (package prefix `Energy_`, utility glossary, "utility" in LLM prompts, ENERGY_DW text in the UI) | High | Moved to estate configuration: `naming.package_affixes`, `glossary`, `llm.domain`. The UI reads package affixes from the project's configuration. Generated output for the sample is unchanged. |
| 7 | Configuration typos silently did nothing | Medium | `validate_config`: unknown keys and wrong types become warnings, shown after every run and available via `semlift config check`. New `config/template_estate.yaml` as the onboarding starting point. |
| 8 | Downloads were plain links, so they failed whenever auth was on | Medium | Downloads go through the authenticated client with the project header. |
| 9 | Segregation of duties not enforceable | Medium (regulated clients) | `governance.four_eyes`: an approver may not approve DDL they edited themselves. |
| 10 | No request tracing | Medium | Access log with user, project, status, duration and `X-Request-ID`; Docker `HEALTHCHECK`. |

Backward compatibility:
- An existing `SEMLIFT_WORKSPACE` appears as project `default`.
- The CLI still accepts `-w` and also accepts `-p <project>`.
- `semanticlift` is added as an alias of the `semlift` command.

## Roadmap (not in this round), in priority order

1. **Shared state store for high availability.** Project state is file-based: atomic writes, safe for one replica with any number of projects. To run several replicas, move decisions, audit and the registry to Postgres (the canonical-graph mirror already supports `SEMLIFT_DB_URL`) and output packages to object storage. The job queue moves with it, for example to the database or Redis.
2. **Scale benchmark.** The largest estate tested is the 588-report sample (about 0.6 s of pipeline time). Build a synthetic estate of 20,000 reports and 200,000 data items, then set and publish limits. Paginate the portfolio and lineage APIs, which currently return whole views gzip-compressed.
3. **Native OIDC and SCIM** so clients without a proxy can connect their IdP directly, with automatic user provisioning and removal.
4. **More BI sources.** Add adapters for Power BI, Tableau, MicroStrategy and BusinessObjects into the same canonical graph. Pull exports straight from the Cognos REST/Content Manager API instead of uploading.
5. **Data lifecycle per client.** Project purge with a certificate of deletion, configurable retention, encryption at rest guidance, and a per-project region and storage location for data residency.
6. **Role-aware UI.** The server already enforces every role and the UI explains refusals. Next, hide or disable controls the user cannot use.
7. **Delivery analytics.** Time from upload to first decision, decision throughput per steward, and blocked items, shown per client on the Projects page.
8. **Extensibility and commercial.** A versioned public API and adapter SDK, and per-project usage metering for licensing.

## How to judge success at scale

- **Onboarding:** a new client goes from project creation to first rationalization in under one day, using `template_estate.yaml`.
- **Access and accountability:** no access across projects, and every change attributable to a named person (audit trail complete).
- **Rework:** steward decisions survive every re-run, so nothing has to be re-decided.
- **Throughput:** pipeline time stays under 5 minutes for a 20,000-report estate (benchmark still to be built).
