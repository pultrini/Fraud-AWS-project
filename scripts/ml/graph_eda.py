import json
from pathlib import Path
from typing import Any

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_MANIFEST_PATH = (
    PROJECT_ROOT
    / "data"
    / "ml"
    / "manifest.json"
)

REPORT_DIRECTORY = (
    PROJECT_ROOT
    / "reports"
    / "ml"
    / "graph_eda"
)


def load_snapshot_directory() -> Path:
    """Localiza o snapshot completo sincronizado do S3."""

    if not SOURCE_MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            "Manifesto do snapshot não encontrado: "
            f"{SOURCE_MANIFEST_PATH}"
        )

    manifest = json.loads(
        SOURCE_MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    snapshot_directory = (
        PROJECT_ROOT
        / manifest["local_directory"]
    )

    if not snapshot_directory.is_dir():
        raise FileNotFoundError(
            "Diretório do snapshot não encontrado: "
            f"{snapshot_directory}"
        )

    parquet_files = list(
        snapshot_directory.rglob("*.parquet")
    )

    if not parquet_files:
        raise FileNotFoundError(
            "Nenhum arquivo Parquet encontrado em: "
            f"{snapshot_directory}"
        )

    print(
        f"Snapshot: {snapshot_directory}"
    )

    print(
        f"Arquivos Parquet: "
        f"{len(parquet_files)}"
    )

    return snapshot_directory


def create_connection(
        snapshot_directory: Path
) -> duckdb.DuckDBPyConnection:
    """Cria uma view sobre todos os parquet."""

    connection = duckdb.connect()

    parquet_pattern = str(
        snapshot_directory
        / "**"
        / "*.parquet"
    )

    transactions = connection.read_parquet(
        parquet_pattern,
        hive_partitioning=True,
    )

    transactions.create_view(
        "transactions"
    )

    return connection


def calculate_graph_overview(
        connection: duckdb.DuckDBPyConnection
) -> dict[str, Any]:
    """Calcula as métricas gerais do grafo direcionado."""

    result = connection.execute(
        """
        with graph_nodes as (

        select
            origin_account_id as account_id
        from transactions

        union

        select
            destination_account_id as account_id
        from transactions

    ),

    transaction_summary as (

        select
            count(*) as transaction_count,

            count(
                distinct (
                    origin_account_id,
                    destination_account_id
                )
            ) as directed_pair_count,

            sum(
                cast(is_fraud as bigint)
            ) as fraud_count,

            sum(
                case
                    when origin_account_id
                        = destination_account_id
                    then 1
                    else 0
                end
            ) as self_loop_count,

            sum(transaction_amount)
                as total_transaction_amount,

            avg(transaction_amount)
                as average_transaction_amount,

            min(simulation_step)
                as minimum_step,

            max(simulation_step)
                as maximum_step

        from transactions

    )

    select
        transaction_summary.*,

        (
            select count(*)
            from graph_nodes
        ) as node_count

    from transaction_summary
    """
    ).fetchone()

    columns = [
        "transaction_count",
        "directed_pair_count",
        "fraud_count",
        "self_loop_count",
        "total_transaction_amount",
        "average_transaction_amount",
        "minimum_step",
        "maximum_step",
        "node_count",
    ]

    overview = dict(
        zip(columns, result)
    )

    transaction_count = int(
        overview["transaction_count"]
    )

    node_count = int(overview["node_count"])

    directed_pair_count = int(overview["directed_pair_count"])

    overview["repeated_edge_count"] = (
        transaction_count
        - directed_pair_count
    )

    overview["fraud_rate_percent"] = (
        100
        * int(overview["fraud_count"])
        / transaction_count
    )

    possible_directed_edges = (
        node_count
        * (node_count - 1)
    )

    overview["graph_density"] = (
        directed_pair_count
        / possible_directed_edges
        if possible_directed_edges > 0
        else 0.0
    )

    return overview



def save_overview(
        overview: dict[str, Any]
) -> Path:
    """Salva as métricas gerais em JSON"""

    REPORT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        REPORT_DIRECTORY
        / "graph_overview.json"
    )

    destination.write_text(
        json.dumps(
            overview,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    return destination

def main() -> None:
    snapshot_directory = load_snapshot_directory()
    connection = create_connection(snapshot_directory)

    try:
        print(
            "Calculando visão geral do grafo..."
        )
        overview = calculate_graph_overview(connection)
        destination = save_overview(overview)

    finally:
        connection.close()

    print(json.dumps(
        overview,
        indent=2,
        ensure_ascii=False,
        default=str
    ))

    print(
        "\nResultado salvo em: "
        f"{destination}"
    )

if __name__ == "__main__":
    main()