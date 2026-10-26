-- Dimension for TransmissionLine (split from report usage, rule DIM-02). Source: RAW_ENERGY_OPS.TRANSMISSION_LINE (TODO confirm)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.TRANSMISSION_LINE_ID as transmission_line_id,
    src.CONSTRAINT_FLAG as constraint_flag,
    src.LINE_NAME as line_name,
    src.VOLTAGE_KV as voltage_kv,
    src.THERMAL_LIMIT_MW as thermal_limit_mw
from {{ source('raw_energy_ops', 'transmission_line') }} src
