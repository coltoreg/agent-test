# output_format = {
#   "市場概況與趨勢": {
#     "title": "市場概況與趨勢",
#     "subtopics": [
#       {
#         "title": "產業規模與成長",
#         "subsubtopics": [
#           "台灣市場規模與成長",
#           "產品類型演進",
#           "年度銷售變化",
#           "驅動因素與未來展望"
#         ]
#       },
#       {
#         "title": "主導品牌分析",
#         "subsubtopics": [
#           "主導品牌銷售概況",
#           "價格帶分析",
#           "平價帶市場概況",
#           "高價帶市場概況",
#           "價格帶結構與策略定位",
#           "價格帶市佔變化趨勢"
#         ]
#       },
#       # {
#       #   "title": "消費者痛點與聲量",
#       #   "subsubtopics": [
#       #     "痛點分析",
#       #     "正面熱點事件",
#       #     "負面熱點事件",
#       #     "聲量與情緒趨勢",
#       #     "痛點轉化機會"
#       #   ]
#       # },
#       # {
#       #   "title": "未來政策與永續趨勢",
#       #   "subsubtopics": [
#       #     "國際政策動向",
#       #     "台灣政策動向",
#       #     "ESG 與永續議題"
#       #   ]
#       # },
#       # {
#       #   "title": "市場概況與趨勢總結",
#       #   "subsubtopics": [
#       #       "市場概況總結",
#       #       "Why 為何是這些變化重要",
#       #       "How 品牌該如何應對市場變化"
#       #   ]
#       # }
#     ]
#   },
#   "品牌定位與形象": {
#     "title": "品牌定位與形象",
#     "subtopics": [
#       {
#         "title": "品牌價格與功能定位",
#         "subsubtopics": []
#       },
#       {
#         "title": "品牌形象",
#         "subsubtopics": []
#       },
#       {
#         "title": "獨特銷售主張（USP）",
#         "subsubtopics": []
#       }
#     ]
#   },
#   "產品分析": {
#     "title": "產品分析",
#     "subtopics": [
#       {
#         "title": "熱銷產品銷量",
#         "subsubtopics": []
#       },
#       {
#         "title": "主打銷售通路",
#         "subsubtopics": []
#       },
#       {
#         "title": "目標族群與使用情境",
#         "subsubtopics": []
#       },
#       {
#         "title": "產品獨特銷售主張",
#         "subsubtopics": []
#       }
#     ]
#   },
#   "消費者行為與洞察": {
#     "title": "消費者行為與洞察",
#     "subtopics": [
#       {
#         "title": "顧客輪廓",
#         "subsubtopics": [
#           "人口屬性",
#           "生活型態",
#           "消費力與行為"
#         ]
#       },
#       {
#         "title": "購買動機",
#         "subsubtopics": []
#       },
#       {
#         "title": "廣告投放策略",
#         "subsubtopics": [
#           "線上投放策略",
#           "線下場域策略"
#         ]
#       },
#       {
#         "title": "Persona",
#         "subsubtopics": []
#       }
#     ]
#   },
#   "競品分析": {
#     "title": "競品分析",
#     "subtopics": [
#       {
#         "title": "功能對比",
#         "subsubtopics": []
#       },
#       {
#         "title": "通路對比",
#         "subsubtopics": []
#       },
#       {
#         "title": "受眾與使用情境差異",
#         "subsubtopics": []
#       },
#       {
#         "title": "競品獨特銷售主張",
#         "subsubtopics": []
#       },
#       {
#         "title": "產品優劣點",
#         "subsubtopics": []
#       }
#     ]
#   },
#   "結論與建議": {
#     "title": "結論與建議",
#     "subtopics": [
#       {
#         "title": "產品賣點",
#         "subsubtopics": []
#       },
#       {
#         "title": "行銷策略",
#         "subsubtopics": []
#       }
#     ]
#   }
# }

