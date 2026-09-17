import math
import os
import time
from typing import Any

import boto3

WORKGROUP_NAME = "financial-risk-platform"
PRICE_PER_TB_USD = 5.0

BYTES_PER_MB = 1024**2
BYTES_PER_TB = 10**12
MINIMUM_BILLABLE_BYTES = 10 * BYTES_PER_MB

QUERIES = {
    "CSV RAW": """
        with transactions as (
            select
                upper(trim(type)) as transaction_type,
                cast(amount as decimal(18, 2)) as transaction_amount,
                isfraud = 1 as is_fraud
            from financial_risk_raw.raw_paysim
        )

        select
            transaction_type,
            count(*) as transaction_count,
            sum(transaction_amount) as transaction_amount_total,
            sum(
                case
                    when is_fraud then 1
                    else 0
                end
            ) as fraudulent_transaction_count
        from transactions
        group by transaction_type
        order by transaction_type
    """,
    "PARQUET FACT": """
        select
            transaction_type,
            count(*) as transaction_count,
            sum(transaction_amount) as transaction_amount_total,
            sum(
                case
                    when is_fraud then 1
                    else 0
                end
            ) as fraudulent_transaction_count
        from financial_risk_dev.fact_transactions
        group by transaction_type
        order by transaction_type
    """,
}


def calculate_billable_bytes(scanned_bytes: int) -> int:
    rounded_bytes = (
        math.ceil(scanned_bytes / BYTES_PER_MB)
        * BYTES_PER_MB
    )
    return max(rounded_bytes, MINIMUM_BILLABLE_BYTES)

def calculate_cost_usd(scanned_bytes: int) -> float:
    billiable_bytes = calculate_billable_bytes(scanned_bytes)

    return billiable_bytes / BYTES_PER_MB * PRICE_PER_TB_USD

def get_result_rows(
        athena: Any,
        query_execution_id: str
) -> list[tuple[str,...]]:
    response = athena.get_query_results(
        QueryExecutionId=query_execution_id
    )

    rows = response["ResultSet"]["Rows"]


    data_rows = rows[1:]

    return [
        tuple(
            column.get("VarCharValue", "")
            for column in row["Data"]
        )
        for row in data_rows
    ]


def execute_query(
    athena: Any,
    label: str,
    query: str,
) -> dict[str, Any]:
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            "Catalog": "AwsDataCatalog",
            "Database": "financial_risk_raw",
        },
        WorkGroup=WORKGROUP_NAME,
        ResultReuseConfiguration={
            "ResultReuseByAgeConfiguration": {
                "Enabled": False,
            }
        },
    )

    query_execution_id = response["QueryExecutionId"]

    while True:
        execution = athena.get_query_execution(
            QueryExecutionId=query_execution_id
        )["QueryExecution"]

        state = execution["Status"]["State"]

        if state == "SUCCEEDED":
            break

        if state in {"FAILED", "CANCELLED"}:
            reason = execution["Status"].get(
                "StateChangeReason",
                "Motivo não informado",
            )
            raise RuntimeError(
                f"Consulta {label} terminou como {state}: {reason}"
            )

        time.sleep(1)

    statistics = execution["Statistics"]
    scanned_bytes = statistics["DataScannedInBytes"]

    return {
        "label": label,
        "query_execution_id": query_execution_id,
        "scanned_bytes": scanned_bytes,
        "billable_bytes": calculate_billable_bytes(scanned_bytes),
        "engine_time_ms": statistics.get(
            "EngineExecutionTimeInMillis",
            0,
        ),
        "total_time_ms": statistics.get(
            "TotalExecutionTimeInMillis",
            0,
        ),
        "estimated_cost_usd": calculate_cost_usd(scanned_bytes),
        "rows": get_result_rows(athena, query_execution_id),
    }


def print_result(result: dict[str, Any]) -> None:
    print(f"\n=== {result['label']} ===")
    print(f"QueryExecutionId: {result['query_execution_id']}")
    print(
        "Dados escaneados: "
        f"{result['scanned_bytes'] / BYTES_PER_MB:,.2f} MiB"
    )
    print(
        "Dados faturáveis: "
        f"{result['billable_bytes'] / BYTES_PER_MB:,.2f} MiB"
    )
    print(
        "Tempo do engine: "
        f"{result['engine_time_ms'] / 1000:.2f} s"
    )
    print(
        "Tempo total: "
        f"{result['total_time_ms'] / 1000:.2f} s"
    )
    print(
        "Custo estimado: "
        f"US$ {result['estimated_cost_usd']:.8f}"
    )


def main() -> None:
    region = os.environ["AWS_DEFAULT_REGION"]

    athena = boto3.client(
        "athena",
        region_name=region,
    )

    results = [
        execute_query(athena, label, query)
        for label, query in QUERIES.items()
    ]

    for result in results:
        print_result(result)

    csv_result, parquet_result = results

    if csv_result["rows"] != parquet_result["rows"]:
        raise RuntimeError(
            "As consultas retornaram resultados diferentes."
        )

    reduction_percent = (
        1
        - parquet_result["scanned_bytes"]
        / csv_result["scanned_bytes"]
    ) * 100

    scan_ratio = (
        csv_result["scanned_bytes"]
        / parquet_result["scanned_bytes"]
    )

    print("\n=== COMPARAÇÃO ===")
    print("Resultados SQL idênticos: sim")
    print(
        "Redução de dados escaneados: "
        f"{reduction_percent:.2f}%"
    )
    print(
        "O CSV escaneou "
        f"{scan_ratio:.2f}x mais dados que o Parquet."
    )


if __name__ == "__main__":
    main()
