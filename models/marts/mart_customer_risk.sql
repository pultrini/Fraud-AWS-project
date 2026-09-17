{{
    config(
        materialized='table',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY'
    )
}}

with customer_aggregates as (

    select
        features.origin_account_id as customer_id,

        customer.first_seen_day,
        customer.last_seen_day,
        customer.customer_role,

        count(*) as transaction_count,

        sum(features.transaction_amount)
            as transaction_amount_total,

        avg(
            cast(features.transaction_amount as double)
        ) as transaction_amount_average,

        max(features.transaction_amount)
            as maximum_transaction_amount,

        avg(features.hours_since_previous_transaction)
            as average_hours_between_transactions,

        max(features.transaction_count_24h)
            as maximum_transaction_count_24h,

        sum(
            case
                when features.is_fraud then 1
                else 0
            end
        ) as fraudulent_transaction_count,

        sum(
            case
                when features.is_fraud
                    then features.transaction_amount
                else cast(0 as decimal(18, 2))
            end
        ) as fraudulent_transaction_amount,

        sum(
            case
                when features.amount_zscore_last_10 >= 3.0
                    or features.amount_to_customer_average_ratio >= 5.0
                    then 1
                else 0
            end
        ) as high_value_anomaly_count,

        coalesce(
            max(features.amount_zscore_last_10),
            0.0
        ) as maximum_amount_zscore,

        coalesce(
            max(features.amount_to_customer_average_ratio),
            0.0
        ) as maximum_amount_to_average_ratio

    from {{ ref('int_customer_transaction_features') }} as features

    inner join {{ ref('dim_customer') }} as customer
        on features.origin_account_id = customer.customer_id

    group by
        features.origin_account_id,
        customer.first_seen_day,
        customer.last_seen_day,
        customer.customer_role

    having count(*) >= 2

),

scored as (

    select
        *,

        100.0
            * fraudulent_transaction_count
            / nullif(transaction_count, 0)
            as fraud_rate_percent,

        case
            when fraudulent_transaction_count > 0
                then 'HIGH'

            when high_value_anomaly_count > 0
                or maximum_amount_to_average_ratio >= 5.0
                then 'MEDIUM'

            else 'LOW'
        end as customer_risk_level

    from customer_aggregates

),

ranked as (

    select
        *,

        rank() over (
            order by
                fraudulent_transaction_count desc,
                fraudulent_transaction_amount desc,
                high_value_anomaly_count desc,
                maximum_amount_zscore desc,
                transaction_amount_total desc
        ) as customer_risk_rank

    from scored

)

select *
from ranked