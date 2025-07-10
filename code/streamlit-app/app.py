import logging
import json
import time
import base64
import datetime
from datetime import date
import re
from bs4 import BeautifulSoup
import html
from typing import Tuple, List, Dict, Any
import concurrent.futures
import streamlit as st
import streamlit.components.v1 as components
from utils import (
    new_session_id,
    header,
    show_footer,
    build_validated_payload_invoke,
    CHATBOT_FLOW,
    TOPIC_HINTS,
    COMPANY_FIELDS,
    EXPORT_FORMATS,
    INDUSTRY_OPTION,
    output_format
)
from connections import Connections
# from streamlit_autorefresh import st_autorefresh
# KEEPALIVE_MS = 55_000 # 55 秒一次，低於 ALB/Streamlit 閒置門檻

logger = logging.getLogger()
logger.setLevel(logging.INFO)
lambda_client = Connections.lambda_client

# -----------------------------
# Helper Functions
# -----------------------------
# ---------------- JSON → HTML 卡片 ---------------- #
_JSON_FENCE = re.compile(r"```json\s*([\s\S]+?)\s*```", re.I)  # ```json ... ```
_JSON_RAW = re.compile(r"\bjson[\s\r\n]+(\{[\s\S]+)", re.I)  #  json\n{ ... }
_CURLY = re.compile(r"\{[\s\S]+?\}", re.S)  # 最後保險：{ ... }

def _json_block_to_html(text: str) -> str | None:
    """
    - 若 content 本身就是純 HTML，就直接包裝並返回
    - 否則嘗試從 ```json ...``` 或裸 JSON 區域解析
    """
    if text.lstrip().startswith("<"):
        return f'<div class="market-analysis-report"><div class="report-section">{text}</div></div>'

    # ---------- 以下同舊版 ----------
    m = _JSON_FENCE.search(text) or _JSON_RAW.search(text) or _CURLY.search(text)
    if not m:
        return None
    raw = m.group(1) if m.re is not _CURLY else m.group(0)

    cleaned = (
        raw.lstrip("\ufeff")
           .replace(""", '"').replace(""", '"')
           .replace("'", "'").replace("'", "'")
    )
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    def _strip_nl(mo: re.Match) -> str:
        c = mo.group(0)
        return c if any(k in c for k in ("chart-container", "plotly", "script")) else c.replace("\n", " ")

    cleaned = re.sub(r'"(?:\\.|[^"\\])*"', _strip_nl, cleaned)

    try:
        obj = json.loads(cleaned)
        if not isinstance(obj, dict):
            return None
    except Exception:
        return None

    parts = ['<div class="market-analysis-report">']
    for frag in obj.values():
        parts.append(f'<div class="report-section">{frag}</div>')
    parts.append("</div>")
    return "\n".join(parts)


_ALLOWED_TAGS = ("b", "small", "em", "strong", "pre", "ul", "li", "h2", "h4", "a")

def _safe_markdown(text: str) -> str:
    """
    把使用者或系統文字轉 markdown-safe html：
      • escape 全部標籤
      • 再放行 _ALLOWED_TAGS
      • 將換行轉 <br>
    """
    escaped = html.escape(text, quote=False)
    tag_pattern = "|".join(_ALLOWED_TAGS)
    unescape_re = re.compile(rf"&lt;(/?(?:{tag_pattern}))&gt;", re.I)
    restored = unescape_re.sub(r"<\1>", escaped)
    return restored.replace("\n", "<br>")

