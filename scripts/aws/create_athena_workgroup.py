# scripts/aws/create_athena_workgroup.py
import os
import sys
import boto3
from botocore.exceptions import ClientError
import dotenv

dotenv.load_dotenv()

WORKGROUP_NAME = "financial-risk-platform"
BYTES_PER_GIBIBYTE = 1024**3


def main() -> None:
    bucket_name = os.environ["BUCKET_NAME"]
    region = os.environ["AWS_DEFAULT_REGION"]

    if not bucket_name:
        print("Erro: A variável BUCKET_NAME não foi definida no ambiente.")
        sys.exit(1)

    if not region:
        print("Erro: A variável AWS_DEFAULT_REGION não foi definida no ambiente.")
        sys.exit(1)

    session = boto3.Session(region_name=region)
    athena = session.client("athena")
    sts = session.client("sts")


    try:
        account_id = sts.get_caller_identity()["Account"]
    except ClientError as e:
        print(f"Erro ao obter ID da conta via STS: {e}")
        sys.exit(1)


    output_location = (
        f"s3://{bucket_name}/"
        "financial-risk-platform/athena-results/"
    )

    configuration = {
        "ResultConfiguration": {
            "OutputLocation": output_location,
            "EncryptionConfiguration": {
                "EncryptionOption": "SSE_S3",
            },
            "ExpectedBucketOwner": account_id,
        },
        "EnforceWorkGroupConfiguration": True,
        "PublishCloudWatchMetricsEnabled": False,
        "BytesScannedCutoffPerQuery": BYTES_PER_GIBIBYTE,
        "RequesterPaysEnabled": False,
        "EngineVersion": {
            "SelectedEngineVersion": "Athena engine version 3",
        },
    }


    try:
        existing_names: set[str] = set()
        next_token: str | None = None

        while True:
            request = {}
            if next_token is not None:
                request["NextToken"] = next_token

            response = athena.list_work_groups(**request)
            existing_names.update(
                item["Name"] for item in response.get("WorkGroups", [])
            )

            next_token = response.get("NextToken")
            if next_token is None:
                break
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ["AccessDenied", "AccessDeniedException"]:
            print("AccessDenied ao listar os workgroups do Athena.")
            sys.exit(1)
        raise


    if WORKGROUP_NAME in existing_names:
        print(f"O Workgroup '{WORKGROUP_NAME}' já existe. Nenhuma alteração realizada.")
    else:
        try:
            athena.create_work_group(
                Name=WORKGROUP_NAME,
                Description="Consultas da Financial Risk & Fraud Analytics Platform",
                Configuration=configuration,
                Tags=[
                    {"Key": "Project", "Value": "financial-risk-platform"},
                    {"Key": "Environment", "Value": "dev"},
                ],
            )
            print(
                f"Workgroup '{WORKGROUP_NAME}' criado com sucesso!\n"
                f"- Resultados: {output_location}\n"
                f"- Limite por consulta: 1 GiB (Cutoff)"
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ["AccessDenied", "AccessDeniedException"]:
                print(f"AccessDenied ao criar o Workgroup '{WORKGROUP_NAME}'.")
                sys.exit(1)
            raise


if __name__ == "__main__":
    main()
