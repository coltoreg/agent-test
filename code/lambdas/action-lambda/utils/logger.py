import logging
import sys

def setup_logger(name: str = "action_lambda", level=logging.INFO) -> logging.Logger:
    """
    Set up and return a standardized logger.
    Args:
        name (str): Logger name
        level (int): Log level (default to INFO)
    Returns:
        logging.Logger: Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 如果 logger 已經有 handler，避免重複加上去
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            "%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
