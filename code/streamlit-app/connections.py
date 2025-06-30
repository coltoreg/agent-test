import os
import boto3
import json
from botocore.config import Config

session = boto3.Session()

if os.environ.get("ACCOUNT_ID") is None:
    ACCOUNT_ID = session.client("sts").get_caller_identity().get("Account")
    AWS_REGION = session.region_name
else:
    ACCOUNT_ID = os.environ["ACCOUNT_ID"]
    AWS_REGION = os.environ["AWS_REGION"]

if os.environ.get("LAMBDA_FUNCTION_NAME") is None:
    try:
        # read in json file cdk.json
        with open("../../cdk.json", encoding="utf-8") as f:
            data = json.load(f)
        config = data["context"]["config"]
        STACK_NAME = config["names"]["stack_name"]
        STREAMLIT_INVOKE_LAMBDA_FUNCTION_NAME = config["names"][
            "streamlit_lambda_function_name"
        ]
        lambda_function_name = f"{STACK_NAME}-{STREAMLIT_INVOKE_LAMBDA_FUNCTION_NAME}-{ACCOUNT_ID}-{AWS_REGION}"
    except Exception:
        raise ValueError(
            "LAMBDA_FUNCTION_NAME not found in environment or cdk.json.")
else:
    lambda_function_name = os.environ["LAMBDA_FUNCTION_NAME"]


if os.environ.get("EXPORT_LAMBDA_FUNCTION_NAME") is None:
    try:
        # read in json file cdk.json
        with open("../../cdk.json", encoding="utf-8") as f:
            data = json.load(f)
        config = data["context"]["config"]
        STACK_NAME = config["names"]["stack_name"]
        STREAMLIT_INVOKE_EXPORT_LAMBDA_FUNCTION_NAME = config["names"][
            "streamlit_export_lambda_function_name"
        ]
        export_lambda_function_name = f"{STACK_NAME}-{STREAMLIT_INVOKE_EXPORT_LAMBDA_FUNCTION_NAME}-{ACCOUNT_ID}-{AWS_REGION}"
    except Exception:
        raise ValueError(
            "EXPORT_LAMBDA_FUNCTION_NAME not found in environment or cdk.json.")
else:
    export_lambda_function_name = os.environ["EXPORT_LAMBDA_FUNCTION_NAME"]


class Connections:
    lambda_function_name = lambda_function_name
    export_lambda_function_name = export_lambda_function_name
    lambda_client = boto3.client(
        "lambda",
        region_name=AWS_REGION,
        config=Config(
            read_timeout=600,  # 10分鐘讀取超時 (原本300秒不夠)
            connect_timeout=20,
            retries={
                'max_attempts': 2,  # 最大重試3次
                'mode': 'adaptive'  # 自適應重試模式
            },
            max_pool_connections=50  # 增加連接池大小
        )
    )