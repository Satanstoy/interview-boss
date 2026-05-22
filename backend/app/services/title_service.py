"""对话标题自动生成服务

模仿 DeepSeek/ChatGPT 的做法：
- 在用户发送第一条消息时，用轻量 LLM 调用提取/生成标题
- 短消息直接用作标题（零 LLM 成本）
- LLM 失败时降级为截断
- 标题限制在 20 字符以内
"""
import logging
from app.services.llm import _call_llm_with_retry

logger = logging.getLogger("interview-boss")

# 标题生成 Prompt（轻量、快速）
TITLE_PROMPT = """从以下用户消息中提取一个简短的对话标题（≤15个中文字）。
要求：
1. 提取核心话题/关键词
2. 用中文简洁表达
3. 不要加引号或标点
4. 直接返回标题文本，不要其他内容

用户消息: {message}

标题:"""

# 默认标题列表（触发重新生成的条件）
DEFAULT_TITLES = {"新对话", "JD定制面试", ""}

# 最大标题长度
MAX_TITLE_LENGTH = 20


def should_generate_title(title: str) -> bool:
    """判断是否需要生成标题（仅在标题为默认值时触发）"""
    return title in DEFAULT_TITLES


async def generate_title(message: str, user_id: int = None) -> str:
    """从用户消息生成对话标题

    Args:
        message: 用户的第一条消息
        user_id: 用户 ID（用于 LLM 客户端选择）

    Returns:
        简短的对话标题（≤20 字符）
    """
    if not message or not message.strip():
        return "新对话"

    message = message.strip()

    # 短消息直接用作标题（零 LLM 成本）
    if len(message) <= 10:
        return message

    # LLM 提取标题
    try:
        prompt = TITLE_PROMPT.format(message=message[:500])  # 限制输入长度
        result = await _call_llm_with_retry(
            prompt,
            system_msg="你是一个标题生成助手。从用户消息中提取简短的中文标题。只返回标题，不要其他内容。",
            user_id=user_id,
        )
        title = result.strip().strip('"').strip("'").strip("《》").strip()

        # 验证标题质量
        if title and len(title) <= MAX_TITLE_LENGTH and title != message:
            return title

        # LLM 返回了过长或无效的结果，截断
        if title:
            return title[:MAX_TITLE_LENGTH]

    except Exception as e:
        logger.warning(f"标题生成 LLM 调用失败，降级为截断: {e}")

    # 降级：截断消息作为标题
    return _truncate_title(message)


def _truncate_title(message: str) -> str:
    """截断消息作为标题（降级方案）"""
    # 在句子边界处截断
    for sep in ['。', '？', '！', '，', ' ', '\n']:
        idx = message.find(sep)
        if 0 < idx <= MAX_TITLE_LENGTH:
            return message[:idx]

    # 直接截断
    if len(message) > MAX_TITLE_LENGTH:
        return message[:MAX_TITLE_LENGTH - 1] + "…"

    return message
