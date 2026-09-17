select *
from {{ ref('int_customer_transaction_features') }}
where
    historical_transaction_count
        <> customer_transaction_number - 1

    or transaction_count_last_10
        <> least(historical_transaction_count, 10)

    or transaction_count_last_10 < 0

    or transaction_count_24h < 0

    or transaction_count_7d < 0

    or transaction_count_24h > transaction_count_7d

    or transaction_count_7d > historical_transaction_count

    or (
        historical_transaction_count = 0
        and (
            customer_average_amount is not null
            or cumulative_transaction_value is not null
            or amount_vs_customer_average is not null
            or amount_to_customer_average_ratio is not null
        )
    )

    or (
        historical_transaction_count > 0
        and (
            customer_average_amount is null
            or cumulative_transaction_value is null
            or amount_vs_customer_average is null
        )
    )

    or (
        transaction_count_last_10 < 2
        and std_last_10_transactions is not null
    )

    or (
        transaction_count_last_10 >= 2
        and std_last_10_transactions is null
    )

    or (
        customer_average_amount is not null
        and abs(
            amount_vs_customer_average
            - (
                cast(transaction_amount as double)
                - customer_average_amount
            )
        ) > 0.000001
    )

    or (
        customer_average_amount = 0
        and amount_to_customer_average_ratio is not null
    )

    or (
        customer_average_amount <> 0
        and abs(
            amount_to_customer_average_ratio
            - (
                cast(transaction_amount as double)
                / customer_average_amount
            )
        ) > 0.000001
    )

    or (
        coalesce(std_last_10_transactions, 0) <= 0
        and amount_zscore_last_10 is not null
    )

    or (
        std_last_10_transactions > 0
        and abs(
            amount_zscore_last_10
            - (
                (
                    cast(transaction_amount as double)
                    - avg_last_10_transactions
                ) / std_last_10_transactions
            )
        ) > 0.000001
    )