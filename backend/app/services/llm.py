import os
import re
import json
import time
import asyncio
import logging
from openai import (
    AsyncOpenAI,
    APIConnectionError,
    RateLimitError,
    APITimeoutError,
    AuthenticationError,
)
from anthropic import AsyncAnthropic
import anthropic as anthropic_mod
from tenacity import (
    retry,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    retry_if_exception_type,
)
from app.core.config import LLM_MODEL, LLM_TIMEOUT

logger = logging.getLogger("interview-boss")

# 联合所有需要重试的异常类型（OpenAI + Anthropic）
_RETRYABLE_EXCEPTIONS = (
    APIConnectionError,
    RateLimitError,
    APITimeoutError,
    asyncio.TimeoutError,
    anthropic_mod.APIConnectionError,
    anthropic_mod.RateLimitError,
    anthropic_mod.APITimeoutError,
)

# 全局默认 client（openai 或 anthropic 类型）
client = None


# --------------- 提供商检测 ---------------


def _detect_provider(base_url: str) -> str:
    """根据 base_url 判断 LLM 提供商类型：'anthropic' 或 'openai'"""
    if not base_url:
        return "openai"
    lower = base_url.lower()
    if "anthropic" in lower:
        return "anthropic"
    return "openai"


# --------------- 供应商能力矩阵 ---------------


_PROVIDER_CAPABILITIES: list[tuple[str, dict]] = [
    ("token-plan-cn.xiaomimimo.com", {"json_mode": False, "max_output_tokens": 4096}),
    ("api.siliconflow.cn", {"json_mode": True, "max_output_tokens": 4096}),
    ("api.openai.com", {"json_mode": True, "max_output_tokens": 4096}),
    ("*", {"json_mode": False, "max_output_tokens": 4096}),
]

_DEFAULT_CAPS = {"json_mode": False, "max_output_tokens": 4096}


def get_provider_capabilities(base_url: str = None) -> dict:
    """按 base_url 前缀匹配供应商能力。未匹配到具名供应商时回退 "*" 保守默认。"""
    if not base_url:
        return dict(_DEFAULT_CAPS)
    lower = base_url.lower()
    for prefix, caps in _PROVIDER_CAPABILITIES:
        if prefix == "*" or prefix in lower:
            return dict(caps)
    return dict(_DEFAULT_CAPS)


def _json_mode_override() -> str:
    """应急开关：force-on / force-off / auto（默认）"""
    return os.environ.get("LLM_JSON_MODE_OVERRIDE", "auto").strip().lower()


def _should_use_response_format(base_url: str = None) -> bool:
    """判断当前配置的 LLM 端点是否应下发 response_format（json_object）。

    优先级：LLM_JSON_MODE_OVERRIDE（应急开关）→ 能力矩阵 → provider 兜底。
    Anthropic 原生不支持，恒 False（走 prompt 指令降级，见 _call_anthropic）。
    """
    override = _json_mode_override()
    if override == "force-on":
        return True
    if override == "force-off":
        return False
    if base_url is None:
        from app.core.config import LLM_BASE_URL

        base_url = LLM_BASE_URL
    if _detect_provider(base_url) != "openai":
        return False
    return get_provider_capabilities(base_url)["json_mode"]


def _make_client(api_key: str, base_url: str, timeout: float, provider: str = "openai"):
    """根据 provider 创建对应的 LLM 客户端。"""
    if provider == "anthropic":
        return AsyncAnthropic(
            api_key=api_key or None, base_url=base_url or None, timeout=timeout
        )
    return AsyncOpenAI(
        api_key=api_key or None, base_url=base_url or None, timeout=timeout
    )


def _init_global_client():
    """初始化全局 client（从环境变量读取）。"""
    global client
    base_url = os.environ.get("OPENAI_BASE_URL")
    provider = _detect_provider(base_url)
    client = _make_client(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=base_url,
        timeout=LLM_TIMEOUT,
        provider=provider,
    )


_init_global_client()


def rebuild_clients():
    """用 config 模块中的当前值重建 LLM 客户端（配置热更新时调用）"""
    global client
    from app.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_TIMEOUT as _TIMEOUT

    provider = _detect_provider(LLM_BASE_URL)
    client = _make_client(LLM_API_KEY or None, LLM_BASE_URL or None, _TIMEOUT, provider)
    logger.info(f"LLM 客户端已重建（provider={provider}）")


# --------------- Per-user client 缓存 ---------------

