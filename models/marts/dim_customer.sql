{{
    config(
        materialized='table',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY'
    )
}}

with account_events as (
    select
        origin_account_id as customer_id,
        simulation_step,
        simulation_day,
        'ORIGIN' as account_event_role
    
    from {{ ref('fact_transactions') }}

    union all

    select
        destination_account_id as customer_id,
        simulation_step,
        simulation_day,
        'DESTINATION' as account_event_role

    from {{ ref('fact_transactions') }}

    where destination_account_type = 'CUSTOMER'
),

customer_history as (
    select
        customer_id,
        min(simulation_step) over (
            partition by customer_id
        ) as first_seen_step,

        max(simulation_step) over (
            partition by customer_id
        ) as last_seen_step,

        min(simulation_day) over (
            partition by customer_id
        ) as first_seen_day,

        max(simulation_day) over (
            partition by customer_id
        ) as last_seen_day,

        sum(
            case
                when account_event_role = 'ORIGIN' then 1
                else 0
            end
        ) over (
            partition by customer_id
        ) as originated_transaction_count,

        sum(
            case
                when account_event_role = 'DESTINATION' then 1
                else 0
            end
        ) over (
            partition by customer_id
        ) as received_transaction_count,

        row_number() over (
            partition by customer_id
            order by simulation_step, account_event_role
        ) as customer_row_number

    from account_events
)

select 
    customer_id,
    first_seen_step,
    last_seen_step,
    first_seen_day,
    last_seen_day,
    originated_transaction_count,
    received_transaction_count,

    originated_transaction_count 
        + received_transaction_count 
        as total_involved_transaction_count,

    case 
        when originated_transaction_count > 0
            and received_transaction_count > 0
            then 'ORIGIN_AND_DESTINATION'
        when originated_transaction_count > 0
            then 'ORIGIN_ONLY'
        else 'DESTINATION_ONLY'
    end as customer_role

from customer_history
where customer_row_number = 1