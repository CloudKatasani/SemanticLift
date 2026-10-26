-- Dimension for Substation (split from report usage, rule DIM-02). Source: RAW_ENERGY_OPS.SUBSTATION (TODO confirm)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.SUBSTATION_ID as substation_id,
    src.REGION as region,
    src.SUBSTATION_NAME as substation_name,
    src.CAPACITY_MVA as capacity_mva
from {{ source('raw_energy_ops', 'substation') }} src
