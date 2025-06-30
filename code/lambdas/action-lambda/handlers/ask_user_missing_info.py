from utils.logger import setup_logger
from utils.exceptions import ValidationError
from utils.validation import get_parameter_value
from utils.handler_response import HandlerResponse
from utils.event_parser import parse_event
from utils.session_attributes import SessionAttributesKeys

logger = setup_logger(__name__)

def ask_user_missing_info_handler(event, context):
    """
    Handle /askusermissinginfo API - Ask user to provide missing information.
    """
    try:
        logger.info("Handling /askusermissinginfo request.")

        parameters, session_attributes = parse_event(event)

        missing_param = get_parameter_value(parameters, "missingParameter")
        instruction = get_parameter_value(parameters, "instruction")

        if not missing_param or not instruction:
            logger.warning("Missing required parameters.")
            raise ValidationError("Missing 'missingParameter' or 'instruction'.")

        result = {
            "status": f"Prompt sent successfully for missing parameter: {missing_param}"
        }

        session_attributes[SessionAttributesKeys.MISSING_PARAM] = missing_param
        session_attributes[SessionAttributesKeys.INSTRUCTION] = instruction

        return HandlerResponse(result, session_attributes).to_tuple()

    except ValidationError:
        raise
    except Exception as e:
        logger.exception("Unexpected error in ask_user_missing_info_handler.")
        raise