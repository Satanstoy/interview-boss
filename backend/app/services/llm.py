import os
import re
import json
import time
import asyncio
import logging
import httpx
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
from app.core.outbound_url import assert_safe_outbound_url_sync
from app.services.llm_usage import normalize_cache_usage

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


def _is_mimo(base_url: str | None) -> bool:
    """判断是否为 mimo（小米）OpenAI 兼容端点：默认开启深度思考且不支持自定义
    temperature；关闭思考可显著提速并让 temperature 真正生效。"""
    return bool(base_url and "mimo" in base_url.lower())


# --------------- 供应商能力矩阵 ---------------
#
# 兼容层：部分 OpenAI 兼容端点（如 mimo Token Plan）的 json_object 模式
# 输出会被服务端截断（2026-08-06 实测：只返回 '```json\n['）。调用方保持
# 声明式传参（response_format={"type": "json_object"}），由本层按 base_url
# 前缀匹配能力决定是否下发。供应商修复后把对应前缀 json_mode 改回 True 即恢复。
# 应急开关：LLM_JSON_MODE_OVERRIDE=force-on/force-off/auto

_PROVIDER_CAPABILITIES: list[tuple[str, dict]] = [
    # mimo Token Plan：json_object 2026-08-06 曾截断 → 降级 prompt 指令；支持 chat + responses
    (
        "token-plan-cn.xiaomimimo.com",
        {
            "json_mode": False,
            "max_output_tokens": 4096,
            "api_formats": ["chat", "responses"],
            "prompt_cache_key": False,
        },
    ),
    # SiliconFlow：json_object 正常；responses 未实测，保守只声明 chat
    (
        "api.siliconflow.cn",
        {"json_mode": True, "max_output_tokens": 4096, "api_formats": ["chat"]},
    ),
    (
        "api.openai.com",
        {
            "json_mode": True,
            "max_output_tokens": 4096,
            "api_formats": ["chat", "responses"],
            "prompt_cache_key": True,
        },
    ),
    (
        "api.anthropic.com",
        {
            "json_mode": False,
            "max_output_tokens": 8192,
            "api_formats": ["anthropic"],
            "prompt_cache_control": True,
        },
    ),
    ("*", {"json_mode": False, "max_output_tokens": 4096, "api_formats": ["chat"]}),
]

_DEFAULT_CAPS = {"json_mode": False, "max_output_tokens": 4096, "api_formats": ["chat"]}


def get_provider_capabilities(base_url: str = None) -> dict:
    """按 base_url 前缀匹配供应商能力。

    Returns: {"json_mode": bool, "max_output_tokens": int, "api_formats": list[str]}
    api_formats 取值：chat（OpenAI Chat Completions）/ responses（OpenAI Responses）/
    anthropic（Anthropic Messages）。缓存能力只声明已知 provider 的安全参数；未匹配
    到具名供应商时回退 "*" 保守默认，不向兼容端点发送未知字段。
    """
    if not base_url:
        return dict(_DEFAULT_CAPS)
    lower = base_url.lower()
    for prefix, caps in _PROVIDER_CAPABILITIES:
        if prefix == "*" or prefix in lower:
            return dict(caps)
    return dict(_DEFAULT_CAPS)


def get_provider_formats(base_url: str = None) -> list[str]:
    """返回端点支持的接口格式列表（chat / responses / anthropic）。"""
    return list(get_provider_capabilities(base_url).get("api_formats", ["chat"]))


def _api_format_override() -> str:
    """接口格式应急开关：chat / responses / anthropic / auto（默认）"""
    return os.environ.get("LLM_API_FORMAT", "auto").strip().lower()


