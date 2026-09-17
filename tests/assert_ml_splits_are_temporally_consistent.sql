select *
from {{ ref('mart_fraud_ml_dataset') }}
where
    (
        dataset_split = 'TRAIN'
        and simulation_step
            > {{ var('ml_train_end_step') }}
    )

    or (
        dataset_split = 'VALIDATION'
        and (
            simulation_step
                <= {{ var('ml_train_end_step') }}

            or simulation_step
                > {{ var('ml_validation_end_step') }}
        )
    )

    or (
        dataset_split = 'TEST'
        and simulation_step
            <= {{ var('ml_validation_end_step') }}
    )