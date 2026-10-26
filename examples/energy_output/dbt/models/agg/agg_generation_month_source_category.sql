{{ config(enabled=true) }}

select
    d1.FISCAL_YEAR as fiscal_year,
    d1.MONTH_NAME as month_name,
    e2.SOURCE_CATEGORY as source_category,
    d1.MONTH_NUMBER as month_number,
    SUM(f.CO2_EMISSIONS_KG) as co2_emissions_kg,
    SUM(f.CAPACITY_FACTOR_PCT) as capacity_factor_pct_sum,
    COUNT(f.CAPACITY_FACTOR_PCT) as capacity_factor_pct_count,
    MAX(f.CAPACITY_MW) as capacity_mw,
    SUM(f.FUEL_COST_PER_MWH) as fuel_cost_per_mwh_sum,
    COUNT(f.FUEL_COST_PER_MWH) as fuel_cost_per_mwh_count,
    SUM(f.GENERATED_MWH) as generated_mwh,
    COUNT(*) as generation_count
from {{ ref('fct_generation') }} f
join {{ ref('dim_date') }} d1 on f.DATE_KEY = d1.DATE_KEY
join {{ ref('dim_energy_source') }} e2 on f.SOURCE_ID = e2.SOURCE_ID
group by all
