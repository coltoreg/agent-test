from pathlib import Path
import yaml
from functools import lru_cache

@lru_cache
def load_industry_sites(cfg_path: str | Path = "config/industry_sites.yaml") -> dict:
    """讀取並快取產業╱網站 YAML"""
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)