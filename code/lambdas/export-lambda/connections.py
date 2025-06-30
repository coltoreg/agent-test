import os
import json
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from utils.logger import get_logger
from utils.exceptions import exception_handler, ExportLambdaError

logger = get_logger("connections")

class Connections:
    """AWS connection helper"""

    region_name = os.getenv("AWS_REGION", "ap-southeast-1")
    secret_name = os.getenv("SECRET_NAME")
    s3_bucket_name = os.getenv("OUTPUT_S3_BUCKET")

    _secret_cache = None
    _creds_cache = None
    _s3_client = None

    @classmethod
    @exception_handler
    def get_secret(cls) -> dict:
        if cls._secret_cache is not None:
            return cls._secret_cache

        if not cls.secret_name:
            logger.error("SECRET_NAME environment variable not set")
            raise ValueError("Environment variable SECRET_NAME is not set")

        try:
            sm = boto3.client("secretsmanager", region_name=cls.region_name)
            resp = sm.get_secret_value(SecretId=cls.secret_name)
            cls._secret_cache = json.loads(resp["SecretString"])
            logger.info(f"Successfully retrieved secret {cls.secret_name}")
            return cls._secret_cache

        except (ClientError, BotoCoreError) as err:
            logger.exception("Failed to retrieve AWS secret")
            raise ExportLambdaError(f"Failed to retrieve secret '{cls.secret_name}'") from err

    @classmethod
    @exception_handler
    def get_credentials(cls) -> dict:
        if cls._creds_cache is not None:
            return cls._creds_cache

        secret = cls.get_secret()
        cls._creds_cache = {
            "access_key": secret.get("AWS_ACCESS_KEY_ID"),
            "secret_key": secret.get("AWS_SECRET_ACCESS_KEY"),
            "session_token": secret.get("AWS_SESSION_TOKEN"),
        }
        logger.info("AWS credentials extracted successfully")
        return cls._creds_cache

    @classmethod
    @exception_handler
    def s3_client(cls):
        if cls._s3_client is not None:
            return cls._s3_client

        creds = cls.get_credentials()
        cls._s3_client = boto3.client(
            "s3",
            region_name=cls.region_name,
            aws_access_key_id=creds["access_key"],
            aws_secret_access_key=creds["secret_key"],
            aws_session_token=creds["session_token"],
        )
        logger.info("S3 client initialized successfully")
        return cls._s3_client