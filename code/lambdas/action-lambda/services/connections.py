from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, Mapping, Any, Callable

import boto3
from botocore.exceptions import BotoCoreError, ClientError
import pyathena
from llama_index.llms.bedrock import Bedrock
from openai import OpenAI

from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

from utils.exceptions import ExternalAPIError

# --------------------------------------------------------------------------- #
# Environment‑variable helper
# --------------------------------------------------------------------------- #

def _env(name: str) -> str:
    """Return required environment variable or raise a friendly error."""
    try:
        return os.environ[name]
    except KeyError as exc:
        raise ExternalAPIError(f"Missing required env var '{name}'") from exc


@dataclass(frozen=True, slots=True)
class Env:
    """Centralised, immutable snapshot of **all** required ENV vars."""

    AWS_REGION: str = field(default_factory=lambda: _env("AWS_REGION"))
    AWS_FBMAPPING_REGION: str = field(default_factory=lambda: _env("AWS_FBMAPPING_REGION"))
    OUTPUT_S3_BUCKET: str = field(default_factory=lambda: _env("OUTPUT_S3_BUCKET"))
    ATHENA_TABLE_NAME: str = field(default_factory=lambda: _env("ATHENA_TABLE_NAME"))
    TEXT2SQL_DATABASE: str = field(default_factory=lambda: _env("TEXT2SQL_DATABASE"))
    LOG_LEVEL: str = field(default_factory=lambda: _env("LOG_LEVEL"))
    FEWSHOT_EXAMPLES_PATH: str = field(default_factory=lambda: _env("FEWSHOT_EXAMPLES_PATH"))
    SECRET_NAME: str = field(default_factory=lambda: _env("SECRET_NAME"))
    SECRET_NAME_PPLX: str = field(default_factory=lambda: _env("SECRET_NAME_PPLX"))
    PREPLEXITY_URL: str = field(default_factory=lambda: _env("PREPLEXITY_URL"))
    OPENSEARCH_HOST: str = field(default_factory=lambda: _env("OPENSEARCH_HOST"))
    OS_DOC_INDEX: str = field(default_factory=lambda: _env("OS_DOC_INDEX"))
    OS_DDL_INDEX: str = field(default_factory=lambda: _env("OS_DDL_INDEX"))
    OS_QSQL_INDEX: str = field(default_factory=lambda: _env("OS_QSQL_INDEX"))


# --------------------------------------------------------------------------- #
# Secret‑manager cache helper
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=None)
def _fetch_secret(secret_id: str, *, region: str) -> Mapping[str, str]:
    """Retrieve and cache a JSON secret by ID for the given region."""
    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_id)
        return json.loads(response["SecretString"])
    except (ClientError, BotoCoreError) as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
        raise ExternalAPIError(f"Failed fetching secret '{secret_id}': {code}") from exc


# --------------------------------------------------------------------------- #
# Bedrock model metadata
# --------------------------------------------------------------------------- #

MODELID_MAPPING: Final[Mapping[str, str]] = {
    "Titan": "amazon.titan-tg1-large",
    "Jurassic": "ai21.j2-ultra-v1",
    "Claude2": "anthropic.claude-v2",
    "ClaudeInstant": "anthropic.claude-instant-v1",
}

DEFAULT_MODEL_KWARGS: Final[Mapping[str, dict]] = {
    name: {"max_tokens": 256, "temperature": 0.0} for name in MODELID_MAPPING
}

