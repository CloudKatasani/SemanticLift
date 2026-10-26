-- Dimension at Date grain. Source: ENERGY_DW.DATE_DIM. Origin: FM Business Layer.Date (conformed across Energy_Billing_Package, Energy_Compliance_Package, Energy_CustomerService_Package, Energy_Finance_Package, Energy_Generation_Package, Energy_Operations_Package)
-- confidence 0.80
{{ config(enabled=true) }}

select
    src.DATE_KEY as date_key,
    src.FISCAL_YEAR as fiscal_year,
    src.FULL_DATE as full_date,
    src.ISO_WEEK as iso_week,
    src.IS_HOLIDAY as is_holiday,
    src.IS_WEEKEND as is_weekend,
    src.MONTH_NAME as month_name,
    src.MONTH_NUMBER as month_number,
    src.QUARTER as quarter
from {{ source('raw_energy_dw', 'date_dim') }} src