_MAX_USER_CLIENT_CACHE = 50  # 最多缓存 50 个用户的 LLM 客户端
_user_client_cache: dict[
    int, tuple
] = {}  # user_id -> (api_key, base_url, timeout, client, provider)


def get_llm_client_for_user(user_id: int) -> tuple:
    """获取用户的 LLM 客户端和模型名。

    Returns:
        (client, model_name, timeout, base_url, provider)

    Raises:
        HTTPException: 用户未配置 LLM 密钥
    """
    from app.core.config import get_user_llm_config
    from fastapi import HTTPException

    cfg = get_user_llm_config(user_id)
    if not cfg:
        raise HTTPException(
            status_code=400, detail="请先在设置中配置 LLM 密钥才能使用 AI 功能"
        )

    api_key = cfg["api_key"]
    base_url = cfg["base_url"]
    model = cfg["model"]
    timeout = cfg["timeout"]
    provider = _detect_provider(base_url)

    # 检查缓存（配置未变则复用 client）
    cached = _user_client_cache.get(user_id)
    if (
        cached
        and cached[0] == api_key
        and cached[1] == base_url
        and cached[2] == timeout
    ):
        return cached[3], model, timeout, base_url, cached[4]

    user_client = _make_client(api_key, base_url, timeout, provider)

    # 缓存淘汰：超过上限时清除最旧的一半
    if len(_user_client_cache) >= _MAX_USER_CLIENT_CACHE:
        keys = list(_user_client_cache.keys())
        for k in keys[: len(keys) // 2]:
            _user_client_cache.pop(k, None)

    _user_client_cache[user_id] = (api_key, base_url, timeout, user_client, provider)
    return user_client, model, timeout, base_url, provider


def clear_user_client_cache(user_id: int = None):
    """清除用户 LLM 客户端缓存（配置更新后调用）"""
    if user_id is not None:
        _user_client_cache.pop(user_id, None)
    else:
        _user_client_cache.clear()


# --------------- 模型可用性状态探测 ---------------

_LLM_STATUS_CACHE_TTL = 120  # 探测结果缓存秒数
_llm_status_cache: dict[
    int, tuple
] = {}  # user_id -> (配置指纹, connected, error, 探测时间戳)

_PROBE_TIMEOUT = 15  # 单次探测最大秒数


def clear_llm_status_cache(user_id: int = None):
    """清除用户模型状态探测缓存（配置更新后调用）"""
    if user_id is not None:
        _llm_status_cache.pop(user_id, None)
    else:
        _llm_status_cache.clear()


def _classify_probe_error(exc: Exception) -> str:
    """把探测异常归类为用户可读的错误信息"""
    if isinstance(exc, AuthenticationError) or isinstance(
        exc, anthropic_mod.AuthenticationError
    ):
        return "认证失败：请检查 API Key 是否正确"
    if isinstance(exc, RateLimitError) or isinstance(exc, anthropic_mod.RateLimitError):
        return "请求过于频繁：请稍后重试"
    if (
        isinstance(exc, APITimeoutError)
        or isinstance(exc, anthropic_mod.APITimeoutError)
        or isinstance(exc, asyncio.TimeoutError)
    ):
        return "模型服务响应超时：请稍后重试"
    if isinstance(exc, APIConnectionError) or isinstance(
        exc, anthropic_mod.APIConnectionError
    ):
        return "无法连接模型服务：请检查 Base URL"
    return f"模型服务异常：{type(exc).__name__}: {str(exc)[:200]}"


async def _probe_llm(user_id: int) -> tuple:
    """向用户配置的模型发最小请求验证可用性，返回 (connected, error)。"""
    resolved_client, model, timeout, base_url, provider = get_llm_client_for_user(
        user_id
    )
    wait_for = max(5, min(int(timeout or _PROBE_TIMEOUT), _PROBE_TIMEOUT))
    try:
        if provider == "anthropic":
            await asyncio.wait_for(
                resolved_client.messages.create(
                    model=model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                ),
                timeout=wait_for,
            )
        else:
            await asyncio.wait_for(
                resolved_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                ),
                timeout=wait_for,
            )
        return True, None
    except Exception as exc:
        return False, _classify_probe_error(exc)


