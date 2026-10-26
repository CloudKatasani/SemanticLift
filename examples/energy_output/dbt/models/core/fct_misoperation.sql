-- Fact at MisoperationEvent grain. Source: NERC_COMPLIANCE_DB.MISOPERATION_EVENT. Origin: inferred from Energy_Compliance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.MISOP_ID as misop_id,
    src.DATE_KEY as date_key,
    src.CAUSE_CATEGORY as cause_category,
    src.PROTECTION_SYSTEM as protection_system,
    src.DURATION_CYCLES as duration_cycles
from {{ source('raw_nerc', 'misoperation_event') }} src
