-- Fact STORAGE_STATUS for StorageAsset measurements (rule DIM-02). Source: RAW_PI.STORAGE_ASSET (TODO confirm)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.STORAGE_STATUS_ID as storage_status_id,
    src.STORAGE_ASSET_ID as storage_asset_id,
    src.DATE_KEY as date_key,
    src.SOURCE_ID as source_id,
    src.POWER_PLANT_ID as power_plant_id,
    src.DISCHARGE_RATE_MW as discharge_rate_mw,
    src.STATE_OF_CHARGE_PCT as state_of_charge_pct
from {{ source('raw_pi', 'storage_asset') }} src
