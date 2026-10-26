-- Dimension at Location grain. Source: ENERGY_DW.LOCATION. Origin: FM Business Layer.Location (conformed across Energy_Billing_Package, Energy_Operations_Package)
-- confidence 0.80
{{ config(enabled=true) }}

select
    HASH(src.LOCATION_ID) as location_sk,
    src.LOCATION_ID as location_id,
    src.CITY as city,
    src.CLIMATE_ZONE as climate_zone,
    src.POSTAL_CODE as postal_code,
    src.REGION as region,
    src.STATE_PROVINCE as state_province
from {{ source('raw_energy_dw', 'location') }} src
