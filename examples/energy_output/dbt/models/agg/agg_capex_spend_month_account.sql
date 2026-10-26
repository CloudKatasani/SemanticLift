{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    g2.ACCOUNT_CODE as account_code,
    g2.ACCOUNT_NAME as account_name,
    d1.MONTH_NUMBER as month_number,
    SUM(f.SPENT_TO_DATE) as spent_to_date,
    COUNT(*) as capex_spend_count
from {{ ref('fct_capex_spend') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_gl_account') }} g2 on f.GL_ACCOUNT_ID = g2.GL_ACCOUNT_ID
group by all
