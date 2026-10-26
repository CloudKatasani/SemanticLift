-- Fact at RECCertificate grain. Source: PI_HISTORIAN_PROD.REC_CERTIFICATE. Origin: inferred from Energy_Generation_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.REC_ID as rec_id,
    src.DATE_KEY as date_key,
    src.SOURCE_ID as source_id,
    src.POWER_PLANT_ID as power_plant_id,
    src.EXPIRY_DATE as expiry_date,
    src.STATUS as status,
    src.MWH as mwh
from {{ source('raw_pi', 'rec_certificate') }} src
