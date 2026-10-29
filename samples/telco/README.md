# Telco test estate

`samples/Cognos Telco Input.zip` is a synthetic Cognos Analytics 12 export for a telecommunications operator, made to test SemanticLift on a second industry. It has the same layout and file formats as the energy sample, so it needs no code changes. Regenerate it with:

```bash
python samples/telco/generate_telco_bundle.py
```

## What is in it

| File | Content |
| --- | --- |
| `FM/telco_fm_package_v12.zip` | Framework Manager project for `Telco_Analytics_Package` on Oracle `TELCO_DW`. It contains 10 business query subjects: Subscriber, Account, Location, Plan, Date, Device, CellSite, UsageRecord, Invoice and NetworkKPI. It has 12 relationships, calculated items, a parameter map, row-level security, column masking and ABAC. |
| `Reports/.../all_reports.xml` | 626 reports in 6 packages (Network, Billing, Customer, Sales, Finance, Regulatory): 243 active, 200 archive copies and 183 community copies |
| `cognos_report_usage_telco.xlsx` | Runs per day, last run date and average duration for every report |
| `FM_Data_Module_Mapping_Telco.xlsx` | Package and data module → source system: Teradata, Oracle Amdocs, Salesforce, SAP HANA and SQL Server |
| `source_catalog_telco.csv` | Landed-table catalog for four inferred entities |

## Problems planted for SemanticLift to find

| Problem | Where to look |
| --- | --- |
| About a third of the report groups are dormant | 1. Report rationalization (Retire) |
| Archive and community copies, some with a column dropped or added | 1. Report rationalization (Consolidate) |
| Active reports that are idle while their archive copy is busy | 1. Report rationalization (usage judged across copies) |
| Reports whose KPIs are a subset of a busier report in the same package | 1. Report rationalization (R4 consolidation) |
| Non-additive measures (drop call rate, throughput, availability, NPS, churn rate) summed in some reports and averaged in others | 3. Common KPIs (aggregation rule) |
| The same KPI under different filters (overdue invoices, roaming usage, P1 tickets, 5G traffic, online orders) | 3. Common KPIs (filter rule) |
| Revenue and data volume defined differently across packages | 3. Common KPIs (business definition, via `kpi_concepts`) |
| `FiscalYear = ?p_Region?`, `FiscalYear = 'FY2026'` and a malformed `in ?p_Region` prompt | Findings |
| TroubleTicket, ChurnEvent, CareInteraction, SalesOrder, BudgetActual, E911Call and others missing from the FM model | Findings, 5. Logical data model (inferred entities) |
| Row security on the inferred BudgetActual and ComplianceCase | Findings, Design review (SEC objects) |
| CPNI masking on MSISDN and credit score, and an ABAC policy | 6. Data products (business logic) |
| Hard-coded USF contribution rate (`InvoiceAmount * 0.364`) | Findings (constant moved to a REF table) |
| `model.xml` differs from the published `package.xml` (AvailabilityPct aggregation) | Findings (model drift) |
| The usage title states more reports than the export contains | Upload & run (stated vs actual counts) |

## Test it in the app

1. Start the app: `semlift serve`, or the container.
2. Optional: on **Client projects** (Administration), create a project, for example client "Telco Co" and project "Cognos wave 1", with starting configuration **telco_estate**.
3. On **Upload & run**, upload `Cognos Telco Input.zip`, choose the **telco_estate** configuration and click **Run pipeline**.
4. Work through **Strategy & approach** and pages 1–7. `config/telco_estate.yaml` turns on `governance.four_eyes`, so an approver cannot approve DDL they edited themselves.
