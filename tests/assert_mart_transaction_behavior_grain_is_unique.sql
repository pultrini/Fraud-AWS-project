select
    simulation_day,
    transaction_type,
    customer_role,
    count(*) as duplicate_count

from {{ ref('mart_transaction_behavior') }}

group by
    simulation_day,
    transaction_type,
    customer_role

having count(*) > 1