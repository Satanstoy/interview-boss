import os
import asyncio
import logging
from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APITimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.core.config import LLM_MODEL, LLM_TIMEOUT

logger = logging.getLogger("multimodal-parser")

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
