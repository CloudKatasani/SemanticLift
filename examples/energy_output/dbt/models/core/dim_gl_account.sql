-- Dimension at GLAccount grain. Source: SAP_FICA_PROD.GL_ACCOUNT. Origin: inferred from Energy_Finance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    HASH(src.GL_ACCOUNT_ID) as gl_account_sk,
    src.GL_ACCOUNT_ID as gl_account_id,
    src.ACCOUNT_CODE as account_code,
    src.ACCOUNT_NAME as account_name,
    src.COST_CENTER as cost_center
from {{ source('raw_sap_fica', 'gl_account') }} src
