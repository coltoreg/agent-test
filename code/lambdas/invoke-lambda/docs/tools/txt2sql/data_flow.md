# txt2figure 數據轉換流程

## 🔄 數據格式轉換步驟

### **步驟 1：Agent Trace 原始數據**
```json
{
  "vanna_result": [
    {
      "title_text": "銷售趨勢圖",
      "img_static": "https://bucket.s3.amazonaws.com/vanna/chart123.png",
      "html": "<div>Plotly HTML</div>"
    }
  ]
}
```
**格式**：S3 URL 字符串

---

### **步驟 2：S3 下載 + 雙格式轉換**
```python
# _process_vanna_result() 函數
data = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()

result[k] = {
    "bytes": data,                           # 二進制數據
    "b64": base64.b64encode(data).decode()   # base64 字符串
}
```

**格式**：雙格式物件
```json
{
  "title_text": "銷售趨勢圖(發票數據)",
  "img_static": {
    "bytes": "<binary_data>",
    "b64": "iVBORw0KGgoAAAANSUhEUgAAA..."
  }
}
```

---

### **步驟 3：HTML + Word 分離處理**
```python
# build_output_format() 函數

# HTML 用途
img_bytes = img_static.get("bytes")
data_uri = f"data:image/png;base64,{base64.b64encode(img_bytes).decode()}"
chart_data[chart_id] = {
    "html": f'<img src="{data_uri}" />',
    "static": img_bytes  # ❌ 不可序列化
}

# Word 用途
word_chart_entry = {
    "chart_id": chart_id,
    "img_static_b64": img_b64,  # ✅ 可序列化
    "placeholder": "[WORD_CHART_abc123]"
}
```

**格式分離**：
- **HTML格式**：包含 bytes (本地使用)
- **Word格式**：只有 base64 (傳輸用)

---

### **步驟 4：Lambda 響應 (JSON 序列化)**
```json
{
  "answer": "<html>包含圖表的完整HTML</html>",
  "word_export_data": {
    "charts_data": {
      "page1": [
        {
          "chart_id": "abc123",
          "title_text": "銷售趨勢圖(發票數據)",
          "img_static_b64": "iVBORw0KGgoAAAANSUhEUgAAA...",
          "placeholder": "[WORD_CHART_abc123]"
        }
      ]
    }
  }
}
```
**格式**：純 base64 字符串 (無 bytes)

---

### **步驟 5：Exporter Lambda 還原**
```python
# exporter-lambda 中
img_static_b64 = chart.get("img_static_b64")
img_bytes = base64.b64decode(img_static_b64)  # 還原成 bytes

processed_chart["img_static_bytes"] = img_bytes  # 新字段名
```

**格式**：base64 → bytes (供 Word 文檔使用)

---

## 📊 關鍵轉換點

| 階段 | 輸入格式 | 輸出格式 | 目的 |
|------|----------|----------|------|
| Agent → Download | S3 URL | bytes | 實際下載圖片 |
| Download → Dual | bytes | {bytes, base64} | 準備雙格式 |
| Dual → Split | {bytes, base64} | 分離存儲 | HTML/Word 分離 |
| Split → Response | 分離格式 | 只 base64 | JSON 序列化 |
| Response → Export | base64 | bytes | Word 文檔插入 |

## ⚠️ 序列化關鍵

```python
# ❌ 會導致 Marshal Error
response = {"data": img_bytes}  # bytes 不可序列化

# ✅ 安全傳輸
response = {"data": img_base64}  # 字符串可序列化
```

## 🎯 核心原則

1. **下載時**：S3 URL → bytes + base64
2. **使用時**：HTML 用 bytes，Word 準備 base64  
3. **傳輸時**：只傳 base64，丟棄 bytes
4. **還原時**：base64 → bytes (按需: 我們在[下載檔案的部分](../../../../export-lambda/index.py)有執行)