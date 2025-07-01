from __future__ import annotations

import os
from collections.abc import Iterable, Sequence

from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError
from utils.config_loader import load_industry_sites
from services.connections import Connections

logger = setup_logger(__name__)


class WebSearchService:
    """
    YAML → include╱exclude 網域 → 組合查詢 → 呼叫 Perplexity
    """

    # 預設排除（可用環境變數覆寫）
    DEFAULT_EXCLUDE = os.getenv(
        "EXCLUDE_SITES",
        "baidu.com, zhihu.com, weixin.qq.com"
    ).split(",")

    def __init__(self, cfg_path: str | None = None):
        self.conn = Connections()
        try:
            self._site_map = load_industry_sites(cfg_path)
        except Exception as e:
            logger.warning(f"Failed to load industry sites config: {e}")
            self._site_map = {}

    # -------------------------------------------------
    # PUBLIC API ―― 與舊版保持相同的 I/O 介面
    # -------------------------------------------------
    def search_internet(
        self,
        query_text: str,
        *,
        industries: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        extra_include: Sequence[str] | None = None,
        extra_exclude: Sequence[str] | None = None,
    ) -> dict:
        """
        保留舊版呼叫方式：
            search_internet("生成式 AI")  ✔︎

        亦支援進階玩法：
            search_internet(
                "2025 美妝市場趨勢",
                industries=["FMCG_美妝_電商產業"],
                categories=["美妝產業動態"],
                extra_exclude=["reddit.com"],
            )
        """
        if not query_text:
            raise ValidationError("Query parameter is required.")

        include_sites = (
            set(self._collect_sites(industries, categories))
            | set(extra_include or [])
        )
        exclude_sites = set(self.DEFAULT_EXCLUDE) | set(extra_exclude or [])

        enhance_query = self._build_query(query_text, include_sites, exclude_sites)
        logger.info("🧩 enhance_query = %s", enhance_query)

        messages = [
            {"role": "system", "content": "Be precise and concise."},
            {"role": "user", "content": enhance_query},
        ]

        try:
            client = self.conn.openai_client()
            response = client.chat.completions.create(
                model="sonar-pro",
                messages=messages,
                stream=False,
            )

            return {
                "query": enhance_query,
                "response": {
                    "answer": response.choices[0].message.content,
                    "sources": getattr(response, "citations", []),
                },
            }

        except ValidationError:
            raise
        except Exception as exc:
            logger.exception("Failed to perform internet search.")
            raise ExternalAPIError("Error performing internet search.") from exc

    # -------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------
    def _collect_sites(
        self,
        industries: Sequence[str] | None,
        categories: Sequence[str] | None,
    ) -> list[str]:
        """根據 YAML 選出欲 include 的網域"""
        sites: list[str] = []

        picked_industries = industries or self._site_map.keys()
        for ind in picked_industries:
            if ind not in self._site_map:
                logger.warning("Unknown industry: %s (ignored)", ind)
                continue

            picked_cates = categories or self._site_map[ind].keys()
            for cate in picked_cates:
                sites += self._site_map[ind].get(cate, [])

        return sites

    @staticmethod
    def _build_query(
        query_text: str,
        include_sites: Iterable[str],
        exclude_sites: Iterable[str],
    ) -> str:
        """site: 與 -site: 子句拼接"""
        include_clause = " OR ".join(f"site:{s.strip()}" for s in include_sites)
        exclude_clause = " ".join(f"-site:{s.strip()}" for s in exclude_sites)
        return f"{query_text} {include_clause} {exclude_clause}".strip()