import json
from pathlib import Path

import duckdb


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
    / "modeling"
)

TRAIN_END_STEP = 322
VALIDATION_END_STEP = 375

LEGITIMATE_TRAIN_SAMPLE_PERCENT = 5

def get_parquet_glob() -> str:
    """Obtém o caminho do dataset pelo manifesto."""

    manifest = json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    dataset_directory = (
        PROJECT_ROOT
        / manifest["local_directory"]
    )

    parquet_files = list(
        dataset_directory.glob("**/*.parquet")
    )

    if not parquet_files:
        raise FileNotFoundError(
            "Nenhum Parquet encontrado em "
            f"{dataset_directory}"
        )

    return str(
        dataset_directory
        / "**"
        / "*.parquet"
    )


def create_dataset_view(
    connection: duckdb.DuckDBPyConnection,
    parquet_glob: str,
) -> None:
    """Cria uma view sobre os dados completos."""

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

MODEL_COLUMNS = """
    transaction_id,

    simulation_step,
    simulation_hour,
    simulation_week,
    day_of_simulation_week,

    transaction_type,
    transaction_family,
    balance_direction,
    destination_account_type,

    transaction_amount,
    log_transaction_amount,

    origin_balance_before,
    destination_balance_before,

    amount_to_origin_balance_ratio,
    amount_to_destination_balance_ratio,

    origin_has_sufficient_balance,
    destination_has_recorded_balance,
    is_merchant_destination,

    customer_transaction_number,
    has_previous_transaction,
    previous_transaction_amount,
    hours_since_previous_transaction,
    days_since_previous_transaction,

    transaction_count_last_10,
    avg_last_10_transactions,
    std_last_10_transactions,

    historical_transaction_count,
    customer_average_amount,
    cumulative_transaction_value,

    amount_vs_customer_average,
    amount_to_customer_average_ratio,
    amount_zscore_last_10,

    transaction_count_24h,
    transaction_count_7d,

    baseline_rule_flag,
    is_fraud,
    dataset_split
"""

def export_dataset(
    connection: duckdb.DuckDBPyConnection,
    filename: str,
    condition: str,
) -> Path:
    """Exporta um subconjunto em Parquet."""

    output_path = (
        OUTPUT_DIRECTORY / filename
    )

    escaped_output_path = str(
        output_path
    ).replace("'", "''")

    connection.execute(
        f"""
        copy (
            select
                {MODEL_COLUMNS}

            from fraud_ml_dataset

            where {condition}
        )
        to '{escaped_output_path}'
        (
            format parquet,
            compression zstd
        )
        """
    )

    return output_path

def show_distribution(
    connection: duckdb.DuckDBPyConnection,
    parquet_path: Path,
) -> None:
    """Mostra tamanho e distribuição da classe."""

    escaped_path = str(
        parquet_path
    ).replace("'", "''")

    result = connection.execute(
        f"""
        select
            dataset_split,
            count(*) as row_count,

            sum(
                cast(is_fraud as integer)
            ) as fraud_count,

            round(
                100.0
                * avg(
                    cast(is_fraud as integer)
                ),
                6
            ) as fraud_rate_percent

        from read_parquet(
            '{escaped_path}'
        )

        group by dataset_split
        """
    ).df()

    print(f"\n{parquet_path.name}")
    print(
        result.to_string(
            index=False
        )
    )

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

        train_path = export_dataset(
            connection=connection,
            filename="train_sample.parquet",
            condition=f"""
                dataset_split = 'TRAIN'
                and (
                    is_fraud
                    or (
                        hash(transaction_id) % 100
                        < {LEGITIMATE_TRAIN_SAMPLE_PERCENT}
                    )
                )
            """,
        )

        validation_path = export_dataset(
            connection=connection,
            filename="validation.parquet",
            condition="""
                dataset_split = 'VALIDATION'
            """,
        )

        test_path = export_dataset(
            connection=connection,
            filename="test.parquet",
            condition="""
                dataset_split = 'TEST'
            """,
        )

        show_distribution(
            connection,
            train_path,
        )

        show_distribution(
            connection,
            validation_path,
        )

        show_distribution(
            connection,
            test_path,
        )

    finally:
        connection.close()

    print(
        f"\nDados preparados em: "
        f"{OUTPUT_DIRECTORY}"
    )


if __name__ == "__main__":
    main()