with source_count as (

    select count(*) as row_count
    from {{ source('paysim_raw', 'raw_paysim') }}

),

fact_count as (

    select count(*) as row_count
    from {{ ref('fact_transactions') }}

)

select
    source_count.row_count as source_row_count,
    fact_count.row_count as fact_row_count

from source_count
cross join fact_count

where source_count.row_count <> fact_count.row_count