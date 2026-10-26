-- Reference dimension AGENT derived from distinct ServiceRequest.AgentID values until a master table is mapped (rule DIM-03)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.AGENT_ID as agent_id
from {{ source('raw_sfsc', 'service_request') }} src
