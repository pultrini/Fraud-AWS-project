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
    / "profiles"
)
# Cortes definidos no dbt
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

def run_analysis(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    title: str,
    query: str,
) -> pd.DataFrame:
    """Executa uma análise, imprime e salva em CSV."""

    result = connection.execute(
        query
    ).df()

    print(f"\n{'=' * 70}")
    print(title)
    print(f"{'=' * 70}")

    print(
        result.to_string(
            index=False
        )
    )

    output_path = (
        OUTPUT_DIRECTORY / f"{name}.csv"
    )

    result.to_csv(
        output_path,
        index=False,
    )

    return result

def profile_splits(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    run_analysis(
        connection=connection,
        name="split_summary",
        title="Distribuição temporal e das classes",
        query="""
            select
                dataset_split,

                min(simulation_step)
                    as minimum_step,

                max(simulation_step)
                    as maximum_step,

                count(*)
                    as transaction_count,

                sum(
                    cast(is_fraud as integer)
                )
                    as fraud_count,

                round(
                    100.0
                    * avg(
                        cast(is_fraud as integer)
                    ),
                    6
                )
                    as fraud_rate_percent

            from fraud_ml_dataset

            group by dataset_split

            order by
                case dataset_split
                    when 'TRAIN' then 1
                    when 'VALIDATION' then 2
                    when 'TEST' then 3
                end
        """,
    )

def profile_transaction_types(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    run_analysis(
        connection=connection,
        name="fraud_by_transaction_type",
        title="Fraude por tipo de transação",
        query="""
            select
                transaction_type,

                count(*)
                    as transaction_count,

                sum(
                    cast(is_fraud as integer)
                )
                    as fraud_count,

                round(
                    100.0
                    * avg(
                        cast(is_fraud as integer)
                    ),
                    6
                )
                    as fraud_rate_percent

            from fraud_ml_dataset

            group by transaction_type

            order by fraud_rate_percent desc
        """,
    )

def profile_transaction_amounts(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    run_analysis(
        connection=connection,
        name="amount_by_class",
        title="Distribuição dos valores por classe",
        query="""
            select
                is_fraud,

                count(*)
                    as transaction_count,

                round(
                    avg(transaction_amount),
                    2
                )
                    as average_amount,

                round(
                    median(transaction_amount),
                    2
                )
                    as median_amount,

                round(
                    quantile_cont(
                        transaction_amount,
                        0.90
                    ),
                    2
                )
                    as percentile_90,

                round(
                    quantile_cont(
                        transaction_amount,
                        0.99
                    ),
                    2
                )
                    as percentile_99

            from fraud_ml_dataset

            group by is_fraud

            order by is_fraud
        """,
    )

def profile_high_value_rule(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    run_analysis(
        connection=connection,
        name="high_value_rule",
        title="Desempenho da regra de valor elevado",
        query="""
            with threshold as (

                select
                    quantile_cont(
                        transaction_amount,
                        0.99
                    ) as legitimate_p99

                from fraud_ml_dataset

                where
                    dataset_split = 'TRAIN'
                    and not is_fraud

            )

            select
                dataset_split,

                round(
                    max(threshold.legitimate_p99),
                    2
                )
                    as high_value_threshold,

                sum(
                    case
                        when is_fraud
                            and transaction_amount
                                >= threshold.legitimate_p99
                            then 1
                        else 0
                    end
                )
                    as detected_frauds,

                sum(
                    cast(is_fraud as integer)
                )
                    as total_frauds,

                round(
                    100.0
                    * sum(
                        case
                            when is_fraud
                                and transaction_amount
                                    >= threshold.legitimate_p99
                                then 1
                            else 0
                        end
                    )
                    / nullif(
                        sum(
                            cast(is_fraud as integer)
                        ),
                        0
                    ),
                    4
                )
                    as fraud_recall_percent,

                sum(
                    case
                        when not is_fraud
                            and transaction_amount
                                >= threshold.legitimate_p99
                            then 1
                        else 0
                    end
                )
                    as legitimate_alerts

            from fraud_ml_dataset

            cross join threshold

            group by dataset_split

            order by
                case dataset_split
                    when 'TRAIN' then 1
                    when 'VALIDATION' then 2
                    when 'TEST' then 3
                end
        """,
    )

def profile_customer_history(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    run_analysis(
        connection=connection,
        name="customer_history_by_class",
        title="Histórico transacional por classe",
        query="""
            select
                is_fraud,

                round(
                    avg(
                        historical_transaction_count
                    ),
                    2
                )
                    as average_previous_transactions,

                median(
                    historical_transaction_count
                )
                    as median_previous_transactions,

                round(
                    avg(transaction_count_24h),
                    2
                )
                    as average_transactions_24h,

                median(
                    transaction_count_24h
                )
                    as median_transactions_24h,

                round(
                    avg(transaction_count_7d),
                    2
                )
                    as average_transactions_7d,

                median(
                    transaction_count_7d
                )
                    as median_transactions_7d,

                round(
                    avg(
                        hours_since_previous_transaction
                    ),
                    2
                )
                    as average_hours_since_previous

            from fraud_ml_dataset

            group by is_fraud

            order by is_fraud
        """,
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

        profile_splits(connection)
        profile_transaction_types(connection)
        profile_transaction_amounts(connection)
        profile_high_value_rule(connection)
        profile_customer_history(connection)

    finally:
        connection.close()

    print(
        "\nPerfil estatístico concluído."
    )

    print(
        f"Resultados salvos em: "
        f"{OUTPUT_DIRECTORY}"
    )


if __name__ == "__main__":
    main()