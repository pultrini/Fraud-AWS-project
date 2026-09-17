select *
from {{ ref('dim_customer') }}
where
    first_seen_step > last_seen_step

    or first_seen_day > last_seen_day

    or originated_transaction_count < 0

    or received_transaction_count < 0

    or originated_transaction_count
        + received_transaction_count
        <> total_involved_transaction_count

    or total_involved_transaction_count <= 0