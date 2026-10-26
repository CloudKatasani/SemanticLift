{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    f.SEVERITY as severity,
    c2.CUSTOMER_SEGMENT as customer_segment,
    d1.MONTH_NUMBER as month_number,
    SUM(f.RESOLUTION_DAYS) as resolution_days_sum,
    COUNT(f.RESOLUTION_DAYS) as resolution_days_count,
    COUNT(*) as complaint_count
from {{ ref('fct_complaint') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_customer') }} c2 on f.CUSTOMER_ID = c2.CUSTOMER_ID
group by all
