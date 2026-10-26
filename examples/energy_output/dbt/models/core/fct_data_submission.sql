-- Fact at DataSubmission grain. Source: NERC_COMPLIANCE_DB.DATA_SUBMISSION. Origin: inferred from Energy_Compliance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.DATA_SUBMISSION_ID as data_submission_id,
    src.DATE_KEY as date_key,
    src.FILING_PERIOD as filing_period,
    src.REPORTING_ENTITY as reporting_entity,
    src.STATUS as status,
    src.SUBMISSION_TYPE as submission_type,
    src.SUBMITTED_BY as submitted_by
from {{ source('raw_nerc', 'data_submission') }} src
