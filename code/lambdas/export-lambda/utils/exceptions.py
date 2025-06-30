import functools
from utils.logger import get_logger

logger = get_logger("exception")

class ExportLambdaError(Exception):
    """自訂基礎錯誤類型，所有自定義錯誤繼承自這個"""
    pass

class S3UploadError(ExportLambdaError):
    """S3 上傳錯誤"""
    pass

class ExportFormatError(ExportLambdaError):
    """不支援的匯出格式錯誤"""
    pass

def exception_handler(func):
    """用 decorator 包住 method，統一處理與 log 未捕捉例外"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ExportLambdaError as e:
            logger.error(f"[KnownError] {str(e)}")
            raise
        except Exception as e:
            logger.exception(f"[UnexpectedError] {str(e)}")
            raise ExportLambdaError("An unexpected error occurred.") from e
    return wrapper