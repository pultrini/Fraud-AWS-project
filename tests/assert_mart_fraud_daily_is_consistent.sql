with expected_values as (

    select
        *,

        lag(fraud_rate_percent) over (
            order by simulation_day
        ) as expected_previous_fraud_rate,

        sum(transaction_count) over (
            order by simulation_day
            rows between 6 preceding and current row
        ) as expected_rolling_transaction_count,

        sum(fraudulent_transaction_count) over (
            order by simulation_day
            rows between 6 preceding and current row
        ) as expected_rolling_fraud_count,

        sum(transaction_count) over (
            order by simulation_day
            rows between unbounded preceding and current row
        ) as expected_cumulative_transaction_count,

        sum(fraudulent_transaction_count) over (
            order by simulation_day
            rows between unbounded preceding and current row
        ) as expected_cumulative_fraud_count

    from {{ ref('mart_fraud_daily') }}

)

select *
from expected_values
where
    transaction_count <= 0

    or fraudulent_transaction_count < 0

    or fraudulent_transaction_count > transaction_count

    or fraud_rate_percent not between 0 and 100

    or rolling_7d_fraud_rate_percent not between 0 and 100

    or rolling_7d_transaction_count
        <> expected_rolling_transaction_count

    or rolling_7d_fraud_count
        <> expected_rolling_fraud_count

    or cumulative_transaction_count
        <> expected_cumulative_transaction_count

    or cumulative_fraud_count
        <> expected_cumulative_fraud_count

    or (
        expected_previous_fraud_rate is null
        and (
            previous_day_fraud_rate_percent is not null
            or fraud_rate_change_percentage_points is not null
        )
    )

    or (
        expected_previous_fraud_rate is not null
        and (
            previous_day_fraud_rate_percent is null

            or abs(
                previous_day_fraud_rate_percent
                - expected_previous_fraud_rate
            ) > 0.000001

            or abs(
                fraud_rate_change_percentage_points
                - (
                    fraud_rate_percent
                    - expected_previous_fraud_rate
                )
            ) > 0.000001
        )
    )