from services.athena_service import AthenaService
from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError
from utils.handler_response import HandlerResponse
from utils.event_parser import parse_event
from utils.session_attributes import SessionAttributesKeys

logger = setup_logger(__name__)
_athena_service = None

def query_glue_table_handler(event, context):
    """
    Handle /querygluetable API - Query company market share or other data from Athena.
    """
    global _athena_service
    if _athena_service is None:
        _athena_service = AthenaService()
    try:
        logger.info("Handling /querygluetable request.")

        input_text = event.get("inputText", "")
        _, session_attributes = parse_event(event)

        if not input_text:
            logger.warning("Missing 'inputText'.")
            raise ValidationError("Missing input text for query.")

        query_result = _athena_service.execute_query(input_text)

        session_attributes[SessionAttributesKeys.LAST_QUERY_TEXT] = input_text

        return HandlerResponse(query_result, session_attributes).to_tuple()

    except (ValidationError, ExternalAPIError):
        raise
    except Exception as e:
        logger.exception("Unexpected error in query_glue_table_handler.")
        raise