import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATABASE_NAME = "financial_risk_dev"
TABLE_NAME = "mart_fraud_training_features"

LOCAL_ROOT = PROJECT_ROOT / "data" / "ml"
PARQUET_ROOT = LOCAL_ROOT / "parquet"
MANIFEST_PATH = LOCAL_ROOT / "manifest.json"


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Separa uma URI S3 em bucket e prefixo"""

    parsed_uri = urlparse(s3_uri)

    if parsed_uri.scheme != "s3":
        raise ValueError(
            f"Esquema inválido na URI: {s3_uri}" 
        )

    if not parsed_uri.netloc:
        raise ValueError(
            f"Bucket não encontrado na URI: {s3_uri}"
        )

    bucket_name = parsed_uri.netloc

    object_prefix = (
        parsed_uri.path.lstrip("/").rstrip("/") + "/"
    )
    return bucket_name, object_prefix



def get_table_location(
    glue_client,
) -> str:
    """Obtém no Glue a localização física da tabela."""

    response = glue_client.get_table(
        DatabaseName=DATABASE_NAME,
        Name=TABLE_NAME,
    )

    table = response["Table"]

    table_type = table.get("TableType")

    location = (
        table
        .get("StorageDescriptor", {})
        .get("Location")
    )

    if not location:
        raise ValueError(
            f"A tabela '{TABLE_NAME}' não possui "
            f"localização física. Tipo: {table_type}. "
            "Views não possuem arquivos próprios no S3."
        )

    return location

def list_parquet_objects(
    s3_client,
    bucket_name: str,
    object_prefix: str,
) -> list[dict]:
    """Lista os objetos Parquet existentes no prefixo."""

    paginator = s3_client.get_paginator(
        "list_objects_v2"
    )

    pages = paginator.paginate(
        Bucket=bucket_name,
        Prefix=object_prefix,
    )

    parquet_objects = []

    for page in pages:
        for s3_object in page.get("Contents", []):
            object_key = s3_object["Key"]
            object_size = s3_object["Size"]

            if object_size < 4:
                continue

            if object_key.endswith("/"):
                continue

            response = s3_client.get_object(
                Bucket=bucket_name,
                Key=object_key,
                Range="bytes=0-3",
            )

            response_body = response["Body"]

            try:
                file_signature = response_body.read()
            finally:
                response_body.close()

            if file_signature != b"PAR1":
                continue

            parquet_objects.append(
                {
                    "key": object_key,
                    "size": object_size,
                    "etag": (
                        s3_object["ETag"]
                        .strip('"')
                    ),
                }
            )

    return parquet_objects

def download_object(
        s3_client,
        bucket_name: str,
        object_key: str,
        destination_path: Path,
        expected_size: int
) -> str:
    """Baixa um arquivo e verifica seu tamanho."""

    if (
        destination_path.exists() and destination_path.stat().st_size == expected_size
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
        str(temporary_path)
    )

    downloaded_size = temporary_path.stat().st_size

    if downloaded_size != expected_size:
        raise RuntimeError(
            f"Download incompleto de '{object_key}'. "
            f"Esperado: {expected_size} bytes. "
            f"Obtido: {downloaded_size} bytes."
        )

    temporary_path.replace(destination_path)

    return "downloaded"


def sync_dataset(
        glue_client,
        s3_client
) -> dict:
    """Sincroniza localmente o dataset de ML."""

    table_location = get_table_location(
        glue_client
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
            "Nenhum arquivo Parquet foi encontrado em "
            f"'{table_location}'."
        )

    snapshot_id = Path(
        object_prefix.rstrip("/")
    ).name

    local_dataset_directory = (
        PARQUET_ROOT / TABLE_NAME / snapshot_id
    )
    downloaded_count = 0
    skipped_count = 0
    manifest_files = []

    print(f"Tabela: {TABLE_NAME}")
    print(f"Origem: {table_location}")
    print(f"Destino: {local_dataset_directory}")
    print(
        f"Arquivos encontrados: "
        f"{len(parquet_objects)}"
    )

    for index, parquet_object in enumerate(
        parquet_objects,
        start=1,
    ):
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
            local_dataset_directory
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

        print(
            f"[{index}/{len(parquet_objects)}] "
            f"{status}: {relative_path}"
        )

        manifest_files.append(
            {
                "s3_key": object_key,
                "local_path": str(
                    destination_path.relative_to(
                        PROJECT_ROOT
                    )
                ),
                "size": parquet_object["size"],
                "etag": parquet_object["etag"],
            }
        )

    return {
        "database": DATABASE_NAME,
        "table": TABLE_NAME,
        "source_location": table_location,
        "local_directory": str(
            local_dataset_directory.relative_to(
                PROJECT_ROOT
            )
        ),
        "synchronized_at": datetime.now(
            UTC
        ).isoformat(),
        "downloaded_files": downloaded_count,
        "skipped_files": skipped_count,
        "total_files": len(parquet_objects),
        "files": manifest_files,
    }

def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    session = boto3.Session()

    glue_client = session.client("glue")
    s3_client = session.client("s3")

    manifest = sync_dataset(
        glue_client=glue_client,
        s3_client=s3_client,
    )

    LOCAL_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\nSincronização concluída.")
    print(
        f"Baixados: "
        f"{manifest['downloaded_files']}"
    )
    print(
        f"Ignorados: "
        f"{manifest['skipped_files']}"
    )
    print(
        f"Manifesto: {MANIFEST_PATH}"
    )

if __name__ == "__main__":
    try:
        main()
    except (
        BotoCoreError,
        ClientError,
        OSError,
        ValueError,
        RuntimeError
    ) as error:
        raise SystemExit (
            f"Erro ao sincronizar dataset: {error}"
        ) from error