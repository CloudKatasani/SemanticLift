-- Fact at EVCharging grain. Source: SF_SERVICE_CLOUD.EV_CHARGING. Origin: inferred from Energy_CustomerService_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.EV_CHARGING_ID as ev_charging_id,
    src.CUSTOMER_ID as customer_id,
    src.DATE_KEY as date_key,
    src.CHARGER_ID as charger_id,
    src.COST as cost,
    src.ENERGY_DELIVERED_KWH as energy_delivered_kwh,
    src.PEAK_KW as peak_kw
from {{ source('raw_sfsc', 'ev_charging') }} src
