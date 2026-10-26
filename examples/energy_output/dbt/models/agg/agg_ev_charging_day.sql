{{ config(enabled=false) }}

select
    d1.FULL_DATE as full_date,
    d1.IS_WEEKEND as is_weekend,
    d1.MONTH_NAME as month_name,
    d1.MONTH_NUMBER as month_number,
    SUM(f.COST) as cost,
    SUM(f.ENERGY_DELIVERED_KWH) as energy_delivered_kwh,
    MAX(f.PEAK_KW) as peak_kw,
    COUNT(*) as ev_charging_count
from {{ ref('fct_ev_charging') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
group by all
