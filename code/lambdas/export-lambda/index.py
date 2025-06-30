import json
import os
import base64
import tempfile
from datetime import datetime

from connections import Connections
from exporters.pdf_exporter import PdfExporter
from exporters.docx_exporter import DocxExporter
from exporters.ppt_exporter import PptExporter
from utils.exceptions import exception_handler, ExportFormatError
from utils.logger import get_logger

logger = get_logger("index")

EXPORTER_MAP = {
    "docx": DocxExporter,
    "pdf": PdfExporter,
    "ppt": PptExporter,
}

@exception_handler
def lambda_handler(event, context):
    logger.info(f"Received event: {event}")
    
    try:
        body = json.loads(event["body"])
        company_info = body["company_info"]
        raw_analysis = body["analysis"]
        file_format = body["format"].lower()
        session_id = body["session_id"]

        # 處理圖表數據
        charts_data = body.get("charts_data", {})
        logger.info(f"接收到圖表數據頁面: {list(charts_data.keys())}")

        # 處理圖表位置信息
        charts_position_info = body.get("charts_position_info", {})
        logger.info(f"接收到圖表位置信息頁面: {list(charts_position_info.keys())}")
        
        # 將 base64 轉換為 bytes
        # 這樣避免了 invoke-lambda 返回不可序列化的 bytes 數據
        processed_charts_data = {}
        for page_name, charts_list in charts_data.items():
            processed_charts_data[page_name] = []
            
            for chart in charts_list:
                # 直接保持原有格式，不做額外處理
                processed_chart = chart.copy()
                
                # 只做驗證，不轉換
                img_static_b64 = chart.get("img_static_b64")
                if img_static_b64:
                    logger.info(f"✅ 圖表 {chart.get('title_text')} 包含有效的 base64 數據")
                else:
                    logger.warning(f"⚠️ 圖表 {chart.get('title_text')} 缺少 img_static_b64 數據")
                
                processed_charts_data[page_name].append(processed_chart)
        
        logger.info(f"📊 圖表數據處理完成，總計 {sum(len(charts) for charts in processed_charts_data.values())} 個圖表")

        # 檢查檔案格式是否支援
        if file_format not in EXPORTER_MAP:
            logger.error(f"不支援的檔案格式: {file_format}")
            raise ExportFormatError(f"不支援的匯出格式: {file_format}")

        # 整理分析資料結構
        analysis = {
            sec: {"內容": (txt.strip() or "（未提供內容）")}
            for sec, txt in raw_analysis.items()
        }

        # 生成檔案名稱前綴
        prefix = (
            f"{company_info.get('品牌名稱', '報告')}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

        # 使用臨時目錄處理檔案
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, f"{prefix}.{file_format}")

            # 選擇對應的匯出器
            exporter_cls = EXPORTER_MAP[file_format]
            
            # 根據檔案格式決定是否傳入圖表數據
            if file_format == "docx":
                # 只有 Word 格式需要圖表數據
                exporter = exporter_cls(
                    analysis, 
                    company_info, 
                    processed_charts_data,
                    charts_position_info
                )
                logger.info(f"建立 DOCX 匯出器，包含 {sum(len(v) for v in processed_charts_data.values())} 個圖表")
                logger.info(f"圖表位置信息: {sum(len(v) for v in charts_position_info.values())} 個位置記錄")
            else:
                # PDF 和 PPT 暫不支援圖表插入
                exporter = exporter_cls(analysis, company_info)
                logger.info(f"建立 {file_format.upper()} 匯出器（不包含圖表）")
                
            # 執行檔案匯出
            logger.info(f"開始匯出檔案: {file_path}")
            exporter.export(file_path)
            
            # 檢查檔案是否成功生成
            if not os.path.exists(file_path):
                raise Exception(f"檔案生成失敗: {file_path}")
            
            file_size = os.path.getsize(file_path)
            logger.info(f"檔案生成成功: {file_path}, 大小: {file_size} bytes")

            # 上傳至 S3
            s3_key = f"exports/{session_id}/{prefix}.{file_format}"
            logger.info(f"上傳檔案至 S3: {s3_key}")
            
            Connections.s3_client().upload_file(
                file_path, Connections.s3_bucket_name, s3_key
            )

            # 讀取檔案並轉換為 base64
            with open(file_path, "rb") as f:
                file_content = f.read()
                encoded = base64.b64encode(file_content).decode("utf-8")

            logger.info(f"檔案匯出完成並上傳至 S3: {s3_key}")
            logger.info(f"檔案大小: {len(file_content)} bytes, Base64 大小: {len(encoded)} 字符")

            # 返回成功響應
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "匯出成功",
                    "download_path": f"s3://{Connections.s3_bucket_name}/{s3_key}",
                    "filename": f"{prefix}.{file_format}",
                    "filedata": encoded,
                    "file_size": len(file_content),
                    "charts_count": sum(len(v) for v in processed_charts_data.values()) if file_format == "docx" else 0
                }, ensure_ascii=False),
            }
            
    except json.JSONDecodeError as json_err:
        logger.error(f"JSON 解析錯誤: {json_err}")
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "請求格式錯誤",
                "message": f"JSON 解析失敗: {str(json_err)}"
            }, ensure_ascii=False)
        }
        
    except ExportFormatError as format_err:
        logger.error(f"格式錯誤: {format_err}")
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "不支援的檔案格式",
                "message": str(format_err)
            }, ensure_ascii=False)
        }
        
    except Exception as general_err:
        logger.error(f"匯出過程發生錯誤: {general_err}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "檔案匯出失敗",
                "message": f"系統錯誤: {str(general_err)}"
            }, ensure_ascii=False)
        }