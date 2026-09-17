select *
from {{ ref('dim_simulation_day') }}
where
    simulation_week < 1

    or day_of_simulation_week not between 1 and 7

    or first_simulation_step > last_simulation_step

    or observed_hour_count not between 1 and 24

    or (
        is_complete_day
        and observed_hour_count <> 24
    )

    or (
        not is_complete_day
        and observed_hour_count = 24
    )