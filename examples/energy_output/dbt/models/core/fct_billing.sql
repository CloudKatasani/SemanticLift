-- Fact at Billing grain. Source: CC_AND_B_PROD.BILLING. Origin: FM Business Layer.Billing
-- confidence 0.80
{{ config(enabled=true) }}

select
    src.BILL_ID as bill_id,
    src.BILL_DATE_KEY as date_key,
    src.METER_ID as meter_id,
    src.DUE_DATE as due_date,
    src.IS_EBILL as is_ebill,
    IFF(src.PAYMENT_STATUS = 'Overdue', 'Yes', 'No') as is_overdue,
    src.PAYMENT_STATUS as payment_status,
    src.BILL_AMOUNT as bill_amount,
    src.DEMAND_CHARGE as demand_charge,
    src.ENERGY_CHARGE as energy_charge,
    src.TAX_AMOUNT as tax_amount,
    src.BILL_AMOUNT + src.TAX_AMOUNT as total_bill_with_tax
from {{ source('raw_ccb', 'billing') }} src
