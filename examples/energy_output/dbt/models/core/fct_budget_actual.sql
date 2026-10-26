-- Fact at BudgetActual grain. Source: SAP_FICA_PROD.BUDGET_ACTUAL. Origin: inferred from Energy_Finance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.BUDGET_ACTUAL_ID as budget_actual_id,
    src.DATE_KEY as date_key,
    src.GL_ACCOUNT_ID as gl_account_id,
    src.ACTUAL_AMOUNT as actual_amount,
    src.BUDGET_AMOUNT as budget_amount,
    src.VARIANCE_AMOUNT as variance_amount,
    src.VARIANCE_PCT as variance_pct
from {{ source('raw_sap_fica', 'budget_actual') }} src
