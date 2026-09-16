import os
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
import dotenv


dotenv.load_dotenv()
def main() -> None:
    bucket_name = os.environ["BUCKET_NAME"]

    local_file=Path("data/raw/PS_20174392719_1491204439457_log.csv")
    if not local_file.exists():
        raise FileNotFoundError(f"Arquivo não encontrado em {local_file.resolve}")

    object_key = (
        "financial-risk-platform/raw/paysim/"
        "PS_20174392719_1491204439457_log.csv"
    )

    s3 = boto3.client("s3")

    try:
        existing = s3.head_object(
            Bucket=bucket_name,
            Key=object_key,
        )
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        if error_code not in {"404", "NoSuchKey"}:
            raise error
    else:
        remote_size = existing["ContentLength"]
        local_size = local_file.stat().st_size

        if remote_size == local_size:
            print("O arquivo já existe com o mesmo tamanho. Upload ignorado.")
            return

        raise RuntimeError(
            "O objeto já existe com tamanho diferente. "
            "Não será sobrescrito automaticamente."
        )

    megabyte = 1024 * 1024

    transfer_config = TransferConfig(
        multipart_threshold=64*megabyte,
        multipart_chunksize=64*megabyte,
        max_concurrency=4
    )

    print(f"Iniciando upload de '{local_file.name}' para 's3://{bucket_name}/{object_key}'...")

    s3.upload_file(
        Filename=str(local_file),
        Bucket=bucket_name,
        Key=object_key,
        ExtraArgs={
            "ContentType": "text/csv",
            "ChecksumAlgorithm": "SHA256",
            "Metadata": {
                "dataset": "paysim",
                "layer": "raw",
                "source": "kaggle",
            }
        },
        Config=transfer_config
    )

    uploaded_object = s3.head_object(
        Bucket=bucket_name,
        Key=object_key
    )

    local_size = local_file.stat().st_size
    remote_size = uploaded_object["ContentLength"]

    if local_size != remote_size:
        raise RuntimeError(
            f"O tamanho remoto ({remote_size} bytes) difere do arquivo local ({local_size} bytes)."
        )

    print(f"Upload concluído com sucesso e tamanho verificado: {remote_size:,} bytes.")


if __name__ == "__main__":
    main()