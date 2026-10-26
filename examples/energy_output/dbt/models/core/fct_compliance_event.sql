-- Fact at ComplianceEvent grain. Source: NERC_COMPLIANCE_DB.COMPLIANCE_EVENT. Origin: inferred from Energy_Compliance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.COMPLIANCE_EVENT_ID as compliance_event_id,
    src.DATE_KEY as date_key,
    src.EVENT_TYPE as event_type,
    src.REQUIREMENT_REF as requirement_ref,
    src.RESOLUTION_DATE as resolution_date,
    src.SEVERITY as severity,
    src.STANDARD_REF as standard_ref,
    src.STATUS as status
from {{ source('raw_nerc', 'compliance_event') }} src
