{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    f.CUSTOMER_SEGMENT as customer_segment,
    f.REVENUE_TYPE as revenue_type,
    d1.MONTH_NUMBER as month_number,
    SUM(f.AMOUNT) as amount,
    SUM(f.KWH_SOLD) as kwh_sold,
    SUM(f.REVENUE_PER_KWH) as revenue_per_kwh_sum,
    COUNT(f.REVENUE_PER_KWH) as revenue_per_kwh_count,
    COUNT(*) as revenue_count
from {{ ref('fct_revenue') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
group by all