output_format = {
    "市場概況與趨勢": {
        "title": "市場概況與趨勢",
        "subtopics": [
            {
                "title": "產業規模與成長",
                "subsubtopics": [
                    {
                        "title": "台灣市場規模與成長",
                        "prompt": "分析台灣該產業的市場規模數據，包含近3-5年的市場規模變化、成長率趨勢、市場價值估算等相關統計數據。"
                    },
                    {
                        "title": "產品類型演進",
                        "prompt": "探討該產業產品類型的演進歷程，包含傳統產品到新興產品的轉變、技術創新帶來的產品形態變化、消費者需求導向的產品開發趨勢。"
                    },
                    {
                        "title": "年度銷售變化",
                        "prompt": "分析近年來該產業的年度銷售表現，包含銷售額變化、銷售量趨勢、季節性波動、疫情等外在因素對銷售的影響。"
                    },
                    {
                        "title": "驅動因素與未來展望",
                        "prompt": "識別推動該產業成長的關鍵驅動因素，如技術進步、消費習慣改變、政策支持等，並預測未來3-5年的市場發展趨勢與機會。"
                    }
                ]
            },
            {
                "title": "主導品牌分析",
                "subsubtopics": [
                    {
                        "title": "主導品牌銷售概況",
                        "prompt": "分析該產業前5-10大主導品牌的銷售表現，包含市佔率排名、銷售額、品牌實力評估、競爭優勢分析。"
                    },
                    {
                        "title": "價格帶分析",
                        "prompt": "將市場產品按價格區間分類分析，包含各價格帶的產品特徵、消費族群、銷售表現、價格競爭策略。"
                    },
                    {
                        "title": "平價帶市場概況",
                        "prompt": "深入分析平價帶市場的現況，包含主要品牌、產品特色、消費者偏好、銷售通路、競爭激烈程度。"
                    },
                    {
                        "title": "高價帶市場概況",
                        "prompt": "深入分析高價帶市場的現況，包含精品品牌表現、高端消費者行為、產品差異化策略、利潤結構分析。"
                    },
                    {
                        "title": "價格帶結構與策略定位",
                        "prompt": "分析各品牌在不同價格帶的策略定位，包含品牌組合策略、價格定位邏輯、目標客群區隔、競爭策略差異。"
                    },
                    {
                        "title": "價格帶市佔變化趨勢",
                        "prompt": "追蹤各價格帶市場佔有率的變化趨勢，分析消費者購買行為在價格帶間的移轉情況，預測未來價格結構演變。"
                    }
                ]
            },
            {
                "title": "消費者痛點與聲量",
                "subsubtopics": [
                    {
                        "title": "痛點分析",
                        "prompt": "深入分析消費者在該產業中遇到的主要痛點，包含產品功能不足、服務問題、價格敏感度、使用體驗困擾等核心問題。"
                    },
                    {
                        "title": "正面熱點事件",
                        "prompt": "收集並分析該產業近期的正面熱點事件，包含品牌創新突破、消費者正面回饋、媒體正面報導、行業標竿案例。"
                    },
                    {
                        "title": "負面熱點事件",
                        "prompt": "分析該產業近期的負面熱點事件，包含產品問題、服務爭議、品牌危機、消費者抱怨、媒體負面報導及其影響。"
                    },
                    {
                        "title": "聲量與情緒趨勢",
                        "prompt": "追蹤該產業在社群媒體與網路平台的討論聲量變化，分析消費者情緒趨勢、話題熱度、品牌提及度、情感傾向分析。"
                    },
                    {
                        "title": "痛點轉化機會",
                        "prompt": "基於痛點分析，識別可轉化為商業機會的消費者需求缺口，提出解決方案建議、產品改善方向、服務優化機會。"
                    }
                ]
            },
            {
                "title": "未來政策與永續趨勢",
                "subsubtopics": [
                    {
                        "title": "國際政策動向",
                        "prompt": "分析影響該產業的國際政策趨勢，包含貿易政策、環保法規、技術標準、國際合作協議對市場的潛在影響。"
                    },
                    {
                        "title": "台灣政策動向",
                        "prompt": "研究台灣政府對該產業的政策方向，包含產業政策、補助措施、法規變化、發展規劃對市場發展的影響。"
                    },
                    {
                        "title": "ESG 與永續議題",
                        "prompt": "分析ESG與永續發展議題對該產業的影響，包含環境責任、社會責任、公司治理要求、綠色轉型趨勢、永續商業模式。"
                    }
                ]
            },
            {
                "title": "市場概況與趨勢總結",
                "subsubtopics": [
                    {
                        "title": "市場概況總結",
                        "prompt": "綜合前述各項分析，總結該產業的整體市場概況，包含關鍵發現、重要趨勢、市場特徵、發展現狀的整體描述。"
                    },
                    {
                        "title": "為何這些變化重要",
                        "prompt": "深入分析市場變化的重要性和意義，解釋這些趨勢對產業、品牌、消費者的影響，說明變化背後的驅動力和必要性。"
                    },
                    {
                        "title": "品牌該如何應對市場變化",
                        "prompt": "基於市場變化分析，提出品牌應對策略建議，包含策略調整方向、執行重點、資源配置建議、風險規避措施。"
                    }
                ]
            }
        ]
    },
    "品牌定位與形象": {
        "title": "品牌定位與形象",
        "subtopics": [
            {
                "title": "產業規模與成長",
                "subsubtopics": [
                    {
                        "title": "品牌價格策略",
                        "prompt": "分析台灣該產業的市場規模數據，包含近3-5年的市場規模變化、成長率趨勢、市場價值估算等相關統計數據。"
                    },
                    {
                        "title": "功能定位分析",
                        "prompt": "探討該產業產品類型的演進歷程，包含傳統產品到新興產品的轉變、技術創新帶來的產品形態變化、消費者需求導向的產品開發趨勢。"
                    },
                ]
            },
            {
                "title": "品牌形象",
                "subsubtopics": [
                    {
                        "title": "品牌關鍵字",
                        "prompt": "分析台灣該產業的市場規模數據，包含近3-5年的市場規模變化、成長率趨勢、市場價值估算等相關統計數據。"
                    },
                    {
                        "title": "品牌視覺元素",
                        "prompt": "探討該產業產品類型的演進歷程，包含傳統產品到新興產品的轉變、技術創新帶來的產品形態變化、消費者需求導向的產品開發趨勢。"
                    },
                    {
                        "title": "品牌標語",
                        "prompt": "探討該產業產品類型的演進歷程，包含傳統產品到新興產品的轉變、技術創新帶來的產品形態變化、消費者需求導向的產品開發趨勢。"
                    },
                ]
            },
            {
                "title": "獨特銷售主張（USP）",
                "prompt": "識別該品牌的獨特銷售主張，分析品牌如何在市場中建立差異化優勢、核心競爭力、獨特價值提案、與競品區隔的關鍵要素。"
            }
        ]
    },
    "產品分析": {
        "title": "產品分析",
        "subtopics": [
            {
                "title": "產品獨特銷售主張（USP）",
                "prompt": "分析該品牌熱銷產品的銷量表現，包含主力產品排行、銷量數據、銷售趨勢、產品生命週期分析、熱銷因素探討。"
            },
            {
                "title": "產品使用情境",
                "prompt": "分析產品的主要銷售通路策略，包含線上線下通路分布、通路夥伴關係、通路銷售表現、通路策略有效性評估。"
            },
            {
                "title": "產品銷量",
                "prompt": "定義產品的核心目標族群，分析主要使用情境、消費者需求滿足情況、使用頻率與使用場景、族群擴張機會。"
            },
            {
                "title": "產品銷售通路",
                "prompt": "分析產品層面的獨特銷售主張，包含產品核心優勢、技術創新點、功能差異化、使用體驗優勢、產品價值主張。"
            }
        ]
    },
    "受眾洞察與溝通策略建議": {
        "title": "受眾洞察與溝通策略建議",
        "subtopics": [
            {
                "title": "市場受眾概況",
                "subsubtopics": [
                    {
                        "title": "人口屬性",
                        "prompt": "分析目標消費者的人口統計資料，包含年齡層分布、性別比例、教育程度、職業類別、收入水準、居住地區等基本屬性。"
                    },
                    {
                        "title": "消費習慣",
                        "prompt": "深入了解目標消費者的生活型態，包含興趣愛好、價值觀念、生活習慣、社交行為、媒體使用習慣、休閒活動偏好。"
                    },
                    {
                        "title": "購買動機",
                        "prompt": "分析消費者的消費能力與購買行為模式，包含消費預算、購買頻率、決策流程、購買動機、品牌忠誠度、消費習慣。"
                    }
                ]
            },
            {
                "title": "商品目標受眾分析",
                "subsubtopics": [
                    {
                        "title": "人口屬性",
                        "prompt": "分析目標消費者的人口統計資料，包含年齡層分布、性別比例、教育程度、職業類別、收入水準、居住地區等基本屬性。"
                    },
                    {
                        "title": "消費習慣",
                        "prompt": "深入了解目標消費者的生活型態，包含興趣愛好、價值觀念、生活習慣、社交行為、媒體使用習慣、休閒活動偏好。"
                    },
                    {
                        "title": "購買動機",
                        "prompt": "分析消費者的消費能力與購買行為模式，包含消費預算、購買頻率、決策流程、購買動機、品牌忠誠度、消費習慣。"
                    }
                ]
            },
            {
                "title": "代表性消費者輪廓（Persona）",
                "prompt": "建立詳細的消費者人物誌，整合人口屬性、行為模式、需求痛點、購買旅程，創建具體的目標客群代表人物描述。"
            }
        ]
    },
    "競品分析": {
        "title": "競品分析",
        "subtopics": [
            {
                "title": "競品價格與功能定位",
                "subsubtopics": [
                    {
                        "title": "價格策略分析",
                        "prompt": "分析目標消費者的人口統計資料，包含年齡層分布、性別比例、教育程度、職業類別、收入水準、居住地區等基本屬性。"
                    },
                    {
                        "title": "功能定位比較",
                        "prompt": "深入了解目標消費者的生活型態，包含興趣愛好、價值觀念、生活習慣、社交行為、媒體使用習慣、休閒活動偏好。"
                    },
                    {
                        "title": "使用情境對照",
                        "prompt": "分析消費者的消費能力與購買行為模式，包含消費預算、購買頻率、決策流程、購買動機、品牌忠誠度、消費習慣。"
                    }
                ]
            },
            {
                "title": "競品銷售狀況分析",
                "prompt": "進行競品功能比較分析，包含產品規格對比、功能特色比較、技術優劣勢分析、創新功能評估、功能滿足度比較。"
            },
            {
                "title": "代表通路銷量對比",
                "subsubtopics": [
                    {
                        "title": "電商平台銷量對比",
                        "prompt": "分析目標消費者的人口統計資料，包含年齡層分布、性別比例、教育程度、職業類別、收入水準、居住地區等基本屬性。"
                    },
                    {
                        "title": "線下通路銷量對比",
                        "prompt": "深入了解目標消費者的生活型態，包含興趣愛好、價值觀念、生活習慣、社交行為、媒體使用習慣、休閒活動偏好。"
                    },
                ]
            },
            {
                "title": "競品獨特銷售主張（USP）",
                "prompt": "進行競品功能比較分析，包含產品規格對比、功能特色比較、技術優劣勢分析、創新功能評估、功能滿足度比較。"
            },
            {
                "title": "與競品之優劣分析",
                "prompt": "進行競品功能比較分析，包含產品規格對比、功能特色比較、技術優劣勢分析、創新功能評估、功能滿足度比較。"
            },
        ]
    }
}

