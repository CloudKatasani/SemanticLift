-- Fact at RevenueRecord grain. Source: SAP_FICA_PROD.REVENUE_RECORD. Origin: inferred from Energy_Finance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.REVENUE_RECORD_ID as revenue_record_id,
    src.DATE_KEY as date_key,
    src.GL_ACCOUNT_ID as gl_account_id,
    src.CUSTOMER_SEGMENT as customer_segment,
    src.REVENUE_TYPE as revenue_type,
    src.AMOUNT as amount,
    src.KWH_SOLD as kwh_sold,
    src.REVENUE_PER_KWH as revenue_per_kwh
from {{ source('raw_sap_fica', 'revenue_record') }} src
