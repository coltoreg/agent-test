"""
vanna_service.py - Vanna服務封裝，處理與OpenSearch和Athena的交互
"""
import os
import json
import time
import uuid
import datetime
import traceback
from typing import Any, Dict, List, Callable, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from functools import wraps
import pandas as pd
import plotly.io as pio

from vanna.opensearch import OpenSearch_VectorStore
from vanna.bedrock import Bedrock_Converse

from utils.logger import setup_logger
from utils.exceptions import ValidationError, ExternalAPIError
from utils.temp_llm import claude_call, parse_claude_json
from models.vanna import CompanyInfo, OutputFormat, QueryItem
from services.connections import Connections

# 按照官方加入 https://pypi.org/project/kaleido/
# kaleido.get_chrome_sync()

logger = setup_logger(__name__)

# 設定超時時間 (秒)
CHART_GENERATION_TIMEOUT = 120

class VannaService(OpenSearch_VectorStore, Bedrock_Converse):
    """
    Vanna服務類，整合OpenSearch向量儲存和Bedrock對話能力，以及Athena連接
    """
    
    def __init__(self):
        """初始化VannaService，連接OpenSearch和Bedrock"""
        # 初始化連接
        self.conn = Connections()
        self.env = self.conn.env
        
        # 設定索引名稱
        self.document_index = self.env.OS_DOC_INDEX
        self.ddl_index = self.env.OS_DDL_INDEX
        self.question_sql_index = self.env.OS_QSQL_INDEX
        self.s3_bucket = self.env.OUTPUT_S3_BUCKET
        
        # 獲取Openseach主機
        os_host = os.getenv("OPENSEARCH_HOST", "")
        if not os_host:
            raise ValidationError("OpenSearch host not specified in environment variables")
        
        os_host = os_host.removeprefix("https://")
        
        # 使用Connections創建Bedrock客戶端
        bedrock_client = self.conn.bedrock_client()
        
        # 初始化Bedrock會話
        Bedrock_Converse.__init__(
            self,
            client=bedrock_client,
            config={
                "modelId": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "temperature": float(0.0),
                "max_tokens": int(50000),
            },
        )
        
        # 使用Connections創建OpenSearch客戶端
        self.opensearch_client = self.conn.opensearch_client(os_host)
        
        # 驗證索引已存在
        self._verify_indices()
        
        # 設定SQL運行函數初始狀態
        self.run_sql_is_set = False
        self.dialect = None

    def safe_execute(self, func, *args, **kwargs):
        """安全執行函數，捕獲並記錄異常"""
        try:
            return func(*args, **kwargs), None
        except Exception as e:
            logger.error(f"安全執行失敗: {str(e)}")
            logger.error(f"堆疊追蹤: {traceback.format_exc()}")
            return None, str(e)

    def gen_ts_random_id(self) -> str:
        """生成帶時間戳的隨機 ID"""
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            rand_suffix = str(uuid.uuid4().int)[:8]
            return f"{ts}_{rand_suffix}"
        except Exception as e:
            logger.warning(f"生成 ID 失敗，使用備用方案: {str(e)}")
            return f"fallback_{int(time.time())}"

    def extract_company_info(
        self,
        input_text: str,
        info: CompanyInfo
    ) -> CompanyInfo:
        """提取公司/品牌/產品/類別/目標標題資訊"""

        try:
            # 1. 所有欄位已齊，直接回傳原 info
            if all([
                info.company,
                info.brand,
                info.product,
                info.product_category,
                info.target_title
            ]):
                return info

            # 2. 使用 Claude 補全缺失欄位
            system_prompt = (
                "You are a JSON-extraction assistant.\n"
                "From the user's message, identify company, brand, product, "
                "product_category, and target_title.\n"
                "Return one minified JSON exactly like "
                '{"company":"","brand":"","product":"","product_category":"","target_title":""} '
                "with missing values as empty strings. No extra text."
            )

            logger.info("正在使用 Claude 提取公司資訊")
            raw_json, error = self.safe_execute(claude_call, system_prompt, input_text)

            if error:
                logger.warning(f"Claude 呼叫失敗: {error}")
                return info

            try:
                parsed = json.loads(raw_json)
                parsed = parse_claude_json(parsed)  # 可選的格式清理函數
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"解析 Claude 回應失敗: {str(e)}")
                return info

            # 合併原始與 Claude 的資訊（Claude 僅補缺欄位）
            return CompanyInfo(
                company=info.company or parsed.get("company", ""),
                brand=info.brand or parsed.get("brand", ""),
                product=info.product or parsed.get("product", ""),
                product_category=info.product_category or parsed.get("product_category", ""),
                target_title=info.target_title or parsed.get("target_title", "")
            )

        except Exception as e:
            logger.error(f"提取公司資訊時發生錯誤: {str(e)}")
            return info

    def setup_training(self) -> bool:
        """設定 Vanna 訓練資料"""
        try:
            # 取得 Athena 查詢執行器
            run_sql, error = self.safe_execute(self.conn.athena_query_runner)
            if error:
                logger.error(f"取得 Athena 查詢執行器失敗: {error}")
                return False
            
            # 設定 Athena 連接
            self.set_athena_connection(run_sql)
            
            # 獲取 schema 資訊
            schema_sql = "SELECT * FROM information_schema.columns WHERE table_schema = 'default' AND table_name = 'invoice_data_invdate'"
            df_information_schema, error = self.safe_execute(self.run_sql, schema_sql)
            
            if error:
                logger.error(f"獲取 schema 資訊失敗: {error}")
                return False
            
            if df_information_schema is None:
                logger.error("schema 資訊為空")
                return False
            
            logger.info(f"成功獲取 schema 資訊")
            
            # 獲取訓練計劃
            plan, error = self.safe_execute(self.get_training_plan_generic, df_information_schema)
            if error:
                logger.error(f"獲取訓練計劃失敗: {error}")
                return False
            
            logger.info(f"成功獲取訓練計劃: {plan}")
            
            # 執行訓練
            return self._execute_training_tasks(plan)
            
        except Exception as e:
            logger.error(f"設定 Vanna 訓練時發生錯誤: {str(e)}")
            return False

    def _execute_training_tasks(self, plan) -> bool:
        """執行訓練任務"""
        training_tasks = [
            (self.train, {"plan": plan}),
            (self.train, {
                "documentation": """
                CRITICAL INSTRUCTIONS - YOU MUST FOLLOW THESE RULES:
                1. ALWAYS RETURN ONLY VALID AWS ATHENA SQL QUERIES
                2. NEVER return explanatory text, disclaimers, or any non-SQL content
                3. If you cannot generate a SQL query, return: SELECT 'No valid query available' as message
                4. Queries must not reference columns that do not exist in this schema.
                5. Always query the "default"."invoice_data_invdate" table
                6. ALL QUERIES MUST INCLUDE invDate FILTERING.;

                DATABASE SCHEMA:
                Table: "default"."invoice_data_invdate"

                COLUMNS AVAILABLE:
                inv_num (invoice number),
                aaid (Android device id),
                idfa (iOS device id),
                vid (user_id),
                invDate (yyyy-mm-dd,date, invoice issue date, partitioned columns), 
                invTime (time, invoice issue time), 
                sellerName (merchant official name), 
                storeName (merchant nickname or store alias), 
                sellerAddress (merchant address in half-width characters), 
                description (product name on invoice), 
                unit_Price (float, price per product), 
                quantity (float, purchased quantity), 
                birthday (YYYY-MM-DD, inferred user birthday),
                gender (inferred user gender),
                amount (integer, total invoice amount)

                
                <error_check>
                If there's an error, I'll explain:
                - What went wrong
                - Why it happened
                - How to fix it
                </error_check>
                """,
                "plan": plan
            })
        ]
        
        # 添加範例訓練
        training_examples = self._get_training_examples(plan)
        training_tasks.extend([(self.train, example) for example in training_examples])
        
        # 執行所有訓練任務
        success_count = 0
        for task_func, task_kwargs in training_tasks:
            _, error = self.safe_execute(task_func, **task_kwargs)
            if error:
                logger.warning(f"訓練任務失敗: {error}")
            else:
                success_count += 1
        
        logger.info(f"完成訓練，成功 {success_count}/{len(training_tasks)} 個任務")
        return success_count > 0

    def _get_training_examples(self, plan) -> List[Dict]:
        """取得訓練範例"""
        return [
            {
                "question": "4月份銷售數前10名的商品",
                "sql": """
                SELECT
                    description AS product_name,
                    SUM(quantity) AS total_sales_counts
                FROM
                    "default"."invoice_data_invdate"
                WHERE
                    invDate BETWEEN '2025-04-01' AND '2025-04-30'
                GROUP BY
                    description
                ORDER BY
                    total_sales_counts DESC
                LIMIT 10;
                """,
                "plan": plan
            },
            {
                "question": "4月份銷售額前10名的商品",
                "sql": """
                SELECT
                    description AS product_name,
                    SUM(unit_Price * quantity) AS total_sales_amount
                FROM
                    "default"."invoice_data_invdate"
                WHERE
                    invDate BETWEEN '2025-04-01' AND '2025-04-30'
                GROUP BY
                    description
                ORDER BY
                    total_sales_amount DESC
                LIMIT 10;
                """,
                "plan": plan
            },
            {
                "question": "4月份 storeName 銷售佔比",
                "sql": """
                WITH total_sales AS (
                    SELECT 
                        SUM(amount) AS total_amount
                    FROM 
                        "default"."invoice_data_invdate"
                    WHERE 
                        invDate BETWEEN '2025-04-01' AND '2025-04-30'
                )
                SELECT 
                    storeName,
                    SUM(amount) AS store_total_sales,
                    ROUND((SUM(amount) * 100.0) / (SELECT total_amount FROM total_sales), 2) AS sales_percentage
                FROM 
                    "default"."invoice_data_invdate"
                WHERE 
                    invDate BETWEEN '2025-04-01' AND '2025-04-30'
                GROUP BY 
                    storeName
                ORDER BY 
                    sales_percentage DESC;
                """,
                "plan": plan
            },
            {
                "question": "4月份性別的銷售額和平均發票金額",
                "sql": """
                WITH distinct_invoices AS (
                    SELECT
                        gender,
                        inv_num,
                        MAX(amount) AS invoice_amount
                    FROM
                        "default"."invoice_data_invdate"
                    WHERE
                        invDate BETWEEN '2025-04-01' AND '2025-04-30'
                    GROUP BY
                        gender, inv_num
                )
                SELECT
                    gender,
                    SUM(invoice_amount) AS total_sales_amount,
                    ROUND(AVG(invoice_amount), 2) AS avg_invoice_amount,
                    COUNT(*) AS invoice_count
                FROM
                    distinct_invoices
                GROUP BY
                    gender
                ORDER BY
                    total_sales_amount DESC;
                """,
                "plan": plan
            }
        ]

    def plotly_to_html(self, fig) -> Optional[bytes]:
        """
        將 Plotly 圖表轉為 HTML bytes  
        - 只負責『轉換』，不上傳，符合 SRP
        """
        try:
            if fig is None:
                return None

            logger.info("Converting figure to HTML")
            html_str = pio.to_html(
                fig,
                include_plotlyjs="cdn",
                full_html=True,
                auto_play=False,
            )
            return html_str.encode("utf-8")
        except Exception as e:
            logger.error(f"Error generating HTML: {e}")
            return None

    def generate_single_chart(
            self, 
            question: str, 
            uu_id_str: str, 
            index: int, 
            target_path: str = ""
        ) -> Dict[str, Any]:
        """生成單一圖表"""
        try:
            logger.info(f"正在生成圖表 {index}")
            logger.info(f"問題: {question.strip()}")
            
            # 使用 Vanna 生成結果
            result, error = self.safe_execute(
                self.ask,
                question=question.strip(),
                allow_llm_to_see_data=True,
                print_results=True,
            )
            #logger.info(f"Vanna ask 結果: {result}")
            
            if error:
                logger.error(f"Vanna ask 失敗: {error}")
                return {
                    "title_text": f"錯誤: {question[:30]}...",
                    "img_html": None,
                    "error": error
                }
            
            if not result or len(result) < 3:
                logger.warning(f"Vanna 回應格式不正確: {result}")
                return {
                    "title_text": f"無結果: {question[:30]}...",
                    "img_html": None,
                    "error": "無有效結果"
                }
            
            fig = result[2] if len(result) > 2 else None
            title_text = "無標題"
            img_html_content = None
            
            if fig is not None:
                try:
                    # 取得圖表標題
                    title_text = fig.layout.title.text if fig.layout.title else f"圖表 {index + 1}"
                    
                    # 更新圖表佈局
                    fig.update_layout(
                        margin=dict(l=40, r=20, t=60, b=120),
                        xaxis_tickangle=-45,
                        autosize=True
                    )
                    
                    # 產生 HTML 並上傳
                    html_bytes = self.plotly_to_html(fig)
                    if html_bytes:
                        s3_url, upload_error = self.safe_execute(
                            self.upload_html_to_s3,
                            uu_id_str,
                            index,
                            html_bytes,
                        )
                        if not upload_error and s3_url:
                            img_html_content = s3_url
                    
                except Exception as e:
                    logger.error(f"處理圖表時發生錯誤: {str(e)}")
                    title_text = f"處理錯誤: {question[:30]}..."
            
            vanna_result = {
                "title_text": title_text,
                "img_html": img_html_content,
                "question": question,
                "target_path": target_path
            }
            
            logger.info(f"圖表 {index} 生成完成，標題為: {title_text}")
            return vanna_result
            
        except Exception as e:
            logger.error(f"生成圖表 {index} 時發生未預期錯誤: {str(e)}")
            return {
                "title_text": f"錯誤: {question[:30]}...",
                "img_html": None,
                "error": str(e)
            }

    def generate_charts_parallel(self, sql_queries: List[QueryItem], uu_id_str: str) -> Tuple[Dict[str, Any], int]:
        """並行生成圖表"""
        results = {}
        successful_results = 0
        
        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                # 提交任務，使用 title 作為 key
                future_to_key = {
                    executor.submit(
                        self.generate_single_chart, 
                        query["question"], 
                        uu_id_str, 
                        i,
                        query["path"]
                    ): query["title"]
                    for i, query in enumerate(sql_queries)
                }
                
                # 處理結果
                for future in as_completed(future_to_key, timeout=CHART_GENERATION_TIMEOUT):
                    try:
                        key = future_to_key[future]
                        result = future.result(timeout=10)
                        results[key] = result
                        
                        if result.get("img_html"):
                            successful_results += 1
                            
                    except Exception as e:
                        key = future_to_key[future]
                        logger.error(f"任務 {key} 執行失敗: {str(e)}")
                        results[key] = {
                            "title_text": f"任務失敗: {key}",
                            "img_html": None,
                            "error": str(e)
                        }
        
        except TimeoutError:
            logger.error("圖表生成超時")
            # 填充未完成的結果
            for future, key in future_to_key.items():
                if key not in results:
                    results[key] = {
                        "title_text": f"任務超時: {key}",
                        "img_html": None,
                        "error": "執行超時"
                    }
        
        return results, successful_results

    def collect_sql_queries(self, output_format: OutputFormat) -> List[QueryItem]:
        """
        從巢狀結構中蒐集所有非空白的 sql_text。
        - 支援 sql_text 是字串或 list[str]
        - 自動排除完全為空的 [""] 或 ["  "]
        """
        queries = []

        def traverse(node, path=""):
            if not isinstance(node, dict):
                return

            # 1️⃣ 整理出目前節點的 sql_text（若有）
            if "sql_text" in node:
                raw_sql = node["sql_text"]

                # 讓 raw_sql 一律變成 list，便於統一處理
                if isinstance(raw_sql, str):
                    raw_sql = [raw_sql]

                if isinstance(raw_sql, list):
                    for idx, sql in enumerate(raw_sql):
                        # 保留「strip 後仍有內容」的 sql
                        if isinstance(sql, str) and sql.strip():
                            queries.append(
                                {
                                    "question": sql.strip(),
                                    "title": node.get("title", ""),
                                    "path": path,
                                    "index": idx,
                                }
                            )

            # 2️⃣ 繼續往下走訪巢狀結構
            for key, value in node.items():
                if key in ("subtopics", "subsubtopics"):
                    # 這兩個鍵一定是 list
                    for idx, item in enumerate(value):
                       new_path = f"{path}.{key}.{idx}" if path else f"{key}.{idx}"
                       traverse(item, new_path)
                elif isinstance(value, dict):
                    traverse(value, f"{path}.{key}" if path else key)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            traverse(item, f"{path}.{key}" if path else key)

        traverse(output_format)
        return queries


    def get_sql_input(self, info: CompanyInfo) -> OutputFormat:

        input_company = info.company
        input_brand = info.brand
        input_product = info.product
        product_category = info.product_category
        input_target_title = info.target_title

        
        input_date = "2025年4月"
        
        output_format = {
            "市場概況與趨勢": {
                "title": "市場概況與趨勢",
                "subtopics": [
                    {
                        "title": "產業規模與成長",
                        "subsubtopics": [
                            {
                                "title": "台灣市場規模與成長",
                                "sql_text": [""]
                            },
                            {
                                "title": "產品類型演進",
                                "sql_text": [""]
                            },
                            {
                                "title": "年度銷售變化",
                                "sql_text": [""]
                            },
                            {
                                "title": "驅動因素與未來展望",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "主導品牌分析",
                        "subsubtopics": [
                            {
                                "title": "主導品牌銷售概況",
                                "sql_text": [f"""
                                {input_date}銷售{input_brand} {input_product}前10名的品牌，
                                    1.請找出與 {input_brand} 在 {input_product} 市場的主要競爭品牌，要求：
                                    1.列出 10 個直接競爭對手
                                    2.包含國際知名品牌和本土品牌
                                    3.確保這些品牌都有生產類似{input_product}的產品
                                2.請撰寫一個 AWS Athena SQL 查詢，用於比較各品牌間的銷售額，要求
                                    1.使用 CASE WHEN 語句來分類品牌
                                    2.使用正則表達式提取品牌名稱
                                    3.計算每個競爭品牌的總銷售額
                                    4.將{input_brand}單獨歸類
                                    5.非競爭品牌歸類為 "其他品牌"
                                    6.結果適合用於製作圓餅圖
                                3. 銷售額是 unit_price * quantity
                                請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                                請優化產生的 Plotly 圖表，要求如下：
                                1. 使用乾淨現代的風格（白色背景、清晰字體、可讀性高的標籤）。
                                2. 調整版面配置（包含圖表標題、座標軸標籤、邊距等）。
                                3. 增加互動性功能，例如提示框（tooltip）、縮放、拖曳移動。
                                4. 請使用 `plotly.offline.plot()` 或 `fig.to_html()` 將圖表轉換為獨立的 HTML 字串，可嵌入網頁使用。
                                5. 請只回傳 HTML 字串，不要回傳圖表物件。
                                6. 所有必要的 JS/CSS 請內嵌，確保離線也可顯示。
                                目的是讓圖表在網站上呈現時更美觀且專業。
                                """]
                            },
                            {
                                "title": "價格帶分析",
                                "sql_text": [""]
                            },
                            {
                                "title": "平價帶市場概況",
                                "sql_text": [f"""
                                {input_date}銷售{input_brand} {input_product}前10名的品牌，
                                    1.請找出與 {input_brand} 在 {input_product} 市場的主要競爭品牌，要求：
                                    1.列出 5 個直接競爭對手品牌定向是平價品牌
                                    2.包含國際知名品牌和本土品牌
                                    3.確保這些品牌都有生產類似{input_product}的產品
                                2.請撰寫一個 AWS Athena SQL 查詢，用於比較各品牌間的銷售額，要求
                                    1.使用 CASE WHEN 語句來分類品牌
                                    2.使用正則表達式提取品牌名稱
                                    3.計算每個競爭品牌的總銷售額
                                    4.將{input_brand}單獨歸類
                                    5.非競爭品牌歸類為 "其他品牌"
                                    6.結果適合用於製作圓餅圖
                                3. 銷售額是 unit_price * quantity
                                請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                                請優化產生的 Plotly 圖表，要求如下：
                                1. 使用乾淨現代的風格（白色背景、清晰字體、可讀性高的標籤）。
                                2. 調整版面配置（包含圖表標題、座標軸標籤、邊距等）。
                                3. 增加互動性功能，例如提示框（tooltip）、縮放、拖曳移動。
                                4. 請使用 `plotly.offline.plot()` 或 `fig.to_html()` 將圖表轉換為獨立的 HTML 字串，可嵌入網頁使用。
                                5. 請只回傳 HTML 字串，不要回傳圖表物件。
                                6. 所有必要的 JS/CSS 請內嵌，確保離線也可顯示。
                                目的是讓圖表在網站上呈現時更美觀且專業。

                                """]
                            },
                            {
                                "title": "高價帶市場概況",
                                "sql_text": [f"""
                                {input_date}銷售{input_brand} {input_product}前10名的品牌，
                                    1.請找出與 {input_brand} 在 {input_product} 市場的主要競爭品牌，要求：
                                    1.列出 5 個直接競爭對手品牌定向是高端品牌
                                    2.包含國際知名品牌和本土品牌
                                    3.確保這些品牌都有生產類似{input_product}的產品
                                2.請撰寫一個 AWS Athena SQL 查詢，用於比較各品牌間的銷售額，要求
                                    1.使用 CASE WHEN 語句來分類品牌
                                    2.使用正則表達式提取品牌名稱
                                    3.計算每個競爭品牌的總銷售額
                                    4.將{input_brand}單獨歸類
                                    5.非競爭品牌歸類為 "其他品牌"
                                    6.結果適合用於製作圓餅圖
                                3. 銷售額是 unit_price * quantity
                                請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                                請優化產生的 Plotly 圖表，要求如下：
                                1. 使用乾淨現代的風格（白色背景、清晰字體、可讀性高的標籤）。
                                2. 調整版面配置（包含圖表標題、座標軸標籤、邊距等）。
                                3. 增加互動性功能，例如提示框（tooltip）、縮放、拖曳移動。
                                4. 請使用 `plotly.offline.plot()` 或 `fig.to_html()` 將圖表轉換為獨立的 HTML 字串，可嵌入網頁使用。
                                5. 請只回傳 HTML 字串，不要回傳圖表物件。
                                6. 所有必要的 JS/CSS 請內嵌，確保離線也可顯示。
                                目的是讓圖表在網站上呈現時更美觀且專業。

                                """]
                            },
                            {
                                "title": "價格帶結構與策略定位",
                                "sql_text": [""] #Table not ready
                            },
                            {
                                "title": "價格帶市佔變化趨勢",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "消費者痛點與聲量",
                        "subsubtopics": [
                            {
                                "title": "痛點分析",
                                "sql_text": [""]
                            },
                            {
                                "title": "正面熱點事件",
                                "sql_text": [""]
                            },
                            {
                                "title": "負面熱點事件",
                                "sql_text": [""]
                            },
                            {
                                "title": "聲量與情緒趨勢",
                                "sql_text": [""]
                            },
                            {
                                "title": "痛點轉化機會",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "未來政策與永續趨勢",
                        "subsubtopics": [
                            {
                                "title": "國際政策動向",
                                "sql_text": [""]
                            },
                            {
                                "title": "台灣政策動向",
                                "sql_text": [""]
                            },
                            {
                                "title": "ESG 與永續議題",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "市場概況與趨勢總結",
                        "subsubtopics": [
                            {
                                "title": "市場概況總結",
                                "sql_text": [""]
                            },
                            {
                                "title": "為何這些變化重要",
                                "sql_text": [""]
                            },
                            {
                                "title": "品牌該如何應對市場變化",
                                "sql_text": [""]
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
                                "sql_text": [""]
                            },
                            {
                                "title": "功能定位分析",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "品牌形象",
                        "subsubtopics": [
                            {
                                "title": "品牌關鍵字",
                                "sql_text": [""]
                            },
                            {
                                "title": "品牌視覺元素",
                                "sql_text": [""]
                            },
                            {
                                "title": "品牌標語",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "獨特銷售主張（USP）",
                        "sql_text": [""]
                    }
                ]
            },
            "產品分析": {
                "title": "產品分析",
                "subtopics": [
                    {
                        "title": "產品獨特銷售主張（USP）",
                        "sql_text": [""]
                    },
                    {
                        "title": "產品使用情境",
                        "sql_text": [""]
                    },
                    {
                        "title": "產品銷量",
                        # "sql_text": [""]
                        "sql_text": [f"""
                        {input_date} {input_product}銷售量在 {input_brand} 的占比，
                        1.請撰寫一個 AWS Athena SQL 查詢
                        2.銷售量是 sum(quantity)
                        3.結果適合用於製作圓餅圖
                        請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                        """]
                    },
                    {
                        "title": "產品銷售通路",
                        # "sql_text": [""]
                        "sql_text": [f"""
                        {input_date} {input_product}在storeName 的購買人數(distinct vid)，給前10名 storeName，前10名之後的 storeName 統一為其他
                        1.第一個子句先去除 storeName 是 NaN (storeName not like '%NaN%'),日期和 description like '%{input_brand}%'或 '%{input_product}%'
                        2.結果適合於製作長條圖
                        請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                        """]
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
                                # "sql_text": [""]
                                "sql_text": [f"""
                                找出{input_date}購買{input_brand} {input_product}年齡和性別的佔比，
                                1.需要不重複的人數(distinct vid)
                                2.年齡分成 18-24, 25-34, 35-44, 45-54, 55-64, 65+
                                3.性別分成 男性, 女性
                                4.X 軸是年齡，Y 軸是百分比佔比，維度是性別
                                5.請撰寫一個 AWS Athena SQL 查詢，使用長條圖顯示年齡和性別的百分比佔比
                                請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                               """]
                            },
                            {
                                "title": "消費習慣",
                                # "sql_text": [""]
                                "sql_text": [f"""
                                找出{input_date}購買{input_brand} {input_product}年齡和性別發票平均金額，
                                1.年齡分成 18-24, 25-34, 35-44, 45-54, 55-64, 65+
                                2.性別分成 男性, 女性
                                3.一張發票會有很多的產品，每個產品的 amount都是一樣，但這是不對，要寫一個子句找出 每個 inv_num 的MAX(amount) AS invoice_amount
                                4.X 軸是年齡，Y 軸是發票平均金額，維度是性別
                                5.請撰寫一個 AWS Athena SQL 查詢，使用長條圖顯示年齡和性別的發票平均金額
                                請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                                """]
                            },
                            {
                                "title": "購買動機",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "商品目標受眾分析",
                        "subsubtopics": [
                            {
                                "title": "人口屬性",
                                "sql_text": [""]
                            },
                            {
                                "title": "消費習慣",
                                "sql_text": [""]
                            },
                            {
                                "title": "購買動機",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "代表性消費者輪廓（Persona）",
                        "sql_text": [""]
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
                                "sql_text": [""]
                            },
                            {
                                "title": "功能定位比較",
                                "sql_text": [""]
                            },
                            {
                                "title": "使用情境對照",
                                "sql_text": [""]
                            }
                        ]
                    },
                    {
                        "title": "競品銷售狀況分析",
                        # "sql_text": [""]
                        "sql_text": [f"""
                        找出{input_date}銷售 / 發票張數 / 不重複cid {input_brand} {input_product}前10名的品牌，
                        1.請找出與{input_brand} {input_product}市場的主要競爭品牌，要求：
                          1.列出 10 個直接競爭對手，
                          2.包含國際知名品牌和本土品牌
                          3.確保這些品牌都有生產類似鑽高效防曬露NA 5X版的產品
                        2.請撰寫一個 AWS Athena SQL 查詢，用於比較各品牌間的銷售額，要求
                          1.使用 CASE WHEN 語句來分類品牌
                          2.使用正則表達式提取品牌名稱
                          3.計算每個競爭品牌的總銷售額
                          4.將{input_brand}單獨歸類
                          5.非競爭品牌歸類為 "其他品牌"
                          6.結果適合用於製作長條圖，圖不需要其他品牌
                        3. 銷售額是 unit_price * quantity
                        4. 發票張數是 count(distinct inv_num)
                        5. 不重複cid是 count(distinct vid)
                        6. 結果適合用於製作長條圖，圖不需要其他品牌，x 軸是品牌，y 軸是百分比，維度是銷售佔比, 發票張數, 不重複cid
                        7. 只需要一張圖，圖的顏色要區分銷售佔比, 發票張數, 不重複cid
                        請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                        """]
                    },
                    {
                        "title": "代表通路銷量對比",
                        "subsubtopics": [
                            {
                                "title": "電商平台銷量對比",
                                # "sql_text": [""]
                                "sql_text": [f"""
                                找出{input_date}銷售額 {input_brand} {input_product}前10名的品牌，先寫出一個字句找出 storeName 是電子商務平台的條件，例如 MOMO, PChome, Yahoo, 蝦皮, 請根據實際情況修改，
                                1.請找出與{input_brand} {input_product}市場的主要競爭品牌，要求：
                                  1.列出 10 個直接競爭對手，
                                  2.包含國際知名品牌和本土品牌
                                  3.確保這些品牌都有生產類似{input_product}的產品
                                2.請撰寫一個 AWS Athena SQL 查詢，用於比較各品牌間的銷售額，要求
                                  1.使用 CASE WHEN 語句來分類品牌
                                  2.使用正則表達式提取品牌名稱
                                  3.計算每個競爭品牌的總銷售額
                                  4.將{input_brand}單獨歸類
                                  5.非競爭品牌歸類為 "其他品牌"
                                  6.結果適合用於製作長條圖，圖不需要其他品牌
                                3. 銷售額是 unit_price * quantity
                                6. 結果適合用於製作長條圖，圖不需要其他品牌，x 軸是storeName，y 軸是銷售額，維度是品牌名稱(不需要堆疊),
                                7. 只需要一張圖，圖的顏色要區分銷售額
                                請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                                """]
                            },
                            {
                                "title": "線下通路銷量對比",
                                # "sql_text": [""]
                                "sql_text": [f"""
                                找出{input_date}銷售額 {input_brand} {input_product}前10名的品牌
                                1.先寫出一個字句排除 storeName 是電子商務平台的條件，例如 MOMO, PChome, Yahoo, 蝦皮, 請根據實際情況修改，
                                2.storeName 是 NaN (storeName not like '%NaN%') 也需要排除
                                3.只需要銷售額前10名的storeName 和銷售額前5名的品牌
                                4.請找出與{input_brand} {input_product}市場的主要競爭品牌，要求：
                                  1.列出 10 個直接競爭對手，
                                  2.包含國際知名品牌和本土品牌
                                  3.確保這些品牌都有生產類似{input_product}的產品
                                5.請撰寫一個 AWS Athena SQL 查詢，用於比較各品牌間的銷售額，要求
                                  1.使用 CASE WHEN 語句來分類品牌
                                  2.使用正則表達式提取品牌名稱
                                  3.計算每個競爭品牌的總銷售額
                                  4.將{input_brand}單獨歸類
                                  5.非競爭品牌歸類為 "其他品牌"
                                  6.結果適合用於製作長條圖，圖不需要其他品牌
                                6. 銷售額是 unit_price * quantity
                                7. 結果適合用於製作長條圖，圖不需要其他品牌，x 軸是storeName，y 軸是銷售額，維度是品牌名稱,
                                8. 只需要一張圖，圖的顏色要區分銷售佔比
                                請提供完整的 SQL 查詢語句，要確保 Query 裡面不會有特殊符號會導致 Query 失敗，Query 出來之後，再檢查一次 Query，確保可以直接在 AWS Athena 中執行。
                                """]
                            }
                        ]
                    },
                    {
                        "title": "競品獨特銷售主張（USP）",
                        "sql_text": [""]
                    },
                    {
                        "title": "與競品之優劣分析",
                        "sql_text": [""]
                    }
                ]
            }
        }

        # 如果指定了 input_target_title，只返回該主題
        if input_target_title and input_target_title in output_format:
            return {input_target_title: output_format[input_target_title]}
        
        return output_format
    
    def upload_html_to_s3(self, uu_id: str, idx: int, html_bytes: bytes) -> str:
        """將 HTML bytes 上傳至 S3，回傳公開 URL（SRP：單一職責：上傳）"""
        key = f"vanna/{uu_id}/fig_{idx}.html"
        s3_client = self.conn.s3_client_fbmapping()
        s3_client.put_object(
            Bucket=self.s3_bucket,
            Key=key,
            Body=html_bytes,
            ContentType="text/html",
        )
        logger.info(f"Uploaded HTML to S3: {key}")
        return f"https://{self.s3_bucket}.s3.amazonaws.com/{key}"
        
    def _verify_indices(self) -> None:
        """驗證必要的索引是否存在"""
        indices = [self.document_index, self.ddl_index, self.question_sql_index]
        for idx in indices:
            try:
                if not self.opensearch_client.indices.exists(index=idx):
                    logger.warning(f"Index {idx} does not exist")
                else:
                    logger.info(f"Index {idx} exists")
            except Exception as e:
                logger.error(f"Error checking index {idx}: {e}")
                raise ValidationError(f"Failed to check OpenSearch index {idx}: {e}")
    
    def set_athena_connection(self, run_sql_func: Callable[[str], pd.DataFrame]) -> None:
        """設定Athena連接及SQL執行函數"""
        self.run_sql = run_sql_func
        self.run_sql_is_set = True
        self.dialect = "AWS Athena SQL"
        logger.info("Athena connection set successfully")
    
    def add_documentation(self, documentation: str, **kwargs) -> str:
        """添加文檔到文檔索引"""
        return self._index(self.document_index, {"doc": documentation}, **kwargs)

    def add_ddl(self, ddl: str, **kwargs) -> str:
        """添加DDL到DDL索引"""
        return self._index(self.ddl_index, {"ddl": ddl}, **kwargs)

    def add_question_sql(self, question: str, sql: str, **kwargs) -> str:
        """添加問題和SQL到問題索引"""
        return self._index(self.question_sql_index, {"question": question, "sql": sql}, **kwargs)

    def _index(self, index: str, body: Dict[str, Any], **kwargs) -> str:
        """向索引加文檔"""
        try:
            resp = self.opensearch_client.index(index=index, body=body, **kwargs)
            return resp["_id"]
        except Exception as e:
            logger.error(f"Indexing to {index} failed: {e}")
            raise ExternalAPIError(f"Failed to index to {index}: {e}")

    def get_related_ddl(self, question: str, **kwargs) -> List[str]:
        """獲取與問題相關的DDL"""
        return self._search(self.ddl_index, "ddl", question, **kwargs)

    def get_related_documentation(self, question: str, **kwargs) -> List[str]:
        """獲取與問題相關的文檔"""
        return self._search(self.document_index, "doc", question, **kwargs)

    def get_similar_question_sql(self, question: str, **kwargs) -> List[Dict[str, str]]:
        """獲取與問題相似的問題和SQL"""
        try:
            q = {"query": {"match": {"question": question}}}
            resp = self.opensearch_client.search(index=self.question_sql_index, body=q, **kwargs)
            return [
                {"question": h["_source"]["question"], "sql": h["_source"]["sql"]}
                for h in resp["hits"]["hits"]
            ]
        except Exception as e:
            logger.error(f"Search similar questions failed: {e}")
            return []

    def _search(self, index: str, field: str, query_str: str, **kwargs) -> List[Any]:
        """搜尋索引中的文檔"""
        try:
            q = {"query": {"match": {field: query_str}}}
            resp = self.opensearch_client.search(index=index, body=q, **kwargs)
            return [hit["_source"].get(field) for hit in resp["hits"]["hits"]]
        except Exception as e:
            logger.error(f"Search in {index} failed: {e}")
            return []