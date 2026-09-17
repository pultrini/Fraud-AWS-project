{{
    config(
        materialized='table',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY',
        partitioned_by=['simulation_day'],
        tags=['ml', 'fraud']
    )
}}

with transaction_features as (

    select *
    from {{ ref('int_customer_transaction_features') }}

),

training_features as (

    select
        features.transaction_id,
        features.origin_account_id,
        features.destination_account_id,

        features.simulation_step,
        features.simulation_hour,
        simulation_day.simulation_week,
        simulation_day.day_of_simulation_week,

        features.transaction_type,
        transaction_type.transaction_family,
        transaction_type.balance_direction,
        features.destination_account_type,

        cast(
            features.transaction_amount as double
        ) as transaction_amount,

        ln(
            1.0
            + cast(features.transaction_amount as double)
        ) as log_transaction_amount,

        -- Estado disponível antes da transação.
        cast(
            features.origin_balance_before as double
        ) as origin_balance_before,

        cast(
            features.destination_balance_before as double
        ) as destination_balance_before,

        cast(features.transaction_amount as double)
            / nullif(
                cast(features.origin_balance_before as double),
                0.0
            )
            as amount_to_origin_balance_ratio,

        cast(features.transaction_amount as double)
            / nullif(
                cast(features.destination_balance_before as double),
                0.0
            )
            as amount_to_destination_balance_ratio,

        features.origin_balance_before
            >= features.transaction_amount
            as origin_has_sufficient_balance,

        features.destination_balance_before > 0
            as destination_has_recorded_balance,

        -- Indicadores categóricos.
        features.destination_account_type = 'MERCHANT'
            as is_merchant_destination,

        features.transaction_type = 'TRANSFER'
            as is_transfer,

        features.transaction_type in (
            'CASH_IN',
            'CASH_OUT'
        ) as is_cash_transaction,

        features.transaction_type in (
            'TRANSFER',
            'CASH_OUT'
        ) as is_higher_fraud_risk_type,

        features.customer_transaction_number,

        features.previous_transaction_amount is not null
            as has_previous_transaction,

        cast(
            features.previous_transaction_amount as double
        ) as previous_transaction_amount,

        features.hours_since_previous_transaction,
        features.days_since_previous_transaction,

        features.transaction_count_last_10,
        features.avg_last_10_transactions,
        features.std_last_10_transactions,

        features.transaction_count_last_10 = 10
            as has_full_10_transaction_history,

        features.historical_transaction_count,
        features.customer_average_amount,

        cast(
            features.cumulative_transaction_value as double
        ) as cumulative_transaction_value,

        features.amount_vs_customer_average,
        features.amount_to_customer_average_ratio,
        features.amount_zscore_last_10,


        features.transaction_count_24h,
        features.transaction_count_7d,

        features.is_flagged_fraud
            as baseline_rule_flag,


        features.is_fraud,


        features.simulation_day

    from transaction_features as features

    inner join {{ ref('dim_transaction_type') }} as transaction_type
        on features.transaction_type
            = transaction_type.transaction_type

    inner join {{ ref('dim_simulation_day') }} as simulation_day
        on features.simulation_day
            = simulation_day.simulation_day

)

select *
from training_features