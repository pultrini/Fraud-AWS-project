{{
    config(
        materialized='view',
        tags=['ml', 'fraud']
    )
}}

select
    *,

    case
        when simulation_step
            <= {{ var('ml_train_end_step') }}
            then 'TRAIN'

        when simulation_step
            <= {{ var('ml_validation_end_step') }}
            then 'VALIDATION'

        else 'TEST'
    end as dataset_split

from {{ ref('mart_fraud_training_features') }}