with fact_count as (

    select count(*) as row_count
    from {{ ref('fact_transactions') }}

),

feature_count as (

    select count(*) as row_count
    from {{ ref('int_customer_transaction_features') }}

)

select
    fact_count.row_count as fact_row_count,
    feature_count.row_count as feature_row_count

from fact_count
cross join feature_count

where fact_count.row_count <> feature_count.row_count