-- Fact at MeterReading grain. Source: CC_AND_B_PROD.METER_READING. Origin: FM Business Layer.MeterReading
-- confidence 0.80
{{ config(enabled=true) }}

select
    src.READING_ID as reading_id,
    src.DATE_KEY as date_key,
    src.METER_ID as meter_id,
    src.TARIFF_ID as tariff_id,
    src.IS_INTERVAL_READ as is_interval_read,
    src.READING_DATE as reading_date,
    src.CONSUMPTION_KWH * ref_1.FACTOR_VALUE as co2_estimate_kg,
    src.CONSUMPTION_KWH as consumption_kwh,
    src.CONSUMPTION_KWH / 1000 as consumption_mwh,
    src.OFF_PEAK_KWH as off_peak_kwh,
    src.PEAK_DEMAND_KW as peak_demand_kw,
    src.REACTIVE_KVARH as reactive_kvarh
from {{ source('raw_ccb', 'meter_reading') }} src
left join {{ ref('ref_emission_factor') }} ref_1
    on ref_1.FACTOR_CODE = 'METER_READING_CO2_ESTIMATE_KG' AND src.READING_DATE >= ref_1.EFFECTIVE_FROM AND src.READING_DATE < COALESCE(ref_1.EFFECTIVE_TO, '9999-12-31'::DATE)
