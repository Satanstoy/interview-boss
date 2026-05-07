import os
import re
import json
import asyncio
import logging
from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APITimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.core.config import LLM_MODEL, LLM_TIMEOUT

logger = logging.getLogger("interview-boss")

client = AsyncOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL"),
    timeout=LLM_TIMEOUT
)


def rebuild_clients():
    """用 config 模块中的当前值重建 LLM 客户端（配置热更新时调用）"""
    global client
    from app.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_TIMEOUT as _TIMEOUT

    client = AsyncOpenAI(api_key=LLM_API_KEY or None, base_url=LLM_BASE_URL or None, timeout=_TIMEOUT)
    logger.info("LLM 客户端已重建")


# --------------- 提供商检测 ---------------

def _detect_provider(base_url: str) -> str:
    """根据 base_url 判断 LLM 提供商类型：'anthropic' 或 'openai'"""
    if not base_url:
        return "openai"
    lower = base_url.lower()
    if "anthropic" in lower:
        return "anthropic"
    return "openai"


def _should_use_response_format() -> bool:
    """判断当前配置的 LLM 端点是否支持 response_format 参数"""
    from app.core.config import LLM_BASE_URL
    return _detect_provider(LLM_BASE_URL) == "openai"


# --------------- JSON 提取 ---------------

def _extract_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON，兼容 markdown 代码块包裹的情况"""
    text = text.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1).strip())
    # 尝试找到第一个 { 到最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise json.JSONDecodeError("无法从 LLM 响应中提取 JSON", text, 0)


# --------------- LLM 调用 ---------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, APITimeoutError, asyncio.TimeoutError)),
    before_sleep=lambda retry_state: logger.warning(f"LLM 调用失败，第 {retry_state.attempt_number} 次重试: {retry_state.outcome.exception()}")
)
async def _call_llm_with_retry(prompt: str, system_msg: str = "你是一个后端和算法面试指导专家。", response_format: dict = None) -> str:
    """带指数退避重试 + 超时保护的 LLM 调用封装"""
    kwargs = dict(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    if response_format and _should_use_response_format():
        kwargs["response_format"] = response_format

    # B11: 仅使用客户端超时，移除多余的 asyncio.wait_for 双重超时
    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content.strip()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, APITimeoutError, asyncio.TimeoutError)),
    before_sleep=lambda retry_state: logger.warning(f"LLM 调用失败，第 {retry_state.attempt_number} 次重试: {retry_state.outcome.exception()}")
)
async def _call_llm_with_retry_messages(messages: list, **kwargs) -> str:
    """带重试的 LLM 调用，支持 multimodal messages（图片+文本）"""
    kwargs.setdefault('model', LLM_MODEL)
    response = await client.chat.completions.create(messages=messages, **kwargs)
    return response.choices[0].message.content.strip()
