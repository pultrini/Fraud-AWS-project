select *
from {{ ref('int_customer_transaction_features') }}
where
    customer_transaction_number < 1

    or (
        customer_transaction_number = 1
        and (
            previous_transaction_amount is not null
            or previous_transaction_step is not null
            or hours_since_previous_transaction is not null
            or days_since_previous_transaction is not null
        )
    )

    or (
        customer_transaction_number > 1
        and (
            previous_transaction_amount is null
            or previous_transaction_step is null
            or hours_since_previous_transaction is null
            or days_since_previous_transaction is null
        )
    )

    or previous_transaction_step > simulation_step

    or hours_since_previous_transaction
        <> simulation_step - previous_transaction_step

    or abs(
        days_since_previous_transaction
        - hours_since_previous_transaction / 24.0
    ) > 0.000001