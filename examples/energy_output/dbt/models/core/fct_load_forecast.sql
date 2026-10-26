-- Fact at LoadForecast grain. Source: ENERGY_OPS_DW.LOAD_FORECAST. Origin: inferred from Energy_Operations_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.LOAD_FORECAST_ID as load_forecast_id,
    src.DATE_KEY as date_key,
    src.LOCATION_ID as location_id,
    src.ACTUAL_LOAD_MW as actual_load_mw,
    src.FORECAST_ACCURACY_PCT as forecast_accuracy_pct,
    src.FORECASTED_LOAD_MW as forecasted_load_mw,
    src.PEAK_FORECAST_MW as peak_forecast_mw,
    src.VARIANCE_MW as variance_mw
from {{ source('raw_energy_ops', 'load_forecast') }} src
