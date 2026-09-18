import json
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MANIFEST_PATH = (
    PROJECT_ROOT
    / "data"
    / "ml"
    / "manifest.json"
)

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "ml"
    / "baselines"
)

TRAIN_END_STEP = 322
VALIDATION_END_STEP = 375


def get_parquet_glob() -> str:
    """Obtém pelo manisfesto o caminho dos Parquet."""

    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifesto não encontrado: "
            f"{MANIFEST_PATH}"
        )

    manifest = json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    relative_directory = manifest["local_directory"]

    dataset_directory = (PROJECT_ROOT / relative_directory)

    parquet_files = list(dataset_directory.glob("**/*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(
            "Nenhum arquivo Parquet encontrado em "
            f"{dataset_directory}"
        )

    return str(
        dataset_directory / "**" / "*.parquet"
    )


def create_dataset_view(
    connection: duckdb.DuckDBPyConnection,
    parquet_glob: str,
) -> None:
    """Cria uma view local sobre os Parquets."""

    escaped_path = parquet_glob.replace(
        "'",
        "''",
    )

    connection.execute(
        f"""
            create or replace temporary view
                fraud_ml_dataset
            as
            select
                *,
                case
                    when simulation_step
                        <= {TRAIN_END_STEP}
                        then 'TRAIN'

                    when simulation_step
                        <= {VALIDATION_END_STEP}
                        then 'VALIDATION'
                    
                    else 'TEST'

                end as dataset_split

            from read_parquet(
                '{escaped_path}',
                hive_partitioning = true,
                union_by_name = true
            )
        """
    )

def evaluate_baselines(
    connection: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    """Avalia regras simples nos três períodos."""

    return connection.execute(
        """
        with high_value_threshold as (

            select
                quantile_cont(
                    transaction_amount,
                    0.99
                ) as threshold

            from fraud_ml_dataset

            where
                dataset_split = 'TRAIN'
                and not is_fraud

        ),

        predictions as (

            select
                dataset_split,
                is_fraud,
                baseline_rule_flag
                    as predicted_fraud,
                'original_rule'
                    as rule_name

            from fraud_ml_dataset

            union all

            select
                dataset_split,
                is_fraud,
                is_higher_fraud_risk_type
                    as predicted_fraud,
                'risky_type'
                    as rule_name

            from fraud_ml_dataset

            union all

            select
                dataset_split,
                is_fraud,
                transaction_amount >= threshold
                    as predicted_fraud,
                'high_value'
                    as rule_name

            from fraud_ml_dataset

            cross join high_value_threshold

            union all

            select
                dataset_split,
                is_fraud,

                is_higher_fraud_risk_type
                    and transaction_amount
                        >= threshold
                    as predicted_fraud,

                'risky_type_and_high_value'
                    as rule_name

            from fraud_ml_dataset

            cross join high_value_threshold

        ),

        confusion_matrix as (

            select
                dataset_split,
                rule_name,

                sum(
                    cast(
                        predicted_fraud
                        and is_fraud
                        as integer
                    )
                ) as true_positive,

                sum(
                    cast(
                        predicted_fraud
                        and not is_fraud
                        as integer
                    )
                ) as false_positive,

                sum(
                    cast(
                        not predicted_fraud
                        and is_fraud
                        as integer
                    )
                ) as false_negative,

                sum(
                    cast(
                        not predicted_fraud
                        and not is_fraud
                        as integer
                    )
                ) as true_negative

            from predictions

            group by
                dataset_split,
                rule_name

        )

        select
            dataset_split,
            rule_name,

            true_positive,
            false_positive,
            false_negative,
            true_negative,

            true_positive + false_positive
                as generated_alerts,

            round(
                100.0
                * true_positive
                / nullif(
                    true_positive + false_positive,
                    0
                ),
                4
            ) as precision_percent,

            round(
                100.0
                * true_positive
                / nullif(
                    true_positive + false_negative,
                    0
                ),
                4
            ) as recall_percent,

            round(
                100.0
                * true_negative
                / nullif(
                    true_negative + false_positive,
                    0
                ),
                4
            ) as specificity_percent,

            round(
                200.0
                * true_positive
                / nullif(
                    2 * true_positive
                    + false_positive
                    + false_negative,
                    0
                ),
                4
            ) as f1_percent,

            round(
                100.0
                * (
                    true_positive
                    + false_positive
                )
                / (
                    true_positive
                    + false_positive
                    + false_negative
                    + true_negative
                ),
                4
            ) as alert_rate_percent

        from confusion_matrix

        order by
            case dataset_split
                when 'TRAIN' then 1
                when 'VALIDATION' then 2
                when 'TEST' then 3
            end,

            rule_name
        """
    ).df()

def main() -> None:
    parquet_glob = get_parquet_glob()

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = duckdb.connect()

    try:
        connection.execute(
            "set threads to 4"
        )

        create_dataset_view(
            connection=connection,
            parquet_glob=parquet_glob,
        )

        metrics = evaluate_baselines(
            connection
        )

    finally:
        connection.close()

    output_path = (
        OUTPUT_DIRECTORY
        / "baseline_metrics.csv"
    )

    metrics.to_csv(
        output_path,
        index=False,
    )

    print(
        "\nComparação dos baselines"
    )

    print(
        metrics.to_string(
            index=False
        )
    )

    print(
        f"\nResultados salvos em: "
        f"{output_path}"
    )


if __name__ == "__main__":
    main()