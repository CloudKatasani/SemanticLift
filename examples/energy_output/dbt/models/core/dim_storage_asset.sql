-- Dimension for StorageAsset (split from report usage, rule DIM-02). Source: RAW_PI.STORAGE_ASSET (TODO confirm)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.STORAGE_ASSET_ID as storage_asset_id,
    src.ASSET_NAME as asset_name,
    src.STORAGE_CAPACITY_MWH as storage_capacity_mwh
from {{ source('raw_pi', 'storage_asset') }} src
