-- Fact at AuditRecord grain. Source: NERC_COMPLIANCE_DB.AUDIT_RECORD. Origin: inferred from Energy_Compliance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.AUDIT_RECORD_ID as audit_record_id,
    src.DATE_KEY as date_key,
    src.ACTION_REQUIRED as action_required,
    src.AUDIT_TYPE as audit_type,
    src.AUDITOR as auditor,
    src.FINDINGS as findings,
    src.RISK_RATING as risk_rating
from {{ source('raw_nerc', 'audit_record') }} src
