"""
invoke-lambda – 依使用者輸入調用 Bedrock Agent，並將回應整理成
符合前端 (Streamlit) 使用的 HTML 片段。

• 先以 session_id 區分同一位使用者一次「完整分析流程」。
• 解析 Agent trace，取出:
    1) 主回答文字 (chunk)
    2) SQL query（如有 ACTION_GROUP）
    3) KB 來源參考連結（S3 URI）
• 再呼叫第二個 FM（Claude 3 Sonnet）把主回答→HTML+JSON 格式化。
• 透過 `parse_json_from_text()` 保證輸出一定能被 json.loads()。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import unquote
import io
import time
import random
import uuid
import base64

from connections import Connections
from utils import (
    output_format, 
    evaluation_prompt_en, 
    parse_json_from_text, 
    combine_html_from_json,
    get_heading_prefix
)

# ============ Logger ============
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============ 環境變數 ============
AGENT_ID: str = os.environ["AGENT_ID"]
REGION_NAME: str = os.environ["REGION_NAME"]

SUPPLY_INFO = "" # "目前未充分資料，將使用既有知識分析..."

logger.info("Bedrock Agent ID: %s", AGENT_ID)

# ============ AWS 連線 ============
agent_client = Connections.agent_client
agent_runtime_client = Connections.agent_runtime_client
s3_resource = Connections.s3_resource
s3_client_fbmapping = Connections.s3_client_fbmapping

# ---------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------
def get_highest_agent_version_alias_id(
    list_resp: Dict[str, Any]
) -> str | None:
    """
    取得目前 Agent 所有別名 (Aliases) 中版本號最大的那一個。

    Parameters
    ----------
    list_resp : dict
        `list_agent_aliases` 的回傳結果。

    Returns
    -------
    str | None
        若找不到可用 alias，回傳 None。
    """
    highest = -1
    best_alias_id = None
    for alias in list_resp.get("agentAliasSummaries", []):
        rcfg = alias.get("routingConfiguration")
        if rcfg:
            ver = rcfg[0]["agentVersion"]
            if ver.isdigit() and int(ver) > highest:
                highest = int(ver)
                best_alias_id = alias["agentAliasId"]
    return best_alias_id


def build_prompt(user_input: str, topic: str, company_info: Dict[str, str]) -> str:
    """
    將公司基本資料 + Topic + 使用者問題 組成 Agent Prompt。

    例：
    「品牌名稱：台灣啤酒，品牌所屬產業：啤酒 ...。
      請以『市場概況與趨勢』的角度…」
    """
    base = "，".join(f"{k}：{v}" for k, v in company_info.items() if v.strip())
    return f"請用searchinternet上網搜尋、querygluetable抓資料及利用knwoledge base抓資料。\n\n{base}。\n\n針對{topic}進行分析，專業地回答使用者問題：{user_input}"


def invoke_agent(
    user_input: str, session_id: str, topic: str, company_info: Dict[str, str]
):
    """
    呼叫 Bedrock Agent 並回傳 streaming response (generator 物件)。
    """
    alias_id = get_highest_agent_version_alias_id(
        agent_client.list_agent_aliases(agentId=AGENT_ID)
    )
    if not alias_id:
        raise RuntimeError("❌ 找不到可用的 Agent Alias")

    prompt = build_prompt(user_input, topic, company_info)
    return agent_runtime_client.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=alias_id,
        sessionId=session_id,
        enableTrace=True,
        inputText=prompt,
    )

# ---------------------------------------------------------------------
# Trace / 回應解析
# ---------------------------------------------------------------------
def get_agent_response(streaming_resp: Dict[str, Any], topic: str = "") -> Tuple[str, List[str], List[dict[str, str]]]:
    """
    解析 Agent Streaming Response:
    - 回答文字 chunk
    - 所有來源連結（KB + Perplexity）
    - 圖表數據：[(title_text, img_html), ...]
    
    新增參數:
    - topic: 分析主題，用於控制是否包含圖表來源
    """
    logger.info(f"get_agent_response ... topic: {topic}")
    if "completion" not in streaming_resp:
        raise ValueError("Invalid response: missing 'completion' field")

    traces: List[dict] = []
    chunk_text = []

    for event in streaming_resp["completion"]:
        if "trace" in event:
            logger.info("trace: %s", event["trace"])
            traces.append(event["trace"])
        elif "chunk" in event:
            chunk_text.append(event["chunk"]["bytes"].decode("utf-8", "ignore"))

    full_text = "".join(chunk_text)

    # 收集所有來源（Knowledge Base + Perplexity）
    sources: List[str] = []

    try:
        kb_sources = extract_source_list_from_kb(traces)
        sources.extend(kb_sources)
        if kb_sources:
            logger.info("✓ Extracted %d KB references", len(kb_sources))
    except Exception as err:
        logger.warning("⚠️ Extract KB refs failed: %s", err)

    try:
        web_sources = extract_source_list_from_perplexity(traces)
        sources.extend(web_sources)
        if web_sources:
            logger.info("✓ Extracted %d Perplexity sources", len(web_sources))
    except Exception as err:
        logger.warning("⚠️ Extract Perplexity refs failed: %s", err)

    # 根據主題決定是否將圖表來源加入 sources
    try:
        txt2figure_result = extract_txt2figure_result_from_traces(traces)
        
        # 只有在"市場概況與趨勢"主題時才將圖表來源加入 sources
        if topic == "市場概況與趨勢":
            # 從圖表數據中提取 title_text 作為來源
            chart_sources = [chart["title_text"] for chart in txt2figure_result]
            sources.extend(chart_sources)
            logger.info("✓ Extracted %d Athena reference (included in sources)", len(chart_sources))
        else:
            logger.info("✓ Extracted %d Athena reference (excluded from sources due to topic: %s)", 
                    len(txt2figure_result), topic)
            
    except Exception as err:
        logger.warning("⚠️ Extract Athena refs failed: %s", err)
        txt2figure_result = []

    return full_text, sources, txt2figure_result

# ---------------------------------------------------------------------
# Athena-Txt2Figure 來源處理
# ---------------------------------------------------------------------
def extract_txt2figure_result_from_traces(traces: List[dict]) -> List[Dict[str, Any]]:
    """
    若 trace 中包含 ACTION_GROUP，擷取 Figure-HTML 片段。
    確保 img_static 字段從 base64 字符串還原為 bytes
    主函數：從traces中提取txt2figure結果，職責：協調整個提取流程
    """
    try:
        for trace in traces:
            logger.info("extract_figure_from_traces - trace: %s", trace)
            
            vanna_result = _extract_vanna_result_from_trace(trace)
            if vanna_result:
                processed_result = _process_vanna_result(vanna_result)
                return _add_title_suffix(processed_result)
        
        return []
        
    except Exception as err:
        logger.warning("⚠️ Extract Athena refs failed: %s", err)
        return []

def _extract_vanna_result_from_trace(trace: dict) -> list | None:
    """
    從 traces 中提取 vanna_result_by_title，轉換為列表格式。
    支援新的多SQL結構。
    """
    obs = (
        trace.get("trace", {})
            .get("orchestrationTrace", {})
            .get("observation", {})
    )

    # 僅處理 ACTION_GROUP
    if obs.get("type") != "ACTION_GROUP":
        return None

    ag_out = obs.get("actionGroupInvocationOutput", {})

    # 優先檢查 sessionAttributes
    session_attrs = ag_out.get("sessionAttributes", {})
    if session_attrs and "vanna_result_by_title" in session_attrs:
        vanna_by_title = session_attrs["vanna_result_by_title"]
        if isinstance(vanna_by_title, dict):
            # 將字典值轉換為列表，並處理可能的多個結果
            result_list = []
            for title, result_data in vanna_by_title.items():
                if isinstance(result_data, list):
                    # 如果一個 title 對應多個結果（多個 SQL）
                    result_list.extend(result_data)
                else:
                    # 單個結果
                    result_list.append(result_data)
            return result_list

    # 回溯 text 欄位
    text_blob = ag_out.get("text", "")
    if not text_blob:
        return None

    try:
        payload = json.loads(text_blob) if isinstance(text_blob, str) else text_blob
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict) and "vanna_result_by_title" in payload:
        vanna_by_title = payload["vanna_result_by_title"]
        if isinstance(vanna_by_title, dict):
            # 將字典值轉換為列表，並處理可能的多個結果
            result_list = []
            for title, result_data in vanna_by_title.items():
                if isinstance(result_data, list):
                    # 如果一個 title 對應多個結果（多個 SQL）
                    result_list.extend(result_data)
                else:
                    # 單個結果
                    result_list.append(result_data)
            return result_list

    return None

def _process_vanna_result(vanna_result: list) -> List[dict]:
    """
    職責：處理vanna_result，將base64字符串還原為bytes
    等同於原始的 restore_bytes_from_base64 函數功能
    """
    def restore_bytes_from_base64(obj):
        """
        將 base64 字符串還原為 bytes，遞歸處理嵌套結構
        """
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                if k == "img_static" and isinstance(v, str) and v:
                    logger.info("正在下載 S3 圖片: %s", v)
                    # v 已是 S3 位置，例：
                    #   https://my-bucket.s3.amazonaws.com/vanna/abcd.png
                    try:
                        if v.startswith("s3://"):
                            # s3://bucket/key  →  bucket, key
                            bucket, key = v.replace("s3://", "").split("/", 1)
                            response = s3_client_fbmapping.get_object(Bucket=bucket, Key=key)
                            data = response["Body"].read()
                        else:  # HTTPS 形式
                            # 轉回 bucket、key 後直接用 boto3 下載（域名同 bucket）
                            m = re.match(r"https://([^.]*)\.s3.*?/(.+)", v)
                            bucket, key = m.group(1), m.group(2)
                            response = s3_client_fbmapping.get_object(Bucket=bucket, Key=key)
                            data = response["Body"].read()
                        result[k] = {
                            "bytes": data,  # Word 用
                            "b64":  base64.b64encode(data).decode()  # 走 JSON 用
                        }
                    except Exception as e:
                        logger.warning(f"無法下載 S3 圖片: {e}")
                        result[k] = None
                else:
                    result[k] = restore_bytes_from_base64(v)
            return result
        elif isinstance(obj, list):
            return [restore_bytes_from_base64(item) for item in obj]
        else:
            return obj
    
    # 還原 base64 為 bytes
    processed_result = restore_bytes_from_base64(vanna_result)
    logger.info("成功還原 base64 數據為 bytes")
    
    # 直接使用原始HTML，不進行轉換
    logger.info("保持原始 Plotly HTML")
    
    return processed_result

def _add_title_suffix(result: List[dict], suffix: str = "(發票數據)") -> List[dict]:
    """
    保留更多上下文資訊用於圖表定位
    """
    for item in result:
        if isinstance(item, dict):
            orig_title = item.get("title_text") or ""
            question = item.get("question", "")
            
            # 保留原始問題作為context，用於後續的圖表定位
            if question and "context" not in item:
                item["context"] = question
            
            if not orig_title:
                if question:
                    simplified_title = question[:30] + "..." if len(question) > 30 else question
                    item["title_text"] = f"{simplified_title}{suffix}"
                else:
                    item["title_text"] = suffix
            elif not orig_title.endswith(suffix):
                item["title_text"] = f"{orig_title}{suffix}"

    return result

# ---------------------------------------------------------------------
# Knowledge-Base 來源處理
# ---------------------------------------------------------------------
def extract_source_list_from_kb(traces: List[dict]) -> List[str]:
    """
    從 KB Trace 萃取 S3 URI list。
    """
    for t in traces:
        obs = (
            t.get("trace", {})
            .get("orchestrationTrace", {})
            .get("observation", {})
        )
        kb_out = obs.get("knowledgeBaseLookupOutput")
        if kb_out:
            return [r["location"]["s3Location"]["uri"] for r in kb_out["retrievedReferences"]]
    return []


def clean_and_dedup_uris(uris: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for u in uris:
        if not u or not isinstance(u, str):
            continue
        norm = unquote(u.strip().lower())
        if norm not in seen:
            seen.add(norm)
            deduped.append(u)
    return deduped


def source_link(uris: list[str]) -> str:
    uris = clean_and_dedup_uris(uris)

    if not uris:
        return "<p><em>目前無可用的來源資料。</em></p>"

    links = []
    source_unknow_idx = 1

    for item in uris:
        try:
            item = item.strip() if item else ""
            if not item:
                continue

            # 判斷是否為 agent question
            if "(發票數據)" in item:
                # safe_text = html.escape(item)
                safe_text = item
                links.append(f"<li><span class='question-text'>{safe_text}</span></li>")
                continue

            filename = item.rsplit("/", 1)[-1]
            filename = unquote(filename)
            filename = re.sub(r"[_\-]+", " ", filename).strip()
            # safe_item = html.escape(item)
            safe_item = item

            # 判斷 s3 還是 http
            if item.lower().startswith("s3://"):
                label = f"{filename}（來源檔案）" if filename else "來源檔案"
            else:
                label = filename or f"未命名來源 {source_unknow_idx}"
                if "未命名來源" in label:
                    source_unknow_idx += 1

            # safe_label = html.escape(label)
            safe_label = label
            links.append(f"<li>. <a href='{safe_item}' target='_blank'>{safe_label}</a></li>")

        except Exception as e:
            logger.warning("Failed to parse URI %s: %s", item, e)
            # links.append(f"<li>. <a href='{html.escape(item)}' target='_blank'>未知來源</a></li>")
            links.append(f"<li>. <a href='{item}' target='_blank'>未知來源</a></li>")

    return "<ul>" + "\n".join(links) + "</ul>"

# ---------------------------------------------------------------------
# Web-Search 來源處理
# ---------------------------------------------------------------------
def extract_source_list_from_perplexity(traces: List[dict]) -> List[str]:
    """
    從 Perplexity Trace 中擷取外部來源連結。
    尋找 trace → orchestrationTrace → observation → actionGroupInvocationOutput.text，
    若該段落為 JSON 格式且含有 'response.sources'，即視為 Perplexity 結果。
    """
    sources = []

    for t in traces:
        obs = (
            t.get("trace", {})
             .get("orchestrationTrace", {})
             .get("observation", {})
        )
        text = obs.get("actionGroupInvocationOutput", {}).get("text", "")

        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                source_list = payload.get("response", {}).get("sources", [])
                if isinstance(source_list, list):
                    sources.extend(source_list)
        except json.JSONDecodeError:
            continue  # 跳過非 JSON 格式

    return sources

# ---------------------------------------------------------------------
# Claude Sonnet – 產生 HTML/JSON 報告
# ---------------------------------------------------------------------
import threading
import concurrent.futures
from typing import List, Tuple

def create_chart_placeholder(chart_id: str) -> str:
    """創建圖表佔位符，避免JSON序列化問題"""
    return f"""
    <div class="chart-body" id="chart-body-{chart_id}" style="
        padding: 20px;
        min-height: 400px;
    ">
        <div id="plotly-placeholder-{chart_id}" style="
            display: flex;
            align-items: center;
            justify-content: center;
            height: 350px;
            color: #666;
            font-size: 16px;
        ">
            📊 圖表加載中...
        </div>
    </div>
    """

def build_output_format(raw_analysis: str, topic: str, txt2figure_results: List[dict[str, Any]]) -> Dict[str, Any]:
    """增強版的build_output_format，統一HTML和Word圖表插入邏輯"""
    topic_data = output_format.get(topic)
    if not topic_data:
        raise ValueError(f"Unsupported topic: {topic}")

    result = {}
    chart_data = {}
    word_chart_data = {}  # 新增：Word專用圖表數據
    subtopics = topic_data.get("subtopics", [])

    # 添加大標題 - 使用特殊前綴確保在最前面
    main_title = topic_data.get("title", topic)
    result["_000_main_title"] = f"<h1>{main_title}</h1>"

    # 收集所有任務（保持原有邏輯）
    all_tasks = []
    for subtopic_idx, subtopic in enumerate(subtopics):
        subtopic_title = subtopic["title"]
        subsubtopics = subtopic.get("subsubtopics", [])
        
        if not subsubtopics:
            all_tasks.append(("subtopic", subtopic_idx, subtopic_title, None, None))
        else:
            for subsubtopic_idx, subsub in enumerate(subsubtopics):
                if isinstance(subsub, dict) and 'title' in subsub:
                    subsub_title = subsub["title"]
                else:
                    subsub_title = subsub
                all_tasks.append(("subsubtopic", subtopic_idx, subtopic_title, subsubtopic_idx, subsub_title))

    # 內容生成處理（保持原有邏輯）
    if all_tasks:
        logger.info(f"開始處理 {len(all_tasks)} 個任務（增強可靠性版本）")
        
        # 第一輪：正常並發處理（降低並發數以減少限流）
        optimal_workers = min(16, len(all_tasks), 20)  # 降低並發數
        logger.info(f"使用 {optimal_workers} 個線程並發處理任務")
        
        completed_results = []
        failed_tasks = []
        
        def call_model_unified_enhanced(task_info):
            try:
                task_type, subtopic_idx, subtopic_title, subsubtopic_idx, subsubtopic_title = task_info
                
                # 生成唯一task_id
                if task_type == "subtopic":
                    task_id = f"main_{subtopic_title}_{subtopic_idx}"
                else:
                    task_id = f"main_{subsubtopic_title}_{subtopic_idx}_{subsubtopic_idx}"
                
                # 基於任務索引錯開執行時間
                if task_type == "subtopic":
                    global_task_idx = subtopic_idx
                else:
                    global_task_idx = subtopic_idx * 10 + subsubtopic_idx
                
                delay = (global_task_idx % 8) * 0.5
                time.sleep(delay)
                
                return call_model_unified(task_info, raw_analysis, task_id)
                
            except Exception as e:
                logger.error(f"任務執行失敗: {task_info}, 錯誤: {e}")
                return None

        # 第一輪執行
        with concurrent.futures.ThreadPoolExecutor(max_workers=optimal_workers) as executor:
            futures = [executor.submit(call_model_unified_enhanced, task_info) for task_info in all_tasks]
            
            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                try:
                    result_tuple = future.result()
                    if result_tuple and result_tuple[5]:  # 檢查是否有有效內容
                        completed_results.append(result_tuple)
                        task_type, _, subtopic_title, _, target_title, _ = result_tuple
                        display_target = target_title or f"(子標題: {subtopic_title})"
                        logger.info(f"完成進度: {i+1}/{len(futures)} - [{task_type}] -> {display_target}")
                    else:
                        # 記錄失敗的任務
                        failed_tasks.append(all_tasks[i])
                        logger.warning(f"任務失敗，將重試: {all_tasks[i]}")
                except Exception as e:
                    failed_tasks.append(all_tasks[i])
                    logger.error(f"任務執行異常: {e}")

        # 第二輪：重試失敗的任務
        if failed_tasks:
            logger.warning(f"第一輪完成 {len(completed_results)}/{len(all_tasks)} 個任務，開始重試 {len(failed_tasks)} 個失敗任務")
            retry_results = retry_failed_tasks(failed_tasks, raw_analysis)
            completed_results.extend(retry_results)
            logger.info(f"重試完成，總計成功: {len(completed_results)}/{len(all_tasks)} 個任務")

        # 第三輪：為仍然失敗的任務生成fallback內容
        successful_titles = {result[4] for result in completed_results}  # target_title
        for task_info in all_tasks:
            task_type, subtopic_idx, subtopic_title, subsubtopic_idx, subsubtopic_title = task_info
            target_title = subtopic_title if task_type == "subtopic" else subsubtopic_title
            
            if target_title not in successful_titles:
                logger.warning(f"為失敗任務生成fallback: {target_title}")
                fallback_result = call_model_unified(task_info, raw_analysis, f"fallback_{target_title}")
                if fallback_result:
                    completed_results.append(fallback_result)

        # 處理結果（修復子標題重複問題）
        grouped_results = {}
        for task_type, subtopic_idx, subtopic_title, subsubtopic_idx, target_title, html_content in completed_results:
            if subtopic_title not in grouped_results:
                grouped_results[subtopic_title] = {"subtopic_content": None, "subsubtopics": []}
            
            if task_type == "subtopic":
                grouped_results[subtopic_title]["subtopic_content"] = html_content
            else:
                grouped_results[subtopic_title]["subsubtopics"].append((subsubtopic_idx, target_title, html_content))

        # 按原始順序整理到result（修復標題位置問題）
        for subtopic_idx, subtopic in enumerate(subtopics):
            subtopic_title = subtopic["title"]
            subsubtopics = subtopic.get("subsubtopics", [])
            
            # 關鍵修復：確保標題在正確位置，使用更精確的排序前綴
            if subtopic_title in grouped_results:
                prefix = get_heading_prefix(2, subtopic_idx)
                
                if not subsubtopics:
                    # 沒有子子標題的情況：先添加標頭，再添加內容
                    subtopic_content = grouped_results[subtopic_title]["subtopic_content"]
                    if subtopic_content:
                        # 檢查內容是否已經包含了正確格式的標題
                        expected_header = f"<h2>{prefix} {subtopic_title}</h2>"
                        if expected_header in subtopic_content:
                            # 內容已包含正確標題，直接使用，使用_01確保在正確位置
                            result[f"_{subtopic_idx:02d}_01_{subtopic_title}_content"] = subtopic_content
                        elif f"<h2>" in subtopic_content:
                            # 內容包含h2標題但格式不對，需要替換或移除多餘的標題
                            import re
                            cleaned_content = re.sub(r'<h2[^>]*>.*?</h2>', '', subtopic_content, flags=re.DOTALL)
                            # 使用_00確保標頭在前，_01確保內容在後
                            result[f"_{subtopic_idx:02d}_00_{subtopic_title}_header"] = expected_header
                            result[f"_{subtopic_idx:02d}_01_{subtopic_title}_content"] = cleaned_content
                        else:
                            # 內容不包含標題，正常添加標頭和內容
                            result[f"_{subtopic_idx:02d}_00_{subtopic_title}_header"] = expected_header
                            result[f"_{subtopic_idx:02d}_01_{subtopic_title}_content"] = subtopic_content
                        logger.info(f"已整理子標題: {subtopic_title}")
                else:
                    # 有子子標題的情況：先添加子標題標頭，然後處理子子標題
                    # 使用_00確保子標題標頭在最前面
                    result[f"_{subtopic_idx:02d}_00_{subtopic_title}_header"] = f"<h2>{prefix} {subtopic_title}</h2>"
                    
                    sorted_subsubtopics = sorted(grouped_results[subtopic_title]["subsubtopics"], key=lambda x: x[0])
                    for subsubtopic_idx, subsubtopic_title, html_content in sorted_subsubtopics:
                        # 確保子子標題內容的標題層級正確
                        subprefix = get_heading_prefix(3, subsubtopic_idx)
                        expected_subheader = f"<h3>{subprefix} {subsubtopic_title}</h3>"
                        
                        if expected_subheader in html_content:
                            # 已包含正確的h3標題，使用01+subsubtopic_idx確保順序
                            result[f"_{subtopic_idx:02d}_{subsubtopic_idx+1:02d}_{subsubtopic_title}"] = html_content
                        elif f"<h3>" in html_content:
                            # 包含h3但格式可能不對，移除後重新添加
                            import re
                            cleaned_subcontent = re.sub(r'<h3[^>]*>.*?</h3>', '', html_content, flags=re.DOTALL)
                            final_subcontent = expected_subheader + cleaned_subcontent
                            result[f"_{subtopic_idx:02d}_{subsubtopic_idx+1:02d}_{subsubtopic_title}"] = final_subcontent
                        else:
                            # 不包含h3標題，添加標題
                            final_subcontent = expected_subheader + html_content
                            result[f"_{subtopic_idx:02d}_{subsubtopic_idx+1:02d}_{subsubtopic_title}"] = final_subcontent
                            
                        logger.info(f"已整理子子標題: [{subtopic_title}] -> {subsubtopic_title}")

    # 建立標題到key的映射，用於快速查找
    title_to_key_mapping = {}
    for key in result.keys():
        parts = key.split("_")
        if len(parts) >= 4:
            title_name = parts[3]
            title_to_key_mapping[title_name] = key
    
    logger.info(f"可用的標題映射: {list(title_to_key_mapping.keys())}")

    for chart_result in txt2figure_results:
        title_text = chart_result["title_text"]
        img_static = chart_result.get("img_static")
        if not img_static:
            continue

        # 處理 img_static 的不同格式（保持原有邏輯）
        if isinstance(img_static, dict):
            img_bytes = img_static.get("bytes")
            img_b64 = img_static.get("b64")
            if not img_bytes:
                logger.warning(f"圖表數據不完整，跳過: {title_text}")
                continue
            if not img_b64:
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        elif isinstance(img_static, str):
            logger.warning(f"收到未處理的 S3 URL，跳過: {img_static}")
            continue
        else:
            img_bytes = img_static
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        # 轉成 data-URI
        data_uri = f"data:image/png;base64,{img_b64}"
        img_html = f'<img src="{data_uri}" style="max-width:100%;height:auto;" />'
        chart_id = str(uuid.uuid4().hex[:8])
        
        # 新邏輯：根據圖表的來源資訊定位
        target_key = None
        
        # 方法1：從圖表的context中尋找對應的標題
        if "context" in chart_result:
            context = chart_result["context"]
            logger.info(f"圖表 '{title_text}' 的context: {context}")
            for title_name, key in title_to_key_mapping.items():
                if title_name in context:
                    target_key = key
                    logger.info(f"根據context將圖表 '{title_text}' 插入到 '{title_name}'")
                    break
        
        # 方法2：從圖表的question中尋找對應的標題
        if not target_key and "question" in chart_result:
            question = chart_result["question"]
            logger.info(f"圖表 '{title_text}' 的question: {question}")
            for title_name, key in title_to_key_mapping.items():
                if title_name in question:
                    target_key = key
                    logger.info(f"根據question將圖表 '{title_text}' 插入到 '{title_name}'")
                    break
        
        # 方法3：嘗試從title_text本身推斷（移除後綴後比對）
        if not target_key:
            clean_title = title_text.replace("(發票數據)", "").strip()
            logger.info(f"圖表清理後的標題: {clean_title}")
            for title_name, key in title_to_key_mapping.items():
                if title_name in clean_title or clean_title in title_name:
                    target_key = key
                    logger.info(f"根據清理後標題將圖表 '{title_text}' 插入到 '{title_name}'")
                    break
        
        # Fallback：使用固定對應關係
        if not target_key:
            fig_show_subtitle = ["主導品牌銷售概況", "平價帶市場概況", "高價帶市場概況", "價格帶結構與策略定位"]
            chart_index = txt2figure_results.index(chart_result)
            target_subtitle = fig_show_subtitle[chart_index % len(fig_show_subtitle)]
            
            for key in result.keys():
                if target_subtitle in key:
                    target_key = key
                    break
            
            if target_key:
                logger.warning(f"使用fallback邏輯將圖表 '{title_text}' 插入到 '{target_subtitle}'")
        
        # 最後的fallback
        if not target_key:
            content_keys = [k for k in result.keys() if not k.endswith("_header")]
            if content_keys:
                target_key = sorted(content_keys)[0]
                logger.warning(f"找不到合適位置，將圖表 '{title_text}' 插入到 '{target_key}'")
            else:
                logger.error(f"無法插入圖表 '{title_text}'，跳過此圖表")
                continue
        
        if target_key:
            # HTML圖表處理
            html_placeholder = create_chart_placeholder(chart_id)
            chart_data[chart_id] = {
                "title_text": title_text,
                "html": img_html,
                "static": img_bytes
            }
            
            # Word圖表處理
            word_placeholder = f"[WORD_CHART_{chart_id}]"
            
            # 插入佔位符
            result[target_key] += "\n" + html_placeholder + "\n"
            result[target_key] += f"\n<div class='word-chart-placeholder'>{word_placeholder}</div>\n"
            
            # 保存Word圖表數據
            page_name = extract_page_name_from_key(target_key)
            if page_name not in word_chart_data:
                word_chart_data[page_name] = []

            word_chart_entry = {
                "chart_id": chart_id,
                "title_text": title_text,
                "img_static_b64": img_b64,
                "placeholder": word_placeholder,
                "target_section": extract_page_name_from_key(target_key),
                "target_key": target_key
            }
            word_chart_data[page_name].append(word_chart_entry)
            
            logger.info(f"成功插入圖表 '{title_text}' 到 '{target_key}'")

    return {
        "content": result, 
        "charts": chart_data,
        "word_charts": word_chart_data
    }

def extract_page_name_from_key(key: str) -> str:
    """從key中提取頁面名稱"""
    # 例如: "_01_00_主導品牌銷售概況_header" -> "主導品牌銷售概況"
    parts = key.split("_")
    if len(parts) >= 4:
        return parts[3]
    return "unknown_page"

def call_model_unified(task_info, raw_analysis, task_id=""):
    """帶重試機制的統一任務處理函數"""
    task_type, subtopic_idx, subtopic_title, subsubtopic_idx, subsubtopic_title = task_info
    
    # 基於任務總索引進行錯開
    if task_type == "subtopic":
        global_task_idx = subtopic_idx
        target_title = subtopic_title
        heading_level = 2
        prefix = get_heading_prefix(2, subtopic_idx)
        # 新增：從 output_format 獲取對應的 prompt
        subtopic_prompt = get_subtopic_prompt(subtopic_title)
    else:
        global_task_idx = subtopic_idx * 10 + subsubtopic_idx
        target_title = subsubtopic_title
        heading_level = 3
        prefix = get_heading_prefix(3, subsubtopic_idx)
        # 新增：從 output_format 獲取對應的 prompt
        subtopic_prompt = get_subsubtopic_prompt(subtopic_title, subsubtopic_title)
    
    logger.info(f"處理任務 [{task_type}] [{subtopic_title}] -> {target_title or '(子標題內容)'}")
    
    # 構建system_prompt - 簡化版本，不再包含具體任務描述
    if task_type == "subtopic":
        system_prompt = f"""You are a market insight report integration assistant specializing in data structuring and visualization. 
