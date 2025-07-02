from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field

from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError
from utils.config_loader import load_industry_sites, validate_config_structure
from services.connections import Connections

logger = setup_logger(__name__)


@dataclass
class SearchContext:
    """搜尋上下文，包含所有搜尋相關資訊"""
    original_query: str
    enhanced_query: str
    industries_used: List[str] = field(default_factory=list)
    categories_used: List[str] = field(default_factory=list)
    sites_included: List[str] = field(default_factory=list)
    sites_excluded: List[str] = field(default_factory=list)
    total_sites_available: int = 0
    strategy: str = "manual"
    fallback_reason: Optional[str] = None


@dataclass 
class SearchResult:
    """結構化搜尋結果"""
    context: SearchContext
    answer: str
    sources: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class WebSearchService:
    """
    針對台灣市場優化的網路搜尋服務
    支援多產業、多分類的精準搜尋
    """

    # 針對台灣市場優化的預設排除網站
    DEFAULT_EXCLUDE = [
        "baidu.com", "zhihu.com", "weixin.qq.com",
        "pinterest.com", "quora.com", "reddit.com",
        "facebook.com", "instagram.com", "twitter.com"  # 社群媒體通常內容品質較低
    ]

    # 產業分組配置，用於智能推薦
    INDUSTRY_GROUPS = {
        "科技類": ["科技產業", "B2B_SaaS"],
        "商業研究": ["綜合研究與趨勢", "消費者行為與心理分析"],
        "消費市場": ["FMCG_美妝_電商產業", "食品_飲料"],
        "服務業": ["觀光_交通_旅遊", "教育_親子"],
        "傳統產業": ["房地產_建築", "醫療健康"]
    }

    def __init__(self, cfg_path: str | None = None):
        """初始化搜尋服務"""
        logger.info("初始化 WebSearchService...")
        
        try:
            self.conn = Connections()
            self._site_map = load_industry_sites(cfg_path)
            
            if self._site_map and not validate_config_structure(self._site_map):
                logger.error("配置文件結構驗證失敗")
                raise ValidationError("配置文件結構不正確")
            
            # 統計配置資訊
            total_industries = len(self._site_map)
            total_categories = sum(len(cats) for cats in self._site_map.values())
            total_sites = sum(
                len(sites) for industry in self._site_map.values()
                for sites in industry.values()
            )
            
            logger.info(
                "WebSearchService 初始化成功: %d 產業, %d 分類, %d 網站",
                total_industries, total_categories, total_sites
            )
            
        except Exception as e:
            logger.error("WebSearchService 初始化失敗: %s", e)
            self._site_map = {}
            logger.warning("使用空配置繼續運行")

    @staticmethod
    def _clean_string_list(items):
        """統一的字符串清理邏輯"""
        if not items:
            return []
        return [item.strip() for item in items if item and item.strip()]

    def search_internet(
        self,
        query: str,
        *,
        industries: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        extra_include: Sequence[str] | None = None,
        extra_exclude: Sequence[str] | None = None,
        smart_selection: bool = True,
    ) -> Dict[str, Any]:
        """
        執行智能網路搜尋
        
        Args:
            query: 搜尋查詢
            industries: 指定產業列表
            categories: 指定分類列表
            extra_include: 額外包含網站
            extra_exclude: 額外排除網站
            smart_selection: 是否啟用智能網站選擇
            
        Returns:
            Dict: 包含搜尋結果和上下文的完整回應
        """
        # 輸入驗證
        self._validate_input(query, industries, categories)
        
        # 智能選擇產業和分類（如果啟用）
        if smart_selection and not industries:
            industries = self._smart_industry_selection(query)
        
        # 收集網站
        include_sites, exclude_sites = self._collect_all_sites(
            industries, categories, extra_include, extra_exclude
        )
        
        # 構建搜尋上下文
        context = self._build_search_context(
            query, industries, categories, include_sites, exclude_sites
        )
        
        # 執行搜尋
        try:
            search_response = self._perform_search(context.enhanced_query)
            
            return {
                "success": True,
                "context": {
                    "original_query": context.original_query,
                    "enhanced_query": context.enhanced_query,
                    "industries_used": context.industries_used,
                    "categories_used": context.categories_used,
                    "sites_stats": {
                        "included": len(context.sites_included),
                        "excluded": len(context.sites_excluded),
                        "total_available": context.total_sites_available
                    },
                    "strategy": context.strategy,
                    "fallback_reason": context.fallback_reason
                },
                "result": {
                    "answer": search_response["response"]["answer"],
                    "sources": search_response["response"]["sources"],
                },
                "metadata": {
                    "search_strategy": context.strategy,
                    "config_status": "loaded" if self._site_map else "empty",
                    "query_enhancement": len(context.enhanced_query) > len(context.original_query),
                    "is_fallback": context.strategy == "open_fallback"
                }
            }

            
        except Exception as e:
            logger.exception("搜尋執行失敗")
            return {
                "success": False,
                "error": str(e),
                "context": {
                    "original_query": context.original_query,
                    "enhanced_query": context.enhanced_query,
                }
            }

    def _validate_input(
        self,
        query: str,
        industries: Sequence[str] | None,
        categories: Sequence[str] | None,
    ) -> None:
        """輸入驗證"""
        if not query or not query.strip():
            raise ValidationError("查詢文字不能為空")
        
        if len(query.strip()) > 500:
            raise ValidationError("查詢文字過長（最多500字符）")
        
        # 驗證產業存在性
        if industries:
            unknown_industries = [
                ind for ind in industries if ind not in self._site_map
            ]
            if unknown_industries:
                logger.warning("未知產業將被忽略: %s", unknown_industries)

    def _smart_industry_selection(self, query: str) -> List[str]:
        """
        基於查詢內容智能選擇相關產業
        新增：如果沒有匹配到任何產業，返回空列表觸發fallback
        """
        query_lower = query.lower()
        selected_industries = []
        
        # 關鍵字對應產業的映射
        keyword_mapping = {
            "科技產業": ["ai", "人工智慧", "科技", "tech", "軟體", "程式", "開發", "雲端", "aws", "google", "microsoft"],
            "B2B_SaaS": ["saas", "crm", "b2b", "企業軟體", "行銷科技", "martech"],
            "醫療健康": ["醫療", "健康", "醫美", "保健", "藥物", "疫苗", "醫院"],
            "FMCG_美妝_電商產業": ["美妝", "電商", "零售", "購物", "化妝品", "保養", "網購", "洗髮", "洗髮精", "洗髮露", "去屑", "護髮", "p&g", "寶僑"],
            "食品_飲料": ["食品", "飲料", "餐廳", "美食", "食物"],
            "房地產_建築": ["房地產", "房價", "建築", "室內設計", "裝潢"],
            "觀光_交通_旅遊": ["旅遊", "觀光", "航空", "交通", "飯店"],
            "教育_親子": ["教育", "學習", "親子", "兒童", "學校"],
            "綜合研究與趨勢": ["趨勢", "研究", "分析", "報告", "市場", "統計"]
        }
        
        for industry, keywords in keyword_mapping.items():
            if industry in self._site_map and any(keyword in query_lower for keyword in keywords):
                selected_industries.append(industry)
        
        # 移除原本的綜合研究fallback，讓它自然觸發開放搜尋
        if selected_industries:
            logger.info("智能選擇產業: %s", selected_industries)
        else:
            logger.info("未匹配到特定產業，將使用開放搜尋策略")
        
        return selected_industries

    def _collect_all_sites(
        self,
        industries: Sequence[str] | None,
        categories: Sequence[str] | None,
        extra_include: Sequence[str] | None,
        extra_exclude: Sequence[str] | None,
    ) -> tuple[Set[str], Set[str]]:
        """收集所有包含和排除的網站 - 新增fallback邏輯"""
        # 從配置收集網站
        config_sites = self._collect_sites_from_config(industries, categories)
        
        # 建立包含網站集合
        include_sites = set(config_sites)
        if extra_include:
            include_sites.update(site.strip() for site in extra_include if site.strip())
        
        # 建立排除網站集合
        exclude_sites = self._get_exclude_sites(extra_exclude)
        
        # 新增：fallback檢查
        if not include_sites and not extra_include:
            logger.info("觸發fallback機制：沒有指定包含網站，使用開放搜尋")
            # 不設定任何包含網站，只排除不良網站
            return set(), exclude_sites
        
        # 從包含列表中移除排除的網站
        include_sites -= exclude_sites
        
        return include_sites, exclude_sites
    
    def _collect_sites_from_config(self, industries, categories):
        """使用統一的清理邏輯"""
        if not self._site_map:
            return []
        
        sites = []
        target_industries = industries or list(self._site_map.keys())
        
        for industry in target_industries:
            if industry not in self._site_map:
                continue
            
            target_categories = categories or list(self._site_map[industry].keys())
            
            for category in target_categories:
                if category in self._site_map[industry]:
                    category_sites = self._site_map[industry][category]
                    if isinstance(category_sites, list):
                        sites.extend(category_sites)
        
        return list(set(self._clean_string_list(sites)))
    
    def _get_exclude_sites(self, extra_exclude):
        """使用統一的清理邏輯"""
        exclude_sites = set(
            os.getenv("EXCLUDE_SITES", ",".join(self.DEFAULT_EXCLUDE)).split(",")
        )
        
        if extra_exclude:
            exclude_sites.update(extra_exclude)
        
        return set(self._clean_string_list(exclude_sites))

    def _build_search_context(
        self,
        query: str,
        industries: Sequence[str] | None,
        categories: Sequence[str] | None,
        include_sites: Set[str],
        exclude_sites: Set[str],
    ) -> SearchContext:
        """構建搜尋上下文 - 新增策略判斷"""
        enhanced_query = self._build_enhanced_query(query, include_sites, exclude_sites)
        
        # 判斷搜尋策略
        strategy = "manual"
        fallback_reason = None
        
        if not industries and not categories:
            if not include_sites:
                strategy = "open_fallback"
                fallback_reason = "未找到匹配的產業分類，使用開放搜尋"
            else:
                strategy = "smart_fallback"
        elif industries or categories:
            strategy = "targeted"
        
        return SearchContext(
            original_query=query.strip(),
            enhanced_query=enhanced_query,
            industries_used=list(industries) if industries else [],
            categories_used=list(categories) if categories else [],
            sites_included=list(include_sites),
            sites_excluded=list(exclude_sites),
            total_sites_available=sum(
                len(cats_sites) for industry_sites in self._site_map.values()
                for cats_sites in industry_sites.values()
            ) if self._site_map else 0,
            strategy=strategy,
            fallback_reason=fallback_reason
        )

    def _build_enhanced_query(
        self,
        query: str,
        include_sites: Set[str],
        exclude_sites: Set[str],
    ) -> str:
        """構建增強查詢 - 新增fallback支援"""
        parts = [query.strip()]
        
        # 新增：fallback情況下只加排除條件
        if not include_sites:
            logger.info("🔄 使用開放搜尋策略，僅排除不良網站")
            # 只處理排除網站
            for site in exclude_sites:
                parts.append(f"-site:{site}")
        else:
            # 原本的邏輯：處理包含網站
            if len(include_sites) <= 3:
                # 少量網站直接列出
                for site in include_sites:
                    parts.append(f"site:{site}")
            else:
                # 多網站使用 OR 組合
                site_clause = " OR ".join(f"site:{site}" for site in include_sites)
                parts.append(f"({site_clause})")
            
            # 處理排除網站
            for site in exclude_sites:
                parts.append(f"-site:{site}")
        
        enhanced = " ".join(parts)
        logger.info("🔍 查詢增強: %s -> %s", query, enhanced)
        
        return enhanced

    def _perform_search(self, enhanced_query: str) -> Dict[str, Any]:
        """執行實際搜尋"""
        logger.info(f"Search Input: {enhanced_query}")
        messages = [
            {
                "role": "system",
                "content": "請提供精確、簡潔的回答。如果有多個來源，請綜合分析給出客觀結論。"
            },
            {"role": "user", "content": enhanced_query}
        ]

        try:
            client = self.conn.openai_client()
            response = client.chat.completions.create(
                model="sonar-pro",
                messages=messages,
                stream=False,
            )

            return {
                "query": enhanced_query,
                "response": {
                    "answer": response.choices[0].message.content,
                    "sources": getattr(response, "citations", []),
                },
            }

        except Exception as exc:
            logger.exception("Perplexity API 調用失敗")
            raise ExternalAPIError("搜尋 API 調用失敗") from exc