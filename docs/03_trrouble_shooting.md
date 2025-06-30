# 幾個常見 Bug SOP

## Agent

### Agent Thinking Step
1. ```Handler error: An error occurred (dependencyFailedException) when calling the InvokeAgent operation: Received failed response from API execution. Retry the request later.```

原因: Agent 使用的工具本身出錯

解決方向: 
- 確定正在使用的工具 (目前皆為特定 Lambda Function)
- 檢查該工具的 Log

2. ```Handler error: AWSHTTPSConnectionPool(host='bedrock-agent-runtime.us-east-1.amazonaws.com', port=443): Read timed out.```

原因: Agent 使用的工具本身出錯

解決方向:
- 確定正在使用的工具 (目前皆為特定 Lambda Function)
- 檢查該工具的 Log
- 若真的遇到工具執行時間會Timeout，建議改為異步工具
- 最極端的處理方式，開爆等待時間 (Agent Thinking)

3. ```Handler error: An error occurred (internalServerException) when calling the InvokeAgent operation: A service unavailable exception was thrown from Bedrock when invoking the model. Retry the request.```

原因: 因為 Bedrock 服務在**特定模型**用戶用量較大，用量有徒增情況造成短暫資源不足而導致服務不可用

解決方向:
- 換模型 (檢查現在的Agent使用[哪個模型](./../config/dev.json))
- 等待...碰運氣...


4. ```Handler error: An error occurred (dependencyFailedException) when calling the InvokeAgent operation: Your request couldn't be completed. Lambda function <lambda-arn> encountered a problem while processing request.The error message from the Lambda function is Unhandled. Check the Lambda function log for error details, then try your request again after fixing the error.```


### 