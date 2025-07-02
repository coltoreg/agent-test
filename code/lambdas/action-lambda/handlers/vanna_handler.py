"""
vanna_handler.py - 處理問題輸入，使用 Vanna 服務生成 SQL
"""
import time
from typing import Tuple, Dict, Any, List
from functools import wraps

from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError
from utils.handler_response import HandlerResponse
from utils.event_parser import parse_event
from utils.session_attributes import SessionAttributesKeys
from models.vanna import CompanyInfo
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

def _pick_from_dict(source: Dict[str, Any], key: str, current: str) -> str:
    """
    若 dict 中 key 或其去除 input_ 前綴版本存在，且值非空，則回傳該值；否則維持 current。
    """
    if not isinstance(source, dict):
        return current

    value = source.get(key) or source.get(key.replace("input_", ""))
    return value.strip() if _valid_str(value) else current


def _pick_from_props(props: List[Dict[str, Any]], key: str, current: str) -> str:
    """
    處理屬性陣列，如: {"name": "input_company", "value": "資生堂"}
    優先使用 key 或移除 input_ 前綴的 key 找到非空字串。
    """
    for item in props or []:
        name = item.get("name")
        value = item.get("value")

        if name in (key, key.replace("input_", "")) and _valid_str(value):
            return value.strip()

    return current

def _valid_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip()

def extract_parameters(event: Dict[str, Any]) -> CompanyInfo:
    """
    依序嘗試下列位置：
      #1  顶層 keys event["input_company"] …
      #2  parameters 陣列 event["parameters"][i].{name,value}
      #3  requestBody properties event["requestBody"]["content"]["application/json"]["properties"][i]
      #4  sessionAttributes event["sessionAttributes"][key]
    找不到就回空字串。
    """
    company = brand = product = product_category = target_title = ""

    # ---------- # 頂層 ----------
    company = _pick_from_dict(event, "input_company", company)
    brand = _pick_from_dict(event, "input_brand", brand)
    product = _pick_from_dict(event, "input_product", product)
    product_category = _pick_from_dict(event, "input_product_category", product_category)
    target_title = _pick_from_dict(event, "input_target_title", target_title)

    # ---------- # parameters 陣列 ----------
    for p in event.get("parameters", []):
        if not isinstance(p, dict):
            continue
        name = p.get("name", "")
        value = p.get("value", "")
        if not isinstance(value, str) or not value.strip():
            continue
        if name in ("input_company", "company"):
            company = value
        elif name in ("input_brand", "brand"):
            brand = value
        elif name in ("input_product", "product"):
            product = value
        elif name in ("input_product_category", "product_category"):
            product_category = value
        elif name in ("input_target_title", "target_title"):
            target_title = value

    # ---------- # requestBody → properties ----------
    props = (
        event.get("requestBody", {})
             .get("content", {})
             .get("application/json", {})
             .get("properties", [])
    )
    company = _pick_from_props(props, "input_company", company)
    brand = _pick_from_props(props, "input_brand", brand)
    product = _pick_from_props(props, "input_product", product)
    product_category = _pick_from_props(props, "input_product_category", product_category)
    target_title = _pick_from_props(props, "input_target_title", target_title)

    # ---------- #4 sessionAttributes ----------
    sess = event.get("sessionAttributes", {})
    company = _pick_from_dict(sess, "input_company", company)
    brand = _pick_from_dict(sess, "input_brand", brand)
    product = _pick_from_dict(sess, "input_product", product)
    product_category = _pick_from_dict(sess, "input_product_category", product_category)
    target_title = _pick_from_dict(sess, "input_target_title", target_title)

    return CompanyInfo(
        company=company,
        brand=brand,
        product=product,
        product_category=product_category,
        target_title=target_title
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
        
        # 驗證輸入
        input_text = validate_input(event)
        
        # 提取參數
        info = extract_parameters(event)

        # 初始化服務
        vanna_service = initialize_vanna_service()

        # 確認參數正確
        info = vanna_service.extract_company_info(input_text, info)

        # 設定訓練資料
        training_success = vanna_service.setup_training()

        if not training_success:
            logger.warning("Vanna 訓練設定失敗，但繼續執行")
        
        # 準備 SQL 查詢
        output_format = vanna_service.get_sql_input(info)
        
        sql_queries = vanna_service.collect_sql_queries(output_format)
        
        if not sql_queries:
            logger.warning("沒有找到有效的 SQL 查詢")
            return create_success_response({}, 0, 0, time.time() - start_time, input_text)
        
        # 生成唯一 ID
        uu_id_str = vanna_service.gen_ts_random_id()
        
        # 並行生成圖表
        results, successful_results = vanna_service.generate_charts_parallel(sql_queries, uu_id_str)
        
        # 記錄執行結果
        execution_time = time.time() - start_time
        logger.info(f"處理完成，成功 {successful_results}/{len(sql_queries)} 個查詢，耗時 {execution_time:.2f} 秒")
        
        # 返回成功回應
        return create_success_response(results, successful_results, len(sql_queries), execution_time, input_text)
    
    except (ValidationError, ExternalAPIError) as e:
        logger.error(f"已知錯誤: {str(e)}")
        return create_error_response(e, time.time() - start_time)
    
    except Exception as e:
        logger.exception(f"vanna_question_handler 發生未預期錯誤: {str(e)}")
        return create_error_response(e, time.time() - start_time)