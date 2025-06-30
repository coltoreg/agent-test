from services.web_search_service import WebSearchService
from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError
from utils.validation import get_parameter_value
from utils.handler_response import HandlerResponse
from utils.event_parser import parse_event
from utils.session_attributes import SessionAttributesKeys

logger = setup_logger(__name__)
_web_search_service = None

def search_internet_handler(event, context):
    """
    Handle /searchinternet API - Perform internet search.
    """
    global _web_search_service
    if _web_search_service is None:
        _web_search_service = WebSearchService()
    try:
        logger.info("Handling /searchinternet request.")

        parameters, session_attributes = parse_event(event)

        query = get_parameter_value(parameters, "query")

        if not query:
            logger.warning("Missing 'query' parameter.")
            raise ValidationError("Missing 'query' parameter.")

        search_result = _web_search_service.search_internet(query)

        session_attributes[SessionAttributesKeys.LAST_SEARCH_QUERY] = query

        return HandlerResponse(search_result, session_attributes).to_tuple()

    except (ValidationError, ExternalAPIError):
        raise
    except Exception as e:
        logger.exception("Unexpected error in search_internet_handler.")
        raise