-- Fact CAPEX_SPEND for CapexProject measurements (rule DIM-02). Source: RAW_SAP_FICA.CAPEX_PROJECT (TODO confirm)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.CAPEX_SPEND_ID as capex_spend_id,
    src.CAPEX_PROJECT_ID as capex_project_id,
    src.DATE_KEY as date_key,
    src.GL_ACCOUNT_ID as gl_account_id,
    src.SPENT_TO_DATE as spent_to_date
from {{ source('raw_sap_fica', 'capex_project') }} src
