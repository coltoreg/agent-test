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
import time
import random
import uuid
import base64
import concurrent.futures

from connections import Connections
from utils import (
    output_format_pt, 
    evaluation_prompt_en, 
    parse_json_from_text, 
    combine_html_from_json,
    get_heading_prefix
)

# ============ Logger ============
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CURRENT_OUTPUT_FORMAT: Dict[str, Any] = {}

# ============ 環境變數 ============
AGENT_ID: str = os.environ["AGENT_ID"]
REGION_NAME: str = os.environ["REGION_NAME"]

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
    return f"""請按照以下步驟進行分析：
    1. 使用 searchinternet 工具搜尋相關的最新市場資訊和趨勢
    2. 使用 querygluetable 工具查詢相關數據資料
    3. 使用 knowledge_base 工具獲取專業知識和背景資訊
    公司基本資料：{base}
    分析主題：{topic}
    具體問題：{user_input}
    請基於以上三個工具獲得的資訊，對「{topic}」進行全面且專業的分析。
    """


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
    logger.info(f"prompt:{prompt}")
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

def get_agent_response(
    streaming_resp: Dict[str, Any],
    topic: str = "",
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """
    解析 Bedrock Agent Streaming Response
    ------------------------------------------------
    1. 回答文字 (full_text)
    2. 來源 URI / 標題 (sources)
    3. Vanna 圖表資料 (txt2figure_results)
    """
    logger.info("get_agent_response – topic=%s", topic)

    if "completion" not in streaming_resp:
        raise ValueError("Invalid response: missing `completion` field")

    traces: List[Dict[str, Any]] = []
    chunks: List[str] = []

    # 逐條組裝文字 & 收集 trace
    for event in streaming_resp["completion"]:
        if "trace" in event:
            traces.append(event["trace"])
        elif "chunk" in event:
            chunks.append(event["chunk"]["bytes"].decode("utf-8", "ignore"))

    full_text = "".join(chunks)

    # ==== 收集來源 ====
    sources: List[str] = []
    try:
        sources += extract_source_list_from_kb(traces)
    except Exception as e:
        logger.warning("extract KB refs error: %s", e)

    try:
        sources += extract_source_list_from_perplexity(traces)
    except Exception as e:
        logger.warning("extract web refs error: %s", e)

    # ==== 解析 Vanna 圖表 ====
    try:
        txt2figure_results = extract_txt2figure_result_from_traces(traces)
    except Exception as e:
        logger.warning("extract Athena refs error: %s", e)
        txt2figure_results = []

    # 僅在指定主題時，把「成功取得圖檔」的標題也列入來源
    if topic == "市場概況與趨勢":
        chart_sources = [
            c["title_text"]
            for c in txt2figure_results
            if c.get("img_html") and (
                (isinstance(c["img_html"], dict) and c["img_html"].get("bytes"))
                or not isinstance(c["img_html"], dict)  # str / S3 URL 視為成功
            )
        ]
        sources.extend(chart_sources)
        logger.info("added %d chart titles into sources", len(chart_sources))

    return full_text, sources, txt2figure_results

# ---------------------------------------------------------------------
# Athena-Txt2Figure 來源處理
# ---------------------------------------------------------------------
def extract_txt2figure_result_from_traces(traces: List[dict]) -> List[Dict[str, Any]]:
    try:
        for trace in traces:
            logger.info("extract_figure_from_traces - trace: %s", trace)

            vanna_result = _extract_vanna_result_from_trace(trace)
            if vanna_result:
                processed_result = _process_vanna_result(vanna_result)
                # 先補 suffix，再過濾沒有真正標題的
                with_suffix  = _add_title_suffix(processed_result)
                filtered_res = _filter_result_valid_title(with_suffix)
                return filtered_res

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

# ======================================== 讀取 vanna 儲存的圖片
def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    """
    將 s3:// 或 https://<bucket>.s3.<region>.amazonaws.com/key
    解析成 (bucket, key)。不負責下載。
    """
    logger.debug("Parsing S3 URI: %s", uri)

    if uri.startswith("s3://"):
        bucket, key = uri.replace("s3://", "", 1).split("/", 1)
    else:
        m = re.match(r"https://([^.]*)\.s3[.-][^/]+/(.+)", uri)
        if not m:
            logger.error("Unsupported S3 URI format: %s", uri)
            raise ValueError(f"Unsupported S3 URI format: {uri}")
        bucket, key = m.group(1), m.group(2)

    logger.debug("Parsed -> bucket=%s, key=%s", bucket, key)
    return bucket, key

def _download_from_s3(bucket: str, key: str) -> bytes:
    response = s3_client_fbmapping.get_object(Bucket=bucket, Key=key)
    ctype = response.get("ContentType", "")
    logger.debug("Content-Type: %s", ctype)

    # 只接受 text/html；其他類型可視情況丟警告/例外
    if not ctype.startswith("text/html"):
        logger.warning("Object %s 並非 HTML（Content-Type=%s）", key, ctype)
    return response["Body"].read()

def _fetch_s3_object_as_bytes(uri: str) -> bytes:
    """
    對外 API：輸入 S3 URI/URL，返回 bytes。
    內部只做「解析 + 下載」兩步組合，方便之後換成策略 pattern。
    """
    bucket, key = _parse_s3_uri(uri)
    return _download_from_s3(bucket, key)

def _process_vanna_result(vanna_result: List[dict]) -> List[dict]:
    """
    遞迴掃描 vanna_result；遇到 img_html=S3 URI 就下載，
    並轉成 {"bytes": ..., "b64": ...}。
    """

    def _transform(node: Any) -> Any:
        # Dict ───────────────────────────────────────────────────────────
        if isinstance(node, dict):
            new_node: Dict[str, Any] = {}
            for k, v in node.items():
                if k == "img_html" and isinstance(v, str) and v:
                    logger.info("Fetching S3 object for key '%s': %s", k, v)
                    try:
                        raw = _fetch_s3_object_as_bytes(v)
                        new_node[k] = {
                            "bytes": raw,
                            "b64": base64.b64encode(raw).decode()
                        }
                        logger.debug("Successfully converted '%s' (%d bytes)", k, len(raw))
                    except Exception as exc:
                        # 不 raise，讓後續流程不中斷
                        logger.warning("Failed to fetch S3 object: %s", exc)
                        new_node[k] = None
                else:
                    new_node[k] = _transform(v)
            return new_node

        # List ────────────────────────────────────────────────────────────
        if isinstance(node, list):
            return [_transform(item) for item in node]

        # Scalar ──────────────────────────────────────────────────────────
        return node

    processed = _transform(vanna_result)
    logger.info("Finished converting vanna_result (total items: %d)", len(vanna_result))
    return processed

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

def _filter_result_valid_title(result: List[dict], suffix: str = "(發票數據)") -> List[dict]:
    """
    只保留有「真實 title_text」的圖表  
    - title_text 為空 → 捨棄  
    - title_text 只剩後綴 (e.g. "(發票數據)") → 捨棄
    """
    return [
        item for item in result
        if isinstance(item, dict)
        and item.get("title_text")
        and item["title_text"].strip() != suffix
    ]

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


# ------------------------------------------------------------------
# ------------------------------------------------------------------
# ------------------------------------------------------------------
def _build_path_to_key(topic_cfg: Dict[str, Any]) -> Dict[str, str]:
    """
    把 output_format 的結構轉成 {完整路徑: section_key}
    例：
      subtopics.0           -> _00_00_產業規模與成長_header
      subtopics.0.subsubtopics.2 -> _00_03_年度銷售變化
    """
    mapping = {}
    for s_idx, s in enumerate(topic_cfg["subtopics"]):
        sub_path = f"subtopics.{s_idx}"
        mapping[sub_path] = f"_{s_idx:02d}_00_{s['title']}_header"

        for ss_idx, ss in enumerate(s.get("subsubtopics", [])):
            key = f"_{s_idx:02d}_{ss_idx+1:02d}_{ss['title']}"
            mapping[f"{sub_path}.subsubtopics.{ss_idx}"] = key
    return mapping

def build_output_format(
    raw_analysis: str,
    topic: str,
    txt2figure_results: List[Dict[str, Any]],
    company_info: Dict[str, str]
) -> Dict[str, Any]:
    global _CURRENT_OUTPUT_FORMAT

    # 依照 company_info 自動重新生成
    if (_CURRENT_OUTPUT_FORMAT.get("_meta_company_info") != company_info):
        _CURRENT_OUTPUT_FORMAT = output_format_pt(
            input_company=company_info.get("企業名稱", ""),
            input_brand=company_info.get("品牌名稱", ""),
            input_product=company_info.get("商品名稱", ""),
            input_product_category=company_info.get("商品類型", "")
        )
        _CURRENT_OUTPUT_FORMAT["_meta_company_info"] = company_info

    # ------------------------------------------------------------------
    # 驗證與基本變數
    # ------------------------------------------------------------------
    topic_cfg = _CURRENT_OUTPUT_FORMAT.get(topic)
    if not topic_cfg:
        raise ValueError(f"Unsupported topic: {topic}")
    
    result: Dict[str, str] = {}
    charts: Dict[str, Any] = {}
    word_charts: Dict[str, List[Dict[str, Any]]] = {}

    # 主標題
    result["_000_main_title"] = f"<h1>{topic_cfg.get('title', topic)}</h1>"

    # ------------------------------------------------------------------
    # 產生章節 HTML（Claude）
    # ------------------------------------------------------------------
    result.update(
        _generate_sections_html(
            topic_cfg=topic_cfg,
            raw_analysis=raw_analysis,
        )
    )

    # 生成標題 → section_key 的映射，後續插圖用
    title_to_key = {k.split("_", 3)[3]: k for k in result}
    path_to_key = _build_path_to_key(topic_cfg)

    # ------------------------------------------------------------------
    # 插入 Vanna 圖表
    # ------------------------------------------------------------------
    for chart in txt2figure_results:
        _insert_chart(chart, result, title_to_key, path_to_key, charts, word_charts)

    return {"content": result, "charts": charts, "word_charts": word_charts}


# ==========================================================================
# build_output_format 的輔助函式，保持在同一模組最方便維護
# ==========================================================================
def _generate_sections_html(
    topic_cfg: Dict[str, Any],
    raw_analysis: str,
) -> Dict[str, str]:
    """
    多執行緒呼叫 Claude，將 output_format 的 (sub)subtopic
    轉成 {section_key: html}。
    """
    sections: Dict[str, str] = {}
    tasks: List[Tuple] = []

    # --------- 1. 收集任務 ---------
    for s_idx, s in enumerate(topic_cfg["subtopics"]):
        if not s.get("subsubtopics"):
            tasks.append(("subtopic", s_idx, s["title"], None, None))
        else:
            for ss_idx, ss in enumerate(s["subsubtopics"]):
                ss_title = ss["title"] if isinstance(ss, dict) else ss
                tasks.append(
                    ("subsubtopic", s_idx, s["title"], ss_idx, ss_title)
                )

    # --------- 2. 併發呼叫 Claude ---------
    completed: List[Tuple] = []
    failed: List[Tuple] = []

    def _worker(task):
        return call_model_unified(task, raw_analysis)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(16, len(tasks))
    ) as exe:
        future_to_task = {exe.submit(_worker, t): t for t in tasks}
        for fut in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[fut]
            try:
                r = fut.result()
                if r and r[5]:
                    completed.append(r)
                else:
                    failed.append(task)
            except Exception:
                failed.append(task)

    # 若仍有失敗任務，再走一次同步重試
    for task in failed:
        try:
            r = call_model_unified(task, raw_analysis)
            if r and r[5]:
                completed.append(r)
        except Exception:
            pass

    # --------- 3. 組裝 HTML ---------
    # 依舊的邏輯整理 header / content，確保順序正確
    for (
        task_type,
        s_idx,
        s_title,
        ss_idx,
        target_title,
        html,
    ) in completed:
        if task_type == "subtopic":
            key_header = f"_{s_idx:02d}_00_{s_title}_header"
            key_body   = f"_{s_idx:02d}_01_{s_title}_content"
            if key_header not in sections:
                sections[key_header] = f"<h2>{get_heading_prefix(2, s_idx)} {s_title}</h2>"
            sections[key_body] = html
        else:
            parent_header = f"_{s_idx:02d}_00_{s_title}_header"
            if parent_header not in sections:
                sections[parent_header] = f"<h2>{get_heading_prefix(2, s_idx)} {s_title}</h2>"
            key = f"_{s_idx:02d}_{ss_idx+1:02d}_{target_title}"
            if not html.startswith("<h3"):
                html = f"<h3>{get_heading_prefix(3, ss_idx)} {target_title}</h3>" + html
            sections[key] = html

    return sections


