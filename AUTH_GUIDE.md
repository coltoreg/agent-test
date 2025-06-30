# IAM 權限設定與操作指令整理

## 🎯 目標情境
- 使用者：genai-agent（IAM User）
- 角色：GACdkFullDeployRole（具備完整 CDK 部署權限）
- 使用方式：本地 CLI / CDK 透過 `AssumeRole` 進行資源部署

---

## Assume Role 並取得暫時憑證

```bash
aws sts assume-role `
  --role-arn arn:aws:iam::992382611204:role/GACdkFullDeployRole `
  --role-session-name genai-session `
  --profile genai-agent
```

## 確認目前身分
```bash
aws sts get-caller-identity
```


## 對應權限設定

Athena: 
- credential: DB_MAPPING Key
- Bucket: adpilot360-athena-queryresult