Your task is to transform raw analysis text into a structured JSON containing HTML-formatted report sections.

IMPORTANT: Your output MUST be a valid JSON object with the specified subtopic as key and HTML content as value.

STRICT CONTENT RULES:
- DO NOT fabricate or assume information that is not explicitly present in the provided raw analysis, unless handling a missing subtopic as described below.
- You must extract and restructure content ONLY from the provided raw analysis text for all subtopics that have data. 
- Do NOT extrapolate, infer, or augment the analysis with your own ideas unless explicitly instructed to do so in rule 3 below.
- Do not exceed 1400 words. Do not fall below 1300 words.

PRECISE INSTRUCTIONS:
0. Your response MUST begin with a ```json code block, and contain ONLY the JSON object inside. Do not include any explanation, greeting, or comment before or after the JSON.
1. YOUR RESPONSE MUST BE A VALID JSON OBJECT that matches the example format exactly.
2. For the subtopic that has relevant data:
- Create a key in the JSON with the exact subtopic name.
- The value must be properly formatted HTML that includes:
    - Section heading using `<h2>{prefix} {subtopic_title}</h2>`
    - Content paragraphs using `<p>...</p>` 
    - Lists using `<ul><li>...</li></ul>` for bullet points
    - Important data highlighted with `<strong>` or `<em>` tags
3. For subtopic that is missing information in the provided analysis:
- FIRST, create an HTML block following this structure:
    `<h2>{prefix} {subtopic_title}</h2>`
- THEN, immediately continue by using your own general knowledge to generate a plausible, high-quality analysis for that subtopic in properly structured HTML, without requiring additional user input.
4. your response must be COMPLETE, well-structured, and insightful. You are required to produce between 1300 and 1400 words in total output.
5. your output should be designed to SCORE 3 in each of the following evaluation dimensions: {evaluation_prompt_en}
6. Use only secure HTML (no scripts, iframes, or external resources).
7. Ensure your final output is a properly formatted JSON object that can be parsed without errors.
8. NEVER use raw quotation marks (single or double) inside HTML tags like <strong> or <em>. Escape or move them outside the tag.
9. 繁體中文語氣
10. DO NOT generate img HTML or script tags

REQUIRED OUTPUT FORMAT:
```json
{{
"{subtopic_title}": "<h2>{prefix} {subtopic_title}</h2><p>...</p>"
}}
```"""
    else:
        system_prompt = f"""You are a market insight report integration assistant specializing in data structuring and visualization. 
Your task is to transform raw analysis text into a structured JSON containing HTML-formatted report sections.

IMPORTANT: Your output MUST be a valid JSON object with the specified subtopics as keys and HTML content as values.

STRICT CONTENT RULES:
- DO NOT fabricate or assume information that is not explicitly present in the provided raw analysis, unless handling a missing subtopic as described below.
- You must extract and restructure content ONLY from the provided raw analysis text for all subtopics that have data. 
- Do NOT extrapolate, infer, or augment the analysis with your own ideas unless explicitly instructed to do so in rule 3 below.
- Do not exceed 1400 words. Do not fall below 1300 words.

PRECISE INSTRUCTIONS:
0. Your response MUST begin with a ```json code block, and contain ONLY the JSON object inside. Do not include any explanation, greeting, or comment before or after the JSON.
1. YOUR RESPONSE MUST BE A VALID JSON OBJECT that matches the example format exactly.
2. For each subtopic that has relevant data:
- Create a key in the JSON with the exact subtopic name.
- The value must be properly formatted HTML that includes:
    - Section heading using `<h3>{prefix} {subsubtopic_title}</h3>`
    - Content paragraphs using `<p>...</p>` 
    - Lists using `<ul><li>...</li></ul>` for bullet points
    - Important data highlighted with `<strong>` or `<em>` tags
