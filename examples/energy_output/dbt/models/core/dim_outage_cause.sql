-- Reference dimension OUTAGE_CAUSE derived from distinct OutageEvent.CauseCode values until a master table is mapped (rule DIM-03)
-- confidence 0.60
{{ config(enabled=true) }}

select distinct
    src.CAUSE_CODE as cause_code,
    CAST(NULL AS VARCHAR) as cause_description
from {{ source('raw_energy_ops', 'outage_event') }} src
