import streamlit as st
import secrets
from datetime import datetime, timezone, timedelta

# -----------------------------
# Configuration Constants
# -----------------------------

output_format = {
  "市場概況與趨勢": {
    "title": "市場概況與趨勢",
    "subtopics": [
      {
        "title": "產業規模與成長",
        "subsubtopics": [
          "台灣市場規模與成長",
          "產品類型演進",
          "年度銷售變化",
          "驅動因素與未來展望"
        ]
      },
      {
        "title": "主導品牌分析",
        "subsubtopics": [
          "主導品牌銷售概況",
          "價格帶分析",
          "平價帶市場概況",
          "高價帶市場概況",
          "價格帶結構與策略定位",
          "價格帶市佔變化趨勢"
        ]
      },
      # {
      #   "title": "消費者痛點與聲量",
      #   "subsubtopics": [
      #     "痛點分析",
      #     "正面熱點事件",
      #     "負面熱點事件",
      #     "聲量與情緒趨勢",
      #     "痛點轉化機會"
      #   ]
      # },
      # {
      #   "title": "未來政策與永續趨勢",
      #   "subsubtopics": [
      #     "國際政策動向",
      #     "台灣政策動向",
      #     "ESG 與永續議題"
      #   ]
      # },
      # {
      #   "title": "市場概況與趨勢總結",
      #   "subsubtopics": [
      #       "市場概況總結",
      #       "Why 為何是這些變化重要",
      #       "How 品牌該如何應對市場變化"
      #   ]
      # }
    ]
  },
  "品牌定位與形象": {
    "title": "品牌定位與形象",
    "subtopics": [
      {
        "title": "品牌價格與功能定位",
        "subsubtopics": []
      },
      {
        "title": "品牌形象",
        "subsubtopics": []
      },
      {
        "title": "獨特銷售主張（USP）",
        "subsubtopics": []
      }
    ]
  },
  "產品分析": {
    "title": "產品分析",
    "subtopics": [
      {
        "title": "熱銷產品銷量",
        "subsubtopics": []
      },
      {
        "title": "主打銷售通路",
        "subsubtopics": []
      },
      {
        "title": "目標族群與使用情境",
        "subsubtopics": []
      },
      {
        "title": "產品獨特銷售主張",
        "subsubtopics": []
      }
    ]
  },
  "消費者行為與洞察": {
    "title": "消費者行為與洞察",
    "subtopics": [
      {
        "title": "顧客輪廓",
        "subsubtopics": [
          "人口屬性",
          "生活型態",
          "消費力與行為"
        ]
      },
      {
        "title": "購買動機",
        "subsubtopics": []
      },
      {
        "title": "廣告投放策略",
        "subsubtopics": [
          "線上投放策略",
          "線下場域策略"
        ]
      },
      {
        "title": "Persona",
        "subsubtopics": []
      }
    ]
  },
  "競品分析": {
    "title": "競品分析",
    "subtopics": [
      {
        "title": "功能對比",
        "subsubtopics": []
      },
      {
        "title": "通路對比",
        "subsubtopics": []
      },
      {
        "title": "受眾與使用情境差異",
        "subsubtopics": []
      },
      {
        "title": "競品獨特銷售主張",
        "subsubtopics": []
      },
      {
        "title": "產品優劣點",
        "subsubtopics": []
      }
    ]
  },
  "結論與建議": {
    "title": "結論與建議",
    "subtopics": [
      {
        "title": "產品賣點",
        "subsubtopics": []
      },
      {
        "title": "行銷策略",
        "subsubtopics": []
      }
    ]
  }
}


CHATBOT_FLOW = [key for key in output_format.keys()]

TOPIC_HINTS = {
    "市場概況與趨勢": "概覽市場規模、成長潛力與最新動態。",
    "品牌定位與形象": "分析品牌在市場中的角色、優勢與定位策略。",
    "產品分析": "比較熱銷產品的特色、價格帶、銷售通路與 USP。",
    "消費者行為與洞察": "描繪目標族群的行為模式、需求痛點與社群情緒趨勢。",
    "競品分析": "對照主要競品的功能、價格、通路與獨特賣點。",
    "結論與建議": "提出行銷賣點、產品優勢與線上／線下策略建議。"
}

# 合併成結構化格式
combined_output = []

for topic, description in TOPIC_HINTS.items():
    subtopics = output_format.get(topic, [])
    combined_output.append({
        "section_title": topic,
        "section_description": description,
        "subtopics": subtopics
    })

# Example: 輸出為清單或寫入 JSON、Markdown 等
for section in combined_output:
    print(f"【{section['section_title']}】\n{section['section_description']}")
    for idx, sub in enumerate(section["subtopics"], 1):
        print(f"  {idx}. {sub}")
    print()

COMPANY_FIELDS = [
    "企業名稱",
    "品牌名稱",
    # "品牌所屬產業",
    "商品名稱",
    # "分析年月區間",
    "商品類型",
    "補充資訊"
]