3. For subtopics that are missing information in the provided analysis:
- FIRST, create an HTML block following this structure:
    `<h3>{prefix} {subsubtopic_title}</h3>`
- THEN, immediately continue by using your own general knowledge to generate a plausible, high-quality analysis for that subtopic in properly structured HTML, without requiring additional user input.
4. your response must be COMPLETE, well-structured, and insightful. You are required to produce between 1300 and 1400 words in total output.
5. your output should be designed to SCORE 3 in each of the following evaluation dimensions: {evaluation_prompt_en}
6. Use only secure HTML (no scripts, iframes, or external resources).
7. Ensure your final output is a properly formatted JSON object that can be parsed without errors.
8. NEVER use raw quotation marks (single or double) inside HTML tags like <strong> or <em>. Escape or move them outside the tag.
9. 繁體中文思維
10. DO NOT generate img HTML or script tags

REQUIRED OUTPUT FORMAT:
```json
{{
"{subsubtopic_title}": "<h3>{prefix} {subsubtopic_title}</h3><p>...</p>"
}}
```"""
    
    try:
        start_time = time.time()
        # 將 subtopic_prompt 加入 user input
        raw_text = get_response_invoke(system_prompt, raw_analysis, subtopic_prompt, task_id)
        
        if not raw_text.strip():
            raise Exception("返回內容為空")
            
        parsed = parse_json_from_text(raw_text)
        html_piece = parsed.get(target_title, "")
        
        if not html_piece.strip():
            raise Exception("解析後HTML內容為空")
        
        elapsed = time.time() - start_time
        logger.info(f"任務完成 [{task_type}] [{subtopic_title}] -> {target_title or '(子標題內容)'} (耗時: {elapsed:.2f}s)")
        
        return task_type, subtopic_idx, subtopic_title, subsubtopic_idx, target_title, html_piece
        
    except Exception as err:
        logger.warning(f"⚠️ 任務處理失敗 [{task_type}] [{subtopic_title}] -> {target_title or '(子標題內容)'}: {err}")
        
        # 生成fallback內容
        if task_type == "subtopic":
            fallback = f"""<h2>{prefix} {subtopic_title}</h2>
