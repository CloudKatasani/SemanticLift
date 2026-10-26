{{ config(enabled=false) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    g2.ACCOUNT_CODE as account_code,
    f.MARKET_TYPE as market_type,
    d1.MONTH_NUMBER as month_number,
    SUM(f.ENERGY_MWH) as energy_mwh,
    SUM(f.PRICE_MWH) as price_mwh_sum,
    COUNT(f.PRICE_MWH) as price_mwh_count,
    SUM(f.SETTLEMENT_AMOUNT) as settlement_amount,
    COUNT(*) as market_settlement_count
from {{ ref('fct_market_settlement') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_gl_account') }} g2 on f.GL_ACCOUNT_ID = g2.GL_ACCOUNT_ID
group by all