def resolve_api_format(
    base_url: str = None, user_id: int = None, llm_scope: str = "user"
) -> str:
    """解析应使用的接口格式。

    优先级：用户配置的 api_format（非 auto）→ LLM_API_FORMAT（应急开关）→
    端点能力（anthropic 端点用 anthropic；responses-only 端点用 responses；
    其余默认 chat）。
    """
    if user_id is not None and llm_scope != "global":
        try:
            from app.core.config import get_user_llm_config

            user_cfg = get_user_llm_config(user_id)
            user_format = (user_cfg or {}).get("api_format")
            if user_format and user_format != "auto":
                return user_format
        except Exception:
            pass
    override = _api_format_override()
    if override in ("chat", "responses", "anthropic"):
        return override
    if base_url is None:
        from app.core.config import LLM_BASE_URL

        base_url = LLM_BASE_URL
    formats = get_provider_formats(base_url)
    if "anthropic" in formats:
        return "anthropic"
    if "responses" in formats and "chat" not in formats:
        return "responses"
    return "chat"


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
    if base_url:
        assert_safe_outbound_url_sync(base_url)
    http_client = httpx.AsyncClient(follow_redirects=False)
    if provider == "anthropic":
        return AsyncAnthropic(
            api_key=api_key or None,
            base_url=base_url or None,
            timeout=timeout,
            http_client=http_client,
        )
    return AsyncOpenAI(
        api_key=api_key or None,
        base_url=base_url or None,
        timeout=timeout,
        http_client=http_client,
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


def get_llm_client_for_user(user_id: int, llm_scope: str = "user") -> tuple:
    """获取用户的 LLM 客户端和模型名。

    Returns:
        (client, model_name, timeout, base_url, provider)

    Raises:
        HTTPException: 用户未配置 LLM 密钥
    """
    from app.core.config import get_user_llm_config
    from fastapi import HTTPException

    if llm_scope == "global":
        from app.core.config import _get_global_llm_config

        cfg = _get_global_llm_config()
    else:
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

    # 全局配置从 user_profile 热加载，直接按当前解析结果建 client，避免
    # 复用某个管理员账号的 user_llm_config 或陈旧的用户 client。
    if llm_scope == "global":
        global_client = _make_client(api_key, base_url, timeout, provider)
        return global_client, model, timeout, base_url, provider

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


async def _probe_resolved(client, model, timeout, base_url, provider, user_id=None) -> tuple:
    """向给定的 client/model 发最小请求验证可用性，返回 (connected, error)。"""
    wait_for = max(5, min(int(timeout or _PROBE_TIMEOUT), _PROBE_TIMEOUT))
    try:
        if provider == "anthropic":
            await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                ),
                timeout=wait_for,
            )
        elif resolve_api_format(base_url, user_id) == "responses":
            await asyncio.wait_for(
                client.responses.create(
                    model=model,
                    input=[
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "ping"}],
                        }
                    ],
                    max_output_tokens=1,
                ),
                timeout=wait_for,
            )
        else:
            await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                ),
                timeout=wait_for,
            )
        return True, None
    except Exception as exc:
        return False, _classify_probe_error(exc)


async def _probe_llm(user_id: int) -> tuple:
    """向用户配置的模型发最小请求验证可用性，返回 (connected, error)。"""
    resolved_client, model, timeout, base_url, provider = get_llm_client_for_user(
        user_id
    )
    return await _probe_resolved(resolved_client, model, timeout, base_url, provider, user_id)


async def check_global_llm_status() -> dict:
    """用全局 LLM 配置探测连通性（管理员「测试连接」用，绕过缓存）。"""
    from app.core.config import _get_global_llm_config

    cfg = _get_global_llm_config()
    if not cfg or not cfg.get("api_key"):
        return {"configured": False, "connected": False, "error": None, "model": None}

    model = cfg.get("model")
    timeout = cfg.get("timeout") or 120
    base_url = cfg.get("base_url")
    provider = _detect_provider(base_url)
    client = _make_client(cfg["api_key"], base_url, timeout, provider)
    connected, error = await _probe_resolved(client, model, timeout, base_url, provider)
    return {"configured": True, "connected": connected, "error": error, "model": model}


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


