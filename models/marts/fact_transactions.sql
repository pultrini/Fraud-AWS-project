{{
    config(
        materialized='incremental',
        incremental_strategy='insert_overwrite',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY',
        partitioned_by=['simulation_day'],
        on_schema_change='sync_all_columns'
    )
}}

with enriched_transactions as (

    select *
    from {{ ref('int_paysim_transactions_enriched') }}

    {% if is_incremental() %}

        where simulation_day >= (

            select coalesce(
                max(simulation_day),
                1
            )

            from {{ this }}

        )

    {% endif %}

),

with_transaction_id as (

    select
        to_hex(
            md5(
                to_utf8(
                    concat_ws(
                        '|',
                        cast(simulation_step as varchar),
                        transaction_type,
                        cast(transaction_amount as varchar),
                        origin_account_id,
                        cast(origin_balance_before as varchar),
                        cast(origin_balance_after as varchar),
                        destination_account_id,
                        cast(destination_balance_before as varchar),
                        cast(destination_balance_after as varchar),
                        cast(is_fraud as varchar),
                        cast(is_flagged_fraud as varchar)
                    )
                )
            )
        ) as transaction_id,

        simulation_step,
        simulation_hour,
        transaction_type,
        transaction_amount,

        origin_account_id,
        origin_balance_before,
        origin_balance_after,
        origin_balance_delta,

        destination_account_id,
        destination_account_type,
        destination_balance_before,
        destination_balance_after,
        destination_balance_delta,

        is_fraud,
        is_flagged_fraud,

        simulation_day

    from enriched_transactions

)

select *
from with_transaction_id