def _insert_chart(chart, result, title_to_key, path_to_key, charts, word_charts) -> None:
    """把單一 chart 依規則插進 HTML，並填 chart / word_charts dict"""
    chart_id = chart.get("chart_id") or uuid.uuid4().hex[:8]
    title_text = chart.get("title_text", f"圖表-{chart_id}")
    img_html = chart.get("img_html")
    if not img_html:
        return
    
    # ---- 先判斷是不是 html ----
    if isinstance(img_html, dict):                # 已經被 _process_vanna_result 下載回來
        html_str = img_html.get("bytes", b"").decode("utf-8", "ignore")
        chart_html = html_str                     # 直接把整份 plotly html 塞進 iframe
        img_bytes = img_html.get("bytes")         # 保留給 Word 匯出用
        img_b64 = None
    elif isinstance(img_html, str) and img_html.endswith(".html"):
        # S3 連結還沒下載；直接 iframe 指向外部檔
        chart_html = f"<iframe src='{img_html}' style='width:100%;height:100%;border:none;'></iframe>"
        img_bytes = None
        img_b64 = None
    else:
        # 真的就是 png/jpg
        img_bytes, img_b64 = _prepare_bytes_b64(img_html)
        chart_html = f"<img src='data:image/png;base64,{img_b64}' style='max-width:100%;height:auto;'/>" \
                     if img_b64 else f"<img src='{img_html}' style='max-width:100%;height:auto;'/>"

    charts[chart_id] = {
        "title_text": title_text,
        "html": chart_html,
        "static": img_bytes or img_html,
    }

    # --- 決定放哪 ---
    target_key = _find_target_key(chart, title_to_key, path_to_key, result)
    if not target_key:
        logger.error("no place for chart: %s", title_text)
        return

    # --- 寫佔位符、收資料 ---
    html_plh = create_chart_placeholder(chart_id)
    result[target_key] += (
        f"\n{html_plh}\n<div class='word-chart-placeholder'>[WORD_CHART_{chart_id}]</div>\n"
    )

    page = extract_page_name_from_key(target_key)
    word_charts.setdefault(page, []).append(
        {
            "chart_id": chart_id,
            "title_text": title_text,
            "img_html_b64": img_b64,
            "placeholder": f"[WORD_CHART_{chart_id}]",
            "target_section": page,
            "target_key": target_key,
            "target_path": chart.get("target_path", ""),
        }
    )


