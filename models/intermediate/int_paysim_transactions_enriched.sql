with staged_transactions as (
    select *
    from {{ ref('stg_paysim_transactions') }}
),

enriched as (
    select *,
        cast(
        floor((simulation_step-1) / 24.0) + 1 as integer
        ) as simulation_day,
        cast(
            mod(simulation_step -1, 24) as integer    
        ) as simulation_hour,

        case
            when destination_account_id like 'M%' then 'MERCHANT'
            when destination_account_id like 'C%' then 'CUSTOMER'
            else 'UNKNOWN'
        end as destination_account_type,

        origin_balance_after
            - origin_balance_before as origin_balance_delta,

        destination_balance_after
            - destination_balance_before as destination_balance_delta
    from staged_transactions

)   
select *
from enriched
