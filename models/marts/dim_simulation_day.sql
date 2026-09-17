{{
    config(
        materialized='table',
        table_type='hive',
        format='parquet',
        write_compression='SNAPPY'
    )
}}

with daily_activity as (
    select
        simulation_day,

        min(simulation_step) as first_simulation_step,
        max(simulation_step) as last_simulation_step,

        count(
            distinct simulation_hour
        ) as observed_hour_count

    from {{ ref('fact_transactions') }}

    group by simulation_day

),

enriched as (
    select
        simulation_day,
        cast(
            floor((simulation_day - 1) / 7.0) + 1
            as integer
        ) as simulation_week,

        cast(
            mod(simulation_day -1, 7) + 1
            as integer
        ) as day_of_simulation_week,

        first_simulation_step,
        last_simulation_step,
        observed_hour_count,

        observed_hour_count = 24 as is_complete_day

    from daily_activity
)

select *
from enriched
