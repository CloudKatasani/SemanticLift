-- Reference dimension REPORTING_ENTITY derived from distinct DataSubmission.ReportingEntity values until a master table is mapped (rule DIM-03)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.REPORTING_ENTITY as reporting_entity
from {{ source('raw_nerc', 'data_submission') }} src
