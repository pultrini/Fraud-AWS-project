select
    origin_account_id,
    customer_transaction_number,
    count(*) as duplicate_count

from {{ ref('int_customer_transaction_features') }}

group by
    origin_account_id,
    customer_transaction_number

having count(*) > 1