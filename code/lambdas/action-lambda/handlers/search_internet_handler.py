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
    Handle /searchinternet API - Perform enhanced internet search.
    
    支援的參數:
    - query (必需): 搜尋查詢
    - industries (可選): 產業列表，逗號分隔
    - categories (可選): 分類列表，逗號分隔  
    - extra_include (可選): 額外包含網站，逗號分隔
    - extra_exclude (可選): 額外排除網站，逗號分隔
    - smart_selection (可選): 是否啟用智能選擇，預設 true
    """
    global _web_search_service
    if _web_search_service is None:
        try:
            _web_search_service = WebSearchService()
            logger.info("WebSearchService 初始化成功")
        except Exception as e:
            logger.error("WebSearchService 初始化失敗: %s", e)
            raise ExternalAPIError("搜尋服務初始化失敗") from e
    
    try:
        logger.info("處理 /searchinternet 請求")
        
        parameters, session_attributes = parse_event(event)
        
        # 使用新的參數提取函數
        search_params = _extract_search_parameters(parameters)
        
        if not search_params['query']:
            logger.warning("缺少必需的 'query' 參數")
            raise ValidationError("缺少必需的 'query' 參數")
        
        logger.info("搜尋參數: query=%s, industries=%s, categories=%s, smart=%s", 
                   search_params['query'], search_params['industries'], 
                   search_params['categories'], search_params['smart_selection'])
        
        # 執行搜尋 - 使用解包語法
        search_result = _web_search_service.search_internet(**search_params)
        
        # 更新 session 屬性
        session_attributes[SessionAttributesKeys.LAST_SEARCH_QUERY] = search_params['query']
        if search_params['industries']:
            session_attributes["last_industries"] = search_params['industries']
        if search_params['categories']:
            session_attributes["last_categories"] = search_params['categories']
        
        # 處理回應格式
        if search_result.get("success", True):
            # 成功情況：重構回應格式以保持向後相容
            response_data = {
                "query": search_result["context"]["enhanced_query"],
                "original_query": search_result["context"]["original_query"],
                "response": {
                    "answer": search_result["result"]["answer"],
                    "sources": search_result["result"]["sources"],
                },
                "context": search_result["context"],
                "metadata": search_result["metadata"]
            }
            
            logger.info("搜尋成功: 使用了 %d 個網站，%d 個產業", 
                       search_result["context"]["sites_stats"]["included"],
                       len(search_result["context"]["industries_used"]))
        else:
            # 失敗情況
            error_msg = search_result.get("error", "搜尋失敗")
            logger.error("搜尋失敗: %s", error_msg)
            raise ExternalAPIError(f"搜尋執行失敗: {error_msg}")
        
        return HandlerResponse(response_data, session_attributes).to_tuple()
        
    except ValidationError as e:
        logger.warning("輸入驗證錯誤: %s", e)
        raise
    except ExternalAPIError as e:
        logger.error("外部 API 錯誤: %s", e)
        raise
    except Exception as e:
        logger.exception("search_internet_handler 中發生未預期錯誤")
        raise ExternalAPIError("搜尋服務內部錯誤") from e

def _extract_search_parameters(parameters):
    """提取並解析搜尋參數"""
    def parse_list_param(param_str):
        if not param_str:
            return None
        return [item.strip() for item in param_str.split(",") if item.strip()]
    
    return {
        'query': get_parameter_value(parameters, "query"),
        'industries': parse_list_param(get_parameter_value(parameters, "industries")),
        'categories': parse_list_param(get_parameter_value(parameters, "categories")),
        'extra_include': parse_list_param(get_parameter_value(parameters, "extra_include")),
        'extra_exclude': parse_list_param(get_parameter_value(parameters, "extra_exclude")),
        'smart_selection': (get_parameter_value(parameters, "smart_selection") or "true").lower() in ("true", "1", "yes", "on")
    }