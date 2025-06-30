# 介紹

本系統依據[需求文件](需求文件)為基礎進行開發，文件內容共分為以下四大部分:

## 文件總覽

* [01. introduction](./01_introduction.md): 記錄專案的整體設計背景、歷史沿革與設計理念，協助後續接手的開發者迅速掌握全貌，降低重工風險。

* [02. maintain](./02_maintain.md): 提供維護者與開發者明確的維護與開發指引，提升效率與品質。

* [03. designing](./03_designing.md): 說明本架構的設計思維，包括基礎建置、職責切分、採用物件導向或函數式開發的考量。

* [04. trouble\_shooting](./04_trouble_shooting.md): 列出常見錯誤與應對方式，提供清楚的處理流程與SOP，方便快速排除問題。

## 專案由來

本專案以 [AWS 開源專案](https://github.com/awslabs/genai-bedrock-agent-chatbot/tree/main) 為基礎進行擴充，強化重點包括：前後端與網路資源的分離、agent tool call 機制的強化，以及實現符合 DEMO 情境的完整業務功能。詳細需求內容請參考[需求文件](需求文件)。

## 歷史沿革

本專案於 2025 年 3 月的[首次相關會議](https://multiforcedatateam.atlassian.net/browse/DT-141)中，明確定義 DATA TEAM 對 DEMO、MVP 與 Product 的目標定位，並設定 DEMO 為首階段目標，於 2025 年 6 月完成並釋出穩定版本 [v1.0.1](https://github.com/ClickForce-RD/ai-cb-agent-datateam/releases/tag/v1.0.1)。主要開發者 Jiao 於 2025 年 7 月離職，專案交接給 \[接手人1] 與 \[接手人2]。

## 設計理念

開發重點著重於擴充性與維護性，目標是在現有技術能力範圍內建構可持續優化的系統。

在技術架構方面，專案團隊製作了多張圖表，協助與開發人員、PM 及營運端達成共識，包括：[成本估算圖](./../assets/diagrams/ai-cb-agent_cost_est.png)、[雲端架構圖](./../assets/diagrams/ai-cb-agent_architecture.png)、[整體資料流程圖](./../assets/diagrams/ai-cb-agent_data_flow.png)、以及[時序圖](./../assets/diagrams/ai-cb-agent-sequence-diagram.png)。

程式設計方面，部分模組採用物件導向，便於日後透過 Closed/Open 原則擴充功能，亦有助於資料傳輸與模組維護；另一部分則採用函數式設計，降低耦合度，因應未來與其他部門串接的需求，預留重構或遷移彈性，例如功能縮減或環境切換等。

## 撰寫人員

本文件由專案主要開發者 **Jiao** 撰寫與整理，最後更新於 2025 年 6 月。後續維護與補充將由接手人員 **\[接手人1]** 與 **\[接手人2]** 負責。

如有任何疑問或建議，請優先聯繫目前維護人員。