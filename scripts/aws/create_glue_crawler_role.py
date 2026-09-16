import json
import os
import sys

import boto3
import dotenv
from botocore.exceptions import ClientError

dotenv.load_dotenv()

def main() -> None:
    bucket_name = os.environ["BUCKET_NAME"]
    if not bucket_name:
        print("Erro: A variável BUCKET_NAME não foi definida no ambiente.")
        sys.exit(1)

    role_name = "AWSGlueServiceRole-FinancialRiskCrawler"
    policy_name = "FinancialRiskCrawlerS3ReadOnly"
    managed_policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"

    iam = boto3.client("iam")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "glue.amazonaws.com",
                },
                "Action": "sts:AssumeRole",
            }
        ],
    }

    role_exists = False
    try:
        iam.get_role(RoleName=role_name)
        role_exists = True
        print(f"Role '{role_name}' já existe. Atualizando políticas...")
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        if error_code == "NoSuchEntity":
            role_exists = False
        elif error_code in ["AccessDenied", "AccessDeniedException"]:
            print(f"AccessDenied ao consultar a role IAM '{role_name}'.")
            sys.exit(1)
        else:
            raise

    if not role_exists:
        try:
            iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Role usada pelo Glue Crawler do Financial Risk Platform",
                Tags=[
                    {"Key": "Project", "Value": "financial-risk-platform"},
                    {"Key": "Environment", "Value": "dev"},
                ],
            )
            print(f"Role '{role_name}' criada com sucesso.")
        except ClientError as error:
            error_code = error.response["Error"]["Code"]
            if error_code in ["AccessDenied", "AccessDeniedException"]:
                print("AccessDenied ao criar a role IAM.")
                sys.exit(1)
            raise

    try:
        iam.update_assume_role_policy(
            RoleName=role_name,
            PolicyDocument=json.dumps(trust_policy),
        )
        print(f"Trust policy da role '{role_name}' atualizada com sucesso.")
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        if error_code in ["AccessDenied", "AccessDeniedException"]:
            print("AccessDenied ao atualizar a trust policy da role IAM.")
            sys.exit(1)
        raise

    try:
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn=managed_policy_arn,
        )
        print(f"Política gerenciada '{managed_policy_arn}' anexada com sucesso.")
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        if error_code in ["AccessDenied", "AccessDeniedException"]:
            print("AccessDenied ao anexar a política gerenciada à role.")
            sys.exit(1)
        raise

    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "GetRawBucketLocation",
                "Effect": "Allow",
                "Action": "s3:GetBucketLocation",
                "Resource": f"arn:aws:s3:::{bucket_name}",
            },
            {
                "Sid": "ListProjectRawPrefix",
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": f"arn:aws:s3:::{bucket_name}",
                "Condition": {
                    "StringLike": {
                        "s3:prefix": [
                            "financial-risk-platform/raw",
                            "financial-risk-platform/raw/*",
                        ]
                    }
                },
            },
            {
                "Sid": "ReadProjectRawObjects",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": (
                    f"arn:aws:s3:::{bucket_name}/"
                    "financial-risk-platform/raw/*"
                ),
            },
        ],
    }

    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(s3_policy),
        )
        print(f"Política inline '{policy_name}' configurada com sucesso.")
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        if error_code in ["AccessDenied", "AccessDeniedException"]:
            print("AccessDenied ao aplicar a política inline do S3.")
            sys.exit(1)
        raise

    print(f"\nRole IAM '{role_name}' pronta para ser utilizada pelo Glue Crawler.")


if __name__ == "__main__":
    main()