def get_response(user_input, session_id, selected_topic):
    """
    - 保存完整的 Lambda 回應數據
    - 穩定的6分鐘長時間處理用戶體驗
    - 10分鐘超時保護
    """
    try:
        topic_hint = TOPIC_HINTS.get(selected_topic, "").strip()

        # 最終組合為一段文字
        combined_q = f"""{topic_hint}{user_input}""".strip()

        # 準備請求 payload
        payload = build_validated_payload_invoke(
            combined_q, session_id, selected_topic, st.session_state.company_info
        )

        # 創建進度顯示區域
        progress_container = st.container()
        with progress_container:
            status_placeholder = st.empty()
            progress_bar = st.progress(0)
            time_placeholder = st.empty()
            
        # 定義6分鐘進度階段 (時間秒數, 進度百分比, 狀態訊息)
        progress_stages = [
            (0, 0.05, "🚀 AI助理開始啟動..."),
            (5, 0.10, "🔍 AI助理開始上網搜尋..."),
            (30, 0.25, "🗄️ AI助理正在查找資料庫..."),
            (90, 0.45, "📊 AI助理正在製作數據表格..."),
            (180, 0.65, "🔄 AI助理正在統整資料中，請稍等..."),
            (270, 0.80, "📝 AI助理正在生成報告內容..."),
            (330, 0.90, "🎨 AI助理正在優化報告格式..."),
            (360, 0.95, "✨ AI助理正在進行最後檢查..."),
            (480, 0.98, "⏳ 處理複雜分析中，請耐心等候..."),
            (570, 0.99, "系統正在進行最終整合...")
        ]
        
        # Lambda 調用函數
        def invoke_lambda():
            """執行實際的 Lambda 調用"""
            logger.info("開始 Lambda 調用...")
            invoke_start_time = time.time()
            
            response = lambda_client.invoke(
                FunctionName=Connections.lambda_function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
            )
            
            invoke_end_time = time.time()
            actual_lambda_time = invoke_end_time - invoke_start_time
            logger.info(f"Lambda 調用完成，實際耗時: {actual_lambda_time:.2f} 秒")
            
            return response, actual_lambda_time
        
        # 穩定進度更新函數
        def update_progress_smoothly(future, start_time):
            """平滑的進度更新函數，確保穩定的時間間隔，支持10分鐘超時"""
            current_stage = 0
            last_update_time = start_time
            update_interval = 1.0  # 固定每1秒更新一次
            timeout_seconds = 600  # 10分鐘超時
            
            # 初始顯示
            status_placeholder.info(progress_stages[0][2])
            progress_bar.progress(progress_stages[0][1])
            time_placeholder.caption("⏱️ 開始處理...")
            
            while not future.done():
                current_time = time.time()
                elapsed_time = current_time - start_time
                
                # 檢查是否超過10分鐘
                if elapsed_time >= timeout_seconds:
                    status_placeholder.error("⏰ 處理超時 - 系統問題")
                    progress_bar.empty()
                    time_placeholder.error(
                        "❌ 處理時間超過10分鐘，系統發生問題\n"
                        "請聯絡工程師：jiao@clickforce.com.tw"
                    )
                    logger.error(f"Lambda 調用超時: {elapsed_time:.2f} 秒")
                    return  # 結束進度更新
                
                # 只有在達到更新間隔時才更新顯示
                if current_time - last_update_time >= update_interval:
                    # 檢查是否需要進入下一階段
                    while (current_stage < len(progress_stages) - 1 and 
                           elapsed_time >= progress_stages[current_stage + 1][0]):
                        current_stage += 1
                    
                    # 獲取當前階段信息
                    current_stage_time, progress_value, message = progress_stages[current_stage]
                    
                    # 如果還沒到下一階段，計算當前階段內的線性進度
                    if current_stage < len(progress_stages) - 1:
                        next_stage_time, next_progress_value, _ = progress_stages[current_stage + 1]
                        stage_duration = next_stage_time - current_stage_time
                        stage_elapsed = elapsed_time - current_stage_time
                        
                        if stage_duration > 0:
                            # 在當前階段內線性插值
                            stage_progress = min(1.0, stage_elapsed / stage_duration)
                            smooth_progress = progress_value + (next_progress_value - progress_value) * stage_progress
                        else:
                            smooth_progress = progress_value
                    else:
                        # 最後階段，逐漸接近99%，但不超過
                        smooth_progress = min(0.99, progress_value + (elapsed_time - current_stage_time) * 0.0005)
                    
                    # 更新顯示
                    status_placeholder.info(message)
                    progress_bar.progress(smooth_progress)
                    
                    # 計算並顯示時間信息
                    minutes = int(elapsed_time // 60)
                    seconds = int(elapsed_time % 60)
                    
                    # 根據時間顯示不同的提示信息
                    if elapsed_time < 360:  # 前6分鐘
                        if current_stage <= 1:  # 前30秒
                            expected_range = "預計剩餘5-7分鐘"
                        elif current_stage <= 2:  # 30秒-90秒
                            expected_range = "預計剩餘4-6分鐘"
                        elif current_stage <= 3:  # 90秒-180秒
                            expected_range = "預計剩餘3-5分鐘"
                        elif current_stage <= 4:  # 180秒-270秒
                            expected_range = "預計剩餘2-4分鐘"
                        elif current_stage <= 5:  # 270秒-330秒
                            expected_range = "預計剩餘1-2分鐘"
                        else:  # 330秒以上
                            expected_range = "即將完成"
                        
                        time_placeholder.caption(
                            f"⏱️ 已處理: {minutes}分{seconds:02d}秒 | {expected_range}"
                        )
                    elif elapsed_time < 480:  # 6-8分鐘
                        time_placeholder.caption(
                            f"⏱️ 已處理: {minutes}分{seconds:02d}秒 | 正在處理複雜分析，請耐心等候"
                        )
                    elif elapsed_time < 540:  # 8-9分鐘
                        time_placeholder.warning(
                            f"⏱️ 已處理: {minutes}分{seconds:02d}秒 | 處理時間較長，系統正在努力完成"
                        )
                    else:  # 9-10分鐘
                        remaining_seconds = timeout_seconds - elapsed_time
                        time_placeholder.error(
                            f"⏱️ 已處理: {minutes}分{seconds:02d}秒 | "
                            f"⚠️ 將在 {int(remaining_seconds)} 秒後超時"
                        )
                    
                    last_update_time = current_time
                
                # 短暫休眠，減少CPU使用率
                time.sleep(0.1)
        
        # 使用線程池執行 Lambda 調用，同時更新進度
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # 提交 Lambda 任務
            future = executor.submit(invoke_lambda)
            start_time = time.time()
            
            # 開始穩定的進度更新
            try:
                update_progress_smoothly(future, start_time)
            except Exception as progress_error:
                logger.warning(f"進度更新異常: {progress_error}")
                # 即使進度更新失敗，也要等待 Lambda 完成
                pass
            
            # 獲取 Lambda 結果，設置10分鐘超時
            try:
                response, actual_lambda_time = future.result(timeout=600)  # 10分鐘 = 600秒
            except concurrent.futures.TimeoutError:
                # 清理進度顯示
                status_placeholder.error("⏰ 系統超時錯誤")
                progress_bar.empty()
                time_placeholder.empty()
                
                # 顯示詳細的超時錯誤訊息
                st.error(
                    "❌ **系統處理超時**\n\n"
                    "處理時間超過10分鐘限制，這通常表示系統遇到了技術問題。\n\n"
                    "**請嘗試以下步驟：**\n"
                    "1. 稍後再試\n"
                    "2. 簡化您的問題內容\n"
                    "3. 如問題持續發生，請聯絡技術支援\n\n"
                    "**技術支援信箱：** jiao@clickforce.com.tw\n"
                    "**請在信件中包含：** 發生時間、使用的功能、具體問題描述"
                )
                
                logger.error("Lambda 調用超時: 超過600秒")
                return {"answer": "系統處理超時，請稍後再試或聯絡技術支援。", "source": ""}
        
        # ======== 檢查是否因為超時而沒有獲得結果 ========
        total_time = time.time() - start_time
        if total_time >= 590:  # 接近10分鐘時顯示警告
            logger.warning(f"處理時間接近極限: {total_time:.2f} 秒")
            st.warning("⚠️ 處理時間較長，建議下次簡化問題內容以獲得更快的回應")
        
        # 處理完成
        status_placeholder.success("✅ 分析完成！")
        progress_bar.progress(1.0)
        
        # 顯示詳細時間統計
        final_minutes = int(total_time // 60)
        final_seconds = int(total_time % 60)
        time_placeholder.success(
            f"🎉 總耗時: {final_minutes}分{final_seconds:02d}秒 | "
            f"實際處理: {actual_lambda_time:.1f}秒"
        )
        
        # 短暫顯示完成狀態，然後清除進度顯示
        time.sleep(2)
        status_placeholder.empty()
        progress_bar.empty()
        time_placeholder.empty()
        
        # 處理 Lambda 響應
        try:
            response_output = json.loads(response["Payload"].read().decode("utf-8"))
            
            # 保存完整的 Lambda 響應數據
            st.session_state.last_lambda_response = response_output
            
            # 支持嵌套和平坦兩種結構
            charts_data = None
            if "word_export_data" in response_output:
                # 新版嵌套結構
                charts_data = response_output.get("word_export_data", {}).get("charts_data", {})
            elif "charts_data" in response_output:
                # 舊版平坦結構（向後兼容）
                charts_data = response_output.get("charts_data", {})
            
            if charts_data:
                st.session_state.setdefault("chart_metadata", {})
                # charts_data = {page_name: [ {chart_id, title_text, ...}, ... ] }
                st.session_state.chart_metadata[selected_topic] = charts_data
                logger.info(f"✅ 保存 {selected_topic} 圖表資訊: {sum(len(v) for v in charts_data.values())} 張")
            else:
                logger.info(f"⚠️ {selected_topic} 無圖表數據")
                
        except json.JSONDecodeError as json_err:
            logger.error(f"JSON 解析錯誤: {json_err}")
            st.error("🚫 回應格式錯誤，請聯繫系統管理員")
            return {"answer": "回應格式錯誤，請重新嘗試。", "source": ""}
        
        logger.info(f"Lambda 處理完畢，總耗時: {total_time:.2f} 秒，實際處理: {actual_lambda_time:.2f} 秒")
        
        # 檢查回應品質並提供用戶提示
        answer = response_output.get("answer", "無回應")
        source = response_output.get("source", "")
        
        if not answer or answer == "無回應":
            st.warning("⚠️ AI 回應內容為空，請重新嘗試或調整問題")
        elif len(answer) < 50:
            st.info("💡 回應內容較短，您可以進一步詢問更多細節")
        else:
            # 成功回應，顯示滿意度調查
            with st.expander("📝 這次分析對您有幫助嗎？", expanded=False):
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("👍 很滿意", key=f"satisfied_{session_id}_{int(time.time())}"):
                        st.success("感謝您的反饋！")
                with col2:
                    if st.button("😐 還可以", key=f"neutral_{session_id}_{int(time.time())}"):
                        st.info("我們會持續改進！")
                with col3:
                    if st.button("👎 不滿意", key=f"unsatisfied_{session_id}_{int(time.time())}"):
                        st.warning("抱歉沒有達到您的期望，請嘗試調整問題或聯繫客服。")
            
        return {
            "answer": answer,
            "source": source,
            "processing_time": total_time,
            "actual_lambda_time": actual_lambda_time
        }
        
    except Exception as e:
        # 清理進度顯示
        if 'status_placeholder' in locals():
            status_placeholder.error(f"❌ 處理失敗: 系統發生錯誤")
        if 'progress_bar' in locals():
            progress_bar.empty()
        if 'time_placeholder' in locals():
            time_placeholder.empty()
            
        logger.error(f"Lambda 錯誤: {e}")
        
        # 根據錯誤類型提供不同的用戶提示
        error_msg = str(e).lower()
        if "timeout" in error_msg or "time" in error_msg:
            st.error(
                "⏰ **請求超時**\n\n"
                "系統處理時間過長，請稍後再試或簡化您的問題。\n\n"
                "如問題持續發生，請聯絡技術支援：jiao@clickforce.com.tw"
            )
            user_msg = "系統處理超時，請稍後再試。"
        elif "connection" in error_msg or "network" in error_msg:
            st.error(
                "🌐 **網路連接問題**\n\n"
                "請檢查網路狀態後重試。\n\n"
                "如問題持續發生，請聯絡技術支援：jiao@clickforce.com.tw"
            )
            user_msg = "網路連接異常，請檢查網路狀態後重試。"
        elif "rate" in error_msg or "limit" in error_msg:
            st.error(
                "🚦 **請求頻率過高**\n\n"
                "系統忙碌中，請稍等片刻再試。\n\n"
                "如問題持續發生，請聯絡技術支援：jiao@clickforce.com.tw"
            )
            user_msg = "系統忙碌中，請稍等片刻再試。"
        else:
            st.error(
                "❌ **系統發生未知錯誤**\n\n"
                "請稍後再試，如問題持續發生，請聯絡技術支援。\n\n"
                "**技術支援信箱：** jiao@clickforce.com.tw\n"
                "**請在信件中包含：** 發生時間、使用的功能、具體錯誤訊息"
            )
            user_msg = "系統錯誤，請稍後再試。"
            
        return {"answer": user_msg, "source": ""}


def convert_html_to_word_format(html_content: str, topic: str) -> Tuple[str, List[Dict]]:
    """
    將富含 <script> 的 HTML 變成 Word 友善格式：
    1. 把 plotly 內嵌 script → [WORD_CHART_ID] 占位符
    2. 回傳每張圖的 meta（含 base-64）給後端
    """
    logger.info(f"🔄 HTML ➜ Word 轉換中… topic={topic}")

    soup = BeautifulSoup(html_content, "html.parser")
    section_map = {idx: hdr.get_text(strip=True)  # 章節索引 → 標題
                   for idx, hdr in enumerate(soup.find_all(["h2", "h3"]))}

    chart_re = re.compile(
        r'<script>\(function\(\).*?getElementById\("(?P<ph>plotly-placeholder-[^"]+)"\).*?`(?P<html>[^`]+)`.*?</script>',
        re.S
    )

    last_resp = st.session_state.get("last_lambda_response", {})
    charts_data = last_resp.get("word_export_data", {}).get("charts_data", {})

    extracted, new_html = [], html_content

    for m in chart_re.finditer(html_content):
        placeholder_id = m.group("ph")  # plotly-placeholder-xxxx
        chart_id = placeholder_id.replace("plotly-placeholder-", "")

        # 找章節
        chart_pos, section_name = m.start(), "未知章節"
        for idx, title in section_map.items():
            hdr_html = str(list(soup.find_all(["h2", "h3"]))[idx])
            if html_content.find(hdr_html) < chart_pos:
                section_name = re.sub(r"^\d+\.\d*\s*", "", title)  # 去前綴
            else:
                break

        # 找圖表 meta
        chart_meta = next(
            (c for plist in charts_data.values() for c in plist if c.get("chart_id") == chart_id),
            None
        )
        if not chart_meta:
            logger.warning(f"⚠️ 找不到 {chart_id} 的 meta，跳過")
            continue

        # 若還沒有 img_static_b64，用 img_html_b64 補上
        img_b64 = chart_meta.get("img_static_b64") or chart_meta.get("img_html_b64")
        chart_meta["img_static_b64"] = img_b64

        # 產生 Word 占位符
        word_tag = f"[WORD_CHART_{chart_id}]"
        new_html = new_html.replace(m.group(0), f'<div class="word-chart-placeholder">{word_tag}</div>')

        extracted.append({
            "chart_id" : chart_id,
            "placeholder" : word_tag,
            "title_text" : chart_meta.get("title_text", ""),
            "img_static_b64": img_b64,
            "target_section": section_name,
            "html_position": chart_pos,
        })

    logger.info(f"✅ 轉換完成：{len(extracted)} 張圖表已替換為占位符")
    return new_html, extracted


def initialization():
    defaults = {
        "session_id": "",
        "company_info": {field: "" for field in COMPANY_FIELDS},
        "flow_index": -1,
        "final_answers": {topic: [] for topic in CHATBOT_FLOW},
        "chat_inputs": {},
        "visited_pages": set(),  # 追蹤已訪問過的頁面
        "export_results": {},  # 用來存匯出結果
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

def auto_generate_if_needed(topic: str) -> None:
    """首次載入頁面時自動產生一筆內容。"""
    if st.session_state.final_answers.get(topic):
        return  # 已有內容

    # ==== 自動生成的 PROMPT ====
    prompt = f"我們好奇{topic}。"

    # 使用升級版的進度顯示
    resp = get_response(prompt, st.session_state.session_id, topic)
    assistant_html = build_assistant_html(resp)

    # 更新 state
    st.session_state.setdefault(f"chat_history_{topic}", []).extend(
        [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": assistant_html},
        ]
    )
    st.session_state.final_answers[topic] = [
        f"🧑‍💼 <b>：</b><br>{prompt}<br><br>🤖 <b>：</b><br>{assistant_html}"
    ]
    st.rerun()
    
def parse_date_or_default(date_str, default_date):
    if date_str and isinstance(date_str, str):
        try:
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return default_date
    elif isinstance(date_str, date):
        return date_str
    else:
        return default_date

def show_form():
    with st.container():
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("填寫基本資訊")
        with st.form("info_form"):
            errors = []
            for field in COMPANY_FIELDS:
                if field == "分析年月區間":
                    start_date, end_date = st.date_input(
                        "分析年月區間",
                        value=(
                            parse_date_or_default(st.session_state.company_info.get("分析開始日期"), date(2025, 4, 1)),
                            parse_date_or_default(st.session_state.company_info.get("分析結束日期"), date(2025, 4, 30))
                        )
                    )
                    st.session_state.company_info["分析開始日期"] = start_date.isoformat()
                    st.session_state.company_info["分析結束日期"] = end_date.isoformat()
                else:
                    value = st.text_input(field, value=st.session_state.company_info.get(field, ""))
                    st.session_state.company_info[field] = value
                    if field != "補充資訊" and not value.strip():
                        errors.append(field)

            submitted = st.form_submit_button(f"✅ 生成{CHATBOT_FLOW[0]}")

        if submitted:
            if errors:
                st.error(f"請填寫以下必填欄位：{', '.join(errors)}")
            else:
                if not st.session_state.session_id:
                    st.session_state.session_id = new_session_id()
                
                # 重置已訪問頁面記錄（每次從表單提交開始新的流程）
                st.session_state.visited_pages = set()
                
                st.session_state.flow_index = 0
                auto_generate_if_needed(CHATBOT_FLOW[0])

# =====================   Enhanced Chat Rendering   =====================
def _render_message(msg: dict) -> None:
    """增強版消息渲染，支持圖表和動態高度調整"""
    role, content = msg["role"], msg["content"]

    if role == "assistant":
        if (
            '<div class="market-analysis-report">' in content
            or '<div class="report-source">' in content
        ):
            # 檢測是否包含圖表來調整高度
            has_charts = 'chart-container' in content or 'plotly' in content.lower()
            chart_count = content.count('chart-container')
            
            # 動態計算高度
            base_height = 700
            if has_charts:
                # 每個圖表增加400px高度
                base_height += chart_count * 400
                
            # 確保最小和最大高度
            final_height = max(800, min(base_height, 2000))
            
            logger.info(f"渲染HTML，檢測到 {chart_count} 個圖表，設定高度為 {final_height}px")
            
            try:
                components.html(
                    content, 
                    height=final_height, 
                    scrolling=True
                )
                return
            except Exception as e:
                logger.error(f"HTML渲染失敗: {e}")
                # fallback to text display
                st.error("圖表渲染失敗，顯示原始內容")
                st.code(content[:1000] + "..." if len(content) > 1000 else content)
                return

    # fallback：markdown chat bubble
    avatar = "🤖" if role == "assistant" else "\U0001F464"
    st.chat_message(role, avatar=avatar).markdown(
        _safe_markdown(content), unsafe_allow_html=True
    )

def _append_history(topic: str, user: str, assistant_html: str):
    """追加到 chat_history 與 final_answers（後者仍可保留最新）。"""
    
    # 累加 chat_history（多輪）
    st.session_state.setdefault(f"chat_history_{topic}", [])
    st.session_state[f"chat_history_{topic}"].extend([
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant_html},
    ])

    # 仍僅保留最後一輪作為 final_answers（for export）
    block = (
        f"🧑‍💼 <b>：</b><br>{user}<br><br>"
        f"🤖 <b>：</b><br>{assistant_html}"
    )
    st.session_state.final_answers[topic] = [block]

# =====================   匯出 Lambda 呼叫   =====================
def _invoke_export_lambda(pages: list[str], fmt: str) -> None:
    topic = st.session_state.current_topic  # 由呼叫端先塞入
    progress_ph = st.empty()

    try:
        with progress_ph, st.spinner("📤 正在匯出報告，請稍候..."):
            t0 = time.time()
            payload, _ = _build_export_payload(pages, fmt)
            resp_json = _call_export_lambda(payload)
            decoded, meta = _parse_export_response(resp_json)
            cost = time.time() - t0
            _store_export_result(topic, decoded, meta, pages, cost)

        progress_ph.success("✅ 匯出完成！")
        _render_export_result(topic)

    except Exception as err:
        progress_ph.empty()
        logger.error(f"匯出失敗: {err}")
        st.error(f"❌ 匯出失敗：{err}")
        
def _build_export_payload(pages: list[str], fmt: str) -> Tuple[dict, str]:
    """把 img_html_b64 補進 img_static_b64，並帶上 charts_position_info"""
    if fmt.lower() not in {"docx", "word", "doc"}:
        raise ValueError(f"尚未支援 {fmt} 匯出格式")

    last_resp = st.session_state.get("last_lambda_response", {})
    word_data = last_resp.get("word_export_data", {})
    charts_data = word_data.get("charts_data", {})  # {page: [chart_dict, ...]}

    # ---------- 1. 組裝 analysis 內容並標記圖表實際位置 ----------
    analysis = {}
    charts_position_info = {}  # {page: [ {chart_id, ...} ]}

    for pg in pages:
        raw_block = st.session_state.final_answers.get(pg, [""])[-1]
        html_body = raw_block.split("🤖 <b>：</b><br>", 1)[-1]

        # 將 <script> 轉占位符，並回傳位置資訊
        if "[WORD_CHART_" in html_body:
            html_body, pos_info = convert_html_to_word_format(html_body, pg)
            charts_position_info[pg] = pos_info

        analysis[pg] = html_body

    # ---------- 2. 對齊 key：確保每張圖都帶 img_static_b64 ----------
    for page_charts in charts_data.values():
        for ch in page_charts:
            if not ch.get("img_static_b64") and ch.get("img_html_b64"):
                ch["img_static_b64"] = ch["img_html_b64"]  # ★ 關鍵 1 行

    # ---------- 3. 打包 Payload ----------
    payload = {
        "company_info" : st.session_state.company_info,
        "analysis" : analysis,
        "format" : fmt,
        "session_id" : st.session_state.session_id,
        "charts_data" : charts_data,  # 帶 base-64 後的版本
        "charts_position_info" : charts_position_info,  # 供後端定位插圖
        "export_type" : "docx",
    }
    return payload, "docx"

def _call_export_lambda(payload: dict) -> dict:
    """直接回傳 `response_json`（已是 dict）"""
    resp = lambda_client.invoke(
        FunctionName=Connections.export_lambda_function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({"body": json.dumps(payload, ensure_ascii=False)}).encode(),
    )

    if resp.get("StatusCode") != 200:
        raise RuntimeError(f"Lambda 回應異常，狀態碼: {resp.get('StatusCode')}")

    response_json = json.loads(resp["Payload"].read())
    if "errorMessage" in response_json:
        raise RuntimeError(f"伺服器處理錯誤: {response_json['errorMessage']}")
    return response_json

def _parse_export_response(response_json: dict) -> Tuple[bytes, dict]:
    """回傳 (decoded_bytes, meta)；meta 含 filename / mime_type / size_mb"""
    body = json.loads(response_json.get("body", "{}"))
    if "error" in body:
        raise RuntimeError(f"匯出失敗: {body['error']}")

    filedata, filename = body.get("filedata"), body.get("filename")
    if not filedata or not filename:
        raise RuntimeError("檔案生成失敗，請重試")

    filedata = filedata.strip()
    if len(filedata) % 4:
        filedata += "=" * (4 - len(filedata) % 4)
    decoded = base64.b64decode(filedata)
    if not decoded:
        raise RuntimeError("檔案資料為空")

    mime_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "txt": "text/plain",
        "html": "text/html",
    }
    ext = filename.lower().split(".")[-1]
    meta = dict(
        filename=filename,
        mime_type=mime_types.get(ext, "application/octet-stream"),
        size_mb=len(decoded) / 1024 / 1024,
    )
    return decoded, meta

def _store_export_result(topic: str, decoded: bytes, meta: dict, pages: list[str], cost: float):
    st.session_state["export_results"][topic] = {
        "file_bytes": decoded,
        "filename": meta["filename"],
        "mime_type": meta["mime_type"],
        "size_mb": meta["size_mb"],
        "pages": pages,
        "process_time": cost,
    }

def _render_export_result(topic: str):
    data = st.session_state.get("export_results", {}).get(topic)
    if not data:
        return

    with st.container():
        st.success("🎉 檔案匯出成功！")

        # 主要下載連結 (不觸發 rerun)
        data_url = f"data:{data['mime_type']};base64,{base64.b64encode(data['file_bytes']).decode()}"
        st.markdown(
            f"""
            <a href="{data_url}" download="{data['filename']}" target="_blank">
                下載報告
            </a>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("🔧 下載問題？點這裡獲取更多選項"):
            st.write("請聯絡以下信箱： jiao@clickforce.com.tw")

        with st.expander("📊 檔案詳細資訊"):
            st.write(dict(
                檔案名稱=data['filename'],
                檔案大小=f"{data['size_mb']:.2f} MB",
                處理時間=f"{data['process_time']:.2f} 秒",
                MIME=data['mime_type'],
                包含頁面=", ".join(data['pages']),
            ))

# =====================   尾端控制區   =====================
def _render_next_controls(topic: str):
    """修改後的控制區域，僅第一頁強制產出"""

    # ---------- 1. 首頁仍需先產出 ----------
    if topic == CHATBOT_FLOW[0]:
        if topic not in st.session_state.get("visited_pages", set()):
            st.warning("⚠️ 請先完成此頁產出後再進行下一步。")
            return

        next_idx = CHATBOT_FLOW.index(topic) + 1
        if next_idx < len(CHATBOT_FLOW):
            nxt = CHATBOT_FLOW[next_idx]
            if st.button(f"⏭️ 下一步：生成 {nxt}", key=f"next_{topic}"):
                st.session_state.flow_index = next_idx
                st.rerun()

    # ---------- 2. 其餘頁面 ----------
    _render_export_result(topic)

    col_left, col_right = st.columns([1, 2])

    # ===== 匯出 =====
    with col_left:
        if st.button("🚀 送出與下載", key=f"dl_{topic}"):
            st.session_state[f"show_download_options_{topic}"] = True

        if st.session_state.get(f"show_download_options_{topic}", False):
            visited = sorted(st.session_state.visited_pages)
            if not visited:
                st.warning("⚠️ 尚未產生任何頁面，請先完成分析流程。")
            else:
                pages = st.multiselect(
                    "📑 選擇要匯出的頁面",
                    options=visited,
                    default=visited,
                    key=f"pages_sel_{topic}",
                )
                fmt = st.selectbox(
                    "📄 匯出格式",
                    EXPORT_FORMATS,
                    key=f"fmt_sel_{topic}",
                )

                if st.button("📥 確認下載", key=f"confirm_dl_{topic}"):
                    if not pages:
                        st.warning("請至少選擇一個頁面！")
                    else:
                        st.session_state.current_topic = topic
                        try:
                            _invoke_export_lambda(pages, fmt)
                        except Exception as e:
                            st.error(f"啟動匯出過程時發生錯誤: {e}")
                            logger.error(f"匯出啟動失敗: {e}")

    # ===== 跳頁 =====
    with col_right:
        remaining = [
            p for p in CHATBOT_FLOW[1:] # 只排除第 0 頁
            if p not in st.session_state.visited_pages or p == topic
        ]
        if remaining:
            tgt = st.selectbox(
                "🔀 跳轉頁面",
                options=remaining,
                key=f"jump_sel_{topic}",
            )
            if st.button("🚀 跳轉", key=f"jump_btn_{topic}"):
                st.session_state.flow_index = CHATBOT_FLOW.index(tgt)
                st.rerun()
        else:
            st.info("所有頁面已訪問完畢，請進行匯出。")

# =====================   增強版聊天 UI   =====================
def build_assistant_html(resp: dict[str, str]) -> str:
    """構建助手HTML回應，支持圖表內容"""
    html_main = _json_block_to_html(resp["answer"]) or resp["answer"]
    
    # 檢查是否包含圖表，如果是則添加一些調試信息
    if 'chart-container' in html_main:
        chart_count = html_main.count('chart-container')
        logger.info(f"✅ 檢測到 {chart_count} 個圖表容器")
    
    if resp["source"]:
        html_main += f"\n\n<div class='report-source'>{resp['source']}</div>"
    
    return html_main

def show_chat_topic(topic: str) -> None:
    """增強版聊天頁面，改善用戶體驗"""
    st.markdown(f"## {topic}")
    st.caption(TOPIC_HINTS.get(topic, ""))

    auto_generate_if_needed(topic)
    st.session_state.visited_pages.add(topic)
    st.session_state.setdefault(f"chat_history_{topic}", [])

    # --- Chat Box ---
    with st.container():
        st.markdown('<div class="card chat-box">', unsafe_allow_html=True)
        for m in st.session_state[f"chat_history_{topic}"]:
            _render_message(m)
        st.markdown("</div>", unsafe_allow_html=True)

    # --- User Input ---
    if user_input := st.chat_input("請輸入你的問題 👇", key=f"input_{topic}"):
        st.chat_message("user", avatar="\U0001F464").write(user_input)
        
        # 使用升級版的 get_response，自動顯示進度
        resp = get_response(user_input, st.session_state.session_id, topic)

        if resp:  # 確保有回應
            assistant_html = build_assistant_html(resp)
            _append_history(topic, user_input, assistant_html)
            
            # 顯示詳細處理時間資訊
            if resp.get("processing_time") and resp.get("actual_lambda_time"):
                processing_time = resp["processing_time"]
                actual_time = resp["actual_lambda_time"]
                st.caption(
                    f"⏱️ 總處理時間: {processing_time:.1f}秒 | "
                    f"AI 分析時間: {actual_time:.1f}秒"
                )
                
        st.rerun()

    _render_next_controls(topic)

# -----------------------------
# Main App Entry
# -----------------------------

def main():
    header()
    # st_autorefresh(interval=KEEPALIVE_MS, 
    #                key="keepalive")
    initialization()

    if st.session_state.flow_index == -1:
        show_form()
    elif st.session_state.flow_index < len(CHATBOT_FLOW):
        show_chat_topic(CHATBOT_FLOW[st.session_state.flow_index])

    show_footer()

if __name__ == "__main__":
    main()