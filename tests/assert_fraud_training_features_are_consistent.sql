select *
from {{ ref('mart_fraud_training_features') }}
where
    transaction_amount < 0

    or log_transaction_amount < 0

    or abs(
        log_transaction_amount
        - ln(1.0 + transaction_amount)
    ) > 0.000001

    or (
        origin_balance_before = 0
        and amount_to_origin_balance_ratio is not null
    )

    or (
        origin_balance_before <> 0
        and (
            amount_to_origin_balance_ratio is null
            or abs(
                amount_to_origin_balance_ratio
                - transaction_amount / origin_balance_before
            ) > 0.000001
        )
    )

    or (
        destination_balance_before = 0
        and amount_to_destination_balance_ratio is not null
    )

    or (
        destination_balance_before <> 0
        and (
            amount_to_destination_balance_ratio is null
            or abs(
                amount_to_destination_balance_ratio
                - transaction_amount / destination_balance_before
            ) > 0.000001
        )
    )

    or origin_has_sufficient_balance
        <> (origin_balance_before >= transaction_amount)

    or destination_has_recorded_balance
        <> (destination_balance_before > 0)

    or is_merchant_destination
        <> (destination_account_type = 'MERCHANT')

    or is_transfer
        <> (transaction_type = 'TRANSFER')

    or is_cash_transaction
        <> (transaction_type in ('CASH_IN', 'CASH_OUT'))

    or is_higher_fraud_risk_type
        <> (transaction_type in ('TRANSFER', 'CASH_OUT'))

    or has_previous_transaction
        <> (previous_transaction_amount is not null)

    or has_full_10_transaction_history
        <> (transaction_count_last_10 = 10)

    or historical_transaction_count
        <> customer_transaction_number - 1

    or transaction_count_last_10
        <> least(historical_transaction_count, 10)

    or transaction_count_24h > transaction_count_7d

    or transaction_count_7d > historical_transaction_count