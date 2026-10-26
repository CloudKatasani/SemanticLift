{{ config(enabled=true) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    d1.QUARTER as quarter,
    c3.CUSTOMER_SEGMENT as customer_segment,
    l4.REGION as region,
    d1.MONTH_NUMBER as month_number,
    SUM(f.CO2_ESTIMATE_KG) as co2_estimate_kg,
    SUM(f.CONSUMPTION_KWH) as consumption_kwh,
    SUM(f.CONSUMPTION_MWH) as consumption_mwh,
    SUM(f.OFF_PEAK_KWH) as off_peak_kwh,
    MAX(f.PEAK_DEMAND_KW) as peak_demand_kw,
    SUM(f.REACTIVE_KVARH) as reactive_kvarh,
    COUNT(*) as meter_reading_count
from {{ ref('fct_meter_reading') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_meter') }} m2 on f.METER_ID = m2.METER_ID
join {{ ref('dim_customer') }} c3 on m2.CUSTOMER_ID = c3.CUSTOMER_ID
join {{ ref('dim_location') }} l4 on m2.LOCATION_ID = l4.LOCATION_ID
group by all