async def check_llm_status(user_id: int, force_probe: bool = False) -> dict:
    """检查用户的 LLM 模型是否可提供服务。

    返回 dict：
    - configured: 是否已配置（用户配置或全局默认）
    - connected: 最小请求探测是否成功（未配置时为 False）
    - error: 探测失败的用户可读原因（成功或未配置时为 None）
    - model: 当前生效的模型名（未配置时为 None）
    """
    from app.core.config import get_user_llm_config

    cfg = get_user_llm_config(user_id)
    if not cfg or not cfg.get("api_key"):
        return {
            "configured": False,
            "connected": False,
            "error": None,
            "model": None,
        }

    fingerprint = (cfg.get("api_key"), cfg.get("base_url"), cfg.get("model"))
    now = time.time()
    cached = _llm_status_cache.get(user_id)
    if (
        not force_probe
        and cached
        and cached[0] == fingerprint
        and (now - cached[3]) < _LLM_STATUS_CACHE_TTL
    ):
        return {
            "configured": True,
            "connected": cached[1],
            "error": cached[2],
            "model": fingerprint[2],
        }

    connected, error = await _probe_llm(user_id)
    _llm_status_cache[user_id] = (fingerprint, connected, error, now)
    return {
        "configured": True,
        "connected": connected,
        "error": error,
        "model": fingerprint[2],
    }


def _resolve_client_and_model(user_id: int = None):
    """解析 LLM 客户端和模型。user_id 有值时使用用户配置，否则使用全局配置。"""
    if user_id is not None:
        return get_llm_client_for_user(user_id)
    from app.core.config import LLM_BASE_URL

    return client, LLM_MODEL, LLM_TIMEOUT, LLM_BASE_URL, _detect_provider(LLM_BASE_URL)


# --------------- Tool Calling 基础设施 ---------------


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


