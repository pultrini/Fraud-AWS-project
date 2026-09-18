import json
from pathlib import Path

import duckdb


LOCAL_ROOT = Path("data/bi")
MANIFEST_PATH = LOCAL_ROOT / "manifest.json"

DATABASE_PATH = (
    LOCAL_ROOT
    / "financial_risk_bi.duckdb"
)

TEMPORARY_DATABASE_PATH = (
    LOCAL_ROOT
    / "financial_risk_bi.tmp.duckdb"
)

REQUIRED_TABLES = (
    "mart_fraud_by_transaction_type",
    "mart_fraud_daily",
    "mart_customer_risk",
    "mart_transaction_behavior",
)


def load_manifest() -> dict:
    """Carrega e valida a estrutura básica do manifesto."""

    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifesto não encontrado: {MANIFEST_PATH}. "
            "Execute primeiro sync_bi_marts.py."
        )

    manifest = json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    manifest_tables = manifest.get(
        "tables",
        {},
    )

    missing_tables = sorted(
        set(REQUIRED_TABLES)
        - set(manifest_tables)
    )

    if missing_tables:
        raise ValueError(
            "Tabelas ausentes no manifesto: "
            + ", ".join(missing_tables)
        )

    return manifest


def get_table_files(
    manifest: dict,
    table_name: str,
) -> list[str]:
    """Obtém e valida os arquivos locais de uma tabela."""

    table_manifest = manifest[
        "tables"
    ][table_name]

    file_paths = [
        Path(file_metadata["local_path"])
        for file_metadata
        in table_manifest["files"]
    ]

    if not file_paths:
        raise ValueError(
            f"Nenhum arquivo registrado para "
            f"'{table_name}'."
        )

    missing_files = [
        file_path
        for file_path in file_paths
        if not file_path.exists()
    ]

    if missing_files:
        formatted_paths = ", ".join(
            str(file_path)
            for file_path in missing_files
        )

        raise FileNotFoundError(
            f"Arquivos ausentes para '{table_name}': "
            f"{formatted_paths}"
        )

    return [
        str(file_path)
        for file_path in file_paths
    ]


def create_base_tables(
    connection: duckdb.DuckDBPyConnection,
    manifest: dict,
) -> dict[str, int]:
    """Materializa os marts do Parquet dentro do DuckDB."""

    row_counts = {}

    for table_name in REQUIRED_TABLES:
        file_paths = get_table_files(
            manifest,
            table_name,
        )

        relation = connection.read_parquet(
            file_paths,
            union_by_name=True,
        )

        relation.create(table_name)

        row_count = connection.execute(
            f"""
            select count(*)
            from {table_name}
            """
        ).fetchone()[0]

        if row_count == 0:
            raise ValueError(
                f"A tabela '{table_name}' ficou vazia."
            )

        row_counts[table_name] = row_count

        print(
            f"Tabela criada: {table_name} "
            f"({row_count:,} linhas)"
        )

    return row_counts


def create_metadata_table(
    connection: duckdb.DuckDBPyConnection,
    manifest: dict,
    row_counts: dict[str, int],
) -> None:
    """Registra a origem e a versão de cada tabela local."""

    connection.execute(
        """
        create table bi_dataset_metadata (
            table_name varchar,
            row_count bigint,
            snapshot_id varchar,
            source_s3_uri varchar,
            synchronized_at_utc timestamp
        )
        """
    )

    synchronized_at = manifest[
        "generated_at_utc"
    ]

    for table_name in REQUIRED_TABLES:
        table_manifest = manifest[
            "tables"
        ][table_name]

        connection.execute(
            """
            insert into bi_dataset_metadata
            values (?, ?, ?, ?, ?)
            """,
            [
                table_name,
                row_counts[table_name],
                table_manifest["snapshot_id"],
                table_manifest["source_s3_uri"],
                synchronized_at,
            ],
        )


