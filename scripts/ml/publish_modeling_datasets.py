"""Publica uma versao imutavel dos datasets preparados no S3."""

from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError

from dataset_registry import build_dataset_manifest, upload_dataset_manifest


def main() -> None:
    manifest = build_dataset_manifest()
    print(f"Dataset: {manifest['dataset_name']}")
    print(f"Versao: {manifest['version']}")
    print(f"Destino: s3://{manifest['bucket']}/{manifest['s3_prefix']}")

    result = upload_dataset_manifest(manifest)
    print("\nPublicacao concluida.")
    print(f"Enviados: {result['uploaded']}")
    print(f"Ignorados: {result['skipped']}")
    print(f"Manifesto: {manifest['manifest_s3_uri']}")


if __name__ == "__main__":
    try:
        main()
    except (BotoCoreError, ClientError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(f"Erro ao publicar datasets: {error}") from error

