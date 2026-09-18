import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError


DATABASE_NAME = "financial_risk_dev"

MART_NAMES = (
    "mart_fraud_by_transaction_type",
    "mart_fraud_daily",
    "mart_customer_risk",
    "mart_transaction_behavior",
)

LOCAL_ROOT = Path("data/bi")
PARQUET_ROOT = LOCAL_ROOT / "parquet"
MANIFEST_PATH = LOCAL_ROOT / "manifest.json"


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Separa uma URI S3 em bucket e prefixo."""

    parsed_uri = urlparse(s3_uri)

    if parsed_uri.scheme != "s3" or not parsed_uri.netloc:
        raise ValueError(f"URI S3 inválida: {s3_uri}")

    bucket_name = parsed_uri.netloc
    object_prefix = parsed_uri.path.lstrip("/").rstrip("/") + "/"

    return bucket_name, object_prefix


def get_table_location(glue_client, table_name: str) -> str:
    """Consulta no Glue a localização física de uma tabela."""

    response = glue_client.get_table(
        DatabaseName=DATABASE_NAME,
        Name=table_name,
    )

    try:
        return response["Table"]["StorageDescriptor"]["Location"]
    except KeyError as error:
        raise ValueError(
            f"A tabela '{table_name}' não possui localização no Glue."
        ) from error


def list_parquet_objects(
    s3_client,
    bucket_name: str,
    object_prefix: str,
) -> list[dict]:
    """Lista os objetos que possuem a assinatura binária do Parquet."""

    paginator = s3_client.get_paginator("list_objects_v2")

    pages = paginator.paginate(
        Bucket=bucket_name,
        Prefix=object_prefix,
    )

    parquet_objects = []

    for page in pages:
        for s3_object in page.get("Contents", []):
            object_key = s3_object["Key"]

            if s3_object["Size"] < 4 or object_key.endswith("/"):
                continue

            response = s3_client.get_object(
                Bucket=bucket_name,
                Key=object_key,
                Range="bytes=0-3",
            )

            response_body = response["Body"]

            try:
                parquet_signature = response_body.read()
            finally:
                response_body.close()

            if parquet_signature == b"PAR1":
                parquet_objects.append(
                    {
                        "key": object_key,
                        "size": s3_object["Size"],
                        "etag": s3_object["ETag"].strip('"'),
                    }
                )

    return parquet_objects


def download_object(
    s3_client,
    bucket_name: str,
    object_key: str,
    destination_path: Path,
    expected_size: int,
) -> str:
    """
    Baixa um objeto de maneira segura.

    Retorna 'skipped' quando o arquivo local já possui o tamanho
    esperado e 'downloaded' quando um download foi realizado.
    """

    if (
        destination_path.exists()
        and destination_path.stat().st_size == expected_size
    ):
        return "skipped"

    destination_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = destination_path.with_suffix(
        destination_path.suffix + ".part"
    )

    s3_client.download_file(
        bucket_name,
        object_key,
        str(temporary_path),
    )

    downloaded_size = temporary_path.stat().st_size

    if downloaded_size != expected_size:
        raise RuntimeError(
            f"Tamanho inválido para '{object_key}': "
            f"esperado={expected_size}, "
            f"baixado={downloaded_size}"
        )

    temporary_path.replace(destination_path)

    return "downloaded"


def sync_table(
    glue_client,
    s3_client,
    table_name: str,
) -> dict:
    """Sincroniza localmente os arquivos Parquet de um mart."""

    table_location = get_table_location(
        glue_client,
        table_name,
    )

    bucket_name, object_prefix = parse_s3_uri(
        table_location
    )

    parquet_objects = list_parquet_objects(
        s3_client,
        bucket_name,
        object_prefix,
    )

    if not parquet_objects:
        raise RuntimeError(
            f"Nenhum arquivo Parquet encontrado para "
            f"'{table_name}' em '{table_location}'."
        )

    # As tabelas criadas pelo Athena usam normalmente um UUID
    # como último componente do caminho.
    snapshot_id = Path(
        object_prefix.rstrip("/")
    ).name

    local_table_directory = (
        PARQUET_ROOT
        / table_name
        / snapshot_id
    )

    downloaded_count = 0
    skipped_count = 0
    manifest_files = []

    print(f"\nSincronizando: {table_name}")
    print(f"Origem: {table_location}")
    print(f"Destino: {local_table_directory}")

    for parquet_object in parquet_objects:
        object_key = parquet_object["key"]

        relative_key = object_key.removeprefix(
            object_prefix
        )

        relative_path = Path(relative_key)

        if relative_path.suffix.lower() != ".parquet":
            relative_path = relative_path.with_name(
                relative_path.name + ".parquet"
            )

        destination_path = (
            local_table_directory
            / relative_path
        )

        status = download_object(
            s3_client=s3_client,
            bucket_name=bucket_name,
            object_key=object_key,
            destination_path=destination_path,
            expected_size=parquet_object["size"],
        )

        if status == "downloaded":
            downloaded_count += 1
        else:
            skipped_count += 1

        manifest_files.append(
            {
                "s3_key": object_key,
                "local_path": str(destination_path),
                "size_bytes": parquet_object["size"],
                "etag": parquet_object["etag"],
            }
        )

    total_size = sum(
        parquet_object["size"]
        for parquet_object in parquet_objects
    )

    print(
        f"Arquivos: {len(parquet_objects)} "
        f"(baixados={downloaded_count}, "
        f"reutilizados={skipped_count})"
    )
    print(f"Tamanho: {total_size:,} bytes")

    return {
        "table_name": table_name,
        "source_s3_uri": table_location,
        "snapshot_id": snapshot_id,
        "local_directory": str(
            local_table_directory
        ),
        "object_count": len(parquet_objects),
        "size_bytes": total_size,
        "downloaded_count": downloaded_count,
        "skipped_count": skipped_count,
        "files": manifest_files,
    }


def main() -> None:
    region_name = os.environ.get(
        "AWS_DEFAULT_REGION"
    )

    if not region_name:
        raise RuntimeError(
            "A variável AWS_DEFAULT_REGION não está configurada."
        )

    session = boto3.Session(
        region_name=region_name
    )

    glue_client = session.client("glue")
    s3_client = session.client("s3")

    PARQUET_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "database_name": DATABASE_NAME,
        "region_name": region_name,
        "tables": {},
    }

    print(
        f"Iniciando sincronização dos marts "
        f"do database '{DATABASE_NAME}'."
    )

    for table_name in MART_NAMES:
        table_manifest = sync_table(
            glue_client=glue_client,
            s3_client=s3_client,
            table_name=table_name,
        )

        manifest["tables"][table_name] = (
            table_manifest
        )

    MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    total_size = sum(
        table["size_bytes"]
        for table in manifest["tables"].values()
    )

    total_objects = sum(
        table["object_count"]
        for table in manifest["tables"].values()
    )

    print("\nSincronização concluída.")
    print(f"Tabelas: {len(MART_NAMES)}")
    print(f"Arquivos Parquet: {total_objects}")
    print(f"Tamanho total: {total_size:,} bytes")
    print(f"Manifesto: {MANIFEST_PATH}")


if __name__ == "__main__":
    try:
        main()
    except (
        BotoCoreError,
        ClientError,
        RuntimeError,
        ValueError,
    ) as error:
        raise SystemExit(
            f"Erro ao sincronizar os marts: {error}"
        ) from error
