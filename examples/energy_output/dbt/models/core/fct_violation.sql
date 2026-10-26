-- Fact at Violation grain. Source: NERC_COMPLIANCE_DB.VIOLATION. Origin: inferred from Energy_Compliance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.VIOLATION_ID as violation_id,
    src.DATE_KEY as date_key,
    src.STANDARD_ID as standard_id,
    src.CLOSED_DATE as closed_date,
    src.DESCRIPTION as description,
    src.MITIGATION_PLAN as mitigation_plan,
    src.PENALTY as penalty
from {{ source('raw_nerc', 'violation') }} src
