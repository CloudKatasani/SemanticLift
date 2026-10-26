-- Dimension at PowerPlant grain. Source: PI_HISTORIAN_PROD.POWER_PLANT. Origin: inferred from Energy_Generation_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    HASH(src.POWER_PLANT_ID) as power_plant_sk,
    src.POWER_PLANT_ID as power_plant_id,
    src.PLANT_NAME as plant_name,
    src.PLANT_TYPE as plant_type,
    src.REGION as region,
    src.INSTALLED_CAPACITY_MW as installed_capacity_mw
from {{ source('raw_pi', 'power_plant') }} src
