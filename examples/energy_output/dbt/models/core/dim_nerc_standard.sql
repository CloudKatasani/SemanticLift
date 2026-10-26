-- Reference dimension NERC_STANDARD derived from ComplianceEvent.StandardRef, Violation.StandardID; union of distinct values until a master table is mapped (rule DIM-03)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select src.STANDARD_REF as standard_ref
from {{ source('raw_nerc', 'compliance_event') }} src
union
select src.STANDARD_ID as standard_ref
from {{ source('raw_nerc', 'violation') }} src
