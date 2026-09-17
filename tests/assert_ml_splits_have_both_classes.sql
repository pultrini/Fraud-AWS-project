select
    dataset_split,
    count(*) as transaction_count,

    sum(
        case when is_fraud then 1 else 0 end
    ) as fraud_count,

    sum(
        case when not is_fraud then 1 else 0 end
    ) as legitimate_count

from {{ ref('mart_fraud_ml_dataset') }}

group by dataset_split

having
    sum(case when is_fraud then 1 else 0 end) = 0

    or sum(case when not is_fraud then 1 else 0 end) = 0