evaluation_prompt_en = """Please evaluate the input content according to the following 11 criteria. Each criterion should be rated on a scale of 1 to 3, along with a brief explanation for the score.

Definitions and scoring standards for each indicator:

- Completeness  
Definition: Does the content cover all the core elements of the prompt (e.g., analytical dimensions, recommendations, target audience)?  
1: Major analytical aspects or recommendations are missing; structure is disorganized  
2: Most points are covered but lack depth or clarity  
3: Clear structure with all key points addressed thoroughly

- Data Support  
Definition: Are specific data points, social listening tools, or cited sources used to support arguments?  
1: No data or vague sources  
2: Some data used but sources not clearly stated  
3: Multiple data points with clear attribution (e.g., OpView)

- Strategic Clarity  
Definition: Are the marketing recommendations grounded in a clear strategic framework and audience segmentation?  
1: Vague suggestions with no phased strategy or segmentation  
2: Basic strategy framework but lacks clear audience targeting  
3: Well-structured short/medium/long-term plans with audience-specific tactics

- Creativity  
Definition: Does the content demonstrate originality, insightful angles, or effective metaphors?  
1: Plain, cliché, or similar to others  
2: Occasional creative ideas or expressions  
3: Multiple perspectives, strong metaphors, or impressive originality

- Localization  
Definition: Is the content tailored to Taiwan's market context (culture, language, habits, seasonal relevance)?  
1: Globalized recommendations with no local relevance  
2: Some local insights but superficial  
3: Deep integration of Taiwanese cultural context, language, and calendar relevance

- Sustainability  
Definition: Does the content incorporate ESG (Environmental, Social, Governance) considerations?  
1: No mention of sustainability  
2: Mentions basics like eco-packaging  
3: Systematically includes ESG: social impact, supply chain, brand responsibility

- Competitor Relevance  
Definition: Are appropriate competitors identified and analyzed?  
1: Irrelevant or incorrect competitors  
2: Correct competitors but limited analysis  
3: Accurate selection and detailed comparison across multiple competitors

- Output Efficiency  
Definition: Was the AI output generated within a reasonable time based on internal benchmarks?  
1: Over 3 minutes  
2: Around 1–2 minutes, acceptable  
3: Under 1 minute with no quality compromise

- Actionability  
Definition: Are the recommendations specific, feasible, and measurable?  
1: Vague with no clear actions  
2: Some actionable points but lack of details or KPIs  
3: Clear action steps with measurable indicators

- Timeliness  
Definition: Are the references current, credible, and aligned with Taiwan's present-day context?  
1: Outdated sources, controversial figures, or obsolete events  
2: Data older than 12 months but still somewhat relevant  
3: Updated within the last 12 months, no major controversies

- Few-shot Generalization  
Definition: How well does the few-shot prompt generalize to different inputs or cases?  
1: Does not apply at all  
2: Partially applicable but needs supplementing  
3: Fully applicable and effectively generalizable
""".strip()


