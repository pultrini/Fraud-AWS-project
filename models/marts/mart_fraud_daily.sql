{{
    config(
        materialized='table',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY'
    )
}}

with daily_aggregates as (

    select
        simulation_day,

        count(*) as transaction_count,

        sum(transaction_amount) as transaction_amount_total,

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

        avg(
            case
                when is_fraud
                    then cast(transaction_amount as double)
                else null
            end
        ) as average_fraudulent_transaction_amount,

        sum(
            case
                when is_flagged_fraud then 1
                else 0
            end
        ) as flagged_transaction_count

    from {{ ref('fact_transactions') }}

    group by simulation_day

),

daily_rates as (

    select
        simulation_day,
        transaction_count,
        transaction_amount_total,
        fraudulent_transaction_count,
        fraudulent_transaction_amount,
        average_fraudulent_transaction_amount,
        flagged_transaction_count,

        100.0
            * fraudulent_transaction_count
            / nullif(transaction_count, 0)
            as fraud_rate_percent

    from daily_aggregates

),

with_calendar as (

    select
        daily.simulation_day,
        calendar.simulation_week,
        calendar.day_of_simulation_week,
        calendar.is_complete_day,

        daily.transaction_count,
        daily.transaction_amount_total,
        daily.fraudulent_transaction_count,
        daily.fraudulent_transaction_amount,
        daily.average_fraudulent_transaction_amount,
        daily.flagged_transaction_count,
        daily.fraud_rate_percent

    from daily_rates as daily

    inner join {{ ref('dim_simulation_day') }} as calendar
        on daily.simulation_day = calendar.simulation_day

),

windowed as (

    select
        *,

        lag(fraud_rate_percent) over (
            order by simulation_day
        ) as previous_day_fraud_rate_percent,

        sum(transaction_count) over (
            order by simulation_day
            rows between 6 preceding and current row
        ) as rolling_7d_transaction_count,

        sum(fraudulent_transaction_count) over (
            order by simulation_day
            rows between 6 preceding and current row
        ) as rolling_7d_fraud_count,

        sum(transaction_count) over (
            order by simulation_day
            rows between unbounded preceding and current row
        ) as cumulative_transaction_count,

        sum(fraudulent_transaction_count) over (
            order by simulation_day
            rows between unbounded preceding and current row
        ) as cumulative_fraud_count,

        sum(fraudulent_transaction_amount) over (
            order by simulation_day
            rows between unbounded preceding and current row
        ) as cumulative_fraudulent_amount

    from with_calendar

),

final as (

    select
        *,

        fraud_rate_percent
            - previous_day_fraud_rate_percent
            as fraud_rate_change_percentage_points,

        100.0
            * rolling_7d_fraud_count
            / nullif(rolling_7d_transaction_count, 0)
            as rolling_7d_fraud_rate_percent

    from windowed

)

select *
from final