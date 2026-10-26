-- Reference dimension COST_CENTER derived from distinct GLAccount.CostCenter values until a master table is mapped (rule DIM-03)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.COST_CENTER as cost_center
from {{ source('raw_sap_fica', 'gl_account') }} src
