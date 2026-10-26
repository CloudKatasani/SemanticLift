{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    f.FUEL_TYPE as fuel_type,
    g2.ACCOUNT_CODE as account_code,
    d1.MONTH_NUMBER as month_number,
    SUM(f.COST_PER_MMBTU) as cost_per_mmbtu_sum,
    COUNT(f.COST_PER_MMBTU) as cost_per_mmbtu_count,
    SUM(f.QUANTITY_MMBTU) as quantity_mmbtu,
    SUM(f.TOTAL_COST) as total_cost,
    COUNT(*) as fuel_cost_count
from {{ ref('fct_fuel_cost') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_gl_account') }} g2 on f.GL_ACCOUNT_ID = g2.GL_ACCOUNT_ID
group by all
