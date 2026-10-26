{{ config(enabled=true) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    c3.CUSTOMER_SEGMENT as customer_segment,
    l4.REGION as region,
    d1.MONTH_NUMBER as month_number,
    SUM(f.BILL_AMOUNT) as bill_amount,
    SUM(f.DEMAND_CHARGE) as demand_charge,
    SUM(f.ENERGY_CHARGE) as energy_charge,
    SUM(f.TAX_AMOUNT) as tax_amount,
    SUM(f.TOTAL_BILL_WITH_TAX) as total_bill_with_tax,
    COUNT(*) as billing_count
from {{ ref('fct_billing') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_meter') }} m2 on f.METER_ID = m2.METER_ID
join {{ ref('dim_customer') }} c3 on m2.CUSTOMER_ID = c3.CUSTOMER_ID
join {{ ref('dim_location') }} l4 on m2.LOCATION_ID = l4.LOCATION_ID
group by all
