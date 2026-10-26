-- Fact at FieldService grain. Source: SF_SERVICE_CLOUD.FIELD_SERVICE. Origin: inferred from Energy_CustomerService_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.FIELD_SERVICE_ID as field_service_id,
    src.CUSTOMER_ID as customer_id,
    src.DATE_KEY as date_key,
    src.TECHNICIAN_ID as technician_id,
    src.OUTCOME as outcome,
    src.VISIT_TYPE as visit_type,
    src.DURATION as duration
from {{ source('raw_sfsc', 'field_service') }} src
