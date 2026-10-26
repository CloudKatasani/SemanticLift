{{ config(enabled=true) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.FULL_DATE as full_date,
    d1.IS_HOLIDAY as is_holiday,
    d1.IS_WEEKEND as is_weekend,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    l2.REGION as region,
    f.CAUSE_CODE as cause_code,
    d1.MONTH_NUMBER as month_number,
    SUM(f.CUSTOMERS_AFFECTED) as customers_affected,
    SUM(f.DURATION_MINUTES) as duration_minutes,
    SUM(f.MAIFI_COUNT) as maifi_count,
    SUM(f.SAIDI_MINUTES) as saidi_minutes,
    SUM(f.SAIFI_COUNT) as saifi_count,
    COUNT(*) as outage_event_count
from {{ ref('fct_outage_event') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_location') }} l2 on f.LOCATION_ID = l2.LOCATION_ID
group by all
