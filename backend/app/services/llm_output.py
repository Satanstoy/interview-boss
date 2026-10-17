import json
import re


def _repair_json(text: str) -> str:
    """修复 LLM 返回的常见 JSON 语法错误"""
    # 移除对象/数组末尾的多余逗号: {"a":1,} → {"a":1}
    text = re.sub(r",\s*([\]}])", r"\1", text)
    return text



def _extract_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON，兼容 markdown 代码块包裹的情况"""
    text = text.strip()

    def _try_parse(s):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return json.loads(_repair_json(s))

    # 尝试直接解析
    try:
        return _try_parse(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return _try_parse(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 尝试找到第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return _try_parse(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("无法从 LLM 响应中提取 JSON", text, 0)



def _extract_anthropic_text(response) -> str:
    """从 Anthropic 响应中提取文本，兼容 ThinkingBlock / TextBlock。"""
    parts = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    if parts:
        return "".join(parts).strip()
    # fallback：拼接所有 block 的 str
    return "".join(str(b) for b in response.content).strip()



def _extract_responses_text(response) -> str:
    """从 Responses API 响应提取文本（兼容 reasoning + message 混合、流式输出）。"""
    if hasattr(response, "output_text"):
        text = response.output_text
        if text:
            return text.strip()
    out = getattr(response, "output", []) or []
    parts = []
    for item in out:
        if getattr(item, "type", None) == "message":
            for block in getattr(item, "content", []) or []:
                text = getattr(block, "text", "") or ""
                if text:
                    parts.append(text)
    return "".join(parts).strip()
