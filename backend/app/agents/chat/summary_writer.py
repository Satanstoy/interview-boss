"""SummaryWriter: 生成结构化面试总结。"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Awaitable

from app.agents.chat.prompts import SUMMARY_WRITER_PROMPT


async def generate_summary(
    *,
    session_notes: str,
    asked_questions: list[str],
    message_count: int,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
) -> dict[str, Any]:
    """生成结构化面试总结。

    Returns:
        {"status": "success", "summary": dict, "markdown": str} 或
        {"status": "error", "error_code": "...", "message": "..."}
    """
    # 构建面试摘要
    transcript_summary = f"""## 面试概况
- 总轮数: {message_count}
- 已问题目: {len(asked_questions)} 个

## 讨论主题
{session_notes}

## 已问问题
{chr(10).join(f'- {q}' for q in asked_questions[-10:])}"""

    messages = [
        {"role": "system", "content": SUMMARY_WRITER_PROMPT},
        {"role": "user", "content": transcript_summary},
    ]

    try:
        raw = await llm_call(messages)
    except Exception as exc:
        return {
            "status": "error",
            "error_code": "summary_generation_failed",
            "message": f"LLM 调用失败: {exc}",
        }

    # 解析 JSON
    try:
        # 尝试提取 JSON
        json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
        json_str = json_match.group(1) if json_match else raw
        # 尝试找到 JSON 对象
        if not json_match:
            obj_match = re.search(r"\{.*\}", raw, re.DOTALL)
            json_str = obj_match.group(0) if obj_match else raw

        summary = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return {
            "status": "error",
            "error_code": "summary_generation_failed",
            "message": f"JSON 解析失败: {raw[:100]}",
        }

    # 验证必备字段
    required_fields = ["overall_comment", "strongest_topic", "weakest_topic", "hiring_signal"]
    missing = [f for f in required_fields if f not in summary]
    if missing:
        return {
            "status": "error",
            "error_code": "summary_generation_failed",
            "message": f"总结缺少必备字段: {', '.join(missing)}",
        }

    # 渲染 Markdown
    markdown = _render_summary_markdown(summary)

    return {"status": "success", "summary": summary, "markdown": markdown}


def _render_summary_markdown(summary: dict[str, Any]) -> str:
    """将总结 dict 渲染为 Markdown。"""
    lines = [
        "## 面试总结",
        "",
        f"**整体表现**: {summary.get('overall_comment', '')}",
        "",
        f"**最佳话题**: {summary.get('strongest_topic', '')}",
        f"**薄弱环节**: {summary.get('weakest_topic', '')}",
        "",
        "**改进建议**:",
    ]

    for suggestion in summary.get("key_suggestions", []):
        lines.append(f"- {suggestion}")

    lines.extend([
        "",
        f"**综合评分**: {summary.get('score_estimate', 'N/A')}/10",
        f"**Hiring Signal**: {summary.get('hiring_signal', '')}",
        f"**主要风险**: {summary.get('risk_points', '无')}",
        "",
        "**下一轮追问**:",
    ])

    for question in summary.get("next_round_questions", []):
        lines.append(f"- {question}")

    return "\n".join(lines)
