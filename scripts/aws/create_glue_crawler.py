import os

import boto3
import dotenv
from botocore.exceptions import ClientError

dotenv.load_dotenv()

DATABASE_NAME = "financial_risk_raw"
CRAWLER_NAME = "financial-risk-paysim-raw-crawler"
ROLE_NAME = "AWSGlueServiceRole-FinancialRiskCrawler"


def main() -> None:
    bucket_name = os.environ["BUCKET_NAME"]
    region = os.environ["AWS_DEFAULT_REGION"]

    session = boto3.Session(region_name=region)
    glue = session.client("glue")
    iam = session.client("iam")

    role = iam.get_role(RoleName=ROLE_NAME)
    role_arn = role["Role"]["Arn"]

    raw_root = f"s3://{bucket_name}/financial-risk-platform/raw/"
    source_path = f"{raw_root}paysim/"

    database_input = {
        "Name": DATABASE_NAME,
        "Description": (
            "Camada raw da plataforma analítica de risco e fraude financeira"
        ),
        "LocationUri": raw_root,
        "Parameters": {
            "project": "financial-risk-platform",
            "layer": "raw",
        },
    }

    try:
        glue.get_database(Name=DATABASE_NAME)
    except glue.exceptions.EntityNotFoundException:
        glue.create_database(DatabaseInput=database_input)
        print(f"Glue Database '{DATABASE_NAME}' criado com sucesso.")
    else:
        glue.update_database(
            Name=DATABASE_NAME,
            DatabaseInput=database_input,
        )
        print(f"Glue Database '{DATABASE_NAME}' atualizado com sucesso.")

    crawler_parameters = {
        "Name": CRAWLER_NAME,
        "Role": role_arn,
        "DatabaseName": DATABASE_NAME,
        "Description": "Cataloga o CSV bruto do PaySim no S3",
        "Targets": {
            "S3Targets": [
                {
                    "Path": source_path,
                }
            ]
        },
        "TablePrefix": "raw_",
        "SchemaChangePolicy": {
            "UpdateBehavior": "UPDATE_IN_DATABASE",
            "DeleteBehavior": "LOG",
        },
        "RecrawlPolicy": {
            "RecrawlBehavior": "CRAWL_EVERYTHING",
        },
    }

    try:
        glue.get_crawler(Name=CRAWLER_NAME)
    except glue.exceptions.EntityNotFoundException:
        glue.create_crawler(
            **crawler_parameters,
            Tags={
                "Project": "financial-risk-platform",
                "Environment": "dev",
                "Layer": "raw",
            },
        )
        print(f"Glue Crawler '{CRAWLER_NAME}' criado com sucesso.")
    else:
        glue.update_crawler(**crawler_parameters)
        print(f"Glue Crawler '{CRAWLER_NAME}' atualizado com sucesso.")

    print("Crawler configurado, mas não iniciado.")


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        if error_code in {"AccessDenied", "AccessDeniedException"}:
            print(
                "AccessDenied ao configurar Glue/IAM. Verifique também a "
                "permissão iam:PassRole para a role do crawler."
            )
        raise
