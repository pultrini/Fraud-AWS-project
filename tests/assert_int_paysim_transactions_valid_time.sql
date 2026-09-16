select *
from {{ ref('int_paysim_transactions_enriched') }}
where
    simulation_day < 1
    or simulation_hour not between 0 and 23

    