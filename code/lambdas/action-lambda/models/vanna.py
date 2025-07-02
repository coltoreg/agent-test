from dataclasses import dataclass
from typing import TypedDict, List, Dict

@dataclass
class CompanyInfo:
    company: str
    brand: str
    product: str
    product_category: str
    target_title: str

# ====================== output format ======================
# ─────────────────────────  最底層  ───────────────────────── #
class SQLLeaf(TypedDict, total=False):
    """只有 title 與 sql_text 的最小單元"""
    title: str
    sql_text: List[str]            # 允許空 list 代表「暫無內容」

# ─────────────────────────  次底層  ───────────────────────── #
class SubSubTopic(SQLLeaf, total=False):
    """可再往下延伸 (理論上現在沒有再更深)"""
    subsubtopics: List["SubSubTopic"]  # 允許遞迴（保留擴充性）

# ─────────────────────────  中層  ───────────────────────── #
class SubTopic(TypedDict, total=False):
    title: str
    subsubtopics: List[SubSubTopic]

# ─────────────────────────  主題層  ───────────────────────── #
class MainTopic(TypedDict, total=False):
    title: str
    subtopics: List[SubTopic]

# ─────────────────────────  輸出總型別  ───────────────────────── #
OutputFormat = Dict[str, MainTopic]

class QueryItem(TypedDict):
    question: str
    title: str
    path: str
    index: int