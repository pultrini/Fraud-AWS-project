with expected_values as (

    select
        *,

        rank() over (
            order by
                fraudulent_transaction_count desc,
                fraudulent_transaction_amount desc,
                high_value_anomaly_count desc,
                maximum_amount_zscore desc,
                transaction_amount_total desc
        ) as expected_risk_rank

    from {{ ref('mart_customer_risk') }}

)

select *
from expected_values
where
    transaction_count < 2

    or first_seen_day > last_seen_day

    or fraudulent_transaction_count < 0

    or fraudulent_transaction_count > transaction_count

    or fraudulent_transaction_amount < 0

    or high_value_anomaly_count < 0

    or fraud_rate_percent not between 0 and 100

    or average_hours_between_transactions < 0

    or customer_risk_rank <> expected_risk_rank

    or (
        fraudulent_transaction_count > 0
        and customer_risk_level <> 'HIGH'
    )

    or (
        fraudulent_transaction_count = 0
        and (
            high_value_anomaly_count > 0
            or maximum_amount_to_average_ratio >= 5.0
        )
        and customer_risk_level <> 'MEDIUM'
    )

    or (
        fraudulent_transaction_count = 0
        and high_value_anomaly_count = 0
        and maximum_amount_to_average_ratio < 5.0
        and customer_risk_level <> 'LOW'
    )