# ==========================================================================
# build_output_format 更小的工具函式（只做單一簡單任務）
# ==========================================================================
def _prepare_bytes_b64(img_html):
    """dict/bytes/URL 統一回 (bytes, b64_str | None)"""
    if isinstance(img_html, dict):
        return img_html.get("bytes"), img_html.get("b64")
    if isinstance(img_html, (bytes, bytearray)):
        b = bytes(img_html)
        return b, base64.b64encode(b).decode()
    return None, None  # URL

def _find_target_key(chart, title_to_key, path_to_key, result):
    """依五層優先序找 section key"""

    # 1. 直接比對 target_path
    tp = chart.get("target_path", "")
    if tp and tp in path_to_key:
        return path_to_key[tp]

    # 2 context
    ctx = chart.get("context", "")
    for t, k in title_to_key.items():
        if t in ctx:
            return k

    # 3 question
    q = chart.get("question", "")
    for t, k in title_to_key.items():
        if t in q:
            return k

    # 4 title_text
    tt = chart.get("title_text", "").replace("(發票數據)", "").strip()
    for t, k in title_to_key.items():
        if tt in t or t in tt:
            return k

    # 5 fallback：第一個非 header 的 key
    for k in sorted(result):
        if not k.endswith("_header"):
            return k
    return None

