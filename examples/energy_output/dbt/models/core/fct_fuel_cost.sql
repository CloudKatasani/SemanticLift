-- Fact at FuelCost grain. Source: SAP_FICA_PROD.FUEL_COST. Origin: inferred from Energy_Finance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.FUEL_COST_ID as fuel_cost_id,
    src.DATE_KEY as date_key,
    src.GL_ACCOUNT_ID as gl_account_id,
    src.FUEL_TYPE as fuel_type,
    src.COST_PER_MMBTU as cost_per_mmbtu,
    src.QUANTITY_MMBTU as quantity_mmbtu,
    src.TOTAL_COST as total_cost
from {{ source('raw_sap_fica', 'fuel_cost') }} src
