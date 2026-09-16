import os

import dotenv
import boto3
from botocore.exceptions import ClientError

dotenv.load_dotenv()

def main() -> None:
    budget_email = os.environ["BUDGET_EMAIL"]
    monthly_budget_usd = os.environ["MONTHLY_BUDGET_USD"]
    session = boto3.Session()

    if session.region_name is None:
            raise RuntimeError("Região AWS não configurada.")

    account_id = session.client("sts").get_caller_identity()["Account"]
    budgets = session.client("budgets", region_name="us-east-1")

    budget_config = {
        "BudgetName": "financial-risk-platform-monthly",
        "BudgetLimit": {
            "Amount": str(monthly_budget_usd),
            "Unit": "USD",
        },
        "TimeUnit": "MONTHLY",
        "BudgetType": "COST",
        "CostTypes": {
            "IncludeCredit": False,
            "IncludeRefund": False,
        },
    }

    notifications_with_subscribers = [
        {
            "Notification": {
                "NotificationType": "ACTUAL",
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": 50.0,
                "ThresholdType": "PERCENTAGE",
            },
            "Subscribers": [
                {
                    "SubscriptionType": "EMAIL",
                    "Address": budget_email,
                }
            ],
        },
        {
            "Notification": {
                "NotificationType": "FORECASTED",
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": 80.0,
                "ThresholdType": "PERCENTAGE",
            },
            "Subscribers": [
                {
                    "SubscriptionType": "EMAIL",
                    "Address": budget_email,
                }
            ],
        },
    ]

    try:
        budgets.create_budget(
        AccountId=account_id,
        Budget=budget_config,
        NotificationsWithSubscribers=notifications_with_subscribers,
        )
        print("Orçamento criado com sucesso.")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "AccessDeniedException":
            print("AccessDeniedException")
        elif error_code == "DuplicateRecordException":
            print("Orçamento já existente na conta.")
        else:
            raise 

if __name__ == "__main__":
     main()