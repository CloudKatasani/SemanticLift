-- Dimension at Meter grain. Source: CC_AND_B_PROD.METER. Origin: FM Business Layer.Meter
-- confidence 0.80
{{ config(enabled=true) }}

select
    HASH(src.METER_ID) as meter_sk,
    src.METER_ID as meter_id,
    src.CUSTOMER_ID as customer_id,
    src.LOCATION_ID as location_id,
    src.INSTALL_DATE as install_date,
    src.IS_SMART_METER as is_smart_meter,
    src.STATUS as status,
    src.METER_TYPE as meter_type
from {{ source('raw_ccb', 'meter') }} src
