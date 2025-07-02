from pathlib import Path
import yaml
from functools import lru_cache
from typing import Dict, Any, Union
import os

from utils.logger import setup_logger
from utils.exceptions import ValidationError

logger = setup_logger(__name__)


@lru_cache
def load_industry_sites(cfg_path: Union[str, Path, None] = None) -> Dict[str, Any]:
    """
    讀取並快取產業/網站 YAML 配置
    
    Args:
        cfg_path: 配置文件路徑，None 時使用默認路徑
        
    Returns:
        Dict: 產業網站配置字典
        
    Raises:
        ValidationError: 當配置文件不存在或格式錯誤時
    """
    # 處理 None 的情況，使用默認路徑
    if cfg_path is None:
        cfg_path = "config/industry_sites.yaml"
    
    # 轉換為 Path 對象以便處理
    config_path = Path(cfg_path)
    
    # 檢查文件是否存在
    if not config_path.exists():
        # 嘗試相對於當前工作目錄的路徑
        alt_path = Path.cwd() / config_path
        if alt_path.exists():
            config_path = alt_path
        else:
            # 如果是 Lambda 環境，嘗試相對於 /var/task
            lambda_path = Path("/var/task") / config_path
            if lambda_path.exists():
                config_path = lambda_path
            else:
                logger.error("配置文件不存在: %s", config_path)
                logger.info("嘗試的路徑: %s, %s, %s", config_path, alt_path, lambda_path)
                logger.info("當前工作目錄: %s", Path.cwd())
                logger.info("目錄內容: %s", list(Path.cwd().iterdir()) if Path.cwd().exists() else "N/A")
                
                # 返回空配置而不是拋出異常，讓服務可以繼續運行
                logger.warning("使用空配置繼續運行")
                return {}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
            
        # 驗證配置格式
        if not isinstance(config_data, dict):
            raise ValidationError("配置文件格式錯誤：根元素必須是字典")
        
        logger.info("成功加載配置文件: %s", config_path)
        logger.debug("配置包含 %d 個產業", len(config_data))
        
        return config_data
        
    except yaml.YAMLError as e:
        logger.error("YAML 解析錯誤: %s", e)
        raise ValidationError(f"配置文件 YAML 格式錯誤: {e}") from e
    except Exception as e:
        logger.error("讀取配置文件失敗: %s", e)
        raise ValidationError(f"無法讀取配置文件 {config_path}: {e}") from e


def get_config_path() -> Path:
    """
    直接使用默認路徑，讓 load_industry_sites 處理查找邏輯
    """
    return Path("config/industry_sites.yaml")


def validate_config_structure(config: Dict[str, Any]) -> bool:
    """
    驗證配置文件結構是否正確
    
    Args:
        config: 配置字典
        
    Returns:
        bool: 結構是否正確
    """
    if not isinstance(config, dict):
        return False
    
    for industry, categories in config.items():
        if not isinstance(industry, str):
            logger.error("產業名稱必須是字符串: %s", industry)
            return False
            
        if not isinstance(categories, dict):
            logger.error("產業 %s 的分類必須是字典", industry)
            return False
            
        for category, sites in categories.items():
            if not isinstance(category, str):
                logger.error("分類名稱必須是字符串: %s", category)
                return False
                
            if not isinstance(sites, list):
                logger.error("分類 %s 的網站列表必須是列表", category)
                return False
                
            for site in sites:
                if not isinstance(site, str):
                    logger.error("網站地址必須是字符串: %s", site)
                    return False
    
    return True