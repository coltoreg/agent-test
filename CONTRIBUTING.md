# 團隊 Git Flow 最佳實踐

本專案採用簡化版 Git Flow 流程，以**分支管理 + Pull Request (ＰＲ)審查**為核心，達到高效、穩定與清楚的開發協作。

## 分支說明

| 分支名稱        | 用途                                                                 |
|-----------------|----------------------------------------------------------------------|
| `main`          | 用於正式上線版本（Production-ready），**受保護，不可直接 push**       |
| `develop`       | 開發整合分支，所有功能開發最終會合併至此分支，**受保護，不可直接 push**                              |
| `feature/xxx`   | 功能開發分支，從 `develop` 分出，用於單一功能或任務                        |
| `hotfix/xxx`    | 緊急修補分支，從 `main` 分出，修補嚴重錯誤                                |
| `release/xxx`   | 發佈版本準備階段（可選）                                                |

> ❗ 所有分支\u皆透過 **Pull Request** 合併，嚴禁直接 push 至 `main` 或 `develop`。

---

## 分支命名規範

為提升版本控管與團隊協作效率，所有分支請依下列命名格式製作：

```
<類型>/<描述>[-<任務ID>]
```

### 常用 prefix 一覽

| 類型       | 說明                             | 範例                                |
|------------|----------------------------------|-------------------------------------|
| `feature/` | ✨ 新功能開發                     | `feature/user-login`                |
| `fix/`     | 🐞 修復 bug                      | `fix/token-refresh`                |
| `hotfix/`  | 🔥 緊急修補（Production）        | `hotfix/crash-on-start`            |
| `release/` | 🚀 發佈前版本準備                 | `release/1.2.0`                     |
| `refactor/`| ♻️ 重構，無改變功能邏輯         | `refactor/order-module`            |
| `docs/`    | 📚 文件變更                       | `docs/update-api-docs`             |
| `test/`    | ✅ 測試相關（新增或調整）         | `test/user-service-tests`          |
| `chore/`   | ♻️ 系統性調整、監控、更新        | `chore/bump-dependencies`          |

---

## 開發流程

```bash
# 從 develop 建立功能分支
git checkout develop
git pull
git checkout -b feature/awesome-feature
```

- 開發完成後，建立 PR 至 `develop`
- 命名建議：`feature/login-api`、`feature/user-avatar-upload`
- 通過 Code Review、Lint 後合併


## Hotfix 緊急修補（可選）

```bash
# 從 main 建立 hotfix 分支
git checkout main
git pull
git checkout -b hotfix/fix-login-error
```

- 修復完成後，建立 PR 至 `main` 和 `develop`
- 通過測試後先合併至 main → 立即部署
- 再合併回 `develop`，保持一致


## 發佈版本（可選）

若需準備穩定版本，可從 develop 建立 release/xxx 分支：

```bash
git checkout develop
git pull
git checkout -b release/1.2.0
```

- 做版本準備（bugfix、文檔、版本號）
- 發佈時建立 PR → main，再 PR → develop


## Pull Request 規範

1. 每個 PR 專注一個功能/ 修復
2. PR 標題清楚描述變更內容（可加上 JIRA 或任務 ID）
3. 填寫 PR Template，描述背景、變更、測試方式
4. 通過 CI/Lint
5. reviewer review 後才可合併


## Commit Message 建議格式

使用 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 規範，有助於自動產生 changelog

```makefile
feat: 新增使用者登入功能
fix: 修正 token 過期錯誤
docs: 補充 README 使用說明
refactor: 重構驗證流程邏輯
chore: 更新套件版本
```

## 保護策略建議

- `main`, `develop` 為 保護分支
- 禁止直接 push
- 必須通過：
    - 至少 1 人 Review 通過
    - 使用 PR 合併