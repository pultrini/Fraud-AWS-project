{{
    config(
        materialized='table',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY'
    )
}}

select
    transaction_type,
    transaction_family,
    balance_direction,
    description
from {{ ref('transaction_types') }}

