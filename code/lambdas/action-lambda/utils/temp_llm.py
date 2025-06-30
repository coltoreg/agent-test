import json, boto3, time, random
from typing import Dict, Any

MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"   # 目標 Bedrock FM
REGION    = "us-east-1"                                   # Bedrock 佈建區域

_client = boto3.client("bedrock-runtime", region_name=REGION)

def claude_call(system_prompt: str, user_text: str,
                *, max_tokens: int = 1024, temperature: float = 0.2) -> str:
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_text}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    })

    for i in range(5):  # 簡單限流重試
        try:
            resp = _client.invoke_model(modelId=MODEL_ID, body=body)
            return resp["body"].read().decode("utf-8")
        except Exception as e:
            if "Throttling" in str(e) or "Too many tokens" in str(e):
                time.sleep(2 ** i + random.random())
                continue
            raise
    raise RuntimeError("Claude invocation failed after retries")


def parse_claude_json(raw: str | Dict[str, Any]) -> Dict[str, str]:
    """
    將 Claude Bedrock 回傳（dict 或 str）解析成真正的 JSON dict。

    Claude 典型回傳:
    {
      "role":"assistant",
      "content":[ {"type":"text","text":"{\"company\":\"...\"}"} ],
      ...
    }

    Returns
    -------
    dict  # 若解析失敗則拋出 ValueError
    """
    # 若剛好已經是 dict 就直接用；否則先 loads
    try:
        resp = raw if isinstance(raw, dict) else json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"上層 JSON 解析失敗: {e}")

    try:
        text_block = resp["content"][0]["text"]
        return json.loads(text_block)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise ValueError(f"內層 JSON 解析失敗: {e}")

# ── demo ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    system = "You are a JSON extractor. Return {\"company\":\"\",\"brand\":\"\", \"company\":\"\",\"date\":\"\"}."
    text   = "公司：L’Oréal Group，產品：Advanced Génifique Youth Activating Serum"
    print(claude_call(system, text))