INDUSTRY_OPTION = [
    "A大類 - 農、林、漁、牧業",
    "B大類 - 礦業及土石採取業",
    "C大類 - 製造業",
    "D大類 - 電力及燃氣供應業",
    "E大類 - 用水供應及污染整治業",
    "F大類 - 營建工程業",
    "G大類 - 批發及零售業",
    "H大類 - 運輸及倉儲業",
    "I大類 - 住宿及餐飲業",
    "J大類 - 出版影音及資通訊業",
    "K大類 - 金融及保險業",
    "L大類 - 不動產業",
    "M大類 - 專業、科學及技術服務業",
    "N大類 - 支援服務業",
    "O大類 - 公共行政及國防；強制性社會安全",
    "P大類 - 教育業",
    "Q大類 - 醫療保健及社會工作服務業",
    "R大類 - 藝術、娛樂及休閒服務業",
    "S大類 - 其他服務業"
]

EXPORT_FORMATS = ["docx"]  #[, "pdf", "ppt"]


def header():
    st.set_page_config(page_title="產業分析助手", page_icon="unknown/logo.png",
                       layout="wide", initial_sidebar_state="collapsed")

    # ===== 全域 CSS，一次就好 =====
    st.markdown("""
    <style>
    html,body{font-family:"Noto Sans TC","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
              background:#f9fafb;color:#334155;}
    h1,h2,h3{color:#1f2937;font-weight:700;margin:0.5rem 0 0.75rem;}
    .card{background:#fff;border-radius:16px;box-shadow:0 2px 8px rgba(0,0,0,.04);
          padding:1.25rem 1.5rem;}
    .chat-box{max-height:500px;overflow-y:auto;}
    .element-container{margin:0!important;}          /* 消掉外框空隙 */
    hr{border:none;border-top:1px solid #e5e7eb;margin:1.5rem 0;}
    </style>
    """, unsafe_allow_html=True)

    # logo + 標題
    col_logo, col_title = st.columns([1,6])
    with col_logo:
        st.image("unknown/logo.png", width=80, output_format="PNG")
    with col_title:
        st.markdown("""
        <h1>產業分析對話機器人</h1>
        <p style="font-size:1.05rem;">歡迎使用產業分析對話機器人。請依照系統指示逐步輸入相關資訊，我們將協助您深入探索產業趨勢，並自動產出可供下載的分析報告。</p>
        <p style="font-size:1.05rem;">若您於使用過程中有任何疑問或需要協助，請隨時聯繫數據分析團隊：<a href="mailto:jiao@clickforce.com.tw">jiao@clickforce.com.tw</a>。</p>
        <p style="font-size:1.05rem;"><strong>立即開始，掌握關鍵洞察，提升決策效率！</strong></p>
        <p style="font-size:0.95rem; color:gray;">系統維護者：Jiao</p>
        """, unsafe_allow_html=True)
    st.markdown("<hr/>", unsafe_allow_html=True)



def show_footer():
    st.markdown(
        """
        <hr style="border: none; border-top: 1px solid #e0e0e0; margin-top: 2rem;">
        <div style="text-align: center; font-size: 0.9rem; color: #888;">
            ⓒ 2025 ClickForce Inc. All rights reserved.
        </div>
        """,
        unsafe_allow_html=True
    )


def build_validated_payload_invoke(query, session_id, topic, company_info):
    """
    驗證參數並構建發送至 Lambda 的 payload。
    
    Args:
        query (str): 使用者輸入問題（可為空）
        session_id (str): UUID 字串，會話 ID
        topic (str): 分析主題名稱
        company_info (dict): 公司資訊（字典格式）

    Returns:
        dict: 可直接發送至 Lambda 的 payload 格式

    Raises:
        ValueError: 任一欄位不符合格式時
    """
    if not session_id or not isinstance(session_id, str):
        raise ValueError("❌ session_id 無效，請確認已初始化")

    if not topic or not isinstance(topic, str):
        raise ValueError("❌ analysis_topic 無效，請提供正確主題")

    if not isinstance(company_info, dict) or not any(v.strip() for v in company_info.values() if isinstance(v, str)):
        raise ValueError("❌ 公司資訊 company_info 不完整或格式錯誤")

    if query is not None and not isinstance(query, str):
        raise ValueError("❌ query 必須為字串")

    if topic not in CHATBOT_FLOW:
        raise ValueError(f"❌ 無效的分析主題：{topic}")

    return {
        "body": {
            "query": query,
            "session_id": session_id,
            "session_attributes": {
                "analysis_topic": topic,
                "company_info": company_info,
            }
        }
    }


# 台北時區 (UTC+8)；如 AWS Lambda 已設定 Asia/Taipei 可省略
TZ_TAIPEI = timezone(timedelta(hours=8))

def new_session_id() -> str:
    """
    產生『YYYYMMDD-HHMMSS-xxxxxxxx』格式：
    - 前綴為台北時間
    - 後綴 8 位 十六進位亂數（32 bits）
    """
    ts = datetime.now(TZ_TAIPEI).strftime("%Y%m%d-%H%M%S")
    rand = secrets.token_hex(4)  # 8 hex chars
    return f"{ts}-{rand}"