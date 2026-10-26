-- Fact at ServiceRequest grain. Source: SF_SERVICE_CLOUD.SERVICE_REQUEST. Origin: inferred from Energy_CustomerService_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.SERVICE_REQUEST_ID as service_request_id,
    src.CUSTOMER_ID as customer_id,
    src.DATE_KEY as date_key,
    src.AGENT_ID as agent_id,
    src.PRIORITY as priority,
    src.REQUEST_TYPE as request_type,
    src.RESOLUTION_DATE as resolution_date,
    src.STATUS as status
from {{ source('raw_sfsc', 'service_request') }} src
