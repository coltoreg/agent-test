## ✅ `create_data_source_bucket(kms_key)`

### 📌 Bucket 部屬行為說明：

| Bucket 名稱           | 來源         | 是否由 CDK 建立 | 說明                                                                 |
|------------------------|--------------|----------------|----------------------------------------------------------------------|
| `athena_bucket`        | 手動建立     | ❌               | 本次透過 `Bucket.from_bucket_name()` 引用，避免重複建立造成衝突              |
| `agent_assets_bucket` | CDK 建立     | ✅               | 用來存放知識文件與 API schema，僅此用途                                 |

### ⚠️ 注意事項：

- `athena_bucket` 為共用或歷史 Bucket，**必須預先存在**，否則部署會失敗
- `agent_assets_bucket` 設定如下：
  - **加密方式**：KMS（自定義金鑰）
  - **版本控制**：開啟 `versioned=True`
  - **刪除策略**：保留（`removal_policy=RETAIN`），確保資料不被誤刪
  - **自動刪除**：關閉（`auto_delete_objects=False`）

---

## ✅ `upload_files_to_s3(...)`

### 📁 需上傳的檔案與對應 Bucket：

| 類別             | 檔案來源資料夾                      | 上傳 Bucket           | 上傳目的地 Prefix                   | 是否由 CDK 自動上傳 |
|------------------|---------------------------------------|------------------------|-------------------------------------|----------------------|
| 知識文件 (KB)     | `assets/<knowledgebase_prefix>/`     | `agent_assets_bucket` | `<knowledgebase_prefix>/`          | ✅                    |
| API Schema       | `assets/agent_api_schema/`           | `agent_assets_bucket` | `agent_api_schema/`                | ✅                    |
| Athena 資料表 CSV | `assets/<athena_data_prefix>/`       | `athena_bucket`       | `<athena_data_prefix>/`            | ❌（需手動上傳）      |

### 📝 設定與行為說明：

- 使用 `s3deploy.BucketDeployment` 部署以下兩類資料：
  - ✅ **知識文件**（可壓縮 .zip）
  - ✅ **API Schema**（如 JSON 文件）
- ✅ 上述皆可透過 `cdk deploy` 自動上傳
- ❌ Athena CSV 資料表部分，**因為 Bucket 為外部指定且固定命名，不由 CDK 管理與上傳**，請開發者手動維護

### 🧠 為什麼 Athena 資料不自動上傳？

- 該 Bucket 為共用資源，避免 CDK 誤刪或上傳覆蓋
- Athena 資料較龐大或變動頻繁，適合透過 Data Pipeline 或 CLI 上傳

---

✅ 完整部屬前確認：

- [ ] `chatbot-stack-athena-bucket-<account_id>` 已事先建立，且權限與結構符合需求
- [ ] `assets/agent_api_schema/` 與 `assets/<knowledgebase_prefix>/` 檔案已齊備
- [ ] `cdk.json` 中相關 prefix 設定正確無誤

✅ 可由 CDK 自動上傳的資料：
- `knowledgebase_file_name`
- API schema (.json)

⛔ 不由 CDK 上傳的資料：
- Athena 查詢資料（如 .csv），需由使用者手動放置於 Bucket 的對應 Prefix 內