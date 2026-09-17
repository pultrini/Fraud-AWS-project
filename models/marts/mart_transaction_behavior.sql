{{
    config(
        materialized='table',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY'
    )
}}

with enriched_transactions as (

    select
        transaction.transaction_id,
        transaction.transaction_amount,
        transaction.is_fraud,
        transaction.is_flagged_fraud,

        customer.customer_id,
        customer.customer_role,

        transaction_type.transaction_type,
        transaction_type.transaction_family,
        transaction_type.balance_direction,

        simulation_day.simulation_day,
        simulation_day.simulation_week,
        simulation_day.day_of_simulation_week,
        simulation_day.is_complete_day

    from {{ ref('fact_transactions') }} as transaction

    inner join {{ ref('dim_customer') }} as customer
        on transaction.origin_account_id = customer.customer_id

    inner join {{ ref('dim_transaction_type') }} as transaction_type
        on transaction.transaction_type
            = transaction_type.transaction_type

    inner join {{ ref('dim_simulation_day') }} as simulation_day
        on transaction.simulation_day
            = simulation_day.simulation_day

),

aggregated as (

    select
        simulation_day,
        simulation_week,
        day_of_simulation_week,
        is_complete_day,

        transaction_type,
        transaction_family,
        balance_direction,

        customer_role,

        count(*) as transaction_count,

        count(
            distinct customer_id
        ) as distinct_customer_count,

        sum(transaction_amount)
            as transaction_amount_total,

        avg(
            cast(transaction_amount as double)
        ) as transaction_amount_average,

        sum(
            case
                when is_fraud then 1
                else 0
            end
        ) as fraudulent_transaction_count,

        sum(
            case
                when is_fraud then transaction_amount
                else cast(0 as decimal(18, 2))
            end
        ) as fraudulent_transaction_amount,

        sum(
            case
                when is_flagged_fraud then 1
                else 0
            end
        ) as flagged_transaction_count

    from enriched_transactions

    group by
        simulation_day,
        simulation_week,
        day_of_simulation_week,
        is_complete_day,
        transaction_type,
        transaction_family,
        balance_direction,
        customer_role

),

final as (

    select
        *,

        100.0
            * fraudulent_transaction_count
            / nullif(transaction_count, 0)
            as fraud_rate_percent

    from aggregated

)

select *
from final