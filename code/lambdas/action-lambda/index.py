import os
import tempfile

os.environ["NLTK_DATA"] = tempfile.gettempdir()

import json
# from handlers.ask_user_missing_info import ask_user_missing_info_handler
# from handlers.query_glue_table import query_glue_table_handler
from handlers.search_internet_handler import search_internet_handler
from handlers.vanna_handler import vanna_question_handler
from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError

logger = setup_logger(__name__)

# API 路由映射表
ROUTE_TABLE = {
    # "/askusermissinginfo": ask_user_missing_info_handler,
    # "/querygluetable": query_glue_table_handler,
    "/searchinternet": search_internet_handler,
    "/querygluetable": vanna_question_handler
}

def get_response(event, context):
    """
    Main Lambda entry point for routing API requests to the correct handler.
    """
    try:
        logger.info("Received event: %s", json.dumps(event))

        api_path = event.get("apiPath", "")
        handler = ROUTE_TABLE.get(api_path)

        if handler is None:
            logger.warning(f"No handler found for apiPath: {api_path}")
            return build_error_response(event, 404, "API path not found.")

        logger.info(f"Routing to handler for API Path: {api_path}")

        # 這裡 handler 要回傳 (result, session_attributes)
        result, session_attributes = handler(event, context)

        logger.info("action group result: %s", json.dumps(result, ensure_ascii=False))

        return build_success_response(event, result, session_attributes)

    except ValidationError as ve:
        logger.warning("Validation error: %s", str(ve))
        return build_error_response(event, 400, str(ve))

    except ExternalAPIError as ee:
        logger.error("External API error: %s", str(ee))
        return build_error_response(event, 502, "External service error.")

    except Exception as e:
        logger.exception("Unexpected error: %s", str(e))
        return build_error_response(event, 500, "Internal server error.")

# AWS 定義格式: https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html
# --- 成功 Response ---
def build_success_response(event, result: dict, session_attributes: dict):
    """
    Build a success response in standard Bedrock action group format.
    """
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", "Unknown"),
            "apiPath": event.get("apiPath", "Unknown"),
            "httpMethod": event.get("httpMethod", "Unknown"),
            "httpStatusCode": 200,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(result)
                }
            },
        },
        "sessionAttributes": session_attributes or {},
        "promptSessionAttributes": event.get("promptSessionAttributes", {}),
    }

# --- 錯誤 Response ---
def build_error_response(event, status_code: int, message: str):
    """
    Build an error response in standard Bedrock action group format.
    """
    error_body = {
        "errorMessage": message
    }
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", "Unknown"),
            "apiPath": event.get("apiPath", "Unknown"),
            "httpMethod": event.get("httpMethod", "Unknown"),
            "httpStatusCode": status_code,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(error_body)
                }
            },
        },
        "sessionAttributes": event.get("sessionAttributes", {}),
        "promptSessionAttributes": event.get("promptSessionAttributes", {}),
    }