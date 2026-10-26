-- Reference dimension ASSET derived from distinct PRC004Requirement.AssetID values until a master table is mapped (rule DIM-03)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.ASSET_ID as asset_id
from {{ source('raw_nerc', 'prc004_requirement') }} src
