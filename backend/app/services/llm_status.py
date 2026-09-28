"""LLM availability probing and configuration validation.

This module owns status-cache and provider-health policy while delegating
actual client construction to the compatibility service at call time.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
import anthropic as anthropic_mod

from app.services.llm_protocol import (
    _PROBE_TIMEOUT,
    _api_format_override,
    _detect_provider,
    _endpoint_api_format_hint,
    _is_endpoint_mismatch,
    _is_missing_session_error,
    _normalise_api_format,
    _provider_for_api_format,
    _SUPPORTED_API_FORMATS,
    get_provider_formats,
    llm_config_fingerprint,
    resolve_api_format_async,
)

logger = logging.getLogger("interview-boss")


def _service():
    """Resolve the request service lazily to avoid an import cycle."""
    from app.services import llm

    return llm


def _make_client(*args, **kwargs):
    return _service()._make_client(*args, **kwargs)


async def _probe_api_format(*args, **kwargs):
    return await _service()._probe_api_format(*args, **kwargs)


def get_llm_client_for_user(*args, **kwargs):
    return _service().get_llm_client_for_user(*args, **kwargs)


def get_user_llm_config(user_id):
    from app.core.config import get_user_llm_config as load_config

    return load_config(user_id)


# --------------- 模型可用性状态探测 ---------------

_LLM_STATUS_CACHE_TTL = 120  # 探测结果缓存秒数
_llm_status_cache: dict[int, tuple] = {}  # user_id -> (配置指纹, connected, error, 探测时间戳)


def clear_llm_status_cache(user_id: int = None):
    """清除用户模型状态探测缓存（配置更新后调用）"""
    if user_id is not None:
        _llm_status_cache.pop(user_id, None)
    else:
        _llm_status_cache.clear()


def _classify_probe_error(exc: Exception) -> str:
    """把探测异常归类为用户可读的错误信息"""
    status_code = getattr(exc, "status_code", None)
    if status_code in (401, 403):
        return "认证失败：请检查 API Key 是否正确"
    if status_code == 429:
        return "请求过于频繁：请稍后重试"
    if isinstance(exc, AuthenticationError) or isinstance(exc, anthropic_mod.AuthenticationError):
        return "认证失败：请检查 API Key 是否正确"
    if isinstance(exc, RateLimitError) or isinstance(exc, anthropic_mod.RateLimitError):
        return "请求过于频繁：请稍后重试"
    if (
        isinstance(exc, APITimeoutError)
        or isinstance(exc, anthropic_mod.APITimeoutError)
        or isinstance(exc, asyncio.TimeoutError)
    ):
        return "模型服务响应超时：请稍后重试"
    if isinstance(exc, APIConnectionError) or isinstance(exc, anthropic_mod.APIConnectionError):
        return "无法连接模型服务：请检查 Base URL"
    if _is_missing_session_error(exc):
        return "接口缺少会话标识：OpenCode Go 端点要求 x-opencode-session 请求头"
    if status_code == 404:
        return "模型服务未找到：请检查 Base URL 和模型名称"
    if status_code in (405, 415):
        return "接口不支持当前请求格式：请检查 Base URL 和接口类型"
    if status_code and status_code >= 500:
        return "模型服务暂时不可用：请稍后重试"
    return "模型服务异常：请检查 Base URL、模型名称和 API Key"


def _api_format_label(api_format: str) -> str:
    return {
        "chat": "Chat Completions",
        "responses": "Responses",
        "anthropic": "Anthropic Messages",
    }.get(api_format, api_format)


def _validation_candidates(base_url: str, requested_format: str) -> list[str]:
    """生成保存前探测顺序：用户选择优先，路由错配时再尝试其它协议。"""
    requested = _normalise_api_format(requested_format)
    hint = _endpoint_api_format_hint(base_url)
    candidates: list[str] = []
    preferred = [requested] if requested != "auto" else []
    preferred.extend([hint] if hint else [])
    if requested == "auto":
        preferred.extend(get_provider_formats(base_url))
    else:
        # 能力矩阵只用于排序，不阻止自定义网关的实际探测。
        preferred.extend(get_provider_formats(base_url))
    preferred.extend(_SUPPORTED_API_FORMATS)
    for candidate in preferred:
        if candidate in _SUPPORTED_API_FORMATS and candidate not in candidates:
            candidates.append(candidate)
    return candidates


async def validate_llm_api_format(
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float = 120,
    requested_format: str = "auto",
) -> dict:
    """探测未保存的 LLM 配置，并报告用户选择是否匹配真实协议。

    该函数不读取用户已保存的协议缓存，也不写入配置或自动探测缓存。只有
    404/405/415 才会继续尝试下一个协议；认证、限流、超时等错误立即返回，
    防止一次保存操作造成重复请求或重复计费。
    """
    requested = _normalise_api_format(requested_format)
    candidates = _validation_candidates(base_url, requested)
    last_mismatch: Exception | None = None

    for candidate in candidates:
        probe_client = None
        try:
            provider = _provider_for_api_format(candidate) or _detect_provider(base_url)
            probe_client = _make_client(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                provider=provider,
                api_format=candidate,
            )
            await _probe_api_format(probe_client, model, timeout, candidate)
        except Exception as exc:
            if _is_endpoint_mismatch(exc):
                last_mismatch = exc
                continue
            logger.warning("LLM configuration validation failed: %s", exc)
            return {
                "connected": False,
                "compatible": False,
                "requested_format": requested,
                "detected_format": None,
                "suggested_format": None,
                "model": model,
                "message": None,
                "error": _classify_probe_error(exc),
            }
        finally:
            if probe_client is not None:
                close = getattr(probe_client, "close", None)
                if close:
                    try:
                        close_result = close()
                        if inspect.isawaitable(close_result):
                            await close_result
                    except Exception as close_exc:
                        logger.warning("Failed to close temporary LLM client: %s", close_exc)

        compatible = requested == "auto" or requested == candidate
        if compatible:
            message = f"接口格式校验成功：{_api_format_label(candidate)}"
            suggested = None
        else:
            message = (
                f"检测到实际接口格式为 {_api_format_label(candidate)}，"
                "已为你切换建议格式，请再次保存确认"
            )
            suggested = candidate
        return {
            "connected": True,
            "compatible": compatible,
            "requested_format": requested,
            "detected_format": candidate,
            "suggested_format": suggested,
            "model": model,
            "message": message,
            "error": None,
        }

    mismatch_detail = "未检测到可用的 Chat / Responses / Anthropic 接口"
    if last_mismatch:
        logger.warning(
            "LLM configuration validation found no compatible protocol: %s",
            last_mismatch,
        )
    return {
        "connected": False,
        "compatible": False,
        "requested_format": requested,
        "detected_format": None,
        "suggested_format": None,
        "model": model,
        "message": mismatch_detail,
        "error": mismatch_detail,
    }


async def _probe_resolved(client, model, timeout, base_url, provider, user_id=None) -> tuple:
    """向给定的 client/model 发最小请求验证可用性，返回 (connected, error)。"""
    wait_for = max(5, min(int(timeout or _PROBE_TIMEOUT), _PROBE_TIMEOUT))
    try:
        api_format, probe_error, probed = await resolve_api_format_async(
            client,
            model=model,
            timeout=timeout,
            base_url=base_url,
            provider=provider,
            user_id=user_id,
            _return_probe_error=True,
        )
        if probe_error is not None:
            return False, _classify_probe_error(probe_error)
        if probed:
            return True, None
        if api_format == "anthropic":
            await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                ),
                timeout=wait_for,
            )
        elif api_format == "responses":
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
    resolved_client, model, timeout, base_url, provider = get_llm_client_for_user(user_id)
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
    configured_format = _normalise_api_format(cfg.get("api_format"))
    override_format = _normalise_api_format(_api_format_override())
    api_format = (
        configured_format
        if configured_format != "auto"
        else override_format
        if override_format != "auto"
        else None
    )
    provider = _provider_for_api_format(api_format) or _detect_provider(base_url)
    client = _make_client(
        cfg["api_key"],
        base_url,
        timeout,
        provider,
        api_format=api_format,
    )
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

    fingerprint = llm_config_fingerprint(cfg)
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
