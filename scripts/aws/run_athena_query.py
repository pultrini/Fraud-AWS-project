import os
import time
from typing import Any

import boto3
import dotenv

dotenv.load_dotenv()

WORKGROUP_NAME = "financial-risk-platform"
DATABASE_NAME = "financial_risk_raw"
CATALOG_NAME = "AwsDataCatalog"
CLIENT_REQUEST_TOKEN = "financial-risk-platform-raw-profile-v1"
POLL_INTERVAL_SECONDS = 2
QUERY_TIMEOUT_SECONDS = 5 * 60
ATHENA_PRICE_PER_TB_USD = 5.0

QUERY = """
SELECT
    COUNT(*) AS total_transactions,
    MIN(step) AS first_step,
    MAX(step) AS last_step,
    SUM(
        CASE WHEN isfraud = 1 THEN 1 ELSE 0 END
    ) AS fraud_transactions,
    ROUND(
        100.0 * SUM(
            CASE WHEN isfraud = 1 THEN 1 ELSE 0 END
        ) / COUNT(*),
        4
    ) AS fraud_rate_pct
FROM financial_risk_raw.raw_paysim
"""


def wait_for_query(athena: Any, query_execution_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    terminal_states = {"SUCCEEDED", "FAILED", "CANCELLED"}

    while time.monotonic() < deadline:
        response = athena.get_query_execution(
            QueryExecutionId=query_execution_id,
        )
        execution = response["QueryExecution"]
        state = execution["Status"]["State"]

        print(f"Estado da consulta: {state}")

        if state in terminal_states:
            return execution

        time.sleep(POLL_INTERVAL_SECONDS)

    athena.stop_query_execution(QueryExecutionId=query_execution_id)
    raise TimeoutError(
        f"A consulta Athena não terminou em {QUERY_TIMEOUT_SECONDS} segundos e "
        "foi cancelada."
    )


def fetch_first_result_row(
    athena: Any,
    query_execution_id: str,
) -> dict[str, str | None]:
    response = athena.get_query_results(
        QueryExecutionId=query_execution_id,
        MaxResults=2,
    )
    result_set = response["ResultSet"]
    columns = [
        column["Name"]
        for column in result_set["ResultSetMetadata"]["ColumnInfo"]
    ]
    rows = result_set.get("Rows", [])

    if len(rows) < 2:
        raise RuntimeError("A consulta não retornou a linha de resultado esperada.")

    values = [
        cell.get("VarCharValue") if cell else None
        for cell in rows[1].get("Data", [])
    ]

    if len(values) != len(columns):
        raise RuntimeError("Quantidade inesperada de valores no resultado Athena.")

    return dict(zip(columns, values, strict=True))


def main() -> None:
    region = os.environ["AWS_DEFAULT_REGION"]
    session = boto3.Session(region_name=region)
    athena = session.client("athena")

    response = athena.start_query_execution(
        QueryString=QUERY,
        ClientRequestToken=CLIENT_REQUEST_TOKEN,
        QueryExecutionContext={
            "Database": DATABASE_NAME,
            "Catalog": CATALOG_NAME,
        },
        WorkGroup=WORKGROUP_NAME,
    )
    query_execution_id = response["QueryExecutionId"]
    print(f"QueryExecutionId: {query_execution_id}")

    execution = wait_for_query(athena, query_execution_id)
    status = execution["Status"]
    state = status["State"]

    if state != "SUCCEEDED":
        reason = status.get("StateChangeReason", "sem detalhes")
        raise RuntimeError(f"Consulta terminou com status {state}: {reason}")

    result = fetch_first_result_row(athena, query_execution_id)
    statistics = execution.get("Statistics", {})
    bytes_scanned = statistics.get("DataScannedInBytes", 0)
    engine_execution_ms = statistics.get("EngineExecutionTimeInMillis", 0)
    total_execution_ms = statistics.get("TotalExecutionTimeInMillis", 0)
    estimated_cost = bytes_scanned / 10**12 * ATHENA_PRICE_PER_TB_USD

    print("\nResultado:")
    for column, value in result.items():
        print(f"  {column}: {value}")

    print("\nEstatísticas:")
    print(f"  bytes_scanned: {bytes_scanned:,}")
    print(f"  engine_execution_ms: {engine_execution_ms:,}")
    print(f"  total_execution_ms: {total_execution_ms:,}")
    print(f"  estimated_cost_usd: {estimated_cost:.8f}")


if __name__ == "__main__":
    main()
