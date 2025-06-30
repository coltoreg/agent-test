"""
vanna_handler.py - 處理問題輸入，使用 Vanna 服務生成 SQL
"""
import time
from typing import Tuple, Dict, Any
from functools import wraps

from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError
from utils.handler_response import HandlerResponse
from utils.event_parser import parse_event
from utils.session_attributes import SessionAttributesKeys
from services.vanna_service import VannaService

logger = setup_logger(__name__)

# 全域變數，避免每次請求都重新初始化 VannaService
_vanna_service = None

# 設定總體超時時間 (秒) (測試用，TODO:所有tools的超時時間管理器具)
OVERALL_TIMEOUT = 300

def timeout_handler(timeout_seconds: int):
    """超時處理裝飾器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except TimeoutError:
                logger.error(f"函數 {func.__name__} 執行超時 ({timeout_seconds}秒)")
                raise ExternalAPIError(f"操作超時，請稍後再試")
            except Exception as e:
                logger.error(f"函數 {func.__name__} 執行失敗: {str(e)}")
                raise
        return wrapper
    return decorator

def initialize_vanna_service() -> VannaService:
    """初始化 Vanna 服務"""
    global _vanna_service
    
    if _vanna_service is not None:
        return _vanna_service
    
    try:
        logger.info("正在初始化 Vanna 服務")
        _vanna_service = VannaService()
        logger.info("Vanna 服務初始化成功")
        return _vanna_service
    except Exception as e:
        logger.error(f"Vanna 服務初始化失敗: {str(e)}")
        raise ExternalAPIError(f"服務初始化失敗: {str(e)}")

def validate_input(event: Dict[str, Any]) -> str:
    """驗證輸入參數"""
    input_text = event.get("inputText", "").strip()
    if not input_text:
        raise ValidationError("請提供具體的問題內容")
    
    logger.info(f"使用者輸入: {input_text}")
    return input_text

def extract_parameters(event: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """提取參數"""
    return (
        event.get("input_company", ""),
        event.get("input_brand", ""),
        event.get("input_product", ""),
        event.get("input_product_category", "")
    )

def create_error_response(error: Exception, execution_time: float) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """創建錯誤回應"""
    error_type = "validation" if isinstance(error, ValidationError) else \
                 "external_api" if isinstance(error, ExternalAPIError) else "system"
    
    error_response = {
        "vanna_result_by_title": {},
        "summary": {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "execution_time": execution_time
        },
        "error": str(error),
        "error_type": error_type
    }
    return HandlerResponse(error_response, {}).to_tuple()

def create_success_response(results: Dict[str, Any], successful_results: int, 
                          total_queries: int, execution_time: float, 
                          input_text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """創建成功回應"""
    # 更新會話屬性
    session_attributes = {
        SessionAttributesKeys.LAST_QUERY_TEXT: input_text,
        "query_count": total_queries,
        "successful_results": successful_results,
        "execution_timestamp": int(time.time()),
        "execution_duration": round(execution_time, 2)
    }
    
    # 準備回應
    response = {
        "vanna_result_by_title": results,
        "summary": {
            "total_queries": total_queries,
            "successful_queries": successful_results,
            "failed_queries": total_queries - successful_results,
            "execution_time": round(execution_time, 2)
        }
    }
    
    return HandlerResponse(response, session_attributes).to_tuple()

@timeout_handler(OVERALL_TIMEOUT)
def vanna_question_handler(event: Dict[str, Any], context: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    處理使用者問題輸入，產生 SQL 輸出
    
    參數:
        event: Lambda 事件物件
        context: Lambda 執行上下文
        
    回傳:
        元組 (回應內容, 會話屬性)
    """
    start_time = time.time()
    
    try:
        logger.info(f"開始處理 Vanna 問題: {event}")
        
        # 1. 驗證輸入
        input_text = validate_input(event)
        
        # 2. 提取參數
        input_company, input_brand, input_product, input_product_category = extract_parameters(event)
        
        # 3. 解析會話屬性
        _, session_attributes = parse_event(event)
        
        # 4. 初始化服務
        vanna_service = initialize_vanna_service()
        
        # 5. 提取公司資訊（使用 AI）
        input_company, input_brand, input_product, input_product_category = vanna_service.extract_company_info(
            input_text, input_company, input_brand, input_product, input_product_category
        )
        
        logger.info(f"公司資訊: 公司: {input_company}, 品牌: {input_brand}, 產品: {input_product}, 產品類型: {input_product_category}")
        
        # 6. 設定訓練資料
        training_success = vanna_service.setup_training()
        if not training_success:
            logger.warning("Vanna 訓練設定失敗，但繼續執行")
        
        # 7. 準備 SQL 查詢
        output_format = vanna_service.get_sql_input(input_company, input_brand, input_product)
        sql_queries = vanna_service.collect_sql_queries(output_format)
        
        if not sql_queries:
            logger.warning("沒有找到有效的 SQL 查詢")
            return create_success_response({}, 0, 0, time.time() - start_time, input_text)
        
        # 8. 生成唯一 ID
        uu_id_str = vanna_service.gen_ts_random_id()
        
        # 9. 並行生成圖表
        results, successful_results = vanna_service.generate_charts_parallel(sql_queries, uu_id_str)
        
        # 10. 記錄執行結果
        execution_time = time.time() - start_time
        logger.info(f"處理完成，成功 {successful_results}/{len(sql_queries)} 個查詢，耗時 {execution_time:.2f} 秒")
        
        # 11. 返回成功回應
        return create_success_response(results, successful_results, len(sql_queries), execution_time, input_text)
    
    except (ValidationError, ExternalAPIError) as e:
        logger.error(f"已知錯誤: {str(e)}")
        return create_error_response(e, time.time() - start_time)
    
    except Exception as e:
        logger.exception(f"vanna_question_handler 發生未預期錯誤: {str(e)}")
        return create_error_response(e, time.time() - start_time)