import json, re, html
from typing import Any, Dict

_JSON_BLOCK = re.compile(r'```json\s*([\s\S]+?)\s*```', re.I)
_CURLY_BLOCK = re.compile(r'\{[\s\S]+\}')

def extract_first_json(text: str) -> str:
    """從文字中抓出第一段 JSON 區塊。若找不到就 raise ValueError。"""
    text = html.unescape(text)
    if m := _JSON_BLOCK.search(text):
        return m.group(1)
    if m := _CURLY_BLOCK.search(text):
        return m.group(0)
    raise ValueError("❌ 找不到 JSON 區段")

def sanitize_json(raw: str) -> str:
    """最基本的清理：逗號、中文引號、BOM，並把字串中的裸換行替換掉。"""
    s = raw.lstrip("\ufeff")
    s = re.sub(r",\s*([\]}])", r"\1", s)  # 去掉 ,  }  或 , ]
    s = s.translate(str.maketrans("“”‘’", '""\'\''))  # 中文引號 → 英文

    # 只在 "字串常量" 內把裸 \n / \r 換成空格，避免 json.loads 爆
    def _fix_str(m):
        return m.group(0).replace("\n", " ").replace("\r", " ")
    s = re.sub(r'"(?:\\.|[^"\\])*"', _fix_str, s)

    return s

