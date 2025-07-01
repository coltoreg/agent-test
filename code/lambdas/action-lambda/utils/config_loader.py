"""
Configuration loader utilities for Lambda functions.
Handles loading YAML configuration files with proper error handling and fallbacks.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Union, Optional
from functools import lru_cache

import yaml

# Set up logger
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_industry_sites(cfg_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """
    讀取並快取產業/網站 YAML 配置文件
    
    Args:
        cfg_path: 配置文件路徑，如果為 None 則使用默認路徑
        
    Returns:
        Dict: 產業網站配置字典，出錯時返回空字典
        
    Examples:
        >>> sites = load_industry_sites()
        >>> tech_sites = sites.get("科技產業", {})
        >>> news_sites = tech_sites.get("科技新聞與趨勢", [])
    """
    # 設置默認配置文件路徑
    if cfg_path is None:
        cfg_path = "config/industry_sites.yaml"
    
    # 轉換為 Path 對象便於處理
    config_path = Path(cfg_path)
    
    try:
        # 檢查文件是否存在
        if not config_path.exists():
            # 嘗試相對於當前腳本的路徑
            script_dir = Path(__file__).parent.parent
            alternative_path = script_dir / cfg_path
            
            if alternative_path.exists():
                config_path = alternative_path
                logger.info(f"Using alternative config path: {config_path}")
            else:
                logger.warning(f"Configuration file not found: {cfg_path}")
                logger.warning(f"Also tried: {alternative_path}")
                return _get_fallback_config()
        
        # 讀取並解析 YAML 文件
        with open(config_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
            
        # 驗證內容
        if not isinstance(content, dict):
            logger.error(f"Invalid configuration format in {config_path}: expected dict, got {type(content)}")
            return _get_fallback_config()
            
        if not content:
            logger.warning(f"Empty configuration file: {config_path}")
            return _get_fallback_config()
            
        logger.info(f"Successfully loaded configuration from: {config_path}")
        logger.debug(f"Loaded {len(content)} industry categories")
        
        return content
        
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error in {config_path}: {e}")
        return _get_fallback_config()
        
    except FileNotFoundError as e:
        logger.error(f"Configuration file not found: {config_path}")
        return _get_fallback_config()
        
    except PermissionError as e:
        logger.error(f"Permission denied reading {config_path}: {e}")
        return _get_fallback_config()
        
    except Exception as e:
        logger.exception(f"Unexpected error loading configuration from {config_path}: {e}")
        return _get_fallback_config()


def _get_fallback_config() -> Dict[str, Any]:
    """
    返回備用配置，確保系統能夠繼續運行
    
    Returns:
        Dict: 基本的產業網站配置
    """
    logger.info("Using fallback configuration")
    
    return {
        "科技產業": {
            "科技新聞與趨勢": [
                "techcrunch.com",
                "theverge.com",
                "wired.com"
            ],
            "資訊科技研究": [
                "gartner.com",
                "forrester.com"
            ]
        },
        "綜合研究與趨勢": {
            "產業趨勢與白皮書": [
                "mckinsey.com",
                "bcg.com",
                "bain.com"
            ],
            "企業財經與產業新聞": [
                "bloomberg.com",
                "reuters.com"
            ]
        }
    }


def validate_config(config: Dict[str, Any]) -> bool:
    """
    驗證配置格式是否正確
    
    Args:
        config: 配置字典
        
    Returns:
        bool: 配置是否有效
    """
    try:
        if not isinstance(config, dict):
            return False
            
        for industry_name, industry_data in config.items():
            if not isinstance(industry_name, str):
                logger.error(f"Invalid industry name type: {type(industry_name)}")
                return False
                
            if not isinstance(industry_data, dict):
                logger.error(f"Invalid industry data type for {industry_name}: {type(industry_data)}")
                return False
                
            for category_name, sites in industry_data.items():
                if not isinstance(category_name, str):
                    logger.error(f"Invalid category name type in {industry_name}: {type(category_name)}")
                    return False
                    
                if not isinstance(sites, list):
                    logger.error(f"Invalid sites type for {industry_name}.{category_name}: {type(sites)}")
                    return False
                    
                for site in sites:
                    if not isinstance(site, str):
                        logger.error(f"Invalid site type in {industry_name}.{category_name}: {type(site)}")
                        return False
                        
        return True
        
    except Exception as e:
        logger.exception(f"Error validating config: {e}")
        return False


def get_config_info(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    獲取配置統計信息
    
    Args:
        config: 配置字典
        
    Returns:
        Dict: 配置統計信息
    """
    try:
        total_industries = len(config)
        total_categories = sum(len(industry_data) for industry_data in config.values())
        total_sites = sum(
            len(sites) 
            for industry_data in config.values() 
            for sites in industry_data.values()
        )
        
        return {
            "total_industries": total_industries,
            "total_categories": total_categories,
            "total_sites": total_sites,
            "industries": list(config.keys())
        }
        
    except Exception as e:
        logger.exception(f"Error getting config info: {e}")
        return {
            "total_industries": 0,
            "total_categories": 0,
            "total_sites": 0,
            "industries": []
        }


def reload_config() -> Dict[str, Any]:
    """
    清除緩存並重新加載配置
    
    Returns:
        Dict: 重新加載的配置
    """
    logger.info("Reloading configuration (clearing cache)")
    load_industry_sites.cache_clear()
    return load_industry_sites()


# 環境變量相關的配置加載器
def get_env_config() -> Dict[str, str]:
    """
    獲取環境變量配置
    
    Returns:
        Dict: 環境變量配置字典
    """
    env_vars = [
        "AWS_REGION",
        "OPENAI_API_KEY", 
        "OUTPUT_S3_BUCKET",
        "TEXT2SQL_DATABASE",
        "LOG_LEVEL",
        "FEWSHOT_EXAMPLES_PATH",
        "SECRET_NAME",
        "SECRET_NAME_PPLX"
    ]
    
    config = {}
    missing_vars = []
    
    for var in env_vars:
        value = os.getenv(var)
        if value is not None:
            config[var] = value
        else:
            missing_vars.append(var)
    
    if missing_vars:
        logger.warning(f"Missing environment variables: {missing_vars}")
    
    return config


if __name__ == "__main__":
    # 測試配置加載
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    print("Testing config loader...")
    
    # 測試加載配置
    config = load_industry_sites()
    print(f"Loaded config with {len(config)} industries")
    
    # 驗證配置
    is_valid = validate_config(config)
    print(f"Configuration is valid: {is_valid}")
    
    # 獲取統計信息
    info = get_config_info(config)
    print(f"Config info: {info}")
    
    # 測試環境變量
    env_config = get_env_config()
    print(f"Environment variables found: {len(env_config)}")
    
    print("Config loader test completed.")