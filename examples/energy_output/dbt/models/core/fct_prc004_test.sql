-- Fact at PRC004Requirement grain. Source: NERC_COMPLIANCE_DB.PRC004_REQUIREMENT. Origin: inferred from Energy_Compliance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.PRC004_REQUIREMENT_ID as prc004_requirement_id,
    src.DATE_KEY as date_key,
    src.ASSET_ID as asset_id,
    src.NEXT_TEST_DUE as next_test_due,
    src.REQUIREMENT_SECTION as requirement_section,
    src.TEST_RESULT as test_result,
    src.MAINTENANCE_INTERVAL as maintenance_interval
from {{ source('raw_nerc', 'prc004_requirement') }} src
