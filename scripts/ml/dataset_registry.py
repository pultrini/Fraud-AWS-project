"""Versionamento e publicacao dos datasets de modelagem no S3."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import duckdb
from botocore.exceptions import ClientError

from ml_config import (
    DATASET_MANIFEST_PATH,
    ML_DATASET_S3_PREFIX,
    MODELING_DATA_DIRECTORY,
    PROJECT_ROOT,
    require_bucket_name,
)


DATASET_NAME = "fraud-modeling"
DATASET_FILES = {
    "training": "train_sample.parquet",
    "validation": "validation.parquet",
    "testing": "test.parquet",
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calcula o SHA-256 sem carregar o arquivo inteiro na memoria."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_parquet(path: Path) -> dict[str, Any]:
    """Coleta contagens e esquema diretamente do Parquet."""

    connection = duckdb.connect()
    try:
        row_count, fraud_count = connection.execute(
            """
            select
                count(*) as row_count,
                sum(cast(is_fraud as integer)) as fraud_count
            from read_parquet(?)
            """,
            [str(path)],
        ).fetchone()

        schema_rows = connection.execute(
            "describe select * from read_parquet(?)",
            [str(path)],
        ).fetchall()
    finally:
        connection.close()

    return {
        "row_count": int(row_count),
        "fraud_count": int(fraud_count),
        "fraud_rate_percent": 100.0 * fraud_count / row_count,
        "schema": [
            {"name": row[0], "type": row[1], "nullable": row[2] == "YES"}
            for row in schema_rows
        ],
    }


def build_dataset_manifest() -> dict[str, Any]:
    """Cria um manifesto deterministico para os tres splits."""

    source_manifest_path = PROJECT_ROOT / "data" / "ml" / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))

    files: dict[str, Any] = {}
    version_material: list[str] = []

    for role, filename in DATASET_FILES.items():
        path = MODELING_DATA_DIRECTORY / filename
        if not path.is_file():
            raise FileNotFoundError(f"Dataset nao encontrado: {path}")

        sha256 = sha256_file(path)
        inspection = inspect_parquet(path)
        version_material.append(f"{role}:{filename}:{sha256}")

        files[role] = {
            "filename": filename,
            "local_path": str(path.relative_to(PROJECT_ROOT)),
            "size_bytes": path.stat().st_size,
            "sha256": sha256,
            **inspection,
        }

    version = hashlib.sha256(
        "\n".join(version_material).encode("utf-8")
    ).hexdigest()[:16]

    created_at = datetime.now(UTC).isoformat()
    if DATASET_MANIFEST_PATH.is_file():
        previous_manifest = json.loads(
            DATASET_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        if previous_manifest.get("version") == version:
            created_at = previous_manifest["created_at"]

    bucket_name = require_bucket_name()
    s3_prefix = f"{ML_DATASET_S3_PREFIX}/{DATASET_NAME}/{version}"

    for file_metadata in files.values():
        key = f"{s3_prefix}/{file_metadata['filename']}"
        file_metadata["s3_key"] = key
        file_metadata["s3_uri"] = f"s3://{bucket_name}/{key}"

    return {
        "dataset_name": DATASET_NAME,
        "version": version,
        "created_at": created_at,
        "bucket": bucket_name,
        "s3_prefix": s3_prefix,
        "source_table": source_manifest["table"],
        "source_location": source_manifest["source_location"],
        "source_snapshot": Path(source_manifest["local_directory"]).name,
        "split_strategy": {
            "type": "temporal",
            "train_end_step": 322,
            "validation_end_step": 375,
            "legitimate_train_sample_percent": 5,
            "all_training_frauds_preserved": True,
        },
        "files": files,
    }


def object_is_current(
    s3_client: Any,
    bucket_name: str,
    key: str,
    size_bytes: int,
    sha256: str,
) -> bool:
    """Evita upload quando tamanho e hash remoto ja correspondem."""

    try:
        response = s3_client.head_object(Bucket=bucket_name, Key=key)
    except ClientError as error:
        if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise

    return (
        response["ContentLength"] == size_bytes
        and response.get("Metadata", {}).get("sha256") == sha256
    )


def upload_dataset_manifest(manifest: dict[str, Any]) -> dict[str, int]:
    """Publica os splits e o manifesto de forma idempotente."""

    session = boto3.Session()
    s3_client = session.client("s3")
    bucket_name = manifest["bucket"]

    uploaded = 0
    skipped = 0

    for role, file_metadata in manifest["files"].items():
        key = file_metadata["s3_key"]
        if object_is_current(
            s3_client,
            bucket_name,
            key,
            file_metadata["size_bytes"],
            file_metadata["sha256"],
        ):
            print(f"Ignorado (ja publicado): {role} -> {file_metadata['s3_uri']}")
            skipped += 1
            continue

        local_path = PROJECT_ROOT / file_metadata["local_path"]
        print(f"Enviando: {local_path.name} -> {file_metadata['s3_uri']}")
        s3_client.upload_file(
            str(local_path),
            bucket_name,
            key,
            ExtraArgs={
                "Metadata": {
                    "sha256": file_metadata["sha256"],
                    "dataset-version": manifest["version"],
                    "dataset-role": role,
                },
                "ServerSideEncryption": "AES256",
            },
        )
        uploaded += 1

    manifest_key = f"{manifest['s3_prefix']}/dataset_manifest.json"
    manifest["manifest_s3_uri"] = f"s3://{bucket_name}/{manifest_key}"
    manifest_bytes = json.dumps(
        manifest,
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    if not object_is_current(
        s3_client,
        bucket_name,
        manifest_key,
        len(manifest_bytes),
        manifest_sha256,
    ):
        s3_client.put_object(
            Bucket=bucket_name,
            Key=manifest_key,
            Body=manifest_bytes,
            ContentType="application/json",
            ServerSideEncryption="AES256",
            Metadata={
                "sha256": manifest_sha256,
                "dataset-version": manifest["version"],
            },
        )

    DATASET_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"uploaded": uploaded, "skipped": skipped}


def load_published_manifest() -> dict[str, Any]:
    """Carrega e valida o manifesto exigido pelos treinamentos."""

    if not DATASET_MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            "Dataset ainda nao foi publicado. Execute "
            "scripts/ml/publish_modeling_datasets.py."
        )
    manifest = json.loads(DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not manifest.get("manifest_s3_uri"):
        raise ValueError("Manifesto local nao possui uma URI S3 publicada.")
    return manifest
