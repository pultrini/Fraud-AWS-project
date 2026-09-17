{{
    config(
        materialized='table',
        format='parquet',
        table_type='hive'
    )
}}

with transactions as (
    select *
    from {{ ref('fact_transactions') }}
),

aggregated as (
    select
        transaction_type,

        count(*) as transaction_count,
        sum(transaction_amount) as transaction_amount_total,
        avg(transaction_amount) as transaction_amount_average,

        sum(
            case
                when is_fraud then 1
                else 0
            end
        ) as fraudulent_transaction_count,

        sum(
            case 
                when is_flagged_fraud then 1
                else 0
            end
        ) as flagged_transaction_count,

        sum(
            case
                when is_fraud and is_flagged_fraud then 1
                else 0
            end
        ) as detected_fraud_count,

        sum(
            case
                when is_fraud and not is_flagged_fraud then 1
                else 0
            end
        ) as missed_fraud_count,

        sum(
            case
                when is_fraud then transaction_amount
                else cast(0 as decimal(18, 2))
            end
        ) as fraudulent_transaction_amount

    from transactions
    group by transaction_type
),

final as (

    select
        *,

        cast(
            100.0
            * fraudulent_transaction_count
            / nullif(transaction_count, 0)
            as decimal(10, 4)
        ) as fraud_rate_percent,

        cast(
            100.0
            * detected_fraud_count
            / nullif(fraudulent_transaction_count, 0)
            as decimal(10, 4)
        ) as fraud_detection_rate_percent

    from aggregated

)

select *
from final