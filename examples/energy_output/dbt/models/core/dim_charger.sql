-- Reference dimension CHARGER derived from distinct EVCharging.ChargerID values until a master table is mapped (rule DIM-03)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.CHARGER_ID as charger_id
from {{ source('raw_sfsc', 'ev_charging') }} src
