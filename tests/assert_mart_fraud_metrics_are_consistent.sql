select *
from {{ ref('mart_fraud_by_transaction_type') }}
where
    transaction_count <= 0

    or fraudulent_transaction_count > transaction_count

    or detected_fraud_count > fraudulent_transaction_count

    or missed_fraud_count > fraudulent_transaction_count

    or detected_fraud_count + missed_fraud_count
        <> fraudulent_transaction_count

    or detected_fraud_count > flagged_transaction_count

    or fraud_rate_percent not between 0 and 100

    or (
        fraudulent_transaction_count = 0
        and fraud_detection_rate_percent is not null
    )

    or (
        fraudulent_transaction_count > 0
        and fraud_detection_rate_percent not between 0 and 100
    )