<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 8px; margin: 20px 0;">
    <p><strong>⚠️ 內容生成中遇到技術問題</strong></p>
    <p>此部分內容暫時無法顯示，系統正在處理中。</p>
</div>"""
        else:
            fallback = f"""<h3>{prefix} {subsubtopic_title}</h3>
<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 8px; margin: 20px 0;">
    <p><strong>⚠️ 內容生成中遇到技術問題</strong></p>
    <p>此部分內容暫時無法顯示，系統正在處理中。</p>
</div>"""
        
        return task_type, subtopic_idx, subtopic_title, subsubtopic_idx, target_title, fallback

def get_response_invoke(system_prompt: str, raw_analysis: str, subtopic_prompt: str, task_id: str = "") -> str:
    # 將 subtopic_prompt 加入 user input
    user_content = f"分析任務：{subtopic_prompt}\n\nAI Agent-Extracted Market Insights：\n{raw_analysis}"
    messages = [{"role": "user", "content": user_content}]
     
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "system": system_prompt,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": 0.3,
    })

    max_retries = 8
    base_wait = 1.0
    
    for attempt in range(max_retries):
        try:
            resp = Connections.bedrock_client.invoke_model(
                body=body,
                modelId=Connections.output_format_fm,
            )
            result = resp["body"].read().decode("utf-8")
            
            # 新增：驗證結果是否包含有效內容
            if result.strip() and len(result.strip()) > 50:  # 基本內容檢查
                return result
            else:
                logger.warning(f"任務 {task_id} 第 {attempt+1} 次嘗試返回內容過短")
                if attempt == max_retries - 1:
                    return result  # 最後一次嘗試仍返回結果
                    
        except Exception as e:
            error_msg = str(e)
            
            if "Too many tokens" in error_msg or "ThrottlingException" in error_msg:
                # 退避策略
                wait_time = min(60, base_wait * (2 ** attempt)) + random.uniform(0, 3) + (hash(task_id) % 10) * 0.2
                logger.warning(f"⚠️ 任務 {task_id} 被限流，第 {attempt+1} 次重試，等待 {wait_time:.2f} 秒")
                time.sleep(wait_time)
                continue
            elif "Connection" in error_msg:
                wait_time = min(10, 0.5 * (2 ** attempt)) + random.uniform(0, 0.5)
                logger.warning(f"⚠️ 任務 {task_id} 連接問題，第 {attempt+1} 次重試，等待 {wait_time:.2f} 秒")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"任務 {task_id} 遇到其他錯誤: {error_msg}")
                continue
    
    logger.error(f"❌ 任務 {task_id} 最多重試次數已達，放棄")
    return ""

def get_subtopic_prompt(subtopic_title: str) -> str:
    """從新的 output_format 結構獲取子標題的 prompt"""
    for main_topic, main_data in output_format.items():
        for subtopic in main_data.get("subtopics", []):
            if subtopic["title"] == subtopic_title:
                return subtopic.get("prompt", f"請分析 {subtopic_title} 相關內容")
    return f"請分析 {subtopic_title} 相關內容"

def get_subsubtopic_prompt(subtopic_title: str, subsubtopic_title: str) -> str:
    """從新的 output_format 結構獲取子子標題的 prompt"""
    for main_topic, main_data in output_format.items():
        for subtopic in main_data.get("subtopics", []):
            if subtopic["title"] == subtopic_title:
                subsubtopics = subtopic.get("subsubtopics", [])
                for subsub in subsubtopics:
                    if isinstance(subsub, dict) and subsub.get("title") == subsubtopic_title:
                        return subsub.get("prompt", f"請分析 {subsubtopic_title} 相關內容")
    return f"請分析 {subsubtopic_title} 相關內容"

def retry_failed_tasks(failed_tasks, raw_analysis, max_retry_rounds=2):
    """重新執行失敗的任務，使用更保守的策略"""
    retry_round = 0
    remaining_failed = failed_tasks.copy()
    successful_results = []
    
    while remaining_failed and retry_round < max_retry_rounds:
        retry_round += 1
        logger.info(f"🔄 第 {retry_round} 輪重試，處理 {len(remaining_failed)} 個失敗任務")
        
        # 使用單線程重試，避免再次限流
        for task_info in remaining_failed:
            try:
                # 增加任務間隔，避免限流
                time.sleep(random.uniform(2, 5))
                
                task_type, subtopic_idx, subtopic_title, subsubtopic_idx, subsubtopic_title = task_info
                
                # 生成任務ID用於重試
                if task_type == "subtopic":
                    target_title = subtopic_title
                    task_id = f"retry_{retry_round}_{subtopic_title}"
                else:
                    target_title = subsubtopic_title
                    task_id = f"retry_{retry_round}_{subsubtopic_title}"
                
                logger.info(f"🔄 重試任務: {task_id}")
                
                # 重新調用原有的任務處理邏輯
                result_tuple = call_model_unified(task_info, raw_analysis, task_id)
                
                if result_tuple and result_tuple[5]:  # 檢查是否有有效內容
                    successful_results.append(result_tuple)
                    logger.info(f"✅ 重試成功: {task_id}")
                else:
                    logger.warning(f"⚠️ 重試仍失敗: {task_id}")
                    
            except Exception as e:
                logger.error(f"❌ 重試過程中出錯: {task_info}, 錯誤: {e}")
        
        # 更新失敗列表（簡化版本，實際可根據需要優化）
        remaining_failed = []  # 簡化：不再重複重試同一任務
        
    return successful_results

def inject_charts_into_html(html_content: str, chart_data: Dict[str, Any]) -> str:
    if not chart_data:
        return html_content

    final_html = html_content   # 之前加的 plotly_cdn 可保留

    for chart_id, data in chart_data.items():
        placeholder_id = f"plotly-placeholder-{chart_id}"
        chart_html = data["html"]

        chart_html_escaped = (
            chart_html.replace("\\", "\\\\")
                      .replace("`", "\\`")
                      .replace("</script>", "<\\/script>")
        )

        inject_script = f"""
        <script>(function() {{
            var ph = document.getElementById("{placeholder_id}");
            if (!ph) return;

            // 1️⃣ 建 iframe
            var frame = document.createElement("iframe");
            frame.style.width      = "100%";   // 滿版寬
            frame.style.maxWidth   = "600px";  // 但最多 600
            frame.style.aspectRatio= "4 / 3";  // 4:3 外觀；瀏覽器不支援時再補 height
            frame.style.height     = "auto";
            frame.style.border     = "none";
            frame.style.display    = "block";
            frame.style.margin     = "0 auto"; // 置中

            ph.replaceWith(frame);

            // 2️⃣ 把整段 Plotly HTML 寫進去
            var doc = frame.contentDocument || frame.contentWindow.document;
            doc.open();
            doc.write(`{chart_html_escaped}`);
            doc.close();
        }})();</script>
        """

        final_html += inject_script

    return final_html

# ---------------------------------------------------------------------
# Lambda 入口
# ---------------------------------------------------------------------
def lambda_handler(event: Dict[str, Any], context):
    """
    AWS Lambda Handler – 主流程

    1. 讀取前端傳來的 `query`, `session_id`, `topic`, `company_info`
    2. 呼叫 Bedrock Agent → 取得分析文字
    3. 用 Claude 4 Sonnet 轉 JSON+HTML
    4. 智能插入圖表並組合來源 / HTML 回傳給前端
    """
    logger.info("Event: %s", json.dumps(event, ensure_ascii=False))

    body = event.get("body", {})
    query: str = body.get("query", "")
    session_id: str = body.get("session_id", "")
    topic: str = body.get("session_attributes", {}).get("analysis_topic", "")
    company_info: dict = body.get("session_attributes", {}).get("company_info", {})

    try:
        # 1. Agent
        logger.info("🤖 調用 Bedrock Agent...")
        agent_resp = invoke_agent(query, session_id, topic, company_info)
        
        # 傳遞 topic 參數給 get_agent_response
        answer_raw, refs, txt2figure_results = get_agent_response(agent_resp, topic)

        logger.info("Agent response: %s", answer_raw)
        logger.info(f"找到 {len(txt2figure_results)} 個圖表")

        # 2. Format to HTML JSON with smart chart placement
        logger.info("📊 格式化內容並插入圖表...")
        output_data = build_output_format(answer_raw, topic, txt2figure_results)
        
        # 3. 組合最終HTML
        html_result = combine_html_from_json(output_data["content"])
        
        # 4. 注入圖表
        if output_data["charts"]:
            logger.info(f"💉 注入 {len(output_data['charts'])} 個圖表...")
            html_result = inject_charts_into_html(html_result, output_data["charts"])

        # 5. 處理來源
        logger.info("📚 處理參考來源...")
        src_parts = []
        if refs:
            src_parts.append("<h4>參考來源</h4>" + source_link(refs))

        # 去除空值、唯一化（保順序），包裝成 HTML
        src_parts = list(dict.fromkeys(p for p in src_parts if p))
        src_str = "\n\n".join(
            f"<div class='report-source-item'>{part}</div>" for part in src_parts
        )
        logger.info("參考來源處理完畢: %s", src_str)

        # 直接使用已處理的數據
        response = {
            "answer": html_result,
            "source": src_str,
            "word_export_data": {
                "content": output_data["content"],
                "charts_data": output_data["word_charts"],  # 直接使用已處理的數據
                "metadata": {
                    "topic": topic,
                    "company_info": company_info,
                    "session_id": session_id
                }
            }
        }

        total_charts = sum(len(charts) for charts in output_data["word_charts"].values())
        logger.info(f"📊 處理完成，包含 {total_charts} 個圖表")
        return response
        
    except Exception as err:
        logger.exception("Handler error: %s", err)
        return {"answer": "系統錯誤，請稍後再試。", "source": ""}