def parse_json_from_text(text: str) -> Dict[str, Any]:
    """
    1. 優先偵測 Claude Messages API 的包裝格式，抓出 content[].text
    2. 然後依舊流程：
          extract_first_json()  →  sanitize_json()  →  json.loads()
    過程若失敗，一律拋出帶有問題片段的 ValueError，方便 CloudWatch 追蹤。
    """
    # ------------------------------------------------------------------
    # A. 嘗試「外層解包」── Claude v3 Messages API 回傳的 JSON 物件
    # ------------------------------------------------------------------
    try:
        outer = json.loads(text)
        # Claude 會回 {id, role, content:[{type:'text',text:'```json ...```'}], ...}
        if isinstance(outer, dict) and "content" in outer:
            for blk in outer["content"]:
                if blk.get("type") == "text":
                    text = blk["text"]  # 只取真正的文字區塊
                    break  # 找到就退出
    except json.JSONDecodeError:
        # text 不是 JSON 包（舊情況），直接進入原本流程
        pass

    # ------------------------------------------------------------------
    # B. 舊流程：抽出 ```json ...``` 或裸 { ... } 區塊，再清理 / 解析
    # ------------------------------------------------------------------
    try:
        raw = extract_first_json(text)
    except ValueError as e:
        raise ValueError(f"{e}\n—— Raw head ——\n{text[:300]}") from e

    cleaned = sanitize_json(raw).strip()
    if not cleaned:
        raise ValueError(f"抽出的 JSON 為空。\n—— Raw head ——\n{text[:300]}")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as jde:
        snippet = cleaned[max(jde.pos - 60, 0): jde.pos + 60]
        raise ValueError(
            f"JSON 解析失敗: {jde}\n—— Problem Snippet ——\n{snippet}"
        ) from jde
    

