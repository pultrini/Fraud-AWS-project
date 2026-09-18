"""Funcoes comuns de tracking para todos os modelos do projeto."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
from mlflow.models import infer_signature

from dataset_registry import load_published_manifest
from ml_config import (
    DATASET_MANIFEST_PATH,
    MLFLOW_EXPERIMENT_NAME,
    MLFLOW_REGISTERED_MODEL_NAME,
    MLFLOW_TRACKING_URI,
)


def configure_mlflow() -> Any:
    """Configura o servidor e devolve o experimento ativo."""

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    return mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)


def log_dataset_input(
    dataframe: pd.DataFrame,
    manifest: dict[str, Any],
    role: str,
) -> None:
    """Registra origem, versao, esquema e perfil de um split."""

    file_metadata = manifest["files"][role]
    dataset = mlflow.data.from_pandas(
        dataframe,
        source=file_metadata["s3_uri"],
        name=f"{manifest['dataset_name']}-{role}",
        digest=file_metadata["sha256"][:16],
    )
    mlflow.log_input(
        dataset,
        context=role,
        tags={"dataset_version": manifest["version"]},
    )


def flatten_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    """Converte metricas aninhadas em chaves aceitas pelo MLflow."""

    flattened: dict[str, float] = {}
    for split_name, split_metrics in metrics.items():
        if not isinstance(split_metrics, dict):
            continue
        for metric_name, value in split_metrics.items():
            if isinstance(value, (int, float)):
                flattened[f"{split_name}_{metric_name}"] = float(value)
    return flattened


def log_common_run_metadata(
    *,
    model_name: str,
    parameters: dict[str, Any],
    metrics: dict[str, Any],
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Registra informacoes comuns e retorna o manifesto do dataset."""

    manifest = load_published_manifest()
    mlflow.log_params(
        {
            **parameters,
            "model_name": model_name,
            "dataset_name": manifest["dataset_name"],
            "dataset_version": manifest["version"],
            "source_snapshot": manifest["source_snapshot"],
        }
    )
    mlflow.log_metrics(flatten_metrics(metrics))
    mlflow.set_tags(
        {
            "project": "financial-risk-platform",
            "problem_type": "binary-classification",
            "model_name": model_name,
            **(tags or {}),
        }
    )
    mlflow.log_artifact(str(DATASET_MANIFEST_PATH), artifact_path="dataset")
    return manifest


def log_sklearn_model(
    *,
    pipeline: Any,
    input_example: pd.DataFrame,
    artifact_name: str = "model",
) -> Any:
    """Registra o pipeline com assinatura e cria versao no Registry."""

    output_example = pipeline.predict_proba(input_example)
    signature = infer_signature(input_example, output_example)
    return mlflow.sklearn.log_model(
        sk_model=pipeline,
        name=artifact_name,
        registered_model_name=MLFLOW_REGISTERED_MODEL_NAME,
        signature=signature,
        input_example=input_example,
        pyfunc_predict_fn="predict_proba",
        serialization_format="cloudpickle",
        metadata={"prediction_output": "class_probabilities"},
    )


def write_run_reference(path: Path) -> None:
    """Persiste localmente a referencia do run para automacoes futuras."""

    active_run = mlflow.active_run()
    if active_run is None:
        raise RuntimeError("Nenhum run MLflow esta ativo.")
    payload = {
        "run_id": active_run.info.run_id,
        "experiment_id": active_run.info.experiment_id,
        "artifact_uri": active_run.info.artifact_uri,
        "tracking_uri": mlflow.get_tracking_uri(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

