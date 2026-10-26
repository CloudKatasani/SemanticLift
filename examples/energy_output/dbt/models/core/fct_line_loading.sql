-- Fact LINE_LOADING for TransmissionLine measurements (rule DIM-02). Source: RAW_ENERGY_OPS.TRANSMISSION_LINE (TODO confirm)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.LINE_LOADING_ID as line_loading_id,
    src.TRANSMISSION_LINE_ID as transmission_line_id,
    src.DATE_KEY as date_key,
    src.LOCATION_ID as location_id,
    src.CURRENT_LOAD_MW as current_load_mw
from {{ source('raw_energy_ops', 'transmission_line') }} src