# ------------------------------------------------------------------
# ------------------------------------------------------------------
# ------------------------------------------------------------------

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
        target_title = subtopic_title
        heading_level = 2
        prefix = get_heading_prefix(2, subtopic_idx)
        # 從 output_format 獲取對應的 prompt
        subtopic_prompt = get_subtopic_prompt(subtopic_title)
    else:
        target_title = subsubtopic_title
        heading_level = 3
        prefix = get_heading_prefix(3, subsubtopic_idx)
        # 從 output_format 獲取對應的 prompt
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
    # 直接從快取拿
    for main_topic, main_data in _CURRENT_OUTPUT_FORMAT.items():
        for subtopic in main_data.get("subtopics", []):
            if subtopic["title"] == subtopic_title:
                return subtopic.get("prompt", f"請分析 {subtopic_title} 相關內容")
    return f"請分析 {subtopic_title} 相關內容"

def get_subsubtopic_prompt(subtopic_title: str, subsubtopic_title: str) -> str:
    for main_topic, main_data in _CURRENT_OUTPUT_FORMAT.items():
        for subtopic in main_data.get("subtopics", []):
            if subtopic["title"] == subtopic_title:
                for subsub in subtopic.get("subsubtopics", []):
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

        logger.debug("Agent response: %s", answer_raw)
        logger.info(f"找到 {len(txt2figure_results)} 個圖表")

        # 2. Format to HTML JSON with smart chart placement
        logger.info("📊 格式化內容並插入圖表...")
        output_data = build_output_format(answer_raw, topic, txt2figure_results, company_info)
        
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