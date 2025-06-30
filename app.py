#!/usr/bin/env python3
import os
import aws_cdk as cdk
import cdk_nag
import json

from code.code_stack import CodeStack
from cdk_nag import NagSuppressions
from aws_cdk import Aspects

app = cdk.App()

with open("cdk.json", encoding="utf-8") as f:
    data = json.load(f)
config = data["context"]["config"]
stack_name = config["names"]["stack_name"]

appStack = CodeStack(
    app,
    stack_name,
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=os.getenv("CDK_DEFAULT_REGION")
    ),
)

# 以下皆為靜態檢查
"""
`cdk-nag` 是一個 CDK 套件，
可以幫你根據 AWS 的安全、合規、操作最佳實踐來檢查你的資源設計

檢查的例子:
- IAM Policy 是否過於寬鬆（如 *:*）
- S3 Bucket 是否開放存取、是否加密
- Lambda 是否設有 log retention
- 是否有 VPC Flow Logs、GuardDuty 等安全功能
"""
Aspects.of(appStack).add(cdk_nag.AwsSolutionsChecks())

"""
要忽略的警告項目，即「這些檢查我知道，但我有正當理由不遵守」
"""
NagSuppressions.add_stack_suppressions(
    appStack,
    suppressions=[
        {"id": "AwsSolutions-IAM5", "reason": "Dynamic resource creation"},
        {
            "id": "AwsSolutions-IAM4",
            "reason": "Managed policies are used for log stream access",
        },
        {
            "id": "AwsSolutions-L1",
            "reason": "Lambda auto-created by CDK library construct",
        },
    ],
)

"""
將你在 CDK 中用程式碼描述的基礎架構轉換成
「CloudFormation 模板（CloudFormation Template）」，儲存在 cdk.out/ 目錄中。
"""
app.synth()
