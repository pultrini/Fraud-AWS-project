"""Configuracoes compartilhadas da camada de machine learning."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

ML_DATA_ROOT = PROJECT_ROOT / "data" / "ml"
MODELING_DATA_DIRECTORY = ML_DATA_ROOT / "modeling"
DATASET_MANIFEST_PATH = MODELING_DATA_DIRECTORY / "dataset_manifest.json"

MLFLOW_LOCAL_DIRECTORY = ML_DATA_ROOT / "mlflow"
MLFLOW_DATABASE_PATH = MLFLOW_LOCAL_DIRECTORY / "tracking.db"

MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI",
    "http://127.0.0.1:5000",
)
MLFLOW_HOST = os.getenv("MLFLOW_HOST", "127.0.0.1")
MLFLOW_PORT = int(os.getenv("MLFLOW_PORT", "5000"))
MLFLOW_EXPERIMENT_NAME = os.getenv(
    "MLFLOW_EXPERIMENT_NAME",
    "fraud-detection",
)
MLFLOW_REGISTERED_MODEL_NAME = os.getenv(
    "MLFLOW_REGISTERED_MODEL_NAME",
    "fraud-detection-classifier",
)

S3_PROJECT_PREFIX = os.getenv(
    "S3_PROJECT_PREFIX",
    "financial-risk-platform",
).strip("/")
ML_DATASET_S3_PREFIX = os.getenv(
    "ML_DATASET_S3_PREFIX",
    f"{S3_PROJECT_PREFIX}/ml/datasets",
).strip("/")
MLFLOW_ARTIFACT_S3_PREFIX = os.getenv(
    "MLFLOW_ARTIFACT_S3_PREFIX",
    f"{S3_PROJECT_PREFIX}/mlflow-artifacts",
).strip("/")


def require_bucket_name() -> str:
    """Retorna o bucket configurado sem expor credenciais."""

    bucket_name = os.getenv("BUCKET_NAME")
    if not bucket_name:
        raise RuntimeError("BUCKET_NAME nao esta definido no arquivo .env.")
    return bucket_name


def mlflow_artifact_destination() -> str:
    """URI S3 usada pelo servidor para armazenar artefatos."""

    return f"s3://{require_bucket_name()}/{MLFLOW_ARTIFACT_S3_PREFIX}"

