with fact_totals as (

    select
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

        sum(
            case
                when is_flagged_fraud then 1
                else 0
            end
        ) as flagged_transaction_count

    from {{ ref('fact_transactions') }}

),

mart_totals as (

    select
        sum(transaction_count) as transaction_count,
        sum(transaction_amount_total) as transaction_amount_total,
        sum(fraudulent_transaction_count) as fraudulent_transaction_count,
        sum(fraudulent_transaction_amount) as fraudulent_transaction_amount,
        sum(flagged_transaction_count) as flagged_transaction_count

    from {{ ref('mart_transaction_behavior') }}

)

select
    fact_totals.transaction_count as fact_transaction_count,
    mart_totals.transaction_count as mart_transaction_count,

    fact_totals.transaction_amount_total as fact_transaction_amount,
    mart_totals.transaction_amount_total as mart_transaction_amount,

    fact_totals.fraudulent_transaction_count as fact_fraud_count,
    mart_totals.fraudulent_transaction_count as mart_fraud_count

from fact_totals
cross join mart_totals

where
    fact_totals.transaction_count
        <> mart_totals.transaction_count

    or fact_totals.transaction_amount_total
        <> mart_totals.transaction_amount_total

    or fact_totals.fraudulent_transaction_count
        <> mart_totals.fraudulent_transaction_count

    or fact_totals.fraudulent_transaction_amount
        <> mart_totals.fraudulent_transaction_amount

    or fact_totals.flagged_transaction_count
        <> mart_totals.flagged_transaction_count