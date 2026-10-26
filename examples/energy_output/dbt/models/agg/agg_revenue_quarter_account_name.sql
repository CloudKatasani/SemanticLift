{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.QUARTER as quarter,
    g2.ACCOUNT_NAME as account_name,
    SUM(f.AMOUNT) as amount,
    SUM(f.KWH_SOLD) as kwh_sold,
    SUM(f.REVENUE_PER_KWH) as revenue_per_kwh_sum,
    COUNT(f.REVENUE_PER_KWH) as revenue_per_kwh_count,
    COUNT(*) as revenue_count
from {{ ref('fct_revenue') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_gl_account') }} g2 on f.GL_ACCOUNT_ID = g2.GL_ACCOUNT_ID
group by all
