-- Dimension at Tariff grain. Source: CC_AND_B_PROD.TARIFF. Origin: FM Business Layer.Tariff
-- confidence 0.80
{{ config(enabled=true) }}

select
    HASH(src.TARIFF_ID) as tariff_sk,
    src.TARIFF_ID as tariff_id,
    src.TARIFF_TYPE as tariff_type,
    src.DEMAND_CHARGE_RATE as demand_charge_rate,
    src.RATE_PER_KWH as rate_per_kwh
from {{ source('raw_ccb', 'tariff') }} src
