import os
import boto3
from botocore.config import Config
import json
from botocore.exceptions import BotoCoreError, ClientError
# Bedrock Runtime 配置 - 處理格式化任務
runtime_config = Config(
    connect_timeout=20,     # 增加連接超時
    read_timeout=400,       # 增加讀取超時到10分鐘
    retries={
        "max_attempts": 2,  # 增加重試次數
        "mode": "adaptive"  # 使用自適應重試模式
    }
)

# Agent 配置 (處理 internalServerException 問題)
agent_config = Config(
    connect_timeout=30,     # 增加 Agent 連接超時
    read_timeout=220,       # 增加 Agent 讀取超時到5分鐘
    retries={
        "max_attempts": 2, # 大幅增加 Agent 重試次數
        "mode": "adaptive", # 自適應重試模式
        "total_max_attempts": 2
    },
    max_pool_connections=8  # 降低連接池大小，減少資源競爭
)

class Connections:
    REGION_NAME = os.environ["AWS_REGION"]
    
    bedrock_client = boto3.client("bedrock-runtime", region_name=REGION_NAME, config=runtime_config)
    output_format_fm = "us.anthropic.claude-sonnet-4-20250514-v1:0"  # "us.anthropic.claude-sonnet-4-20250514-v1:0"

    agent_client = boto3.client("bedrock-agent", region_name=REGION_NAME, config=agent_config)
    agent_runtime_client = boto3.client("bedrock-agent-runtime", region_name=REGION_NAME, config=agent_config)
    s3_resource = boto3.resource("s3", region_name=REGION_NAME)

    # ------ S3 Client ----------------------------------------
    REGION_NAME_FBMAPPING = os.environ["AWS_FBMAPPING_REGION"]
    SECRET_NAME = os.getenv("SECRET_NAME", "AdPilot-Demo")
    if not SECRET_NAME:
        raise RuntimeError("環境變數 SECRET_NAME 未設定，無法讀取憑證")

    try:
        sm_client = boto3.client(
            "secretsmanager",
            region_name=REGION_NAME
        )
        secret_resp = sm_client.get_secret_value(SecretId=SECRET_NAME)
        secret_dict = json.loads(secret_resp["SecretString"])
    except ClientError as e:
        raise RuntimeError(f"讀取 Secret【{SECRET_NAME}】失敗: {e}")

    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if k not in secret_dict:
            raise RuntimeError(f"Secret 缺少 {k}")

    session = boto3.Session(
        aws_access_key_id = secret_dict["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key = secret_dict["AWS_SECRET_ACCESS_KEY"],
        region_name = REGION_NAME_FBMAPPING
    )
    s3_client_fbmapping = session.client("s3")