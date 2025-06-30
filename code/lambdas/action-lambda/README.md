# Action Lambda

## 🌐 介紹

這個 Lambda 是 Amazon Bedrock Agent 的 **Action Group** 一部分，用來處理操作群組指定的各種許可自動化件任，包括:

- 網路搜尋
- 統計查詢 (Athena)
- 用戶表協信息表協

它通過 Bedrock Agent 啟動，操作動作群組中指定的 API handler，以來對應用戶的請求。

---

## ⚡ 目錄結構

```plaintext
lambdas/action-lambda/
├── Dockerfile
├── README.md
├── connections.py
├── dynamic_examples.csv
├── handlers/
│   ├── __init__.py
│   ├── ask_user_missing_info.py
│   ├── query_market_share.py
│   ├── search_internet.py
├── index.py
├── requirements.txt
├── services/
│   ├── __init__.py
│   ├── athena_service.py
│   ├── prompt_templates.py
│   ├── web_search_service.py
├── utils/
    ├── __init__.py
    ├── exceptions.py
    ├── logger.py
```

---

## 📚 標準上線說明

### 依賴套件 (`requirements.txt`)
- boto3
- llama-index
- llama-index-embeddings-bedrock
- llama-index-llms-bedrock
- sqlalchemy
- PyAthena[SQLAlchemy]
- openai

### 技術堆棒
- **AWS Lambda**
- **Amazon Bedrock Agent**
- **AWS Athena**
- **OpenAI Web Search API**


---

## 🔄 處理流程

1. Bedrock Agent 接收到用戶問題
2. 根據 API Path 挑選 handler (index.py ROUTE_TABLE)
3. handler 處理問題，可能:
   - 驗證用戶資料
   - 啟動網路搜尋 (OpenAI API)
   - 啟動 Athena SQL 查詢
4. 返回正解格式給 Bedrock Agent
5. Bedrock 自動把結果放入 **Session Memory**
6. Agent 根據 Memory 接著繼續對話

---

## 🔍 Handler 檢視

| Handler | 責任 |
|:--------|:--------|
| `/searchinternet` | 網路搜尋 (OpenAI Web Search API) |
| `/querymarketshare` | 查詢公司市佔率 (AWS Athena) |
| `/askusermissinginfo` | 表協用戶表示缺少資料 |


---

## 📅 輸入格式

```json
{
  "agent": { "id": "agent-id", "alias": "agent-alias" },
  "sessionId": "123456789",
  "inputText": "User question here",
  "apiPath": "/searchinternet",
  "parameters": [
    { "name": "query", "type": "string", "value": "What's the latest AI news?" }
  ],
  "messageVersion": "1.0"
}
```


---

## 🚀 輸出格式

正確的 Lambda Response：

```json
{
  "messageVersion": "1.0",
  "response": {
    "contentType": "application/json",
    "statusCode": 200,
    "body": {
      "query": "What's the latest AI news?",
      "response": "According to the latest news, AI is advancing rapidly..."
    }
  }
}
```

- 記得 `body` 是 JSON object，而不是字串
- 這樣才能輕鬆被 Bedrock Agent 將結果放進 **Session Memory**

---

## 🔧 環境設定 (ENV Vars)

| 變數名稱 | 用途 |
|:----------|:-----|
| `OPENAI_API_KEY` | OpenAI 上網搜尋手鍵 |
| `ATHENA_BUCKET_NAME` | Athena S3 儲存區名稱 |
| `TEXT2SQL_DATABASE` | Athena 數據庫名稱 |
| `LOG_LEVEL` | 日誌級別 |
| `FEWSHOT_EXAMPLES_PATH` | 關聯輸入範例路徑 |


---

## 📊 關於 Dockerfile

- 執行基礎: AWS Lambda Python 3.11
- 安裝了 PyTorch CPU 版，與最新的 pip / setuptools
- 用 Dockerfile 作為 Lambda Image Build 執行環境


---

## ⚠️ 注意事項

- `body` 必須是 **JSON 物件**，而不是字串 JSON.
- Session Memory 不用自己編輯，Bedrock Agent 會自動編入.
- OpenAI Web Search 需要設定好 API Key.