@retry(
    stop=stop_after_attempt(4) | stop_after_delay(60),
    wait=wait_exponential(multiplier=2, min=3, max=15),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    before_sleep=lambda retry_state: logger.warning(
        f"llm_with_tools 调用失败，第 {retry_state.attempt_number} 次重试: {retry_state.outcome.exception()}"
    ),
)
async def _llm_with_tools_call(
    resolved_client,
    model,
    messages,
    tools,
    provider,
    max_tokens,
    temperature,
    system_text,
) -> dict:
    """带重试的 tool calling LLM 调用（内部函数）。"""
    if provider == "anthropic":
        anthropic_tools = _convert_tools_to_anthropic(tools) if tools else []
        call_kwargs = dict(
            model=model,
            system=system_text or "你是一个面试官。",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if anthropic_tools:
            call_kwargs["tools"] = anthropic_tools
        response = await resolved_client.messages.create(**call_kwargs)

        tool_calls = _extract_tool_calls(response, "anthropic")
        text_content = _extract_anthropic_text(response)

        # 统一 finish_reason 为 OpenAI 术语，并检查 max_tokens 截断
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            finish_reason = "length"
        elif tool_calls:
            finish_reason = "tool_calls"
        else:
            finish_reason = "stop"

        return {
            "content": text_content if text_content else None,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
        }

    # OpenAI path
    call_kwargs = dict(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if tools:
        call_kwargs["tools"] = tools
    response = await resolved_client.chat.completions.create(**call_kwargs)

    msg = response.choices[0].message
    tool_calls = _extract_tool_calls(response, "openai")
    return {
        "content": msg.content,
        "reasoning_content": getattr(msg, "reasoning_content", None),
        "tool_calls": tool_calls,
        "finish_reason": response.choices[0].finish_reason,
    }


async def llm_with_tools(
    messages: list,
    tools: list,
    user_id: int = None,
    **kwargs,
) -> dict:
    """带 tool calling 的 LLM 调用（自动适配 OpenAI / Anthropic，带指数退避重试）。

    Args:
        messages: OpenAI 格式消息列表
        tools: OpenAI 格式 tools schema
        user_id: 用户 ID（用于获取用户配置的 LLM client）

    Returns:
        {
            "content": str | None,   # LLM 文本回复（tool calling 时可能为 None）
            "tool_calls": list | None,  # [{"id", "function": {"name", "arguments"}}]
            "finish_reason": "stop" | "tool_calls" | "length",
        }
    """
    resolved_client, model, timeout, base_url, provider = _resolve_client_and_model(
        user_id
    )
    model = kwargs.pop("model", None) or model
    max_tokens = kwargs.get("max_tokens", 4096)
    temperature = kwargs.get("temperature", 0.7)

    # Anthropic 需要预先转换消息格式
    if provider == "anthropic":
        system_text, anthropic_msgs = _convert_messages_with_tools_to_anthropic(
            messages
        )
        return await _llm_with_tools_call(
            resolved_client,
            model,
            anthropic_msgs,
            tools,
            provider,
            max_tokens,
            temperature,
            system_text,
        )

    return await _llm_with_tools_call(
        resolved_client,
        model,
        messages,
        tools,
        provider,
        max_tokens,
        temperature,
        None,
    )


# --------------- JSON 提取 ---------------


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


# --------------- Anthropic 辅助 ---------------


def _convert_openai_messages_to_anthropic(messages: list) -> tuple[str, list]:
    """将 OpenAI 格式 messages 转换为 Anthropic 格式。

    Returns:
        (system_text, anthropic_messages)
    """
    system_text = ""
    anthropic_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_text += (
                msg["content"]
                if isinstance(msg["content"], str)
                else str(msg["content"])
            ) + "\n"
        elif msg["role"] in ("user", "assistant"):
            content = msg["content"]
            # 处理 multimodal content（OpenAI 格式：[{"type":"text",...}, {"type":"image_url",...}]）
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
                            # data URI：解析 media_type 和 base64
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
                            # 普通 URL（Anthropic 不直接支持 URL，转为 text 提示）
                            anthropic_blocks.append(
                                {"type": "text", "text": f"[图片链接: {url}]"}
                            )
                content = anthropic_blocks
            anthropic_messages.append({"role": msg["role"], "content": content})
    return system_text.strip(), anthropic_messages


async def _call_anthropic(
    anthropic_client: AsyncAnthropic,
    model: str,
    timeout: float,
    system_msg: str,
    messages: list,
    temperature: float = 0.3,
    response_format: dict = None,
    max_tokens: int = 8192,
) -> str:
    """调用 Anthropic Messages API。"""
    # 如果需要 JSON 输出，在 system 提示中追加指令（Anthropic 不支持 response_format）
    effective_system = system_msg
    if response_format and response_format.get("type") == "json_object":
        effective_system += (
            "\n请严格以 JSON 格式输出，不要包含任何其他文字或 markdown 代码块。"
        )

    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=effective_system,
        messages=messages,
        temperature=temperature,
    )
    response = await anthropic_client.messages.create(**kwargs)
    return _extract_anthropic_text(response)


def _extract_anthropic_text(response) -> str:
    """从 Anthropic 响应中提取文本，兼容 ThinkingBlock / TextBlock。"""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()
    # fallback：拼接所有 block 的 str
    return "".join(str(b) for b in response.content).strip()


async def raw_llm_call(user_id: int, **kwargs) -> str:
    """统一的原始 LLM 调用接口，自动适配 OpenAI / Anthropic。

    kwargs 使用 OpenAI 格式（model, messages, temperature, response_format 等）。
    返回 LLM 输出文本。
    """
    resolved_client, model, timeout, base_url, provider = _resolve_client_and_model(
        user_id
    )

    # 处理 model=None 的情况，使用默认模型
    if kwargs.get("model") is None:
        kwargs["model"] = model

    if provider == "anthropic":
        messages = kwargs.get("messages", [])
        system_text, anthropic_msgs = _convert_openai_messages_to_anthropic(messages)
        response_format = kwargs.get("response_format")
        system_msg = system_text or "你是一个后端和算法面试指导专家。"
        if response_format and response_format.get("type") == "json_object":
            system_msg += (
                "\n请严格以 JSON 格式输出，不要包含任何其他文字或 markdown 代码块。"
            )
        response = await resolved_client.messages.create(
            model=kwargs["model"],
            max_tokens=kwargs.get("max_tokens", 8192),
            system=system_msg,
            messages=anthropic_msgs,
            temperature=kwargs.get("temperature", 0.3),
        )
        return _extract_anthropic_text(response)

    response = await resolved_client.chat.completions.create(**kwargs)
    return response.choices[0].message.content.strip()


# --------------- LLM 调用 ---------------


@retry(
    stop=stop_after_attempt(4) | stop_after_delay(60),
    wait=wait_exponential(multiplier=2, min=3, max=15),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    before_sleep=lambda retry_state: logger.warning(
        f"LLM 调用失败，第 {retry_state.attempt_number} 次重试: {retry_state.outcome.exception()}"
    ),
)
async def _call_llm_with_retry(
    prompt: str,
    system_msg: str = "你是一个后端和算法面试指导专家。",
    response_format: dict = None,
    user_id: int = None,
    model: str = None,
) -> str:
    """带指数退避重试 + 超时保护的 LLM 调用封装（自动适配 OpenAI / Anthropic）

    model 参数非空时覆盖用户/全局默认模型配置，仅切换本次调用的模型名，
    不会修改 base_url、api_key 等其他配置。
    """
    resolved_client, resolved_model, timeout, base_url, provider = (
        _resolve_client_and_model(user_id)
    )
    if model:
        resolved_model = model

    if provider == "anthropic":
        return await _call_anthropic(
            resolved_client,
            resolved_model,
            timeout,
            system_msg=system_msg,
            messages=[{"role": "user", "content": prompt}],
            response_format=response_format,
        )

    kwargs = dict(
        model=resolved_model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    if response_format and _should_use_response_format(base_url):
        kwargs["response_format"] = response_format

    response = await resolved_client.chat.completions.create(**kwargs)
    return response.choices[0].message.content.strip()


@retry(
    stop=stop_after_attempt(4) | stop_after_delay(60),
    wait=wait_exponential(multiplier=2, min=3, max=15),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    before_sleep=lambda retry_state: logger.warning(
        f"LLM 调用失败，第 {retry_state.attempt_number} 次重试: {retry_state.outcome.exception()}"
    ),
)
async def _call_llm_with_retry_messages(
    messages: list, user_id: int = None, **kwargs
) -> str:
    """带重试的 LLM 调用，支持 multimodal messages（图片+文本），自动适配 OpenAI / Anthropic"""
    resolved_client, model, timeout, base_url, provider = _resolve_client_and_model(
        user_id
    )

    if provider == "anthropic":
        system_text, anthropic_msgs = _convert_openai_messages_to_anthropic(messages)
        return await _call_anthropic(
            resolved_client,
            model,
            timeout,
            system_msg=system_text or "你是一个后端和算法面试指导专家。",
            messages=anthropic_msgs,
            max_tokens=kwargs.get("max_tokens", 8192),
        )

    kwargs.setdefault("model", model)
    response = await resolved_client.chat.completions.create(
        messages=messages, **kwargs
    )
    return response.choices[0].message.content.strip()


async def stream_llm_messages(
    messages: list, user_id: int = None, yield_thinking: bool = False, **kwargs
):
    """流式 LLM 调用，yield 每个 chunk 的文本内容。仅支持 OpenAI 兼容 API。

    Args:
        yield_thinking: 如果为 True，yield dict {"type": "thinking"/"content", "content": "..."}，
                       用于支持 DeepSeek 等模型的 reasoning_content。默认 False（向后兼容，yield str）。
        model: 可选，覆盖用户默认模型。
    """
    resolved_client, model, timeout, base_url, provider = _resolve_client_and_model(
        user_id
    )

    if kwargs.get("model"):
        model = kwargs.pop("model")

    if provider == "anthropic":
        # Anthropic 流式：转换消息格式
        system_text, anthropic_msgs = _convert_openai_messages_to_anthropic(messages)
        async with resolved_client.messages.stream(
            model=model,
            system=system_text or "你是一个后端和算法面试指导专家。",
            messages=anthropic_msgs,
            max_tokens=kwargs.get("max_tokens", 4096),
            temperature=kwargs.get("temperature", 0.7),
        ) as stream:
            async for event in stream:
                # Anthropic 流式事件：检查是否是 ThinkingBlock
                if hasattr(event, "type"):
                    if event.type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", None) == "thinking":
                            # ThinkingBlock 开始
                            if yield_thinking:
                                yield {"type": "thinking_start", "content": ""}
                    elif event.type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            if hasattr(delta, "thinking") and delta.thinking:
                                # ThinkingBlock 内容
                                if yield_thinking:
                                    yield {
                                        "type": "thinking",
                                        "content": delta.thinking,
                                    }
                            elif hasattr(delta, "text") and delta.text:
                                # TextBlock 内容
                                if yield_thinking:
                                    yield {"type": "content", "content": delta.text}
                                else:
                                    yield delta.text
                elif hasattr(event, "text") and event.text:
                    # Fallback: 直接文本
                    if yield_thinking:
                        yield {"type": "content", "content": event.text}
                    else:
                        yield event.text
        return

    # OpenAI 兼容流式
    kwargs.setdefault("model", model)
    kwargs.setdefault("temperature", 0.7)
    stream = await resolved_client.chat.completions.create(
        messages=messages,
        stream=True,
        **kwargs,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        # 检查 reasoning_content（DeepSeek 等模型）
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning and yield_thinking:
            yield {"type": "thinking", "content": reasoning}
            continue

        # 普通内容
        if delta.content:
            if yield_thinking:
                yield {"type": "content", "content": delta.content}
            else:
                yield delta.content
