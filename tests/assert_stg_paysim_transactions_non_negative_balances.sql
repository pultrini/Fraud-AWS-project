select *
from {{ ref('stg_paysim_transactions') }}

where
    transaction_amount < 0
    or origin_balance_before < 0
    or origin_balance_after < 0
    or destination_balance_before < 0
    or destination_balance_after < 0