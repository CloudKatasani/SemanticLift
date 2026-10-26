-- Fact at OutageEvent grain. Source: ENERGY_OPS_DW.OUTAGE_EVENT. Origin: FM Business Layer.OutageEvent
-- confidence 0.60
{{ config(enabled=true) }}

select
    src.OUTAGE_ID as outage_id,
    TO_NUMBER(TO_CHAR(src.OUTAGE_END, 'YYYYMMDD')) as date_key,
    src.LOCATION_ID as location_id,
    src.CAUSE_CODE as cause_code,
    src.OUTAGE_END as outage_end,
    src.OUTAGE_START as outage_start,
    src.CUSTOMERS_AFFECTED as customers_affected,
    src.DURATION_MINUTES as duration_minutes,
    CAST(NULL AS NUMBER(38,0)) as maifi_count,
    src.SAIDI_MINUTES as saidi_minutes,
    CAST(NULL AS NUMBER(38,0)) as saifi_count
from {{ source('raw_energy_ops', 'outage_event') }} src
