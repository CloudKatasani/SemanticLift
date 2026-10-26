{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.FULL_DATE as full_date,
    d1.IS_HOLIDAY as is_holiday,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    l2.REGION as region,
    d1.MONTH_NUMBER as month_number,
    SUM(f.LOAD_FACTOR_PCT) as load_factor_pct_sum,
    COUNT(f.LOAD_FACTOR_PCT) as load_factor_pct_count,
    MAX(f.PEAK_LOAD_MW) as peak_load_mw,
    COUNT(*) as substation_load_count
from {{ ref('fct_substation_load') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_location') }} l2 on f.LOCATION_ID = l2.LOCATION_ID
group by all
