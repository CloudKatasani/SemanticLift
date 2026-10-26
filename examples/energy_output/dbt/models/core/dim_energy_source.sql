-- Dimension at EnergySource grain. Source: PI_HISTORIAN_PROD.ENERGY_SOURCE. Origin: FM Business Layer.EnergySource
-- confidence 0.80
{{ config(enabled=true) }}

select
    HASH(src.SOURCE_ID) as energy_source_sk,
    src.SOURCE_ID as source_id,
    src.IS_REC_ELIGIBLE as is_rec_eligible,
    src.SOURCE_CATEGORY as source_category,
    src.SOURCE_NAME as source_name,
    src.CO2_FACTOR_KG_KWH as co2_factor_kg_kwh
from {{ source('raw_pi', 'energy_source') }} src
