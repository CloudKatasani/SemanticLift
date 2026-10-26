-- Fact at Generation grain. Source: PI_HISTORIAN_PROD.GENERATION. Origin: FM Business Layer.Generation
-- confidence 0.60
{{ config(enabled=true) }}

select
    src.GENERATION_ID as generation_id,
    src.DATE_KEY as date_key,
    src.POWER_PLANT_ID as power_plant_id,
    src.SOURCE_ID as source_id,
    src.CO2_EMISSIONS_KG as co2_emissions_kg,
    src.CAPACITY_FACTOR_PCT as capacity_factor_pct,
    src.CAPACITY_MW as capacity_mw,
    CAST(NULL AS NUMBER(18,4)) as fuel_cost_per_mwh,
    src.GENERATED_MWH as generated_mwh
from {{ source('raw_pi', 'generation') }} src