# --------------------------------------------------------------------------- #
# Main public factory
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class Connections:
    """Factory for AWS + LLM clients using consolidated environment config."""

    env: Env = field(default_factory=Env)

    # ---------- AWS low‑level resources ----------------------------------- #
    def bedrock_client(self):
        """Return Bedrock runtime *client* for direct invocations."""
        return boto3.client("bedrock-runtime", region_name=self.env.AWS_REGION)

    # ---------- Secrets ---------------------------------------------------- #

    def _secret(self, *, which: str | None = None) -> Mapping[str, str]:
        """Return secret payload for the requested secret (primary by default)."""
        secret_id = which or self.env.SECRET_NAME
        return _fetch_secret(secret_id, region=self.env.AWS_REGION)

    # ---------- Credentials ---------------------------------------------- #

    def athena_credentials(self) -> Mapping[str, str]:
        """Temporary AWS credentials for Athena, taken from primary secret."""
        s = self._secret()
        return {
            "access_key": s["AWS_ACCESS_KEY_ID"],
            "secret_key": s["AWS_SECRET_ACCESS_KEY"],
            "session_token": s.get("AWS_SESSION_TOKEN", ""),
        }
    
    def boto3_session(self) -> boto3.Session:
        """Return a boto3 Session scoped to the configured region."""
        return boto3.Session(region_name=self.env.AWS_REGION)

    # ---------- 新增 OpenSearch 客戶端 ------------------------------------ #
    
    def opensearch_client(self, host: str) -> OpenSearch:
        """
        建立並返回 OpenSearch 客戶端。
        
        Args:
            host: OpenSearch 主機名（不含https://前綴）
            
        Returns:
            已配置的 OpenSearch 客戶端
        """

        host = host or self.env.OPENSEARCH_HOST
        host = host.replace("https://", "").replace("http://", "").rstrip("/")
        
        session = self.boto3_session()
        credentials = session.get_credentials()
        
        auth = AWSV4SignerAuth(credentials, self.env.AWS_REGION, "aoss")
        return OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=60,
            max_retries=10,
            retry_on_timeout=True,
        )
    
    # ---------- 新增 Athena 連接方法 ------------------------------------- #
    
    def athena_connection(self, database: str = None, s3_staging_dir: str = None):
        """
        建立並返回 Athena 連接。
        
        Args:
            database: Athena 數據庫名稱，默認使用環境變數配置
            s3_staging_dir: S3 暫存目錄，默認基於 OUTPUT_S3_BUCKET 環境變數
            
        Returns:
            已配置的 pyathena 連接物件
        """
        try:
            # 使用默認值或參數提供的值
            db = database or self.env.TEXT2SQL_DATABASE
            staging_dir = s3_staging_dir or f"s3://{self.env.OUTPUT_S3_BUCKET}/athena-results/"

            print(f"athena s3 temp location: {staging_dir}")
            
            # 獲取認證
            credentials = self.athena_credentials()
            
            # 建立連接
            return pyathena.connect(
                region_name=self.env.AWS_FBMAPPING_REGION,
                s3_staging_dir=staging_dir,
                catalog_name="",
                schema_name=db,
                work_group="primary",
                aws_access_key_id=credentials["access_key"],
                aws_secret_access_key=credentials["secret_key"],
                aws_session_token=credentials["session_token"]
            )
        except ImportError as e:
            raise ExternalAPIError(f"缺少 pyathena 套件: {e}")
        except Exception as e:
            raise ExternalAPIError(f"建立 Athena 連接失敗: {e}")

    # ---------- 新增 Athena 查詢方法 ------------------------------------- #
    
    def athena_query_runner(self) -> Callable[[str], Any]:
        """
        返回一個可執行 Athena 查詢的函數。
        
        Returns:
            一個接受 SQL 字符串並返回 pandas DataFrame 的函數
        """
        try:
            import pandas as pd
            
            # 建立連接
            conn = self.athena_connection()
            
            # 返回可執行查詢的函數
            def run_sql(sql: str):
                try:
                    return pd.read_sql_query(sql, conn)
                except Exception as e:
                    raise ExternalAPIError(f"SQL 執行失敗: {e}")
            
            return run_sql
        except ImportError as e:
            raise ExternalAPIError(f"缺少必要套件: {e}")

    # ---------- LLM wrappers --------------------------------------------- #

    def bedrock_llm(self, *, model_name: str = "ClaudeInstant", **overrides) -> Bedrock:
        """High‑level Bedrock LLM wrapper with sensible defaults."""
        if model_name not in MODELID_MAPPING:
            raise ValueError(f"Unsupported model_name '{model_name}'")

        kwargs = {**DEFAULT_MODEL_KWARGS[model_name], **overrides}
        kwargs.update(model=MODELID_MAPPING[model_name], aws_region_name=self.env.AWS_REGION)
        return Bedrock(**kwargs)

    def openai_client(self) -> OpenAI:
        """Return Perplexity‑flavoured OpenAI client (uses secondary secret)."""
        pplx_secret = self._secret(which=self.env.SECRET_NAME_PPLX)
        return OpenAI(api_key=pplx_secret["PPLX_KEY"], base_url=self.env.PREPLEXITY_URL)
    

    # ---------- S3 client - FBMAPPING --------------------------------------------- #
    def s3_client_fbmapping(self) -> boto3.Session:
        """Return a boto3 Session scoped to the configured region."""
        s = self._secret()
        session = boto3.Session(
            aws_access_key_id=s["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=s["AWS_SECRET_ACCESS_KEY"],
            region_name=self.env.AWS_FBMAPPING_REGION
        )
        return session.client('s3')