{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    c2.CUSTOMER_SEGMENT as customer_segment,
    f.RESOLUTION_DATE as resolution_date,
    f.STATUS as status,
    d1.MONTH_NUMBER as month_number,
    COUNT(*) as service_request_count
from {{ ref('fct_service_request') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_customer') }} c2 on f.CUSTOMER_ID = c2.CUSTOMER_ID
group by all
