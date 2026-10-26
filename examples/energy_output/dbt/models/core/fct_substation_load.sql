-- Fact SUBSTATION_LOAD for Substation measurements (rule DIM-02). Source: RAW_ENERGY_OPS.SUBSTATION (TODO confirm)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.SUBSTATION_LOAD_ID as substation_load_id,
    src.SUBSTATION_ID as substation_id,
    src.DATE_KEY as date_key,
    src.LOCATION_ID as location_id,
    src.LOAD_FACTOR_PCT as load_factor_pct,
    src.PEAK_LOAD_MW as peak_load_mw
from {{ source('raw_energy_ops', 'substation') }} src
