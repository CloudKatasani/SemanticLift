{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.FULL_DATE as full_date,
    d1.IS_HOLIDAY as is_holiday,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    l2.REGION as region,
    d1.MONTH_NUMBER as month_number,
    SUM(f.ACTUAL_LOAD_MW) as actual_load_mw_sum,
    COUNT(f.ACTUAL_LOAD_MW) as actual_load_mw_count,
    SUM(f.FORECAST_ACCURACY_PCT) as forecast_accuracy_pct_sum,
    COUNT(f.FORECAST_ACCURACY_PCT) as forecast_accuracy_pct_count,
    SUM(f.FORECASTED_LOAD_MW) as forecasted_load_mw_sum,
    COUNT(f.FORECASTED_LOAD_MW) as forecasted_load_mw_count,
    MAX(f.PEAK_FORECAST_MW) as peak_forecast_mw,
    SUM(f.VARIANCE_MW) as variance_mw_sum,
    COUNT(f.VARIANCE_MW) as variance_mw_count,
    COUNT(*) as load_forecast_count
from {{ ref('fct_load_forecast') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_location') }} l2 on f.LOCATION_ID = l2.LOCATION_ID
group by all
