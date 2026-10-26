-- Reference dimension TECHNICIAN derived from distinct FieldService.TechnicianID values until a master table is mapped (rule DIM-03)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.TECHNICIAN_ID as technician_id
from {{ source('raw_sfsc', 'field_service') }} src
