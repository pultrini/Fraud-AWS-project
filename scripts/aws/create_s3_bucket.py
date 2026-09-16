import os

import dotenv
import boto3
from botocore.exceptions import ClientError

dotenv.load_dotenv()

def main() -> None:
    bucket_name = os.environ["BUCKET_NAME"]
    region = os.environ["AWS_DEFAULT_REGION"]

    session = boto3.Session(region_name=region)
    s3 = session.client("s3")

    bucket_exists_in_account = False
    try:
        response = s3.list_buckets()
        existing_buckets = [b["Name"] for b in response.get("Buckets", [])]
        if bucket_name in existing_buckets:
            bucket_exists_in_account = True
            print(f"O bucket {bucket_name} já existe na conta")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ["AccessDenied", "AccessDeniedException"]:
            print("AccessDenied ao listar buckets. Verifique suas permissões IAM.")
        raise 

    if not bucket_exists_in_account:
        create_parameters = {
            "Bucket": bucket_name,
            "ObjectOwnership": "BucketOwnerEnforced"
        }
        if region != "us-east-1":
            create_parameters["CreateBucketConfiguration"] = {
                "LocationConstraint": region,
            }

        try:
            s3.create_bucket(**create_parameters)
            print(f"Bucket '{bucket_name}' criado com sucesso na região '{region}'.")
        except ClientError as error:
            error_code = error.response["Error"]["Code"]

            if error_code == "BucketAlreadyOwnedByYou":
                print(f"O bucket '{bucket_name}' já pertence à conta.")

            elif error_code == "BucketAlreadyExists":
                raise RuntimeError(
                    f"O nome '{bucket_name}' já pertence a outra conta. "
                    "Escolha outro BUCKET_NAME."
                ) from error

            elif error_code in {"AccessDenied", "AccessDeniedException"}:
                print("AccessDenied ao criar o bucket S3.")
                raise

            else:
                raise

    try:
        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )

        s3.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256"
                        }
                    }
                ]
            },
        )

        s3.put_bucket_versioning(
            Bucket=bucket_name,
            VersioningConfiguration={"Status": "Enabled"},
        )

        s3.put_bucket_tagging(
            Bucket=bucket_name,
            Tagging={
                "TagSet": [
                    {"Key": "Project", "Value": "financial-risk-platform"},
                    {"Key": "Environment", "Value": "dev"},
                    {"Key": "ManagedBy", "Value": "boto3"},
                ]
            },
        )
        print("Bloqueio público, criptografia (AES256), versionamento e tags configurados com sucesso.")

    except ClientError as error:
        error_code = error.response["Error"]["Code"]

        if error_code in {"AccessDenied", "AccessDeniedException"}:
            print("AccessDenied ao configurar o bucket.")

        raise

if __name__ == "__main__":
    main()