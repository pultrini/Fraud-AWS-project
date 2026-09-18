"""Inicia o tracking server local com artefatos persistidos no S3."""

from __future__ import annotations

import os
import shutil
import subprocess

from ml_config import (
    MLFLOW_DATABASE_PATH,
    MLFLOW_HOST,
    MLFLOW_LOCAL_DIRECTORY,
    MLFLOW_PORT,
    mlflow_artifact_destination,
)


def main() -> None:
    MLFLOW_LOCAL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    backend_uri = f"sqlite:///{MLFLOW_DATABASE_PATH}"
    artifact_destination = mlflow_artifact_destination()

    print(f"Backend MLflow: {backend_uri}")
    print(f"Artefatos MLflow: {artifact_destination}")
    print(f"Interface: http://{MLFLOW_HOST}:{MLFLOW_PORT}")

    mlflow_executable = shutil.which("mlflow")
    if mlflow_executable is None:
        raise RuntimeError(
            "Executavel do MLflow nao encontrado. Execute o script com `uv run`."
        )

    command = [
        mlflow_executable,
        "server",
        "--backend-store-uri",
        backend_uri,
        "--artifacts-destination",
        artifact_destination,
        "--host",
        MLFLOW_HOST,
        "--port",
        str(MLFLOW_PORT),
        "--workers",
        "1",
    ]
    environment = {**os.environ, "MLFLOW_DISABLE_AGENT_HINT": "1"}
    raise SystemExit(subprocess.call(command, env=environment))


if __name__ == "__main__":
    main()
