-- Reference dimension COUNTERPARTY derived from distinct MarketSettlement.CounterpartyID values until a master table is mapped (rule DIM-03)
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select distinct
    src.COUNTERPARTY_ID as counterparty_id
from {{ source('raw_sap_fica', 'market_settlement') }} src
