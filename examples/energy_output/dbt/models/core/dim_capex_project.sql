-- Dimension for CapexProject (split from report usage, rule DIM-02). Source: RAW_SAP_FICA.CAPEX_PROJECT (TODO confirm)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.CAPEX_PROJECT_ID as capex_project_id,
    src.CATEGORY as category,
    src.PROJECT_NAME as project_name,
    src.STATUS as status,
    src.APPROVED_BUDGET as approved_budget
from {{ source('raw_sap_fica', 'capex_project') }} src
