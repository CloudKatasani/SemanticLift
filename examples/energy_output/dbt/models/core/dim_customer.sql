-- Dimension at Customer grain. Source: ENERGY_DW.CUSTOMER. Origin: FM Business Layer.Customer (conformed across Energy_Billing_Package, Energy_CustomerService_Package)
-- confidence 0.60
{{ config(enabled=true) }}

select
    HASH(src.CUSTOMER_ID) as customer_sk,
    src.CUSTOMER_ID as customer_id,
    src.ACCOUNT_TYPE as account_type,
    CAST(NULL AS VARCHAR) as churn_risk,
    src.CREDIT_SCORE as credit_score,
    src.CUSTOMER_NAME as customer_name,
    src.CUSTOMER_SEGMENT as customer_segment,
    CAST(NULL AS VARCHAR) as service_tier,
    CAST(NULL AS NUMBER(18,4)) as lifetime_value_usd,
    CAST(NULL AS NUMBER(18,4)) as nps_score
from {{ source('raw_energy_dw', 'customer') }} src
