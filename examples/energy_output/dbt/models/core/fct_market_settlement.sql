-- Fact at MarketSettlement grain. Source: SAP_FICA_PROD.MARKET_SETTLEMENT. Origin: inferred from Energy_Finance_Package report usage
-- confidence 0.30 (STUB)
{{ config(enabled=false) }}

select
    src.MARKET_SETTLEMENT_ID as market_settlement_id,
    src.DATE_KEY as date_key,
    src.GL_ACCOUNT_ID as gl_account_id,
    src.COUNTERPARTY_ID as counterparty_id,
    src.MARKET_TYPE as market_type,
    src.ENERGY_MWH as energy_mwh,
    src.PRICE_MWH as price_mwh,
    src.SETTLEMENT_AMOUNT as settlement_amount
from {{ source('raw_sap_fica', 'market_settlement') }} src