def create_dashboard_views(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Cria datasets preparados para o Superset."""

    connection.execute(
        """
        create view bi_executive_summary as

        select
            sum(transaction_count)
                as transaction_count,

            sum(transaction_amount_total)
                as transaction_amount_total,

            sum(fraudulent_transaction_count)
                as fraudulent_transaction_count,

            sum(fraudulent_transaction_amount)
                as fraudulent_transaction_amount,

            sum(flagged_transaction_count)
                as flagged_transaction_count,

            100.0
                * sum(fraudulent_transaction_count)
                / nullif(
                    sum(transaction_count),
                    0
                )
                as fraud_rate_percent,

            avg(
                average_fraudulent_transaction_amount
            )
                as average_daily_fraud_amount,

            max(fraudulent_transaction_amount)
                as maximum_daily_fraud_amount

        from mart_fraud_daily
        """
    )

    connection.execute(
        """
        create view bi_customer_risk_distribution as

        select
            customer_risk_level,

            case customer_risk_level
                when 'HIGH' then 1
                when 'MEDIUM' then 2
                when 'LOW' then 3
                else 4
            end as risk_level_order,

            count(*) as customer_count,

            sum(transaction_count)
                as transaction_count,

            sum(transaction_amount_total)
                as transaction_amount_total,

            sum(fraudulent_transaction_count)
                as fraudulent_transaction_count,

            sum(fraudulent_transaction_amount)
                as fraudulent_transaction_amount,

            sum(high_value_anomaly_count)
                as high_value_anomaly_count,

            100.0
                * sum(fraudulent_transaction_count)
                / nullif(
                    sum(transaction_count),
                    0
                )
                as fraud_rate_percent,

            avg(maximum_amount_zscore)
                as average_maximum_amount_zscore

        from mart_customer_risk

        group by
            customer_risk_level
        """
    )

    connection.execute(
        """
        create view bi_top_risk_customers as

        select
            customer_id,
            customer_risk_rank,
            customer_risk_level,
            customer_role,

            first_seen_day,
            last_seen_day,

            transaction_count,
            transaction_amount_total,
            transaction_amount_average,
            maximum_transaction_amount,

            fraudulent_transaction_count,
            fraudulent_transaction_amount,

            high_value_anomaly_count,
            maximum_amount_zscore,
            maximum_amount_to_average_ratio,

            maximum_transaction_count_24h,
            average_hours_between_transactions,
            fraud_rate_percent

        from mart_customer_risk

        order by customer_risk_rank

        limit 100
        """
    )

    connection.execute(
        """
        create view bi_daily_transaction_type as

        select
            simulation_day,
            simulation_week,
            day_of_simulation_week,
            is_complete_day,

            transaction_type,
            transaction_family,
            balance_direction,

            sum(transaction_count)
                as transaction_count,

            sum(distinct_customer_count)
                as distinct_customer_count,

            sum(transaction_amount_total)
                as transaction_amount_total,

            sum(fraudulent_transaction_count)
                as fraudulent_transaction_count,

            sum(fraudulent_transaction_amount)
                as fraudulent_transaction_amount,

            sum(flagged_transaction_count)
                as flagged_transaction_count,

            100.0
                * sum(fraudulent_transaction_count)
                / nullif(
                    sum(transaction_count),
                    0
                )
                as fraud_rate_percent

        from mart_transaction_behavior

        group by
            simulation_day,
            simulation_week,
            day_of_simulation_week,
            is_complete_day,
            transaction_type,
            transaction_family,
            balance_direction
        """
    )

    print("Views de dashboard criadas.")


def validate_database(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Confirma que os marts preservam os mesmos totais."""

    totals = connection.execute(
        """
        with daily as (
            select
                sum(transaction_count)
                    as transaction_count,

                sum(transaction_amount_total)
                    as transaction_amount_total,

                sum(fraudulent_transaction_count)
                    as fraud_count,

                sum(fraudulent_transaction_amount)
                    as fraud_amount,

                sum(flagged_transaction_count)
                    as flagged_count

            from mart_fraud_daily
        ),

        by_type as (
            select
                sum(transaction_count)
                    as transaction_count,

                sum(transaction_amount_total)
                    as transaction_amount_total,

                sum(fraudulent_transaction_count)
                    as fraud_count,

                sum(fraudulent_transaction_amount)
                    as fraud_amount,

                sum(flagged_transaction_count)
                    as flagged_count

            from mart_fraud_by_transaction_type
        ),

        behavior as (
            select
                sum(transaction_count)
                    as transaction_count,

                sum(transaction_amount_total)
                    as transaction_amount_total,

                sum(fraudulent_transaction_count)
                    as fraud_count,

                sum(fraudulent_transaction_amount)
                    as fraud_amount,

                sum(flagged_transaction_count)
                    as flagged_count

            from mart_transaction_behavior
        )

        select
            daily.transaction_count
                = by_type.transaction_count
                and daily.transaction_count
                = behavior.transaction_count,

            daily.transaction_amount_total
                = by_type.transaction_amount_total
                and daily.transaction_amount_total
                = behavior.transaction_amount_total,

            daily.fraud_count
                = by_type.fraud_count
                and daily.fraud_count
                = behavior.fraud_count,

            daily.fraud_amount
                = by_type.fraud_amount
                and daily.fraud_amount
                = behavior.fraud_amount,

            daily.flagged_count
                = by_type.flagged_count
                and daily.flagged_count
                = behavior.flagged_count

        from daily
        cross join by_type
        cross join behavior
        """
    ).fetchone()

    validation_names = (
        "quantidade de transações",
        "valor transacionado",
        "quantidade de fraudes",
        "valor fraudado",
        "quantidade sinalizada",
    )

    failures = [
        validation_name
        for validation_name, is_valid
        in zip(
            validation_names,
            totals,
            strict=True,
        )
        if not is_valid
    ]

    if failures:
        raise ValueError(
            "Inconsistências encontradas entre marts: "
            + ", ".join(failures)
        )

    print("Totais entre os marts validados.")


def print_summary(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Exibe os principais KPIs após a construção."""

    summary = connection.execute(
        """
        select
            transaction_count,
            transaction_amount_total,
            fraudulent_transaction_count,
            fraudulent_transaction_amount,
            flagged_transaction_count,
            fraud_rate_percent

        from bi_executive_summary
        """
    ).fetchone()

    print("\nResumo executivo:")
    print(f"Transações: {summary[0]:,}")
    print(f"Valor transacionado: {summary[1]:,.2f}")
    print(f"Fraudes: {summary[2]:,}")
    print(f"Valor fraudado: {summary[3]:,.2f}")
    print(f"Sinalizadas: {summary[4]:,}")
    print(f"Taxa de fraude: {summary[5]:.4f}%")


def build_database() -> None:
    manifest = load_manifest()

    LOCAL_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    if TEMPORARY_DATABASE_PATH.exists():
        TEMPORARY_DATABASE_PATH.unlink()

    connection = duckdb.connect(
        str(TEMPORARY_DATABASE_PATH)
    )

    try:
        connection.execute(
            "set threads = 4"
        )

        row_counts = create_base_tables(
            connection,
            manifest,
        )

        create_metadata_table(
            connection,
            manifest,
            row_counts,
        )

        create_dashboard_views(
            connection
        )

        validate_database(
            connection
        )

        print_summary(
            connection
        )

        connection.execute(
            "checkpoint"
        )

    finally:
        connection.close()

    TEMPORARY_DATABASE_PATH.replace(
        DATABASE_PATH
    )

    print(
        f"\nBanco criado com sucesso: "
        f"{DATABASE_PATH}"
    )


if __name__ == "__main__":
    try:
        build_database()
    except (
        duckdb.Error,
        FileNotFoundError,
        KeyError,
        RuntimeError,
        ValueError,
    ) as error:
        raise SystemExit(
            f"Erro ao construir o banco de BI: {error}"
        ) from error