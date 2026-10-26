-- Fact at Complaint grain. Source: SF_SERVICE_CLOUD.COMPLAINT. Origin: inferred from Energy_CustomerService_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.COMPLAINT_ID as complaint_id,
    src.CUSTOMER_ID as customer_id,
    src.DATE_KEY as date_key,
    src.CATEGORY as category,
    src.SEVERITY as severity,
    src.STATUS as status,
    src.RESOLUTION_DAYS as resolution_days
from {{ source('raw_sfsc', 'complaint') }} src
