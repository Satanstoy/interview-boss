import os
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

client_of_embedding = AsyncOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY_EMBEDDING"),
    base_url=os.environ.get("OPENAI_BASE_URL_EMBEDDING"),
    timeout=60
)


def rebuild_clients():
    """用 config 模块中的当前值重建 LLM 客户端（配置热更新时调用）"""
    global client, client_of_embedding
    from app.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_TIMEOUT as _TIMEOUT
    from app.core.config import EMBEDDING_API_KEY, EMBEDDING_BASE_URL

    client = AsyncOpenAI(api_key=LLM_API_KEY or None, base_url=LLM_BASE_URL or None, timeout=_TIMEOUT)
    client_of_embedding = AsyncOpenAI(api_key=EMBEDDING_API_KEY or None, base_url=EMBEDDING_BASE_URL or None, timeout=60)
    logger.info("LLM 客户端已重建")


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
    if response_format:
        kwargs["response_format"] = response_format

    response = await asyncio.wait_for(
        client.chat.completions.create(**kwargs),
        timeout=LLM_TIMEOUT
    )
    return response.choices[0].message.content.strip()
