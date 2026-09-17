{{
    config(
        materialized='table',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY',
        partitioned_by=['simulation_day']
    )
}}

with transactions as (

    select
        transaction_id,
        simulation_step,
        simulation_hour,
        transaction_type,
        transaction_amount,

        origin_account_id,
        origin_balance_before,
        origin_balance_after,
        origin_balance_delta,

        destination_account_id,
        destination_account_type,
        destination_balance_before,
        destination_balance_after,
        destination_balance_delta,

        is_fraud,
        is_flagged_fraud,

        simulation_day

    from {{ ref('fact_transactions') }}

),

sequenced as (

    select
        *,

        row_number() over (
            partition by origin_account_id
            order by simulation_step, transaction_id
        ) as customer_transaction_number,

        lag(transaction_amount) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
        ) as previous_transaction_amount,

        lag(simulation_step) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
        ) as previous_transaction_step,

        lead(transaction_amount) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
        ) as next_transaction_amount,

        count(*) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
            rows between 10 preceding and 1 preceding
        ) as transaction_count_last_10,

        avg(
            cast(transaction_amount as double)
        ) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
            rows between 10 preceding and 1 preceding
        ) as avg_last_10_transactions,

        stddev_samp(
            cast(transaction_amount as double)
        ) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
            rows between 10 preceding and 1 preceding
        ) as std_last_10_transactions,

        count(*) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
            rows between unbounded preceding and 1 preceding
        ) as historical_transaction_count,

        avg(
            cast(transaction_amount as double)
        ) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
            rows between unbounded preceding and 1 preceding
        ) as customer_average_amount,

        sum(transaction_amount) over (
            partition by origin_account_id
            order by simulation_step, transaction_id
            rows between unbounded preceding and 1 preceding
        ) as cumulative_transaction_value,

        count(*) over (
            partition by origin_account_id
            order by simulation_step
            range between 24 preceding and 1 preceding
        ) as transaction_count_24h,

        count(*) over (
            partition by origin_account_id
            order by simulation_step
            range between 168 preceding and 1 preceding
        ) as transaction_count_7d

    from transactions

),

final as (

    select
        transaction_id,
        simulation_step,
        simulation_hour,
        transaction_type,
        transaction_amount,

        origin_account_id,
        origin_balance_before,
        origin_balance_after,
        origin_balance_delta,

        destination_account_id,
        destination_account_type,
        destination_balance_before,
        destination_balance_after,
        destination_balance_delta,

        is_fraud,
        is_flagged_fraud,

        customer_transaction_number,
        previous_transaction_amount,
        previous_transaction_step,
        next_transaction_amount,

        simulation_step
            - previous_transaction_step
            as hours_since_previous_transaction,

        cast(
            simulation_step - previous_transaction_step
            as double
        ) / 24.0 as days_since_previous_transaction,

        transaction_count_last_10,
        avg_last_10_transactions,
        std_last_10_transactions,

        historical_transaction_count,
        customer_average_amount,
        cumulative_transaction_value,

        transaction_count_24h,
        transaction_count_7d,

        cast(transaction_amount as double)
            - customer_average_amount
            as amount_vs_customer_average,

        cast(transaction_amount as double)
            / nullif(customer_average_amount, 0.0)
            as amount_to_customer_average_ratio,

        case
            when std_last_10_transactions > 0
                then (
                    cast(transaction_amount as double)
                    - avg_last_10_transactions
                ) / std_last_10_transactions
            else null
        end as amount_zscore_last_10,

        simulation_day

    from sequenced

)

select *
from final
