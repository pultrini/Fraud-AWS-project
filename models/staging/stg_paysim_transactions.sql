with source as (

    select *
    from {{ source('paysim_raw', 'raw_paysim') }}

),

renamed_and_cast as (

    select
        cast(step as bigint) as simulation_step,
        upper(trim(type)) as transaction_type,
        cast(amount as decimal(18, 2)) as transaction_amount,

        trim(nameorig) as origin_account_id,
        cast(oldbalanceorg as decimal(18, 2)) as origin_balance_before,
        cast(newbalanceorig as decimal(18, 2)) as origin_balance_after,

        trim(namedest) as destination_account_id,
        cast(oldbalancedest as decimal(18, 2)) as destination_balance_before,
        cast(newbalancedest as decimal(18, 2)) as destination_balance_after,

        isfraud = 1 as is_fraud,
        isflaggedfraud = 1 as is_flagged_fraud

    from source

)

select *
from renamed_and_cast