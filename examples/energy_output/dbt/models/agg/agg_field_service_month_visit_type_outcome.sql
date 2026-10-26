{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    f.OUTCOME as outcome,
    f.VISIT_TYPE as visit_type,
    d1.MONTH_NUMBER as month_number,
    SUM(f.DURATION) as duration,
    COUNT(*) as field_service_count
from {{ ref('fct_field_service') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
group by all