def _resolve_client_and_model(user_id: int = None, llm_scope: str = "user"):
    """解析 LLM 客户端和模型。user_id 有值时使用用户配置，否则使用全局配置。"""
    if user_id is not None or llm_scope == "global":
        return get_llm_client_for_user(user_id, llm_scope=llm_scope)
    from app.core.config import LLM_BASE_URL

    return client, LLM_MODEL, LLM_TIMEOUT, LLM_BASE_URL, _detect_provider(LLM_BASE_URL)


# --------------- Tool Calling 基础设施 ---------------


from app.services.llm_converters import (
    _convert_tools_to_anthropic,
    _convert_tools_to_responses,
    _convert_tool_choice_to_anthropic,
    _convert_tool_choice_to_responses,
    _convert_messages_with_tools_to_anthropic,
    _extract_tool_calls,
    make_tool_result_message,
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
    tool_choice=None,
    base_url=None,
    user_id: int = None,
    cache_control=None,
    prompt_cache_key=None,
    prompt_cache_options=None,
    api_format: str | None = None,
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
        if tool_choice is not None:
            call_kwargs["tool_choice"] = _convert_tool_choice_to_anthropic(tool_choice)
        if cache_control is not None or get_provider_capabilities(base_url).get(
            "prompt_cache_control", False
        ):
            call_kwargs["cache_control"] = cache_control or {"type": "ephemeral"}
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
            "usage": normalize_cache_usage(getattr(response, "usage", None)),
        }

    # OpenAI path（chat 或 responses）
    if resolve_api_format(base_url, user_id) == "responses":
        caps = get_provider_capabilities(base_url)
        if not system_text:
            system_text = "\n\n".join(
                str(msg.get("content") or "")
                for msg in messages
                if msg.get("role") == "system"
            )
        input_items = _convert_messages_to_responses_input(messages, system_text)
        call_kwargs = dict(
            model=model,
            input=input_items or " ",
            instructions=system_text or None,
            max_output_tokens=caps["max_output_tokens"],
            temperature=temperature,
        )
        if tools:
            call_kwargs["tools"] = _convert_tools_to_responses(tools)
        if tool_choice is not None:
            call_kwargs["tool_choice"] = _convert_tool_choice_to_responses(tool_choice)
        if prompt_cache_key is not None and get_provider_capabilities(base_url).get(
            "prompt_cache_key", False
        ):
            call_kwargs["prompt_cache_key"] = prompt_cache_key
        if prompt_cache_options is not None and caps.get("prompt_cache_key", False):
            call_kwargs["prompt_cache_options"] = prompt_cache_options
        response = await resolved_client.responses.create(**call_kwargs)

        tool_calls = _extract_responses_tool_calls(response)
        text_content = _extract_responses_text(response)
        status = getattr(response, "status", None)
        if status == "incomplete":
            finish_reason = "length"
        elif tool_calls:
            finish_reason = "tool_calls"
        else:
            finish_reason = "stop"
        return {
            "content": text_content if text_content else None,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "usage": normalize_cache_usage(getattr(response, "usage", None)),
        }

    call_kwargs = dict(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if tools:
        call_kwargs["tools"] = tools
    if tool_choice is not None:
        call_kwargs["tool_choice"] = tool_choice
    caps = get_provider_capabilities(base_url)
    if prompt_cache_key is not None and caps.get("prompt_cache_key", False):
        call_kwargs["prompt_cache_key"] = prompt_cache_key
    if prompt_cache_options is not None and caps.get("prompt_cache_key", False):
        call_kwargs["prompt_cache_options"] = prompt_cache_options
    response = await resolved_client.chat.completions.create(**call_kwargs)

    msg = response.choices[0].message
    tool_calls = _extract_tool_calls(response, "openai")
    return {
        "content": msg.content,
        "reasoning_content": getattr(msg, "reasoning_content", None),
        "tool_calls": tool_calls,
        "finish_reason": response.choices[0].finish_reason,
        "usage": normalize_cache_usage(getattr(response, "usage", None)),
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
            "usage": {"input_tokens": int | None, ...},  # token/cache usage
        }
    """
    resolved_client, model, timeout, base_url, provider = _resolve_client_and_model(
        user_id
    )
    model = kwargs.pop("model", None) or model
    max_tokens = kwargs.get("max_tokens", 4096)
    temperature = kwargs.get("temperature", 0.7)
    tool_choice = kwargs.get("tool_choice")
    cache_control = kwargs.get("cache_control")
    prompt_cache_key = kwargs.get("prompt_cache_key")
    prompt_cache_options = kwargs.get("prompt_cache_options")

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
            tool_choice=tool_choice,
            base_url=base_url,
            user_id=user_id,
            cache_control=cache_control,
            prompt_cache_key=prompt_cache_key,
            prompt_cache_options=prompt_cache_options,
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
        tool_choice=tool_choice,
        base_url=base_url,
        user_id=user_id,
        cache_control=cache_control,
        prompt_cache_key=prompt_cache_key,
        prompt_cache_options=prompt_cache_options,
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
    **kwargs,
) -> str:
    """调用 Anthropic Messages API。"""
    # 如果需要 JSON 输出，在 system 提示中追加指令（Anthropic 不支持 response_format）
    effective_system = system_msg
    if response_format and response_format.get("type") == "json_object":
        effective_system += (
            "\n请严格以 JSON 格式输出，不要包含任何其他文字或 markdown 代码块。"
        )

    body = dict(
        model=model,
        max_tokens=max_tokens,
        system=effective_system,
        messages=messages,
        temperature=temperature,
    )
    for key in (
        "top_p",
        "top_k",
        "stop_sequences",
        "metadata",
        "service_tier",
        "thinking",
        "cache_control",
    ):
        if key in kwargs and kwargs[key] is not None:
            body[key] = kwargs[key]
    response = await anthropic_client.messages.create(**body)
    return _extract_anthropic_text(response)


def _extract_anthropic_text(response) -> str:
    """从 Anthropic 响应中提取文本，兼容 ThinkingBlock / TextBlock。"""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()
    # fallback：拼接所有 block 的 str
    return "".join(str(b) for b in response.content).strip()


def _convert_messages_to_responses_input(messages: list, system_text: str = "") -> list:
    """OpenAI messages → Responses API input items。

    映射（对齐 LiteLLM responses 规范）：
    - system role → 跳过（由调用方拼进 instructions）
    - user → message item（input_text 块）
    - assistant（含 tool_calls）→ message item（output_text）+ function_call 顶层 item
    - tool → function_call_output 顶层 item
    """
    items = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": str(msg.get("content", "") or ""),
                }
            )
            continue
        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if msg.get("content"):
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": msg["content"]}],
                    }
                )
            for tc in tool_calls or []:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": tc["id"],
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    }
                )
            continue
        items.append(
            {
                "type": "message",
                "role": role or "user",
                "content": [
                    {"type": "input_text", "text": str(msg.get("content", "") or "")}
                ],
            }
        )
    return items


def _extract_responses_tool_calls(response) -> list | None:
    """从 Responses API 响应提取 function_call items（OpenAI 统一格式）。"""
    out = getattr(response, "output", []) or []
    calls = []
    for item in out:
        if getattr(item, "type", None) == "function_call":
            calls.append(
                {
                    "id": getattr(item, "call_id", ""),
                    "function": {
                        "name": getattr(item, "name", ""),
                        "arguments": getattr(item, "arguments", "") or "",
                    },
                }
            )
    return calls or None


async def _call_responses(
    client,
    model: str,
    system_msg: str,
    messages: list,
    temperature: float = 0.3,
    response_format: dict = None,
    max_output_tokens: int = 4096,
    **kwargs,
) -> str:
    """调用 OpenAI Responses API（POST /v1/responses）。

    参数映射（对齐 LiteLLM 映射表）：
    messages+system → input + instructions；max_tokens → max_output_tokens；
    response_format(json_object) → text.format；工具消息 → function_call/function_call_output
    顶层 item；其余 OpenAI Responses 参数（tools/tool_choice/reasoning/top_p/
    parallel_tool_calls/previous_response_id/store/metadata/user 等）透传。
    """
    input_items = _convert_messages_to_responses_input(messages, system_msg)
    body = dict(
        model=model,
        input=input_items or " ",
        instructions=system_msg or None,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )
    if response_format and response_format.get("type") == "json_object":
        body["text"] = {"format": {"type": "json_object"}}
    for key in (
        "top_p",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "reasoning",
        "previous_response_id",
        "store",
        "metadata",
        "user",
        "stream_options",
        "include",
        "truncation",
        "service_tier",
    ):
        if key in kwargs and kwargs[key] is not None:
            body[key] = kwargs[key]
    response = await client.responses.create(**body)
    return _extract_responses_text(response)


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

    caps = get_provider_capabilities(base_url)
    response_format = kwargs.get("response_format")
    if response_format and not _should_use_response_format(base_url):
        # 降级：剥离 response_format；json 指令在 messages 的 system 里追加
        kwargs.pop("response_format", None)
        if response_format.get("type") == "json_object":
            msgs = list(kwargs.get("messages", []))
            if msgs and msgs[0].get("role") == "system":
                msgs[0] = {
                    **msgs[0],
                    "content": f"{msgs[0].get('content', '')}\n请严格以 JSON 格式输出，不要包含任何其他文字或 markdown 代码块。",
                }
                kwargs["messages"] = msgs

    if resolve_api_format(base_url, user_id) == "responses":
        # Responses API 路径：messages → input、system → instructions
        messages = kwargs.get("messages", [])
        system_text = ""
        for m in messages:
            if m.get("role") == "system":
                system_text += str(m.get("content", "")) + "\n"
        input_items = _convert_messages_to_responses_input(messages, system_text)
        body = dict(
            model=kwargs["model"],
            input=input_items or " ",
            instructions=system_text.strip() or kwargs.get("instructions"),
            max_output_tokens=kwargs.get(
                "max_output_tokens", kwargs.get("max_tokens", caps["max_output_tokens"])
            ),
            temperature=kwargs.get("temperature", 0.3),
        )
        for key in (
            "top_p",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "reasoning",
            "previous_response_id",
            "store",
            "metadata",
            "user",
            "text",
        ):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]
        if (
            kwargs.get("response_format")
            and kwargs["response_format"].get("type") == "json_object"
        ):
            body["text"] = {"format": {"type": "json_object"}}
        if _is_mimo(base_url) and not kwargs.get("thinking"):
            body["reasoning"] = {"effort": "none"}
        response = await resolved_client.responses.create(**body)
        return _extract_responses_text(response)

    if _is_mimo(base_url) and not kwargs.get("thinking"):
        # mimo 默认开启深度思考：长输出任务（rerank/结构化）会被思考吃光
        # max_tokens 预算导致空响应（2026-08-06 实测）→ 默认关闭，与 _call_llm_with_retry 对齐
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["thinking"] = {"type": "disabled"}
        kwargs["extra_body"] = extra_body

    kwargs.setdefault("max_tokens", caps["max_output_tokens"])

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
    thinking: bool = None,
    llm_scope: str = "user",
    temperature: float = 0.3,
) -> str:
    """带指数退避重试 + 超时保护的 LLM 调用封装（自动适配 OpenAI / Anthropic）

    model 参数非空时覆盖用户/全局默认模型配置，仅切换本次调用的模型名，
    不会修改 base_url、api_key 等其他配置。
    thinking: mimo 端点默认关闭深度思考（显著提速，temperature 才真正生效）；
              传 True 保留思考；None（默认）时按用户配置的 llm_thinking 决定。
    """
    if llm_scope == "global":
        resolved_client, resolved_model, timeout, base_url, provider = (
            _resolve_client_and_model(user_id, llm_scope="global")
        )
    else:
        # Preserve the historical one-argument resolver contract for all
        # ordinary user-scoped callers and their test doubles.
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
            temperature=temperature,
            response_format=response_format,
        )

    if thinking is None:
        try:
            if llm_scope == "global":
                thinking = False
            else:
                from app.core.config import get_user_llm_config

                user_cfg = get_user_llm_config(user_id)
                thinking = bool((user_cfg or {}).get("thinking"))
        except Exception:
            thinking = False

    if resolve_api_format(base_url, user_id, llm_scope=llm_scope) == "responses":
        caps = get_provider_capabilities(base_url)
        if response_format and _should_use_response_format(base_url):
            return await _call_responses(
                resolved_client,
                resolved_model,
                system_msg,
                [{"role": "user", "content": prompt}],
                temperature=temperature,
                response_format=response_format,
                max_output_tokens=caps["max_output_tokens"],
            )
        # json_mode=false 时降级：prompt 指令 + 无 text.format
        effective_system = system_msg
        if response_format and response_format.get("type") == "json_object":
            effective_system += (
                "\n请严格以 JSON 格式输出，不要包含任何其他文字或 markdown 代码块。"
            )
        return await _call_responses(
            resolved_client,
            resolved_model,
            effective_system,
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            max_output_tokens=caps["max_output_tokens"],
        )

    kwargs = dict(
        model=resolved_model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
    )
    caps = get_provider_capabilities(base_url)
    if response_format and _should_use_response_format(base_url):
        kwargs["response_format"] = response_format
    else:
        # 降级：端点不支持/不可靠 json_object → prompt 指令约束 + 调用方容错解析兜底
        if response_format and response_format.get("type") == "json_object":
            kwargs["messages"][0]["content"] = (
                f"{system_msg}\n请严格以 JSON 格式输出，不要包含任何其他文字或 markdown 代码块。"
            )
    if not thinking and _is_mimo(base_url):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    kwargs["max_tokens"] = caps["max_output_tokens"]

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
    caps = get_provider_capabilities(base_url)
    response_format = kwargs.get("response_format")
    if response_format and not _should_use_response_format(base_url):
        kwargs.pop("response_format", None)
    kwargs.setdefault("max_tokens", caps["max_output_tokens"])

    if resolve_api_format(base_url, user_id) == "responses":
        system_text = ""
        for m in messages:
            if m.get("role") == "system":
                system_text += str(m.get("content", "")) + "\n"
        input_items = _convert_messages_to_responses_input(messages, system_text)
        kwargs.pop("messages", None)
        kwargs["input"] = input_items or " "
        kwargs["instructions"] = (
            kwargs.get("instructions") or system_text.strip() or None
        )
        kwargs["max_output_tokens"] = kwargs.pop(
            "max_tokens", caps["max_output_tokens"]
        )
        if (
            kwargs.get("response_format")
            and kwargs["response_format"].get("type") == "json_object"
        ):
            kwargs["text"] = {"format": {"type": "json_object"}}
        kwargs.pop("response_format", None)
        response = await resolved_client.responses.create(**kwargs)
        return _extract_responses_text(response)

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

    if resolve_api_format(base_url, user_id) == "responses":
        # Responses API 流式：语义事件
        kwargs.pop("messages", None)
        kwargs["input"] = kwargs.pop(
            "input", None
        ) or _convert_messages_to_responses_input(messages, "")
        stream = await resolved_client.responses.create(stream=True, **kwargs)
        async for event in stream:
            etype = getattr(event, "type", "")
            if etype == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    if yield_thinking:
                        yield {"type": "content", "content": delta}
                    else:
                        yield delta
            elif etype in (
                "response.reasoning_text.delta",
                "response.reasoning_summary_text.delta",
            ):
                delta = getattr(event, "delta", "")
                if delta and yield_thinking:
                    yield {"type": "thinking", "content": delta}
        return

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
