# Prompt 管理說明文件

本專案為生成式 AI 應用，**Prompt 的設計與管理為系統運作關鍵之一**。為提升維護效率與跨團隊協作，我們統整了所有與 LLM 互動的 prompt 使用場景、位置與用途，幫助新進開發者快速掌握專案架構與設計邏輯。


文件更新時間: 2025/05/09

---

## 一、Agent 初始化階段

### 📁 位置

`cdk.json`

### 🧾 說明

當 Agent 被部屬或啟動時，會透過 `agent_instruction` 設定其基礎任務認知（例如是資料分析助理、產業報告助手等）。

### ✅ 功能用途

* 定義 Agent 的角色、能力範疇、語氣風格
* 初始系統 prompt 影響 LLM 回答品質與一致性

---

## 二、前端互動階段（Streamlit）

### 📁 位置

[`app.py`](./code/streamlit-app/app.py)

### 🧾 說明

當使用者首次進入頁面並提出問題時，前端會呼叫 `get_response` 與 Agent 互動，這是 Prompt 發送給 LLM 的第一次機會。

### ✅ 功能用途

* 負責組合使用者問題與主題提示（如 topic\_hint + user\_input）
* 構成初步任務輸入，回傳初步分析方向或查詢建議

---

## 三、Lambda Functions（伺服端推論邏輯）

### 🔹 1. invoke-lambda

#### 📁 位置

[`index.py`](./code/lambdas/invoke-lambda/index.py)

#### 🧾 說明

處理 LLM 最終生成的輸出格式與結構，透過 `call_model_unified` 對回應做封裝，生成結構化內容（如產業分析報告、行銷建議等）。

#### ✅ 功能用途

* 統整回應內容成標準化欄位
* 控制輸出的一致性與可機器讀性

---

### 🔹 2. action-lambda (棄用: 文字轉搜尋從 LlamaIndex 轉移到 vanna)

#### 📁 Prompt 模板

[`prompt_templates.py`](./code/lambdas/action-lambda/services/prompt_templates.py)

#### 📁 Few-shot 範例資料

[`dynamic_examples.csv`](./code/lambdas/action-lambda/dynamic_examples.csv)

### 2. action-lambda (vanna 中的 few-shot)

[`action-lambda\handlers\vanna_handler.py`](./action-lambda/handlers/vanna_handler.py)

#### 🧾 說明

負責將自然語言問題轉換為 SQL 查詢。此部分設計了：

* **自定義 Prompt 模板**：描述資料表結構、轉換目標、語法格式
* **Few-shot Examples**：提供實例範本強化 LLM 對轉換任務的理解與精度

#### ✅ 功能用途

* 提升自然語言轉 SQL 的正確率
* 根據表結構提供上下文資訊
* 增強語意比對與欄位推論能力

---

## 小結與建議

| 階段        | Prompt 目的       | 對應位置                                                                                 | 額外資源 |
| --------- | --------------- | ------------------------------------------------------------------------------------ | ---- |
| Agent 初始化 | 定義 LLM 行為與角色    | `cdk.json`                                                                           | -    |
| 使用者進入頁面   | 初步理解使用者意圖       | `streamlit-app/app.py`                                                               | -    |
| 輸出封裝      | 結構化 LLM 回應      | `invoke-lambda/index.py`                                                             | -    |
| 語意轉 SQL (棄用)   | LLM 理解資料結構與語意轉換 | `action-lambda/services/prompt_templates.py`<br>`action-lambda/dynamic_examples.csv` | -    |
| 語意轉 SQL 轉圖   | LLM 理解資料結構與語意轉換及製作圖表 | `action-lambda\handlers\vanna_handler.py` | -    |

---

### TODO: 建議維護方式

* **集中管理 Prompt**：如可能，將所有 prompt 定義集中於單一模組，減少分散維護風險。
* **版本控管**：重大 prompt 改動請標註版本與用途，利於測試與回溯。
* **測試樣本追蹤**：搭配測試資料記錄不同 prompt 對結果的影響。