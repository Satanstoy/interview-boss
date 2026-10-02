"""Protocol selection and provider capability policy for LLM clients.

Keeping this policy separate from the request/retry implementation makes the
large LLM service easier to review without changing its compatibility surface.
The original service re-exports these names for existing callers and tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from urllib.parse import urlsplit


logger = logging.getLogger("interview-boss")

_SUPPORTED_API_FORMATS = ("chat", "responses", "anthropic")
_API_FORMAT_CACHE_TTL = 600
_PROBE_TIMEOUT = 15
_api_format_cache: dict[tuple, tuple[str, float]] = {}

# --------------- OpenCode 会话头与 base_url 归一化 ---------------
#
# SDK 总会在 base_url 后再拼一次协议路径：OpenAI SDK 拼 /chat/completions
# （responses 模式拼 /responses），Anthropic SDK 拼 /v1/messages。而 provider
# 文档列出的是"完整端点 URL"，直接粘贴会被二次拼接 —— 例如
# https://opencode.ai/zen/go/v1/chat/completions 会打到 .../chat/completions/chat/completions。
_PROTOCOL_SUFFIX_RE = re.compile(r"/(?:chat/completions|responses|messages)/?$", re.IGNORECASE)
_ANTHROPIC_BASE_SUFFIX_RE = re.compile(r"/(?:v1/messages|v1)/?$", re.IGNORECASE)
# OpenCode 网关域名：仅对它注入会话头，避免把 api_key 的哈希指纹送给第三方
_OPENCODE_HOST = "opencode.ai"


def _normalise_llm_base_url(base_url: str | None, provider: str = "openai") -> str | None:
    """剥掉 SDK 会重新拼接的后缀，得到 SDK 期望的 base URL。

    provider 决定剥哪一套后缀：anthropic 的 SDK 拼的是 ``/v1/messages``，所以
    以 ``/v1`` 结尾同样要剥，否则必然产生 ``/v1/v1/messages``。
    """
    if not base_url:
        return base_url
    stripped = str(base_url).rstrip("/")
    pattern = _ANTHROPIC_BASE_SUFFIX_RE if provider == "anthropic" else _PROTOCOL_SUFFIX_RE
    normalised = pattern.sub("", stripped)
    return normalised or base_url


def _is_opencode_host(base_url: str | None) -> bool:
    """是否为 OpenCode 网关（精确域名或其子域），拒绝后缀伪造。"""
    hostname = _provider_hostname(base_url)
    return bool(hostname) and (
        hostname == _OPENCODE_HOST or hostname.endswith(f".{_OPENCODE_HOST}")
    )


def _models_list_url(base_url: str | None) -> str:
    """构造模型列表端点 URL。

    先用 ``_normalise_llm_base_url`` 剥掉协议后缀：用户按文档粘贴的
    ``.../zen/go/v1/chat/completions`` 若不剥离会拼成
    ``.../chat/completions/v1/models`` → 404，模型下拉框直接空掉。
    """
    base = (_normalise_llm_base_url(base_url) or (base_url or "")).rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def _opencode_session_id(base_url: str | None, api_key: str | None) -> str:
    """生成稳定的会话标识，用于 ``x-opencode-session`` 路由与 prompt cache。

    只按协议后缀归一化（不区分 provider），使 ``.../v1`` 与
    ``.../v1/chat/completions`` 等粘贴形式落到同一 session；输出为 32 位十六进制，
    不泄露 api_key 本身。
    """
    seed = f"{_normalise_llm_base_url(base_url) or ''}|{api_key or ''}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _opencode_session_headers(base_url: str | None, api_key: str | None) -> dict:
    """OpenCode 端点需要的请求头；其它 provider 返回空字典。"""
    if not _is_opencode_host(base_url):
        return {}
    return {"x-opencode-session": _opencode_session_id(base_url, api_key)}


def _is_missing_session_error(exc: Exception) -> bool:
    """OpenCode Go 缺少 ``x-opencode-session`` 时的 400，属于配置问题而非协议错配。"""
    if getattr(exc, "status_code", None) != 400:
        return False
    body = getattr(exc, "body", None)
    if body is None:
        response = getattr(exc, "response", None)
        body = getattr(response, "text", None) if response is not None else None
    text = str(body or "").lower()
    return "missingsessionid" in text or "x-opencode-session" in text


def _provider_hostname(base_url: str | None) -> str:
    """Extract a normalized hostname for exact provider capability matching."""
    raw = str(base_url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    return (parsed.hostname or "").lower().rstrip(".")


def _detect_provider(base_url: str) -> str:
    """根据 base_url 判断 LLM 提供商类型：'anthropic' 或 'openai'。"""
    if not base_url:
        return "openai"
    lower = base_url.lower()
    hostname = _provider_hostname(base_url)
    path = urlsplit(lower if "://" in lower else f"//{lower}").path
    if hostname == "api.anthropic.com" or "/anthropic" in path:
        return "anthropic"
    return "openai"


def _provider_for_api_format(api_format: str | None) -> str | None:
    """将协议格式映射为 SDK provider；OpenAI 的两种格式共用一个 SDK。"""
    if api_format == "anthropic":
        return "anthropic"
    if api_format in ("chat", "responses"):
        return "openai"
    return None


def _normalise_api_format(value: str | None) -> str:
    value = (value or "auto").strip().lower()
    return value if value in ("auto", *_SUPPORTED_API_FORMATS) else "auto"


def _endpoint_api_format_hint(base_url: str | None, model: str | None = None) -> str | None:
    """仅从明确的 endpoint/provider 线索推断格式，不把普通域名当作事实。"""
    lower = (base_url or "").lower().rstrip("/")
    path = urlsplit(lower if "://" in lower else f"//{lower}").path
    if (
        _provider_hostname(base_url) == "api.anthropic.com"
        or "/anthropic" in path
        or "/messages" in path
    ):
        return "anthropic"
    if "/responses" in path:
        return "responses"
    if "/chat/completions" in path:
        return "chat"
    return None


def _api_format_override() -> str:
    """接口格式应急开关：chat / responses / anthropic / auto（默认）。"""
    return os.environ.get("LLM_API_FORMAT", "auto").strip().lower()


def _explicit_api_format(
    base_url: str | None = None, user_id: int | None = None, llm_scope: str = "user"
) -> str | None:
    """返回用户/环境明确指定的格式；auto 和无效值返回 None。"""
    if user_id is not None and llm_scope != "global":
        try:
            from app.core.config import get_user_llm_config

            configured = _normalise_api_format(
                (get_user_llm_config(user_id) or {}).get("api_format")
            )
            if configured != "auto":
                return configured
        except Exception:
            pass
    override = _normalise_api_format(_api_format_override())
    return override if override != "auto" else None


def llm_config_fingerprint(cfg: dict | None) -> tuple:
    """生成会影响连通性/协议选择的配置指纹。"""
    cfg = cfg or {}
    return (
        cfg.get("api_key"),
        cfg.get("base_url"),
        cfg.get("model"),
        _normalise_api_format(cfg.get("api_format")),
    )


def clear_api_format_cache(base_url: str | None = None, model: str | None = None):
    """清理自动协议探测缓存；传 endpoint/model 时只清理匹配项。"""
    if base_url is None and model is None:
        _api_format_cache.clear()
        return
    for key in list(_api_format_cache):
        if (base_url is None or key[1] == base_url) and (model is None or key[2] == model):
            _api_format_cache.pop(key, None)


# --------------- 供应商能力矩阵 ---------------

_PROVIDER_CAPABILITIES: list[tuple[str, dict]] = [
    (
        "token-plan-cn.xiaomimimo.com",
        {
            "json_mode": False,
            "max_output_tokens": 4096,
            "api_formats": ["chat", "responses"],
            "prompt_cache_key": False,
        },
    ),
    (
        "opencode.ai",
        {
            # 2026-09-27 实测：hy3 拒绝 response_format（400），mimo/glm/kimi 才支持
            # → 必须保持 False，统一走 prompt 指令降级。
            "json_mode": False,
            # 网关硬上限 131072（262144 会被 400 拒绝，且 BadRequestError 不在重试
            # 白名单里，超限即硬失败）。取 32768 覆盖常规长输出与思考预算，
            # 同时给 grok/gpt/deepseek 等无法验证的模型留足余量
            # （其 /responses 端点当时区域不可用）。
            "max_output_tokens": 32768,
            "api_formats": ["chat", "responses", "anthropic"],
            "prompt_cache_key": True,
        },
    ),
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
    """按 base_url 匹配供应商能力，未知端点回退保守默认值。"""
    if not base_url:
        return dict(_DEFAULT_CAPS)
    hostname = _provider_hostname(base_url)
    for prefix, caps in _PROVIDER_CAPABILITIES:
        if prefix == "*" or hostname == prefix:
            return dict(caps)
    return dict(_DEFAULT_CAPS)


def _has_named_provider_capability(base_url: str | None) -> bool:
    hostname = _provider_hostname(base_url)
    return any(prefix != "*" and hostname == prefix for prefix, _caps in _PROVIDER_CAPABILITIES)


def get_provider_formats(base_url: str = None) -> list[str]:
    """返回端点支持的接口格式列表（chat / responses / anthropic）。"""
    return list(get_provider_capabilities(base_url).get("api_formats", ["chat"]))


def _api_format_cache_key(api_key: str | None, base_url: str | None, model: str | None) -> tuple:
    return (api_key or "", base_url or "", model or "")


def _cache_api_format(
    api_key: str | None, base_url: str | None, model: str | None, api_format: str
):
    _api_format_cache[_api_format_cache_key(api_key, base_url, model)] = (
        api_format,
        time.time(),
    )


def _cached_api_format(api_key: str | None, base_url: str | None, model: str | None) -> str | None:
    cached = _api_format_cache.get(_api_format_cache_key(api_key, base_url, model))
    if not cached:
        return None
    if time.time() - cached[1] >= _API_FORMAT_CACHE_TTL:
        _api_format_cache.pop(_api_format_cache_key(api_key, base_url, model), None)
        return None
    return cached[0]


def _is_endpoint_mismatch(exc: Exception) -> bool:
    """只有明确的协议错配/路由不存在错误才允许探测下一个协议。"""
    status_code = getattr(exc, "status_code", None)
    if status_code not in (400, 404, 405, 415):
        return False
    body = getattr(exc, "body", None)
    if body is None:
        response = getattr(exc, "response", None)
        body = getattr(response, "text", None) if response is not None else None
    body_text = str(body or "").lower()
    if status_code == 400:
        # OpenCode Go 对"模型不支持该协议"返回 400 ModelProtocolUnsupported
        # （如 grok/gpt 打在 chat 端点上）→ 属于协议错配，应继续探测。
        # 其余 400（认证、参数、MissingSessionID）仍是致命错误。
        return "modelprotocolunsupported" in body_text
    model_not_found = "model" in body_text and any(
        marker in body_text
        for marker in (
            "not found",
            "not_found",
            "does not exist",
            "doesn't exist",
            "unknown",
            "invalid",
        )
    )
    return not model_not_found


async def _probe_api_format(client, model: str, timeout: float, api_format: str):
    """用不带工具/提示词的最小请求验证单一协议。"""
    wait_for = max(5, min(int(timeout or _PROBE_TIMEOUT), _PROBE_TIMEOUT))
    from app.services.upload_llm_accounting import call_provider_with_upload_ledger

    if api_format == "anthropic":
        request = lambda: client.messages.create(
            model=model, max_tokens=1, messages=[{"role": "user", "content": "ping"}]
        )
        provider = "anthropic"
    elif api_format == "responses":
        request = lambda: client.responses.create(
            model=model, input="ping", max_output_tokens=1
        )
        provider = "openai"
    else:
        request = lambda: client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "ping"}], max_tokens=1
        )
        provider = "openai"

    async def bounded_request():
        return await asyncio.wait_for(request(), timeout=wait_for)

    return await call_provider_with_upload_ledger(
        bounded_request, model=model, provider=provider
    )


async def resolve_api_format_async(
    client,
    model: str,
    timeout: float,
    base_url: str | None,
    provider: str,
    *,
    api_key: str | None = None,
    user_id: int | None = None,
    llm_scope: str = "user",
    _return_probe_error: bool = False,
) -> str | tuple[str, Exception | None, bool]:
    """解析协议：显式配置 → 缓存 → endpoint hint → 最小探测 → Chat。"""

    from app.services.upload_llm_accounting import current_upload_llm_context

    upload_context = current_upload_llm_context()
    if upload_context is not None:
        user_id = (
            upload_context.user_id
            if upload_context.credential_scope == "user"
            else None
        )
        llm_scope = upload_context.credential_scope
        credential = upload_context.credential
        if credential is not None:
            api_key = credential.api_key
            if credential.api_format:
                upload_context.api_format = credential.api_format
                return (
                    (credential.api_format, None, False)
                    if _return_probe_error
                    else credential.api_format
                )

    def result(api_format: str, probe_error: Exception | None = None, probed: bool = False):
        if upload_context is not None:
            upload_context.api_format = api_format
        if _return_probe_error:
            return api_format, probe_error, probed
        return api_format

    explicit = _explicit_api_format(base_url, user_id, llm_scope)
    if explicit:
        return result(explicit)
    if api_key is None and user_id is not None and llm_scope != "global":
        try:
            from app.core.config import get_user_llm_config

            api_key = (get_user_llm_config(user_id) or {}).get("api_key")
        except Exception:
            pass
    cached = _cached_api_format(api_key, base_url, model)
    if cached:
        return result(cached)
    hint = _endpoint_api_format_hint(base_url, model)
    if hint:
        _cache_api_format(api_key, base_url, model, hint)
        return result(hint)

    static_formats = get_provider_formats(base_url)
    if _has_named_provider_capability(base_url) and len(static_formats) == 1:
        detected = static_formats[0]
        _cache_api_format(api_key, base_url, model, detected)
        return result(detected)
    if _has_named_provider_capability(base_url) and "chat" in static_formats:
        _cache_api_format(api_key, base_url, model, "chat")
        return result("chat")

    candidates = ["anthropic"] if provider == "anthropic" else ["chat", "responses"]
    last_mismatch = None
    for candidate in candidates:
        try:
            await _probe_api_format(client, model, timeout, candidate)
        except Exception as exc:
            if _is_endpoint_mismatch(exc):
                last_mismatch = exc
                continue
            raise
        _cache_api_format(api_key, base_url, model, candidate)
        return result(candidate, probed=True)
    if last_mismatch:
        logger.warning("LLM endpoint did not advertise a supported protocol; falling back to chat")
    _cache_api_format(api_key, base_url, model, "chat")
    return result("chat", last_mismatch, probed=last_mismatch is not None)


def resolve_api_format(base_url: str = None, user_id: int = None, llm_scope: str = "user") -> str:
    """同步解析协议，供非 async 调用方复用同一能力矩阵。"""
    explicit = _explicit_api_format(base_url, user_id, llm_scope)
    if explicit:
        return explicit
    if base_url is None:
        from app.core.config import LLM_BASE_URL

        base_url = LLM_BASE_URL
    cached = _cached_api_format(None, base_url, None)
    if cached:
        return cached
    hint = _endpoint_api_format_hint(base_url)
    if hint:
        return hint
    formats = get_provider_formats(base_url)
    if "anthropic" in formats:
        return "anthropic"
    if "responses" in formats and "chat" not in formats:
        return "responses"
    return "chat"


def _json_mode_override() -> str:
    """应急开关：force-on / force-off / auto（默认）。"""
    return os.environ.get("LLM_JSON_MODE_OVERRIDE", "auto").strip().lower()
