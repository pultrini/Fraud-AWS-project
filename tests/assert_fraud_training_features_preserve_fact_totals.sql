with fact_totals as (

    select
        count(*) as row_count,
        sum(
            cast(transaction_amount as decimal(18, 2))
        ) as transaction_amount_total,

        sum(
            case when is_fraud then 1 else 0 end
        ) as fraud_count,

        sum(
            case when is_flagged_fraud then 1 else 0 end
        ) as flagged_count

    from {{ ref('fact_transactions') }}

),

training_totals as (

    select
        count(*) as row_count,
        sum(
            cast(transaction_amount as decimal(18, 2))
        ) as transaction_amount_total,

        sum(
            case when is_fraud then 1 else 0 end
        ) as fraud_count,

        sum(
            case when baseline_rule_flag then 1 else 0 end
        ) as flagged_count

    from {{ ref('mart_fraud_training_features') }}

)

select
    fact_totals.row_count as fact_row_count,
    training_totals.row_count as training_row_count,
    fact_totals.fraud_count as fact_fraud_count,
    training_totals.fraud_count as training_fraud_count

from fact_totals
cross join training_totals

where
    fact_totals.row_count <> training_totals.row_count

    or fact_totals.transaction_amount_total
        <> training_totals.transaction_amount_total

    or fact_totals.fraud_count
        <> training_totals.fraud_count

    or fact_totals.flagged_count
        <> training_totals.flagged_count
