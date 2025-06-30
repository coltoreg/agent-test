import re
from html import unescape

def build_cover(info: dict):
    """
    根據公司資訊建立封面所需的標題、期間與補充說明。

    Args:
        info (dict): 公司資訊，包含品牌名稱、分析日期、補充資訊等欄位。

    Returns:
        tuple: (title, period, extra)
    """
    brand = info.get("品牌名稱", "")
    title = f"{brand} 產業研究報告書"
    period = f"{info.get('分析開始日期', '')} ~ {info.get('分析結束日期', '')}"
    extra = info.get("補充資訊", "")
    return title, period, extra


def split_by_h2(html: str):
    """將 HTML 按 <h2> 分段，回傳 [(title, html_block)]"""
    blocks = re.split(r"(?i)<h2[^>]*>(.*?)</h2>", html)
    if len(blocks) == 1: # 沒有 <h2>
        return [("內容", html)]
    return [(blocks[i], blocks[i+1] if i+1 < len(blocks) else "") 
            for i in range(1, len(blocks), 2)]


def extract_text_blocks(html: str):
    """從 HTML 中提取段落與清單內容，轉換為可用於 TXT 輸出的段落文字（含換行）"""
    html = unescape(html)

    paragraphs = []

    # 將 <br> 轉為換行符
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)

    # 提取 <p>
    p_matches = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL)
    for match in p_matches:
        cleaned = re.sub(r"<[^>]+>", "", match).strip()
        if cleaned:
            paragraphs.append(cleaned)

    # 提取 <li>，合併為一塊帶項目符號的區段
    li_matches = re.findall(r"<li[^>]*>(.*?)</li>", html, re.DOTALL)
    if li_matches:
        list_block = "\n".join([f"• {re.sub(r'<[^>]+>', '', li).strip()}" for li in li_matches])
        paragraphs.append(list_block)

    return paragraphs


import re
from html import unescape

def extract_text_blocks(html: str):
    html = unescape(html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)

    blocks = []

    for p in re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL):
        text = re.sub(r"<[^>]+>", "", p).strip()
        if text:
            blocks.extend([line.strip() for line in text.split("\n") if line.strip()])

    li_matches = re.findall(r"<li[^>]*>(.*?)</li>", html, re.DOTALL)
    for li in li_matches:
        text = re.sub(r"<[^>]+>", "", li).strip()
        if text:
            blocks.append(f"• {text}")

    return blocks