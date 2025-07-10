# 維護文件

此文件旨在提供維護者或開發者能有效追蹤程式碼，以減少溝通成本。

## 根目錄下的主要資料夾與檔案總攬

我們的根目錄下的主要資料夾與檔案對應用途如下:

- assets: 存放佈署用資料(如: [API Schema](./../assets/agent_api_schema/artifacts_schema.json)、[text to sql prompt 模板](./../assets/agent_prompts/agent_prompts.py)、[產業知識文本資料](./../assets/knowledgebase_data_source/)及[vanna 相關資料](./../assets/vanna_data/))與圖表資料(如: [各種圖表](./../assets/diagrams/))。

- `code/`: 存放主要業務功能程式碼，可區分為[前端](./../code/streamlit-app)與[後端](./../code/lambdas)。

- `config/`: 佈署時的設定文件，主要設定內容為各資源名稱。

- `docs/`: 此專案文件。

- `scripts/`: 自動化佈署用。

- `stacks/`: 包含[前後端及網路的 IaC](./../stacks/) (方便重複佈署的[資源資訊](./../stacks/resources/)，實現資源分離管理及快速佈署)。

- `app.py`: 實作 [stacks](./../stacks/) 中 IaC，完成佈署。

- `cdk.json`: 利用 CDK 佈署時需要的底層資源設定。


## 後端設計

我們使用 AWS Lambda Functions 來實現各職責，如下:

- [Agent 的工具](./../code/lambdas/action-lambda/)

- [向量化資料庫創建](./../code/lambdas/create-index-lambda/)

- [向量化資料庫及Agent資源變動](./../code/lambdas/update-lambda/)

- [Vanna 的底層資源創建](./../code/lambdas/vanna-init-data-lambda/)

- [彙整前後端資料傳遞](./../code/lambdas/invoke-lambda/)

- [後端某功能](./../code/lambdas/export-lambda/)


## 幾個資料流程圖

- Agent 使用 Vanna 抓出圖表並渲染前端，且最後下載到 word，可參考[此文件](./maintain/df_vanna.md)。