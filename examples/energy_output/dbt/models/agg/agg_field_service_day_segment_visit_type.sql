{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.FULL_DATE as full_date,
    d1.QUARTER as quarter,
    c2.CUSTOMER_SEGMENT as customer_segment,
    f.VISIT_TYPE as visit_type,
    SUM(f.DURATION) as duration,
    COUNT(*) as field_service_count
from {{ ref('fct_field_service') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_customer') }} c2 on f.CUSTOMER_ID = c2.CUSTOMER_ID
group by all
