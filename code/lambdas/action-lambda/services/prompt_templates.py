# Tables used by Agent for text to SQL
from services.connections import Connections

table_details = {
    Connections().env.ATHENA_TABLE_NAME: (
        "This table contains detailed invoice data for retail transactions, "
        "including merchant info, time, location, payment method, user identifiers, "
        "item descriptions, and transaction amounts. \n\n"
    )
}

# prompts for pricing details retrieval

# - id: 資料唯一識別碼（主鍵\\n
# - inv_num: 發票號碼\\n
# - aaid: Android 廣告 ID\\n
# - vid: 發票載具\\n
# - code: QR Code\\n
# - invType: 發票種類（0 = QRCode, 1 = 載具, 2 = 未知）\\n
# - sellerID: 商家統編\\n
# - createdDate: 入庫時間（datetime）\\n
# - cid: Money 系統 ID\\n
# - uid: 唯一碼\\n\\n
# - item_amount: 商品小計（單價乘上數量\\n
SQL_TEMPLATE_STR = """Given an input question, first create a syntactically correct {dialect} query to run, then look at the results of the query and return the answer.\\n
You can order the results by a relevant column to return the most interesting examples in the database.\\n\\n
Never query for all the columns from a specific table, only ask for a few relevant columns given the question.\\n\\n
Pay attention to use only the column names that you can see in the schema description. Be careful to not query for columns that do not exist.\\n
Qualify column names with the table name when needed.\\n\\n

If the SQL query is related to a specific product name (e.g., in the `description` field), always use **broad and flexible keyword matching** (e.g., using partial product names, key features, or major terms), rather than exact full product names.\\n
This helps ensure recall and avoids overly specific matches that may miss relevant results.\\n
Do NOT write queries like:\\n
SELECT SUM(amount) AS total_sales, paymentMethod FROM invoice_table WHERE invDate BETWEEN '2025-04-01' AND '2025-04-30' AND description LIKE '%Advanced Génifique Youth Activating Serum%' GROUP BY paymentMethod\\n
Instead, prefer:\\n
SELECT SUM(amount) AS total_sales, paymentMethod FROM invoice_table WHERE invDate BETWEEN '2025-04-01' AND '2025-04-30' AND (description LIKE '%Génifique%' OR description LIKE '%Youth%' OR description LIKE '%精華%') GROUP BY paymentMethod\\n\\n

發票資料表說明：\\n
- id: 資料唯一識別碼（主鍵\\n
- sellerAddress: 商店地址\\n
- os: 手機作業系統（Android, iOS）\\n
- idfa: iOS 廣告 ID\\n
- invDate: 發票日期（格式 YYYY-MM-DD）\\n
- invTime: 發票時間（格式 HH:MM:SS）\\n
- sellerName: 商店名稱\\n
- sellerType: 商家類型（自訂分類）\\n
- storeName: 商店別稱\\n
- storeGPS_lat: 商店緯度\\n
- storeGPS_lon: 商店經度\\n
- description: 商品名稱\\n
- unit_price: 商品單價\\n
- quantity: 數量\\n
- amount: 發票總金額\\n
- paymentMethod: 支付方式（例如：信用卡、悠遊卡）\\n
- gender: 推估性別（male, female, unknown）\\n
- birthday: 推估生日\\n\\n

You are required to use the following format, each taking one line:\\n\\n
Question: <user_question>\\n
SQLQuery: <sql_to_run>\\n
SQLResult: <result>\\n
Answer: <final_answer>\\n\\n

Only use tables listed below.\\n
{schema}\\n\\n
Do not under any circumstance use SELECT * in your query.\\n\\n

Here are some examples:\\n
Query: 查詢 2023 年 1 月用信用卡支付的發票總數\\n
Response: SELECT COUNT(*) FROM invoice_table WHERE paymentMethod LIKE '%信用卡%' AND invDate BETWEEN '2023-01-01' AND '2023-01-31';\\n\\n
Query: 找出台北市發票中含有「紅茶」的商品有哪些商家\\n
Response: SELECT DISTINCT sellerName FROM invoice_table WHERE description LIKE '%紅茶%' AND sellerAddress LIKE '%台北市%';\\n\\n
Question: {query_str}\\n
SQLQuery:"""


# prompt for summarize pricing details retrieval
RESPONSE_TEMPLATE_STR = """If the <SQL Response> below contains data, then given an input question, synthesize a response from the query results.\\n
If the <SQL Response> is empty, then you should not synthesize a response and instead respond that no data was found for the question.\\n\\n

Query: {query_str}\\n
SQL: {sql_query}\\n
<SQL Response>: {context_str}\\n
</SQL Response>\\n\\n

Do not make any mention of SQL queries, databases, or internal systems in your response. Instead, use phrasing like '根據最新資料' (according to the latest information).\\n\\n
Please highlight any key numbers, dates, merchant names, or item descriptions found in the result.\\n\\n
If the final answer contains <dollar_sign>$</dollar_sign>, ADD '\\\\' ahead of each <dollar_sign>$</dollar_sign> to ensure proper rendering.\\n\\n

Response:"""
