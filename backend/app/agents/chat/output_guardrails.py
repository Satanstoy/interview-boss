"""Output guardrails for the interview chat agent.

Validates agent output before it reaches the user, ensuring:
- Closing paths produce structured summaries, not bare goodbyes.
- Counter question paths produce substantive answers, not topic pivots.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("interview-boss")

# ── Closing summary signals ──

_SUMMARY_SIGNALS = (
    "面试总结",
    "整体表现",
    "技术主题",
    "不足",
    "待观察",
    "后续流程",
    "技术亮点",
    "主要不足",
    "综合评价",
    "评估",
    "总结",
)

_BARE_CLOSING_PATTERNS = (
    "今天到这里",
    "再见",
    "感谢参加",
    "面试结束",
    "到这里吧",
    "先这样",
    "就到这里",
)


def validate_closing_summary(text: str) -> bool:
    """Return True if text looks like a structured closing summary.

    Requirements:
    - Must contain at least 2 summary signal words.
    - Must not be a bare goodbye.
    """
    if not text or len(text.strip()) < 20:
        return False

    stripped = text.strip()

    # Check for bare closing patterns (no real summary)
    bare_count = sum(1 for p in _BARE_CLOSING_PATTERNS if p in stripped)
    signal_count = sum(1 for s in _SUMMARY_SIGNALS if s in stripped)

    # If it's mostly bare closing with few signals, fail
    if bare_count > 0 and signal_count < 2:
        return False

    # Must have at least 2 summary signals
    return signal_count >= 2


def validate_counter_question_answer(
    text: str, user_message: str, counter_question_topic: str | None
) -> bool:
    """Return True if text substantively addresses the counter question.

    Requirements:
    - Must contain core technical words from the user's question or topic.
    - Must not be a pure topic pivot.
    """
    if not text or len(text.strip()) < 10:
        return False

    stripped = text.strip()

    # Extract core tokens from user message and topic
    user_tokens = _extract_core_tokens(user_message)
    topic_tokens = _extract_core_tokens(counter_question_topic or "")

    all_expected = user_tokens | topic_tokens
    if not all_expected:
        # No tokens to check against — pass by default
        return True

    text_lower = stripped.lower()
    matched = sum(1 for t in all_expected if t.lower() in text_lower)

    # At least 1 core token must appear in the answer
    return matched >= 1


_PIVOT_PHRASES = (
    "换个方向",
    "接着聊下一个",
    "下一个话题",
    "我们继续",
    "回到刚才",
)


def _is_pure_pivot(text: str) -> bool:
    """Return True if text is mostly a topic pivot without answering."""
    stripped = text.strip()
    if len(stripped) > 100:
        return False
    return any(phrase in stripped for phrase in _PIVOT_PHRASES)


def _extract_core_tokens(text: str) -> set[str]:
    """Extract 2-4 char Chinese words and English terms from text."""
    tokens = set()
    # Chinese 2-4 char words
    for match in re.finditer(r"[一-鿿]{2,4}", text):
        tokens.add(match.group())
    # English words (2+ chars)
    for match in re.finditer(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}", text):
        tokens.add(match.group())
    return tokens


def needs_output_repair(state: dict[str, Any], text: str) -> dict:
    """Check if the output needs repair.

    Returns:
        {"needs_repair": bool, "reason": str, "repair_type": str}
    """
    closing_stage = state.get("closing_stage", "technical")
    counter_question = bool(state.get("counter_question", False))

    # Check closing summary
    if closing_stage in ("final_summary", "closed"):
        if not validate_closing_summary(text):
            return {
                "needs_repair": True,
                "reason": "closing_summary_insufficient",
                "repair_type": "summary",
            }

    # Check counter question answer
    if counter_question:
        topic = state.get("counter_question_topic")
        if _is_pure_pivot(text):
            return {
                "needs_repair": True,
                "reason": "counter_question_pure_pivot",
                "repair_type": "counter_question",
            }
        if not validate_counter_question_answer(text, state.get("user_message", ""), topic):
            return {
                "needs_repair": True,
                "reason": "counter_question_not_addressed",
                "repair_type": "counter_question",
            }

    return {"needs_repair": False, "reason": "", "repair_type": ""}


def build_repair_prompt(
    original_text: str,
    state: dict[str, Any],
    repair_type: str,
) -> str:
    """Build a minimal repair prompt for the LLM.

    Only provides the current output, user question, and required rules.
    No tools are available during repair.
    """
    user_message = state.get("user_message", "")

    if repair_type == "summary":
        return (
            f"你的回复被检测为不够结构化。请重新生成一份面试总结。\n\n"
            f"要求：必须包含以下至少2项：面试总结、整体表现、技术主题、不足、待观察、后续流程。\n"
            f"候选人的最后消息：{user_message}\n"
            f"你之前的回复：{original_text}\n\n"
            f"请直接输出修改后的面试总结，不要解释。"
        )

    if repair_type == "counter_question":
        topic = state.get("counter_question_topic", "")
        return (
            f"你的回复被检测为没有实质回答候选人的反问。请重新回答。\n\n"
            f"候选人的问题：{user_message}\n"
            f"反问主题：{topic}\n"
            f"你之前的回复：{original_text}\n\n"
            f"要求：必须实质回应候选人的问题，不能只是切换话题。请直接输出修改后的回复。"
        )

    return original_text


def check_context_grounding(
    output: str,
    candidate_context: str,
    *,
    known_question_entities: list[str] | None = None,
) -> dict[str, Any]:
    """检查输出是否引入候选人未提及的实体。

    Args:
        output: 面试官输出文本
        candidate_context: 候选人上下文（自我介绍、简历、历史回答）
        known_question_entities: 题库题中提到的实体（允许引用）

    Returns:
        {"passed": bool, "reason": str, "unknown_entities": list[str]}
    """
    # 提取输出中的专有名词/项目名（中文大写开头 + 英文大写开头）
    output_entities = set(re.findall(r'[A-Z][a-zA-Z]+|[一-鿿]{2,4}(?:项目|系统|平台|框架)', output))

    # 构建已知实体集
    known_entities = set(re.findall(r'[A-Z][a-zA-Z]+|[一-鿿]{2,4}(?:项目|系统|平台|框架)', candidate_context))
    if known_question_entities:
        known_entities.update(known_question_entities)

    # 过滤常见技术术语（不是项目名）
    tech_terms = {
        "Redis", "MySQL", "Python", "Java", "Docker", "Kubernetes", "K8s",
        "LangChain", "LangGraph", "Faiss", "Elasticsearch", "Kafka", "RabbitMQ",
        "React", "Vue", "Angular", "Node", "Express", "FastAPI", "Flask",
        "PostgreSQL", "MongoDB", "SQLite", "GraphQL", "REST", "gRPC",
        "BERT", "GPT", "LLM", "RAG", "Agent", "MCP", "SSE", "WebSocket",
        "HNSW", "IVF", "LSM", "B+", "ACID", "CAP",
    }
    known_entities.update(tech_terms)

    # 检查未知实体
    unknown = []
    for entity in output_entities:
        if entity not in known_entities and len(entity) >= 3:
            unknown.append(entity)

    if unknown:
        return {
            "passed": False,
            "reason": f"输出引入候选人未提及的实体: {', '.join(unknown)}",
            "unknown_entities": unknown,
        }

    return {"passed": True, "reason": "", "unknown_entities": []}
