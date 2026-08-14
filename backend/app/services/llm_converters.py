"""消息/工具格式转换器 - 从 llm.py 机械抽取。

职责:OpenAI-compatible tool/message 到 Anthropic/Responses 的格式转换,
及工具调用结果/工具调用提取。被 llm.llm_with_tools 等调用。
"""
import json
import logging

logger = logging.getLogger("interview-boss")


def _convert_tools_to_anthropic(openai_tools: list) -> list:
    """将 OpenAI 格式 tools schema 转换为 Anthropic 格式。

    OpenAI: {"type": "function", "function": {"name", "description", "parameters"}}
    Anthropic: {"name", "description", "input_schema"}
    """
    anthropic_tools = []
    for t in openai_tools:
        func = t.get("function", t)
        anthropic_tools.append(
            {
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func["parameters"],
            }
        )
    return anthropic_tools


def _convert_tools_to_responses(openai_tools: list) -> list:
    """OpenAI Chat tools → Responses API 扁平格式。

    OpenAI: {"type": "function", "function": {"name", "description", "parameters", "strict"}}
    Responses: {"type": "function", "name", "description", "parameters", "strict"}
    """
    responses_tools = []
    for t in openai_tools:
        if t.get("type") != "function":
            responses_tools.append(t)  # 内置工具原样透传
            continue
        func = t.get("function", {})
        item = {"type": "function", "name": func["name"]}
        if func.get("description"):
            item["description"] = func["description"]
        if func.get("parameters"):
            item["parameters"] = func["parameters"]
        if func.get("strict") is not None:
            item["strict"] = func["strict"]
        responses_tools.append(item)
    return responses_tools


def _convert_tool_choice_to_anthropic(tool_choice) -> dict:
    """OpenAI tool_choice → Anthropic 格式。

    auto → {"type": "auto"}；required → {"type": "any"}；
    {"type": "function", "function": {"name": N}} → {"type": "tool", "name": N}；
    none → {"type": "none"}
    """
    if isinstance(tool_choice, str):
        if tool_choice == "required":
            return {"type": "any"}
        if tool_choice == "none":
            return {"type": "none"}
        return {"type": "auto"}
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            fn = tool_choice.get("function", {})
            name = fn.get("name") if isinstance(fn, dict) else None
            return {"type": "tool", "name": name} if name else {"type": "auto"}
        if tool_choice.get("type") in ("any", "auto", "none", "tool"):
            return tool_choice
    return {"type": "auto"}


def _convert_tool_choice_to_responses(tool_choice):
    """OpenAI Chat tool_choice → Responses 格式（扁平 name 字段）。

    {"type": "function", "function": {"name": N}} → {"type": "function", "name": N}
    """
    if isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            fn = tool_choice.get("function", {})
            name = fn.get("name") if isinstance(fn, dict) else None
            return {"type": "function", "name": name} if name else "auto"
        return tool_choice
    return "auto"


def _convert_messages_with_tools_to_anthropic(messages: list) -> tuple[str, list]:
    """将含 tool_calls / tool role 的 OpenAI 消息转换为 Anthropic 格式。

    处理:
    - assistant.content + assistant.tool_calls → assistant.content [text_block, tool_use_block, ...]
    - role=tool → role=user, content=[tool_result_block]
    - 连续的 tool result 合并为单条 user 消息（Anthropic 要求 user/assistant 严格交替）
    - 支持 is_error 标记（tool 执行失败时传给 LLM）

    Returns:
        (system_text, anthropic_messages)
    """
    system_text = ""
    anthropic_messages = []

    for msg in messages:
        role = msg["role"]

        if role == "system":
            system_text += (
                msg["content"]
                if isinstance(msg["content"], str)
                else str(msg["content"])
            ) + "\n"

        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # 有 tool_calls：构建 content blocks
                content_blocks = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in tool_calls:
                    arguments = tc["function"]["arguments"]
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": arguments,
                        }
                    )
                anthropic_messages.append(
                    {"role": "assistant", "content": content_blocks}
                )
            elif msg.get("content"):
                # 无 tool_calls：保持原样（兼容旧逻辑）
                anthropic_messages.append(
                    {"role": "assistant", "content": msg["content"]}
                )

        elif role == "tool":
            # OpenAI tool result → Anthropic user message with tool_result block
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": msg["tool_call_id"],
                "content": msg["content"],
            }
            if msg.get("is_error"):
                tool_result_block["is_error"] = True
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [tool_result_block],
                }
            )

        elif role == "user":
            content = msg["content"]
            # 处理 multimodal content
            if isinstance(content, list):
                anthropic_blocks = []
                for block in content:
                    if block.get("type") == "text":
                        anthropic_blocks.append({"type": "text", "text": block["text"]})
                    elif block.get("type") == "image_url":
                        url_data = block.get("image_url", {})
                        url = (
                            url_data.get("url", "")
                            if isinstance(url_data, dict)
                            else url_data
                        )
                        if url.startswith("data:"):
                            header, b64data = url.split(",", 1)
                            media_type = header.split(";")[0].replace("data:", "")
                            anthropic_blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": b64data,
                                    },
                                }
                            )
                        else:
                            anthropic_blocks.append(
                                {"type": "text", "text": f"[图片链接: {url}]"}
                            )
                content = anthropic_blocks
            anthropic_messages.append({"role": "user", "content": content})

    # Anthropic 严格要求 user/assistant 交替，合并连续的 user 消息
    # （多个 tool_result 时 OpenAI 会产生连续 role=tool → 转为连续 user，需合并）
    merged = []
    for msg in anthropic_messages:
        if merged and merged[-1]["role"] == "user" and msg["role"] == "user":
            prev_content = merged[-1]["content"]
            new_content = msg["content"]
            if isinstance(prev_content, str):
                prev_content = [{"type": "text", "text": prev_content}]
            if isinstance(new_content, str):
                new_content = [{"type": "text", "text": new_content}]
            merged[-1]["content"] = prev_content + new_content
        else:
            merged.append(msg)

    return system_text.strip(), merged


def _extract_tool_calls(response, provider: str) -> list[dict] | None:
    """从 LLM 响应中提取 tool calls，统一为 OpenAI 格式。

    Returns:
        [{"id": str, "function": {"name": str, "arguments": str}}] 或 None
    """
    if provider == "anthropic":
        tool_calls = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input, ensure_ascii=False),
                        },
                    }
                )
        return tool_calls or None

    # OpenAI
    msg = response.choices[0].message
    if msg.tool_calls:
        return [
            {
                "id": tc.id,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return None


def make_tool_result_message(tool_call_id: str, result: str) -> dict:
    """构造 tool result 消息（OpenAI 格式）。

    传给 _convert_messages_with_tools_to_anthropic 时会自动转为 Anthropic 格式。
    """
    return {"role": "tool", "tool_call_id": tool_call_id, "content": result}