def combine_html_from_json(parsed: Dict[str, str]) -> str:
    """
    將 {subtopic: html_fragment} 合併為單一 <div>，方便前端渲染。
    🆕 支持大標題和子標題的層級結構
    """
    if not parsed:
        return "<p>No analysis data available.</p>"

    # 🆕 添加基本樣式
    style = """
    <style>
    .market-analysis-report h1 {
        color: #2c3e50;
        border-bottom: 3px solid #3498db;
        padding-bottom: 10px;
        margin-bottom: 30px;
        font-size: 2.2em;
        text-align: center;
    }
    .market-analysis-report h2 {
        color: #34495e;
        border-left: 4px solid #3498db;
        padding-left: 15px;
        margin-top: 30px;
        margin-bottom: 20px;
        font-size: 1.6em;
        background: #f8f9fa;
        padding: 15px;
        border-radius: 5px;
    }
    .market-analysis-report h3 {
        color: #2c3e50;
        margin-top: 20px;
        margin-bottom: 15px;
        font-size: 1.3em;
        border-bottom: 1px solid #ddd;
        padding-bottom: 5px;
    }
    </style>
    """

    parts = [style, '<div class="market-analysis-report">']
    
    # 🆕 按 key 排序以確保正確順序（大標題、子標題、內容）
    sorted_items = sorted(parsed.items())
    
    for key, fragment in sorted_items:
        if fragment:
            parts.append(f'<div class="report-section">{fragment}</div>')
    
    parts.append("</div>")
    return "\n".join(parts)


def to_roman(n: int) -> str:
    table = [(1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'),
             (100, 'c'), (90, 'xc'), (50, 'l'), (40, 'xl'),
             (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i')]
    res = ''
    for val, sym in table:
        while n >= val:
            res += sym
            n -= val
    return res

def get_heading_prefix(level: int, index: int) -> str:
    """回傳不同層級對應的標題前綴：1., a., i."""
    if level == 1:
        return f"{index + 1}."
    elif level == 2:
        return f"{chr(97 + index)}."
    elif level == 3:
        return f"{to_roman(index + 1)}."
    else:
        return "-"
    
def extract_text_from_html(html_content: str) -> str:
    """
    從HTML內容中提取純文字，去除標籤
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        return soup.get_text(separator=' ', strip=True)
    except ImportError:
        # 如果沒有 BeautifulSoup，使用簡單的正則表達式
        import re
        clean_text = re.sub(r'<[^>]+>', '', html_content)
        return ' '.join(clean_text.split())